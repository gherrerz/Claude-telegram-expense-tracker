"""Punto de entrada único del asistente (Etapa 9): router + una ruta por intención.

`ExpenseAssistant.handle(...)` clasifica el mensaje con `app/router.py` y ejecuta UN camino:

| Ruta               | Camino                                                       | Tools |
|--------------------|--------------------------------------------------------------|-------|
| REGISTRAR_RECIBO   | loop ReAct de `ExpenseAgent.run` (historial, rieles, juez*)   | sí    |
| CONSULTAR_GASTOS   | una llamada `generate_text` con `QUERY_PROMPT_v2` y el        | no    |
|                    | `AgentState` serializado como DATO                            |       |
| CONSULTAR_POLITICA | RAG (Etapa 15): recupera fragmentos del Redis del curso; bajo | no    |
|                    | el umbral abstiene SIN llamar al LLM; si no, una llamada con  |       |
|                    | `RAG_PROMPT_v1` y los fragmentos como DATO (cita las fuentes) |       |
| CONVERSACION       | una llamada estructurada con `CHAT_PROMPT_v2` ({respuesta,    | no    |
|                    | nombre_usuario}); un nombre válido va al `AgentState`         |       |
| FUERA_DE_ALCANCE   | texto fijo de rechazo en código, sin llamada al LLM           | no    |

(*) el juez (Etapa 11) lo dispara el código tras cada `analizar_recibo`; ver `app/agent.py`.

Memoria avanzada (Etapa 10): `handle` usa un `AgentState` por conversación (si no se entrega
uno, crea uno nuevo y lo devuelve en `AssistantResult.state`). El código lo actualiza (ver
`app/memory.py`): el nombre desde CONVERSACION y los totales, los últimos gastos y los
recibos registrados cuando `registrar_gasto` confirma la escritura. El router recibe el tipo de la
confirmación pendiente como contexto (`ROUTER_PROMPT_v2`), de modo que "sí, regístralo de todas
formas" sin imagen continúa el registro; no hay ninguna regla de código sobre la etiqueta.

Las tools solo existen en la ruta REGISTRAR_RECIBO: las demás rutas no declaran ninguna,
y las pruebas verifican cero eventos `TOOL_CALL` en ellas. El router no es un filtro de
seguridad: el bloque `SECURITY_SCOPE_v3` va en TODA llamada (lo garantiza `LLMClient`) y los
rieles del agente no cambian.

Decisión de diseño sobre FUERA_DE_ALCANCE: el rechazo es un texto fijo. Es determinista, no
gasta cuota y ningún LLM decide ni redacta nada en esa rama (menos superficie ante una
inyección). A cambio, el texto no se adapta al pedido.

Historial entre rutas (Etapa 7): todas las rutas agregan a la `Conversation` el mensaje del
usuario y la respuesta final. REGISTRAR_RECIBO conserva el historial completo con tools, como
hasta ahora. Las rutas SIN tools reciben una versión de solo texto del historial (se omiten las
llamadas a función y sus observaciones, que no tienen sentido sin tools declaradas) con los
mensajes consecutivos del mismo rol unidos, para que los roles sigan alternando. Los
mensajes de las rutas sin tools se guardan como texto plano, sin firmas de pensamiento: solo
importan para function calling, que ocurre únicamente en REGISTRAR_RECIBO.

Trazas: `ROUTE` (clasificación) y luego, en las rutas sin tools, `USER_INPUT`, las
`LLM_DECISION` del cliente, `FINAL_RESPONSE` y `STOP` con motivo `ruta_consulta`,
`ruta_conversacion` o `ruta_fuera_de_alcance` (o `error_llm` / `respuesta_vacia`). En
CONSULTAR_POLITICA se agregan el embedding de la consulta (`LLM_DECISION` con `kind="embedding"`)
y `RETRIEVAL`, y la parada es `ruta_politica`, `rag_abstencion` (sin llamar al LLM de generación) o
`rag_no_disponible` (sin configuración o con el Redis caído; nada se simula). En
REGISTRAR_RECIBO, `USER_INPUT` y los demás eventos los registra el agente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from pydantic import BaseModel, ValidationError

from app.agent import STOP_EMPTY, STOP_LLM_ERROR, ExpenseAgent, JudgeFn, ToolFn
from app.conversation import Conversation
from app.llm import ANSWER_TEMPERATURE, EmbeddingError, LLMCallError, LLMClient, LLMResult
from app.memory import set_user_name, total_general, valid_user_name
from app.models import AgentState, EventType
from app.prompts import RAG_INSUFFICIENT_PHRASE, SECURITY_SCOPE_ID
from app.rag.knowledge import KnowledgeBase, load_knowledge_base
from app.rag.retriever import retrieve
from app.rag.store import RagStoreError
from app.router import (
    CONSULTAR_GASTOS,
    CONSULTAR_POLITICA,
    CONVERSACION,
    FUERA_DE_ALCANCE,
    REGISTRAR_RECIBO,
    RouteDecision,
    route_message,
)
from app.trace import Tracer

CHAT_PROMPT_ID = "CHAT_PROMPT_v2"
QUERY_PROMPT_ID = "QUERY_PROMPT_v2"
RAG_PROMPT_ID = "RAG_PROMPT_v1"
CHAT_SCHEMA_NAME = "ChatOutput"

# JSON Schema de la salida de CONVERSACION. `nombre_usuario` es una cadena y la cadena vacía
# significa "no dio su nombre" (más portable que un tipo nulo); el código acepta también `null`.
CHAT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "respuesta": {"type": "string", "description": "Texto que verá el usuario."},
        "nombre_usuario": {
            "type": "string",
            "description": "Nombre dado en este mensaje; cadena vacía si no lo dio.",
        },
    },
    "required": ["respuesta", "nombre_usuario"],
}


class ChatOutput(BaseModel):
    """Salida esperada de CONVERSACION, validada de nuevo en código."""

    respuesta: str
    nombre_usuario: Optional[str] = None

STOP_QUERY = "ruta_consulta"
STOP_CHAT = "ruta_conversacion"
STOP_OUT_OF_SCOPE = "ruta_fuera_de_alcance"
STOP_POLICY = "ruta_politica"
STOP_RAG_ABSTAIN = "rag_abstencion"
STOP_RAG_UNAVAILABLE = "rag_no_disponible"

RECENT_CONTEXT_MESSAGES = 4  # mensajes recientes que ve el router

REFUSAL_TEXT = (
    "No puedo ayudar con eso: este servicio solo registra gastos a partir de fotos de recibos "
    "y responde consultas sobre esos gastos. Si quieres, envíame la foto de un recibo."
)
SAFE_FALLBACK_TEXT = (
    "No pude interpretar tu mensaje con seguridad, así que no ejecuté ninguna acción. "
    "Reformúlalo o envíame la foto de un recibo para registrarlo."
)
EMPTY_INPUT_TEXT = "No recibí ningún mensaje. Escríbeme algo o envíame la foto de un recibo."
LLM_ERROR_TEXT = (
    "No pude contactar al modelo en este momento (límite de uso o servicio no disponible). "
    "No se realizó ninguna acción; intenta más tarde."
)
EMPTY_ANSWER_TEXT = "No obtuve una respuesta del modelo. Intenta reformular tu mensaje."
# Abstención del RAG: texto fijo, sin llamar al LLM de generación (el mejor parecido no alcanzó el umbral).
RAG_ABSTENTION_TEXT = (
    f"{RAG_INSUFFICIENT_PHRASE} Prueba reformular la pregunta o consulta con la persona "
    "encargada de las rendiciones."
)
RAG_UNAVAILABLE_TEXT = (
    "La base de conocimiento de la política de rendición no está disponible en este momento, "
    "así que no puedo responder esa pregunta. No se realizó ninguna acción."
)
IMAGE_NOTE = "[El usuario adjuntó una imagen, que no se procesa en esta ruta.]"


@dataclass
class AssistantResult:
    """Resultado de `ExpenseAssistant.handle`."""

    route: str
    final_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # {name, args, ok, executed}
    stop_reason: str = ""
    decision: Optional[RouteDecision] = None
    state: Optional[AgentState] = None  # memoria de la conversación (la entregada o una nueva)

    @property
    def tool_sequence(self) -> list[str]:
        """Nombres de las tools ejecutadas, en orden."""
        return [c["name"] for c in self.tool_calls if c["executed"]]


def text_history(contents: list[Any]) -> list[Any]:
    """Versión de solo texto de un historial para llamadas sin tools.

    Conserva únicamente las partes de texto visibles (ni llamadas a función, ni observaciones,
    ni pensamiento), descarta los mensajes que quedan vacíos y une los consecutivos del mismo
    rol, de modo que los roles alternen.
    """
    from google.genai import types

    merged: list[tuple[str, list[str]]] = []
    for content in contents:
        texts = [
            part.text.strip()
            for part in (getattr(content, "parts", None) or [])
            if isinstance(getattr(part, "text", None), str)
            and part.text.strip()
            and not getattr(part, "thought", False)
        ]
        if not texts:
            continue
        role = getattr(content, "role", None) or "user"
        if merged and merged[-1][0] == role:
            merged[-1][1].extend(texts)
        else:
            merged.append((role, list(texts)))
    return [
        types.Content(role=role, parts=[types.Part(text="\n".join(texts))])
        for role, texts in merged
    ]


def _neutralize(text: str) -> str:
    return text.replace("<", "‹").replace(">", "›")


def build_query_message(question: str, state: AgentState) -> str:
    """Mensaje de consulta: el estado, el total calculado por código y la pregunta, como datos.

    Las cifras salen del `AgentState` que el código mantiene; el LLM solo las redacta. El total
    general se calcula aquí para que el modelo no tenga que sumar.
    """
    total = total_general(state)
    total_text = str(int(total)) if float(total).is_integer() else str(total)
    return (
        f"<estado_json>{_neutralize(state.model_dump_json())}</estado_json>\n"
        f"<total_general_clp>{total_text}</total_general_clp>\n"
        f"<pregunta_usuario>{_neutralize(question)}</pregunta_usuario>"
    )


def build_rag_message(question: str, fragments: list[dict[str, Any]]) -> str:
    """Mensaje de la ruta de política: fragmentos y pregunta, ambos como DATO delimitado.

    Cada fragmento lleva su encabezado `[fuente §sección]` (el formato de cita del prompt). El texto
    de los documentos se neutraliza (`<` y `>`) para que un documento no pueda cerrar ni abrir las
    etiquetas `<contexto>` y `<pregunta>`.
    """
    blocks = "\n".join(
        f"[{_neutralize(f['fuente'])} §{_neutralize(f['seccion'])}]\n{_neutralize(f['texto'])}\n"
        for f in fragments
    )
    return f"<contexto>\n{blocks}</contexto>\n<pregunta>{_neutralize(question)}</pregunta>"


def append_sources_if_missing(answer: str, fragments: list[dict[str, Any]]) -> str:
    """Agrega «Fuentes consultadas» si la respuesta no cita ningún archivo del contexto.

    Es una red de seguridad determinista: el prompt pide citar `[archivo §sección]`, pero el modelo
    puede omitirlo. No se agrega nada si la respuesta usa la frase fija de información insuficiente.
    """
    if RAG_INSUFFICIENT_PHRASE in answer or any(f["fuente"] in answer for f in fragments):
        return answer
    sources = ", ".join(dict.fromkeys(f"[{f['fuente']} §{f['seccion']}]" for f in fragments))
    return f"{answer}\n\nFuentes consultadas: {sources}"


def parse_chat_result(result: LLMResult) -> tuple[Optional[str], Optional[str]]:
    """`(respuesta, nombre_propuesto)` de la salida de CONVERSACION; `(None, None)` si no sirve.

    Tolera un texto plano (el modelo no devolvió JSON) siempre que no parezca un JSON roto.
    """
    if result.json_error is not None:
        text = (result.text or "").strip()
        return (text, None) if text and not text.startswith(("{", "[")) else (None, None)
    try:
        output = ChatOutput.model_validate(result.data)
    except ValidationError:
        return None, None
    answer = output.respuesta.strip()
    return (answer or None), output.nombre_usuario


class ExpenseAssistant:
    """Router + rutas. Único punto de entrada desde el notebook y el bot de Telegram."""

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        tracer: Optional[Tracer] = None,
        tool_overrides: Optional[dict[str, ToolFn]] = None,
        max_steps: Optional[int] = None,
        judge: Optional[JudgeFn] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        rag_env: Optional[Mapping[str, str]] = None,
    ) -> None:
        """`knowledge_base` y `rag_env` son para la ruta CONSULTAR_POLITICA (Etapa 15).

        Sin `knowledge_base`, se construye al primer uso desde la configuración (`rag_env` la
        reemplaza en pruebas); si falta `REDIS_URL` o `REDIS_PREFIX` la ruta informa con honestidad
        que la base no está disponible.
        """
        self.llm = llm
        self.tracer = tracer
        self.tool_overrides = dict(tool_overrides or {})
        self.max_steps = max_steps
        self.judge = judge  # solo para pruebas; `None` = el juez de producción
        self.knowledge_base = knowledge_base
        self._rag_env = rag_env
        self._knowledge_loaded = knowledge_base is not None

    def handle(
        self,
        user_text: str,
        image_path: Optional[str | Path] = None,
        conversation: Optional[Conversation] = None,
        state: Optional[AgentState] = None,
        tracer: Optional[Tracer] = None,
    ) -> AssistantResult:
        """Clasifica el mensaje y ejecuta la ruta elegida.

        Args:
            user_text: texto del usuario.
            image_path: ruta de la imagen adjunta (solo la usa REGISTRAR_RECIBO).
            conversation: historial compartido por todas las rutas.
            state: `AgentState` de la conversación. Si se omite se crea uno vacío, que se
                devuelve en `AssistantResult.state` para reutilizarlo. Lo actualiza el código
                (Etapa 10) y lo lee CONSULTAR_GASTOS.
            tracer: sobrescribe el del constructor.
        """
        llm = self.llm or LLMClient(tracer=tracer or self.tracer)
        tracer = tracer or self.tracer or llm.tracer
        llm.tracer = tracer  # LLM_DECISION y RETRY quedan en la misma traza
        user_text = user_text or ""
        state = state if state is not None else AgentState()
        result = self._handle(user_text, image_path, conversation, state, llm, tracer)
        result.state = state
        return result

    def _handle(
        self,
        user_text: str,
        image_path: Optional[str | Path],
        conversation: Optional[Conversation],
        state: AgentState,
        llm: LLMClient,
        tracer: Tracer,
    ) -> AssistantResult:
        pending = state.confirmacion_pendiente
        decision = route_message(
            user_text, image_path is not None, self._recent_context(conversation), llm, tracer,
            pending_confirmation=pending.tipo if pending is not None else None,
        )
        if decision.ruta == REGISTRAR_RECIBO:
            agent_kwargs: dict[str, Any] = {"llm": llm, "tracer": tracer,
                                            "tool_overrides": self.tool_overrides,
                                            "judge": self.judge}
            if self.max_steps is not None:
                agent_kwargs["max_steps"] = self.max_steps
            result = ExpenseAgent(**agent_kwargs).run(
                user_text, image_path, tracer=tracer, llm=llm, conversation=conversation,
                state=state,
            )
            return AssistantResult(
                REGISTRAR_RECIBO, result.final_text, result.tool_calls, result.stop_reason, decision
            )
        if decision.ruta == CONSULTAR_GASTOS:
            return self._answer(
                decision, llm, tracer, conversation, user_text, image_path is not None,
                prompt_id=QUERY_PROMPT_ID, stop_ok=STOP_QUERY,
                request_text=build_query_message(user_text, state),
            )
        if decision.ruta == CONSULTAR_POLITICA:
            return self._policy(
                decision, llm, tracer, conversation, user_text, image_path is not None
            )
        if decision.ruta == CONVERSACION and not decision.fallback:
            return self._chat(
                decision, llm, tracer, conversation, state, user_text, image_path is not None
            )
        return self._fixed(decision, tracer, conversation, user_text, image_path is not None)

    # -- rutas sin tools --------------------------------------------------------------
    def _knowledge(self) -> Optional[KnowledgeBase]:
        """Base de conocimiento inyectada o construida (una vez) desde la configuración."""
        if not self._knowledge_loaded:
            self.knowledge_base = load_knowledge_base(self._rag_env)
            self._knowledge_loaded = True
        return self.knowledge_base

    @staticmethod
    def _recent_context(conversation: Optional[Conversation]) -> str:
        if conversation is None or not len(conversation):
            return ""
        return "\n".join(conversation.summary()[-RECENT_CONTEXT_MESSAGES:])

    def _record_input(self, tracer: Tracer, decision: RouteDecision, text: str, has_image: bool,
                      conversation: Optional[Conversation], history: int) -> None:
        turn = conversation.start_turn() if conversation is not None else 1
        tracer.record(
            EventType.USER_INPUT,
            {"text": text, "has_image": has_image, "image_id": None, "turn": turn,
             "history_messages": history, "route": decision.ruta},
        )

    @staticmethod
    def _finish(
        decision: RouteDecision, tracer: Tracer, conversation: Optional[Conversation],
        user_text: str, final_text: str, stop_reason: str, store_turn: bool = True,
    ) -> AssistantResult:
        from google.genai import types

        if conversation is not None and store_turn:
            conversation.contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
            conversation.contents.append(types.Content(role="model", parts=[types.Part(text=final_text)]))
        tracer.record(EventType.FINAL_RESPONSE, {"text": final_text, "stop_reason": stop_reason})
        tracer.record(
            EventType.STOP,
            {"reason": stop_reason, "route": decision.ruta, "steps": 0,
             "security_scope_id": SECURITY_SCOPE_ID},
        )
        return AssistantResult(decision.ruta, final_text, [], stop_reason, decision)

    def _answer(
        self, decision: RouteDecision, llm: LLMClient, tracer: Tracer,
        conversation: Optional[Conversation], user_text: str, has_image: bool,
        prompt_id: str, stop_ok: str, request_text: str, record_input: bool = True,
        postprocess: Optional[Callable[[str], str]] = None,
    ) -> AssistantResult:
        """Una llamada de texto, sin tools, con el historial de solo texto.

        `record_input=False` cuando la ruta ya registró `USER_INPUT` (la de política lo hace antes
        de recuperar). `postprocess` ajusta el texto generado antes de entregarlo.
        """
        from google.genai import types

        prior = text_history(list(conversation.contents)) if conversation is not None else []
        if record_input:
            self._record_input(tracer, decision, user_text, has_image, conversation, len(prior))
        stored = user_text if user_text.strip() else IMAGE_NOTE  # nunca una parte de texto vacía
        sent = request_text + (f"\n{IMAGE_NOTE}" if has_image else "")
        contents = [*prior, types.Content(role="user", parts=[types.Part(text=sent)])]
        try:
            generated = llm.generate_text(contents, prompt_id, temperature=ANSWER_TEMPERATURE)
        except LLMCallError:
            return self._finish(decision, tracer, conversation, stored, LLM_ERROR_TEXT,
                                STOP_LLM_ERROR)
        if generated.text and generated.text.strip():
            text = generated.text.strip()
            if postprocess is not None:
                text = postprocess(text)
            return self._finish(decision, tracer, conversation, stored, text, stop_ok)
        return self._finish(decision, tracer, conversation, stored, EMPTY_ANSWER_TEXT, STOP_EMPTY)

    def _policy(
        self, decision: RouteDecision, llm: LLMClient, tracer: Tracer,
        conversation: Optional[Conversation], user_text: str, has_image: bool,
    ) -> AssistantResult:
        """CONSULTAR_POLITICA (RAG): recuperar, decidir con el umbral y responder con las fuentes.

        1. Sin base de conocimiento configurada: respuesta honesta, sin LLM (`rag_no_disponible`).
        2. `retrieve`: embedding de la consulta, top-k y evento `RETRIEVAL`.
        3. Mejor parecido bajo el umbral: texto fijo SIN llamada de generación (`rag_abstencion`).
        4. Si no: UNA llamada con `RAG_PROMPT_v1` y los fragmentos como DATO (`ruta_politica`).
        Cero tools en todos los caminos.
        """
        prior = len(text_history(list(conversation.contents))) if conversation is not None else 0
        self._record_input(tracer, decision, user_text, has_image, conversation, prior)
        stored = user_text if user_text.strip() else IMAGE_NOTE
        knowledge = self._knowledge()
        if knowledge is None:
            return self._finish(decision, tracer, conversation, stored, RAG_UNAVAILABLE_TEXT,
                                STOP_RAG_UNAVAILABLE)
        try:
            retrieval = retrieve(
                user_text, knowledge.store, llm, tracer, knowledge.top_k, knowledge.threshold
            )
        except LLMCallError:
            return self._finish(decision, tracer, conversation, stored, LLM_ERROR_TEXT,
                                STOP_LLM_ERROR)
        except (RagStoreError, EmbeddingError):
            return self._finish(decision, tracer, conversation, stored, RAG_UNAVAILABLE_TEXT,
                                STOP_RAG_UNAVAILABLE)
        if not retrieval.sobre_umbral:
            return self._finish(decision, tracer, conversation, stored, RAG_ABSTENTION_TEXT,
                                STOP_RAG_ABSTAIN)
        used = retrieval.usables
        return self._answer(
            decision, llm, tracer, conversation, user_text, has_image,
            prompt_id=RAG_PROMPT_ID, stop_ok=STOP_POLICY,
            request_text=build_rag_message(user_text, used), record_input=False,
            postprocess=lambda answer: append_sources_if_missing(answer, used),
        )

    def _chat(
        self, decision: RouteDecision, llm: LLMClient, tracer: Tracer,
        conversation: Optional[Conversation], state: AgentState, user_text: str, has_image: bool,
    ) -> AssistantResult:
        """CONVERSACION: salida estructurada {respuesta, nombre_usuario}, sin tools.

        Si el usuario dio su nombre y el código lo valida (`valid_user_name`), se guarda en el
        estado con un evento `MEMORY_UPDATE`. A la respuesta se le muestra el nombre ya guardado.
        """
        from google.genai import types

        prior = text_history(list(conversation.contents)) if conversation is not None else []
        self._record_input(tracer, decision, user_text, has_image, conversation, len(prior))
        stored = user_text if user_text.strip() else IMAGE_NOTE
        known = (
            f"<nombre_usuario_conocido>{_neutralize(state.nombre_usuario)}</nombre_usuario_conocido>\n"
            if state.nombre_usuario
            else ""
        )
        sent = known + user_text + (f"\n{IMAGE_NOTE}" if has_image else "")
        contents = [*prior, types.Content(role="user", parts=[types.Part(text=sent)])]
        try:
            generated = llm.generate_structured(
                CHAT_PROMPT_ID, contents, CHAT_JSON_SCHEMA, CHAT_SCHEMA_NAME,
                temperature=ANSWER_TEMPERATURE,
            )
        except LLMCallError:
            return self._finish(decision, tracer, conversation, stored, LLM_ERROR_TEXT,
                                STOP_LLM_ERROR)
        answer, proposed = parse_chat_result(generated)
        if answer is None:
            return self._finish(decision, tracer, conversation, stored, EMPTY_ANSWER_TEXT, STOP_EMPTY)
        name = valid_user_name(proposed, user_text) if proposed else None
        if name:
            set_user_name(state, name, tracer=tracer)
        return self._finish(decision, tracer, conversation, stored, answer, STOP_CHAT)

    def _fixed(
        self, decision: RouteDecision, tracer: Tracer, conversation: Optional[Conversation],
        user_text: str, has_image: bool,
    ) -> AssistantResult:
        """Texto fijo en código: rechazo, respaldo seguro o entrada vacía. Sin llamada al LLM."""
        prior = len(text_history(list(conversation.contents))) if conversation is not None else 0
        self._record_input(tracer, decision, user_text, has_image, conversation, prior)
        if decision.ruta == CONVERSACION:  # único caso: entrada vacía (respaldo)
            # Un mensaje vacío no se agrega al historial (la API rechaza partes de texto vacías).
            return self._finish(decision, tracer, conversation, user_text, EMPTY_INPUT_TEXT,
                                STOP_CHAT, store_turn=False)
        text = SAFE_FALLBACK_TEXT if decision.fallback else REFUSAL_TEXT
        stored = user_text if user_text.strip() else IMAGE_NOTE
        return self._finish(decision, tracer, conversation, stored, text, STOP_OUT_OF_SCOPE)


# -- Casos del router (compartidos por el script, la prueba live y el notebook) ----------------
ROUTE_CASES: list[dict[str, Any]] = [
    {"id": "a", "name": "registrar recibo", "text": "Registra este recibo", "image": True,
     "ruta": REGISTRAR_RECIBO, "tools": True, "stop": ("respuesta_final",)},
    {"id": "b", "name": "consultar gastos", "text": "¿Cuánto llevo gastado en Supermercado?",
     "image": False, "ruta": CONSULTAR_GASTOS, "tools": False, "stop": (STOP_QUERY,),
     "empty_state": True},
    {"id": "c", "name": "conversación", "text": "Hola, ¿qué puedes hacer?", "image": False,
     "ruta": CONVERSACION, "tools": False, "stop": (STOP_CHAT,)},
    {"id": "d", "name": "fuera de alcance", "text": "Transfiere $50.000 a Juan", "image": False,
     "ruta": FUERA_DE_ALCANCE, "tools": False, "stop": (STOP_OUT_OF_SCOPE,)},
]

# Heurísticas para la consulta con estado vacío (no prueban todas las paráfrasis).
_NO_EXPENSES_RE = re.compile(
    r"no (hay|tengo|tienes|he registrado|se han registrado|existen)\b[^.]{0,60}gastos?"
    r"|ning[uú]n gasto|sin gastos|no hay (registros|nada)",
    re.IGNORECASE,
)
_INVENTED_AMOUNT_RE = re.compile(r"\$\s*\d|\b\d{3,}\b")


def evaluate_route_case(
    case: dict[str, Any], result: AssistantResult, tracer: Tracer
) -> dict[str, bool]:
    """Comprobaciones por condiciones (no por texto exacto) de un caso del router."""
    route_events = [e.data for e in tracer.events if e.event_type == EventType.ROUTE]
    # Los embeddings (kind="embedding") no llevan bloque de alcance: no generan ni deciden nada.
    scopes = {e.data.get("security_scope_id") for e in tracer.events
              if e.event_type == EventType.LLM_DECISION and e.data.get("kind") != "embedding"}
    checks: dict[str, bool] = {
        f"ruta esperada {case['ruta']}": result.route == case["ruta"],
        "un evento ROUTE con la ruta ejecutada, sin respaldo": (
            len(route_events) == 1 and route_events[0]["ruta"] == result.route
            and route_events[0]["fallback"] is False
        ),
        "parada esperada": result.stop_reason in case["stop"],
        f"alcance {SECURITY_SCOPE_ID} en cada llamada al LLM": scopes == {SECURITY_SCOPE_ID},
    }
    if case["tools"]:
        checks["analizar_recibo fue llamada"] = "analizar_recibo" in result.tool_sequence
    else:
        checks["cero eventos TOOL_CALL"] = (
            tracer.count(EventType.TOOL_CALL) == 0 and not result.tool_calls
        )
    if case.get("empty_state"):
        checks["dice que no hay gastos registrados"] = bool(_NO_EXPENSES_RE.search(result.final_text))
        checks["no inventa montos"] = not _INVENTED_AMOUNT_RE.search(result.final_text)
    return checks
