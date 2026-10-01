"""Verificación real de la Etapa 7 (la ejecuta el autor con su `.env`).

Dos escenarios con Gemini real y el agente ReAct:

  A. Con historial. Turno 1: "Me llamo Diego" (se espera cero tools). Turno 2: la
     imagen `receipt_normal.jpg` y "Registra este recibo". La respuesta final debe
     contener "Diego", que solo pudo salir de los mensajes reenviados.
  B. Prueba negativa. Agente nuevo y sin historial: solo el turno 2. La respuesta
     NO debe contener "Diego", lo que demuestra que el nombre no está en el código.

Por turno imprime: texto del usuario, mensajes de historial enviados, secuencia de
tools, motivo de parada y respuesta final; al final, las comprobaciones OK/FALLA y
`RESULTADO`.

Por defecto Google queda DESACTIVADO (se vacían sus variables dentro del proceso)
para no gastar cuota de Drive ni escribir filas: el agente degrada con honestidad.
`--with-google` conserva la configuración de Google del `.env` (el turno 2 puede
guardar en Drive y registrar UNA fila en la planilla de prueba).

Si falta GEMINI_API_KEY o LLM_MODEL, sale con código 2 sin llamar a la red.
Escribe la traza en `traces/verify-stage7.jsonl`.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_7.py [--with-google]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import MAX_STEPS, AgentResult, ExpenseAgent  # noqa: E402
from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.conversation import Conversation  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.models import EventType  # noqa: E402
from app.trace import Tracer  # noqa: E402

RECEIPT = ROOT / "data" / "receipts" / "receipt_normal.jpg"
GOOGLE_VARIABLES = (
    "GOOGLE_OAUTH_CLIENT_SECRETS", "GOOGLE_OAUTH_TOKEN", "DRIVE_FOLDER_ID", "SHEET_ID",
)


def print_turn(label: str, user_text: str, image: bool, history_sent: int, result: AgentResult) -> None:
    print(f"\n--- {label} ---")
    print(f"Usuario:            {user_text}{' [+ imagen receipt_normal.jpg]' if image else ''}")
    print(f"Historial enviado:  {history_sent} mensajes previos")
    print(f"Secuencia de tools: {' -> '.join(result.tool_sequence) or '(ninguna)'}")
    print(f"Motivo de parada:   {result.stop_reason} (decisiones: {result.steps}/{MAX_STEPS})")
    print(f"Respuesta final:    {result.final_text}")


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

    tracer = Tracer(session="verify-stage7", console=False)
    llm = LLMClient(tracer=tracer, settings=settings)

    print("\n== ESCENARIO A: con historial ==")
    agent = ExpenseAgent(llm=llm, tracer=tracer)
    conversation = Conversation()
    text_1, text_2 = "Me llamo Diego", "Registra este recibo"
    first = agent.run(text_1, conversation=conversation)
    print_turn("Turno 1", text_1, False, 0, first)
    history_before_turn_2 = len(conversation)
    second = agent.run(text_2, RECEIPT, conversation=conversation)
    print_turn("Turno 2", text_2, True, history_before_turn_2, second)
    print("\nHistorial acumulado (resumen):")
    for line in conversation.summary():
        print(f"    {line}")

    print("\n== ESCENARIO B: negativo, sin historial ==")
    fresh_agent = ExpenseAgent(llm=llm, tracer=tracer)
    negative = fresh_agent.run(text_2, RECEIPT)
    print_turn("Solo turno 2", text_2, True, 0, negative)

    inputs = [e.data for e in tracer.events if e.event_type == EventType.USER_INPUT]
    checks = {
        "A: turno 1 sin tool calls": first.tool_calls == [],
        "A: turno 1 paró por respuesta final": first.stop_reason == "respuesta_final",
        "A: turno 2 envió 2 mensajes de historial": inputs[1]["history_messages"] == 2,
        "A: turno 2 pidió analizar_recibo": "analizar_recibo" in second.tool_sequence,
        "A: turno 2 paró por respuesta final": second.stop_reason == "respuesta_final",
        "A: respuesta del turno 2 contiene 'Diego'": "diego" in second.final_text.lower(),
        "B: sin historial se enviaron 0 mensajes previos": inputs[2]["history_messages"] == 0,
        "B: respuesta NO contiene 'Diego'": "diego" not in negative.final_text.lower(),
    }
    print(f"\nContadores LLM: {llm.stats.as_dict()}")
    print()
    for name, passed in checks.items():
        print(f"    {'OK ' if passed else 'FALLA'} {name}")
    print(f"\nTraza: {tracer.path}")
    ok = all(checks.values())
    print("RESULTADO:", "OK" if ok else "CON FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
