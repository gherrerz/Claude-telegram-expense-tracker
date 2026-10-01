"""Ciclo de memoria avanzada de la Etapa 10, compartido por el script, la prueba live y el notebook.

`run_memory_cycle` ejecuta cinco pasos reales a través de `ExpenseAssistant`, con UNA
`Conversation` y UN `AgentState`, y evalúa cada paso por condiciones (no por texto exacto):

  1. "Me llamo Ana"                       -> CONVERSACION; `nombre_usuario` en el estado (MEMORY_UPDATE).
  2. imagen + "Registra este recibo"      -> REGISTRAR_RECIBO; totales y recibos registrados (MEMORY_UPDATE).
  3. "¿Cuánto llevo gastado en <cat>?"    -> CONSULTAR_GASTOS; la respuesta contiene el total del estado.
  4. la misma imagen + "Registra ..."     -> posible duplicado: 0 ejecuciones de guardar/registrar,
                                             confirmación pendiente y pregunta al usuario.
  5. "Sí, regístralo de todas formas"     -> turno posterior: se registra con `permitir_duplicado`,
                                             los totales se duplican y la pendiente se borra.

Las ejecuciones REALES de `guardar_recibo` y `registrar_gasto` se cuentan con envoltorios
(`counting_tools`), no con los eventos TOOL_CALL del agente (que también registran las llamadas que un
riel bloquea).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.assistant import AssistantResult, ExpenseAssistant
from app.conversation import Conversation
from app.memory import state_snapshot
from app.models import AgentState, EventType
from app.router import CONSULTAR_GASTOS, CONVERSACION, REGISTRAR_RECIBO
from app.trace import Tracer

_CONFIRMATION_RE = re.compile(
    r"confirm|de todas formas|de nuevo|otra vez|ya (fue|est[aá]|se)\b.{0,40}registrad|duplicad",
    re.IGNORECASE,
)

QUESTION_TEMPLATE = "¿Cuánto llevo gastado en {categoria}?"
CONFIRM_TEXT = "Sí, regístralo de todas formas"


@dataclass
class StepReport:
    """Un paso del ciclo con su evidencia."""

    id: str
    name: str
    text: str
    with_image: bool
    result: AssistantResult
    route_event: dict[str, Any]
    tool_runs: dict[str, int]  # ejecuciones reales de guardar/registrar en este paso
    memory_events: list[dict[str, Any]]
    state: dict[str, Any]  # `state_snapshot` al terminar el paso
    checks: dict[str, bool]
    sheet_rows: Optional[int] = None

    @property
    def ok(self) -> bool:
        return all(self.checks.values())


@dataclass
class CycleReport:
    """Resultado de todo el ciclo."""

    initial_state: dict[str, Any]
    steps: list[StepReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.steps) == 5 and all(step.ok for step in self.steps)


def counting_tools(
    guardar: Callable[..., Any],
    registrar: Callable[..., Any],
    extra: Optional[dict[str, Callable[..., Any]]] = None,
) -> tuple[dict[str, Callable[..., Any]], dict[str, int]]:
    """Envuelve guardar y registrar para contar sus ejecuciones reales.

    Returns:
        `(tool_overrides, contadores)`; los contadores solo suben cuando la tool se ejecuta
        (un riel que la bloquea antes del despacho no la cuenta).
    """
    counts = {"guardar_recibo": 0, "registrar_gasto": 0}

    def counted_guardar(*args: Any, **kwargs: Any) -> Any:
        counts["guardar_recibo"] += 1
        return guardar(*args, **kwargs)

    def counted_registrar(*args: Any, **kwargs: Any) -> Any:
        counts["registrar_gasto"] += 1
        return registrar(*args, **kwargs)

    overrides = {"guardar_recibo": counted_guardar, "registrar_gasto": counted_registrar, **(extra or {})}
    return overrides, counts


def live_tools() -> tuple[dict[str, Callable[..., Any]], dict[str, int]]:
    """Las tools reales de Drive y Sheets (solo guardar y registrar), con contadores."""
    from app.tools.drive import guardar_recibo
    from app.tools.sheets import registrar_gasto

    def silent() -> Tracer:
        return Tracer(console=False, write_file=False)

    return counting_tools(
        lambda path, comercio, fecha: guardar_recibo(path, comercio, fecha, tracer=silent()),
        lambda **kwargs: registrar_gasto(**kwargs, tracer=silent()),
    )


def _events(tracer: Tracer, start: int, kind: EventType) -> list[dict[str, Any]]:
    return [e.data for e in tracer.events[start:] if e.event_type == kind]


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def run_memory_cycle(
    assistant: ExpenseAssistant,
    counts: dict[str, int],
    image_path: str | Path,
    expected_total: float,
    tracer: Tracer,
    conversation: Optional[Conversation] = None,
    state: Optional[AgentState] = None,
    row_count: Optional[Callable[[], int]] = None,
    on_step: Optional[Callable[[StepReport], None]] = None,
) -> CycleReport:
    """Ejecuta los cinco pasos y evalúa cada uno. `counts` viene de `counting_tools`.

    Args:
        assistant: asistente construido con las tools contadas (`tool_overrides`).
        image_path: recibo único del ciclo (se envía en los pasos 2 y 4).
        expected_total: monto del recibo, para comprobar que lo registrado coincide.
        row_count: función que devuelve las filas de datos de la planilla (opcional).
        on_step: se llama con el `StepReport` al terminar cada paso (por ejemplo, para imprimir).
    """
    conversation = conversation if conversation is not None else Conversation()
    state = state if state is not None else AgentState()
    report = CycleReport(initial_state=state_snapshot(state))
    prev_rows = row_count() if row_count is not None else None
    category: dict[str, str] = {}

    def step(
        step_id: str, name: str, text: str, with_image: bool,
        check: Callable[[StepReport, dict[str, Any], dict[str, Any]], dict[str, bool]],
    ) -> None:
        nonlocal prev_rows
        before = state_snapshot(state)
        runs_before = dict(counts)
        start = len(tracer.events)
        result = assistant.handle(
            text, image_path if with_image else None, conversation=conversation, state=state,
            tracer=tracer,
        )
        route_events = _events(tracer, start, EventType.ROUTE)
        rows = row_count() if row_count is not None else None
        entry = StepReport(
            id=step_id, name=name, text=text, with_image=with_image, result=result,
            route_event=route_events[0] if route_events else {},
            tool_runs={k: counts[k] - runs_before[k] for k in counts},
            memory_events=_events(tracer, start, EventType.MEMORY_UPDATE),
            state=state_snapshot(state), checks={}, sheet_rows=rows,
        )
        entry.checks = check(entry, before, {"rows_before": prev_rows, "rows_after": rows})
        prev_rows = rows
        report.steps.append(entry)
        if on_step is not None:
            on_step(entry)

    def ops(entry: StepReport) -> list[str]:
        return [e["operacion"] for e in entry.memory_events]

    def common(entry: StepReport, route: str, runs: tuple[int, int]) -> dict[str, bool]:
        return {
            f"ruta {route}": entry.result.route == route and not entry.route_event.get("fallback"),
            f"guardar_recibo ejecutada {runs[0]} vez/veces": entry.tool_runs["guardar_recibo"] == runs[0],
            f"registrar_gasto ejecutada {runs[1]} vez/veces": entry.tool_runs["registrar_gasto"] == runs[1],
        }

    # 1) nombre
    def check_name(e: StepReport, before: dict[str, Any], _rows: dict[str, Any]) -> dict[str, bool]:
        return {
            **common(e, CONVERSACION, (0, 0)),
            "nombre_usuario guardado en el estado": (e.state["nombre_usuario"] or "").casefold() == "ana",
            "MEMORY_UPDATE set_user_name": "set_user_name" in ops(e),
        }

    step("1", "nombre", "Me llamo Ana", False, check_name)

    # 2) registrar el recibo
    def check_register(e: StepReport, before: dict[str, Any], r: dict[str, Any]) -> dict[str, bool]:
        totals = e.state["totales_por_categoria"]
        if totals:
            category["name"] = next(iter(totals))
        checks = {
            **common(e, REGISTRAR_RECIBO, (1, 1)),
            "parada respuesta_final": e.result.stop_reason == "respuesta_final",
            "MEMORY_UPDATE record_expense": "record_expense" in ops(e),
            "un recibo registrado en el estado": len(e.state["recibos_registrados"]) == 1,
            "el total registrado coincide con el recibo": abs(e.state["total_general"] - expected_total) < 0.5,
        }
        if r["rows_before"] is not None and r["rows_after"] is not None:
            checks["la planilla tiene 1 fila más"] = r["rows_after"] == r["rows_before"] + 1
        return checks

    step("2", "registrar recibo", "Registra este recibo", True, check_register)

    # 3) consulta desde el estado
    def check_query(e: StepReport, before: dict[str, Any], _rows: dict[str, Any]) -> dict[str, bool]:
        total = int(round(before["total_general"]))
        return {
            **common(e, CONSULTAR_GASTOS, (0, 0)),
            "cero eventos TOOL_CALL": not e.result.tool_calls,
            "el estado no cambió": e.state == before,
            "la respuesta contiene el total del estado": str(total) in _digits(e.result.final_text),
        }

    question = QUESTION_TEMPLATE.format(categoria=category.get("name") or "Supermercado")
    step("3", "consulta desde el estado", question, False, check_query)

    # 4) mismo recibo: duplicado
    def check_duplicate(e: StepReport, before: dict[str, Any], r: dict[str, Any]) -> dict[str, bool]:
        pending = e.state["confirmacion_pendiente"]
        checks = {
            **common(e, REGISTRAR_RECIBO, (0, 0)),
            "confirmación pendiente de tipo duplicado": bool(pending) and pending["tipo"] == "duplicado",
            "MEMORY_UPDATE set_pending_confirmation": "set_pending_confirmation" in ops(e),
            "los totales no cambiaron": e.state["totales_por_categoria"] == before["totales_por_categoria"],
            "la respuesta pide confirmación": bool(_CONFIRMATION_RE.search(e.result.final_text)),
        }
        if r["rows_before"] is not None and r["rows_after"] is not None:
            checks["la planilla no cambió"] = r["rows_after"] == r["rows_before"]
        return checks

    step("4", "mismo recibo (duplicado)", "Registra este recibo", True, check_duplicate)

    # 5) confirmación en el turno posterior
    def check_confirm(e: StepReport, before: dict[str, Any], r: dict[str, Any]) -> dict[str, bool]:
        checks = {
            **common(e, REGISTRAR_RECIBO, (1, 1)),
            "MEMORY_UPDATE record_expense": "record_expense" in ops(e),
            "los totales se duplicaron": abs(e.state["total_general"] - 2 * expected_total) < 1.0,
            "confirmación pendiente borrada": e.state["confirmacion_pendiente"] is None,
            "dos gastos recientes": len(e.state["ultimos_gastos"]) == 2,
        }
        if r["rows_before"] is not None and r["rows_after"] is not None:
            checks["la planilla tiene 1 fila más"] = r["rows_after"] == r["rows_before"] + 1
        return checks

    step("5", "confirmación del usuario", CONFIRM_TEXT, False, check_confirm)
    return report
