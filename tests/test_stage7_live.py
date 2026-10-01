"""Prueba en vivo de la Etapa 7: el historial permite usar el nombre del turno 1.

Se omite sola sin GEMINI_API_KEY / LLM_MODEL. Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage7_live.py -v
Corre SIN Google (modo degradado A12) para no gastar cuota de Drive: las variables
de Google se vacían dentro de la prueba. Consume pocas llamadas de la capa gratuita
(una por turno sin imagen y varias en el turno con imagen, más la llamada de visión).
"""
from pathlib import Path

import pytest

from app.agent import ExpenseAgent
from app.conversation import Conversation
from app.llm import LLMClient
from app.models import EventType
from app.trace import Tracer

pytestmark = pytest.mark.live

RECEIPT = Path(__file__).resolve().parents[1] / "data" / "receipts" / "receipt_normal.jpg"
GOOGLE_VARIABLES = (
    "GOOGLE_OAUTH_CLIENT_SECRETS", "GOOGLE_OAUTH_TOKEN", "DRIVE_FOLDER_ID", "SHEET_ID",
)


@pytest.fixture
def without_google(monkeypatch):
    for name in GOOGLE_VARIABLES:
        monkeypatch.setenv(name, "")


def make_agent(session: str):
    tracer = Tracer(session=session, console=False)
    llm = LLMClient(tracer=tracer)
    return ExpenseAgent(llm=llm, tracer=tracer), tracer


def test_live_second_turn_uses_name_from_first_turn(without_google):
    agent, tracer = make_agent("live-stage7-history")
    conversation = Conversation()

    first = agent.run("Me llamo Diego", conversation=conversation)
    assert first.stop_reason == "respuesta_final"
    assert first.tool_calls == [], "un saludo no debe disparar ninguna tool"

    second = agent.run("Registra este recibo", RECEIPT, conversation=conversation)
    assert second.stop_reason == "respuesta_final"
    assert "analizar_recibo" in second.tool_sequence
    assert "diego" in second.final_text.lower()

    # El historial enviado en el turno 2 incluyó los 2 mensajes del turno 1.
    user_inputs = [e.data for e in tracer.events if e.event_type == EventType.USER_INPUT]
    assert [(u["turn"], u["history_messages"]) for u in user_inputs] == [(1, 0), (2, 2)]


def test_live_negative_without_history_name_is_absent(without_google):
    agent, tracer = make_agent("live-stage7-negative")
    result = agent.run("Registra este recibo", RECEIPT)  # sin conversación: solo el turno 2
    assert result.stop_reason == "respuesta_final"
    assert "diego" not in result.final_text.lower()
