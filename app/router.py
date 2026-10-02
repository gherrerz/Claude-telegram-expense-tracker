"""Router de flujo (Etapa 9): una llamada LLM previa al loop clasifica la entrada.

Rutas (`ROUTES`):
- `REGISTRAR_RECIBO`: loop ReAct con las tools de registro.
- `CONSULTAR_GASTOS`: respuesta desde el `AgentState`, sin tools.
- `CONSULTAR_POLITICA` (Etapa 15): respuesta con RAG sobre la política de rendición de gastos
  (recupera fragmentos del Redis del curso solo en esta ruta), sin tools.
- `CONVERSACION`: respuesta directa, sin tools.
- `FUERA_DE_ALCANCE`: rechazo, sin tools.

El router clasifica el FLUJO; no es un filtro de seguridad. El bloque de alcance
(`SECURITY_SCOPE_v3`) y los rieles de código de las tools siguen activos en todas las rutas:
una mala clasificación no abre ninguna acción prohibida.

Salida estructurada: JSON `{ruta, motivo}` con `ruta` restringida a un enum. Se valida de nuevo
en código (Pydantic con `Literal`) porque el esquema del proveedor no es una garantía.

Respaldos (siempre registrados en el evento `ROUTE` con `fallback=True` y `fallback_reason`):
- Entrada vacía (sin texto y sin imagen) -> `CONVERSACION`, SIN llamar al LLM.
- Falla del LLM, JSON inválido, etiqueta desconocida o campos faltantes -> `FUERA_DE_ALCANCE`,
  la rama segura: no expone ninguna tool y no ejecuta nada.

No hay reglas de código que corrijan la etiqueta del modelo (por ejemplo, forzar
`REGISTRAR_RECIBO` si hay imagen): el prompt indica que una imagen adjunta es una señal fuerte
y la decisión queda en el LLM, de modo que la ruta trazada es la que realmente se ejecutó.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from pydantic import BaseModel, ValidationError

from app.llm import ROUTER_TEMPERATURE, LLMCallError, LLMClient
from app.models import EventType
from app.trace import Tracer

ROUTER_PROMPT_ID = "ROUTER_PROMPT_v3"
SCHEMA_NAME = "RouteDecision"

REGISTRAR_RECIBO = "REGISTRAR_RECIBO"
CONSULTAR_GASTOS = "CONSULTAR_GASTOS"
CONSULTAR_POLITICA = "CONSULTAR_POLITICA"
CONVERSACION = "CONVERSACION"
FUERA_DE_ALCANCE = "FUERA_DE_ALCANCE"
ROUTES: tuple[str, ...] = (
    REGISTRAR_RECIBO, CONSULTAR_GASTOS, CONSULTAR_POLITICA, CONVERSACION, FUERA_DE_ALCANCE,
)

MAX_ROUTER_TEXT_CHARS = 2000
MAX_REASON_CHARS = 200

# JSON Schema enviado como `response_json_schema` (equivale a `RouterOutput`).
ROUTER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ruta": {"type": "string", "enum": list(ROUTES)},
        "motivo": {"type": "string", "description": "Frase breve que explica la elección."},
    },
    "required": ["ruta", "motivo"],
}


class RouterOutput(BaseModel):
    """Salida esperada del LLM, validada con `Literal`."""

    ruta: Literal[
        "REGISTRAR_RECIBO", "CONSULTAR_GASTOS", "CONSULTAR_POLITICA", "CONVERSACION",
        "FUERA_DE_ALCANCE",
    ]
    motivo: str


@dataclass(frozen=True)
class RouteDecision:
    """Ruta elegida. `fallback` es True si no vino de una clasificación válida del LLM."""

    ruta: str
    motivo: str
    fallback: bool = False


def _neutralize(text: str) -> str:
    """Evita que el mensaje cierre o abra las etiquetas de datos del prompt."""
    return text.replace("<", "‹").replace(">", "›")


def build_router_input(
    text: str, has_image: bool, recent_context: str, pending_confirmation: Optional[str] = None
) -> str:
    """Entrada del router: contexto, mensaje, imagen y confirmación pendiente, como datos delimitados.

    `pending_confirmation` es el tipo de la confirmación que el código espera del usuario
    ("duplicado" o "baja_confianza") o `None`. Solo es contexto: el código no corrige la etiqueta.
    """
    return (
        f"<contexto_reciente>{_neutralize(recent_context.strip()[:MAX_ROUTER_TEXT_CHARS])}"
        f"</contexto_reciente>\n"
        f"<mensaje_usuario>{_neutralize(text.strip()[:MAX_ROUTER_TEXT_CHARS])}</mensaje_usuario>\n"
        f"<adjunto_imagen>{'si' if has_image else 'no'}</adjunto_imagen>\n"
        f"<confirmacion_pendiente>{pending_confirmation or 'ninguna'}</confirmacion_pendiente>"
    )


def route_message(
    text: str,
    has_image: bool,
    recent_context: str,
    llm: LLMClient,
    tracer: Optional[Tracer] = None,
    pending_confirmation: Optional[str] = None,
) -> RouteDecision:
    """Clasifica el último mensaje y registra el evento `ROUTE`.

    Args:
        text: texto del usuario (puede ser vacío si hay imagen).
        has_image: si el mensaje trae una imagen adjunta (el router no la ve).
        recent_context: resumen breve de los últimos mensajes ("" si no hay).
        llm: cliente LLM; toda la llamada lleva `SECURITY_SCOPE_v3` por construcción.
        tracer: trazador del evento; por defecto el del cliente LLM.
        pending_confirmation: tipo de la confirmación pendiente del `AgentState` (Etapa 10) o
            `None`. Viaja como contexto al prompt; no hay ninguna regla de código sobre la etiqueta.

    Nunca lanza por fallas del LLM: devuelve la rama segura con `fallback=True`.
    """
    tracer = tracer if tracer is not None else llm.tracer
    decision, reason = _classify(text, has_image, recent_context, llm, pending_confirmation)
    tracer.record(
        EventType.ROUTE,
        {
            "ruta": decision.ruta,
            "motivo": decision.motivo,
            "fallback": decision.fallback,
            **({"fallback_reason": reason} if reason else {}),
            "has_image": has_image,
            **({"pending_confirmation": pending_confirmation} if pending_confirmation else {}),
            "prompt_id": ROUTER_PROMPT_ID,
        },
    )
    return decision


def _classify(
    text: str,
    has_image: bool,
    recent_context: str,
    llm: LLMClient,
    pending_confirmation: Optional[str] = None,
) -> tuple[RouteDecision, Optional[str]]:
    if not text.strip() and not has_image:
        return (
            RouteDecision(CONVERSACION, "entrada vacía; no se llamó al LLM", fallback=True),
            "entrada_vacia",
        )
    try:
        result = llm.generate_structured(
            system_prompt_id=ROUTER_PROMPT_ID,
            contents=build_router_input(text, has_image, recent_context, pending_confirmation),
            schema=ROUTER_JSON_SCHEMA,
            schema_name=SCHEMA_NAME,
            temperature=ROUTER_TEMPERATURE,
        )
    except LLMCallError as error:
        return _safe(f"falló la llamada al LLM (código={error.code})"), "error_llm"
    if result.json_error is not None:
        return _safe(result.json_error), "json_invalido"
    try:
        output = RouterOutput.model_validate(result.data)
    except ValidationError:
        # Solo el tipo de problema, nunca el contenido devuelto por el modelo.
        return _safe("etiqueta o campos inválidos"), "salida_invalida"
    return RouteDecision(output.ruta, output.motivo.strip()[:MAX_REASON_CHARS]), None


def _safe(detail: str) -> RouteDecision:
    return RouteDecision(FUERA_DE_ALCANCE, f"respaldo seguro: {detail}", fallback=True)
