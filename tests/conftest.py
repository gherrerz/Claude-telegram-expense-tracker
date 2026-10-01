"""Configuración común de pytest: omite las pruebas `live` sin credenciales."""
import pytest

from app.config import config_status


@pytest.fixture(autouse=True)
def _approving_judge(request, monkeypatch):
    """Etapa 11: las pruebas de las Etapas 2 a 10 usan un juez que siempre aprueba.

    El juez de producción (`app.judge.judge_receipt`) hace una llamada al LLM tras cada
    `analizar_recibo`; los guiones de esas pruebas no la contemplan. Este reemplazo NO aplica a las
    pruebas `live` ni a las marcadas `real_judge` (Etapa 11), que ejecutan el juez de verdad.
    """
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("real_judge"):
        return
    from app import judge
    from app.judge import APROBAR, JudgeVerdict

    def always_approve(image, extracted, llm, tracer=None):
        return JudgeVerdict(veredicto=APROBAR, motivo="juez de prueba: siempre aprueba", senales=[])

    monkeypatch.setattr(judge, "judge_receipt", always_approve)


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
