"""Arnés de evaluación del golden set (Etapa 12): ejecuta cada caso contra el sistema real.

Qué hace
- Carga `eval/golden_set_vN.json` (se valida antes de gastar una sola llamada) y ejecuta cada caso con
  una `Conversation` y un `AgentState` NUEVOS, a través de `ExpenseAssistant` con el juez de producción.
- Los casos con `google: true` usan las tools REALES de Drive y Sheets (carpeta y planilla de prueba) y
  miden las filas de la planilla antes y después de cada turno (solo lectura). Los demás usan las mismas
  tools reales con la configuración de Google en blanco (degradación controlada, decisión A12): devuelven
  su error estructurado `servicio_no_disponible`; nunca se finge un éxito de Drive o Sheets.
- Los recibos sintéticos únicos se generan en una carpeta temporal con un sufijo de corrida en el
  comercio, para que una corrida nueva no choque con la deduplicación de la planilla.
- Cada criterio se evalúa por condición (`eval/criteria.py`); un caso solo es APROBADO si TODOS sus
  criterios se cumplen. La evidencia por caso (rutas, tools, veredictos, respuesta, llamadas LLM, tokens,
  duración y traza `traces/eval_<versión>_<caso>.jsonl`) queda en `eval/results_<versión>.json`.

Etiquetas de versión (no se confunden)
- La versión del GOLDEN SET (`version` del JSON, hoy v1) solo cambia si se AGREGAN casos; nunca se
  quitan ni se editan para que pasen.
- La versión del SISTEMA (`--system-version`) etiqueta el código bajo prueba: `results_v1.json` es la
  primera corrida; cada corrección del sistema por un fallo genera `results_v2.json`, etc.

Estados por caso: APROBADO, FALLIDO, ERROR (excepción del arnés), PENDIENTE (no hubo veredicto: cuota
agotada o API caída, falta de configuración de Google, o no se ejecutó) y OMITIDO (`--no-google`).

Interrupción. Si un caso agota la cuota (429 / RESOURCE_EXHAUSTED tras los reintentos) o la API no responde
(503 / UNAVAILABLE), el caso queda PENDIENTE (no FALLIDO), la corrida se detiene y se escribe el archivo con
`interrumpida: true`. `--resume` ejecuta SOLO los casos PENDIENTE u OMITIDO y los que nunca corrieron; un
FALLIDO o ERROR registrado se conserva tal cual (reejecutarlo en la misma versión ocultaría el fallo).
La corrida solo cuenta como aprobada si todos los casos están APROBADO y no quedó interrumpida.

Códigos de salida: 0 todo aprobado; 1 hay casos FALLIDO o ERROR; 2 falta configuración (Gemini) o la
entrada es inválida; 3 corrida incompleta (interrumpida, o con casos PENDIENTE u OMITIDO).

Uso:
    .venv\\Scripts\\python eval\\run_eval.py --system-version v1 --out eval\\results_v1.json
    .venv\\Scripts\\python eval\\run_eval.py --system-version v1 --out eval\\results_v1.json --resume
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.assistant import ExpenseAssistant  # noqa: E402
from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.conversation import Conversation  # noqa: E402
from app.llm import RETRYABLE_CODES, RETRYABLE_STATUSES, LLMCallError, LLMClient  # noqa: E402
from app.memory import state_snapshot  # noqa: E402
from app.models import AgentState, EventType  # noqa: E402
from app.prompts import SECURITY_SCOPE_ID  # noqa: E402
from app.trace import Tracer, mask_value  # noqa: E402
from eval.criteria import evaluate_case, validate_golden_set  # noqa: E402

DEFAULT_GOLDEN = ROOT / "eval" / "golden_set_v1.json"
TRACE_DIR = ROOT / "traces"
EXPECTED_JSON = ROOT / "data" / "receipts" / "expected.json"

APROBADO = "APROBADO"
FALLIDO = "FALLIDO"
ERROR = "ERROR"
PENDIENTE = "PENDIENTE"
OMITIDO = "OMITIDO"
FINAL_STATES = (APROBADO, FALLIDO, ERROR)  # con veredicto: `--resume` no los reejecuta

EXIT_PASS, EXIT_FAIL, EXIT_CONFIG, EXIT_INCOMPLETE = 0, 1, 2, 3

TOOL_NAMES = ("analizar_recibo", "guardar_recibo", "registrar_gasto")
GOOGLE_VARIABLES = (
    "GOOGLE_OAUTH_CLIENT_SECRETS", "GOOGLE_OAUTH_TOKEN", "DRIVE_FOLDER_ID", "SHEET_ID",
)
MAX_TEXT = 600  # caracteres de la respuesta que se guardan por turno


@contextmanager
def google_blanked():
    """Degradación controlada (decisión A12): sin configuración de Google las tools reales devuelven su
    error estructurado `servicio_no_disponible`. Las variables quedan definidas pero vacías (así dotenv no
    las rellena desde `.env`) y se restauran al salir. Nunca se finge un éxito de Drive o Sheets."""
    saved = {name: os.environ.get(name) for name in GOOGLE_VARIABLES}
    for name in GOOGLE_VARIABLES:
        os.environ[name] = ""
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _silent() -> Tracer:
    return Tracer(console=False, write_file=False)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# -- Tools con contadores -----------------------------------------------------------------------
class ToolProbe:
    """Envoltorios de las tools REALES: cuentan las ejecuciones y recogen la evidencia.

    Con `real=True` Drive y Sheets usan la configuración de Google. Con `real=False` (casos sin Google)
    las mismas tools reales corren con la configuración de Google en blanco (`google_blanked`) y devuelven
    su error estructurado; no existe ningún modo simulado. El conteo sube solo cuando el despacho llega a
    la tool (un riel que la bloquea antes no la cuenta).
    """

    def __init__(self, real: bool, llm: Any) -> None:
        self.real = real
        self.llm = llm
        self.counts: dict[str, int] = {name: 0 for name in TOOL_NAMES}
        self.extractions: list[dict[str, Any]] = []
        self.rows: list[int] = []
        self.drive_links: list[str] = []

    def overrides(self) -> dict[str, Callable[..., Any]]:
        return {
            "analizar_recibo": self._analizar,
            "guardar_recibo": self._guardar,
            "registrar_gasto": self._registrar,
        }

    def _analizar(self, path: Any) -> Any:
        self.counts["analizar_recibo"] += 1
        from app.tools.analyzer import analizar_recibo

        receipt = analizar_recibo(path, llm=self.llm, tracer=_silent())
        self.extractions.append(receipt.model_dump())
        return receipt

    def _guardar(self, path: Any, comercio: Any, fecha: Any) -> Any:
        self.counts["guardar_recibo"] += 1
        from app.tools.drive import guardar_recibo

        with nullcontext() if self.real else google_blanked():
            result = guardar_recibo(path, comercio, fecha, tracer=_silent())
        if getattr(result, "success", False) and getattr(result, "web_view_link", None):
            self.drive_links.append(result.web_view_link)
        return result

    def _registrar(self, **kwargs: Any) -> Any:
        self.counts["registrar_gasto"] += 1
        from app.tools.sheets import registrar_gasto

        with nullcontext() if self.real else google_blanked():
            result = registrar_gasto(**kwargs, tracer=_silent())
        if getattr(result, "success", False) and getattr(result, "row_number", None) is not None:
            self.rows.append(int(result.row_number))
        return result


# -- Contexto de una corrida -----------------------------------------------------------------------
@dataclass
class RunContext:
    llm: Any  # `LLMClient` (o un doble con `.stats`)
    system_version: str
    run_id: str  # sufijo numérico único de la corrida (HHMMSS)
    tmp_dir: Path
    trace_dir: Path = TRACE_DIR
    root: Path = ROOT
    google_ready: bool = False
    google_reason: str = ""
    sheet_rows: Optional[Callable[[], int]] = None
    assistant_factory: Optional[Callable[[dict[str, Callable[..., Any]], Tracer], Any]] = None
    now: Callable[[], datetime] = datetime.now
    expected_json: dict[str, Any] = field(default_factory=dict)

    def make_assistant(self, overrides: dict[str, Callable[..., Any]], tracer: Tracer) -> Any:
        if self.assistant_factory is not None:
            return self.assistant_factory(overrides, tracer)
        return ExpenseAssistant(llm=self.llm, tracer=tracer, tool_overrides=overrides)


# -- Recibos y entradas ---------------------------------------------------------------------------
def case_number(case_id: str) -> int:
    match = re.match(r"GS(\d+)", case_id)
    return int(match.group(1)) if match else 0


def generate_receipt(
    recipe: dict[str, Any], case_id: str, turn: int, run_id: str, out_dir: Path, now: datetime
) -> tuple[Path, dict[str, Any]]:
    """Genera el recibo sintético único de una receta del golden set.

    El comercio es `<comercio_base> <HHMMSS>-<n>` y el monto `monto_base + k * 10` con `k` derivada de la
    corrida y del número del caso, de modo que cada corrida y cada caso escriben una fila distinta.
    """
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from generate_receipts import make_unique

    number = case_number(case_id)
    merchant = f"{recipe['comercio_base']} {run_id}-{number}"
    amount = int(recipe.get("monto_base", 15000)) + ((int(run_id) + number * 137) % 9000) * 10
    date = now.strftime("%Y-%m-%d") if recipe.get("fecha", "hoy") == "hoy" else str(recipe["fecha"])
    category = str(recipe.get("categoria_hint", "Supermercado"))
    image, expected = make_unique(
        merchant, date, amount, category, f"Sucursal Prueba - Boleta N {run_id}-{number}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{case_id}_turno{turn}.jpg"
    image.save(path, format="JPEG", quality=80)
    return path, expected


def _resolve_image(
    spec: Any, case_id: str, turn: int, ctx: RunContext, images: dict[int, Path],
    evidence: dict[str, Any],
) -> Optional[Path]:
    if spec is None:
        return None
    if "archivo" in spec:
        path = ctx.root / spec["archivo"]
        if not path.is_file():
            raise FileNotFoundError(f"falta la imagen {spec['archivo']}")
        images[turn] = path
        return path
    if "generado" in spec:
        path, expected = generate_receipt(
            spec["generado"], case_id, turn, ctx.run_id, ctx.tmp_dir, ctx.now()
        )
        images[turn] = path
        evidence["generado"] = {k: expected[k] for k in ("fecha", "comercio", "monto", "categoria")}
        return path
    images[turn] = images[spec["igual_turno"]]
    return images[turn]


def _image_label(spec: Any) -> Optional[str]:
    if spec is None:
        return None
    if "archivo" in spec:
        return spec["archivo"]
    if "generado" in spec:
        return "generado"
    return f"igual al turno {spec['igual_turno']}"


# -- Fallas de la API -------------------------------------------------------------------------------
def classify_api_failure(code: Any, status: Any) -> Optional[dict[str, Any]]:
    """Interrupción por cuota (429) o API caída (503) tras agotar los reintentos; otro error, `None`."""
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return {"motivo": "cuota_agotada", "codigo": code, "estado": status}
    if code in RETRYABLE_CODES or status in RETRYABLE_STATUSES:
        return {"motivo": "api_no_disponible", "codigo": code, "estado": status}
    return None


def api_failure(events: list[Any]) -> Optional[dict[str, Any]]:
    """Primera llamada al LLM que falló por cuota o disponibilidad en estos eventos.

    El asistente captura `LLMCallError` y responde con un texto seguro, así que la señal fiable es el
    `LLM_DECISION` con `status="error"` que deja el cliente tras agotar los reintentos.
    """
    found: list[dict[str, Any]] = []
    for event in events:
        if event.event_type == EventType.LLM_DECISION and event.data.get("status") == "error":
            failure = classify_api_failure(event.data.get("error_code"), event.data.get("error_status"))
            if failure:
                found.append(failure)
    quota = [f for f in found if f["motivo"] == "cuota_agotada"]
    return (quota or found or [None])[0]


# -- Ejecución de un caso -------------------------------------------------------------------------------
def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _definition_hash(case: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _play_case(case: dict[str, Any], ctx: RunContext, tracer: Tracer, evidence: dict[str, Any],
               probe: ToolProbe) -> Optional[dict[str, Any]]:
    """Ejecuta los turnos del caso y va llenando `evidence`. Devuelve la interrupción, si la hubo."""
    assistant = ctx.make_assistant(probe.overrides(), tracer)
    conversation, state = Conversation(), AgentState()
    images: dict[int, Path] = {}
    measure = bool(case["google"]) and ctx.sheet_rows is not None
    rows_before = ctx.sheet_rows() if measure and ctx.sheet_rows else None
    for index, turn in enumerate(case["entrada"], start=1):
        image = _resolve_image(turn.get("imagen"), case["id"], index, ctx, images, evidence)
        start = len(tracer.events)
        counts_before = dict(probe.counts)
        extractions_before, rows_registered_before = len(probe.extractions), len(probe.rows)
        result = assistant.handle(
            turn["texto"], image, conversation=conversation, state=state, tracer=tracer
        )
        events = tracer.events[start:]
        rows_after = ctx.sheet_rows() if measure and ctx.sheet_rows else None
        route_events = [e.data for e in events if e.event_type == EventType.ROUTE]
        evidence["turnos"].append({
            "indice": index,
            "texto": turn["texto"],
            "imagen": _image_label(turn.get("imagen")),
            "ruta": result.route,
            "respaldo": bool(route_events[0].get("fallback")) if route_events else False,
            "respuesta": result.final_text,
            "stop": result.stop_reason,
            "tools_llamadas": [e.data.get("tool") for e in events if e.event_type == EventType.TOOL_CALL],
            "tools_ejecutadas": {k: probe.counts[k] - counts_before[k] for k in probe.counts},
            "veredictos": [e.data for e in events if e.event_type == EventType.JUDGE_VERDICT],
            "extracciones": probe.extractions[extractions_before:],
            "estado": state_snapshot(state),
            "filas_antes": rows_before,
            "filas_despues": rows_after,
            "filas_registradas": probe.rows[rows_registered_before:],
            "llamadas_llm": sum(1 for e in events if e.event_type == EventType.LLM_DECISION),
            "alcances": sorted({
                e.data.get("security_scope_id") for e in events
                if e.event_type == EventType.LLM_DECISION and e.data.get("security_scope_id")
            }),
        })
        rows_before = rows_after
        failure = api_failure(events)
        if failure:
            return failure
    return None


def _turn_summary(turn: dict[str, Any]) -> dict[str, Any]:
    verdicts = turn.get("veredictos") or []
    state = turn.get("estado") or {}
    return {
        "indice": turn["indice"],
        "texto": turn["texto"],
        "imagen": turn.get("imagen"),
        "ruta": turn["ruta"],
        "respaldo_del_router": turn["respaldo"],
        "stop": turn["stop"],
        "tools_llamadas": turn["tools_llamadas"],
        "tools_ejecutadas": turn["tools_ejecutadas"],
        "veredicto_juez": verdicts[-1].get("veredicto") if verdicts else None,
        "filas_antes": turn.get("filas_antes"),
        "filas_despues": turn.get("filas_despues"),
        "llamadas_llm": turn["llamadas_llm"],
        "estado_memoria": {
            "nombre_usuario": state.get("nombre_usuario"),
            "totales_por_categoria": state.get("totales_por_categoria"),
            "confirmacion_pendiente": (state.get("confirmacion_pendiente") or {}).get("tipo"),
        },
        "respuesta": _clip(turn["respuesta"]),
    }


def _empty_result(case: dict[str, Any], estado: str, motivo: Optional[str]) -> dict[str, Any]:
    return {
        "id": case["id"],
        "nombre": case["nombre"],
        "categoria": case["categoria"],
        "google": case["google"],
        "estado": estado,
        "motivo": motivo,
        "definicion_sha256": _definition_hash(case),
        "criterios": [],
        "rutas": [],
        "tools_llamadas": [],
        "tools_ejecutadas": {name: 0 for name in TOOL_NAMES},
        "veredicto_juez": None,
        "respuesta_final": "",
        "llamadas_llm": 0,
        "reintentos": 0,
        "tokens": {"entrada": 0, "salida": 0, "razonamiento": 0, "total": 0},
        "duracion_s": 0.0,
        "traza": None,
        "turnos": [],
    }


def run_case(case: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Ejecuta un caso y devuelve su resultado (estado, criterios y evidencia)."""
    started = time.monotonic()
    stats_before = dict(ctx.llm.stats.as_dict())
    session = f"eval_{ctx.system_version}_{case['id']}"
    tracer = Tracer(session=session, trace_dir=ctx.trace_dir, console=False)
    real = bool(case["google"]) and ctx.google_ready
    probe = ToolProbe(real, ctx.llm)
    evidence: dict[str, Any] = {
        "turnos": [], "generado": None, "expected_json": ctx.expected_json,
        "alcance_esperado": SECURITY_SCOPE_ID,
    }
    result = _empty_result(case, ERROR, None)
    result["herramientas"] = "reales" if real else "reales_sin_google"
    interruption: Optional[dict[str, Any]] = None
    crashed: Optional[str] = None
    try:
        interruption = _play_case(case, ctx, tracer, evidence, probe)
    except LLMCallError as error:
        interruption = classify_api_failure(error.code, error.status)
        if interruption is None:
            crashed = f"LLMCallError (codigo={error.code}, estado={error.status})"
    except KeyboardInterrupt:
        interruption = {"motivo": "interrumpida_por_el_usuario", "codigo": None, "estado": None}
    except Exception as error:  # noqa: BLE001 - un fallo del arnés se registra como ERROR del caso
        crashed = f"{type(error).__name__}: {str(error)[:200]}"

    stats_after = ctx.llm.stats.as_dict()
    delta = {k: stats_after.get(k, 0) - stats_before.get(k, 0) for k in stats_after}
    turns = evidence["turnos"]
    result.update({
        "rutas": [t["ruta"] for t in turns],
        "tools_llamadas": [name for t in turns for name in t["tools_llamadas"]],
        "tools_ejecutadas": dict(probe.counts),
        "veredicto_juez": next(
            (t["veredictos"][-1].get("veredicto") for t in reversed(turns) if t["veredictos"]), None
        ),
        "respuesta_final": _clip(turns[-1]["respuesta"]) if turns else "",
        "llamadas_llm": delta.get("calls", 0),
        "reintentos": delta.get("retries", 0),
        "tokens": {
            "entrada": delta.get("prompt_tokens", 0), "salida": delta.get("output_tokens", 0),
            "razonamiento": delta.get("thinking_tokens", 0), "total": delta.get("total_tokens", 0),
        },
        "duracion_s": round(time.monotonic() - started, 1),
        "traza": f"traces/{session}.jsonl",
        "turnos": [_turn_summary(t) for t in turns],
    })
    if evidence["generado"]:
        result["recibo_generado"] = evidence["generado"]
    if interruption is not None:
        result["estado"] = PENDIENTE
        result["motivo"] = f"interrumpida: {interruption['motivo']}"
        result["interrupcion"] = interruption
    elif crashed is not None:
        result["estado"] = ERROR
        result["motivo"] = crashed
    else:
        criteria = evaluate_case(case, evidence)
        result["criterios"] = criteria
        passed = bool(criteria) and len(criteria) == len(case["criterio"]) and all(c["ok"] for c in criteria)
        result["estado"] = APROBADO if passed else FALLIDO
    return result


# -- Corrida completa ---------------------------------------------------------------------------------
def plan_cases(golden: dict[str, Any], prior: dict[str, dict[str, Any]],
               only: Optional[set[str]]) -> list[dict[str, Any]]:
    """Casos que esta invocación debe ejecutar: los pendientes (u omitidos o nunca corridos) y elegidos."""
    return [
        case for case in golden["casos"]
        if prior.get(case["id"], {}).get("estado") not in FINAL_STATES
        and (only is None or case["id"].upper() in only)
    ]


def golden_sha256(golden: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(golden, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def summarize(doc: dict[str, Any]) -> dict[str, Any]:
    """Resumen del documento de resultados (totales, tasa, llamadas, interrupción, aprobada)."""
    cases = doc["casos"]
    totals = {state: sum(1 for c in cases if c["estado"] == state)
              for state in (APROBADO, FALLIDO, ERROR, PENDIENTE, OMITIDO)}
    runs = doc.get("ejecuciones") or []
    last = runs[-1] if runs else {}
    interrupted = bool(last.get("interrumpida"))
    return {
        "casos": len(cases),
        **totals,
        "tasa_aprobacion": round(totals[APROBADO] / len(cases), 4) if cases else 0.0,
        "llamadas_llm_total": sum(int(r.get("llamadas_llm", 0)) for r in runs),
        "tokens_total": sum(int(r.get("tokens", 0)) for r in runs),
        "interrumpida": interrupted,
        "motivo_interrupcion": last.get("motivo_interrupcion") if interrupted else None,
        "aprobada": bool(cases) and totals[APROBADO] == len(cases) and not interrupted,
    }


def exit_code(doc: dict[str, Any]) -> int:
    """0 todo aprobado; 3 interrumpida; 1 con FALLIDO o ERROR; 3 si quedan PENDIENTE u OMITIDO."""
    summary = doc["resumen"]
    if summary["interrumpida"]:
        return EXIT_INCOMPLETE
    if summary[FALLIDO] or summary[ERROR]:
        return EXIT_FAIL
    if summary[PENDIENTE] or summary[OMITIDO]:
        return EXIT_INCOMPLETE
    return EXIT_PASS if summary["aprobada"] else EXIT_FAIL


def execute_run(
    golden: dict[str, Any],
    ctx: RunContext,
    *,
    existing: Optional[dict[str, Any]] = None,
    only: Optional[set[str]] = None,
    resume: bool = False,
    no_google: bool = False,
    save: Optional[Callable[[dict[str, Any]], None]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Ejecuta los casos pendientes y devuelve el documento de resultados completo.

    `existing` solo se usa con `resume`: sus casos con veredicto (APROBADO, FALLIDO, ERROR) se conservan
    sin reejecutarse; los PENDIENTE u OMITIDO y los que nunca corrieron se ejecutan.
    """
    say = progress or (lambda _text: None)
    cases = golden["casos"]
    prior = {c["id"]: c for c in (existing or {}).get("casos", [])} if resume and existing else {}
    results: dict[str, dict[str, Any]] = {
        c["id"]: prior.get(c["id"]) or _empty_result(c, PENDIENTE, "no_ejecutado")
        for c in cases
    }
    run: dict[str, Any] = {
        "inicio": _now_iso(), "fin": None, "reanudada": bool(prior), "run_id": ctx.run_id,
        "casos_ejecutados": [], "llamadas_llm": 0, "tokens": 0,
        "interrumpida": False, "motivo_interrupcion": None,
    }
    history = [*(existing or {}).get("ejecuciones", [])] if resume and existing else []
    doc: dict[str, Any] = {
        "version_golden": golden["version"],
        "version_sistema": ctx.system_version,
        "golden_sha256": golden_sha256(golden),
        "modelo": getattr(ctx.llm, "model", None),
        "bloque_de_alcance": SECURITY_SCOPE_ID,
        "ejecuciones": [*history, run],
    }

    def snapshot() -> dict[str, Any]:
        doc["casos"] = [results[c["id"]] for c in cases]
        doc["resumen"] = summarize(doc)
        return doc

    for case in plan_cases(golden, prior, only):
        cid = case["id"]
        if run["interrumpida"]:
            break
        if case["google"] and no_google:
            results[cid] = _empty_result(case, OMITIDO, "omitido por --no-google")
            say(f"[{cid}] OMITIDO (--no-google)")
        elif case["google"] and not ctx.google_ready:
            results[cid] = _empty_result(case, PENDIENTE, f"falta configuración de Google: {ctx.google_reason}")
            say(f"[{cid}] PENDIENTE (falta configuración de Google)")
        else:
            say(f"[{cid}] ejecutando: {case['nombre']}")
            result = run_case(case, ctx)
            results[cid] = result
            run["casos_ejecutados"].append(cid)
            run["llamadas_llm"] += result["llamadas_llm"]
            run["tokens"] += result["tokens"]["total"]
            ok = sum(1 for c in result["criterios"] if c["ok"])
            say(f"[{cid}] {result['estado']} {ok}/{len(case['criterio'])} criterios, "
                f"{result['llamadas_llm']} llamadas LLM, {result['duracion_s']} s"
                + (f" ({result['motivo']})" if result["estado"] in (PENDIENTE, ERROR) else ""))
            if result["estado"] == PENDIENTE and result.get("interrupcion"):
                run["interrumpida"] = True
                run["motivo_interrupcion"] = result["interrupcion"]["motivo"]
        if save is not None:
            save(snapshot())
    if run["interrumpida"]:
        for case in cases:
            entry = results[case["id"]]
            if entry["estado"] == PENDIENTE and entry.get("motivo") == "no_ejecutado":
                entry["motivo"] = f"no_ejecutado: la corrida se interrumpió ({run['motivo_interrupcion']})"
    run["fin"] = _now_iso()
    return snapshot()


# -- Archivos y reporte -----------------------------------------------------------------------------
def write_results(doc: dict[str, Any], path: Path) -> None:
    """Escribe el documento (enmascarado) de forma atómica; el temporal `*.tmp.json` está en .gitignore."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp.json")
    temporary.write_text(
        json.dumps(mask_value(doc), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def format_report(doc: dict[str, Any]) -> str:
    """Tabla legible de resultados, fallos y resumen."""
    lines = [
        f"{'caso':<7}{'estado':<11}{'categoría':<11}{'criterios':<11}{'LLM':>4}{'seg':>7}  nombre",
    ]
    for case in doc["casos"]:
        total = len(case["criterios"])
        ok = sum(1 for c in case["criterios"] if c["ok"])
        crit = f"{ok}/{total}" if total else "-"
        lines.append(
            f"{case['id']:<7}{case['estado']:<11}{case['categoria']:<11}{crit:<11}"
            f"{case['llamadas_llm']:>4}{case['duracion_s']:>7}  {case['nombre'][:52]}"
        )
    details = []
    for case in doc["casos"]:
        if case["estado"] == FALLIDO:
            details += [f"  {case['id']} [{c['tipo']}] {c['detalle']}" for c in case["criterios"] if not c["ok"]]
        elif case["estado"] in (PENDIENTE, ERROR, OMITIDO):
            details.append(f"  {case['id']} {case['estado']}: {case.get('motivo')}")
    if details:
        lines += ["", "Detalle:", *details]
    s = doc["resumen"]
    lines += [
        "",
        f"Casos: {s['casos']} | APROBADO {s[APROBADO]} | FALLIDO {s[FALLIDO]} | ERROR {s[ERROR]} | "
        f"PENDIENTE {s[PENDIENTE]} | OMITIDO {s[OMITIDO]} | tasa de aprobación {s['tasa_aprobacion']:.0%}",
        f"Llamadas LLM (todas las ejecuciones): {s['llamadas_llm_total']} | tokens: {s['tokens_total']}",
        f"Interrumpida: {'sí (' + str(s['motivo_interrupcion']) + ')' if s['interrumpida'] else 'no'}",
        "RESULTADO: " + ("APROBADA" if s["aprobada"] else (
            "CON FALLAS" if s[FALLIDO] or s[ERROR] else "INCOMPLETA")),
    ]
    return "\n".join(lines)


# -- Configuración y CLI ---------------------------------------------------------------------------------
def prepare_google(status: dict[str, str]) -> tuple[bool, str, Optional[Callable[[], int]]]:
    """`(lista, motivo, contador_de_filas)`: solo presencia de variables y del token, nunca valores."""
    missing = [
        f"falta {name}" for name in ("DRIVE_FOLDER_ID", "SHEET_ID", "GOOGLE_OAUTH_CLIENT_SECRETS")
        if status.get(name) == "falta"
    ]
    if missing:
        return False, "; ".join(missing) + " (scripts/setup_google_resources.py, docs/setup_google.md)", None
    from app.google_auth import GoogleAuthError, build_sheets_service, token_exists
    from app.tools.sheets import get_sheet_snapshot

    try:
        settings = load_settings(required=["llm", "google"])
        if not token_exists(settings):
            return False, "falta el token OAuth (scripts/google_auth.py)", None
        sheets = build_sheets_service(settings)
    except (ConfigError, GoogleAuthError) as error:
        return False, str(error), None
    return True, "", lambda: get_sheet_snapshot(sheets, settings)["row_count"]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN, help="golden set JSON")
    parser.add_argument("--system-version", required=True, help="etiqueta del sistema bajo prueba (vN)")
    parser.add_argument("--out", type=Path, default=None, help="archivo de resultados")
    parser.add_argument("--resume", action="store_true",
                        help="ejecuta solo los casos PENDIENTE, OMITIDO o nunca corridos")
    parser.add_argument("--only", default=None, help="ids separados por coma (p. ej. GS01,GS08A)")
    parser.add_argument("--no-google", action="store_true",
                        help="omite los casos con Google (quedan OMITIDO: la corrida no queda completa)")
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    print(f"ERROR: {message}")
    return EXIT_CONFIG


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    if not re.fullmatch(r"v\d+", args.system_version):
        return _fail("--system-version debe tener la forma vN (por ejemplo v1).")
    out = args.out or ROOT / "eval" / f"results_{args.system_version}.json"
    try:
        golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return _fail(f"no se pudo leer el golden set ({type(error).__name__}).")
    problems = validate_golden_set(golden)
    if problems:
        return _fail("golden set inválido:\n  " + "\n  ".join(problems))
    only: Optional[set[str]] = None
    if args.only:
        only = {part.strip().upper() for part in args.only.split(",") if part.strip()}
        unknown = sorted(only - {c["id"].upper() for c in golden["casos"]})
        if unknown:
            return _fail(f"--only tiene ids que no existen: {', '.join(unknown)}.")

    existing: Optional[dict[str, Any]] = None
    if out.exists() and not args.resume:
        return _fail(
            f"{out.name} ya existe. Usa --resume para continuar esa corrida o elige otra "
            "--system-version (los resultados registrados no se sobrescriben)."
        )
    if out.exists() and args.resume:
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return _fail(f"no se pudo leer {out.name} ({type(error).__name__}).")
        mismatch = [
            name for name, expected in (
                ("version_sistema", args.system_version), ("version_golden", golden["version"]),
                ("golden_sha256", golden_sha256(golden)),
            ) if existing.get(name) != expected
        ]
        if mismatch:
            return _fail(
                f"{out.name} no corresponde a este golden set y versión del sistema ({', '.join(mismatch)}). "
                "No se reanuda: un caso editado no puede heredar resultados anteriores."
            )

    status = config_status()
    missing = [name for name in ("GEMINI_API_KEY", "LLM_MODEL") if status[name] == "falta"]
    if missing:
        return _fail(
            f"falta {', '.join(missing)}. Copia .env.example a .env y completa los valores. "
            "No se hizo ninguna llamada de red."
        )
    try:
        settings = load_settings(required=["llm"])
    except ConfigError as error:
        return _fail(str(error))

    prior = {c["id"]: c for c in (existing or {}).get("casos", [])}
    todo = plan_cases(golden, prior, only)
    google_ready, google_reason, sheet_rows = False, "", None
    if any(c["google"] for c in todo) and not args.no_google:
        google_ready, google_reason, sheet_rows = prepare_google(status)
        if not google_ready:
            print(f"AVISO: los casos con Google quedarán PENDIENTE ({google_reason}).")
    try:
        expected_json = json.loads(EXPECTED_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return _fail(f"no se pudo leer data/receipts/expected.json ({type(error).__name__}).")

    llm = LLMClient(settings=settings, tracer=Tracer(console=False, write_file=False))
    print(f"Golden set {golden['version']} | sistema {args.system_version} | modelo {llm.model} | "
          f"alcance {SECURITY_SCOPE_ID} | casos a ejecutar: {len(todo)}")
    with tempfile.TemporaryDirectory(prefix="eval_") as tmp:
        ctx = RunContext(
            llm=llm, system_version=args.system_version, run_id=datetime.now().strftime("%H%M%S"),
            tmp_dir=Path(tmp), google_ready=google_ready, google_reason=google_reason,
            sheet_rows=sheet_rows, expected_json=expected_json,
        )
        doc = execute_run(
            golden, ctx, existing=existing, only=only, resume=args.resume, no_google=args.no_google,
            save=lambda d: write_results(d, out), progress=print,
        )
    write_results(doc, out)
    print("\n" + format_report(doc))
    print(f"\nResultados: {out}")
    return exit_code(doc)


if __name__ == "__main__":
    raise SystemExit(main())
