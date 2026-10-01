"""Juez LLM independiente (Etapa 11).

Una llamada al LLM, separada de la del agente, que corre DESPUÉS de `analizar_recibo` y ANTES de
guardar o registrar. Verifica que los datos extraídos coincidan con la imagen y detecta texto impreso
dirigido al sistema (inyección dentro de la imagen). El código aplica el veredicto (ver
`app/agent.py`); el LLM del agente no lo dispara ni lo puede omitir.

Veredictos:

| Veredicto            | Criterio                                                          | Efecto (código)                      |
|----------------------|-------------------------------------------------------------------|--------------------------------------|
| `RECHAZAR`           | inyección en la imagen o un campo contradice la imagen             | bloqueo definitivo para ese recibo   |
| `PEDIR_CONFIRMACION` | dato ilegible/desconocido, confianza baja o duda razonable         | confirmación del usuario en un turno |
|                      |                                                                   | posterior (pendiente `juez`)         |
| `APROBAR`            | los campos coinciden y no hay texto dirigido al sistema            | se permite guardar y registrar       |

Independencia: la solicitud del juez contiene SOLO la imagen, los datos extraídos (como dato
delimitado) y su propio prompt (`JUDGE_PROMPT_v1`). Nunca recibe el historial de la conversación, el
mensaje del usuario ni el razonamiento del agente: la firma de `judge_receipt` no tiene dónde
entregárselos. La instrucción de sistema es `SECURITY_SCOPE_v2` + `JUDGE_PROMPT_v1` (la antepone
`LLMClient`); el prompt del juez define solo criterios de verificación y no repite el alcance.

Piso de señales en código: aunque el modelo devuelva `APROBAR`, una señal de inyección o de
contradicción sube el veredicto a `RECHAZAR` y un dato ilegible lo sube a `PEDIR_CONFIRMACION`.

Falla cerrada: si el juez no puede emitir un veredicto (error de la API, JSON inválido, esquema
inválido o imagen no admitida) el veredicto es `RECHAZAR` con la señal `juez_no_disponible`. Bloquea
guardar y registrar en esta ejecución, pero NO es un rechazo definitivo del recibo: el agente no lo
guarda como rechazado y el siguiente análisis vuelve a llamar al juez. No se usa `PEDIR_CONFIRMACION`
porque la confirmación del usuario saltaría el control justo cuando no pudo ejecutarse.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, ValidationError

from app.llm import JUDGE_TEMPERATURE, LLMCallError, LLMClient
from app.models import EventType, ReceiptData
from app.prompts import PROMPTS
from app.tools.analyzer import MAX_IMAGE_BYTES, detect_mime_type
from app.trace import Tracer

JUDGE_PROMPT_ID = "JUDGE_PROMPT_v1"
SCHEMA_NAME = "JudgeVerdict"
MAX_REASON_CHARS = 300

APROBAR = "APROBAR"
PEDIR_CONFIRMACION = "PEDIR_CONFIRMACION"
RECHAZAR = "RECHAZAR"
VERDICTS: tuple[str, ...] = (APROBAR, PEDIR_CONFIRMACION, RECHAZAR)

INJECTION = "inyeccion_en_imagen"
UNAVAILABLE = "juez_no_disponible"
CONTRADICTIONS: tuple[str, ...] = ("monto_no_coincide", "fecha_no_coincide", "comercio_no_coincide")
UNCERTAIN: tuple[str, ...] = ("dato_ilegible", "imagen_no_es_recibo")
SIGNALS: tuple[str, ...] = (INJECTION, *CONTRADICTIONS, *UNCERTAIN, "categoria_dudosa")

_SEVERITY = {APROBAR: 0, PEDIR_CONFIRMACION: 1, RECHAZAR: 2}

JudgeVeredicto = Literal["APROBAR", "PEDIR_CONFIRMACION", "RECHAZAR"]

# JSON Schema de la salida del juez (se envía como `response_json_schema`).
JUDGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "veredicto": {"type": "string", "enum": list(VERDICTS)},
        "motivo": {"type": "string", "description": "Frase breve que explica el veredicto."},
        "senales": {
            "type": "array",
            "items": {"type": "string", "enum": list(SIGNALS)},
            "description": "Señales detectadas; vacía si no hay ninguna.",
        },
    },
    "required": ["veredicto", "motivo", "senales"],
}


class JudgeVerdict(BaseModel):
    """Veredicto del juez sobre una extracción."""

    veredicto: JudgeVeredicto
    motivo: str = ""
    senales: list[str] = Field(default_factory=list)

    @property
    def unavailable(self) -> bool:
        """`True` si el juez no pudo ejecutarse (bloqueo de esta ejecución, no definitivo)."""
        return UNAVAILABLE in self.senales


def unavailable_verdict(reason: str) -> JudgeVerdict:
    """Veredicto de falla cerrada: bloquea esta ejecución sin rechazar el recibo para siempre."""
    return JudgeVerdict(
        veredicto=RECHAZAR,
        motivo=f"El juez no pudo verificar el recibo ({reason}); no se registra nada por ahora.",
        senales=[UNAVAILABLE],
    )


def apply_signal_floor(verdict: JudgeVerdict) -> JudgeVerdict:
    """Sube el veredicto cuando las señales lo exigen (el modelo no puede aprobar lo que él mismo marcó).

    Inyección o contradicción -> `RECHAZAR`; dato ilegible o imagen que no es un recibo ->
    `PEDIR_CONFIRMACION`. Nunca baja un veredicto.
    """
    floor = APROBAR
    if any(s in verdict.senales for s in UNCERTAIN):
        floor = PEDIR_CONFIRMACION
    if INJECTION in verdict.senales or any(s in verdict.senales for s in CONTRADICTIONS):
        floor = RECHAZAR
    if _SEVERITY[floor] > _SEVERITY[verdict.veredicto]:
        return verdict.model_copy(update={"veredicto": floor})
    return verdict


def _neutralize(text: str) -> str:
    return text.replace("<", "‹").replace(">", "›")


def build_judge_input(extracted: ReceiptData) -> str:
    """Texto de la solicitud: los datos extraídos como dato delimitado (nada más)."""
    payload = _neutralize(json.dumps(extracted.model_dump(), ensure_ascii=False))
    return (
        "Verifica estos datos extraídos contra la imagen adjunta.\n"
        f"<datos_extraidos>{payload}</datos_extraidos>"
    )


def parse_verdict(data: Any) -> JudgeVerdict:
    """Valida la salida del modelo, descarta señales desconocidas y acota el motivo.

    Raises:
        ValidationError: si el JSON no cumple el esquema.
    """
    verdict = JudgeVerdict.model_validate(data)
    signals = [s for s in dict.fromkeys(verdict.senales) if s in SIGNALS]
    return verdict.model_copy(
        update={"senales": signals, "motivo": " ".join(verdict.motivo.split())[:MAX_REASON_CHARS]}
    )


def _model_name(llm: LLMClient) -> Optional[str]:
    try:
        return llm.model
    except Exception:  # noqa: BLE001 - la traza no debe fallar por la configuración
        return None


def judge_receipt(
    image: Union[str, Path, bytes],
    extracted: ReceiptData,
    llm: LLMClient,
    tracer: Optional[Tracer] = None,
) -> JudgeVerdict:
    """Emite el veredicto del juez sobre `extracted` frente a `image`. Nunca lanza excepciones.

    Args:
        image: ruta o bytes de la imagen del recibo (JPEG, PNG o WebP).
        extracted: datos que `analizar_recibo` extrajo de esa imagen.
        llm: cliente LLM (aporta el bloque de alcance y la traza `LLM_DECISION`).
        tracer: recibe el evento `JUDGE_VERDICT`; por defecto el del cliente.

    Returns:
        el veredicto. Ante cualquier falla, `RECHAZAR` con la señal `juez_no_disponible`.
    """
    from google.genai import types

    tracer = tracer if tracer is not None else llm.tracer
    verdict: Optional[JudgeVerdict] = None
    reason = ""
    try:
        data = Path(image).read_bytes() if isinstance(image, (str, Path)) else bytes(image)
    except OSError:
        data, reason = b"", "imagen no legible"
    mime_type = detect_mime_type(data) if data else None
    if not reason and mime_type is None:
        reason = "formato de imagen no admitido"
    if not reason and len(data) > MAX_IMAGE_BYTES:
        reason = "imagen demasiado grande"
    if not reason:
        assert mime_type is not None
        try:
            result = llm.generate_structured(
                system_prompt_id=JUDGE_PROMPT_ID,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    build_judge_input(extracted),
                ],
                schema=JUDGE_JSON_SCHEMA,
                schema_name=SCHEMA_NAME,
                temperature=JUDGE_TEMPERATURE,
            )
        except LLMCallError as error:
            reason = f"falló la llamada al modelo, código {error.code}"
        else:
            if result.json_error is not None:
                reason = result.json_error
            else:
                try:
                    verdict = apply_signal_floor(parse_verdict(result.data))
                except ValidationError:
                    reason = "salida con esquema inválido"
    fallback = verdict is None
    if verdict is None:
        verdict = unavailable_verdict(reason or "sin veredicto")
    tracer.record(
        EventType.JUDGE_VERDICT,
        {
            "veredicto": verdict.veredicto,
            "motivo": verdict.motivo,
            "senales": list(verdict.senales),
            "prompt_id": JUDGE_PROMPT_ID,
            "model": _model_name(llm),
            "fallback": fallback,
        },
    )
    return verdict


# El texto del prompt vive en `app/prompts.py`; se reexporta para la documentación y el notebook.
JUDGE_PROMPT_TEXT = PROMPTS[JUDGE_PROMPT_ID]
