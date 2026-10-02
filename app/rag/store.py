"""Almacén vectorial sobre el Redis del curso (Etapa 15, adenda A14).

Usa RediSearch (módulo `search` del Redis del curso): un índice vectorial nativo sobre documentos
HASH. Nombres, todos bajo el prefijo del grupo (`REDIS_PREFIX`, por ejemplo `Grupo_03_TrabajoFinal_v1`):

| Qué            | Nombre                          |
|----------------|---------------------------------|
| Índice         | `{prefijo}:rag:idx`             |
| Claves HASH    | `{prefijo}:rag:chunk:{chunk_id}`|
| Firma del corpus | `{prefijo}:rag:firma`         |

Configuración del índice (la que exige el bono): `FT.CREATE ... ON HASH PREFIX 1 {prefijo}:rag:chunk:`
con los campos `chunk_id` (TAG), `fuente` (TAG), `seccion` (TEXT), `texto` (TEXT) y `embedding`
(VECTOR, algoritmo HNSW, tipo FLOAT32, DIM 768, métrica COSINE).

Seguridad sobre el Redis COMPARTIDO: el prefijo debe ser no vacío y solo de letras, números, guion y
guion bajo (sin comodines ni dos puntos), así que ningún patrón puede alcanzar claves de otros grupos;
`reset()` borra únicamente nuestro índice y las claves que empiezan con `{prefijo}:rag:`. Los errores
de Redis se reducen al nombre de su clase: el mensaje puede contener el host.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Protocol, Sequence

import numpy as np
from redis.commands.search.field import Field, TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from redis.exceptions import RedisError, ResponseError

from app.config import EMBEDDING_DIMS, EMBEDDING_MODEL, REDIS_PREFIX_PATTERN, Settings
from app.rag.chunking import Chunk

ALGORITHM = "HNSW"
DISTANCE_METRIC = "COSINE"
VECTOR_TYPE = "FLOAT32"
VECTOR_FIELD = "embedding"
RETURN_FIELDS = ("chunk_id", "fuente", "seccion", "texto")
# Los campos tal como se declaran al crear el índice (para documentarlos y mostrarlos).
INDEX_FIELDS: tuple[tuple[str, str], ...] = (
    ("chunk_id", "TAG"),
    ("fuente", "TAG"),
    ("seccion", "TEXT"),
    ("texto", "TEXT"),
    (VECTOR_FIELD, f"VECTOR {ALGORITHM} {VECTOR_TYPE} DIM {EMBEDDING_DIMS} {DISTANCE_METRIC}"),
)
CONNECT_TIMEOUT_SECONDS = 10


class RagStoreError(Exception):
    """Falla del almacén (conexión, comando o configuración). El mensaje no incluye el host."""


def validate_prefix(prefix: Optional[str]) -> str:
    """Devuelve el prefijo validado.

    Raises:
        ValueError: si está vacío o contiene caracteres fuera de `[A-Za-z0-9_-]`.
    """
    if not prefix or not prefix.strip() or not REDIS_PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError(
            "REDIS_PREFIX es obligatorio y solo admite letras, números, guion y guion bajo"
        )
    return prefix


def index_name_for(prefix: str) -> str:
    return f"{validate_prefix(prefix)}:rag:idx"


def key_prefix_for(prefix: str) -> str:
    return f"{validate_prefix(prefix)}:rag:chunk:"


def signature_key_for(prefix: str) -> str:
    return f"{validate_prefix(prefix)}:rag:firma"


class VectorStore(Protocol):
    """Contrato mínimo del almacén; lo implementan `RedisVectorStore` y los dobles de prueba."""

    def knn(self, query_vector: Sequence[float], k: int) -> list[dict[str, Any]]: ...
    def index_exists(self) -> bool: ...
    def ensure_index(self) -> bool: ...
    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int: ...
    def reset(self) -> None: ...
    def get_signature(self) -> Optional[str]: ...
    def set_signature(self, signature: str) -> None: ...
    def index_info(self) -> dict[str, Any]: ...


@contextmanager
def _redis_errors() -> Iterator[None]:
    """Convierte fallas de Redis en `RagStoreError` sin filtrar el mensaje (puede traer el host)."""
    try:
        yield
    except RagStoreError:
        raise
    except (RedisError, OSError) as error:
        raise RagStoreError(f"Falló la operación con Redis ({type(error).__name__})") from None


def _is_unknown_index(error: ResponseError) -> bool:
    message = str(error).lower()
    return "unknown" in message or "no such index" in message


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


class RedisVectorStore:
    """Índice vectorial HNSW/COSINE de un grupo en el Redis del curso."""

    def __init__(self, client: Any, prefix: str) -> None:
        self._prefix = validate_prefix(prefix)
        self._client = client
        self.index_name = index_name_for(self._prefix)
        self.key_prefix = key_prefix_for(self._prefix)
        self.signature_key = signature_key_for(self._prefix)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RedisVectorStore":
        """Crea el almacén desde la configuración (no abre la conexión hasta el primer comando).

        Raises:
            RagStoreError: si faltan `REDIS_URL` o `REDIS_PREFIX`.
        """
        if not settings.redis_url or not settings.redis_prefix:
            raise RagStoreError("Falta la configuración de Redis (REDIS_URL y REDIS_PREFIX)")
        import redis  # import perezoso: solo si se usa el Redis real

        client = redis.Redis.from_url(
            settings.redis_url,
            socket_timeout=CONNECT_TIMEOUT_SECONDS,
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        )
        return cls(client, settings.redis_prefix)

    # -- índice ------------------------------------------------------------------------
    def _schema(self) -> list[Field]:
        return [
            TagField("chunk_id"),
            TagField("fuente"),
            TextField("seccion"),
            TextField("texto"),
            VectorField(
                VECTOR_FIELD,
                ALGORITHM,
                {"TYPE": VECTOR_TYPE, "DIM": EMBEDDING_DIMS, "DISTANCE_METRIC": DISTANCE_METRIC},
            ),
        ]

    def index_exists(self) -> bool:
        with _redis_errors():
            try:
                self._client.ft(self.index_name).info()
            except ResponseError as error:
                if _is_unknown_index(error):
                    return False
                raise
            return True

    def ensure_index(self) -> bool:
        """Crea el índice si no existe. Devuelve `True` si lo creó."""
        if self.index_exists():
            return False
        with _redis_errors():
            self._client.ft(self.index_name).create_index(
                self._schema(),
                definition=IndexDefinition(prefix=[self.key_prefix], index_type=IndexType.HASH),
            )
        return True

    def reset(self) -> None:
        """Borra SOLO nuestro índice, nuestras claves de fragmentos y nuestra firma.

        Nunca toca otros prefijos: el patrón de borrado siempre empieza con `{prefijo}:rag:chunk:`
        y cada clave se vuelve a comprobar antes de borrarla.
        """
        with _redis_errors():
            if self.index_exists():
                self._client.ft(self.index_name).dropindex(delete_documents=True)
            for key in self._client.scan_iter(match=f"{self.key_prefix}*", count=200):
                if _to_text(key).startswith(self.key_prefix):
                    self._client.delete(key)
            self._client.delete(self.signature_key)

    # -- carga -------------------------------------------------------------------------
    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int:
        """Escribe un HASH por fragmento (`{prefijo}:rag:chunk:{chunk_id}`). Devuelve cuántos."""
        if len(chunks) != len(vectors):
            raise ValueError("Debe haber un vector por fragmento")
        with _redis_errors():
            pipe = self._client.pipeline(transaction=False)
            for chunk, vector in zip(chunks, vectors):
                if len(vector) != EMBEDDING_DIMS:
                    raise ValueError(f"El vector debe tener {EMBEDDING_DIMS} dimensiones")
                pipe.hset(
                    f"{self.key_prefix}{chunk.chunk_id}",
                    mapping={
                        "chunk_id": chunk.chunk_id,
                        "fuente": chunk.fuente,
                        "seccion": chunk.seccion,
                        "texto": chunk.texto,
                        VECTOR_FIELD: np.asarray(vector, dtype=np.float32).tobytes(),
                    },
                )
            pipe.execute()
        return len(chunks)

    def get_signature(self) -> Optional[str]:
        with _redis_errors():
            value = self._client.get(self.signature_key)
        return _to_text(value) if value is not None else None

    def set_signature(self, signature: str) -> None:
        with _redis_errors():
            self._client.set(self.signature_key, signature)

    # -- consulta ----------------------------------------------------------------------
    def knn(self, query_vector: Sequence[float], k: int) -> list[dict[str, Any]]:
        """Los `k` fragmentos más cercanos. `similitud` = 1 - distancia coseno (mayor = más parecido)."""
        if len(query_vector) != EMBEDDING_DIMS:
            raise ValueError(f"El vector debe tener {EMBEDDING_DIMS} dimensiones")
        query = (
            Query(f"*=>[KNN $k @{VECTOR_FIELD} $vec AS score]")
            .sort_by("score")
            .return_fields(*RETURN_FIELDS, "score")
            .paging(0, k)
            .dialect(2)
        )
        params = {"k": k, "vec": np.asarray(query_vector, dtype=np.float32).tobytes()}
        with _redis_errors():
            result = self._client.ft(self.index_name).search(query, query_params=params)
        hits = [
            {
                "chunk_id": _to_text(getattr(doc, "chunk_id", "")),
                "fuente": _to_text(getattr(doc, "fuente", "")),
                "seccion": _to_text(getattr(doc, "seccion", "")),
                "texto": _to_text(getattr(doc, "texto", "")),
                "similitud": max(-1.0, min(1.0, 1.0 - float(getattr(doc, "score", 1.0)))),
            }
            for doc in result.docs
        ]
        return sorted(hits, key=lambda h: h["similitud"], reverse=True)

    # -- información -------------------------------------------------------------------
    def index_info(self) -> dict[str, Any]:
        """Configuración del índice y estado, sin secretos.

        `configurado` es lo que `FT.CREATE` recibió (constantes del código); `atributos` y
        `num_docs` son lo que Redis reporta en `FT.INFO`.
        """
        with _redis_errors():
            info = self._client.ft(self.index_name).info()
        return {
            "indice": self.index_name,
            "prefijo_claves": self.key_prefix,
            "clave_firma": self.signature_key,
            "num_docs": _to_int(info.get("num_docs")),
            "atributos": info.get("attributes"),
            "configurado": {
                "modelo_embeddings": EMBEDDING_MODEL,
                "dimensiones": EMBEDDING_DIMS,
                "metrica": DISTANCE_METRIC,
                "algoritmo": ALGORITHM,
                "tipo_vector": VECTOR_TYPE,
                "campos": [f"{name} ({kind})" for name, kind in INDEX_FIELDS],
            },
        }
