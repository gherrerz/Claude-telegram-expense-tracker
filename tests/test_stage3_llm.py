"""Pruebas offline de la Etapa 3: cliente LLM con un cliente de Gemini falso."""
import json

import pytest
from google.genai import errors

from fakes import FakeClient, FakeTime, api_error, ok_response

from app.config import Settings
from app.llm import EXTRACTION_TEMPERATURE, LLMCallError, LLMClient
from app.models import EventType
from app.trace import Tracer

FAKE_KEY = "AIza" + "k" * 35  # secreto sintético, no real


def make(script, max_retries=3, min_seconds=0.0, **kwargs):
    fake = FakeTime()
    tracer = Tracer(session="t", console=False, write_file=False)
    client = FakeClient(script)
    llm = LLMClient(
        tracer=tracer, client=client, model="modelo-de-prueba",
        min_seconds_between_calls=min_seconds, max_retries=max_retries,
        clock=fake.clock, sleep=fake.sleep, **kwargs,
    )
    return llm, client, fake, tracer


def test_retry_on_429_emits_retry_and_succeeds():
    llm, client, fake, tracer = make(
        [api_error(429, "RESOURCE_EXHAUSTED"), api_error(429, "RESOURCE_EXHAUSTED"), ok_response()]
    )
    result = llm.generate_text("hola")
    assert result.text == "hola" and result.attempts == 3
    retries = [e for e in tracer.events if e.event_type == EventType.RETRY]
    assert [r.data["attempt"] for r in retries] == [1, 2]
    assert [r.data["wait_seconds"] for r in retries] == [2.0, 4.0]  # exponencial
    assert all(r.data["error_code"] == 429 for r in retries)
    assert fake.sleeps == [2.0, 4.0]
    assert llm.stats.retries == 2 and llm.stats.calls == 1


def test_gives_up_after_max_retries():
    err = api_error(429, "RESOURCE_EXHAUSTED")
    llm, client, fake, tracer = make([err, err, err], max_retries=2)
    with pytest.raises(LLMCallError) as info:
        llm.generate_text("hola")
    assert info.value.code == 429 and info.value.attempts == 3
    assert tracer.count(EventType.RETRY) == 2
    assert llm.stats.failed_calls == 1
    last = tracer.events[-1]
    assert last.event_type == EventType.LLM_DECISION and last.data["status"] == "error"


def test_non_retryable_error_fails_immediately():
    llm, client, fake, tracer = make([api_error(400, "INVALID_ARGUMENT")])
    with pytest.raises(LLMCallError) as info:
        llm.generate_text("hola")
    assert info.value.attempts == 1 and tracer.count(EventType.RETRY) == 0


def test_503_is_retried():
    llm, *_ = make([api_error(503, "UNAVAILABLE"), ok_response()])
    assert llm.generate_text("hola").attempts == 2


def test_min_interval_enforced_with_fake_clock():
    llm, client, fake, tracer = make([ok_response(), ok_response()], min_seconds=4.0)
    llm.generate_text("uno")
    fake.now += 1.0  # solo pasa 1 s entre llamadas
    llm.generate_text("dos")
    assert fake.sleeps == [pytest.approx(3.0)]


def test_no_wait_when_interval_already_elapsed():
    llm, client, fake, tracer = make([ok_response(), ok_response()], min_seconds=4.0)
    llm.generate_text("uno")
    fake.now += 10.0
    llm.generate_text("dos")
    assert fake.sleeps == []


def test_counters_and_usage_traced():
    llm, client, fake, tracer = make([ok_response(), ok_response(prompt=1, out=1, thoughts=0, total=2)])
    llm.generate_text("uno")
    llm.generate_text("dos")
    assert llm.stats.as_dict() == {
        "calls": 2, "failed_calls": 0, "retries": 0, "prompt_tokens": 11,
        "output_tokens": 6, "thinking_tokens": 2, "total_tokens": 19,
    }
    event = tracer.events[0]
    assert event.event_type == EventType.LLM_DECISION
    assert event.data["model"] == "modelo-de-prueba"
    assert event.data["usage"]["prompt_token_count"] == 10
    assert event.data["params"]["temperature"] == EXTRACTION_TEMPERATURE
    assert event.data["system_prompt_id"] == "SMOKE_PROMPT_v1"
    assert event.data["security_scope_id"] == "SECURITY_SCOPE_v2"
    assert "latency_ms" in event.data


def test_system_instruction_includes_security_scope_and_params_sent():
    llm, client, fake, tracer = make([ok_response('{"a": 1}')])
    result = llm.generate_structured(
        "ANALYZER_PROMPT_v1", "x", {"type": "object"}, schema_name="Demo",
        temperature=1.0, thinking_level="LOW",
    )
    assert result.data == {"a": 1}
    config = client.models.calls[0]["config"]
    assert "SECURITY_SCOPE_v2" in config.system_instruction
    assert config.temperature == 1.0
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == {"type": "object"}
    assert config.thinking_config.thinking_level.value == "LOW"
    params = tracer.events[0].data["params"]
    assert params["response_schema"] == "Demo" and params["thinking_level"] == "LOW"
    assert client.models.calls[0]["model"] == "modelo-de-prueba"


def test_structured_invalid_json_reports_error():
    llm, *_ = make([ok_response("esto no es json")])
    result = llm.generate_structured("ANALYZER_PROMPT_v1", "x", {"type": "object"})
    assert result.data is None and "JSON inválido" in result.json_error


def test_api_key_never_in_trace_output(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    tracer = Tracer(session="k", trace_dir=tmp_path)
    err = errors.ClientError(
        429, {"error": {"code": 429, "message": f"clave {FAKE_KEY}", "status": "RESOURCE_EXHAUSTED"}}
    )
    fake = FakeTime()
    llm = LLMClient(
        settings=Settings(gemini_api_key=FAKE_KEY, llm_model="m"), tracer=tracer,
        client=FakeClient([err, ok_response()]), min_seconds_between_calls=0,
        max_retries=2, clock=fake.clock, sleep=fake.sleep,
    )
    llm.generate_text("hola")
    out = capsys.readouterr().out
    file_text = (tmp_path / "k.jsonl").read_text(encoding="utf-8")
    assert FAKE_KEY not in out and FAKE_KEY not in file_text
    assert "RETRY" in file_text


def test_lazy_client_requires_llm_config(monkeypatch):
    from app.config import ConfigError

    for name in ("GEMINI_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.config.ROOT", __import__("pathlib").Path("no-existe"))
    llm = LLMClient(tracer=Tracer(console=False, write_file=False))  # no falla al crear
    with pytest.raises(ConfigError) as info:
        llm.generate_text("hola")
    assert "GEMINI_API_KEY" in str(info.value)


def test_settings_supply_model_and_limits():
    settings = Settings(
        gemini_api_key="x", llm_model="gemini-de-prueba", llm_max_retries=7,
        llm_min_seconds_between_calls=1.5,
    )
    llm = LLMClient(settings=settings, client=FakeClient([]))
    assert (llm.model, llm.max_retries, llm.min_seconds) == ("gemini-de-prueba", 7, 1.5)
    json.dumps(llm.stats.as_dict())  # serializable
