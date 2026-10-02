"""Lectura única de la configuración desde variables de entorno.

Este módulo es el único lugar del proyecto que lee el entorno. Nunca imprime
ni incluye valores en los mensajes de error: solo nombres de variables.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_LLM_MAX_RETRIES = 5
DEFAULT_LLM_MIN_SECONDS_BETWEEN_CALLS = 4.0
# Ruta por defecto (relativa a la raíz del repositorio) del token OAuth de Google.
DEFAULT_GOOGLE_OAUTH_TOKEN = "secrets/token.json"

# Etapa 15 (RAG con el Redis del curso, adenda A14). El modelo de embeddings y sus dimensiones
# son constantes del código, no variables de entorno: el índice vectorial se crea con ellas y
# cambiarlas obliga a reindexar (la firma del corpus las incluye).
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMS = 768
DEFAULT_RAG_TOP_K = 3
MAX_RAG_TOP_K = 10
# Calibrado el 2026-10-02 con `scripts/calibrate_rag_threshold.py` contra el índice real: peor
# acierto dentro del corpus 0.7929, mejor desacierto fuera del corpus 0.6988 (margen 0.0941).
# 0.75 queda dentro del margen. Se puede sobrescribir con `RAG_THRESHOLD`.
DEFAULT_RAG_THRESHOLD = 0.75
# Prefijo de grupo en el Redis compartido: solo letras, números, guion y guion bajo. Excluye los
# comodines de patrón (`*?[]`) y los dos puntos, así ningún prefijo puede alcanzar claves ajenas.
REDIS_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")

# Variables obligatorias por grupo de uso.
REQUIRED_BY_GROUP: dict[str, tuple[str, ...]] = {
    "llm": ("GEMINI_API_KEY", "LLM_MODEL"),
    "google": ("GOOGLE_OAUTH_CLIENT_SECRETS", "DRIVE_FOLDER_ID", "SHEET_ID"),
    "telegram": ("TELEGRAM_BOT_TOKEN",),
    "rag": ("REDIS_URL", "REDIS_PREFIX"),
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
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "REDIS_URL",
    "REDIS_PREFIX",
)

# `RAG_TOP_K` y `RAG_THRESHOLD` son opcionales y NO forman parte de `ALL_VARIABLES`: son ajustes
# con valor por defecto en el código, así que `.env.example` no está obligado a declararlos.

# Variables cuyo valor es secreto (las usa el trazador para enmascarar).
SECRET_VARIABLES: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_OAUTH_CLIENT_SECRETS",
    "GOOGLE_OAUTH_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "REDIS_URL",  # la URL incluye la contraseña del Redis del curso
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
    # Chats autorizados (Etapa 13). Vacío = sin restricción (el bot lo avisa al iniciar).
    telegram_allowed_chat_ids: tuple[int, ...] = ()
    # RAG (Etapa 15): Redis del curso. `redis_url` es secreta (incluye la contraseña).
    redis_url: Optional[str] = None
    redis_prefix: Optional[str] = None
    rag_top_k: int = DEFAULT_RAG_TOP_K
    rag_threshold: float = DEFAULT_RAG_THRESHOLD

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

    allowed_chat_ids: list[int] = []
    raw = _clean(source, "TELEGRAM_ALLOWED_CHAT_IDS")
    if raw is not None:
        try:
            allowed_chat_ids = [int(item) for item in raw.split(",") if item.strip()]
        except ValueError:
            raise ConfigError(
                ["TELEGRAM_ALLOWED_CHAT_IDS"],
                "Valores inválidos (se espera una lista de enteros separados por comas)",
            ) from None

    redis_prefix = _clean(source, "REDIS_PREFIX")
    if redis_prefix is not None and not REDIS_PREFIX_PATTERN.fullmatch(redis_prefix):
        raise ConfigError(
            ["REDIS_PREFIX"], "Valores inválidos (se admiten letras, números, guion y guion bajo)"
        )
    rag_top_k = DEFAULT_RAG_TOP_K
    raw = _clean(source, "RAG_TOP_K")
    if raw is not None:
        try:
            rag_top_k = int(raw)
            if not 1 <= rag_top_k <= MAX_RAG_TOP_K:
                raise ValueError
        except ValueError:
            raise ConfigError(
                ["RAG_TOP_K"], f"Valores inválidos (se espera un entero entre 1 y {MAX_RAG_TOP_K})"
            ) from None
    rag_threshold = DEFAULT_RAG_THRESHOLD
    raw = _clean(source, "RAG_THRESHOLD")
    if raw is not None:
        try:
            rag_threshold = float(raw)
            if not 0.0 <= rag_threshold <= 1.0:
                raise ValueError
        except ValueError:
            raise ConfigError(
                ["RAG_THRESHOLD"], "Valores inválidos (se espera un número entre 0 y 1)"
            ) from None

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
        telegram_allowed_chat_ids=tuple(allowed_chat_ids),
        redis_url=_clean(source, "REDIS_URL"),
        redis_prefix=redis_prefix,
        rag_top_k=rag_top_k,
        rag_threshold=rag_threshold,
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
