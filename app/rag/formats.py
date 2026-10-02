"""Plantillas de texto para los embeddings (`gemini-embedding-2`).

`gemini-embedding-2` NO admite el parámetro `task_type`: la tarea se indica dentro del propio texto,
según la documentación oficial (https://ai.google.dev/gemini-api/docs/embeddings). Por eso los
documentos y las consultas se formatean con estas plantillas ANTES de llamar a `LLMClient.embed`.
Cambiarlas cambia los vectores: la firma del corpus (`app/rag/corpus.py`) las incluye, así que un
cambio fuerza a reindexar.
"""
from __future__ import annotations

# Documentos (fragmentos del corpus): el título es la ruta de secciones del fragmento.
DOCUMENT_TEMPLATE = "title: {titulo} | text: {fragmento}"
# Consultas (la pregunta del usuario): tarea de búsqueda.
QUERY_TEMPLATE = "task: search result | query: {pregunta}"

MAX_QUERY_CHARS = 2000


def format_document(titulo: str, fragmento: str) -> str:
    """Texto de un fragmento del corpus tal como se envía a embeddings."""
    return DOCUMENT_TEMPLATE.format(titulo=titulo.strip() or "none", fragmento=fragmento.strip())


def format_query(pregunta: str) -> str:
    """Texto de una pregunta tal como se envía a embeddings (acotada en largo)."""
    return QUERY_TEMPLATE.format(pregunta=pregunta.strip()[:MAX_QUERY_CHARS])
