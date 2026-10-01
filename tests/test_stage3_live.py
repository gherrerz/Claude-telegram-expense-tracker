"""Pruebas en vivo de la Etapa 3 (API real de Gemini).

Se omiten solas si faltan GEMINI_API_KEY o LLM_MODEL. Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live -v
Cada prueba consume una llamada de la capa gratuita.
"""
import json
from pathlib import Path

import pytest

from app.llm import LLMClient
from app.models import UNKNOWN
from app.tools.analyzer import analizar_recibo
from app.trace import Tracer

pytestmark = pytest.mark.live

RECEIPTS = Path(__file__).resolve().parents[1] / "data" / "receipts"
EXPECTED = json.loads((RECEIPTS / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def llm():
    return LLMClient(tracer=Tracer(session="live-stage3", console=False))


def test_live_text_smoke(llm):
    result = llm.generate_text("Di hola.")
    assert result.text and result.usage["total_token_count"] > 0


@pytest.mark.parametrize("name", ["receipt_normal.jpg", "receipt_hard.jpg"])
def test_live_readable_receipts_match_expected(llm, name):
    exp = EXPECTED[name]
    receipt = analizar_recibo(RECEIPTS / name, llm=llm)
    assert receipt.fecha == exp["fecha"]
    assert receipt.monto == exp["monto"]
    assert exp["comercio"].lower() in receipt.comercio.lower()


def test_live_illegible_receipt_is_unknown(llm):
    receipt = analizar_recibo(RECEIPTS / "receipt_illegible.jpg", llm=llm)
    assert receipt.monto == UNKNOWN or receipt.fecha == UNKNOWN
    assert receipt.confianza <= 0.5
