"""Verificación real de la Etapa 6 (la ejecuta el autor con su `.env`).

Ejecuta el agente ReAct con Gemini real sobre `receipt_normal.jpg` y el mensaje
"Registra este recibo". Imprime la traza legible, la secuencia de tools, el
motivo de parada y los contadores de uso. Si Google está configurado, el agente
guarda en Drive y escribe UNA fila en la planilla de prueba; si no, el flujo
degrada de forma honesta (los errores vuelven al LLM como observaciones).

Si falta GEMINI_API_KEY o LLM_MODEL, sale con código 2 sin llamar a la red.
Escribe la traza en `traces/verify-stage6.jsonl`.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_6.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import MAX_STEPS, ExpenseAgent  # noqa: E402
from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.google_auth import token_exists  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.models import EventType  # noqa: E402
from app.trace import Tracer  # noqa: E402

RECEIPT = ROOT / "data" / "receipts" / "receipt_normal.jpg"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    status = config_status()
    missing = [n for n in ("GEMINI_API_KEY", "LLM_MODEL") if status[n] == "falta"]
    if missing:
        print(
            f"ERROR: faltan variables de entorno: {', '.join(missing)}.\n"
            "Copia .env.example a .env y completa la clave de Gemini y LLM_MODEL. "
            "No se hizo ninguna llamada de red."
        )
        return 2
    try:
        settings = load_settings(required=["llm"])
    except ConfigError as error:
        print(f"ERROR: {error}")
        return 2

    google = (
        status["DRIVE_FOLDER_ID"] == "definida"
        and status["SHEET_ID"] == "definida"
        and token_exists(settings)
    )
    print(f"Google configurado: {'sí' if google else 'no (modo degradado honesto)'}\n")

    tracer = Tracer(session="verify-stage6", console=True)
    llm = LLMClient(tracer=tracer, settings=settings)
    result = ExpenseAgent(llm=llm, tracer=tracer).run("Registra este recibo", RECEIPT)

    print("\n== RESUMEN ==")
    print(f"Secuencia de tools: {' -> '.join(result.tool_sequence) or '(ninguna)'}")
    print(f"Motivo de parada:   {result.stop_reason} (decisiones: {result.steps}/{MAX_STEPS})")
    print(f"Respuesta final:    {result.final_text}")
    print(f"Contadores LLM:     {llm.stats.as_dict()}")

    registrar = [c for c in result.tool_calls if c["name"] == "registrar_gasto"]
    registered = [
        e.data["result"] for e in tracer.events
        if e.event_type == EventType.TOOL_RESULT and e.data["tool"] == "registrar_gasto"
    ]
    checks = {
        "analizar_recibo pedida por el LLM": "analizar_recibo" in result.tool_sequence,
        "observaciones devueltas al LLM": tracer.count(EventType.TOOL_RESULT) == len(result.tool_calls) > 0,
        "un evento STOP con motivo": tracer.count(EventType.STOP) == 1,
        "parada por respuesta final": result.stop_reason == "respuesta_final",
        "FINAL_RESPONSE registrado": tracer.events[-1].event_type == EventType.FINAL_RESPONSE,
    }
    if google:
        last = registered[-1] if registered else {}
        checks["guardar y registrar intentados"] = bool(registrar) and any(
            c["name"] == "guardar_recibo" for c in result.tool_calls
        )
        checks["respuesta menciona fila o duplicado"] = bool(last) and (
            (last.get("ok") and str(last.get("row_number")) in result.final_text)
            or (last.get("duplicate") and ("duplic" in result.final_text.lower()
                                           or str(last.get("row_number")) in result.final_text))
        )
    else:
        checks["degradación honesta (sin fila afirmada)"] = (
            not any(c["ok"] for c in registrar)
            and not re.search(r"fila\s+\d+", result.final_text.lower())
        )
    print()
    for name, passed in checks.items():
        print(f"    {'OK ' if passed else 'FALLA'} {name}")
    print(f"\nTraza: {tracer.path}")
    ok = all(checks.values())
    print("RESULTADO:", "OK" if ok else "CON FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
