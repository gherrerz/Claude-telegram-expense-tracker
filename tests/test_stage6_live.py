"""Prueba en vivo de la Etapa 6: el loop ReAct con Gemini real.

Se omite sola sin GEMINI_API_KEY / LLM_MODEL. Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage6_live.py -v
Consume varias llamadas de la capa gratuita (una por decisión del LLM, más la
llamada de visión). Si Google está configurado, escribe UNA fila en la planilla de prueba.
"""
import re
from pathlib import Path

import pytest

from app.agent import MAX_STEPS, ExpenseAgent
from app.config import config_status, load_settings
from app.google_auth import token_exists
from app.llm import LLMClient
from app.models import EventType
from app.trace import Tracer

pytestmark = pytest.mark.live

RECEIPT = Path(__file__).resolve().parents[1] / "data" / "receipts" / "receipt_normal.jpg"


def google_ready() -> bool:
    status = config_status()
    return (
        status["DRIVE_FOLDER_ID"] == "definida"
        and status["SHEET_ID"] == "definida"
        and token_exists(load_settings())
    )


def test_live_react_loop_on_normal_receipt():
    tracer = Tracer(session="live-stage6", console=False)
    llm = LLMClient(tracer=tracer)
    result = ExpenseAgent(llm=llm, tracer=tracer).run("Registra este recibo", RECEIPT)

    # El LLM pidió la tool y su observación volvió a él.
    assert "analizar_recibo" in result.tool_sequence
    assert tracer.count(EventType.TOOL_RESULT) == len(result.tool_calls)
    assert result.steps >= 2 and result.steps <= MAX_STEPS
    # Parada explícita y respuesta final registradas.
    stops = [e for e in tracer.events if e.event_type == EventType.STOP]
    assert len(stops) == 1 and stops[0].data["reason"] == result.stop_reason
    assert result.stop_reason == "respuesta_final"
    assert tracer.events[-1].event_type == EventType.FINAL_RESPONSE and result.final_text

    registrar = [c for c in result.tool_calls if c["name"] == "registrar_gasto"]
    if google_ready():
        assert any(c["name"] == "guardar_recibo" for c in result.tool_calls)
        assert registrar, "con Google configurado el agente debía intentar registrar"
        results = [
            e.data["result"] for e in tracer.events
            if e.event_type == EventType.TOOL_RESULT and e.data["tool"] == "registrar_gasto"
        ]
        last = results[-1]
        if last.get("duplicate"):
            assert "duplic" in result.final_text.lower() or str(last["row_number"]) in result.final_text
        else:
            assert last["ok"] is True and str(last["row_number"]) in result.final_text
    else:
        # Degradación honesta: nada se registró y no se afirma ninguna fila.
        assert not any(c["ok"] for c in registrar)
        assert not re.search(r"fila\s+\d+", result.final_text.lower())
