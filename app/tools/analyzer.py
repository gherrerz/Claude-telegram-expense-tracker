"""Tool `analizar_recibo`: extrae los datos de un recibo con el LLM con visión."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, Union

from pydantic import ValidationError

from app.llm import EXTRACTION_TEMPERATURE, LLMClient
from app.models import ALLOWED_CATEGORIES, UNKNOWN, EventType, ReceiptData
from app.trace import Tracer

ANALYZER_PROMPT_ID = "ANALYZER_PROMPT_v1"
SCHEMA_NAME = "ReceiptData"
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # el envío inline admite hasta ~20 MB

# JSON Schema equivalente a `ReceiptData` (se envía como `response_json_schema`).
RECEIPT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "fecha": {"type": "string", "description": "Fecha ISO YYYY-MM-DD o 'desconocido'."},
        "comercio": {"type": "string", "description": "Nombre del comercio o 'desconocido'."},
        "monto": {
            "anyOf": [{"type": "number"}, {"type": "string", "enum": [UNKNOWN]}],
            "description": "Total pagado, sin separadores, o 'desconocido'.",
        },
        "categoria": {"type": "string", "enum": [*ALLOWED_CATEGORIES, UNKNOWN]},
        "confianza": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["fecha", "comercio", "monto", "categoria", "confianza"],
}


def safe_receipt() -> ReceiptData:
    """Resultado seguro: todo "desconocido" y confianza 0 (nunca inventa datos)."""
    return ReceiptData(
        fecha=UNKNOWN, comercio=UNKNOWN, monto=UNKNOWN, categoria=UNKNOWN, confianza=0.0
    )


def detect_mime_type(data: bytes) -> Optional[str]:
    """Tipo MIME según los primeros bytes; `None` si no es una imagen admitida."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate(data: object) -> ReceiptData:
    """Valida con Pydantic y comprueba que la fecha sea ISO o "desconocido"."""
    receipt = ReceiptData.model_validate(data)
    if receipt.fecha != UNKNOWN:
        date.fromisoformat(receipt.fecha)  # ValueError si no es ISO
    return receipt


def analizar_recibo(
    image_path_or_bytes: Union[str, Path, bytes],
    llm: Optional[LLMClient] = None,
    tracer: Optional[Tracer] = None,
    temperature: float = EXTRACTION_TEMPERATURE,
) -> ReceiptData:
    """Extrae fecha, comercio, monto, categoría y confianza de un recibo.

    Si un dato no es legible, su valor es "desconocido": nunca se estima. Ante
    una imagen no admitida, JSON inválido o datos que no cumplen el esquema,
    devuelve un resultado seguro (todo "desconocido", confianza 0) y lo traza.

    Args:
        image_path_or_bytes: ruta de la imagen o sus bytes (JPEG, PNG o WebP).
        llm: cliente LLM; si se omite se crea uno con la configuración del entorno.
        tracer: trazador; por defecto el del cliente LLM.
        temperature: temperatura de la llamada (ver `EXTRACTION_TEMPERATURE`).

    Raises:
        FileNotFoundError: si la ruta no existe.
        LLMCallError: si la API falla tras agotar los reintentos.
    """
    from google.genai import types

    llm = llm if llm is not None else LLMClient(tracer=tracer)
    tracer = tracer if tracer is not None else llm.tracer

    if isinstance(image_path_or_bytes, (str, Path)):
        path = Path(image_path_or_bytes)
        data = path.read_bytes()
        source = path.name
    else:
        data = bytes(image_path_or_bytes)
        source = "bytes"

    mime_type = detect_mime_type(data)
    tracer.record(
        EventType.TOOL_CALL,
        {
            "tool": "analizar_recibo",
            "source": source,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "prompt_id": ANALYZER_PROMPT_ID,
            "temperature": temperature,
        },
    )

    def finish(receipt: ReceiptData, fallback: bool, reason: Optional[str] = None) -> ReceiptData:
        tracer.record(
            EventType.TOOL_RESULT,
            {
                "tool": "analizar_recibo",
                "ok": not fallback,
                "fallback": fallback,
                "reason": reason,
                "result": receipt.model_dump(),
            },
        )
        return receipt

    if mime_type is None:
        return finish(safe_receipt(), True, "formato de imagen no admitido")
    if len(data) > MAX_IMAGE_BYTES:
        return finish(safe_receipt(), True, "imagen demasiado grande")

    part = types.Part.from_bytes(data=data, mime_type=mime_type)
    result = llm.generate_structured(
        system_prompt_id=ANALYZER_PROMPT_ID,
        contents=[part, "Extrae los datos de este recibo."],
        schema=RECEIPT_JSON_SCHEMA,
        schema_name=SCHEMA_NAME,
        temperature=temperature,
    )
    if result.json_error is not None:
        return finish(safe_receipt(), True, result.json_error)
    try:
        receipt = _validate(result.data)
    except (ValidationError, ValueError) as error:
        # Solo se registra el tipo de error, no el contenido devuelto por el modelo.
        return finish(safe_receipt(), True, f"validación fallida: {type(error).__name__}")
    return finish(receipt, False)
