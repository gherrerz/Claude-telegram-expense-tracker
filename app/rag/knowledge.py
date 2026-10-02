"""Base de conocimiento del asistente: almacén + parámetros de recuperación (Etapa 15).

`load_knowledge_base` devuelve `None` si falta la configuración del Redis del curso (`REDIS_URL` o
`REDIS_PREFIX`): la ruta `CONSULTAR_POLITICA` responde entonces con honestidad que la base no está
disponible (A12: nada se simula). No abre la conexión: solo construye el cliente.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from app.config import ConfigError, load_settings
from app.rag.store import RagStoreError, RedisVectorStore, VectorStore


@dataclass(frozen=True)
class KnowledgeBase:
    """Almacén y parámetros de recuperación de la ruta de política."""

    store: VectorStore
    top_k: int
    threshold: float


def load_knowledge_base(env: Optional[Mapping[str, str]] = None) -> Optional[KnowledgeBase]:
    """Construye la base desde la configuración, o `None` si no está configurada o es inválida.

    Args:
        env: mapeo que reemplaza al entorno (pruebas). Si se omite, se lee `.env` y `os.environ`.
    """
    try:
        settings = load_settings(env=env)
        if not settings.redis_url or not settings.redis_prefix:
            return None
        store = RedisVectorStore.from_settings(settings)
    except (ConfigError, RagStoreError):
        return None
    return KnowledgeBase(store, settings.rag_top_k, settings.rag_threshold)
