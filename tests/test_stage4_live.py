"""Prueba en vivo de la Etapa 4 (Google Drive real, OAuth de usuario).

Se omite sola si faltan DRIVE_FOLDER_ID o el archivo de token. Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage4_live.py -v
Sube un recibo sintético a la carpeta de prueba y lo confirma con `files.get`.
"""
from pathlib import Path

import pytest

from app.config import config_status, load_settings
from app.google_auth import build_drive_service, token_exists
from app.tools.drive import guardar_recibo, verify_file_exists
from app.trace import Tracer

pytestmark = pytest.mark.live

RECEIPT = Path(__file__).resolve().parents[1] / "data" / "receipts" / "receipt_normal.jpg"


def _skip_reason():
    if config_status()["DRIVE_FOLDER_ID"] == "falta":
        return "omitida: falta DRIVE_FOLDER_ID"
    if not token_exists(load_settings()):
        return "omitida: falta el token OAuth (ejecuta scripts/google_auth.py)"
    return None


@pytest.fixture(scope="module")
def service():
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    return build_drive_service(load_settings())


def test_live_upload_and_verify_with_files_get(service):
    tracer = Tracer(session="live-stage4", console=False)
    result = guardar_recibo(RECEIPT, "Comercio de Prueba", "2026-09-30", service=service, tracer=tracer)
    assert result.success, result.error
    assert result.file_id and result.web_view_link
    meta = verify_file_exists(result.file_id, service)
    assert meta is not None and meta["id"] == result.file_id
    assert meta.get("trashed") is False
