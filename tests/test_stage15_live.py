"""Pruebas `live` de la Etapa 15: RAG con el Redis del curso y Gemini reales.

Se omiten si falta GEMINI_API_KEY, LLM_MODEL, REDIS_URL o REDIS_PREFIX. Requieren el índice cargado
(`scripts/load_corpus.py`). El router y el modelo reales deciden las rutas, así que las condiciones
son las de `app/rag/demo.py` (no se relajan). Google queda desactivado: ninguna ruta del RAG lo usa.
"""
import pytest

from app.assistant import ExpenseAssistant
from app.config import config_status, load_settings
from app.llm import LLMClient
from app.models import AgentState, EventType
from app.rag.demo import RAG_CASES, evaluate_rag_case
from app.rag.knowledge import KnowledgeBase
from app.rag.store import RedisVectorStore
from app.trace import Tracer

REQUIRED = ("GEMINI_API_KEY", "LLM_MODEL", "REDIS_URL", "REDIS_PREFIX")
_status = config_status()  # solo presencia de variables, nunca valores
_missing = [n for n in REQUIRED if _status[n] == "falta"]

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(bool(_missing), reason=f"omitida: falta {'/'.join(_missing)}"),
]


@pytest.fixture(scope="module")
def settings():
    return load_settings(required=["llm", "rag"])


@pytest.fixture(scope="module")
def store(settings):
    return RedisVectorStore.from_settings(settings)


@pytest.fixture(scope="module")
def llm(settings):
    return LLMClient(settings=settings)


def run_case(case_id, settings, store, llm):
    case = next(c for c in RAG_CASES if c["id"] == case_id)
    tracer = Tracer(session=f"live-stage15-{case_id}", console=False)
    assistant = ExpenseAssistant(
        llm=llm, tracer=tracer, knowledge_base=KnowledgeBase(store, settings.rag_top_k, settings.rag_threshold)
    )
    result = assistant.handle(case["text"], None, state=AgentState(), tracer=tracer)
    return case, result, tracer


def test_the_index_exists_with_the_expected_configuration_and_documents(store):
    assert store.index_exists()
    info = store.index_info()
    config = info["configurado"]
    assert (config["dimensiones"], config["metrica"], config["algoritmo"], config["tipo_vector"]) == (
        768, "COSINE", "HNSW", "FLOAT32"
    )
    assert info["num_docs"] > 0
    assert info["indice"].endswith(":rag:idx") and info["prefijo_claves"].endswith(":rag:chunk:")
    reported = str(info["atributos"]).upper()
    assert "HNSW" in reported or "VECTOR" in reported  # lo que Redis reporta, no solo lo configurado


def test_an_in_corpus_question_retrieves_above_the_threshold_and_cites_a_source(settings, store, llm):
    case, result, tracer = run_case("a", settings, store, llm)
    checks = evaluate_rag_case(case, result, tracer)
    assert all(checks.values()), (checks, result.final_text)
    retrieval = next(e.data for e in tracer.events if e.event_type == EventType.RETRIEVAL)
    assert retrieval["decision"] == "usar_contexto" and retrieval["mejor_similitud"] >= settings.rag_threshold


def test_an_out_of_corpus_question_abstains_or_is_rejected_without_a_contextual_answer(settings, store, llm):
    case, result, tracer = run_case("c", settings, store, llm)
    checks = evaluate_rag_case(case, result, tracer)
    assert all(checks.values()), (checks, result.final_text)


def test_hola_does_not_retrieve(settings, store, llm):
    case, result, tracer = run_case("b", settings, store, llm)
    assert tracer.count(EventType.RETRIEVAL) == 0
    checks = evaluate_rag_case(case, result, tracer)
    assert all(checks.values()), checks
