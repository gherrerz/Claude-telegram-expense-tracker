"""Pruebas de la Etapa 2: modelos Pydantic."""
import pytest
from pydantic import ValidationError

from app.models import (
    ALLOWED_CATEGORIES,
    AgentState,
    DriveResult,
    EventType,
    ReceiptData,
    SheetResult,
    TraceEvent,
)


def _receipt(**overrides):
    base = {
        "fecha": "2026-09-30",
        "comercio": "Tienda",
        "monto": 1000.0,
        "categoria": "Hogar",
        "confianza": 0.9,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("category", ALLOWED_CATEGORIES)
def test_allowed_categories_accepted(category):
    assert ReceiptData(**_receipt(categoria=category)).categoria == category


def test_category_outside_set_rejected():
    with pytest.raises(ValidationError):
        ReceiptData(**_receipt(categoria="Viajes"))


def test_unknown_values_accepted():
    receipt = ReceiptData(
        fecha="desconocido",
        comercio="desconocido",
        monto="desconocido",
        categoria="desconocido",
        confianza=0.0,
    )
    assert receipt.monto == "desconocido"


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_out_of_range_rejected(confidence):
    with pytest.raises(ValidationError):
        ReceiptData(**_receipt(confianza=confidence))


def test_negative_amount_rejected():
    with pytest.raises(ValidationError):
        ReceiptData(**_receipt(monto=-5))


def test_amount_text_other_than_unknown_rejected():
    with pytest.raises(ValidationError):
        ReceiptData(**_receipt(monto="mucho"))


def test_drive_and_sheet_results():
    drive = DriveResult(success=True, file_id="id", file_name="a.jpg", web_view_link="u")
    assert drive.file_id == "id"
    assert SheetResult(success=True, row_number=3).row_number == 3
    assert SheetResult(success=False).row_number is None


def test_trace_event_has_utc_timestamp_and_all_types():
    assert len(EventType) == 10
    for kind in EventType:
        event = TraceEvent(event_type=kind)
        assert event.timestamp.endswith("+00:00")
    with pytest.raises(ValidationError):
        TraceEvent(event_type="OTRO")


def test_recent_expenses_cap_keeps_newest():
    state = AgentState(ultimos_gastos=[{"n": i} for i in range(8)])
    assert [g["n"] for g in state.ultimos_gastos] == [3, 4, 5, 6, 7]
    state.add_expense({"n": 99})
    assert len(state.ultimos_gastos) == 5
    assert state.ultimos_gastos[-1] == {"n": 99}
    assert state.ultimos_gastos[0] == {"n": 4}


def test_agent_state_defaults():
    state = AgentState()
    assert state.nombre_usuario is None
    assert state.totales_por_categoria == {}
    assert state.recibos_registrados == []
