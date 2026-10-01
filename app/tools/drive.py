"""Tool `guardar_recibo`: sube la imagen de un recibo a la carpeta de prueba de Drive.

Reglas:
- Sube solo a `DRIVE_FOLDER_ID` (campo `parents`).
- `web_view_link` sale únicamente de la respuesta de la API (`webViewLink`);
  nunca se construye a mano.
- Nunca lanza excepciones al agente: ante credenciales ausentes, configuración
  incompleta o error de la API devuelve `DriveResult(success=False, error=...)`
  con un mensaje seguro (sin rutas, tokens ni detalles internos).
"""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional, Union

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from app.config import Settings, load_settings
from app.google_auth import GoogleAuthError, build_drive_service
from app.models import UNKNOWN, DriveResult, EventType
from app.tools.analyzer import MAX_IMAGE_BYTES, detect_mime_type
from app.trace import Tracer

TOOL_NAME = "guardar_recibo"
MAX_PART_LENGTH = 40  # largo máximo de cada parte normalizada del nombre
MAX_DATE_LENGTH = 12  # admite una fecha ISO (10) o "desconocido" (11)
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def normalize_name_part(text: object, max_length: int = MAX_PART_LENGTH) -> str:
    """Normaliza una parte del nombre de archivo.

    Minúsculas, sin acentos, todo carácter no alfanumérico pasa a `_`, los
    guiones bajos repetidos se colapsan y se recorta a `max_length`. Si no
    queda nada, devuelve "desconocido".
    """
    raw = "" if text is None else str(text)
    ascii_text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    cleaned = cleaned[:max_length].strip("_")
    return cleaned or UNKNOWN


def build_file_name(comercio: object, fecha: object, mime_type: str = "image/jpeg") -> str:
    """Nombre `recibo_{comercio}_{fecha}.{ext}` normalizado (ext según el tipo MIME)."""
    extension = _EXTENSIONS.get(mime_type, "jpg")
    return f"recibo_{normalize_name_part(comercio)}_{normalize_name_part(fecha, MAX_DATE_LENGTH)}.{extension}"


def _http_error_message(error: HttpError) -> str:
    status = getattr(getattr(error, "resp", None), "status", None)
    hints = {
        401: "credenciales rechazadas; vuelve a ejecutar scripts/google_auth.py",
        403: "permiso denegado o API no habilitada; revisa docs/setup_google.md",
        404: "carpeta no encontrada o no visible para la aplicación; verifica DRIVE_FOLDER_ID",
        429: "límite de uso de la API; reintenta más tarde",
    }
    detail = hints.get(status, "error de la API")
    return f"Drive respondió HTTP {status if status is not None else '?'}: {detail}"


def guardar_recibo(
    image_path_or_bytes: Union[str, Path, bytes],
    comercio: object,
    fecha: object,
    service: Optional[Any] = None,
    tracer: Optional[Tracer] = None,
    settings: Optional[Settings] = None,
) -> DriveResult:
    """Sube la imagen del recibo a la carpeta de prueba de Drive.

    Args:
        image_path_or_bytes: ruta de la imagen o sus bytes (JPEG, PNG o WebP).
        comercio: comercio extraído del recibo (puede ser "desconocido").
        fecha: fecha ISO extraída del recibo (puede ser "desconocido").
        service: cliente de Drive v3; si se omite se crea con el token OAuth local.
        tracer: trazador; por defecto uno silencioso (sin consola ni archivo).
        settings: configuración; si se omite se lee del entorno.

    Returns:
        `DriveResult` con `file_id`, `file_name` y `web_view_link` tomados de la
        respuesta de la API. Si algo falla, `success=False` y `error` con un
        mensaje seguro. Nunca lanza excepciones.
    """
    tracer = tracer if tracer is not None else Tracer(console=False, write_file=False)

    def finish(result: DriveResult) -> DriveResult:
        tracer.record(
            EventType.TOOL_RESULT,
            {"tool": TOOL_NAME, "ok": result.success, "result": result.model_dump()},
        )
        return result

    def fail(message: str) -> DriveResult:
        return finish(DriveResult(success=False, error=message))

    try:
        if isinstance(image_path_or_bytes, (str, Path)):
            path = Path(image_path_or_bytes)
            data = path.read_bytes()
            source = path.name
        else:
            data = bytes(image_path_or_bytes)
            source = "bytes"
    except OSError:
        tracer.record(EventType.TOOL_CALL, {"tool": TOOL_NAME, "source": "ilegible"})
        return fail("No se pudo leer la imagen del recibo.")

    mime_type = detect_mime_type(data)
    file_name = build_file_name(comercio, fecha, mime_type or "image/jpeg")
    tracer.record(
        EventType.TOOL_CALL,
        {
            "tool": TOOL_NAME,
            "source": source,
            "file_name": file_name,
            "mime_type": mime_type,
            "size_bytes": len(data),
        },
    )

    if mime_type is None:
        return fail("Formato de imagen no admitido (se espera JPEG, PNG o WebP).")
    if len(data) > MAX_IMAGE_BYTES:
        return fail("La imagen es demasiado grande para subirla.")

    try:
        settings = settings if settings is not None else load_settings()
    except Exception:  # noqa: BLE001 - configuración inválida: no se detalla
        return fail("Configuración inválida; revisa .env y .env.example.")
    if not settings.drive_folder_id:
        return fail("Falta DRIVE_FOLDER_ID; ejecuta scripts/setup_google_resources.py y complétalo en .env.")

    if service is None:
        try:
            service = build_drive_service(settings, interactive=False)
        except GoogleAuthError as error:
            return fail(str(error))
        except Exception:  # noqa: BLE001 - no se filtran detalles internos
            return fail("No se pudo crear el cliente de Drive con las credenciales locales.")

    try:
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        response = (
            service.files()
            .create(
                body={"name": file_name, "parents": [settings.drive_folder_id]},
                media_body=media,
                fields="id,name,webViewLink",
            )
            .execute()
        )
    except HttpError as error:
        return fail(_http_error_message(error))
    except Exception as error:  # noqa: BLE001 - red u otros fallos: solo el tipo
        return fail(f"Falló la subida a Drive ({type(error).__name__}).")

    file_id = response.get("id") if isinstance(response, dict) else None
    if not file_id:
        return fail("La API de Drive no devolvió un file_id.")
    return finish(
        DriveResult(
            success=True,
            file_id=file_id,
            file_name=response.get("name") or file_name,
            web_view_link=response.get("webViewLink"),  # solo de la API; nunca construido
        )
    )


def verify_file_exists(file_id: str, service: Any) -> Optional[dict]:
    """Consulta `files.get` y devuelve los metadatos, o `None` si el archivo no existe (404).

    Otros errores de la API se propagan: es un auxiliar de verificación, no una
    tool del agente.
    """
    try:
        return (
            service.files()
            .get(fileId=file_id, fields="id,name,mimeType,parents,trashed,webViewLink")
            .execute()
        )
    except HttpError as error:
        if getattr(getattr(error, "resp", None), "status", None) == 404:
            return None
        raise
