"""Pruebas offline de la Etapa 14: acumulador de consumo de todos los clientes LLM del proceso."""
import pytest

from fakes import FakeClient, FakeTime, api_error, ok_response

from app.llm import LLMCallError, LLMClient, reset_session_stats, session_stats
from app.trace import Tracer


@pytest.fixture(autouse=True)
def _clean_session():
    reset_session_stats()
    yield
    reset_session_stats()


def make(script, max_retries=1):
    fake = FakeTime()
    return LLMClient(
        tracer=Tracer(session="t", console=False, write_file=False),
        client=FakeClient(script), model="modelo-de-prueba",
        min_seconds_between_calls=0.0, max_retries=max_retries,
        clock=fake.clock, sleep=fake.sleep,
    )


def test_session_starts_at_zero():
    assert session_stats().as_dict() == dict.fromkeys(session_stats().as_dict(), 0)


def test_session_accumulates_across_clients():
    first = make([ok_response(), ok_response()])
    second = make([ok_response(prompt=100, out=50, thoughts=0, total=150)])
    first.generate_text("a")
    first.generate_text("b")
    second.generate_text("c")
    total = session_stats()
    assert total.calls == 3 and first.stats.calls == 2 and second.stats.calls == 1
    assert total.prompt_tokens == 10 + 10 + 100
    assert total.total_tokens == first.stats.total_tokens + second.stats.total_tokens == 17 + 17 + 150


def test_session_counts_retries_and_failed_calls():
    retried = make([api_error(429, "RESOURCE_EXHAUSTED"), ok_response()])
    retried.generate_text("a")
    failing = make([api_error(400, "INVALID_ARGUMENT")])
    with pytest.raises(LLMCallError):
        failing.generate_text("b")
    total = session_stats()
    assert total.calls == 2 and total.retries == 1 and total.failed_calls == 1


def test_session_stats_returns_a_copy_and_reset_clears_it():
    make([ok_response()]).generate_text("a")
    snapshot = session_stats()
    snapshot.calls = 999  # modificar la copia no altera el acumulador
    assert session_stats().calls == 1
    reset_session_stats()
    assert session_stats().calls == 0 and session_stats().total_tokens == 0
