"""Verificación real de la Etapa 4 (la ejecuta el autor con su `.env` y su token).

Sube `data/receipts/receipt_normal.jpg` a la carpeta de prueba de Drive
(`DRIVE_FOLDER_ID`) y confirma con `files.get` que el `file_id` existe.
Imprime `file_id`, nombre y `webViewLink` (tomado de la respuesta de la API).

Si falta la configuración o el token, sale con código 2 sin llamar a la red.
Escribe la traza en `traces/verify-stage4.jsonl`.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.google_auth import GoogleAuthError, build_drive_service, token_exists  # noqa: E402
from app.tools.drive import guardar_recibo, verify_file_exists  # noqa: E402
from app.trace import Tracer  # noqa: E402

RECEIPT = ROOT / "data" / "receipts" / "receipt_normal.jpg"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    status = config_status()
    problems = []
    if status["DRIVE_FOLDER_ID"] == "falta":
        problems.append("falta DRIVE_FOLDER_ID (ejecuta scripts/setup_google_resources.py)")
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

    tracer = Tracer(session="verify-stage4", console=False)
    try:
        service = build_drive_service(settings)
    except GoogleAuthError as error:
        print(f"ERROR: {error} No se hizo ninguna llamada de red de la tool.")
        return 2

    print(f"[1] Subiendo {RECEIPT.name} a la carpeta de prueba")
    result = guardar_recibo(
        RECEIPT, "Comercio de Prueba", "2026-09-30", service=service, tracer=tracer, settings=settings
    )
    if not result.success:
        print(f"    FALLÓ: {result.error}")
        print(f"Traza: {tracer.path}")
        return 1
    print(f"    file_id:       {result.file_id}")
    print(f"    file_name:     {result.file_name}")
    print(f"    webViewLink:   {result.web_view_link}")

    print("\n[2] Confirmando con files.get")
    try:
        meta = verify_file_exists(result.file_id, service)
    except Exception as error:  # noqa: BLE001 - se informa solo el tipo
        print(f"    FALLÓ la consulta: {type(error).__name__}")
        return 1
    if meta is None or meta.get("trashed"):
        print("    El archivo NO existe (o está en la papelera).")
        return 1
    parents_ok = settings.drive_folder_id in (meta.get("parents") or [])
    print(f"    existe: id={meta['id']} nombre={meta.get('name')} tipo={meta.get('mimeType')}")
    print(f"    está en la carpeta de prueba: {parents_ok}")

    print(f"\nTraza: {tracer.path}")
    ok = parents_ok
    print("RESULTADO:", "OK" if ok else "CON FALLAS (el archivo no está en la carpeta esperada)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
