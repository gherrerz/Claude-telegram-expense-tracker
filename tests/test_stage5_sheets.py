"""Pruebas offline de la Etapa 5: `registrar_gasto` con un servicio de Sheets falso."""
from pathlib import Path

import httplib2
import pytest
from fakes import SHEET_HEADER_ROW, FakeSheetsService
from googleapiclient.errors import HttpError

from app.config import load_settings
from app.models import ALLOWED_CATEGORIES, SheetResult
from app.tools import sheets
from app.tools.sheets import get_sheet_snapshot, parse_row_number, registrar_gasto
from app.trace import Tracer

SHEET = "planilla-de-prueba"
SETTINGS = load_settings(env={"SHEET_ID": SHEET, "GOOGLE_OAUTH_TOKEN": "inexistente/token.json"})
URL = "https://drive.google.com/file/d/ID123/view?usp=drivesdk"
GOOD = dict(fecha="2026-09-12", comercio="Los Aromos", monto=18490, categoria="Supermercado", recibo_url=URL)


def _http_error(status):
    return HttpError(httplib2.Response({"status": status}), b'{"error": "x"}')


def _call(service, **overrides):
    args = {**GOOD, **overrides}
    return registrar_gasto(**args, service=service, settings=SETTINGS)


def _api_calls(service):
    values = service.values()
    return len(values.get_calls) + len(values.append_calls)


def test_valid_append_returns_row_number_from_updated_range():
    service = FakeSheetsService()
    result = _call(service)
    assert result.success and result.duplicate is False and result.error is None
    assert result.row_number == 2  # parseado de "Hoja 1!A2:E2" devuelta por la API
    call = service.values().append_calls[0]
    assert call["spreadsheetId"] == SHEET
    assert call["range"] == "A:E"
    assert call["valueInputOption"] == "RAW"
    assert call["insertDataOption"] == "INSERT_ROWS"
    assert call["body"] == {"values": [["2026-09-12", "Los Aromos", 18490, "Supermercado", URL]]}


def test_row_number_comes_from_response_not_from_precount():
    service = FakeSheetsService(updated_range="Hoja 1!A57:E57")
    assert _call(service).row_number == 57


def test_amount_stays_numeric_and_accepts_numeric_strings():
    service = FakeSheetsService()
    assert _call(service, monto="18490.5").success
    stored = service.values().append_calls[0]["body"]["values"][0][2]
    assert stored == 18490.5 and isinstance(stored, float)


@pytest.mark.parametrize(
    "overrides",
    [
        {"categoria": "Cripto"},
        {"categoria": "desconocido"},
        {"categoria": None},
        {"monto": 0},
        {"monto": -5},
        {"monto": "desconocido"},
        {"monto": "abc"},
        {"monto": True},
        {"monto": float("nan")},
        {"monto": float("inf")},
        {"monto": None},
        {"fecha": "desconocido"},
        {"fecha": "12/09/2026"},
        {"fecha": "2026-9-12"},
        {"fecha": "2026-02-30"},
        {"fecha": None},
        {"comercio": ""},
        {"comercio": "   "},
        {"comercio": "Desconocido"},
        {"comercio": None},
        {"comercio": "x" * 201},
        {"recibo_url": "http://drive.google.com/file/d/1/view"},
        {"recibo_url": "https://evil.example.com/file/d/1/view"},
        {"recibo_url": "https://drive.google.com.evil.com/file/d/1"},
        {"recibo_url": "https://drive.google.com@evil.com/file/d/1"},
        {"recibo_url": "https://user@drive.google.com/file/d/1"},
        {"recibo_url": "https://drive.google.com:8443/file/d/1"},
        {"recibo_url": "javascript:alert(1)"},
        {"recibo_url": ""},
        {"recibo_url": None},
    ],
)
def test_validation_failure_makes_zero_api_calls(overrides):
    service = FakeSheetsService()
    result = _call(service, **overrides)
    assert result.success is False and result.duplicate is False and result.error
    assert _api_calls(service) == 0
    assert len(service.values().rows) == 1  # solo el encabezado


def test_every_allowed_category_is_accepted():
    service = FakeSheetsService()
    for index, categoria in enumerate(ALLOWED_CATEGORIES):
        assert _call(service, categoria=categoria, comercio=f"Tienda {index}").success


def test_validation_does_not_need_config_or_credentials():
    result = registrar_gasto(**{**GOOD, "categoria": "Cripto"}, settings=load_settings(env={}))
    assert result.success is False and "Categoría" in result.error


def test_duplicate_is_detected_without_append():
    service = FakeSheetsService(
        rows=[SHEET_HEADER_ROW, ["2026-09-12", "los  AROMOS ", 18490, "Supermercado", URL]]
    )
    result = _call(service)
    assert result.success is False and result.duplicate is True and result.row_number == 2
    assert service.values().append_calls == []
    assert len(service.values().rows) == 2


def test_same_merchant_different_amount_or_date_is_not_duplicate():
    service = FakeSheetsService(
        rows=[SHEET_HEADER_ROW, ["2026-09-12", "Los Aromos", 18490.5, "Supermercado", URL]]
    )
    assert _call(service).success  # monto distinto
    assert _call(service, fecha="2026-09-13", monto=18490.5).success  # fecha distinta


def test_repeat_after_first_append_is_duplicate_and_state_unchanged():
    service = FakeSheetsService()
    first = _call(service)
    assert first.success and first.row_number == 2
    snapshot = [list(row) for row in service.values().rows]
    second = _call(service)
    assert second.success is False and second.duplicate is True and second.row_number == 2
    assert len(service.values().append_calls) == 1
    assert service.values().rows == snapshot


def test_duplicate_compares_amount_numerically_and_tolerates_short_rows():
    service = FakeSheetsService(
        rows=[SHEET_HEADER_ROW, ["2026-09-12", "Los Aromos", "18490", "Supermercado", URL], ["2026-09-12"]]
    )
    assert _call(service).duplicate is True


def test_duplicate_search_requests_unformatted_values():
    service = FakeSheetsService()
    _call(service)
    call = service.values().get_calls[0]
    assert call["range"] == "A:E" and call["valueRenderOption"] == "UNFORMATTED_VALUE"


@pytest.mark.parametrize(
    "updated, expected",
    [
        ("Hoja 1!A7:E7", 7),
        ("'Hoja 1'!A7:E7", 7),
        ("Sheet1!A12:E12", 12),
        ("'Gastos ''2026'''!A103:E103", 103),
        ("'Hoja!rara'!A9:E9", 9),
        ("A5:E5", 5),
        ("Sheet1!$A$8:$E$8", 8),
        ("", None),
        (None, None),
        ("Sheet1!", None),
    ],
)
def test_parse_row_number(updated, expected):
    assert parse_row_number(updated) == expected


def test_sheet_name_with_spaces_and_quotes_is_parsed_end_to_end():
    service = FakeSheetsService(sheet_title="Mi hoja d'prueba")
    assert _call(service).row_number == 2


def test_response_without_updated_range_is_failure():
    service = FakeSheetsService(updated_range="sin-fila")
    result = _call(service)
    assert result.success is False and result.row_number is None


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_http_error_on_append_is_safe_failure(status):
    service = FakeSheetsService(append_error=_http_error(status))
    result = _call(service)
    assert result.success is False and str(status) in result.error
    assert '"error"' not in result.error


def test_http_error_on_read_blocks_the_write():
    service = FakeSheetsService(get_error=_http_error(403))
    result = _call(service)
    assert result.success is False and "403" in result.error
    assert service.values().append_calls == []


def test_unexpected_exception_is_safe_failure():
    service = FakeSheetsService(append_error=ConnectionError("detalle /ruta/secreta"))
    result = _call(service)
    assert result.success is False
    assert "ConnectionError" in result.error and "/ruta/secreta" not in result.error


def test_missing_sheet_id_is_safe_failure():
    service = FakeSheetsService()
    result = registrar_gasto(**GOOD, service=service, settings=load_settings(env={}))
    assert result.success is False and "SHEET_ID" in result.error
    assert _api_calls(service) == 0


def test_missing_credentials_is_safe_failure_without_leaking_paths(tmp_path):
    settings = load_settings(
        env={"SHEET_ID": SHEET, "GOOGLE_OAUTH_TOKEN": str(tmp_path / "token-secreto.json")}
    )
    result = registrar_gasto(**GOOD, settings=settings)  # sin service
    assert result.success is False and "scripts/google_auth.py" in result.error
    assert "token-secreto" not in result.error and str(tmp_path) not in result.error


def test_snapshot_counts_data_rows_and_last_row():
    assert get_sheet_snapshot(FakeSheetsService(), SETTINGS) == {"row_count": 0, "last_row": None}
    service = FakeSheetsService(
        rows=[SHEET_HEADER_ROW, ["a", "b", 1, "c", "d"], [], ["e", "f", 2, "g", "h"]]
    )
    snap = get_sheet_snapshot(service, SETTINGS)
    assert snap == {"row_count": 2, "last_row": ["e", "f", 2, "g", "h"]}
    assert service.values().append_calls == []  # solo lectura


def test_snapshot_changes_by_one_after_append():
    service = FakeSheetsService()
    before = get_sheet_snapshot(service, SETTINGS)
    _call(service)
    after = get_sheet_snapshot(service, SETTINGS)
    assert after["row_count"] == before["row_count"] + 1
    assert after["last_row"][:4] == ["2026-09-12", "Los Aromos", 18490, "Supermercado"]


def test_traces_tool_call_and_result(tmp_path):
    tracer = Tracer(session="s1", trace_dir=tmp_path, console=False)
    registrar_gasto(**GOOD, service=FakeSheetsService(), tracer=tracer, settings=SETTINGS)
    assert tracer.count("TOOL_CALL") == 1 and tracer.count("TOOL_RESULT") == 1
    event = tracer.events[-1]
    assert event.data["tool"] == "registrar_gasto" and event.data["ok"] is True


def test_validation_failure_is_traced():
    tracer = Tracer(console=False, write_file=False)
    registrar_gasto(**{**GOOD, "monto": -1}, service=FakeSheetsService(), tracer=tracer, settings=SETTINGS)
    assert tracer.count("TOOL_CALL") == 1 and tracer.events[-1].data["ok"] is False


def test_sheet_result_new_fields_default_and_tool_name():
    result = SheetResult(success=True, row_number=3)
    assert result.duplicate is False and result.error is None
    assert sheets.TOOL_NAME == "registrar_gasto"


def test_module_is_append_only():
    source = Path(sheets.__file__).read_text(encoding="utf-8")
    for forbidden in (".clear(", ".batchClear(", ".batchUpdate(", ".delete(", ".update("):
        assert forbidden not in source
