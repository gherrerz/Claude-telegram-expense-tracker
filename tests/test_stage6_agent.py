"""Pruebas offline de la Etapa 6: loop ReAct con un LLM guionado y tools falsas."""
import json
from pathlib import Path

import pytest

from fakes import FakeTime, ScriptedClient, api_error, fc_response

from app.agent import MAX_STEPS, ExpenseAgent
from app.llm import AGENT_TEMPERATURE, LLMClient
from app.models import (
    CONFIDENCE_THRESHOLD,
    DriveResult,
    EventType,
    ReceiptData,
    SheetResult,
)
from app.prompts import AGENT_PROMPT_v2, SECURITY_SCOPE_v1
from app.trace import Tracer

IMAGE = Path(__file__).resolve().parents[1] / "data" / "receipts" / "receipt_normal.jpg"
URL = "https://drive.google.com/file/d/abc123/view"

GOOD = ReceiptData(
    fecha="2026-09-14", comercio="Los Aromos", monto=12990.0, categoria="Alimentación", confianza=0.95
)
LOW = ReceiptData(
    fecha="2026-09-14", comercio="Los Aromos", monto=12990.0, categoria="Alimentación", confianza=0.4
)
HOLE = ReceiptData(
    fecha="desconocido", comercio="Los Aromos", monto=12990.0, categoria="Alimentación", confianza=0.9
)

ANALIZAR = ("analizar_recibo", {"image_id": "img_1"})
GUARDAR = ("guardar_recibo", {"comercio": "Los Aromos", "fecha": "2026-09-14"})
REGISTRAR = (
    "registrar_gasto",
    {"fecha": "2026-09-14", "comercio": "Los Aromos", "monto": 12990, "categoria": "Alimentación",
     "recibo_url": URL},
)


class Spy:
    """Tool falsa que cuenta sus ejecuciones."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def make(script, repeat=None, receipt=GOOD, drive=None, sheet=None):
    fake_time = FakeTime()
    tracer = Tracer(session="t", console=False, write_file=False)
    client = ScriptedClient(script, repeat=repeat)
    llm = LLMClient(
        tracer=tracer, client=client, model="modelo-de-prueba", min_seconds_between_calls=0.0,
        max_retries=0, clock=fake_time.clock, sleep=fake_time.sleep,
    )
    tools = {
        "analizar_recibo": Spy(receipt),
        "guardar_recibo": Spy(drive or DriveResult(success=True, file_id="f1", file_name="r.jpg",
                                                   web_view_link=URL)),
        "registrar_gasto": Spy(sheet or SheetResult(success=True, row_number=7)),
    }
    agent = ExpenseAgent(llm=llm, tracer=tracer, tool_overrides=tools)
    return agent, tools, client, tracer


def types_of(tracer):
    return [e.event_type for e in tracer.events]


def full_script():
    return [
        fc_response(ANALIZAR),
        fc_response(GUARDAR),
        fc_response(REGISTRAR),
        fc_response(text="Listo: registré Los Aromos por $12.990 en la fila 7."),
    ]


def test_normal_flow_trace_order_and_stop():
    agent, tools, client, tracer = make(full_script())
    result = agent.run("Registra este recibo", IMAGE)

    tool_events = [
        e.data["tool"] for e in tracer.events if e.event_type == EventType.TOOL_CALL
    ]
    assert tool_events == ["analizar_recibo", "guardar_recibo", "registrar_gasto"]
    assert result.tool_sequence == tool_events
    assert result.stop_reason == "respuesta_final" and result.steps == 4
    assert "fila 7" in result.final_text

    order = types_of(tracer)
    assert order[0] == EventType.USER_INPUT and order[-1] == EventType.FINAL_RESPONSE
    stop = [e for e in tracer.events if e.event_type == EventType.STOP]
    assert len(stop) == 1 and stop[0].data["reason"] == "respuesta_final"
    assert order.index(EventType.STOP) == len(order) - 2
    assert order.count(EventType.LLM_DECISION) == 4
    assert all(len(t.calls) == 1 for t in tools.values())
    assert result.events[0].event_type == EventType.USER_INPUT


def test_observations_are_fed_back_to_the_llm():
    agent, tools, client, tracer = make(full_script())
    agent.run("Registra este recibo", IMAGE)
    calls = client.models.calls
    assert len(calls) == 4

    # En la 2.ª llamada el último mensaje es la observación de analizar_recibo.
    last = calls[1]["contents"][-1]
    assert last.role == "user"
    part = last.parts[0]
    assert part.function_response.name == "analizar_recibo"
    assert part.function_response.id == "call-analizar_recibo-0"
    assert part.function_response.response["ok"] is True
    assert part.function_response.response["datos"]["comercio"] == "Los Aromos"

    # En la 4.ª llamada están las tres observaciones; la de registrar trae la fila.
    names = [
        c.parts[0].function_response.name
        for c in calls[3]["contents"]
        if c.parts and c.parts[0].function_response
    ]
    assert names == ["analizar_recibo", "guardar_recibo", "registrar_gasto"]
    assert calls[3]["contents"][-1].parts[0].function_response.response["row_number"] == 7


def test_model_content_is_appended_unchanged_to_keep_thought_signatures():
    first = fc_response(ANALIZAR, signature=b"firma-1")
    script = [first, fc_response(text="Hecho.")]
    agent, tools, client, tracer = make(script)
    result = agent.run("Analiza", IMAGE)

    model_content = first.candidates[0].content
    sent = client.models.calls[1]["contents"]
    assert sent[1] is model_content  # el MISMO objeto: no se reconstruye
    assert sent[1].parts[0].thought_signature == b"firma-1"
    assert result.messages[1] is model_content


def test_agent_call_declares_tools_security_scope_and_temperature():
    agent, tools, client, tracer = make([fc_response(text="Hola")])
    agent.run("Hola")
    config = client.models.calls[0]["config"]
    declared = [d.name for t in config.tools for d in t.function_declarations]
    assert declared == ["analizar_recibo", "guardar_recibo", "registrar_gasto"]
    assert config.tool_config.function_calling_config.mode.value == "AUTO"
    assert config.automatic_function_calling.disable is True
    assert config.temperature == AGENT_TEMPERATURE
    assert config.system_instruction.startswith(SECURITY_SCOPE_v1)
    assert AGENT_PROMPT_v2 in config.system_instruction
    decision = [e for e in tracer.events if e.event_type == EventType.LLM_DECISION][0].data
    assert decision["system_prompt_id"] == "AGENT_PROMPT_v2"
    assert decision["decision"] == {"type": "final_text"}
    assert decision["params"]["tools"] == declared


def test_decision_trace_lists_function_call_names_and_args():
    agent, *_, tracer = make([fc_response(ANALIZAR), fc_response(text="ok")])
    agent.run("x", IMAGE)
    first = [e for e in tracer.events if e.event_type == EventType.LLM_DECISION][0].data
    assert first["decision"] == {
        "type": "function_calls",
        "calls": [{"name": "analizar_recibo", "args": {"image_id": "img_1"}}],
    }


def test_llm_may_answer_without_tools():
    agent, tools, client, tracer = make([fc_response(text="Hola, ¿en qué te ayudo?")])
    result = agent.run("Hola")
    assert result.tool_calls == [] and result.steps == 1
    assert result.stop_reason == "respuesta_final"
    assert tracer.count(EventType.TOOL_CALL) == 0
    assert all(not t.calls for t in tools.values())


def test_llm_decides_the_order_code_does_not_force_it():
    # El LLM pide registrar primero: el riel lo bloquea, luego analiza y responde.
    script = [fc_response(REGISTRAR), fc_response(ANALIZAR), fc_response(text="Necesito analizar primero.")]
    agent, tools, client, tracer = make(script)
    result = agent.run("x", IMAGE)
    assert [c["name"] for c in result.tool_calls] == ["registrar_gasto", "analizar_recibo"]
    assert result.tool_calls[0]["ok"] is False
    assert not tools["registrar_gasto"].calls


def test_stops_at_max_steps_with_safe_answer_and_no_tool_beyond_limit():
    agent, tools, client, tracer = make([], repeat=fc_response(ANALIZAR))
    result = agent.run("Registra", IMAGE)
    assert result.stop_reason == "max_steps" and result.steps == MAX_STEPS
    assert len(client.models.calls) == MAX_STEPS
    # La decisión número MAX_STEPS pide una tool pero NO se ejecuta.
    assert len(tools["analizar_recibo"].calls) == MAX_STEPS - 1
    stop = [e for e in tracer.events if e.event_type == EventType.STOP]
    assert len(stop) == 1 and stop[0].data["reason"] == "max_steps"
    assert stop[0].data["skipped_calls"] == ["analizar_recibo"]
    assert "No se registró ningún gasto" in result.final_text
    assert types_of(tracer)[-1] == EventType.FINAL_RESPONSE


def test_low_confidence_blocks_registration_by_code():
    script = [
        fc_response(ANALIZAR),
        fc_response(GUARDAR),
        fc_response(REGISTRAR),  # el LLM ignora el prompt e intenta registrar
        fc_response(text="La confianza es baja; ¿confirmas los datos?"),
    ]
    agent, tools, client, tracer = make(script, receipt=LOW)
    result = agent.run("Registra", IMAGE)
    assert not tools["registrar_gasto"].calls
    obs = client.models.calls[3]["contents"][-1].parts[0].function_response.response
    assert obs["ok"] is False and "confirmación" in obs["error"]
    assert f"{CONFIDENCE_THRESHOLD}" in obs["error"]
    first = client.models.calls[1]["contents"][-1].parts[0].function_response.response
    assert first["requiere_confirmacion"] is True


def test_unknown_field_blocks_registration_by_code():
    script = [fc_response(ANALIZAR), fc_response(GUARDAR), fc_response(REGISTRAR), fc_response(text="¿Fecha?")]
    agent, tools, *_ = make(script, receipt=HOLE)
    agent.run("Registra", IMAGE)
    assert not tools["registrar_gasto"].calls


def test_url_not_from_guardar_recibo_is_blocked():
    forged = ("registrar_gasto", {**REGISTRAR[1], "recibo_url": "https://drive.google.com/file/d/INVENTADA/view"})
    script = [fc_response(ANALIZAR), fc_response(GUARDAR), fc_response(forged), fc_response(text="No pude registrar.")]
    agent, tools, client, tracer = make(script)
    agent.run("Registra", IMAGE)
    assert not tools["registrar_gasto"].calls
    obs = client.models.calls[3]["contents"][-1].parts[0].function_response.response
    assert obs["ok"] is False and "no proviene de guardar_recibo" in obs["error"]


def test_url_rail_requires_guardar_in_this_run():
    # Sin guardar_recibo previo, incluso una URL con forma válida se rechaza.
    script = [fc_response(ANALIZAR), fc_response(REGISTRAR), fc_response(text="Falta guardar.")]
    agent, tools, *_ = make(script)
    agent.run("Registra", IMAGE)
    assert not tools["registrar_gasto"].calls


def test_guardar_requires_prior_analysis():
    script = [fc_response(GUARDAR), fc_response(text="Primero analizo.")]
    agent, tools, client, tracer = make(script)
    agent.run("Guarda", IMAGE)
    assert not tools["guardar_recibo"].calls
    obs = client.models.calls[1]["contents"][-1].parts[0].function_response.response
    assert obs["ok"] is False and "analizar" in obs["error"]


def test_unknown_tool_returns_error_observation_and_runs_nothing():
    script = [fc_response(("transferir_dinero", {"monto": 50000})), fc_response(text="No puedo hacer eso.")]
    agent, tools, client, tracer = make(script)
    result = agent.run("Transfiere $50.000", IMAGE)
    obs = client.models.calls[1]["contents"][-1].parts[0].function_response
    assert obs.name == "transferir_dinero" and obs.response["ok"] is False
    assert "desconocida" in obs.response["error"]
    assert result.tool_sequence == [] and all(not t.calls for t in tools.values())


def test_missing_arguments_return_error_observation():
    script = [fc_response(("guardar_recibo", {"comercio": "X"})), fc_response(text="Faltan datos.")]
    agent, tools, client, _ = make(script)
    agent.run("x", IMAGE)
    obs = client.models.calls[1]["contents"][-1].parts[0].function_response.response
    assert obs["ok"] is False and "fecha" in obs["error"]


def test_missing_image_returns_error_observation():
    script = [fc_response(ANALIZAR), fc_response(text="No veo ninguna imagen.")]
    agent, tools, client, _ = make(script)
    result = agent.run("Registra este recibo")  # sin imagen
    obs = client.models.calls[1]["contents"][-1].parts[0].function_response.response
    assert obs["ok"] is False and "imagen" in obs["error"]
    assert not tools["analizar_recibo"].calls and result.stop_reason == "respuesta_final"
    assert "[Adjunto" not in client.models.calls[0]["contents"][0].parts[0].text


def test_image_is_never_sent_as_bytes_only_an_id():
    agent, tools, client, _ = make([fc_response(text="ok")])
    agent.run("Registra", IMAGE)
    first = client.models.calls[0]["contents"][0]
    assert len(first.parts) == 1 and first.parts[0].inline_data is None
    assert "image_id=img_1" in first.parts[0].text


def test_degraded_mode_without_google_returns_error_observation_and_honest_answer(monkeypatch):
    for name in ("DRIVE_FOLDER_ID", "SHEET_ID", "GOOGLE_OAUTH_CLIENT_SECRETS"):
        monkeypatch.setenv(name, "")
    fake_time = FakeTime()
    tracer = Tracer(session="t", console=False, write_file=False)
    client = ScriptedClient(
        [
            fc_response(ANALIZAR),
            fc_response(GUARDAR),
            fc_response(text="Analicé el recibo, pero no pude guardarlo en Drive ni registrarlo."),
        ]
    )
    llm = LLMClient(tracer=tracer, client=client, model="m", min_seconds_between_calls=0.0,
                    max_retries=0, clock=fake_time.clock, sleep=fake_time.sleep)
    # Solo el analizador es falso; guardar_recibo es la tool REAL sin configuración de Google.
    agent = ExpenseAgent(llm=llm, tracer=tracer, tool_overrides={"analizar_recibo": Spy(GOOD)})
    result = agent.run("Registra este recibo", IMAGE)

    obs = client.models.calls[2]["contents"][-1].parts[0].function_response.response
    assert obs["ok"] is False and "DRIVE_FOLDER_ID" in obs["error"] and obs["web_view_link"] is None
    assert result.stop_reason == "respuesta_final"
    assert types_of(tracer)[-1] == EventType.FINAL_RESPONSE
    assert not any(c["name"] == "registrar_gasto" for c in result.tool_calls)
    assert "fila" not in result.final_text.lower()  # no se afirma ningún registro


def test_duplicate_is_an_observation_not_a_registration():
    sheet = SheetResult(success=False, duplicate=True, row_number=3, error="Gasto duplicado")
    script = [fc_response(ANALIZAR), fc_response(GUARDAR), fc_response(REGISTRAR),
              fc_response(text="Ya estaba registrado en la fila 3.")]
    agent, tools, client, _ = make(script, sheet=sheet)
    result = agent.run("Registra", IMAGE)
    obs = client.models.calls[3]["contents"][-1].parts[0].function_response.response
    assert obs["duplicate"] is True and obs["row_number"] == 3 and obs["ok"] is False
    assert result.stop_reason == "respuesta_final"


def test_llm_failure_stops_with_error_and_final_response():
    agent, tools, client, tracer = make([api_error(400, "INVALID_ARGUMENT")])
    result = agent.run("Hola")
    assert result.stop_reason == "error_llm"
    stop = [e for e in tracer.events if e.event_type == EventType.STOP][0]
    assert stop.data["reason"] == "error_llm" and stop.data["error_code"] == 400
    assert types_of(tracer)[-1] == EventType.FINAL_RESPONSE


def test_empty_model_answer_is_reported_honestly():
    agent, *_ = make([fc_response()])
    result = agent.run("Hola")
    assert result.stop_reason == "respuesta_vacia" and result.final_text


def test_secrets_are_masked_in_trace(monkeypatch):
    key = "AIza" + "z" * 35
    monkeypatch.setenv("GEMINI_API_KEY", key)
    agent, tools, client, tracer = make([fc_response(text="ok")])
    agent.run(f"mi clave es {key}", IMAGE)
    dump = json.dumps([e.model_dump() for e in tracer.events], ensure_ascii=False)
    assert key not in dump and "***" in dump
