"""Dobles de prueba compartidos de la Etapa 3 (cliente de Gemini falso)."""
from types import SimpleNamespace

from google.genai import errors


def ok_response(text="hola", prompt=10, out=5, thoughts=2, total=17):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=out,
            thoughts_token_count=thoughts,
            total_token_count=total,
        ),
    )


def api_error(code, status):
    return errors.ClientError(code, {"error": {"code": code, "message": "x", "status": status}})


class FakeModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


class FakeTime:
    """Reloj y sleep falsos: dormir avanza el reloj."""

    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
