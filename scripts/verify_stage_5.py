"""Verificación real de la Etapa 5 (la ejecuta el autor con su `.env` y su token).

Flujo (todo en la carpeta y la planilla de PRUEBA):
  ANTES   conteo de filas de datos y última fila de la planilla.
  LLAMADA sube `receipt_normal.jpg` a Drive y registra el gasto con los valores de
          `data/receipts/expected.json` (la fila queda enlazada al archivo subido).
  DESPUÉS el conteo debe subir en 1 y la última fila debe coincidir.
  REPETIR la misma llamada: debe devolver `duplicate=True` y dejar el conteo igual.

El comercio real ("Los Aromos") se registraría una sola vez; para poder re-ejecutar el
script sin que la deduplicación lo trate como repetido, se agrega el sufijo
"(verificación <marca UTC>)". La deduplicación sí se ejercita con la repetición inmediata.

Si falta la configuración o el token, sale con código 2 sin llamar a la red.
Escribe la traza en `traces/verify-stage5.jsonl`.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_5.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.google_auth import (  # noqa: E402
    GoogleAuthError,
    build_drive_service,
    build_sheets_service,
    token_exists,
)
from app.tools.drive import guardar_recibo  # noqa: E402
from app.tools.sheets import get_sheet_snapshot, registrar_gasto  # noqa: E402
from app.trace import Tracer  # noqa: E402

RECEIPT = ROOT / "data" / "receipts" / "receipt_normal.jpg"
EXPECTED = ROOT / "data" / "receipts" / "expected.json"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    status = config_status()
    problems = []
    for name in ("DRIVE_FOLDER_ID", "SHEET_ID"):
        if status[name] == "falta":
            problems.append(f"falta {name} (ejecuta scripts/setup_google_resources.py)")
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"ERROR: {error}")
        return 2
    if not token_exists(settings):
        problems.append("falta el token OAuth (ejecuta scripts/google_auth.py)")
    if problems:
        print("ERROR: " + "; ".join(problems) + ". Consulta docs/setup_google.md. "
              "No se hizo ninguna llamada de red.")
        return 2

    tracer = Tracer(session="verify-stage5", console=False)
    try:
        drive = build_drive_service(settings)
        sheets = build_sheets_service(settings)
    except GoogleAuthError as error:
        print(f"ERROR: {error} No se hizo ninguna llamada de red de la tool.")
        return 2

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))["receipt_normal.jpg"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    comercio = f"{expected['comercio']} (verificación {stamp})"

    try:
        print("== ANTES ==")
        before = get_sheet_snapshot(sheets, settings)
        print(f"    filas de datos: {before['row_count']}")
        print(f"    última fila:    {before['last_row']}")

        print("\n== LLAMADA ==")
        upload = guardar_recibo(RECEIPT, comercio, expected["fecha"], service=drive,
                                tracer=tracer, settings=settings)
        if not upload.success:
            print(f"    FALLÓ la subida a Drive: {upload.error}")
            return 1
        print(f"    recibo en Drive: {upload.web_view_link}")
        args = dict(
            fecha=expected["fecha"],
            comercio=comercio,
            monto=expected["monto"],
            categoria=expected["categoria"],
            recibo_url=upload.web_view_link,
            service=sheets,
            tracer=tracer,
            settings=settings,
        )
        result = registrar_gasto(**args)
        print(f"    resultado: {result.model_dump()}")
        if not result.success:
            return 1

        print("\n== DESPUÉS ==")
        after = get_sheet_snapshot(sheets, settings)
        print(f"    filas de datos: {after['row_count']}")
        print(f"    última fila:    {after['last_row']}")

        print("\n== REPETIR (misma llamada) ==")
        repeated = registrar_gasto(**args)
        print(f"    resultado: {repeated.model_dump()}")
        final = get_sheet_snapshot(sheets, settings)
        print(f"    filas de datos: {final['row_count']}")
    except Exception as error:  # noqa: BLE001 - se informa solo el tipo
        print(f"    FALLÓ la consulta a la planilla: {type(error).__name__}")
        return 1

    last = after["last_row"] or []
    checks = {
        "conteo +1": after["row_count"] == before["row_count"] + 1,
        "última fila coincide": last[:4] == [expected["fecha"], comercio, expected["monto"],
                                             expected["categoria"]],
        "repetición marcada duplicate": repeated.duplicate is True and not repeated.success,
        "repetición apunta a la misma fila": repeated.row_number == result.row_number,
        "conteo sin cambio tras repetir": final["row_count"] == after["row_count"],
    }
    for name, passed in checks.items():
        print(f"    {'OK ' if passed else 'FALLA'} {name}")
    print(f"\nTraza: {tracer.path}")
    ok = all(checks.values())
    print("RESULTADO:", "OK" if ok else "CON FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
