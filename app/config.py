"""Lectura única de la configuración desde variables de entorno.

Este módulo es el único lugar del proyecto que lee el entorno. Nunca imprime
ni incluye valores en los mensajes de error: solo nombres de variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_LLM_MAX_RETRIES = 5
DEFAULT_LLM_MIN_SECONDS_BETWEEN_CALLS = 4.0
# Ruta por defecto (relativa a la raíz del repositorio) del token OAuth de Google.
DEFAULT_GOOGLE_OAUTH_TOKEN = "secrets/token.json"

# Variables obligatorias por grupo de uso.
REQUIRED_BY_GROUP: dict[str, tuple[str, ...]] = {
    "llm": ("GEMINI_API_KEY", "LLM_MODEL"),
    "google": ("GOOGLE_OAUTH_CLIENT_SECRETS", "DRIVE_FOLDER_ID", "SHEET_ID"),
    "telegram": ("TELEGRAM_BOT_TOKEN",),
}

ALL_VARIABLES: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "LLM_MODEL",
    "LLM_MAX_RETRIES",
    "LLM_MIN_SECONDS_BETWEEN_CALLS",
    "GOOGLE_OAUTH_CLIENT_SECRETS",
    "GOOGLE_OAUTH_TOKEN",
    "DRIVE_FOLDER_ID",
    "SHEET_ID",
    "TELEGRAM_BOT_TOKEN",
)

# Variables cuyo valor es secreto (las usa el trazador para enmascarar).
SECRET_VARIABLES: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_OAUTH_CLIENT_SECRETS",
    "GOOGLE_OAUTH_TOKEN",
    "TELEGRAM_BOT_TOKEN",
)


class ConfigError(Exception):
    """Configuración ausente o inválida. El mensaje solo contiene nombres."""

    def __init__(self, names: list[str], reason: str) -> None:
        self.names = list(names)
        super().__init__(
            f"{reason}: {', '.join(self.names)}. "
            "Revisa el archivo .env y consulta .env.example para ver el formato."
        )


@dataclass(frozen=True)
class Settings:
    """Configuración inmutable del agente."""

    gemini_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES
    llm_min_seconds_between_calls: float = DEFAULT_LLM_MIN_SECONDS_BETWEEN_CALLS
    google_oauth_client_secrets: Optional[str] = None
    google_oauth_token: str = DEFAULT_GOOGLE_OAUTH_TOKEN
    drive_folder_id: Optional[str] = None
    sheet_id: Optional[str] = None
    telegram_bot_token: Optional[str] = None

    def __repr__(self) -> str:  # evita filtrar secretos por accidente
        return "Settings(<oculto>)"


def _clean(env: Mapping[str, str], name: str) -> Optional[str]:
    value = env.get(name)
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _resolve_env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    if env is not None:
        return env
    dotenv_path = ROOT / ".env"
    if dotenv_path.is_file():
        load_dotenv(dotenv_path, override=False)
    return os.environ


def load_settings(
    required: tuple[str, ...] | list[str] = (),
    env: Optional[Mapping[str, str]] = None,
) -> Settings:
    """Carga y valida la configuración.

    Args:
        required: grupos a validar ("llm", "google", "telegram"). Los demás
            grupos pueden estar incompletos.
        env: mapeo opcional que reemplaza al entorno (útil en pruebas). Si se
            omite, se carga `.env` (si existe) y se usa `os.environ`.

    Raises:
        ConfigError: si falta una variable de un grupo requerido o si un valor
            numérico no es válido. Solo se informan nombres de variables.
    """
    source = _resolve_env(env)

    unknown = [g for g in required if g not in REQUIRED_BY_GROUP]
    if unknown:
        raise ConfigError(unknown, "Grupos de configuración desconocidos")

    missing = [
        name
        for group in required
        for name in REQUIRED_BY_GROUP[group]
        if _clean(source, name) is None
    ]
    if missing:
        raise ConfigError(missing, "Faltan variables de entorno")

    invalid: list[str] = []
    retries = DEFAULT_LLM_MAX_RETRIES
    raw = _clean(source, "LLM_MAX_RETRIES")
    if raw is not None:
        try:
            retries = int(raw)
            if retries < 0:
                raise ValueError
        except ValueError:
            invalid.append("LLM_MAX_RETRIES")
    pause = DEFAULT_LLM_MIN_SECONDS_BETWEEN_CALLS
    raw = _clean(source, "LLM_MIN_SECONDS_BETWEEN_CALLS")
    if raw is not None:
        try:
            pause = float(raw)
            if pause < 0 or pause != pause:
                raise ValueError
        except ValueError:
            invalid.append("LLM_MIN_SECONDS_BETWEEN_CALLS")
    if invalid:
        raise ConfigError(invalid, "Valores inválidos (se espera un número no negativo)")

    # Las variables OAuth son RUTAS a archivos JSON. Si contienen el client
    # secret (prefijo GOCSPX-), el token terminaría guardado en un archivo con
    # el secreto como nombre.
    bad_paths = [
        name
        for name in ("GOOGLE_OAUTH_CLIENT_SECRETS", "GOOGLE_OAUTH_TOKEN")
        if (value := _clean(source, name)) is not None
        and (value.startswith("GOCSPX-") or not value.lower().endswith(".json"))
    ]
    if bad_paths:
        raise ConfigError(
            bad_paths,
            "Valores inválidos (se espera la ruta a un archivo .json, no el secreto)",
        )

    return Settings(
        gemini_api_key=_clean(source, "GEMINI_API_KEY"),
        llm_model=_clean(source, "LLM_MODEL"),
        llm_max_retries=retries,
        llm_min_seconds_between_calls=pause,
        google_oauth_client_secrets=_clean(source, "GOOGLE_OAUTH_CLIENT_SECRETS"),
        google_oauth_token=_clean(source, "GOOGLE_OAUTH_TOKEN") or DEFAULT_GOOGLE_OAUTH_TOKEN,
        drive_folder_id=_clean(source, "DRIVE_FOLDER_ID"),
        sheet_id=_clean(source, "SHEET_ID"),
        telegram_bot_token=_clean(source, "TELEGRAM_BOT_TOKEN"),
    )


def config_status(env: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """Devuelve {VARIABLE: "definida" | "falta"} sin exponer valores."""
    source = _resolve_env(env)
    return {
        name: "definida" if _clean(source, name) is not None else "falta"
        for name in ALL_VARIABLES
    }


def secret_values(env: Optional[Mapping[str, str]] = None) -> list[str]:
    """Valores secretos actualmente definidos (solo para enmascarar)."""
    source = env if env is not None else os.environ
    values = [_clean(source, name) for name in SECRET_VARIABLES]
    return [v for v in values if v]
