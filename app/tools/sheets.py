"""Tool `registrar_gasto`: agrega una fila de gasto en la planilla de prueba de Google Sheets.

Reglas (aplicadas en código, no en el prompt):
- Validación previa a cualquier llamada a la API: categoría permitida, monto
  numérico positivo, fecha ISO real, comercio no vacío y URL de Drive (https y
  host `drive.google.com`). Si algo falla no se hace ninguna llamada de red.
- Solo agrega filas (`values.append`). Nunca usa `update`, `clear` ni `delete`.
- Repetible con seguridad (mecanismo del bono): antes de escribir se leen las
  filas existentes y, si ya hay una con la misma fecha, comercio normalizado y
  monto, no se escribe y se devuelve `duplicate=True` con la fila existente.
  Por defecto SIEMPRE rige. Solo `permitir_duplicado=True` (Etapa 10) omite esa
  comprobación, y el agente lo pasa únicamente tras una confirmación explícita del
  usuario en un turno posterior (ver `app/agent.py`); nunca lo decide el LLM.
- `row_number` sale de `updates.updatedRange` de la respuesta de la API; nunca
  se calcula contando filas antes de escribir.
- Nunca lanza excepciones al agente: devuelve `SheetResult(success=False, error=...)`
  con un mensaje seguro (sin rutas, tokens ni detalles internos).

Referencia oficial de `values.append`:
https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append

Limitación conocida: la lectura y el append no son atómicos; dos ejecuciones
simultáneas podrían duplicar. El agente es de un solo hilo, así que se acepta.
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Optional
from urllib.parse import urlparse

from googleapiclient.errors import HttpError

from app.config import Settings, load_settings
from app.google_auth import GoogleAuthError, build_sheets_service
from app.models import ALLOWED_CATEGORIES, UNKNOWN, EventType, SheetResult
from app.trace import Tracer

TOOL_NAME = "registrar_gasto"
SHEET_RANGE = "A:E"  # sin nombre de hoja: se refiere a la primera hoja
DRIVE_HOST = "drive.google.com"
MAX_MERCHANT_LENGTH = 200
AMOUNT_TOLERANCE = 0.005

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Fila final de `updatedRange`, p. ej. `Hoja 1!A7:E7` o `'Gastos ''2026'''!A7:E7`.
_ROW_RE = re.compile(r"^\$?[A-Za-z]+\$?(\d+)")


def normalize_merchant(text: object) -> str:
    """Normaliza el comercio para comparar: minúsculas y espacios colapsados."""
    return " ".join(str(text).split()).casefold()


def _parse_amount(value: object) -> Optional[float]:
    """Devuelve el monto como float finito o `None` si no es numérico."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() == UNKNOWN:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def validate_expense(
    fecha: object, comercio: object, monto: object, categoria: object, recibo_url: object
) -> tuple[Optional[list[Any]], Optional[str]]:
    """Valida los datos del gasto antes de escribir.

    Returns:
        `(fila, None)` con la fila ya normalizada `[fecha, comercio, monto, categoria, url]`
        o `(None, mensaje)` con el primer motivo de rechazo.
    """
    if categoria not in ALLOWED_CATEGORIES:  # "desconocido" tampoco se admite
        return None, f"Categoría no permitida; use una de {', '.join(ALLOWED_CATEGORIES)}."

    amount = _parse_amount(monto)
    if amount is None or amount <= 0:
        return None, "El monto debe ser un número positivo."

    if not isinstance(fecha, str) or not _ISO_DATE_RE.match(fecha.strip()):
        return None, "La fecha debe tener formato ISO AAAA-MM-DD."
    try:
        date.fromisoformat(fecha.strip())
    except ValueError:
        return None, "La fecha no es un día válido del calendario."

    merchant = " ".join(str(comercio).split()) if isinstance(comercio, str) else ""
    if not merchant or merchant.casefold() == UNKNOWN:
        return None, "El comercio no puede estar vacío ni ser 'desconocido'."
    if len(merchant) > MAX_MERCHANT_LENGTH:
        return None, f"El comercio excede {MAX_MERCHANT_LENGTH} caracteres."

    if not isinstance(recibo_url, str):
        return None, "La URL del recibo debe provenir de Google Drive (https://drive.google.com/...)."
    try:
        parsed = urlparse(recibo_url.strip())
        host, port, user = parsed.hostname, parsed.port, parsed.username
    except ValueError:
        return None, "La URL del recibo no es válida."
    if parsed.scheme != "https" or host != DRIVE_HOST or port is not None or user is not None:
        return None, "La URL del recibo debe provenir de Google Drive (https://drive.google.com/...)."

    stored_amount: float | int = int(amount) if amount.is_integer() else amount
    return [fecha.strip(), merchant, stored_amount, categoria, recibo_url.strip()], None


def parse_row_number(updated_range: object) -> Optional[int]:
    """Extrae el número de la primera fila de un rango A1 (`Hoja!A7:E7` -> 7).

    Soporta nombres de hoja con espacios, comillas simples (escapadas duplicadas)
    y signos `!`, porque se usa la última aparición de `!` como separador.
    """
    if not isinstance(updated_range, str) or not updated_range:
        return None
    cells = updated_range.rsplit("!", 1)[-1]
    match = _ROW_RE.match(cells)
    return int(match.group(1)) if match else None


def _http_error_message(error: HttpError) -> str:
    status = getattr(getattr(error, "resp", None), "status", None)
    hints = {
        401: "credenciales rechazadas; vuelve a ejecutar scripts/google_auth.py",
        403: "permiso denegado o API de Sheets no habilitada; revisa docs/setup_google.md",
        404: "planilla no encontrada o no visible para la aplicación; verifica SHEET_ID",
        429: "límite de uso de la API; reintenta más tarde",
    }
    detail = hints.get(status, "error de la API")
    return f"Sheets respondió HTTP {status if status is not None else '?'}: {detail}"


def _cell_text(row: list[Any], index: int) -> str:
    return str(row[index]) if index < len(row) and row[index] is not None else ""


def find_duplicate_row(rows: list[list[Any]], data_row: list[Any]) -> Optional[int]:
    """Busca en `rows` (A:E, fila 1 = encabezado) una fila equivalente a `data_row`.

    Equivalente = misma fecha, mismo comercio normalizado y mismo monto (comparación
    numérica). Devuelve el número de fila de la hoja (1-indexado) o `None`.
    """
    fecha, comercio, monto = data_row[0], normalize_merchant(data_row[1]), float(data_row[2])
    for position, row in enumerate(rows[1:], start=2):  # la fila 1 es el encabezado
        if _cell_text(row, 0).strip() != fecha:
            continue
        if normalize_merchant(_cell_text(row, 1)) != comercio:
            continue
        existing = _parse_amount(row[2]) if len(row) > 2 else None
        if existing is not None and abs(existing - monto) < AMOUNT_TOLERANCE:
            return position
    return None


def _read_rows(service: Any, spreadsheet_id: str) -> list[list[Any]]:
    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=SHEET_RANGE,
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    values = response.get("values") if isinstance(response, dict) else None
    return values if isinstance(values, list) else []


def get_sheet_snapshot(service: Any, settings: Settings) -> dict[str, Any]:
    """Evidencia de solo lectura del estado de la planilla.

    Returns:
        `{"row_count": filas de datos sin contar el encabezado, "last_row": [...] | None}`.
        Se ignoran las filas totalmente vacías. Los errores de la API se propagan:
        es un auxiliar de verificación, no una tool del agente.
    """
    rows = _read_rows(service, settings.sheet_id or "")
    data_rows = [row for row in rows[1:] if any(str(cell).strip() for cell in row)]
    return {
        "row_count": len(data_rows),
        "last_row": list(data_rows[-1]) if data_rows else None,
    }


def registrar_gasto(
    fecha: object,
    comercio: object,
    monto: object,
    categoria: object,
    recibo_url: object,
    service: Optional[Any] = None,
    tracer: Optional[Tracer] = None,
    settings: Optional[Settings] = None,
    permitir_duplicado: bool = False,
) -> SheetResult:
    """Agrega un gasto a la planilla de prueba, validando antes y sin duplicar.

    Args:
        fecha: fecha ISO `AAAA-MM-DD` del recibo.
        comercio: nombre del comercio (no vacío, distinto de "desconocido").
        monto: monto numérico positivo.
        categoria: una de las categorías permitidas.
        recibo_url: enlace de Drive (https, host `drive.google.com`) devuelto por `guardar_recibo`.
        service: cliente de Sheets v4; si se omite se crea con el token OAuth local.
        tracer: trazador; por defecto uno silencioso.
        settings: configuración; si se omite se lee del entorno.
        permitir_duplicado: con `True` (solo ese valor exacto) se omite la deduplicación y la
            fila se agrega aunque ya exista una equivalente. Por defecto `False`: la llamada
            sigue siendo idempotente. La validación de los datos no se omite nunca.

    Returns:
        `SheetResult`. Éxito: `success=True` y `row_number` tomado de la API.
        Duplicado: `success=False`, `duplicate=True` y `row_number` de la fila existente
        (no se escribe nada). Otro fallo: `success=False` y `error` seguro. Nunca lanza.
    """
    tracer = tracer if tracer is not None else Tracer(console=False, write_file=False)
    tracer.record(
        EventType.TOOL_CALL,
        {
            "tool": TOOL_NAME,
            "fecha": fecha if isinstance(fecha, str) else str(type(fecha).__name__),
            "comercio": str(comercio)[:MAX_MERCHANT_LENGTH],
            "monto": monto if isinstance(monto, (int, float, str)) else str(type(monto).__name__),
            "categoria": categoria if isinstance(categoria, str) else str(type(categoria).__name__),
            "recibo_url": recibo_url if isinstance(recibo_url, str) else str(type(recibo_url).__name__),
            **({"permitir_duplicado": True} if permitir_duplicado is True else {}),
        },
    )

    def finish(result: SheetResult) -> SheetResult:
        tracer.record(
            EventType.TOOL_RESULT,
            {"tool": TOOL_NAME, "ok": result.success, "result": result.model_dump()},
        )
        return result

    def fail(message: str) -> SheetResult:
        return finish(SheetResult(success=False, error=message))

    row, problem = validate_expense(fecha, comercio, monto, categoria, recibo_url)
    if row is None:
        return fail(f"Datos inválidos, no se escribió nada: {problem}")

    try:
        settings = settings if settings is not None else load_settings()
    except Exception:  # noqa: BLE001 - configuración inválida: no se detalla
        return fail("Configuración inválida; revisa .env y .env.example.")
    if not settings.sheet_id:
        return fail("Falta SHEET_ID; ejecuta scripts/setup_google_resources.py y complétalo en .env.")

    if service is None:
        try:
            service = build_sheets_service(settings, interactive=False)
        except GoogleAuthError as error:
            return fail(str(error))
        except Exception:  # noqa: BLE001 - no se filtran detalles internos
            return fail("No se pudo crear el cliente de Sheets con las credenciales locales.")

    existing_row: Optional[int] = None
    if permitir_duplicado is not True:  # solo el valor exacto True omite la deduplicación
        try:
            existing_row = find_duplicate_row(_read_rows(service, settings.sheet_id), row)
        except HttpError as error:
            return fail(_http_error_message(error))
        except Exception as error:  # noqa: BLE001 - red u otros fallos: solo el tipo
            return fail(f"Falló la lectura de la planilla ({type(error).__name__}).")
    if existing_row is not None:
        return finish(
            SheetResult(
                success=False,
                duplicate=True,
                row_number=existing_row,
                error="Gasto duplicado (misma fecha, comercio y monto); no se escribió nada.",
            )
        )

    try:
        response = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=settings.sheet_id,
                range=SHEET_RANGE,
                # RAW: los valores se guardan tal cual. Con USER_ENTERED un comercio que
                # empiece con "=" se evaluaría como fórmula y la fecha ISO se convertiría
                # en fecha serial. Con RAW el monto enviado como número JSON sigue siendo numérico.
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            )
            .execute()
        )
    except HttpError as error:
        return fail(_http_error_message(error))
    except Exception as error:  # noqa: BLE001 - red u otros fallos: solo el tipo
        return fail(f"Falló el registro en la planilla ({type(error).__name__}).")

    updates = response.get("updates") if isinstance(response, dict) else None
    row_number = parse_row_number(updates.get("updatedRange") if isinstance(updates, dict) else None)
    if row_number is None:
        return fail("La API de Sheets no devolvió el rango actualizado (updatedRange).")
    return finish(SheetResult(success=True, row_number=row_number))
