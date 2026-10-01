"""Credenciales OAuth de usuario para Google Drive y Sheets (flujo de escritorio).

Se usa OAuth de usuario y no una cuenta de servicio porque las cuentas de
servicio no tienen cuota de almacenamiento en Drive y no pueden ser dueñas de
archivos:
https://developers.google.com/workspace/drive/api/guides/about-shareddrives

`load_credentials` nunca abre el navegador salvo con `interactive=True`; el
agente siempre la llama con `interactive=False`. El consentimiento lo hace el
usuario ejecutando `python scripts/google_auth.py`.

Los mensajes de error no incluyen rutas ni contenido de los archivos.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app.config import ROOT, Settings, load_settings

# Un único scope para las Etapas 4 y 5. `drive.file` da acceso solo a los
# archivos que la aplicación crea o abre (no es un scope sensible):
# https://developers.google.com/workspace/drive/api/guides/api-specific-auth
# La API de Sheets lo acepta para planillas creadas por la aplicación:
# https://developers.google.com/workspace/sheets/api/scopes
SCOPES: list[str] = ["https://www.googleapis.com/auth/drive.file"]

SETUP_HINT = "Ejecuta `python scripts/google_auth.py` para autorizar la cuenta de Google."


class GoogleAuthError(Exception):
    """Credenciales de Google ausentes o inválidas. Mensaje seguro, en español."""


def resolve_path(value: str) -> Path:
    """Convierte una ruta de configuración en absoluta (relativa a la raíz del repositorio)."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def token_path(settings: Settings) -> Path:
    """Ruta del archivo `token.json` configurado."""
    return resolve_path(settings.google_oauth_token)


def token_exists(settings: Settings) -> bool:
    """Indica si el archivo de token existe (sin leerlo)."""
    return token_path(settings).is_file()


def _save_token(credentials: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")


def load_credentials(settings: Optional[Settings] = None, interactive: bool = False) -> Any:
    """Carga las credenciales OAuth guardadas y las renueva si expiraron.

    Args:
        settings: configuración; si se omite se lee del entorno.
        interactive: si es `True` y no hay credenciales válidas, abre el flujo de
            consentimiento en el navegador (requiere `GOOGLE_OAUTH_CLIENT_SECRETS`).
            Por defecto es `False`: nunca abre el navegador.

    Raises:
        GoogleAuthError: si falta el token o no se puede renovar (p. ej. expiró
            a los 7 días en modo "Testing"). El mensaje indica cómo resolverlo.
    """
    from google.auth.exceptions import GoogleAuthError as _LibAuthError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    settings = settings if settings is not None else load_settings()
    path = token_path(settings)

    credentials = None
    if path.is_file():
        try:
            credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
        except (ValueError, OSError):
            credentials = None  # archivo corrupto o incompleto

    if credentials is not None and credentials.valid:
        return credentials

    if credentials is not None and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            _save_token(credentials, path)
            return credentials
        except (_LibAuthError, OSError):
            credentials = None  # token revocado o vencido (7 días en modo Testing)

    if not interactive:
        raise GoogleAuthError(
            "No hay credenciales de Google válidas (token ausente, inválido o vencido; "
            "en modo Testing el token caduca a los 7 días). " + SETUP_HINT
        )
    return _run_interactive_flow(settings, path)


def _run_interactive_flow(settings: Settings, path: Path) -> Any:
    if not settings.google_oauth_client_secrets:
        raise GoogleAuthError(
            "Falta GOOGLE_OAUTH_CLIENT_SECRETS (ruta al JSON del cliente OAuth de escritorio). "
            "Consulta docs/setup_google.md."
        )
    secrets_file = resolve_path(settings.google_oauth_client_secrets)
    if not secrets_file.is_file():
        raise GoogleAuthError(
            "El archivo indicado en GOOGLE_OAUTH_CLIENT_SECRETS no existe. "
            "Consulta docs/setup_google.md."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), SCOPES)
    credentials = flow.run_local_server(port=0)  # abre el navegador del usuario
    _save_token(credentials, path)
    return credentials


def build_drive_service(settings: Optional[Settings] = None, interactive: bool = False) -> Any:
    """Cliente de Drive v3 con las credenciales del usuario."""
    from googleapiclient.discovery import build

    credentials = load_credentials(settings, interactive=interactive)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def build_sheets_service(settings: Optional[Settings] = None, interactive: bool = False) -> Any:
    """Cliente de Sheets v4 con las credenciales del usuario (se usa en la Etapa 5)."""
    from googleapiclient.discovery import build

    credentials = load_credentials(settings, interactive=interactive)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)
