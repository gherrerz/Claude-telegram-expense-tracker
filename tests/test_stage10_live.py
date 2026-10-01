"""Prueba en vivo de la Etapa 10: ciclo de memoria avanzada con Gemini y Google reales.

Se omite sola sin GEMINI_API_KEY / LLM_MODEL, sin DRIVE_FOLDER_ID / SHEET_ID o sin el token OAuth.
Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage10_live.py -v
Escribe en la carpeta y la planilla de PRUEBA: sube el recibo único dos veces y agrega dos filas.
Genera un recibo sintético único por ejecución (`generate_unique_receipt`). Reutiliza el ciclo y las
condiciones de `app/memory_demo.py` (las mismas que `scripts/verify_stage_10.py`).
"""
import sys
from pathlib import Path

import pytest

from app.assistant import ExpenseAssistant
from app.config import config_status, load_settings
from app.conversation import Conversation
from app.google_auth import build_sheets_service, token_exists
from app.llm import LLMClient
from app.memory_demo import live_tools, run_memory_cycle
from app.models import AgentState
from app.tools.sheets import get_sheet_snapshot
from app.trace import Tracer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_receipts import generate_unique_receipt  # noqa: E402

pytestmark = pytest.mark.live


def _skip_reason():
    status = config_status()
    for name in ("GEMINI_API_KEY", "LLM_MODEL", "DRIVE_FOLDER_ID", "SHEET_ID"):
        if status[name] == "falta":
            return f"omitida: falta {name}"
    if not token_exists(load_settings()):
        return "omitida: falta el token OAuth (ejecuta scripts/google_auth.py)"
    return None


def test_live_memory_cycle_name_register_query_duplicate_and_confirmation(tmp_path):
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    settings = load_settings(required=["llm", "google"])
    sheets = build_sheets_service(settings)
    tracer = Tracer(session="live-stage10", console=False)
    image, expected = generate_unique_receipt(tmp_path)
    tools, counts = live_tools()
    assistant = ExpenseAssistant(llm=LLMClient(settings=settings, tracer=tracer), tracer=tracer,
                                 tool_overrides=tools)
    report = run_memory_cycle(
        assistant, counts, image, float(expected["monto"]), tracer,
        conversation=Conversation(), state=AgentState(),
        row_count=lambda: get_sheet_snapshot(sheets, settings)["row_count"],
    )
    failed = {
        f"paso {s.id}": [name for name, ok in s.checks.items() if not ok]
        for s in report.steps if not s.ok
    }
    assert report.ok, (
        f"{failed} | respuestas={[s.result.final_text for s in report.steps]} | "
        f"rutas={[s.result.route for s in report.steps]}"
    )
