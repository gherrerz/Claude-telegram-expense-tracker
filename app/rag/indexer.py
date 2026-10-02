"""Carga idempotente del corpus en el índice (Etapa 15; la usa `scripts/load_corpus.py`).

Flujo de `index_corpus`:
1. Fragmenta el corpus y calcula su firma (`app/rag/corpus.py`).
2. Si la firma guardada coincide, el índice existe y tiene todos los fragmentos, y no se pidió
   `force`: devuelve `omitido` sin llamar a embeddings ni escribir nada.
3. Si no: calcula TODOS los embeddings primero (si la cuota falla aquí, el índice anterior queda
   intacto), luego reinicia SOLO nuestro índice y nuestras claves, lo crea, escribe los HASH y guarda
   la firma al final (una carga interrumpida no deja una firma que engañe a la siguiente).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from app.rag.chunking import Chunk, chunk_documents
from app.rag.corpus import corpus_signature
from app.rag.formats import format_document
from app.rag.store import VectorStore

EMBED_BATCH_SIZE = 20  # textos por llamada de embeddings (el máximo de la API es mayor)
ACTION_SKIPPED = "omitido"
ACTION_INDEXED = "indexado"


class DocumentEmbedder(Protocol):
    def embed(self, texts: list[str], purpose: str = "documento") -> list[list[float]]: ...


@dataclass(frozen=True)
class IndexReport:
    """Qué hizo la carga. `razon` explica por qué se indexó u omitió."""

    accion: str
    razon: str
    fragmentos: int
    firma: str
    firma_anterior: Optional[str] = None


def embed_chunks(chunks: Sequence[Chunk], llm: DocumentEmbedder) -> list[list[float]]:
    """Embeddings de los fragmentos (propósito "documento"), por lotes de `EMBED_BATCH_SIZE`."""
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        vectors.extend(
            llm.embed([format_document(c.seccion, c.texto) for c in batch], purpose="documento")
        )
    return vectors


def index_corpus(
    store: VectorStore, llm: DocumentEmbedder, documents: dict[str, str], force: bool = False
) -> IndexReport:
    """Carga el corpus en el índice del grupo; omite el trabajo si nada cambió y no hay `force`."""
    chunks = chunk_documents(documents)
    if not chunks:
        raise ValueError("El corpus no produjo ningún fragmento")
    signature = corpus_signature(documents)
    previous = store.get_signature()
    if not force and previous == signature and store.index_exists():
        if store.index_info()["num_docs"] == len(chunks):
            return IndexReport(
                ACTION_SKIPPED, "la firma del corpus no cambió", len(chunks), signature, previous
            )
    reason = (
        "carga forzada" if force
        else "no había firma guardada" if previous is None
        else "cambió el corpus o los parámetros" if previous != signature
        else "el índice no estaba completo"
    )
    vectors = embed_chunks(chunks, llm)
    store.reset()
    store.ensure_index()
    store.upsert(chunks, vectors)
    store.set_signature(signature)
    return IndexReport(ACTION_INDEXED, reason, len(chunks), signature, previous)
