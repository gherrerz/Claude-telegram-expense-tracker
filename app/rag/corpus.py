"""Lectura del corpus y firma para no reindexar si nada cambió (Etapa 15).

La firma es el md5 de todo lo que determina el contenido del índice: cada archivo del corpus (con
saltos de línea normalizados), los parámetros de fragmentación, el modelo y las dimensiones de los
embeddings, las plantillas de texto y la versión del esquema. Se guarda en Redis y, si coincide con
la del corpus actual y el índice está completo, la carga se omite.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import EMBEDDING_DIMS, EMBEDDING_MODEL, ROOT
from app.rag.chunking import CHUNK_OVERLAP, CHUNK_SIZE, normalize_text
from app.rag.formats import DOCUMENT_TEMPLATE, QUERY_TEMPLATE

CORPUS_DIR = ROOT / "data" / "corpus"
# Los README y otras notas del directorio no son parte del corpus; solo se indexan estos archivos.
CORPUS_GLOB = "*.md"
CORPUS_EXCLUDED = frozenset({"README.md"})
# Súbela si cambia el esquema del índice (campos, algoritmo o métrica) para forzar la recarga.
SCHEMA_VERSION = "1"


def read_corpus(directory: str | Path = CORPUS_DIR) -> dict[str, str]:
    """`{nombre_de_archivo: texto}` de los documentos del corpus (UTF-8, saltos normalizados).

    Raises:
        FileNotFoundError: si el directorio no existe.
        ValueError: si no hay ningún documento.
    """
    base = Path(directory)
    if not base.is_dir():
        raise FileNotFoundError("No existe el directorio del corpus")
    documents = {
        path.name: normalize_text(path.read_text(encoding="utf-8"))
        for path in sorted(base.glob(CORPUS_GLOB))
        if path.name not in CORPUS_EXCLUDED
    }
    if not documents:
        raise ValueError("El corpus no tiene documentos .md")
    return documents


def corpus_signature(documents: dict[str, str]) -> str:
    """md5 del corpus y de los parámetros que definen el índice."""
    digest = hashlib.md5()  # noqa: S324 - firma de cambios, no criptografía
    for name in sorted(documents):
        file_md5 = hashlib.md5(documents[name].encode("utf-8")).hexdigest()  # noqa: S324
        digest.update(f"{name}:{file_md5}\n".encode("utf-8"))
    params = (
        f"chunk_size={CHUNK_SIZE};chunk_overlap={CHUNK_OVERLAP};model={EMBEDDING_MODEL};"
        f"dims={EMBEDDING_DIMS};doc={DOCUMENT_TEMPLATE};query={QUERY_TEMPLATE};schema={SCHEMA_VERSION}"
    )
    digest.update(params.encode("utf-8"))
    return digest.hexdigest()
