"""Autoriza el acceso a Google Drive y Sheets (flujo OAuth de aplicación de escritorio).

Lo ejecuta el autor (o el revisor) una vez: abre el navegador para dar el
consentimiento y guarda el token en la ruta de `GOOGLE_OAUTH_TOKEN`
(por defecto `secrets/token.json`, ignorada por git).

Requisitos: `GOOGLE_OAUTH_CLIENT_SECRETS` apunta al JSON del cliente OAuth
"Aplicación de escritorio" descargado de Google Cloud (ver docs/setup_google.md).

Importante: con la pantalla de consentimiento en modo "Testing", el token de
renovación caduca a los 7 días
(https://developers.google.com/identity/protocols/oauth2). Cuando eso pase,
vuelve a ejecutar este script.

Uso:
    .venv\\Scripts\\python scripts\\google_auth.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.google_auth import SCOPES, GoogleAuthError, load_credentials, token_exists  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = load_settings()
    print("Scope solicitado (privilegio mínimo):", ", ".join(SCOPES))
    if token_exists(settings):
        print("Ya existe un token; se intentará reutilizarlo o renovarlo antes de pedir consentimiento.")
    try:
        load_credentials(settings, interactive=True)
    except GoogleAuthError as error:
        print(f"ERROR: {error}")
        return 2
    print("Listo: el token quedó guardado en la ruta de GOOGLE_OAUTH_TOKEN.")
    print("Con la pantalla en modo Testing el token caduca a los 7 días; repite este paso entonces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
