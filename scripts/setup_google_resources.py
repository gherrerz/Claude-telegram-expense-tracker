"""Crea la carpeta y la planilla de PRUEBA en el Google Drive del usuario.

Con el scope `drive.file` la aplicación solo ve los archivos que ella misma
crea, por eso la carpeta y la planilla se crean por API y no a mano. Solo
se crean recursos; no se agrega ninguna fila de gastos (eso es la Etapa 5).

Es "casi idempotente": si `DRIVE_FOLDER_ID` o `SHEET_ID` ya están definidos
en el entorno, ese recurso no se vuelve a crear. Para crearlo de nuevo, deja
la variable vacía en `.env`.

Imprime los IDs para que los pegues en `.env`. Requiere haber ejecutado antes
`scripts/google_auth.py`.

Uso:
    .venv\\Scripts\\python scripts\\setup_google_resources.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from googleapiclient.errors import HttpError  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.google_auth import (  # noqa: E402
    GoogleAuthError,
    build_drive_service,
    build_sheets_service,
)

FOLDER_NAME = "Expense Tracker - Prueba"
SHEET_TITLE = "Expense Tracker - Prueba (gastos)"
SHEET_HEADER = ["Fecha", "Comercio", "Monto", "Categoría", "Recibo_URL"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def create_folder(drive) -> dict:
    """Crea la carpeta de prueba y devuelve `id`, `name` y `webViewLink` de la API."""
    return (
        drive.files()
        .create(body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME}, fields="id,name,webViewLink")
        .execute()
    )


def create_spreadsheet(sheets) -> dict:
    """Crea la planilla con solo la fila de encabezado (sin filas de datos)."""
    header_row = {
        "values": [{"userEnteredValue": {"stringValue": title}} for title in SHEET_HEADER]
    }
    body = {
        "properties": {"title": SHEET_TITLE},
        "sheets": [
            {"data": [{"startRow": 0, "startColumn": 0, "rowData": [header_row]}]},
        ],
    }
    return sheets.spreadsheets().create(body=body, fields="spreadsheetId,spreadsheetUrl").execute()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = load_settings()
    try:
        drive = build_drive_service(settings)
        sheets = build_sheets_service(settings)
    except GoogleAuthError as error:
        print(f"ERROR: {error}")
        return 2

    lines: list[str] = []
    try:
        if settings.drive_folder_id:
            print("DRIVE_FOLDER_ID ya está definido: no se crea otra carpeta.")
        else:
            folder = create_folder(drive)
            print(f"Carpeta creada: {folder.get('name')} -> {folder.get('webViewLink')}")
            lines.append(f"DRIVE_FOLDER_ID={folder['id']}")
        if settings.sheet_id:
            print("SHEET_ID ya está definido: no se crea otra planilla.")
        else:
            sheet = create_spreadsheet(sheets)
            print(f"Planilla creada con encabezado {' | '.join(SHEET_HEADER)} -> {sheet.get('spreadsheetUrl')}")
            lines.append(f"SHEET_ID={sheet['spreadsheetId']}")
    except HttpError as error:
        status = getattr(getattr(error, "resp", None), "status", "?")
        print(f"ERROR: la API de Google respondió HTTP {status}. Revisa que Drive API y Sheets API estén habilitadas.")
        failed = True
    else:
        failed = False

    if lines:
        print("\nPega estas líneas en tu .env (los IDs no son secretos):")
        for line in lines:
            print("  " + line)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
