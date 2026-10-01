"""Pruebas offline del arnés de evaluación (Etapa 12): sin red, con asistentes y LLM falsos."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.assistant import AssistantResult
from app.llm import LLMCallError, UsageStats
from app.models import EventType
from app.prompts import SECURITY_SCOPE_ID
from eval import run_eval
from eval.criteria import (
    CATEGORIES,
    CRITERIA,
    evaluate_case,
    evaluate_criterion,
    validate_criterion,
    validate_golden_set,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "eval" / "golden_set_v1.json"


# -- Evidencia sintética ---------------------------------------------------------------------------
def turn(**overrides):
    base = {
        "indice": 1, "texto": "x", "ruta": "REGISTRAR_RECIBO", "respaldo": False, "respuesta": "",
        "stop": "respuesta_final", "tools_llamadas": [], "tools_ejecutadas": {}, "veredictos": [],
        "extracciones": [], "estado": {"nombre_usuario": None, "totales_por_categoria": {},
                                       "confirmacion_pendiente": None},
        "filas_antes": None, "filas_despues": None, "filas_registradas": [], "llamadas_llm": 1,
        "alcances": [SECURITY_SCOPE_ID],
    }
    return {**base, **overrides}


def evidence(*turns, generado=None, expected=None):
    numbered = [{**t, "indice": i} for i, t in enumerate(turns, start=1)]
    return {"turnos": numbered, "generado": generado, "expected_json": expected or {},
            "alcance_esperado": SECURITY_SCOPE_ID}


GENERATED = {"fecha": "2026-10-01", "comercio": "Minimarket Prueba 105334-9", "monto": 78340,
             "categoria": "Supermercado"}
EXPECTED = {"receipt_hard.jpg": {"fecha": "2026-09-05", "monto": 12990, "comercio": "Luna Azul"}}


def _state(**kw):
    return {"nombre_usuario": None, "totales_por_categoria": {}, "confirmacion_pendiente": None, **kw}


# tipo -> (criterio, evidencia que lo cumple, evidencia que lo incumple)
CASES = {
    "ruta": (
        {"tipo": "ruta", "turno": 1, "igual": "CONSULTAR_GASTOS"},
        evidence(turn(ruta="CONSULTAR_GASTOS")), evidence(turn(ruta="CONVERSACION"))),
    "ruta_en": (
        {"tipo": "ruta_en", "en": ["FUERA_DE_ALCANCE", "CONVERSACION"]},
        evidence(turn(ruta="FUERA_DE_ALCANCE")), evidence(turn(ruta="REGISTRAR_RECIBO"))),
    "tool_llamada": (
        {"tipo": "tool_llamada", "nombre": "analizar_recibo", "min": 1},
        evidence(turn(tools_llamadas=["analizar_recibo"])), evidence(turn())),
    "tool_ejecutada": (
        {"tipo": "tool_ejecutada", "nombre": "registrar_gasto", "exactamente": 0},
        evidence(turn(tools_ejecutadas={"registrar_gasto": 0})),
        evidence(turn(tools_ejecutadas={"registrar_gasto": 1}))),
    "sin_tool_calls": (
        {"tipo": "sin_tool_calls"},
        evidence(turn()), evidence(turn(tools_llamadas=["guardar_recibo"]))),
    "extraccion_coincide": (
        {"tipo": "extraccion_coincide", "campos": ["fecha", "monto"],
         "esperado_de": "expected.json:receipt_hard.jpg"},
        evidence(turn(extracciones=[{"fecha": "2026-09-05", "monto": 12990.0}]), expected=EXPECTED),
        evidence(turn(extracciones=[{"fecha": "2026-09-05", "monto": 13000.0}]), expected=EXPECTED)),
    "veredicto_juez": (
        {"tipo": "veredicto_juez", "igual": "RECHAZAR"},
        evidence(turn(veredictos=[{"veredicto": "RECHAZAR"}])),
        evidence(turn(veredictos=[{"veredicto": "APROBAR"}]))),
    "respuesta_contiene": (
        {"tipo": "respuesta_contiene", "texto": "Diego", "sin_mayusculas": True},
        evidence(turn(respuesta="Listo, diego, quedó registrado.")), evidence(turn(respuesta="Listo."))),
    "respuesta_no_contiene": (
        {"tipo": "respuesta_no_contiene", "texto": "999999"},
        evidence(turn(respuesta="Registrado.")), evidence(turn(respuesta="Registré 999999."))),
    "respuesta_no_contiene_canarios": (
        {"tipo": "respuesta_no_contiene_canarios"},
        evidence(turn(respuesta="No puedo ayudar con eso.")),
        evidence(turn(respuesta="Mi regla es SECURITY_SCOPE_v2 y nada más."))),
    "no_afirma_accion_prohibida": (
        {"tipo": "no_afirma_accion_prohibida"},
        evidence(turn(respuesta="No he transferido nada: no puedo hacerlo.")),
        evidence(turn(respuesta="Listo, he transferido $50.000."))),
    "stop": (
        {"tipo": "stop", "igual": "ruta_consulta"},
        evidence(turn(stop="ruta_consulta")), evidence(turn(stop="respuesta_final"))),
    "memoria_total": (
        {"tipo": "memoria_total", "categoria": "Supermercado", "igual_a_monto_generado": True},
        evidence(turn(estado=_state(totales_por_categoria={"Supermercado": 78340.0})), generado=GENERATED),
        evidence(turn(estado=_state(totales_por_categoria={"Supermercado": 1.0})), generado=GENERATED)),
    "confirmacion_pendiente": (
        {"tipo": "confirmacion_pendiente", "tipo_pendiente": "duplicado"},
        evidence(turn(estado=_state(confirmacion_pendiente={"tipo": "duplicado"}))),
        evidence(turn(estado=_state()))),
    "filas_planilla_delta": (
        {"tipo": "filas_planilla_delta", "igual": 1},
        evidence(turn(filas_antes=3, filas_despues=4)), evidence(turn(filas_antes=3, filas_despues=3))),
    "estado_nombre_usuario": (
        {"tipo": "estado_nombre_usuario", "igual": "Diego", "sin_mayusculas": True},
        evidence(turn(estado=_state(nombre_usuario="diego"))), evidence(turn())),
    "respuesta_contiene_monto_generado": (
        {"tipo": "respuesta_contiene_monto_generado"},
        evidence(turn(respuesta="Llevas gastado $78.340 en total."), generado=GENERATED),
        evidence(turn(respuesta="Aún no tienes gastos."), generado=GENERATED)),
    "respuesta_menciona_fila": (
        {"tipo": "respuesta_menciona_fila"},
        evidence(turn(respuesta="Quedó en la fila 5.", filas_registradas=[5])),
        evidence(turn(respuesta="Quedó en la fila 15.", filas_registradas=[5]))),
    "respuesta_pide_aclaracion": (
        {"tipo": "respuesta_pide_aclaracion"},
        evidence(turn(respuesta="La fecha es ilegible, ¿puedes enviar otra foto?")),
        evidence(turn(respuesta="Registrado."))),
    "respuesta_pide_confirmacion": (
        {"tipo": "respuesta_pide_confirmacion"},
        evidence(turn(respuesta="¿Confirmas que quieres registrarlo de nuevo?")),
        evidence(turn(respuesta="Listo."))),
    "respuesta_indica_sin_gastos": (
        {"tipo": "respuesta_indica_sin_gastos"},
        evidence(turn(respuesta="Todavía no tienes gastos registrados.")),
        evidence(turn(respuesta="Llevas varios."))),
    "respuesta_sin_montos": (
        {"tipo": "respuesta_sin_montos"},
        evidence(turn(respuesta="Aún no hay nada que sumar.")),
        evidence(turn(respuesta="Llevas $5.000 gastados."))),
    "alcance_en_cada_llamada": (
        {"tipo": "alcance_en_cada_llamada"},
        evidence(turn()), evidence(turn(alcances=["SECURITY_SCOPE_v1"]))),
}


# -- Golden set ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_set_is_valid(golden):
    assert validate_golden_set(golden) == []
    assert golden["version"] == "v1"


def test_golden_set_has_every_required_case(golden):
    ids = [c["id"] for c in golden["casos"]]
    assert len(ids) == len(set(ids))
    assert ids == ["GS01", "GS02", "GS03", "GS04", "GS05", "GS06", "GS07",
                   "GS08A", "GS08B", "GS08C", "GS08D", "GS09", "GS10"]
    assert {c["categoria"] for c in golden["casos"]} == set(CATEGORIES)


def test_golden_set_router_cases_cover_the_four_routes(golden):
    routes = {
        c["igual"] for case in golden["casos"] if case["id"].startswith("GS08")
        for c in case["criterio"] if c["tipo"] == "ruta"
    }
    assert routes == {"REGISTRAR_RECIBO", "CONSULTAR_GASTOS", "CONVERSACION", "FUERA_DE_ALCANCE"}


def test_golden_set_cases_encode_the_requirements(golden):
    by_id = {c["id"]: c for c in golden["casos"]}

    def types(case_id):
        return [(c["tipo"], c.get("igual"), c.get("nombre")) for c in by_id[case_id]["criterio"]]

    assert ("veredicto_juez", "RECHAZAR", None) in types("GS06")
    assert ("tool_ejecutada", None, "registrar_gasto") in types("GS01")
    assert any(t[0] == "sin_tool_calls" for t in types("GS07"))
    assert any(t[0] == "sin_tool_calls" for t in types("GS05"))
    assert any(t[0] == "respuesta_no_contiene_canarios" for t in types("GS05"))
    assert by_id["GS01"]["google"] and by_id["GS06"]["google"]
    assert by_id["GS09"]["google"] and by_id["GS10"]["google"]
    assert not by_id["GS02"]["google"] and not by_id["GS04"]["google"]
    duplicate_pending = [c for c in by_id["GS10"]["criterio"] if c["tipo"] == "confirmacion_pendiente"]
    assert duplicate_pending and duplicate_pending[0]["tipo_pendiente"] == "duplicado"


def test_golden_set_references_exist(golden):
    expected = json.loads((ROOT / "data" / "receipts" / "expected.json").read_text(encoding="utf-8"))
    for case in golden["casos"]:
        for entry in case["entrada"]:
            image = entry["imagen"]
            if image and "archivo" in image:
                assert (ROOT / image["archivo"]).is_file(), image["archivo"]
        for c in case["criterio"]:
            source = c.get("esperado_de", "")
            if source.startswith("expected.json:"):
                assert source.split(":", 1)[1] in expected


def test_golden_set_validation_rejects_bad_sets(golden):
    def mutated(edit):
        data = copy.deepcopy(golden)
        edit(data)
        return validate_golden_set(data)

    assert mutated(lambda d: d["casos"][0].__setitem__("criterio", []))
    assert mutated(lambda d: d["casos"][0]["criterio"].append({"tipo": "inventado"}))
    assert mutated(lambda d: d["casos"][0]["criterio"].append({"tipo": "ruta"}))
    assert mutated(lambda d: d["casos"][0]["criterio"].append({"tipo": "tool_llamada", "nombre": "x"}))
    assert mutated(lambda d: d["casos"][0]["criterio"].append({"tipo": "stop", "igual": "x", "turno": 5}))
    assert mutated(lambda d: d["casos"][1].__setitem__("id", "GS01"))
    assert mutated(lambda d: d["casos"][0].__setitem__("categoria", "otra"))
    assert mutated(lambda d: d["casos"][0].__setitem__("google", "si"))
    assert mutated(lambda d: d["casos"][1]["criterio"].append(
        {"tipo": "respuesta_contiene_monto_generado"}))  # GS02 no tiene recibo generado
    assert mutated(lambda d: d.__setitem__("casos", []))
    assert mutated(lambda d: d.__setitem__("version", "uno"))


# -- Criterios ---------------------------------------------------------------------------------------
def test_every_criterion_type_has_a_pass_and_a_fail_case():
    assert set(CASES) == set(CRITERIA)


@pytest.mark.parametrize("kind", sorted(CASES))
def test_criterion_passes_when_the_condition_holds(kind):
    criterion, passing, _failing = CASES[kind]
    assert validate_criterion(criterion) == []
    outcome = evaluate_criterion(criterion, passing)
    assert outcome["ok"] is True, outcome["detalle"]
    assert outcome["tipo"] == kind


@pytest.mark.parametrize("kind", sorted(CASES))
def test_criterion_fails_when_the_condition_does_not_hold(kind):
    criterion, _passing, failing = CASES[kind]
    outcome = evaluate_criterion(criterion, failing)
    assert outcome["ok"] is False
    assert outcome["detalle"]


def test_route_criterion_does_not_accept_a_router_fallback():
    criterion = {"tipo": "ruta", "turno": 1, "igual": "FUERA_DE_ALCANCE"}
    assert not evaluate_criterion(criterion, evidence(turn(ruta="FUERA_DE_ALCANCE", respaldo=True)))["ok"]
    assert evaluate_criterion(criterion, evidence(turn(ruta="FUERA_DE_ALCANCE")))["ok"]


def test_criteria_fail_without_the_evidence_they_need():
    empty = evidence()
    for kind, (criterion, _p, _f) in CASES.items():
        assert not evaluate_criterion(criterion, empty)["ok"], kind
    assert not evaluate_criterion(CASES["extraccion_coincide"][0], evidence(turn(), expected=EXPECTED))["ok"]
    assert not evaluate_criterion(CASES["filas_planilla_delta"][0], evidence(turn()))["ok"]
    assert not evaluate_criterion({"tipo": "ruta", "turno": 3, "igual": "CONVERSACION"},
                                  evidence(turn(ruta="CONVERSACION")))["ok"]


def test_criteria_can_target_one_turn_or_sum_all():
    two = evidence(turn(tools_ejecutadas={"registrar_gasto": 1}), turn(tools_ejecutadas={"registrar_gasto": 0}))
    assert evaluate_criterion({"tipo": "tool_ejecutada", "nombre": "registrar_gasto", "exactamente": 1}, two)["ok"]
    assert evaluate_criterion({"tipo": "tool_ejecutada", "nombre": "registrar_gasto", "exactamente": 0,
                               "turno": 2}, two)["ok"]
    assert not evaluate_criterion({"tipo": "tool_ejecutada", "nombre": "registrar_gasto", "exactamente": 0,
                                   "turno": 1}, two)["ok"]


def test_a_broken_criterion_counts_as_failed_not_skipped():
    case = {"criterio": [{"tipo": "ruta", "igual": "X"}, {"tipo": "inventado"}, {"tipo": "ruta"}]}
    results = evaluate_case(case, evidence(turn()))
    assert len(results) == 3
    assert not any(r["ok"] for r in results)


# -- run_case con un asistente falso ---------------------------------------------------------------
class FakeAssistant:
    """Asistente guionado por texto: cada texto tiene una lista de comportamientos (uno por uso)."""

    def __init__(self, behaviors, llm, calls):
        self.behaviors, self.llm, self.calls = behaviors, llm, calls

    def handle(self, text, image=None, conversation=None, state=None, tracer=None):
        self.calls.append(text)
        behavior = self.behaviors[text].pop(0)
        if behavior.get("raise"):
            raise behavior["raise"]
        self.llm.stats.calls += 1
        tracer.record(EventType.ROUTE, {"ruta": behavior["route"], "fallback": False})
        if behavior.get("quota"):
            tracer.record(EventType.LLM_DECISION, {
                "status": "error", "error_code": behavior.get("code", 429),
                "error_status": behavior.get("status", "RESOURCE_EXHAUSTED"),
                "security_scope_id": SECURITY_SCOPE_ID})
        else:
            tracer.record(EventType.LLM_DECISION, {"status": "ok", "security_scope_id": SECURITY_SCOPE_ID})
        for name in behavior.get("tools", []):
            tracer.record(EventType.TOOL_CALL, {"tool": name})
        if behavior.get("verdict"):
            tracer.record(EventType.JUDGE_VERDICT, {"veredicto": behavior["verdict"]})
        if behavior.get("name") and state is not None:
            state.nombre_usuario = behavior["name"]
        return AssistantResult(behavior["route"], behavior.get("text", "ok"),
                               [{"name": n, "args": {}, "ok": True, "executed": True}
                                for n in behavior.get("tools", [])],
                               behavior.get("stop", "ruta_conversacion"))


def make_case(case_id, text, route, google=False):
    return {
        "id": case_id, "nombre": f"caso {case_id}", "categoria": "router", "google": google,
        "entrada": [{"texto": text, "imagen": None}],
        "expectativa": "x",
        "criterio": [{"tipo": "ruta", "turno": 1, "igual": route}],
    }


def make_golden(*cases):
    return {"version": "v1", "descripcion": "mini", "casos": list(cases)}


def make_ctx(tmp_path, behaviors, google_ready=False, calls=None, sheet_rows=None):
    llm = SimpleNamespace(stats=UsageStats(), model="modelo-falso")
    calls = calls if calls is not None else []
    return run_eval.RunContext(
        llm=llm, system_version="v1", run_id="123456", tmp_dir=tmp_path / "tmp",
        trace_dir=tmp_path / "traces", root=ROOT, google_ready=google_ready,
        google_reason="falta DRIVE_FOLDER_ID", sheet_rows=sheet_rows, expected_json={},
        assistant_factory=lambda overrides, tracer: FakeAssistant(behaviors, llm, calls),
    ), calls


def good(route="CONVERSACION"):
    return {"route": route}


def test_run_case_approves_when_every_criterion_holds(tmp_path):
    ctx, _ = make_ctx(tmp_path, {"hola": [good()]})
    result = run_eval.run_case(make_case("GS01", "hola", "CONVERSACION"), ctx)
    assert result["estado"] == "APROBADO"
    assert result["criterios"][0]["ok"] is True
    assert result["rutas"] == ["CONVERSACION"] and result["llamadas_llm"] == 1
    assert result["traza"] == "traces/eval_v1_GS01.jsonl"
    assert (tmp_path / "traces" / "eval_v1_GS01.jsonl").is_file()
    assert result["herramientas"] == "reales_sin_google"


def test_run_case_fails_when_a_criterion_does_not_hold(tmp_path):
    ctx, _ = make_ctx(tmp_path, {"hola": [good("FUERA_DE_ALCANCE")]})
    result = run_eval.run_case(make_case("GS01", "hola", "CONVERSACION"), ctx)
    assert result["estado"] == "FALLIDO"
    assert result["criterios"][0]["ok"] is False


def test_a_case_cannot_pass_without_criteria_or_with_a_skipped_one(tmp_path):
    ctx, _ = make_ctx(tmp_path, {"hola": [good(), good()]})
    empty = make_case("GS01", "hola", "CONVERSACION")
    empty["criterio"] = []
    assert run_eval.run_case(empty, ctx)["estado"] == "FALLIDO"
    unknown = make_case("GS02", "hola", "CONVERSACION")
    unknown["criterio"].append({"tipo": "inventado"})
    result = run_eval.run_case(unknown, ctx)
    assert result["estado"] == "FALLIDO" and len(result["criterios"]) == 2


@pytest.mark.parametrize("failure,reason", [
    (LLMCallError(429, "RESOURCE_EXHAUSTED", 6), "cuota_agotada"),
    (LLMCallError(503, "UNAVAILABLE", 6), "api_no_disponible"),
])
def test_exhausted_api_raised_by_the_assistant_leaves_the_case_pending(tmp_path, failure, reason):
    ctx, _ = make_ctx(tmp_path, {"hola": [{"raise": failure}]})
    result = run_eval.run_case(make_case("GS01", "hola", "CONVERSACION"), ctx)
    assert result["estado"] == "PENDIENTE"
    assert result["interrupcion"]["motivo"] == reason
    assert result["criterios"] == []


def test_quota_error_in_the_trace_leaves_the_case_pending(tmp_path):
    # El asistente real captura LLMCallError y responde con un texto seguro: la señal es el LLM_DECISION.
    ctx, _ = make_ctx(tmp_path, {"hola": [{"route": "FUERA_DE_ALCANCE", "quota": True}]})
    result = run_eval.run_case(make_case("GS01", "hola", "FUERA_DE_ALCANCE"), ctx)
    assert result["estado"] == "PENDIENTE"
    assert result["interrupcion"] == {"motivo": "cuota_agotada", "codigo": 429, "estado": "RESOURCE_EXHAUSTED"}


def test_a_non_quota_api_error_is_judged_not_deferred(tmp_path):
    ctx, _ = make_ctx(tmp_path, {"hola": [{"route": "FUERA_DE_ALCANCE", "quota": True,
                                           "code": 400, "status": "INVALID_ARGUMENT"}]})
    result = run_eval.run_case(make_case("GS01", "hola", "CONVERSACION"), ctx)
    assert result["estado"] == "FALLIDO"


def test_a_harness_crash_is_an_error_not_a_pass(tmp_path):
    ctx, _ = make_ctx(tmp_path, {"hola": [{"raise": RuntimeError("boom")}]})
    result = run_eval.run_case(make_case("GS01", "hola", "CONVERSACION"), ctx)
    assert result["estado"] == "ERROR" and "RuntimeError" in result["motivo"]


def test_run_case_measures_the_sheet_per_turn(tmp_path):
    rows = iter([3, 3, 4, 4])
    ctx, _ = make_ctx(tmp_path, {"uno": [good()], "dos": [good()]}, google_ready=True,
                      sheet_rows=lambda: next(rows))
    case = make_case("GS01", "uno", "CONVERSACION", google=True)
    case["entrada"].append({"texto": "dos", "imagen": None})
    case["criterio"] = [
        {"tipo": "filas_planilla_delta", "turno": 1, "igual": 0},
        {"tipo": "filas_planilla_delta", "turno": 2, "igual": 1},
        {"tipo": "filas_planilla_delta", "igual": 1},
    ]
    result = run_eval.run_case(case, ctx)
    assert result["estado"] == "APROBADO", result["criterios"]
    assert [t["filas_antes"] for t in result["turnos"]] == [3, 3]
    assert [t["filas_despues"] for t in result["turnos"]] == [3, 4]


# -- Corrida completa, interrupción y reanudación ---------------------------------------------------
def three_case_golden():
    return make_golden(
        make_case("GS01", "uno", "CONVERSACION"),
        make_case("GS02", "dos", "CONVERSACION"),
        make_case("GS03", "tres", "CONVERSACION"),
    )


def test_a_quota_interruption_stops_the_run_and_is_not_a_pass(tmp_path):
    behaviors = {"uno": [good()], "dos": [{"raise": LLMCallError(429, "RESOURCE_EXHAUSTED", 6)}],
                 "tres": [good()]}
    ctx, calls = make_ctx(tmp_path, behaviors)
    doc = run_eval.execute_run(three_case_golden(), ctx)
    states = {c["id"]: c["estado"] for c in doc["casos"]}
    assert states == {"GS01": "APROBADO", "GS02": "PENDIENTE", "GS03": "PENDIENTE"}
    assert calls == ["uno", "dos"]  # el caso 3 no se intentó
    assert "interrumpió" in doc["casos"][2]["motivo"]
    summary = doc["resumen"]
    assert summary["interrumpida"] is True and summary["motivo_interrupcion"] == "cuota_agotada"
    assert summary["aprobada"] is False and summary["PENDIENTE"] == 2
    assert run_eval.exit_code(doc) == run_eval.EXIT_INCOMPLETE == 3


def test_an_interrupted_run_is_never_a_pass_even_if_every_case_passed():
    doc = {"casos": [{"estado": "APROBADO"}] * 2,
           "ejecuciones": [{"llamadas_llm": 4, "tokens": 0, "interrumpida": True,
                            "motivo_interrupcion": "cuota_agotada"}]}
    doc["resumen"] = run_eval.summarize(doc)
    assert doc["resumen"]["aprobada"] is False
    assert run_eval.exit_code(doc) == 3
    doc["ejecuciones"][-1]["interrumpida"] = False
    doc["resumen"] = run_eval.summarize(doc)
    assert doc["resumen"]["aprobada"] is True and run_eval.exit_code(doc) == 0


def test_exit_code_one_when_a_case_failed():
    doc = {"casos": [{"estado": "APROBADO"}, {"estado": "FALLIDO"}], "ejecuciones": [{"interrumpida": False}]}
    doc["resumen"] = run_eval.summarize(doc)
    assert doc["resumen"]["aprobada"] is False and run_eval.exit_code(doc) == 1


def test_resume_runs_only_pending_cases_and_keeps_failures(tmp_path):
    golden = three_case_golden()
    first_ctx, _ = make_ctx(tmp_path, {"uno": [good("FUERA_DE_ALCANCE")],
                                       "dos": [{"raise": LLMCallError(429, "RESOURCE_EXHAUSTED", 6)}]})
    first = run_eval.execute_run(golden, first_ctx)
    assert [c["estado"] for c in first["casos"]] == ["FALLIDO", "PENDIENTE", "PENDIENTE"]
    kept = copy.deepcopy(first["casos"][0])

    ctx, calls = make_ctx(tmp_path, {"uno": [good()], "dos": [good()], "tres": [good()]})
    doc = run_eval.execute_run(golden, ctx, existing=first, resume=True)
    assert calls == ["dos", "tres"]  # GS01 (FALLIDO) no se reejecuta aunque ahora pasaría
    assert doc["casos"][0] == kept and doc["casos"][0]["estado"] == "FALLIDO"
    assert [c["estado"] for c in doc["casos"][1:]] == ["APROBADO", "APROBADO"]
    assert doc["resumen"]["aprobada"] is False
    assert run_eval.exit_code(doc) == run_eval.EXIT_FAIL
    assert len(doc["ejecuciones"]) == 2
    assert doc["ejecuciones"][0]["interrumpida"] is True and doc["ejecuciones"][0]["motivo_interrupcion"] == "cuota_agotada"
    assert doc["ejecuciones"][1]["reanudada"] is True and doc["ejecuciones"][1]["casos_ejecutados"] == ["GS02", "GS03"]
    assert doc["resumen"]["interrumpida"] is False  # la última ejecución terminó
    assert doc["resumen"]["llamadas_llm_total"] == sum(c["llamadas_llm"] for c in first["casos"]) + 2


def test_resume_completes_a_run_without_rerunning_approved_cases(tmp_path):
    golden = three_case_golden()
    first_ctx, _ = make_ctx(tmp_path, {"uno": [good()],
                                       "dos": [{"raise": LLMCallError(429, "RESOURCE_EXHAUSTED", 6)}]})
    first = run_eval.execute_run(golden, first_ctx)
    ctx, calls = make_ctx(tmp_path, {"dos": [good()], "tres": [good()]})
    doc = run_eval.execute_run(golden, ctx, existing=first, resume=True)
    assert calls == ["dos", "tres"]
    assert doc["resumen"]["aprobada"] is True and run_eval.exit_code(doc) == run_eval.EXIT_PASS


def test_without_resume_the_existing_document_is_ignored(tmp_path):
    golden = three_case_golden()
    old = run_eval.execute_run(golden, make_ctx(tmp_path, {"uno": [good("FUERA_DE_ALCANCE")]})[0],
                               only={"GS01"})
    ctx, calls = make_ctx(tmp_path, {"uno": [good()], "dos": [good()], "tres": [good()]})
    doc = run_eval.execute_run(golden, ctx, existing=old, resume=False)
    assert calls == ["uno", "dos", "tres"]
    assert len(doc["ejecuciones"]) == 1


def test_only_leaves_the_other_cases_pending(tmp_path):
    ctx, calls = make_ctx(tmp_path, {"dos": [good()]})
    doc = run_eval.execute_run(three_case_golden(), ctx, only={"GS02"})
    assert calls == ["dos"]
    assert [c["estado"] for c in doc["casos"]] == ["PENDIENTE", "APROBADO", "PENDIENTE"]
    assert doc["resumen"]["aprobada"] is False


def test_google_cases_are_pending_when_google_is_not_configured(tmp_path):
    golden = make_golden(make_case("GS01", "uno", "CONVERSACION"),
                         make_case("GS02", "dos", "CONVERSACION", google=True))
    ctx, calls = make_ctx(tmp_path, {"uno": [good()], "dos": [good()]}, google_ready=False)
    doc = run_eval.execute_run(golden, ctx)
    assert calls == ["uno"]
    assert doc["casos"][1]["estado"] == "PENDIENTE" and "DRIVE_FOLDER_ID" in doc["casos"][1]["motivo"]
    assert doc["resumen"]["aprobada"] is False and doc["resumen"]["interrumpida"] is False
    assert run_eval.exit_code(doc) == run_eval.EXIT_INCOMPLETE


def test_no_google_marks_google_cases_omitted_and_the_run_is_not_complete(tmp_path):
    golden = make_golden(make_case("GS01", "uno", "CONVERSACION"),
                         make_case("GS02", "dos", "CONVERSACION", google=True))
    ctx, calls = make_ctx(tmp_path, {"uno": [good()], "dos": [good()]}, google_ready=True)
    doc = run_eval.execute_run(golden, ctx, no_google=True)
    assert calls == ["uno"]
    assert doc["casos"][1]["estado"] == "OMITIDO"
    assert doc["resumen"]["OMITIDO"] == 1 and doc["resumen"]["aprobada"] is False
    assert run_eval.exit_code(doc) == run_eval.EXIT_INCOMPLETE


def test_resume_reruns_google_cases_once_google_is_available(tmp_path):
    golden = make_golden(make_case("GS01", "uno", "CONVERSACION"),
                         make_case("GS02", "dos", "CONVERSACION", google=True))
    first = run_eval.execute_run(golden, make_ctx(tmp_path, {"uno": [good()]}, google_ready=False)[0])
    ctx, calls = make_ctx(tmp_path, {"dos": [good()]}, google_ready=True)
    doc = run_eval.execute_run(golden, ctx, existing=first, resume=True)
    assert calls == ["dos"] and doc["resumen"]["aprobada"] is True


def test_the_document_is_saved_after_every_case(tmp_path):
    saved = []
    ctx, _ = make_ctx(tmp_path, {"uno": [good()], "dos": [good()], "tres": [good()]})
    run_eval.execute_run(three_case_golden(), ctx, save=lambda d: saved.append(copy.deepcopy(d["resumen"])))
    assert [s["APROBADO"] for s in saved] == [1, 2, 3]


# -- Archivos, reporte y CLI --------------------------------------------------------------------------
def test_write_results_is_atomic_masked_and_leaves_no_temporary(tmp_path):
    doc = {"casos": [], "nota": "Authorization: Bearer abcdef0123456789xyz"}
    out = tmp_path / "results_v9.json"
    run_eval.write_results(doc, out)
    assert json.loads(out.read_text(encoding="utf-8"))["nota"].endswith("***")
    assert not list(tmp_path.glob("*.tmp.json"))


def test_report_lists_every_case_and_the_verdict(tmp_path):
    ctx, _ = make_ctx(tmp_path, {"uno": [good("FUERA_DE_ALCANCE")], "dos": [good()], "tres": [good()]})
    doc = run_eval.execute_run(three_case_golden(), ctx)
    report = run_eval.format_report(doc)
    for case_id in ("GS01", "GS02", "GS03"):
        assert case_id in report
    assert "FALLIDO" in report and "RESULTADO: CON FALLAS" in report
    assert "ruta" in report  # detalle del criterio fallido


def test_gitignore_keeps_results_versioned():
    lines = [line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "eval/results_*.tmp.json" in lines
    assert not any(line in ("eval/results_*.json", "eval/", "eval/*", "eval/results*") for line in lines)


def _no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no debe crear el cliente LLM")

    monkeypatch.setattr(run_eval, "LLMClient", boom)


def test_main_exits_2_without_gemini_configuration_and_without_network(monkeypatch, tmp_path, capsys):
    _no_network(monkeypatch)
    monkeypatch.setattr(run_eval, "config_status", lambda: {
        name: "falta" for name in ("GEMINI_API_KEY", "LLM_MODEL", "DRIVE_FOLDER_ID", "SHEET_ID",
                                   "GOOGLE_OAUTH_CLIENT_SECRETS")})
    out = tmp_path / "x.json"
    assert run_eval.main(["--system-version", "v0", "--out", str(out)]) == 2
    assert not out.exists()
    assert "GEMINI_API_KEY" in capsys.readouterr().out


def test_main_does_not_overwrite_an_existing_results_file(monkeypatch, tmp_path):
    _no_network(monkeypatch)
    out = tmp_path / "results_v1.json"
    out.write_text("{}", encoding="utf-8")
    assert run_eval.main(["--system-version", "v1", "--out", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == "{}"


def test_main_refuses_to_resume_results_of_another_version_or_golden(monkeypatch, tmp_path):
    _no_network(monkeypatch)
    out = tmp_path / "results_v1.json"
    out.write_text(json.dumps({"version_sistema": "v1", "version_golden": "v1",
                               "golden_sha256": "otro", "casos": []}), encoding="utf-8")
    assert run_eval.main(["--system-version", "v1", "--out", str(out), "--resume"]) == 2
    out.write_text(json.dumps({"version_sistema": "v7", "version_golden": "v1",
                               "golden_sha256": "otro", "casos": []}), encoding="utf-8")
    assert run_eval.main(["--system-version", "v1", "--out", str(out), "--resume"]) == 2


def test_main_rejects_bad_arguments(monkeypatch, tmp_path):
    _no_network(monkeypatch)
    out = str(tmp_path / "x.json")
    assert run_eval.main(["--system-version", "uno", "--out", out]) == 2
    assert run_eval.main(["--system-version", "v1", "--out", out, "--only", "GS99"]) == 2
    broken = tmp_path / "golden.json"
    broken.write_text(json.dumps({"version": "v1", "descripcion": "x", "casos": [{"id": "GS01"}]}),
                      encoding="utf-8")
    assert run_eval.main(["--system-version", "v1", "--out", out, "--golden", str(broken)]) == 2


# -- Recibos y tools --------------------------------------------------------------------------------
def test_generated_receipts_are_unique_per_run_and_case(tmp_path):
    from datetime import datetime

    recipe = {"comercio_base": "Minimarket Prueba", "fecha": "hoy", "monto_base": 15000,
              "categoria_hint": "Supermercado"}
    now = datetime(2026, 10, 1, 10, 53, 34)
    path_a, exp_a = run_eval.generate_receipt(recipe, "GS01", 1, "105334", tmp_path, now)
    path_b, exp_b = run_eval.generate_receipt(recipe, "GS09", 1, "105334", tmp_path, now)
    _, exp_c = run_eval.generate_receipt(recipe, "GS01", 1, "105400", tmp_path, now)
    assert path_a.is_file() and path_b.is_file() and path_a != path_b
    assert exp_a["comercio"] == "Minimarket Prueba 105334-1"
    assert len({exp_a["comercio"], exp_b["comercio"], exp_c["comercio"]}) == 3
    assert exp_a["fecha"] == "2026-10-01" and exp_a["monto"] >= 15000 and exp_a["monto"] % 10 == 0


def test_same_image_reference_resolves_to_the_same_file(tmp_path):
    ctx, _ = make_ctx(tmp_path, {})
    images, ev = {}, {"generado": None}
    spec = {"generado": {"comercio_base": "Minimarket Prueba", "monto_base": 15000}}
    first = run_eval._resolve_image(spec, "GS10", 1, ctx, images, ev)
    again = run_eval._resolve_image({"igual_turno": 1}, "GS10", 2, ctx, images, ev)
    assert first == again and ev["generado"]["monto"] >= 15000
    with pytest.raises(FileNotFoundError):
        run_eval._resolve_image({"archivo": "data/receipts/no_existe.jpg"}, "GS02", 1, ctx, {}, {})


def test_google_blanked_restores_the_environment(monkeypatch):
    monkeypatch.setenv("DRIVE_FOLDER_ID", "carpeta-de-prueba")
    monkeypatch.delenv("SHEET_ID", raising=False)
    with run_eval.google_blanked():
        assert all(os.environ[name] == "" for name in run_eval.GOOGLE_VARIABLES)
    assert os.environ["DRIVE_FOLDER_ID"] == "carpeta-de-prueba"
    assert "SHEET_ID" not in os.environ


def test_there_is_no_simulated_success_path():
    source = (ROOT / "eval" / "run_eval.py").read_text(encoding="utf-8")
    assert not hasattr(run_eval, "SIMULATED_URL")
    assert "DriveResult(" not in source and "SheetResult(" not in source


def test_non_google_cases_never_report_a_drive_url_or_a_row(monkeypatch, tmp_path):
    # Aunque el entorno tenga configuración de Google, un caso sin Google corre con ella en blanco.
    monkeypatch.setenv("DRIVE_FOLDER_ID", "carpeta-real")
    monkeypatch.setenv("SHEET_ID", "planilla-real")
    seen = {}
    from app.models import DriveResult, SheetResult
    import app.tools.drive as drive_module
    import app.tools.sheets as sheets_module

    def fake_guardar(path, comercio, fecha, tracer=None):
        seen["drive"] = os.environ.get("DRIVE_FOLDER_ID")
        return DriveResult(success=False, error="servicio_no_disponible")

    def fake_registrar(tracer=None, **kwargs):
        seen["sheet"] = os.environ.get("SHEET_ID")
        return SheetResult(success=False, error="servicio_no_disponible")

    monkeypatch.setattr(drive_module, "guardar_recibo", fake_guardar)
    monkeypatch.setattr(sheets_module, "registrar_gasto", fake_registrar)
    probe = run_eval.ToolProbe(real=False, llm=None)
    tools_ = probe.overrides()
    drive = tools_["guardar_recibo"](Path("x.jpg"), "Comercio", "2026-10-01")
    sheet = tools_["registrar_gasto"](fecha="2026-10-01", comercio="C", monto=1000, categoria="Hogar",
                                      recibo_url="https://drive.google.com/file/d/x/view")
    assert seen == {"drive": "", "sheet": ""}  # las tools reales vieron la configuración en blanco
    assert os.environ["DRIVE_FOLDER_ID"] == "carpeta-real"  # y se restauró
    assert not drive.success and not sheet.success
    assert probe.rows == [] and probe.drive_links == []
    assert probe.counts == {"analizar_recibo": 0, "guardar_recibo": 1, "registrar_gasto": 1}


def test_real_tools_without_google_configuration_return_a_structured_error(monkeypatch):
    for name in run_eval.GOOGLE_VARIABLES:
        monkeypatch.setenv(name, "")
    probe = run_eval.ToolProbe(real=False, llm=None)
    tools_ = probe.overrides()
    drive = tools_["guardar_recibo"](ROOT / "data" / "receipts" / "receipt_normal.jpg", "Los Aromos", "2026-09-12")
    sheet = tools_["registrar_gasto"](fecha="2026-09-12", comercio="Los Aromos", monto=18490,
                                      categoria="Supermercado",
                                      recibo_url="https://drive.google.com/file/d/x/view")
    assert drive.success is False and not drive.web_view_link
    assert sheet.success is False and sheet.row_number is None
    assert probe.rows == [] and probe.drive_links == []
