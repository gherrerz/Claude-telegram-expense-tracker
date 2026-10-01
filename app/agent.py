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

Memoria avanzada (Etapa 10): con `run(..., state=AgentState())` el código actualiza el estado a
partir de lo que observa (nunca de lo que diga el LLM) y aplica dos rieles más:

- Duplicados. Tras `analizar_recibo` se calcula la huella del recibo (hash de la imagen + campos).
  Si ya está en `state.recibos_registrados`, la observación informa `posible_duplicado` con la
  fila existente, queda una confirmación pendiente (`duplicado`) y `guardar_recibo` y
  `registrar_gasto` se bloquean para ese recibo. La confianza baja deja una pendiente
  `baja_confianza` (solo bloquea `registrar_gasto`, como en la Etapa 6).
- Confirmación del usuario. `confirmado_por_usuario=true` solo se acepta si el estado tiene una
  confirmación pendiente de un turno ANTERIOR (`pendiente.turno < Conversation.turn`) para el
  mismo recibo. Dentro del mismo turno se rechaza con un error como observación. En el turno de
  confirmación, si el usuario no reenvía la imagen, el agente restaura el análisis y la imagen
  pendientes y se los entrega al LLM en un bloque `<confirmacion_pendiente>`, de modo que se
  confirma solo con texto ("sí, regístralo de todas formas") sin volver a llamar a
  `analizar_recibo`. Un duplicado confirmado llama a Sheets con `permitir_duplicado=True`; el
  LLM no controla ese parámetro. Sin `Conversation` el turno es siempre 1: no hay confirmación.
- Tras una escritura exitosa (no duplicada) se llama a `record_expense` y se borra la
  confirmación pendiente. Si la planilla reporta un duplicado (Etapa 5) NO se registra como gasto
  nuevo: se informa la fila existente y queda una pendiente `duplicado` para que el usuario pueda
  confirmarlo en un turno posterior. Sin `state` el comportamiento es el de las Etapas 6 a 9.

Juez (Etapa 11): tras CADA `analizar_recibo` exitoso el código llama al juez (`app/judge.py`), una
llamada LLM independiente que solo ve la imagen y los datos extraídos. No es una tool del LLM: no
puede omitirlo ni invocarlo. El veredicto se aplica en código antes de `guardar_recibo` y de
`registrar_gasto`:

- `APROBAR`: se permite guardar y registrar (siguen rigiendo los rieles de las Etapas 6 y 10).
- `PEDIR_CONFIRMACION`: deja una confirmación pendiente de tipo `juez`; solo un `confirmado_por_usuario`
  de un turno POSTERIOR la desbloquea (la misma regla de la Etapa 10). Esa confirmación cubre también un
  duplicado o una confianza baja del mismo recibo, porque la observación los informó juntos. En el
  turno de confirmación el juez NO se vuelve a ejecutar: el usuario ya aceptó la duda; el veredicto
  original queda en la traza y en la pendiente.
- `RECHAZAR`: bloqueo definitivo para ese recibo (misma imagen): se guarda en
  `state.recibos_rechazados` y ninguna confirmación lo desbloquea; el LLM recibe el error
  `rechazado_por_juez`. Sin `state` el rechazo vale solo durante la ejecución.
- Falla del juez: veredicto `RECHAZAR` con la señal `juez_no_disponible`. Bloquea esta ejecución pero no
  se guarda como rechazo definitivo: el siguiente análisis vuelve a llamar al juez.

El juez de producción es `app.judge.judge_receipt`; se puede inyectar otro (`ExpenseAgent(judge=...)`),
pero solo código del programador, nunca el LLM.

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

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.conversation import Conversation
from app import judge as judge_module
from app.judge import APROBAR, PEDIR_CONFIRMACION, RECHAZAR, JudgeVerdict, unavailable_verdict
from app.llm import AGENT_TEMPERATURE, LLMCallError, LLMClient
from app.memory import (
    build_key,
    clear_pending_confirmation,
    existing_row,
    image_hash,
    is_duplicate,
    record_expense,
    reject_receipt,
    rejected_key,
    same_receipt,
    set_pending_confirmation,
)
from app.models import (
    ALLOWED_CATEGORIES,
    CONFIDENCE_THRESHOLD,
    UNKNOWN,
    AgentState,
    EventType,
    ReceiptData,
    TraceEvent,
)
from app.prompts import SECURITY_SCOPE_ID
from app.security import sanitize_failure, sanitize_observation
from app.trace import Tracer

MAX_STEPS = 6
AGENT_PROMPT_ID = "AGENT_PROMPT_v3"
IMAGE_ID = "img_1"  # identificador de la imagen sin conversación; el LLM nunca recibe bytes

STOP_FINAL = "respuesta_final"
STOP_MAX_STEPS = "max_steps"
STOP_LLM_ERROR = "error_llm"
STOP_EMPTY = "respuesta_vacia"

ToolFn = Callable[..., dict[str, Any]]
JudgeFn = Callable[..., JudgeVerdict]  # (imagen, datos extraídos, llm, tracer) -> JudgeVerdict


_CONFIRMED_PROPERTY = {
    "type": "boolean",
    "description": (
        "true solo si el usuario confirmó el registro en el mensaje ACTUAL, respondiendo a una "
        "pregunta de confirmación hecha en un mensaje anterior. El código rechaza cualquier otro uso."
    ),
}


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
                "web_view_link. Requiere haber analizado el recibo antes. Para un recibo ya "
                "registrado (posible duplicado) se bloquea hasta que el usuario confirme."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "comercio": {"type": "string", "description": "Comercio extraído del recibo."},
                    "fecha": {"type": "string", "description": "Fecha ISO AAAA-MM-DD del recibo."},
                    "confirmado_por_usuario": _CONFIRMED_PROPERTY,
                },
                "required": ["comercio", "fecha"],
            },
        ),
        types.FunctionDeclaration(
            name="registrar_gasto",
            description=(
                "Agrega una fila de gasto a la planilla de prueba de Google Sheets. Solo agrega; "
                "recibo_url debe ser el web_view_link devuelto por guardar_recibo. Se bloquea si "
                "el recibo es un posible duplicado o la extracción es poco fiable, hasta que el "
                "usuario confirme."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "Fecha ISO AAAA-MM-DD."},
                    "comercio": {"type": "string"},
                    "monto": {"type": "number", "description": "Total pagado, positivo."},
                    "categoria": {"type": "string", "enum": list(ALLOWED_CATEGORIES)},
                    "recibo_url": {"type": "string", "description": "web_view_link de guardar_recibo."},
                    "confirmado_por_usuario": _CONFIRMED_PROPERTY,
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
    # Memoria avanzada (Etapa 10); sin `state` todo esto queda inactivo.
    state: Optional[AgentState] = None
    turn: int = 1
    tracer: Optional[Tracer] = None  # recibe los MEMORY_UPDATE
    image_hash: Optional[str] = None
    analysis_key: Optional[str] = None  # huella del recibo analizado (o restaurado)
    confirmed_key: Optional[str] = None  # huella cuya confirmación ya se validó en esta ejecución
    # Juez (Etapa 11).
    judge: Optional[JudgeVerdict] = None  # veredicto del recibo analizado (o restaurado)
    judge_confirmed_key: Optional[str] = None  # huella cuyo PEDIR_CONFIRMACION ya se confirmó
    rejected_keys: set[str] = field(default_factory=set)  # rechazos de esta ejecución (sin `state`)


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
    """Ejecuta las tools aplicando validación y rieles. Nunca lanza excepciones.

    Saneamiento (Etapa 8): la observación que vuelve al LLM nunca incluye rutas,
    comandos, nombres de variables de entorno ni pistas internas. El detalle original
    de un fallo de servicio queda en `last_diagnostic` y el agente lo registra solo en
    la traza (enmascarado). Los resultados de las tools reales (`DriveResult`,
    `SheetResult`) conservan su `error` detallado para quien desarrolla.
    """

    def __init__(
        self,
        ctx: _RunContext,
        llm: LLMClient,
        overrides: dict[str, ToolFn],
        judge: Optional[JudgeFn] = None,
    ) -> None:
        self.ctx = ctx
        self.llm = llm
        self.overrides = overrides
        self.judge = judge  # `None` = el juez de producción (`app.judge.judge_receipt`)
        self.last_diagnostic: Optional[str] = None  # detalle oculto del último despacho

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.last_diagnostic = None
        if name not in _REQUIRED_ARGS:
            # El nombre lo eligió el modelo: no se refleja en la observación.
            self.last_diagnostic = f"herramienta desconocida: {str(name)[:60]}"
            return {"ok": False, "error": "Herramienta desconocida. No se ejecutó nada."}
        missing = [a for a in _REQUIRED_ARGS[name] if a not in args or args[a] in (None, "")]
        if missing:
            return {"ok": False, "error": f"Faltan argumentos obligatorios: {', '.join(missing)}."}
        handler = getattr(self, f"_do_{name}")
        try:
            observation = handler(args)
        except LLMCallError:
            return {"ok": False, "error": "Falló la llamada al modelo de visión; reintenta más tarde."}
        except Exception as error:  # noqa: BLE001 - solo el tipo, nunca detalles internos
            return {"ok": False, "error": f"Falló la herramienta ({type(error).__name__})."}
        # Red de seguridad final sobre cualquier observación.
        observation, leaked = sanitize_observation(name, observation)
        if leaked is not None:
            self.last_diagnostic = leaked
        return observation

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
        observation: dict[str, Any] = {
            "ok": True,
            "datos": receipt.model_dump(),
            "requiere_confirmacion": reason is not None,
            "motivo": reason,
        }
        self._identify_receipt(receipt)
        verdict = self._run_judge(receipt)
        observation["veredicto_juez"] = {
            "veredicto": verdict.veredicto, "motivo": verdict.motivo, "senales": verdict.senales,
        }
        if verdict.veredicto == RECHAZAR:
            # Los datos de un recibo rechazado no se entregan: el LLM no puede usarlos.
            observation.pop("datos")
            observation.update(
                rechazado_por_juez=not verdict.unavailable,
                requiere_confirmacion=False,
                motivo=(
                    "El control independiente no pudo verificar el recibo; no se registra nada por "
                    "ahora. Informa al usuario que lo intente de nuevo más tarde."
                    if verdict.unavailable
                    else "El control independiente rechazó este recibo: no se guarda ni se registra "
                    "y ninguna confirmación lo desbloquea. Informa al usuario que no se pudo registrar."
                ),
            )
            return observation
        if self.ctx.state is not None:
            duplicate, row = self._duplicate_info()
            if duplicate:
                where = f"en la fila {row}" if row is not None else "en esta conversación"
                notice = (
                    f"posible_duplicado: este recibo ya fue registrado {where}; "
                    "pide confirmación al usuario antes de registrarlo de nuevo"
                )
                self._ensure_pending("duplicado", row)
                observation.update(
                    posible_duplicado=True,
                    fila_existente=row,
                    requiere_confirmacion=True,
                    motivo=notice if reason is None else f"{notice}; además: {reason}",
                )
            elif reason is not None:
                self._ensure_pending("baja_confianza")
        if verdict.veredicto == PEDIR_CONFIRMACION:
            self._ensure_pending("juez")
            observation.update(
                requiere_confirmacion=True,
                motivo=f"el control independiente pide confirmación del usuario: {verdict.motivo}",
            )
        return observation

    # -- juez (Etapa 11) ------------------------------------------------------------
    def _is_rejected(self, key: Optional[str]) -> bool:
        if key is None:
            return False
        ctx = self.ctx
        if any(same_receipt(k, key) for k in ctx.rejected_keys):
            return True
        return ctx.state is not None and rejected_key(ctx.state, key) is not None

    def _run_judge(self, receipt: ReceiptData) -> JudgeVerdict:
        """Llama al juez sobre el recibo analizado y deja el veredicto en el contexto.

        Un recibo ya rechazado (misma imagen) no se vuelve a juzgar: sigue rechazado. Un rechazo
        genuino (no `juez_no_disponible`) se guarda en el estado de forma definitiva.
        """
        ctx = self.ctx
        key = ctx.analysis_key
        tracer = ctx.tracer
        if self._is_rejected(key):
            verdict = JudgeVerdict(
                veredicto=RECHAZAR,
                motivo="El recibo ya había sido rechazado por el juez.",
                senales=["rechazado_previamente"],
            )
            if tracer is not None:
                tracer.record(EventType.JUDGE_VERDICT, {
                    "veredicto": verdict.veredicto, "motivo": verdict.motivo,
                    "senales": verdict.senales, "prompt_id": judge_module.JUDGE_PROMPT_ID,
                    "model": None, "fallback": False, "reutilizado": True,
                })
            ctx.judge = verdict
            return verdict
        judge_fn = self.judge or judge_module.judge_receipt
        try:
            verdict = judge_fn(ctx.image_path, receipt, self.llm, tracer)
        except Exception as error:  # noqa: BLE001 - el juez nunca debe romper el ciclo: falla cerrada
            verdict = unavailable_verdict(f"error {type(error).__name__}")
        ctx.judge = verdict
        if verdict.veredicto == RECHAZAR and not verdict.unavailable and key is not None:
            ctx.rejected_keys.add(key)
            if ctx.state is not None:
                reject_receipt(ctx.state, key, tracer=tracer)
                pending = ctx.state.confirmacion_pendiente
                if pending is not None and same_receipt(pending.clave, key):
                    clear_pending_confirmation(
                        ctx.state, tracer=tracer, motivo="el juez rechazó el recibo"
                    )
        return verdict

    def _judge_gate(self, args: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Riel del juez. Devuelve una observación de error si hay que bloquear, o `None`.

        Va ANTES del riel de confirmación de la Etapa 10 y no depende de lo que diga el LLM.
        """
        ctx = self.ctx
        key = ctx.analysis_key
        verdict = ctx.judge
        if self._is_rejected(key) or (
            verdict is not None and verdict.veredicto == RECHAZAR and not verdict.unavailable
        ):
            return {
                "ok": False,
                "error": (
                    "rechazado_por_juez: el control independiente rechazó este recibo. No se guarda "
                    "ni se registra y ninguna confirmación lo desbloquea. Informa al usuario."
                ),
            }
        if verdict is None or verdict.unavailable:
            return {
                "ok": False,
                "error": (
                    "Registro bloqueado: el control independiente no pudo verificar este recibo. "
                    "No se registra nada por ahora; informa al usuario que lo intente más tarde."
                ),
            }
        if verdict.veredicto == APROBAR:
            return None
        # PEDIR_CONFIRMACION: solo la confirmación del usuario en un turno posterior desbloquea.
        if key is not None and ctx.judge_confirmed_key is not None and same_receipt(
            ctx.judge_confirmed_key, key
        ):
            return None
        state = ctx.state
        pending = state.confirmacion_pendiente if state is not None else None
        valid = (
            pending is not None and pending.tipo == "juez" and key is not None
            and same_receipt(pending.clave, key)
        )
        confirmed = args.get("confirmado_por_usuario") is True
        if confirmed and valid:
            assert pending is not None
            if pending.turno >= ctx.turn:
                return {
                    "ok": False,
                    "error": (
                        "Confirmación rechazada: la confirmación debe venir del usuario en un mensaje "
                        "posterior al que la pidió, no en el mismo mensaje. Responde al usuario "
                        "pidiéndola y espera su respuesta."
                    ),
                }
            ctx.judge_confirmed_key = key
            return None
        self._ensure_pending("juez")
        rejected = (
            "Confirmación rechazada: no hay una confirmación pendiente de un mensaje anterior "
            "para este recibo. "
            if confirmed
            else ""
        )
        return {
            "ok": False,
            "error": (
                f"{rejected}Registro bloqueado: el control independiente pide confirmación del "
                "usuario. Pídesela; solo en un mensaje posterior podrás reintentar con "
                "confirmado_por_usuario=true."
            ),
            "motivo": verdict.motivo,
        }

    # -- memoria avanzada (Etapa 10) ---------------------------------------------
    def _identify_receipt(self, receipt: ReceiptData) -> None:
        """Calcula el hash de la imagen y la huella del recibo analizado."""
        ctx = self.ctx
        ctx.image_hash = None
        if ctx.image_path is not None:
            try:
                ctx.image_hash = image_hash(ctx.image_path.read_bytes())
            except OSError:
                ctx.image_hash = None  # sin imagen legible la huella solo usa los campos
        ctx.analysis_key = build_key(ctx.image_hash, receipt.comercio, receipt.fecha, receipt.monto)

    def _duplicate_info(self) -> tuple[bool, Optional[int]]:
        """`(es_duplicado, fila_existente)` del recibo analizado según la memoria.

        Cuenta como duplicado un recibo ya registrado o uno que la planilla ya reportó como
        repetido (pendiente `duplicado` del mismo recibo).
        """
        state, key = self.ctx.state, self.ctx.analysis_key
        if state is None or key is None:
            return False, None
        if is_duplicate(state, key):
            return True, existing_row(state, key)
        pending = state.confirmacion_pendiente
        if pending is not None and pending.tipo == "duplicado" and same_receipt(pending.clave, key):
            return True, pending.fila_existente
        return False, None

    def _ensure_pending(self, kind: str, row: Optional[int] = None) -> None:
        """Deja (o conserva) la confirmación pendiente del recibo analizado."""
        ctx = self.ctx
        if ctx.state is None or ctx.analysis is None or ctx.analysis_key is None:
            return
        current = ctx.state.confirmacion_pendiente
        if (
            kind != "juez" and current is not None and current.tipo == "juez"
            and same_receipt(current.clave, ctx.analysis_key)
        ):
            return  # la pendiente del juez cubre también el duplicado y la confianza baja
        set_pending_confirmation(
            ctx.state,
            kind,  # type: ignore[arg-type]
            ctx.analysis_key,
            ctx.analysis.model_dump(),
            ctx.turn,
            imagen=str(ctx.image_path) if ctx.image_path is not None else None,
            imagen_id=ctx.image_id,
            imagen_hash=ctx.image_hash,
            fila_existente=row,
            juicio=ctx.judge.model_dump() if ctx.judge is not None else None,
            tracer=ctx.tracer,
        )

    def _confirmation_gate(self, tool: str, args: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Riel de confirmación. Devuelve una observación de error si hay que bloquear, o `None`.

        - Sin `state`: solo rige el riel de la Etapa 6 (confianza baja o campos desconocidos
          bloquean `registrar_gasto`).
        - Con `state`: un duplicado bloquea `guardar_recibo` y `registrar_gasto`; la confianza
          baja bloquea `registrar_gasto`. `confirmado_por_usuario=true` desbloquea solo si hay
          una confirmación pendiente del mismo recibo y tipo creada en un turno ANTERIOR.
        """
        ctx = self.ctx
        analysis = ctx.analysis
        assert analysis is not None
        reason = None if tool == "guardar_recibo" else _needs_confirmation(analysis)
        state = ctx.state
        duplicate, row = self._duplicate_info()
        if not duplicate and reason is None:
            return None
        if state is None or ctx.analysis_key is None:
            return {
                "ok": False,
                "error": (
                    f"Registro bloqueado: la extracción necesita confirmación del usuario ({reason}). "
                    "Pide al usuario que confirme o aclare los datos."
                ),
            }
        key = ctx.analysis_key
        kind = "duplicado" if duplicate else "baja_confianza"
        if ctx.confirmed_key is not None and same_receipt(ctx.confirmed_key, key):
            return None  # la confirmación ya se validó en esta ejecución
        pending = state.confirmacion_pendiente
        valid = (
            pending is not None and pending.tipo in (kind, "juez") and same_receipt(pending.clave, key)
        )  # una pendiente del juez cubre también el duplicado y la confianza baja del mismo recibo
        if args.get("confirmado_por_usuario") is True and valid:
            assert pending is not None
            if pending.turno >= ctx.turn:
                return {
                    "ok": False,
                    "error": (
                        "Confirmación rechazada: la confirmación debe venir del usuario en un mensaje "
                        "posterior al que la pidió, no en el mismo mensaje. Responde al usuario "
                        "pidiéndola y espera su respuesta."
                    ),
                }
            ctx.confirmed_key = key
            return None
        self._ensure_pending(kind, row)
        if duplicate:
            where = f"en la fila {row}" if row is not None else "en esta conversación"
            detail = f"posible_duplicado: este recibo ya fue registrado {where}"
        else:
            detail = f"la extracción necesita confirmación del usuario ({reason})"
        rejected = (
            "Confirmación rechazada: no hay una confirmación pendiente de un mensaje anterior "
            "para este recibo. "
            if args.get("confirmado_por_usuario") is True
            else ""
        )
        return {
            "ok": False,
            "error": (
                f"{rejected}Registro bloqueado: {detail}. Pide al usuario que confirme; solo en un "
                "mensaje posterior podrás reintentar con confirmado_por_usuario=true."
            ),
        }

    def _remember_expense(self, args: dict[str, Any], row_number: int) -> None:
        """Actualiza la memoria con el gasto que la planilla confirmó y borra la pendiente."""
        ctx = self.ctx
        if ctx.state is None or ctx.analysis is None:
            return
        try:
            receipt = ReceiptData(
                fecha=args["fecha"],
                comercio=args["comercio"],
                monto=float(args["monto"]),
                categoria=args["categoria"],
                confianza=ctx.analysis.confianza,
            )
            record_expense(ctx.state, receipt, ctx.image_hash, row_number, tracer=ctx.tracer)
            # Un registro exitoso cierra cualquier confirmación en espera.
            clear_pending_confirmation(
                ctx.state, tracer=ctx.tracer, motivo="el gasto se registró en la planilla"
            )
        except Exception as error:  # noqa: BLE001 - la planilla ya escribió; solo el tipo en la traza
            self.last_diagnostic = f"no se pudo actualizar la memoria ({type(error).__name__})"

    def _do_guardar_recibo(self, args: dict[str, Any]) -> dict[str, Any]:
        problem = self._image_error()
        if problem:
            return problem
        if self.ctx.analysis is None:
            return {"ok": False, "error": "Primero hay que analizar el recibo con analizar_recibo."}
        blocked = self._judge_gate(args) or self._confirmation_gate("guardar_recibo", args)
        if blocked is not None:
            return blocked
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
        if not result.success:
            observation, self.last_diagnostic = sanitize_failure(
                "guardar_recibo", result.error, file_name=None, web_view_link=None
            )
            return observation
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
        blocked = self._judge_gate(args) or self._confirmation_gate("registrar_gasto", args)
        if blocked is not None:
            return blocked
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
        # Un duplicado solo llega hasta aquí si el usuario lo confirmó (ver `_confirmation_gate`):
        # solo entonces, y solo el código, pide a la planilla omitir su deduplicación.
        if self._duplicate_info()[0]:
            kwargs["permitir_duplicado"] = True
        if "registrar_gasto" in self.overrides:
            result = self.overrides["registrar_gasto"](**kwargs)
        else:
            from app.tools.sheets import registrar_gasto

            result = registrar_gasto(**kwargs, tracer=Tracer(console=False, write_file=False))
        if result.success and result.row_number is not None:
            self.ctx.registered_row = result.row_number
            self._remember_expense(args, result.row_number)
        if not result.success and not result.duplicate:
            observation, self.last_diagnostic = sanitize_failure(
                "registrar_gasto", result.error, row_number=None, duplicate=False
            )
            return observation
        observation = {
            "ok": result.success,
            "row_number": result.row_number,
            "duplicate": result.duplicate,
            "error": result.error,
        }
        if result.duplicate and self.ctx.state is not None:
            # La planilla ya tiene la fila: no es un gasto nuevo, pero el usuario puede
            # confirmarlo en un turno posterior.
            self._ensure_pending("duplicado", result.row_number)
            observation["requiere_confirmacion"] = True
        return observation


def _restore_pending(ctx: _RunContext) -> str:
    """Restaura el análisis y la imagen de una confirmación pendiente (turno sin imagen nueva).

    Permite confirmar solo con texto: el contexto de la ejecución recupera el recibo ya analizado
    y su imagen, y se devuelve el bloque de datos `<confirmacion_pendiente>` que se agrega al
    mensaje del usuario. Devuelve "" si no hay nada que restaurar.
    """
    state = ctx.state
    pending = state.confirmacion_pendiente if state is not None else None
    if pending is None or not pending.imagen or not Path(pending.imagen).is_file():
        return ""
    try:
        analysis = ReceiptData.model_validate(pending.datos)
    except Exception:  # noqa: BLE001 - datos corruptos: no se restaura
        return ""
    ctx.image_path = Path(pending.imagen)
    ctx.image_id = pending.imagen_id or IMAGE_ID
    ctx.analysis = analysis
    ctx.analysis_key = pending.clave
    ctx.image_hash = pending.imagen_hash
    try:  # el juez NO se vuelve a ejecutar: se restaura el veredicto guardado en la pendiente
        ctx.judge = JudgeVerdict.model_validate(pending.juicio) if pending.juicio else None
    except Exception:  # noqa: BLE001 - veredicto corrupto: sin veredicto el riel bloquea
        ctx.judge = None
    info: dict[str, Any] = {
        "tipo": pending.tipo,
        "fila_existente": pending.fila_existente,
        "datos": pending.datos,
        "image_id": ctx.image_id,
    }
    if ctx.judge is not None:
        info["veredicto_juez"] = {
            "veredicto": ctx.judge.veredicto, "motivo": ctx.judge.motivo, "senales": ctx.judge.senales,
        }
    block = json.dumps(info, ensure_ascii=False)
    block = block.replace("<", "‹").replace(">", "›")  # los datos no pueden cerrar la etiqueta
    return (
        f"\n[Sistema: el mensaje anterior pidió confirmar el registro de un recibo ya analizado "
        f"(image_id={ctx.image_id}). Si el usuario lo confirma en este mensaje, usa "
        f"confirmado_por_usuario=true; no vuelvas a llamar analizar_recibo.]\n"
        f"<confirmacion_pendiente>{block}</confirmacion_pendiente>"
    )


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
        judge: Optional[JudgeFn] = None,
    ) -> None:
        self.llm = llm
        self.tracer = tracer
        self.tool_overrides = dict(tool_overrides or {})
        self.max_steps = max_steps
        # Solo código del programador puede reemplazar al juez (pruebas); `None` = el de producción.
        self.judge = judge

    def run(
        self,
        user_text: str,
        image_path: Optional[str | Path] = None,
        tracer: Optional[Tracer] = None,
        llm: Optional[LLMClient] = None,
        tool_overrides: Optional[dict[str, ToolFn]] = None,
        conversation: Optional[Conversation] = None,
        state: Optional[AgentState] = None,
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
            state: memoria avanzada (Etapa 10). Si se entrega, el código la actualiza tras
                cada registro, frena los duplicados y exige la confirmación del usuario en un
                turno posterior (ver el docstring del módulo). Sin él, no hay memoria.
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
        ctx = _RunContext(image_path=path, image_id=image_id, state=state, turn=turn, tracer=tracer)
        pending_note = _restore_pending(ctx) if path is None else ""
        dispatcher = _Dispatcher(ctx, llm, overrides, self.judge)
        tools = build_tool_declarations()

        tracer.record(
            EventType.USER_INPUT,
            {"text": user_text, "has_image": path is not None,
             "image_id": image_id if path is not None else None,
             "turn": turn, "history_messages": len(prior),
             **({"restored_pending": state.confirmacion_pendiente.tipo} if pending_note else {})},
        )
        text = user_text
        if path is not None:
            text += f"\n[Adjunto: imagen de un recibo, image_id={image_id}]"
        text += pending_note
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
                     "agent_step": steps,
                     **({"diagnostic": dispatcher.last_diagnostic}
                        if dispatcher.last_diagnostic else {})},
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
