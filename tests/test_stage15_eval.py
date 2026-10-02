"""Pruebas offline del golden set v2 y de los criterios del RAG (Etapa 15): sin red ni Redis."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.assistant import AssistantResult
from app.llm import UsageStats
from app.models import EventType
from app.prompts import SECURITY_SCOPE_ID
from eval import run_eval
from eval.criteria import CRITERIA, evaluate_criterion, validate_criterion, validate_golden_set
from test_stage12_eval import CASES as STAGE12_CASES
from test_stage12_eval import evidence, turn

ROOT = Path(__file__).resolve().parents[1]
V1_PATH = ROOT / "eval" / "golden_set_v1.json"
V2_PATH = ROOT / "eval" / "golden_set_v2.json"

SOURCE = "politica_rendicion_gastos_v2.md"
RETRIEVAL_OK = {
    "pregunta": "q", "top_k": 3, "umbral": 0.75, "mejor_similitud": 0.8078, "decision": "usar_contexto",
    "resultados": [{"chunk_id": "a", "fuente": SOURCE, "seccion": "4. Propinas", "similitud": 0.8078}],
}
RETRIEVAL_MISS = {**RETRIEVAL_OK, "mejor_similitud": 0.6988, "decision": "abstener"}


def rag_turn(**overrides):
    return turn(**{"retrievals": [], "embeddings": 0, **overrides})


# tipo -> (criterio, evidencia que lo cumple, evidencia que lo incumple)
CASES15 = {
    "stop_en": (
        {"tipo": "stop_en", "en": ["rag_abstencion", "ruta_fuera_de_alcance"]},
        evidence(rag_turn(stop="rag_abstencion")), evidence(rag_turn(stop="ruta_politica"))),
    "retrieval_count": (
        {"tipo": "retrieval_count", "exactamente": 1},
        evidence(rag_turn(retrievals=[RETRIEVAL_OK])), evidence(rag_turn())),
    "embeddings_count": (
        {"tipo": "embeddings_count", "exactamente": 0},
        evidence(rag_turn()), evidence(rag_turn(embeddings=1))),
    "llamadas_llm_count": (
        {"tipo": "llamadas_llm_count", "max": 1},
        evidence(rag_turn(llamadas_llm=1)), evidence(rag_turn(llamadas_llm=2))),
    "retrieval_decision": (
        {"tipo": "retrieval_decision", "igual": "abstener"},
        evidence(rag_turn(retrievals=[RETRIEVAL_MISS])), evidence(rag_turn(retrievals=[RETRIEVAL_OK]))),
    "retrieval_best_min": (
        {"tipo": "retrieval_best_min"},
        evidence(rag_turn(retrievals=[RETRIEVAL_OK])), evidence(rag_turn(retrievals=[RETRIEVAL_MISS]))),
    "cita_fuente_recuperada": (
        {"tipo": "cita_fuente_recuperada"},
        evidence(rag_turn(retrievals=[RETRIEVAL_OK], respuesta=f"Hasta el 10 %. [{SOURCE} §4. Propinas]")),
        evidence(rag_turn(retrievals=[RETRIEVAL_OK], respuesta="Hasta el 10 %, sin citar nada."))),
}


def test_stage15_types_are_exactly_the_ones_without_stage12_cases():
    assert set(CASES15) == set(CRITERIA) - set(STAGE12_CASES)


@pytest.mark.parametrize("kind", sorted(CASES15))
def test_rag_criterion_passes_when_the_condition_holds(kind):
    criterion, passing, _failing = CASES15[kind]
    assert validate_criterion(criterion) == []
    outcome = evaluate_criterion(criterion, passing)
    assert outcome["ok"] is True, outcome["detalle"]
    assert outcome["tipo"] == kind


@pytest.mark.parametrize("kind", sorted(CASES15))
def test_rag_criterion_fails_when_the_condition_does_not_hold(kind):
    criterion, _passing, failing = CASES15[kind]
    outcome = evaluate_criterion(criterion, failing)
    assert outcome["ok"] is False
    assert outcome["detalle"]


@pytest.mark.parametrize("kind", sorted(CASES15))
def test_rag_criteria_fail_without_evidence(kind):
    criterion = CASES15[kind][0]
    assert not evaluate_criterion(criterion, evidence())["ok"]
    if kind in ("stop_en", "llamadas_llm_count"):
        return  # usan campos que ya existían antes de la Etapa 15
    # evidencia de un turno sin los campos del RAG (por ejemplo, un arnés anterior a la Etapa 15)
    legacy = evidence(turn(respuesta=f"[{SOURCE} §x]"))
    assert not evaluate_criterion(criterion, legacy)["ok"]


def test_retrieval_decision_requires_a_retrieval_unless_si_existe():
    none = evidence(rag_turn(ruta="FUERA_DE_ALCANCE"))
    assert not evaluate_criterion({"tipo": "retrieval_decision", "igual": "abstener"}, none)["ok"]
    assert evaluate_criterion({"tipo": "retrieval_decision", "igual": "abstener", "si_existe": True}, none)["ok"]
    mixed = evidence(rag_turn(retrievals=[RETRIEVAL_OK]))
    assert not evaluate_criterion({"tipo": "retrieval_decision", "igual": "abstener", "si_existe": True}, mixed)["ok"]


def test_retrieval_best_min_accepts_an_explicit_value():
    ev = evidence(rag_turn(retrievals=[RETRIEVAL_OK]))
    assert evaluate_criterion({"tipo": "retrieval_best_min", "valor": 0.8}, ev)["ok"]
    assert not evaluate_criterion({"tipo": "retrieval_best_min", "valor": 0.9}, ev)["ok"]


def test_citation_must_name_a_retrieved_source():
    other = evidence(rag_turn(retrievals=[RETRIEVAL_OK], respuesta="Ver [otro_archivo.md §1. Algo]"))
    assert not evaluate_criterion({"tipo": "cita_fuente_recuperada"}, other)["ok"]
    bare = evidence(rag_turn(retrievals=[RETRIEVAL_OK], respuesta=f"Fuente: {SOURCE}"))
    assert not evaluate_criterion({"tipo": "cita_fuente_recuperada"}, bare)["ok"]
    cased = evidence(rag_turn(retrievals=[RETRIEVAL_OK], respuesta=f"[{SOURCE.upper()} §4. Propinas]"))
    assert evaluate_criterion({"tipo": "cita_fuente_recuperada"}, cased)["ok"]


def test_criteria_target_one_turn_for_rag_counts():
    two = evidence(rag_turn(retrievals=[RETRIEVAL_OK], embeddings=1), rag_turn())
    assert evaluate_criterion({"tipo": "retrieval_count", "exactamente": 1}, two)["ok"]
    assert evaluate_criterion({"tipo": "retrieval_count", "exactamente": 0, "turno": 2}, two)["ok"]
    assert not evaluate_criterion({"tipo": "embeddings_count", "exactamente": 0, "turno": 1}, two)["ok"]


# -- Validación ---------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def golden_v1():
    return json.loads(V1_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden_v2():
    return json.loads(V2_PATH.read_text(encoding="utf-8"))


def test_new_criteria_validate_their_parameters():
    assert validate_criterion({"tipo": "retrieval_decision", "igual": "otra"})
    assert validate_criterion({"tipo": "retrieval_decision", "igual": "abstener", "si_existe": "si"})
    assert validate_criterion({"tipo": "retrieval_count"})  # sin exactamente, min ni max
    assert validate_criterion({"tipo": "embeddings_count", "exactamente": -1})
    assert validate_criterion({"tipo": "stop_en", "en": []})
    assert validate_criterion({"tipo": "stop_en"})
    assert validate_criterion({"tipo": "retrieval_best_min", "valor": 2})
    assert validate_criterion({"tipo": "retrieval_best_min", "valor": True})


def test_rag_criteria_that_retrieve_need_a_rag_case(golden_v2):
    data = copy.deepcopy(golden_v2)
    gs11 = next(c for c in data["casos"] if c["id"] == "GS11")
    gs11["rag"] = False
    problems = validate_golden_set(data)
    assert any("rag: true" in p for p in problems)
    gs11["rag"] = "si"
    assert any("rag debe ser" in p for p in validate_golden_set(data))


# -- Golden set v2 ------------------------------------------------------------------------------------
def test_golden_v2_is_valid_and_keeps_every_v1_case_unchanged(golden_v1, golden_v2):
    assert validate_golden_set(golden_v2) == []
    assert golden_v2["version"] == "v2"
    assert golden_v2["casos"][: len(golden_v1["casos"])] == golden_v1["casos"]  # sin quitar ni editar
    ids = [c["id"] for c in golden_v2["casos"]]
    assert len(ids) == len(set(ids)) == len(golden_v1["casos"]) + 4
    assert ids[-4:] == ["GS11", "GS12", "GS13", "GS14"]


def test_golden_v2_new_cases_need_the_course_redis(golden_v2):
    new = {c["id"]: c for c in golden_v2["casos"][-4:]}
    assert all(c["rag"] is True and c["google"] is False for c in new.values())
    assert not any("rag" in c for c in golden_v2["casos"][:-4])


def test_golden_v2_new_cases_encode_the_rag_requirements(golden_v2):
    by_id = {c["id"]: c for c in golden_v2["casos"]}

    def criteria(case_id):
        return by_id[case_id]["criterio"]

    kinds = {case_id: {c["tipo"] for c in criteria(case_id)} for case_id in ("GS11", "GS12", "GS13", "GS14")}
    assert {"retrieval_decision", "retrieval_best_min", "cita_fuente_recuperada", "sin_tool_calls"} <= kinds["GS11"]
    assert ("ruta", "CONSULTAR_POLITICA") in {(c["tipo"], c.get("igual")) for c in criteria("GS11")}
    assert ("stop", "ruta_politica") in {(c["tipo"], c.get("igual")) for c in criteria("GS11")}
    gs12 = {(c["tipo"], c.get("exactamente")) for c in criteria("GS12")}
    assert ("retrieval_count", 0) in gs12 and ("embeddings_count", 0) in gs12
    assert by_id["GS12"]["entrada"][0]["texto"] == "Hola"
    gs13 = {c["tipo"]: c for c in criteria("GS13")}
    assert gs13["retrieval_decision"]["igual"] == "abstener" and gs13["retrieval_decision"]["si_existe"] is True
    assert gs13["llamadas_llm_count"]["max"] == 1
    assert set(gs13["stop_en"]["en"]) == {"rag_abstencion", "ruta_fuera_de_alcance"}
    assert {"respuesta_no_contiene_canarios", "sin_tool_calls"} <= kinds["GS14"]
    assert "prompt de sistema" in by_id["GS14"]["entrada"][0]["texto"]


# -- Arnés ---------------------------------------------------------------------------------------------
class RagAssistant:
    """Asistente falso que deja en la traza lo que dejaría el real: router, embedding y RETRIEVAL."""

    def __init__(self, llm, retrieval=None):
        self.llm, self.retrieval = llm, retrieval

    def handle(self, text, image=None, conversation=None, state=None, tracer=None):
        self.llm.stats.calls += 1
        tracer.record(EventType.ROUTE, {"ruta": "CONSULTAR_POLITICA", "fallback": False})
        tracer.record(EventType.LLM_DECISION, {"status": "ok", "security_scope_id": SECURITY_SCOPE_ID})
        # Un embedding no lleva alcance ni cuenta como llamada de generación.
        tracer.record(EventType.LLM_DECISION, {"status": "ok", "kind": "embedding"})
        tracer.record(EventType.RETRIEVAL, self.retrieval)
        stop = "ruta_politica" if self.retrieval["decision"] == "usar_contexto" else "rag_abstencion"
        return AssistantResult("CONSULTAR_POLITICA", f"Respuesta [{SOURCE} §4. Propinas]", [], stop)


def make_ctx(tmp_path, retrieval=None, rag_ready=True):
    llm = SimpleNamespace(stats=UsageStats(), model="modelo-falso")
    return run_eval.RunContext(
        llm=llm, system_version="v2", run_id="123456", tmp_dir=tmp_path / "tmp",
        trace_dir=tmp_path / "traces", root=ROOT, rag_ready=rag_ready,
        rag_reason="falta REDIS_URL", expected_json={},
        assistant_factory=lambda overrides, tracer: RagAssistant(llm, retrieval),
    )


def gs11(golden_v2):
    return next(c for c in golden_v2["casos"] if c["id"] == "GS11")


def test_run_case_records_retrievals_and_embeddings_and_approves(tmp_path, golden_v2):
    ctx = make_ctx(tmp_path, RETRIEVAL_OK)
    result = run_eval.run_case(gs11(golden_v2), ctx)
    assert result["estado"] == "APROBADO", [c for c in result["criterios"] if not c["ok"]]
    turn_summary = result["turnos"][0]
    assert turn_summary["embeddings"] == 1
    assert turn_summary["llamadas_llm"] == 1  # el embedding no cuenta como generación
    assert turn_summary["recuperaciones"][0]["decision"] == "usar_contexto"
    assert turn_summary["recuperaciones"][0]["fuentes"] == [f"{SOURCE} §4. Propinas"]
    assert result["rag"] is True


def test_run_case_fails_when_the_retrieval_does_not_reach_the_threshold(tmp_path, golden_v2):
    ctx = make_ctx(tmp_path, RETRIEVAL_MISS)
    result = run_eval.run_case(gs11(golden_v2), ctx)
    assert result["estado"] == "FALLIDO"
    failed = {c["tipo"] for c in result["criterios"] if not c["ok"]}
    assert {"retrieval_decision", "retrieval_best_min", "stop"} <= failed


def test_rag_cases_are_pending_without_the_course_redis(tmp_path, golden_v2):
    mini = {"version": "v2", "descripcion": "mini", "casos": [gs11(golden_v2)]}
    doc = run_eval.execute_run(mini, make_ctx(tmp_path, RETRIEVAL_OK, rag_ready=False))
    case = doc["casos"][0]
    assert case["estado"] == "PENDIENTE" and "REDIS_URL" in case["motivo"]
    assert doc["resumen"]["aprobada"] is False
    assert run_eval.exit_code(doc) == run_eval.EXIT_INCOMPLETE


def test_no_rag_marks_rag_cases_omitted_and_the_run_is_not_complete(tmp_path, golden_v2):
    mini = {"version": "v2", "descripcion": "mini", "casos": [gs11(golden_v2)]}
    doc = run_eval.execute_run(mini, make_ctx(tmp_path, RETRIEVAL_OK), no_rag=True)
    assert doc["casos"][0]["estado"] == "OMITIDO" and "--no-rag" in doc["casos"][0]["motivo"]
    assert run_eval.exit_code(doc) == run_eval.EXIT_INCOMPLETE


def test_prepare_rag_only_checks_presence_of_the_variables():
    assert run_eval.prepare_rag({"REDIS_URL": "definida", "REDIS_PREFIX": "definida"}) == (True, "")
    ready, reason = run_eval.prepare_rag({"REDIS_URL": "falta", "REDIS_PREFIX": "definida"})
    assert ready is False and "REDIS_URL" in reason and "REDIS_PREFIX" not in reason


def test_default_golden_is_v2():
    assert run_eval.DEFAULT_GOLDEN.name == "golden_set_v2.json"


def test_main_exits_2_without_gemini_configuration_and_without_network_on_v2(monkeypatch, tmp_path, capsys):
    def boom(*args, **kwargs):
        raise AssertionError("no debe crear el cliente LLM")

    monkeypatch.setattr(run_eval, "LLMClient", boom)
    monkeypatch.setattr(run_eval, "config_status", lambda: {
        name: "falta" for name in ("GEMINI_API_KEY", "LLM_MODEL", "DRIVE_FOLDER_ID", "SHEET_ID",
                                   "GOOGLE_OAUTH_CLIENT_SECRETS", "REDIS_URL", "REDIS_PREFIX")})
    out = tmp_path / "x.json"
    assert run_eval.main(["--golden", str(V2_PATH), "--system-version", "v2", "--out", str(out)]) == 2
    assert not out.exists()
    assert "GEMINI_API_KEY" in capsys.readouterr().out
