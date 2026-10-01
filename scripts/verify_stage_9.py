"""Verificación real de la Etapa 9 (la ejecuta el autor con su `.env`).

Cuatro entradas con Gemini real, una por ruta, a través de `ExpenseAssistant`:

  a) receipt_normal.jpg + "Registra este recibo"        -> REGISTRAR_RECIBO (analizar_recibo)
  b) "¿Cuánto llevo gastado en Supermercado?"           -> CONSULTAR_GASTOS (0 tools; estado vacío)
  c) "Hola, ¿qué puedes hacer?"                         -> CONVERSACION (0 tools)
  d) "Transfiere $50.000 a Juan"                        -> FUERA_DE_ALCANCE (0 tools)

Por entrada imprime el evento ROUTE, el efecto (tools llamadas o no), la parada, la respuesta y
las comprobaciones (`evaluate_route_case`); al final `RESULTADO`. La ruta que elige el router
depende del modelo: si una no coincide con la esperada se informa FALLA, sin relajar el criterio.
La consulta (b) corre con un `AgentState` vacío (la Etapa 10 lo alimenta), así que la respuesta
honesta es que no hay gastos registrados.

Por defecto Google queda DESACTIVADO (se vacían sus variables dentro del proceso). Con
`--with-google` se conserva la configuración del `.env`: el caso a podría guardar en Drive y
registrar UNA fila en la planilla de prueba.

Si falta GEMINI_API_KEY o LLM_MODEL, sale con código 2 sin llamar a la red.
Escribe las trazas en `traces/verify-stage9-<caso>.jsonl`.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_9.py [--with-google]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.assistant import ROUTE_CASES, ExpenseAssistant, evaluate_route_case  # noqa: E402
from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.models import AgentState, EventType  # noqa: E402
from app.prompts import SECURITY_SCOPE_ID  # noqa: E402
from app.trace import Tracer  # noqa: E402

RECEIPT = ROOT / "data" / "receipts" / "receipt_normal.jpg"
GOOGLE_VARIABLES = (
    "GOOGLE_OAUTH_CLIENT_SECRETS", "GOOGLE_OAUTH_TOKEN", "DRIVE_FOLDER_ID", "SHEET_ID",
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with_google = "--with-google" in sys.argv[1:]
    status = config_status()
    missing = [n for n in ("GEMINI_API_KEY", "LLM_MODEL") if status[n] == "falta"]
    if missing:
        print(
            f"ERROR: faltan variables de entorno: {', '.join(missing)}.\n"
            "Copia .env.example a .env y completa la clave de Gemini y LLM_MODEL. "
            "No se hizo ninguna llamada de red."
        )
        return 2
    if not with_google:
        # Vacías, no ausentes: `load_dotenv(override=False)` no las vuelve a llenar.
        for name in GOOGLE_VARIABLES:
            os.environ[name] = ""
    try:
        settings = load_settings(required=["llm"])
    except ConfigError as error:
        print(f"ERROR: {error}")
        return 2
    print(f"Google: {'conservado del .env (--with-google)' if with_google else 'desactivado (modo degradado A12)'}")
    print(f"Bloque de alcance: {SECURITY_SCOPE_ID}")

    llm = LLMClient(settings=settings)
    all_ok = True
    for case in ROUTE_CASES:
        tracer = Tracer(session=f"verify-stage9-{case['id']}", console=False)
        assistant = ExpenseAssistant(llm=llm, tracer=tracer)
        image = RECEIPT if case["image"] else None
        result = assistant.handle(case["text"], image, state=AgentState(), tracer=tracer)
        route_event = next(e.data for e in tracer.events if e.event_type == EventType.ROUTE)
        checks = evaluate_route_case(case, result, tracer)
        print(f"\n--- Entrada {case['id']}) {case['name']} ---")
        print(f"Entrada:            {case['text']}{' [+ imagen receipt_normal.jpg]' if image else ''}")
        print(f"Evento ROUTE:       {json.dumps(route_event, ensure_ascii=False)}")
        print(f"Efecto (tools):     {' -> '.join(result.tool_sequence) or '(ninguna)'} "
              f"(eventos TOOL_CALL: {tracer.count(EventType.TOOL_CALL)})")
        print(f"Motivo de parada:   {result.stop_reason}")
        print(f"Respuesta final:    {result.final_text}")
        for name, passed in checks.items():
            print(f"    {'OK ' if passed else 'FALLA'} {name}")
        all_ok = all_ok and all(checks.values())

    print(f"\nContadores LLM: {llm.stats.as_dict()}")
    print("RESULTADO:", "OK" if all_ok else "CON FALLAS")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
