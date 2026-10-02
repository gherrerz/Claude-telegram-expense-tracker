"""Recuperador top-k con umbral de abstención (Etapa 15).

`retrieve` embebe la pregunta (`LLMClient.embed`, propósito "consulta"), busca los `top_k` fragmentos
más parecidos por coseno y compara el MEJOR parecido con el umbral:

- `mejor_similitud >= umbral`: decisión `usar_contexto` (se responde con los fragmentos);
- si no: decisión `abstener` (el asistente responde con un texto fijo y NO llama al LLM de
  generación; la única llamada del turno fue el embedding de la consulta).

Registra el evento `RETRIEVAL` con la pregunta, `top_k`, el umbral, los resultados (identificador,
fuente, sección y similitud; nunca el texto del fragmento) y la decisión.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence

from app.models import EventType
from app.rag.formats import format_query
from app.trace import Tracer

DECISION_USE = "usar_contexto"
DECISION_ABSTAIN = "abstener"
MAX_TRACED_QUESTION_CHARS = 300


class Embedder(Protocol):
    """Lo único que el recuperador necesita del cliente LLM."""

    def embed(self, texts: list[str], purpose: str = "documento") -> list[list[float]]: ...


@dataclass(frozen=True)
class RetrievalResult:
    """Resultado de una recuperación.

    `fragmentos`: los top-k, del más al menos parecido, cada uno
    `{chunk_id, fuente, seccion, texto, similitud}`.
    """

    fragmentos: list[dict[str, Any]] = field(default_factory=list)
    mejor_similitud: float = 0.0
    sobre_umbral: bool = False
    umbral: float = 0.0
    top_k: int = 0

    @property
    def decision(self) -> str:
        return DECISION_USE if self.sobre_umbral else DECISION_ABSTAIN

    @property
    def usables(self) -> list[dict[str, Any]]:
        """Fragmentos que llegan al contexto: los que alcanzan el umbral (el mejor siempre que haya)."""
        if not self.sobre_umbral:
            return []
        return [f for f in self.fragmentos if f["similitud"] >= self.umbral]


class _Searchable(Protocol):
    def knn(self, query_vector: Sequence[float], k: int) -> list[dict[str, Any]]: ...


def retrieve(
    question: str,
    store: _Searchable,
    llm: Embedder,
    tracer: Optional[Tracer],
    top_k: int,
    threshold: float,
) -> RetrievalResult:
    """Recupera los fragmentos más parecidos a `question` y decide si alcanzan el umbral.

    Raises:
        LLMCallError: si falla el embedding de la consulta tras los reintentos.
        RagStoreError: si falla la consulta al Redis.
    """
    vector = llm.embed([format_query(question)], purpose="consulta")[0]
    hits = sorted(store.knn(vector, top_k), key=lambda h: h["similitud"], reverse=True)[:top_k]
    best = hits[0]["similitud"] if hits else 0.0
    result = RetrievalResult(
        fragmentos=hits,
        mejor_similitud=best,
        sobre_umbral=bool(hits) and best >= threshold,
        umbral=threshold,
        top_k=top_k,
    )
    if tracer is not None:
        tracer.record(
            EventType.RETRIEVAL,
            {
                "pregunta": question.strip()[:MAX_TRACED_QUESTION_CHARS],
                "top_k": top_k,
                "umbral": threshold,
                "mejor_similitud": round(best, 4),
                "resultados": [
                    {
                        "chunk_id": h["chunk_id"],
                        "fuente": h["fuente"],
                        "seccion": h["seccion"],
                        "similitud": round(h["similitud"], 4),
                    }
                    for h in hits
                ],
                "decision": result.decision,
            },
        )
    return result
