"""Prueba en vivo de la Etapa 9: el router elige la ruta y cada ruta ejecuta su camino.

Se omite sola sin GEMINI_API_KEY / LLM_MODEL. Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage9_live.py -v
Corre SIN Google (modo degradado A12): las variables de Google se vacían dentro de la prueba.
La precisión del router depende del modelo: si una ruta no coincide, la prueba falla (no se
relajan las expectativas). Criterios por condiciones en `app/assistant.py::evaluate_route_case`.
"""
from pathlib import Path

import pytest

from app.assistant import ROUTE_CASES, ExpenseAssistant, evaluate_route_case
from app.config import config_status
from app.llm import LLMClient
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


@pytest.mark.parametrize("case", ROUTE_CASES, ids=[c["id"] for c in ROUTE_CASES])
def test_live_each_input_takes_its_route_and_effect(case):
    tracer = Tracer(session=f"live-stage9-{case['id']}", console=False)
    assistant = ExpenseAssistant(llm=LLMClient(tracer=tracer), tracer=tracer)
    result = assistant.handle(case["text"], RECEIPT if case["image"] else None)

    checks = evaluate_route_case(case, result, tracer)
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, (
        f"{failed} | ruta={result.route} ({result.decision.motivo!r}) | "
        f"tools={result.tool_sequence} | respuesta={result.final_text!r}"
    )
