"""Prueba en vivo de la Etapa 11: juez LLM con Gemini y Google reales.

Se omite sola sin GEMINI_API_KEY / LLM_MODEL, sin DRIVE_FOLDER_ID / SHEET_ID o sin el token OAuth.
Ejecutar con:
    .venv\\Scripts\\python -m pytest -m live tests/test_stage11_live.py -v
Escribe en la carpeta y la planilla de PRUEBA solo en el caso benigno (un recibo único, una fila). Reutiliza
los casos y las condiciones de `app/judge_demo.py` (las mismas que `scripts/verify_stage_11.py`).
"""
import sys
from pathlib import Path

import pytest

from app.assistant import ExpenseAssistant
from app.config import config_status, load_settings
from app.google_auth import build_sheets_service, token_exists
from app.judge_demo import run_judge_cases
from app.llm import LLMClient
from app.memory_demo import live_tools
from app.tools.sheets import get_sheet_snapshot
from app.trace import Tracer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_receipts import generate_unique_receipt  # noqa: E402

pytestmark = pytest.mark.live
INJECTION_IMAGE = ROOT / "data" / "receipts" / "receipt_injection.jpg"


def _skip_reason():
    status = config_status()
    for name in ("GEMINI_API_KEY", "LLM_MODEL", "DRIVE_FOLDER_ID", "SHEET_ID"):
        if status[name] == "falta":
            return f"omitida: falta {name}"
    if not token_exists(load_settings()):
        return "omitida: falta el token OAuth (ejecuta scripts/google_auth.py)"
    return None


def test_live_judge_approves_the_benign_receipt_and_rejects_the_injected_one(tmp_path):
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    settings = load_settings(required=["llm", "google"])
    sheets = build_sheets_service(settings)
    tracer = Tracer(session="live-stage11", console=False)
    image, _expected = generate_unique_receipt(tmp_path)
    tools, counts = live_tools()
    assistant = ExpenseAssistant(llm=LLMClient(settings=settings, tracer=tracer), tracer=tracer,
                                 tool_overrides=tools)
    report = run_judge_cases(
        assistant, counts, image, INJECTION_IMAGE, tracer,
        row_count=lambda: get_sheet_snapshot(sheets, settings)["row_count"],
    )
    failed = {
        f"caso {c.id}": [name for name, ok in c.checks.items() if not ok]
        for c in report.cases if not c.ok
    }
    assert report.ok, (
        f"{failed} | veredictos={[c.verdicts for c in report.cases]} | "
        f"respuestas={[c.result.final_text for c in report.cases]}"
    )
