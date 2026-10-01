"""Prueba en vivo de la Etapa 8: rechazo seguro ante peticiones fuera de alcance.

Se omite sola sin GEMINI_API_KEY / LLM_MODEL. Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage8_live.py -v
Corre SIN Google (modo degradado A12): las variables de Google se vacían dentro de la
prueba. Criterios (condiciones, no texto exacto) en `app/security.py::evaluate_case`.
"""
from pathlib import Path

import pytest

from app.agent import ExpenseAgent
from app.config import config_status
from app.llm import LLMClient
from app.models import EventType
from app.prompts import SECURITY_SCOPE_ID
from app.security import SECURITY_CASES, evaluate_case
from app.trace import Tracer

pytestmark = pytest.mark.live

RECEIPT = Path(__file__).resolve().parents[1] / "data" / "receipts" / "receipt_normal.jpg"
GOOGLE_VARIABLES = (
    "GOOGLE_OAUTH_CLIENT_SECRETS", "GOOGLE_OAUTH_TOKEN", "DRIVE_FOLDER_ID", "SHEET_ID",
)


@pytest.fixture(autouse=True)
def require_gemini_and_disable_google(monkeypatch):
    for name in GOOGLE_VARIABLES:
        monkeypatch.setenv(name, "")
    status = config_status()
    if status["GEMINI_API_KEY"] == "falta" or status["LLM_MODEL"] == "falta":
        pytest.skip("omitida: falta GEMINI_API_KEY o LLM_MODEL")


@pytest.mark.parametrize("case", SECURITY_CASES, ids=[c["id"] for c in SECURITY_CASES])
def test_live_out_of_scope_requests_are_refused_within_limits(case):
    tracer = Tracer(session=f"live-stage8-{case['id']}", console=False)
    agent = ExpenseAgent(llm=LLMClient(tracer=tracer), tracer=tracer)
    result = agent.run(case["text"], RECEIPT if case["image"] else None)

    checks = evaluate_case(case, result.tool_sequence, result.stop_reason, result.final_text,
                           tracer.count(EventType.TOOL_CALL))
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"{failed} | tools={result.tool_sequence} | respuesta={result.final_text!r}"
    scopes = {e.data.get("security_scope_id") for e in tracer.events
              if e.event_type == EventType.LLM_DECISION}
    assert scopes == {SECURITY_SCOPE_ID}
