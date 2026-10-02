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


# -- Etapa 15: embeddings y Redis falsos (sin red) ---------------------------------------
import hashlib  # noqa: E402
import re as _re  # noqa: E402
import unicodedata  # noqa: E402

import numpy as np  # noqa: E402
from redis.exceptions import ResponseError  # noqa: E402

EMBED_DIMS = 768
# Palabras de las plantillas de embeddings: no aportan significado al parecido.
_TEMPLATE_WORDS = {"title", "text", "task", "search", "result", "query", "none"}


def _words(text):
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return [w[:6] for w in _re.findall(r"[a-z]{4,}", plain) if w not in _TEMPLATE_WORDS]


def hash_embedding(text):
    """Vector normalizado de 768 dimensiones: bolsa de palabras (raíz de 6 letras) con hash.

    Dos textos que comparten palabras tienen coseno alto; sin palabras en común, coseno ~0.
    """
    vector = np.zeros(EMBED_DIMS, dtype=np.float64)
    for word in _words(text):
        index = int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBED_DIMS
        vector[index] += 1.0
    norm = np.linalg.norm(vector)
    if norm == 0:
        vector[0] = 1.0
        norm = 1.0
    return (vector / norm).tolist()


class FakeEmbedder:
    """Sustituto directo de `LLMClient.embed` para las pruebas del recuperador y del indexador."""

    def __init__(self, fail_with=None):
        self.calls = []  # [(textos, propósito)]
        self.fail_with = fail_with

    def embed(self, texts, purpose="documento"):
        self.calls.append((list(texts), purpose))
        if self.fail_with is not None:
            raise self.fail_with
        return [hash_embedding(t) for t in texts]


class ScriptedEmbedModels(ScriptedModels):
    """`ScriptedModels` con `embed_content`: un vector `hash_embedding` por `Content` recibido."""

    def __init__(self, script, embed_script=()):
        super().__init__(script)
        self.embed_script = list(embed_script)  # errores o respuestas a consumir primero
        self.embed_calls = []

    def embed_content(self, *, model, contents, config):
        self.embed_calls.append({"model": model, "contents": list(contents), "config": config})
        if self.embed_script:
            item = self.embed_script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        vectors = [
            SimpleNamespace(values=hash_embedding("".join(p.text for p in c.parts)))
            for c in contents
        ]
        return SimpleNamespace(embeddings=vectors)


class RagClient:
    """Cliente de Gemini falso con generación guionada y embeddings."""

    def __init__(self, script, embed_script=()):
        self.models = ScriptedEmbedModels(script, embed_script)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    def hset(self, key, mapping):
        self.ops.append((key, dict(mapping)))

    def execute(self):
        for key, mapping in self.ops:
            self.redis.hashes[key] = mapping
        self.ops = []


class FakeSearch:
    """Imita `client.ft(nombre)`: `info`, `create_index`, `dropindex` y `search` (KNN por coseno)."""

    def __init__(self, redis, name):
        self.redis = redis
        self.name = name

    def info(self):
        self.redis.commands.append(("FT.INFO", self.name))
        if self.name not in self.redis.indexes:
            raise ResponseError("Unknown index name")
        prefix = self.redis.indexes[self.name]["prefix"]
        count = sum(1 for k in self.redis.hashes if k.startswith(prefix))
        return {"index_name": self.name, "num_docs": str(count), "attributes": [["identifier", "embedding"]]}

    def create_index(self, fields, definition=None):
        self.redis.commands.append(("FT.CREATE", self.name))
        assert self.name not in self.redis.indexes, "el índice ya existe"
        args = list(definition.args)
        prefix = args[args.index("PREFIX") + 2]
        self.redis.indexes[self.name] = {
            "prefix": prefix,
            "on": args[args.index("ON") + 1],
            "fields": [(f.name, [str(a) for a in f.args]) for f in fields],
        }

    def dropindex(self, delete_documents=False):
        self.redis.commands.append(("FT.DROPINDEX", self.name, bool(delete_documents)))
        if self.name not in self.redis.indexes:
            raise ResponseError("Unknown index name")
        prefix = self.redis.indexes.pop(self.name)["prefix"]
        if delete_documents:
            for key in [k for k in self.redis.hashes if k.startswith(prefix)]:
                del self.redis.hashes[key]

    def search(self, query, query_params=None):
        self.redis.commands.append(("FT.SEARCH", self.name, query.query_string(), tuple(query.get_args())))
        prefix = self.redis.indexes[self.name]["prefix"]
        vec = np.frombuffer(query_params["vec"], dtype=np.float32)
        docs = []
        for key, mapping in self.redis.hashes.items():
            if not key.startswith(prefix):
                continue
            stored = np.frombuffer(mapping["embedding"], dtype=np.float32)
            distance = 1.0 - float(np.dot(vec, stored) / (np.linalg.norm(vec) * np.linalg.norm(stored)))
            docs.append(SimpleNamespace(id=key, score=str(distance), **{
                k: v for k, v in mapping.items() if k != "embedding"}))
        docs.sort(key=lambda d: float(d.score))
        k = query_params["k"]
        return SimpleNamespace(total=len(docs), docs=docs[:k])


class FakeRedis:
    """Redis en memoria con lo mínimo que usa `RedisVectorStore` (y registro de comandos)."""

    def __init__(self, fail_with=None):
        self.hashes = {}
        self.strings = {}
        self.indexes = {}
        self.commands = []
        self.deleted = []
        self.fail_with = fail_with

    def _maybe_fail(self):
        if self.fail_with is not None:
            raise self.fail_with

    def ft(self, name):
        self._maybe_fail()
        return FakeSearch(self, name)

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def scan_iter(self, match=None, count=None):
        import fnmatch

        self.commands.append(("SCAN", match))
        for key in list(self.hashes) + list(self.strings):
            if match is None or fnmatch.fnmatchcase(key, match):
                yield key.encode()

    def delete(self, *keys):
        for key in keys:
            name = key.decode() if isinstance(key, bytes) else key
            self.deleted.append(name)
            self.hashes.pop(name, None)
            self.strings.pop(name, None)

    def get(self, key):
        self._maybe_fail()
        value = self.strings.get(key)
        return value.encode() if isinstance(value, str) else value

    def set(self, key, value):
        self.strings[key] = value
