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


class _FakeRequest:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeDriveFiles:
    """Imita `service.files()` de Drive v3 (`create` y `get`)."""

    def __init__(self, create_result=None, get_result=None):
        self.create_result = create_result
        self.get_result = get_result
        self.create_calls = []
        self.get_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _FakeRequest(self.create_result)

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return _FakeRequest(self.get_result)


class FakeDriveService:
    def __init__(self, create_result=None, get_result=None):
        self._files = FakeDriveFiles(create_result, get_result)

    def files(self):
        return self._files
