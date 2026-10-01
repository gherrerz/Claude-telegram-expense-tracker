"""Pruebas offline de la Etapa 4: `guardar_recibo` con un servicio de Drive falso."""
import json
from pathlib import Path

import httplib2
import pytest
from fakes import FakeDriveService
from googleapiclient.errors import HttpError

from app.config import load_settings
from app.google_auth import SCOPES, GoogleAuthError, load_credentials
from app.models import DriveResult
from app.tools import drive
from app.tools.drive import (
    build_file_name,
    guardar_recibo,
    normalize_name_part,
    verify_file_exists,
)
from app.trace import MASK, Tracer

RECEIPT = Path(__file__).resolve().parents[1] / "data" / "receipts" / "receipt_normal.jpg"
FOLDER = "carpeta-de-prueba"
API_LINK = "https://drive.google.com/file/d/ID123/view?usp=drivesdk"
SETTINGS = load_settings(
    env={"DRIVE_FOLDER_ID": FOLDER, "GOOGLE_OAUTH_TOKEN": "inexistente/token.json"}
)


def _ok_service():
    return FakeDriveService(
        create_result={"id": "ID123", "name": "recibo_x.jpg", "webViewLink": API_LINK}
    )


def _http_error(status):
    return HttpError(httplib2.Response({"status": status}), b'{"error": "x"}')


@pytest.mark.parametrize(
    "comercio, fecha, expected",
    [
        ("Jumbo", "2026-09-30", "recibo_jumbo_2026_09_30.jpg"),
        ("Café  Ñandú & Cía.", "2026-01-05", "recibo_cafe_nandu_cia_2026_01_05.jpg"),
        ("desconocido", "desconocido", "recibo_desconocido_desconocido.jpg"),
        ("!!!", "", "recibo_desconocido_desconocido.jpg"),
        ("../../etc/passwd", "2026-09-30", "recibo_etc_passwd_2026_09_30.jpg"),
    ],
)
def test_file_name_normalization(comercio, fecha, expected):
    assert build_file_name(comercio, fecha) == expected


def test_name_is_truncated_and_has_no_edge_underscores():
    assert len(normalize_name_part("a" * 100)) <= 40
    assert normalize_name_part("x" * 39 + " y") == "x" * 39
    assert build_file_name("a", "b", "image/png").endswith(".png")


def test_upload_returns_link_from_api_and_uses_folder_parent():
    service = _ok_service()
    result = guardar_recibo(RECEIPT, "Jumbo", "2026-09-30", service=service, settings=SETTINGS)
    assert result.success and result.error is None
    assert result.file_id == "ID123"
    assert result.web_view_link == API_LINK  # tomado de la respuesta, no construido
    call = service.files().create_calls[0]
    assert call["body"]["parents"] == [FOLDER]
    assert call["body"]["name"] == "recibo_jumbo_2026_09_30.jpg"
    assert call["fields"] == "id,name,webViewLink"
    assert call["media_body"].mimetype() == "image/jpeg"


def test_link_is_never_built_by_hand_when_api_omits_it():
    service = FakeDriveService(create_result={"id": "ID999", "name": "a.jpg"})
    result = guardar_recibo(RECEIPT, "Jumbo", "2026-09-30", service=service, settings=SETTINGS)
    assert result.success and result.file_id == "ID999"
    assert result.web_view_link is None


def test_bytes_input_and_png_mime():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    service = _ok_service()
    result = guardar_recibo(png, "Tienda", "2026-02-02", service=service, settings=SETTINGS)
    assert result.success
    call = service.files().create_calls[0]
    assert call["media_body"].mimetype() == "image/png"
    assert call["body"]["name"].endswith(".png")


def test_unsupported_format_does_not_call_api():
    service = _ok_service()
    result = guardar_recibo(b"no soy una imagen", "x", "y", service=service, settings=SETTINGS)
    assert result.success is False and "Formato" in result.error
    assert service.files().create_calls == []


def test_missing_image_file_returns_failure(tmp_path):
    result = guardar_recibo(tmp_path / "nada.jpg", "x", "y", service=_ok_service(), settings=SETTINGS)
    assert result.success is False and result.error
    assert "nada.jpg" not in result.error


def test_missing_folder_id_returns_failure():
    settings = load_settings(env={})
    result = guardar_recibo(RECEIPT, "x", "y", service=_ok_service(), settings=settings)
    assert result.success is False and "DRIVE_FOLDER_ID" in result.error


def test_missing_credentials_returns_clear_error_without_raising(tmp_path):
    settings = load_settings(
        env={"DRIVE_FOLDER_ID": FOLDER, "GOOGLE_OAUTH_TOKEN": str(tmp_path / "token-secreto.json")}
    )
    result = guardar_recibo(RECEIPT, "x", "y", settings=settings)  # sin service
    assert result.success is False
    assert "scripts/google_auth.py" in result.error
    assert "token-secreto" not in result.error and str(tmp_path) not in result.error


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_http_error_returns_failure_without_details(status):
    service = FakeDriveService(create_result=_http_error(status))
    result = guardar_recibo(RECEIPT, "x", "y", service=service, settings=SETTINGS)
    assert result.success is False
    assert str(status) in result.error
    assert '"error"' not in result.error  # no se copia el cuerpo de la respuesta


def test_unexpected_exception_returns_failure():
    service = FakeDriveService(create_result=ConnectionError("detalle interno /ruta/secreta"))
    result = guardar_recibo(RECEIPT, "x", "y", service=service, settings=SETTINGS)
    assert result.success is False
    assert "ConnectionError" in result.error and "/ruta/secreta" not in result.error


def test_response_without_id_is_failure():
    service = FakeDriveService(create_result={"name": "a.jpg"})
    result = guardar_recibo(RECEIPT, "x", "y", service=service, settings=SETTINGS)
    assert result.success is False


def test_traces_tool_call_and_result(tmp_path):
    tracer = Tracer(session="d1", trace_dir=tmp_path, console=False)
    guardar_recibo(
        RECEIPT, "Jumbo", "2026-09-30", service=_ok_service(), tracer=tracer, settings=SETTINGS
    )
    assert tracer.count("TOOL_CALL") == 1 and tracer.count("TOOL_RESULT") == 1
    result_event = tracer.events[-1]
    assert result_event.data["tool"] == "guardar_recibo" and result_event.data["ok"] is True


def test_trace_masks_credential_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS", "C:\\mis cosas\\client_secret_abc.json")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN", "D:/datos/mio/token-privado.json")
    tracer = Tracer(session="d2", trace_dir=tmp_path, console=False)
    tracer.record(
        "TOOL_RESULT",
        {
            "error": "falló con C:\\mis cosas\\client_secret_abc.json y D:/datos/mio/token-privado.json",
            "ruta": "C:\\repo\\secrets\\token.json",
        },
    )
    text = (tmp_path / "d2.jsonl").read_text(encoding="utf-8")
    assert MASK in text
    for leaked in ("client_secret_abc", "token-privado", "token.json"):
        assert leaked not in text


def test_verify_file_exists_uses_files_get():
    service = FakeDriveService(get_result={"id": "ID123", "name": "a.jpg", "trashed": False})
    meta = verify_file_exists("ID123", service)
    assert meta["id"] == "ID123"
    assert service.files().get_calls[0]["fileId"] == "ID123"


def test_verify_file_exists_returns_none_on_404_and_raises_otherwise():
    assert verify_file_exists("x", FakeDriveService(get_result=_http_error(404))) is None
    with pytest.raises(HttpError):
        verify_file_exists("x", FakeDriveService(get_result=_http_error(500)))


def test_load_credentials_non_interactive_never_opens_browser(tmp_path, monkeypatch):
    def boom(*args, **kwargs):  # si se llamara al flujo interactivo, la prueba falla
        raise AssertionError("no debe abrir el navegador")

    monkeypatch.setattr("app.google_auth._run_interactive_flow", boom)
    settings = load_settings(env={"GOOGLE_OAUTH_TOKEN": str(tmp_path / "no-existe.json")})
    with pytest.raises(GoogleAuthError) as exc:
        load_credentials(settings)
    assert "scripts/google_auth.py" in str(exc.value)


def test_load_credentials_with_corrupt_token_raises_clear_error(tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{ no es json", encoding="utf-8")
    settings = load_settings(env={"GOOGLE_OAUTH_TOKEN": str(token)})
    with pytest.raises(GoogleAuthError):
        load_credentials(settings)


def test_scopes_are_minimal():
    assert SCOPES == ["https://www.googleapis.com/auth/drive.file"]


def test_drive_result_error_field_is_optional():
    assert DriveResult(success=True, file_id="i").error is None
    assert json.loads(DriveResult(success=False, error="x").model_dump_json())["error"] == "x"
    assert drive.TOOL_NAME == "guardar_recibo"
