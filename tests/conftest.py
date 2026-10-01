"""Configuración común de pytest: omite las pruebas `live` sin credenciales."""
import pytest

from app.config import config_status


def pytest_collection_modifyitems(config, items):
    # Las pruebas de Google (Etapas 4 y 5) se omiten por su propia condición.
    live_items = [
        item
        for item in items
        if "live" in item.keywords and "stage4" not in item.nodeid and "stage5" not in item.nodeid
    ]
    if not live_items:
        return
    status = config_status()  # solo presencia de variables, nunca valores
    missing = [n for n in ("GEMINI_API_KEY", "LLM_MODEL") if status[n] == "falta"]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"omitida: falta {'/'.join(missing)}")
    for item in live_items:
        item.add_marker(skip)
