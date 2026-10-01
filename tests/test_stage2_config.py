"""Pruebas de la Etapa 2: configuración."""
import dataclasses
from pathlib import Path

import pytest

import app
from app.config import (
    ALL_VARIABLES,
    ConfigError,
    config_status,
    load_settings,
)

ROOT = Path(__file__).resolve().parents[1]

# Valores sintéticos construidos en tiempo de ejecución.
FAKE_KEY = "AIza" + "x" * 35
FAKE_TOKEN = "123456789:" + "y" * 35

EXAMPLE_ENV = {
    "GEMINI_API_KEY": FAKE_KEY,
    "LLM_MODEL": "modelo-de-prueba",
    "GOOGLE_APPLICATION_CREDENTIALS": "ruta/falsa.json",
    "DRIVE_FOLDER_ID": "carpeta-de-prueba",
    "SHEET_ID": "planilla-de-prueba",
    "TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
}


def test_app_imports():
    assert app is not None


def test_load_full_example_with_defaults():
    settings = load_settings(["llm", "google", "telegram"], env=EXAMPLE_ENV)
    assert settings.llm_model == "modelo-de-prueba"
    assert settings.llm_max_retries == 5
    assert settings.llm_min_seconds_between_calls == 4.0


def test_numeric_overrides():
    env = {**EXAMPLE_ENV, "LLM_MAX_RETRIES": "3", "LLM_MIN_SECONDS_BETWEEN_CALLS": "1.5"}
    settings = load_settings(["llm"], env=env)
    assert settings.llm_max_retries == 3
    assert settings.llm_min_seconds_between_calls == 1.5


def test_only_required_groups_are_validated():
    env = {"GEMINI_API_KEY": FAKE_KEY, "LLM_MODEL": "m"}
    assert load_settings(["llm"], env=env).telegram_bot_token is None
    with pytest.raises(ConfigError):
        load_settings(["llm", "telegram"], env=env)


def test_settings_is_frozen():
    settings = load_settings(["llm"], env=EXAMPLE_ENV)
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.llm_model = "otro"  # type: ignore[misc]


def test_missing_error_lists_names_not_values():
    env = {"GEMINI_API_KEY": FAKE_KEY}
    with pytest.raises(ConfigError) as exc:
        load_settings(["llm", "google"], env=env)
    message = str(exc.value)
    for name in ("LLM_MODEL", "DRIVE_FOLDER_ID", "SHEET_ID"):
        assert name in message
    assert FAKE_KEY not in message
    assert ".env.example" in message


def test_invalid_number_error_has_no_values():
    env = {**EXAMPLE_ENV, "LLM_MAX_RETRIES": "abc-secreto"}
    with pytest.raises(ConfigError) as exc:
        load_settings(["llm"], env=env)
    assert "LLM_MAX_RETRIES" in str(exc.value)
    assert "abc-secreto" not in str(exc.value)


def test_unknown_group_rejected():
    with pytest.raises(ConfigError):
        load_settings(["inexistente"], env={})


def test_config_status_reports_presence_only():
    status = config_status({"GEMINI_API_KEY": FAKE_KEY})
    assert status["GEMINI_API_KEY"] == "definida"
    assert status["SHEET_ID"] == "falta"
    assert set(status) == set(ALL_VARIABLES)
    assert FAKE_KEY not in str(status)


def test_settings_repr_hides_values():
    settings = load_settings(["llm"], env=EXAMPLE_ENV)
    assert FAKE_KEY not in repr(settings)


def test_every_settings_variable_is_declared_in_env_example():
    declared = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            declared.add(line.partition("=")[0].strip())
    missing = [name for name in ALL_VARIABLES if name not in declared]
    assert not missing, f".env.example no declara: {missing}"
