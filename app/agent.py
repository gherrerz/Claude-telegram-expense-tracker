"""Agente ReAct: el LLM decide, se ejecuta la tool y la observación vuelve al LLM.

Ciclo (explícito, sin frameworks):

    USER_INPUT
    repetir hasta MAX_STEPS decisiones:
        decisión del LLM (function calling nativo, modo AUTO)
        - sin llamadas a función  -> STOP(respuesta_final) + FINAL_RESPONSE
        - con llamadas a función  -> TOOL_CALL, despacho, TOOL_RESULT y la
          observación se agrega al historial como `function_response`
    si la decisión número MAX_STEPS aún pide tools -> STOP(max_steps) y respuesta
    segura; esas llamadas NO se ejecutan.

El código NO fija el orden de las herramientas: la secuencia la decide el LLM.
El código sí aplica rieles que no dependen del prompt (ver `_Dispatcher`).

Condiciones de parada (evento `STOP`, campo `reason`):
- `respuesta_final`: el LLM respondió sin pedir tools.
- `max_steps`: se alcanzó el límite de decisiones sin respuesta final.
- `error_llm`: la API falló tras agotar los reintentos.
- `respuesta_vacia`: el LLM no devolvió texto ni llamadas.

Historial (Etapa 7): con `run(..., conversation=Conversation())` el agente antepone
al turno TODOS los mensajes previos y, al terminar, agrega a la conversación lo
nuevo de la ejecución (mensaje del usuario, contenido del modelo sin modificar,
llamadas y observaciones). Si la parada NO es `respuesta_final` (`max_steps`,
`error_llm`, `respuesta_vacia`), se agrega además un mensaje del modelo con el
texto seguro que se entregó al usuario, para que los roles sigan alternando y el
LLM sepa en el turno siguiente qué se le respondió; el `Content` vacío o la
llamada a tool no ejecutada del modelo nunca se agregan. Si `run` lanza una
excepción inesperada, el historial no se modifica. Sin `conversation` el
comportamiento es el de un solo turno (Etapa 6).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.conversation import Conversation
from app.llm import AGENT_TEMPERATURE, LLMCallError, LLMClient
from app.models import ALLOWED_CATEGORIES, CONFIDENCE_THRESHOLD, UNKNOWN, EventType, ReceiptData, TraceEvent
from app.prompts import SECURITY_SCOPE_ID
from app.trace import Tracer

MAX_STEPS = 6
AGENT_PROMPT_ID = "AGENT_PROMPT_v2"
IMAGE_ID = "img_1"  # identificador de la imagen sin conversación; el LLM nunca recibe bytes

STOP_FINAL = "respuesta_final"
STOP_MAX_STEPS = "max_steps"
STOP_LLM_ERROR = "error_llm"
STOP_EMPTY = "respuesta_vacia"

ToolFn = Callable[..., dict[str, Any]]


def build_tool_declarations() -> list[Any]:
    """Declaraciones de las tres tools para function calling nativo."""
    from google.genai import types

    declarations = [
        types.FunctionDeclaration(
            name="analizar_recibo",
            description=(
                "Lee la imagen de recibo adjunta con visión y devuelve fecha, comercio, monto, "
                "categoría y confianza. Un dato ilegible vale 'desconocido'."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "image_id": {"type": "string", "description": "Identificador de la imagen adjunta."}
                },
                "required": ["image_id"],
            },
        ),
        types.FunctionDeclaration(
            name="guardar_recibo",
            description=(
                "Sube la imagen adjunta a la carpeta de prueba de Google Drive y devuelve su "
                "web_view_link. Requiere haber analizado el recibo antes."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "comercio": {"type": "string", "description": "Comercio extraído del recibo."},
                    "fecha": {"type": "string", "description": "Fecha ISO AAAA-MM-DD del recibo."},
                },
                "required": ["comercio", "fecha"],
            },
        ),
        types.FunctionDeclaration(
            name="registrar_gasto",
            description=(
                "Agrega una fila de gasto a la planilla de prueba de Google Sheets. Solo agrega; "
                "recibo_url debe ser el web_view_link devuelto por guardar_recibo."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "Fecha ISO AAAA-MM-DD."},
                    "comercio": {"type": "string"},
                    "monto": {"type": "number", "description": "Total pagado, positivo."},
                    "categoria": {"type": "string", "enum": list(ALLOWED_CATEGORIES)},
                    "recibo_url": {"type": "string", "description": "web_view_link de guardar_recibo."},
                },
                "required": ["fecha", "comercio", "monto", "categoria", "recibo_url"],
            },
        ),
    ]
    return [types.Tool(function_declarations=declarations)]


# Argumentos obligatorios por tool, para validar antes de despachar.
_REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "analizar_recibo": ("image_id",),
    "guardar_recibo": ("comercio", "fecha"),
    "registrar_gasto": ("fecha", "comercio", "monto", "categoria", "recibo_url"),
}


@dataclass
class AgentResult:
    """Resultado de una ejecución del agente."""

    final_text: str
    stop_reason: str
    steps: int  # decisiones del LLM realizadas
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # {name, args, ok, executed}
    events: list[TraceEvent] = field(default_factory=list)
    messages: list[Any] = field(default_factory=list)  # mensajes enviados al LLM (historial + turno)

    @property
    def tool_sequence(self) -> list[str]:
        """Nombres de las tools ejecutadas, en orden."""
        return [c["name"] for c in self.tool_calls if c["executed"]]


@dataclass
class _RunContext:
    """Estado de UNA ejecución, usado por los rieles de código."""

    image_path: Optional[Path]
    image_id: str = IMAGE_ID  # identificador de la imagen de ESTE turno
    analysis: Optional[ReceiptData] = None
    drive_links: set[str] = field(default_factory=set)
    registered_row: Optional[int] = None


def _needs_confirmation(receipt: ReceiptData) -> Optional[str]:
    """Motivo por el que NO se puede registrar sin confirmación, o `None`."""
    if receipt.confianza < CONFIDENCE_THRESHOLD:
        return f"confianza {receipt.confianza} menor que {CONFIDENCE_THRESHOLD}"
    unknown = [
        name
        for name in ("fecha", "comercio", "monto", "categoria")
        if getattr(receipt, name) == UNKNOWN
    ]
    if unknown:
        return f"campos desconocidos: {', '.join(unknown)}"
    return None


class _Dispatcher:
    """Ejecuta las tools aplicando validación y rieles. Nunca lanza excepciones."""

    def __init__(
        self,
        ctx: _RunContext,
        llm: LLMClient,
        overrides: dict[str, ToolFn],
    ) -> None:
        self.ctx = ctx
        self.llm = llm
        self.overrides = overrides

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in _REQUIRED_ARGS:
            return {"ok": False, "error": f"Herramienta desconocida: {name}. No se ejecutó nada."}
        missing = [a for a in _REQUIRED_ARGS[name] if a not in args or args[a] in (None, "")]
        if missing:
            return {"ok": False, "error": f"Faltan argumentos obligatorios: {', '.join(missing)}."}
        handler = getattr(self, f"_do_{name}")
        try:
            return handler(args)
        except LLMCallError:
            return {"ok": False, "error": "Falló la llamada al modelo de visión; reintenta más tarde."}
        except Exception as error:  # noqa: BLE001 - solo el tipo, nunca detalles internos
            return {"ok": False, "error": f"Falló la herramienta ({type(error).__name__})."}

    # -- tools -------------------------------------------------------------------
    def _image_error(self, image_id: Any = None) -> Optional[dict[str, Any]]:
        if self.ctx.image_path is None:
            return {"ok": False, "error": "No hay ninguna imagen adjunta en este mensaje."}
        if image_id is None:
            image_id = self.ctx.image_id
        if image_id != self.ctx.image_id:
            return {
                "ok": False,
                "error": f"image_id desconocido: {image_id}. Usa {self.ctx.image_id}.",
            }
        return None

    def _do_analizar_recibo(self, args: dict[str, Any]) -> dict[str, Any]:
        problem = self._image_error(args["image_id"])
        if problem:
            return problem
        if "analizar_recibo" in self.overrides:
            receipt = self.overrides["analizar_recibo"](self.ctx.image_path)
        else:
            from app.tools.analyzer import analizar_recibo

            # Tracer silencioso: el agente ya registra TOOL_CALL/TOOL_RESULT; la
            # llamada de visión sí queda en la traza del cliente LLM.
            receipt = analizar_recibo(
                self.ctx.image_path, llm=self.llm, tracer=Tracer(console=False, write_file=False)
            )
        self.ctx.analysis = receipt
        reason = _needs_confirmation(receipt)
        return {
            "ok": True,
            "datos": receipt.model_dump(),
            "requiere_confirmacion": reason is not None,
            "motivo": reason,
        }

    def _do_guardar_recibo(self, args: dict[str, Any]) -> dict[str, Any]:
        problem = self._image_error()
        if problem:
            return problem
        if self.ctx.analysis is None:
            return {"ok": False, "error": "Primero hay que analizar el recibo con analizar_recibo."}
        if "guardar_recibo" in self.overrides:
            result = self.overrides["guardar_recibo"](
                self.ctx.image_path, args["comercio"], args["fecha"]
            )
        else:
            from app.tools.drive import guardar_recibo

            result = guardar_recibo(
                self.ctx.image_path,
                args["comercio"],
                args["fecha"],
                tracer=Tracer(console=False, write_file=False),
            )
        if result.success and result.web_view_link:
            self.ctx.drive_links.add(result.web_view_link)
        return {
            "ok": result.success,
            "file_name": result.file_name,
            "web_view_link": result.web_view_link,
            "error": result.error,
        }

    def _do_registrar_gasto(self, args: dict[str, Any]) -> dict[str, Any]:
        # Rieles de código: valen aunque el LLM ignore el prompt.
        if self.ctx.analysis is None:
            return {"ok": False, "error": "Primero hay que analizar el recibo con analizar_recibo."}
        reason = _needs_confirmation(self.ctx.analysis)
        if reason is not None:
            return {
                "ok": False,
                "error": (
                    f"Registro bloqueado: la extracción necesita confirmación del usuario ({reason}). "
                    "Pide al usuario que confirme o aclare los datos."
                ),
            }
        if args["recibo_url"] not in self.ctx.drive_links:
            return {
                "ok": False,
                "error": (
                    "Registro bloqueado: la url no proviene de guardar_recibo en esta ejecución. "
                    "Guarda el recibo primero y usa el web_view_link devuelto."
                ),
            }
        monto = args["monto"]
        if isinstance(monto, float) and not math.isfinite(monto):
            return {"ok": False, "error": "El monto debe ser un número finito."}
        kwargs = dict(
            fecha=args["fecha"],
            comercio=args["comercio"],
            monto=monto,
            categoria=args["categoria"],
            recibo_url=args["recibo_url"],
        )
        if "registrar_gasto" in self.overrides:
            result = self.overrides["registrar_gasto"](**kwargs)
        else:
            from app.tools.sheets import registrar_gasto

            result = registrar_gasto(**kwargs, tracer=Tracer(console=False, write_file=False))
        if result.success and result.row_number is not None:
            self.ctx.registered_row = result.row_number
        return {
            "ok": result.success,
            "row_number": result.row_number,
            "duplicate": result.duplicate,
            "error": result.error,
        }


def _safe_max_steps_message(ctx: _RunContext) -> str:
    """Respuesta segura al llegar al límite; solo afirma lo que el código observó."""
    if ctx.registered_row is not None:
        return (
            f"Alcancé el límite de {MAX_STEPS} pasos sin cerrar la conversación. "
            f"El gasto sí quedó registrado en la fila {ctx.registered_row}; verifica la planilla."
        )
    return (
        f"Alcancé el límite de {MAX_STEPS} pasos sin completar el registro. "
        "No se registró ningún gasto. Intenta de nuevo o reformula tu solicitud."
    )


def _commit_turn(
    conversation: Conversation, new_messages: list[Any], stop_reason: str, final_text: str
) -> None:
    """Agrega a la conversación lo nuevo de una ejecución (ver docstring del módulo)."""
    from google.genai import types

    messages = list(new_messages)
    if stop_reason != STOP_FINAL:
        if stop_reason == STOP_EMPTY and messages and getattr(messages[-1], "role", None) == "model":
            messages.pop()  # un Content de modelo sin texto ni llamadas no se reenvía
        messages.append(types.Content(role="model", parts=[types.Part(text=final_text)]))
    conversation.contents.extend(messages)


class ExpenseAgent:
    """Agente de gastos con loop ReAct propio sobre function calling nativo."""

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        tracer: Optional[Tracer] = None,
        tool_overrides: Optional[dict[str, ToolFn]] = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        self.llm = llm
        self.tracer = tracer
        self.tool_overrides = dict(tool_overrides or {})
        self.max_steps = max_steps

    def run(
        self,
        user_text: str,
        image_path: Optional[str | Path] = None,
        tracer: Optional[Tracer] = None,
        llm: Optional[LLMClient] = None,
        tool_overrides: Optional[dict[str, ToolFn]] = None,
        conversation: Optional[Conversation] = None,
    ) -> AgentResult:
        """Ejecuta el loop para un mensaje del usuario.

        Args:
            user_text: texto del usuario.
            image_path: ruta de la imagen adjunta (el LLM solo ve su `image_id`).
            tracer, llm: sobrescriben los del constructor. Si ambos se omiten se
                crean con la configuración del entorno.
            tool_overrides: `{nombre: función}` que reemplazan a las tools reales
                (pruebas). `analizar_recibo(path) -> ReceiptData`,
                `guardar_recibo(path, comercio, fecha) -> DriveResult`,
                `registrar_gasto(**args) -> SheetResult`.
            conversation: historial de la conversación. Sus mensajes se anteponen
                al turno y, al terminar (con cualquier motivo de parada), se le
                agrega lo nuevo. Sin él, la ejecución es de un solo turno. La
                instrucción de sistema se envía en cada llamada y NO se guarda.
        """
        from google.genai import types

        llm = llm or self.llm or LLMClient(tracer=tracer or self.tracer)
        tracer = tracer or self.tracer or llm.tracer
        llm.tracer = tracer  # LLM_DECISION y RETRY quedan en la misma traza
        overrides = {**self.tool_overrides, **(tool_overrides or {})}
        first_event = len(tracer.events)

        path = Path(image_path) if image_path is not None else None
        prior: list[Any] = list(conversation.contents) if conversation is not None else []
        turn = conversation.start_turn() if conversation is not None else 1
        image_id = IMAGE_ID
        if conversation is not None and path is not None:
            image_id = conversation.register_image(path)
        ctx = _RunContext(image_path=path, image_id=image_id)
        dispatcher = _Dispatcher(ctx, llm, overrides)
        tools = build_tool_declarations()

        tracer.record(
            EventType.USER_INPUT,
            {"text": user_text, "has_image": path is not None,
             "image_id": image_id if path is not None else None,
             "turn": turn, "history_messages": len(prior)},
        )
        text = user_text
        if path is not None:
            text += f"\n[Adjunto: imagen de un recibo, image_id={image_id}]"
        contents: list[Any] = list(prior)
        contents.append(types.Content(role="user", parts=[types.Part(text=text)]))

        tool_calls: list[dict[str, Any]] = []
        steps = 0
        final_text = ""
        stop_reason = STOP_MAX_STEPS

        def stop(reason: str, **extra: Any) -> None:
            tracer.record(
                EventType.STOP,
                {"reason": reason, "steps": steps, "max_steps": self.max_steps,
                 "security_scope_id": SECURITY_SCOPE_ID, **extra},
            )

        while True:
            steps += 1
            try:
                decision = llm.generate_with_tools(
                    contents, tools, AGENT_PROMPT_ID, temperature=AGENT_TEMPERATURE
                )
            except LLMCallError as error:
                stop_reason = STOP_LLM_ERROR
                final_text = (
                    "No pude contactar al modelo en este momento (límite de uso o servicio no "
                    "disponible). No se realizó ninguna acción adicional; intenta más tarde."
                )
                stop(STOP_LLM_ERROR, error_code=error.code, error_status=error.status)
                break

            if not decision.function_calls:
                if decision.text and decision.text.strip():
                    stop_reason, final_text = STOP_FINAL, decision.text.strip()
                else:
                    stop_reason = STOP_EMPTY
                    final_text = "No obtuve una respuesta del modelo. Intenta reformular tu mensaje."
                if decision.content is not None:
                    contents.append(decision.content)
                stop(stop_reason)
                break

            if steps >= self.max_steps:
                # Límite alcanzado: estas llamadas NO se ejecutan.
                stop_reason = STOP_MAX_STEPS
                final_text = _safe_max_steps_message(ctx)
                stop(STOP_MAX_STEPS, skipped_calls=[c.name for c in decision.function_calls])
                break

            # El Content del modelo se agrega SIN modificar (conserva las firmas de pensamiento).
            contents.append(decision.content)
            response_parts = []
            for call in decision.function_calls:
                tracer.record(
                    EventType.TOOL_CALL,
                    {"tool": call.name, "args": call.args, "call_id": call.id, "agent_step": steps},
                )
                observation = dispatcher.dispatch(call.name, call.args)
                tracer.record(
                    EventType.TOOL_RESULT,
                    {"tool": call.name, "ok": observation.get("ok"), "result": observation,
                     "agent_step": steps},
                )
                tool_calls.append(
                    {"name": call.name, "args": call.args, "ok": bool(observation.get("ok")),
                     "executed": call.name in _REQUIRED_ARGS}
                )
                response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call.id, name=call.name, response=observation
                        )
                    )
                )
            # Las observaciones vuelven al LLM con rol "user" (convención del SDK).
            contents.append(types.Content(role="user", parts=response_parts))

        if conversation is not None:
            _commit_turn(conversation, contents[len(prior):], stop_reason, final_text)
        tracer.record(EventType.FINAL_RESPONSE, {"text": final_text, "stop_reason": stop_reason})
        return AgentResult(
            final_text=final_text,
            stop_reason=stop_reason,
            steps=steps,
            tool_calls=tool_calls,
            events=list(tracer.events[first_event:]),
            messages=contents,
        )


def run_agent(user_text: str, image_path: Optional[str | Path] = None, **kwargs: Any) -> AgentResult:
    """Atajo: `ExpenseAgent().run(...)`."""
    return ExpenseAgent().run(user_text, image_path, **kwargs)
