"""Prueba en vivo de la Etapa 5 (Drive y Sheets reales, OAuth de usuario).

Se omite sola si faltan DRIVE_FOLDER_ID, SHEET_ID o el archivo de token. Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage5_live.py -v
Flujo: estado ANTES -> sube el recibo -> `registrar_gasto` -> estado DESPUÉS (+1 fila)
-> repite la misma llamada -> duplicado y conteo sin cambios. El comercio lleva una marca de
tiempo UTC para que cada ejecución use una fila nueva (la planilla es de prueba).
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import config_status, load_settings
from app.google_auth import build_drive_service, build_sheets_service, token_exists
from app.tools.drive import guardar_recibo
from app.tools.sheets import get_sheet_snapshot, registrar_gasto
from app.trace import Tracer

pytestmark = pytest.mark.live

RECEIPT = Path(__file__).resolve().parents[1] / "data" / "receipts" / "receipt_normal.jpg"


def _skip_reason():
    status = config_status()
    for name in ("DRIVE_FOLDER_ID", "SHEET_ID"):
        if status[name] == "falta":
            return f"omitida: falta {name}"
    if not token_exists(load_settings()):
        return "omitida: falta el token OAuth (ejecuta scripts/google_auth.py)"
    return None


@pytest.fixture(scope="module")
def services():
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    settings = load_settings()
    return settings, build_drive_service(settings), build_sheets_service(settings)


def test_live_append_then_repeat_is_duplicate(services):
    settings, drive, sheets = services
    tracer = Tracer(session="live-stage5", console=False)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    comercio = f"Comercio de Prueba E5 {stamp}"

    upload = guardar_recibo(RECEIPT, comercio, "2026-09-12", service=drive, tracer=tracer, settings=settings)
    assert upload.success and upload.web_view_link, upload.error

    args = dict(
        fecha="2026-09-12",
        comercio=comercio,
        monto=18490,
        categoria="Supermercado",
        recibo_url=upload.web_view_link,
        service=sheets,
        tracer=tracer,
        settings=settings,
    )
    before = get_sheet_snapshot(sheets, settings)
    result = registrar_gasto(**args)
    assert result.success, result.error
    assert result.row_number and result.row_number >= 2

    after = get_sheet_snapshot(sheets, settings)
    assert after["row_count"] == before["row_count"] + 1
    assert after["last_row"][:4] == ["2026-09-12", comercio, 18490, "Supermercado"]

    repeated = registrar_gasto(**args)
    assert repeated.success is False and repeated.duplicate is True
    assert repeated.row_number == result.row_number
    assert get_sheet_snapshot(sheets, settings)["row_count"] == after["row_count"]
