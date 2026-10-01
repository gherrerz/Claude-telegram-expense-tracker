"""Pruebas de la Etapa 2: trazador y enmascarado de secretos."""
import json

import pytest

from app.models import EventType
from app.trace import MASK, Tracer, mask_value

# Secretos sintéticos construidos en tiempo de ejecución (no literales).
FAKE_GOOGLE_KEY = "AIza" + "x" * 35
FAKE_TELEGRAM = "123456789:" + "y" * 35
FAKE_PEM = "-----BEGIN " + "PRIVATE KEY-----\nabcdef\n-----END " + "PRIVATE KEY-----"
FAKE_CRED_PATH = "C:\\secretos\\mi-credentials.json"


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_secrets_masked_in_console_and_file(tmp_path, capsys):
    tracer = Tracer(session="s1", trace_dir=tmp_path)
    tracer.record(
        EventType.TOOL_CALL,
        {
            "api_key": FAKE_GOOGLE_KEY,
            "nota": f"usando {FAKE_GOOGLE_KEY} y {FAKE_TELEGRAM}",
            "header": "Bearer abc.def-123",
            "pem": FAKE_PEM,
            "ruta": f"cargué {FAKE_CRED_PATH}",
        },
    )
    out = capsys.readouterr().out
    file_text = (tmp_path / "s1.jsonl").read_text(encoding="utf-8")
    for text in (out, file_text):
        assert MASK in text
        assert FAKE_GOOGLE_KEY not in text
        assert FAKE_TELEGRAM not in text
        assert "abc.def-123" not in text
        assert "abcdef" not in text
        assert "mi-credentials.json" not in text


def test_nested_structures_are_masked():
    data = {
        "a": [{"token": "valor-secreto"}, ("x", f"k={FAKE_GOOGLE_KEY}")],
        "b": {"c": {"password": "p4ss", "ok": "texto normal", "n": 3}},
    }
    result = mask_value(data)
    assert result["a"][0]["token"] == MASK
    assert FAKE_GOOGLE_KEY not in json.dumps(result)
    assert result["b"]["c"]["password"] == MASK
    assert result["b"]["c"]["ok"] == "texto normal"
    assert result["b"]["c"]["n"] == 3


def test_usage_metrics_and_dedup_keys_are_not_masked():
    data = {
        "usage": {"prompt_token_count": 120, "candidates_token_count": 35},
        "dedup_key": "hash-recibo-1",
        "bot_token": "valor-secreto",
    }
    result = mask_value(data)
    assert result["usage"] == {"prompt_token_count": 120, "candidates_token_count": 35}
    assert result["dedup_key"] == "hash-recibo-1"
    assert result["bot_token"] == MASK


def test_env_secret_values_are_masked(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "valor-corto-de-prueba")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS", "/ruta/rara/archivo.txt")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN", "/ruta/rara/otro-token.txt")
    result = mask_value(
        {"texto": "x valor-corto-de-prueba y /ruta/rara/archivo.txt y /ruta/rara/otro-token.txt"}
    )
    assert "valor-corto-de-prueba" not in result["texto"]
    assert "/ruta/rara/archivo.txt" not in result["texto"]
    assert "/ruta/rara/otro-token.txt" not in result["texto"]


def test_extra_secrets_are_masked(tmp_path):
    tracer = Tracer(session="s2", trace_dir=tmp_path, console=False, extra_secrets=["clave-extra"])
    event = tracer.record(EventType.RETRY, {"msg": "falló con clave-extra"})
    assert "clave-extra" not in json.dumps(event.data)


def test_all_event_types_accepted_and_counted(tmp_path):
    tracer = Tracer(session="s3", trace_dir=tmp_path, console=False)
    for kind in EventType:
        tracer.record(kind, {"i": kind.value})
    assert len(tracer.events) == 10
    assert tracer.count("TOOL_CALL") == 1
    rows = _read_jsonl(tmp_path / "s3.jsonl")
    assert [r["event_type"] for r in rows] == [k.value for k in EventType]
    assert all(r["timestamp"] and r["session"] == "s3" for r in rows)


def test_invalid_event_type_rejected(tmp_path):
    tracer = Tracer(session="s4", trace_dir=tmp_path, console=False)
    with pytest.raises(ValueError):
        tracer.record("NO_EXISTE")


def test_trace_dir_created_on_demand(tmp_path):
    target = tmp_path / "nueva" / "traces"
    tracer = Tracer(session="s5", trace_dir=target, console=False)
    assert not target.exists()
    tracer.record(EventType.USER_INPUT, {"texto": "hola"})
    assert (target / "s5.jsonl").is_file()


def test_console_format_is_readable(tmp_path, capsys):
    tracer = Tracer(session="s6", trace_dir=tmp_path, write_file=False)
    tracer.record(EventType.ROUTE, {"ruta": "recibo"})
    out = capsys.readouterr().out
    assert "ROUTE" in out and "recibo" in out and out.count("\n") == 1
    assert not (tmp_path / "s6.jsonl").exists()
