"""Verificación real de la Etapa 10: memoria avanzada (la ejecuta el autor con su `.env` y su token).

Requiere Gemini Y Google (Drive y Sheets de PRUEBA): el ciclo escribe en la carpeta y la planilla de
prueba. Genera en tiempo de ejecución un recibo sintético ÚNICO (`Minimarket Prueba <HHMMSS>`, monto
derivado de la hora, datos ficticios) en una carpeta temporal, de modo que cada ejecución agrega filas
nuevas. Todo pasa por `ExpenseAssistant` con UNA conversación y UN `AgentState`:

  0) estado inicial (vacío).
  1) "Me llamo Ana"                          -> `nombre_usuario` en el estado (MEMORY_UPDATE).
  2) imagen + "Registra este recibo"         -> registrado; MEMORY_UPDATE con los totales.
  3) "¿Cuánto llevo gastado en <categoría>?" -> CONSULTAR_GASTOS; la respuesta contiene el total del estado.
  4) la misma imagen + "Registra este recibo" -> duplicado detectado: 0 ejecuciones de guardar/registrar
                                                (ni Drive ni planilla), queda una confirmación pendiente.
  5) "Sí, regístralo de todas formas"        -> turno posterior: registrado con `permitir_duplicado`; los
                                                totales se duplican.

Las ejecuciones reales de las tools se cuentan con envoltorios (`app/memory_demo.py`), no con los eventos
TOOL_CALL del agente. Tras cada paso imprime el estado y las comprobaciones OK/FALLA; al final `RESULTADO`.
Los criterios son condiciones, no texto exacto: la ruta que elige el router y lo que responde el LLM
dependen del modelo, y una condición que no se cumple se informa como FALLA sin relajarla.

Si falta la configuración de Gemini o de Google, o el token, sale con código 2 sin llamar a la red.
Escribe la traza en `traces/verify-stage10.jsonl`.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_10.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.assistant import ExpenseAssistant  # noqa: E402
from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.conversation import Conversation  # noqa: E402
from app.google_auth import GoogleAuthError, build_sheets_service, token_exists  # noqa: E402
from app.llm import LLMCallError, LLMClient  # noqa: E402
from app.memory import state_snapshot  # noqa: E402
from app.memory_demo import StepReport, live_tools, run_memory_cycle  # noqa: E402
from app.models import AgentState  # noqa: E402
from app.prompts import SECURITY_SCOPE_ID  # noqa: E402
from app.tools.sheets import get_sheet_snapshot  # noqa: E402
from app.trace import Tracer  # noqa: E402
from generate_receipts import generate_unique_receipt  # noqa: E402


def missing_configuration() -> list[str]:
    """Problemas de configuración que impiden la verificación real (solo presencia, sin valores)."""
    status = config_status()
    problems = [
        f"falta {name}" for name in ("GEMINI_API_KEY", "LLM_MODEL") if status[name] == "falta"
    ]
    problems += [
        f"falta {name} (scripts/setup_google_resources.py)"
        for name in ("DRIVE_FOLDER_ID", "SHEET_ID")
        if status[name] == "falta"
    ]
    try:
        if not token_exists(load_settings()):
            problems.append("falta el token OAuth (scripts/google_auth.py)")
    except ConfigError as error:
        problems.append(str(error))
    return problems


def print_step(step: StepReport) -> None:
    print(f"\n--- Paso {step.id}) {step.name} ---")
    print(f"Entrada:            {step.text}{' [+ imagen única]' if step.with_image else ''}")
    print(f"Evento ROUTE:       {json.dumps(step.route_event, ensure_ascii=False)}")
    print(f"Tools ejecutadas:   guardar_recibo x{step.tool_runs['guardar_recibo']}, "
          f"registrar_gasto x{step.tool_runs['registrar_gasto']} (reales, contadas por envoltorio)")
    print(f"Motivo de parada:   {step.result.stop_reason}")
    print(f"Respuesta final:    {step.result.final_text}")
    for event in step.memory_events:
        print(f"MEMORY_UPDATE:      {json.dumps(event, ensure_ascii=False)}")
    if step.sheet_rows is not None:
        print(f"Filas de la planilla: {step.sheet_rows}")
    print(f"Estado:             {json.dumps(step.state, ensure_ascii=False)}")
    for name, passed in step.checks.items():
        print(f"    {'OK ' if passed else 'FALLA'} {name}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    problems = missing_configuration()
    if problems:
        print(
            f"ERROR: {'; '.join(problems)}.\n"
            "Esta verificación necesita Gemini y Google (carpeta y planilla de prueba, token OAuth). "
            "Copia .env.example a .env, completa los valores y ejecuta scripts/google_auth.py. "
            "No se hizo ninguna llamada de red."
        )
        return 2
    try:
        settings = load_settings(required=["llm", "google"])
        sheets = build_sheets_service(settings)
    except (ConfigError, GoogleAuthError) as error:
        print(f"ERROR: {error}")
        return 2

    print(f"Bloque de alcance: {SECURITY_SCOPE_ID}")
    tracer = Tracer(session="verify-stage10", console=False)
    llm = LLMClient(settings=settings, tracer=tracer)
    state = AgentState()
    with tempfile.TemporaryDirectory(prefix="stage10_") as tmp:
        image, expected = generate_unique_receipt(Path(tmp))
        print(f"Recibo único generado (ficticio): {expected['comercio']} | {expected['fecha']} | "
              f"monto {expected['monto']} | categoría sugerida {expected['categoria']}")
        tools, counts = live_tools()
        assistant = ExpenseAssistant(llm=llm, tracer=tracer, tool_overrides=tools)
        print("\n--- Paso 0) estado inicial ---")
        print(f"Estado:             {json.dumps(state_snapshot(state), ensure_ascii=False)}")
        try:
            report = run_memory_cycle(
                assistant, counts, image, float(expected["monto"]), tracer,
                conversation=Conversation(), state=state,
                row_count=lambda: get_sheet_snapshot(sheets, settings)["row_count"],
                on_step=print_step,
            )
        except LLMCallError as error:
            print(f"\nLa API falló tras los reintentos: {error}")
            print("RESULTADO: CON FALLAS (ciclo incompleto)")
            return 1

    print(f"\nContadores LLM: {llm.stats.as_dict()}")
    print(f"Ejecuciones reales: {counts}")
    print("RESULTADO:", "OK" if report.ok else "CON FALLAS")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
