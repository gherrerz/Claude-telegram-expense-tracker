"""Casos y comprobaciones del RAG compartidos por el script, la prueba `live` y el notebook (Etapa 15).

- `RAG_CASES`: tres entradas que muestran cuándo se recupera y cuándo no: una pregunta cuya respuesta
  está en el corpus (recupera y cita), un saludo (no recupera: "Hola" = respuesta directa) y una
  pregunta que el corpus no cubre (abstención, o rechazo si el router la considera ajena).
- `evaluate_rag_case`: comprobaciones por condiciones (no por texto exacto).
- Calibración del umbral: preguntas dentro y fuera del corpus (patrón del taller del curso) y
  `suggest_threshold`, que propone un umbral en el margen entre ambos grupos.
"""
from __future__ import annotations

from typing import Any, Optional

from app.assistant import (
    STOP_CHAT,
    STOP_OUT_OF_SCOPE,
    STOP_POLICY,
    STOP_RAG_ABSTAIN,
    AssistantResult,
    RAG_PROMPT_ID,
)
from app.models import EventType
from app.prompts import SECURITY_SCOPE_ID
from app.rag.retriever import DECISION_ABSTAIN, DECISION_USE
from app.router import CONSULTAR_POLITICA, CONVERSACION, FUERA_DE_ALCANCE
from app.trace import Tracer

# `retrieval`: True = exactamente un RETRIEVAL; False = ninguno (ni embedding); None = a lo más uno.
RAG_CASES: list[dict[str, Any]] = [
    {"id": "a", "name": "pregunta del corpus",
     "text": "¿Se puede rendir la propina en un restaurante y hasta qué porcentaje?",
     "rutas": (CONSULTAR_POLITICA,), "retrieval": True, "decision": DECISION_USE,
     "stop": (STOP_POLICY,), "cita": True},
    {"id": "b", "name": "saludo (sin RAG)", "text": "Hola",
     "rutas": (CONVERSACION,), "retrieval": False, "decision": None,
     "stop": (STOP_CHAT,), "cita": False},
    {"id": "c", "name": "pregunta fuera del corpus",
     "text": "¿Cuánto reembolsa la empresa por un hospedaje de hotel en el extranjero?",
     "rutas": (CONSULTAR_POLITICA, FUERA_DE_ALCANCE), "retrieval": None, "decision": DECISION_ABSTAIN,
     "stop": (STOP_RAG_ABSTAIN, STOP_OUT_OF_SCOPE), "cita": False},
]

# Calibración del umbral: preguntas con respuesta en el corpus y preguntas sin ella (algunas de otro
# tema y otras cercanas al dominio). El umbral se elige en el margen entre ambos grupos.
CALIBRATION_IN: list[str] = [
    "¿Hasta cuánto reembolsa la empresa por un taxi?",
    "¿Cuántos días hábiles tengo para rendir un gasto?",
    "¿Se reembolsa el alcohol en la cuenta de un restaurante?",
    "¿En qué categoría clasifico la boleta de una farmacia?",
]
CALIBRATION_OUT: list[str] = [
    "¿Cómo se prepara una cazuela de vacuno?",
    "¿Quién ganó el mundial de fútbol de 2014?",
    "¿Cuál es el protocolo de teletrabajo y vacaciones de la empresa?",
    "¿Cuánto reembolsa la empresa por un hospedaje de hotel en el extranjero?",
]


def suggest_threshold(in_scores: list[float], out_scores: list[float]) -> dict[str, Any]:
    """Propone un umbral entre el peor acierto y el mejor desacierto.

    `separable`: el peor parecido de las preguntas del corpus supera al mejor de las ajenas. Si lo es,
    `sugerido` es el punto medio (2 decimales) y `margen` el ancho de la brecha; si no, `sugerido` es
    `None` y no hay umbral que separe ambos grupos con estos casos.
    """
    if not in_scores or not out_scores:
        raise ValueError("Se necesitan preguntas dentro y fuera del corpus")
    min_in, max_out = min(in_scores), max(out_scores)
    separable = min_in > max_out
    return {
        "min_dentro": round(min_in, 4),
        "max_fuera": round(max_out, 4),
        "margen": round(min_in - max_out, 4),
        "separable": separable,
        "sugerido": round((min_in + max_out) / 2, 2) if separable else None,
    }


def evaluate_rag_case(
    case: dict[str, Any], result: AssistantResult, tracer: Tracer
) -> dict[str, bool]:
    """Comprobaciones por condiciones de un caso del RAG (True = se cumplió)."""
    retrievals = [e.data for e in tracer.events if e.event_type == EventType.RETRIEVAL]
    embeddings = [e.data for e in tracer.events
                  if e.event_type == EventType.LLM_DECISION and e.data.get("kind") == "embedding"]
    generations = [e.data for e in tracer.events
                   if e.event_type == EventType.LLM_DECISION and e.data.get("kind") != "embedding"]
    rag_answers = [g for g in generations if g.get("system_prompt_id") == RAG_PROMPT_ID]
    checks: dict[str, bool] = {
        f"ruta esperada {' o '.join(case['rutas'])}": result.route in case["rutas"],
        "parada esperada": result.stop_reason in case["stop"],
        "cero eventos TOOL_CALL": tracer.count(EventType.TOOL_CALL) == 0 and not result.tool_calls,
        f"alcance {SECURITY_SCOPE_ID} en cada llamada de generación": (
            {g.get("security_scope_id") for g in generations} <= {SECURITY_SCOPE_ID}
        ),
    }
    if case["retrieval"] is True:
        checks["un evento RETRIEVAL"] = len(retrievals) == 1
        checks[f"decisión {case['decision']}"] = (
            bool(retrievals) and retrievals[0]["decision"] == case["decision"]
        )
    elif case["retrieval"] is False:
        checks["no recupera (cero RETRIEVAL y cero embeddings)"] = not retrievals and not embeddings
    else:
        checks["a lo más un RETRIEVAL, y si hay, abstiene"] = len(retrievals) <= 1 and all(
            r["decision"] == case["decision"] for r in retrievals
        )
    if case["cita"]:
        sources = {r["fuente"] for ev in retrievals for r in ev["resultados"]}
        checks["una sola llamada de generación con el contexto"] = len(rag_answers) == 1
        checks["la respuesta cita una fuente recuperada"] = any(s in result.final_text for s in sources)
    else:
        checks["sin respuesta generada con contexto"] = not rag_answers
    return checks


def retrieval_summary(tracer: Tracer) -> Optional[dict[str, Any]]:
    """El primer evento `RETRIEVAL` de la traza, o `None` si no hubo recuperación."""
    return next((e.data for e in tracer.events if e.event_type == EventType.RETRIEVAL), None)
