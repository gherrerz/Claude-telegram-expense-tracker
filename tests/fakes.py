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


SHEET_HEADER_ROW = ["Fecha", "Comercio", "Monto", "Categoría", "Recibo_URL"]


class FakeSheetsValues:
    """Imita `service.spreadsheets().values()` de Sheets v4 (`get` y `append`) con estado.

    `append` agrega la fila a `rows` y responde con `updates.updatedRange`
    calculado como lo haría la API (`<hoja>!A{n}:E{n}`).
    """

    def __init__(self, rows=None, sheet_title="Hoja 1", get_error=None, append_error=None,
                 updated_range=None):
        self.rows = [list(r) for r in (rows if rows is not None else [SHEET_HEADER_ROW])]
        self.sheet_title = sheet_title
        self.get_error = get_error
        self.append_error = append_error
        self.updated_range = updated_range  # fuerza el valor devuelto (None = calculado)
        self.get_calls = []
        self.append_calls = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        if self.get_error is not None:
            return _FakeRequest(self.get_error)
        return _FakeRequest(
            {"range": f"{self.sheet_title}!A1:E{len(self.rows)}", "values": [list(r) for r in self.rows]}
        )

    def append(self, **kwargs):
        self.append_calls.append(kwargs)
        if self.append_error is not None:
            return _FakeRequest(self.append_error)
        self.rows.extend([list(r) for r in kwargs["body"]["values"]])
        number = len(self.rows)
        title = self.sheet_title.replace("'", "''")
        quoted = f"'{title}'" if any(c in self.sheet_title for c in " '!") else title
        return _FakeRequest(
            {
                "spreadsheetId": kwargs["spreadsheetId"],
                "updates": {
                    "updatedRange": self.updated_range or f"{quoted}!A{number}:E{number}",
                    "updatedRows": 1,
                },
            }
        )


class FakeSheetsService:
    def __init__(self, **kwargs):
        self._values = FakeSheetsValues(**kwargs)

    def spreadsheets(self):
        return self

    def values(self):
        return self._values


# -- Etapa 6: LLM falso con function calling ---------------------------------------
def fc_response(*calls, text=None, signature=b"firma-de-prueba", prompt=10, out=5):
    """Respuesta real del SDK (`GenerateContentResponse`) con llamadas a función.

    `calls` son tuplas `(nombre, args)`. Con `text` y sin `calls` es una respuesta final.
    La primera llamada lleva una `thought_signature` para comprobar que se conserva.
    """
    from google.genai import types

    parts = []
    for index, (name, args) in enumerate(calls):
        parts.append(
            types.Part(
                function_call=types.FunctionCall(id=f"call-{name}-{index}", name=name, args=args),
                thought_signature=signature if index == 0 else None,
            )
        )
    if text is not None:
        parts.append(types.Part(text=text))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=out, total_token_count=prompt + out
        ),
    )


class ScriptedModels:
    """`models.generate_content` guionado; guarda una COPIA de `contents` en cada llamada."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        item = self.script.pop(0) if self.script else self.repeat
        if isinstance(item, Exception):
            raise item
        return item

    repeat = None  # respuesta que se repite al agotarse el guion (opcional)


class ScriptedClient:
    def __init__(self, script, repeat=None):
        self.models = ScriptedModels(script)
        self.models.repeat = repeat
