"""Pruebas offline de la Etapa 7: historial simple reenviado al LLM en cada turno."""
from pathlib import Path

from fakes import FakeTime, ScriptedClient, api_error, fc_response

from app.agent import ExpenseAgent
from app.conversation import Conversation
from app.llm import LLMClient
from app.models import DriveResult, EventType, ReceiptData, SheetResult
from app.prompts import SECURITY_SCOPE_v1
from app.trace import Tracer

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "data" / "receipts" / "receipt_normal.jpg"
URL = "https://drive.google.com/file/d/abc123/view"
GOOD = ReceiptData(
    fecha="2026-09-14", comercio="Los Aromos", monto=12990.0, categoria="Alimentación", confianza=0.95
)


class Spy:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def make(script, repeat=None, max_steps=6):
    fake_time = FakeTime()
    tracer = Tracer(session="t", console=False, write_file=False)
    client = ScriptedClient(script, repeat=repeat)
    llm = LLMClient(
        tracer=tracer, client=client, model="modelo-de-prueba", min_seconds_between_calls=0.0,
        max_retries=0, clock=fake_time.clock, sleep=fake_time.sleep,
    )
    tools = {
        "analizar_recibo": Spy(GOOD),
        "guardar_recibo": Spy(DriveResult(success=True, file_id="f1", file_name="r.jpg",
                                          web_view_link=URL)),
        "registrar_gasto": Spy(SheetResult(success=True, row_number=7)),
    }
    agent = ExpenseAgent(llm=llm, tracer=tracer, tool_overrides=tools, max_steps=max_steps)
    return agent, client, tracer, tools


def texts(contents):
    """Todo el texto de una lista de `Content`, para buscar datos en lo enviado al LLM."""
    return " ".join(
        part.text for content in contents for part in (content.parts or []) if part.text
    )


def kinds(contents):
    """Forma de cada mensaje: `rol:texto|call|resp`."""
    out = []
    for content in contents:
        part = content.parts[0]
        kind = "call" if part.function_call else "resp" if part.function_response else "texto"
        out.append(f"{content.role}:{kind}")
    return out


def two_turn_script():
    return [
        fc_response(text="Mucho gusto, Diego. ¿En qué te ayudo?"),
        fc_response(("analizar_recibo", {"image_id": "img_1"})),
        fc_response(text="Listo, Diego: analicé el recibo."),
    ]


def test_turn_2_request_contains_turn_1_user_text_and_model_reply():
    agent, client, tracer, _ = make(two_turn_script())
    conversation = Conversation()
    agent.run("Me llamo Diego", conversation=conversation)
    agent.run("Registra este recibo", IMAGE, conversation=conversation)

    second_turn_first_call = client.models.calls[1]["contents"]
    assert [c.role for c in second_turn_first_call] == ["user", "model", "user"]
    assert "Me llamo Diego" in second_turn_first_call[0].parts[0].text
    assert "Diego" in second_turn_first_call[1].parts[0].text  # respuesta del modelo del turno 1
    assert "Registra este recibo" in second_turn_first_call[2].parts[0].text


def test_negative_without_conversation_turn_1_text_is_absent():
    agent, client, tracer, _ = make(two_turn_script()[1:])
    agent.run("Registra este recibo", IMAGE)  # mismo turno 2, pero sin historial
    for call in client.models.calls:
        assert "Diego" not in texts(call["contents"])
    assert len(client.models.calls[0]["contents"]) == 1


def test_history_grows_across_three_turns_keeping_call_response_order():
    script = [
        fc_response(text="Hola Diego."),
        fc_response(("analizar_recibo", {"image_id": "img_1"})),
        fc_response(text="Analizado."),
        fc_response(text="De nada."),
    ]
    agent, client, tracer, tools = make(script)
    conversation = Conversation()

    agent.run("Me llamo Diego", conversation=conversation)
    assert kinds(conversation.contents) == ["user:texto", "model:texto"]

    agent.run("Analiza este recibo", IMAGE, conversation=conversation)
    assert kinds(conversation.contents) == [
        "user:texto", "model:texto",
        "user:texto", "model:call", "user:resp", "model:texto",
    ]
    assert len(tools["analizar_recibo"].calls) == 1

    agent.run("Gracias", conversation=conversation)
    assert len(conversation) == 8
    # Cada llamada al LLM recibió todo lo acumulado hasta ese punto.
    assert [len(c["contents"]) for c in client.models.calls] == [1, 3, 5, 7]
    assert conversation.turn == 3


def test_model_content_identity_is_preserved_across_turns():
    agent, client, tracer, _ = make(two_turn_script())
    conversation = Conversation()
    agent.run("Me llamo Diego", conversation=conversation)
    turn_1_model = conversation.contents[1]
    agent.run("Registra este recibo", IMAGE, conversation=conversation)

    assert client.models.calls[1]["contents"][1] is turn_1_model
    assert conversation.contents[1] is turn_1_model


def test_function_call_signature_survives_into_next_turn():
    script = [
        fc_response(("analizar_recibo", {"image_id": "img_1"}), signature=b"firma-t1"),
        fc_response(text="Listo."),
        fc_response(text="Aquí sigo."),
    ]
    agent, client, tracer, _ = make(script)
    conversation = Conversation()
    agent.run("Analiza", IMAGE, conversation=conversation)
    agent.run("¿Sigues ahí?", conversation=conversation)
    sent = client.models.calls[2]["contents"]
    assert sent[1].parts[0].thought_signature == b"firma-t1"
    assert sent[2].parts[0].function_response.name == "analizar_recibo"


def test_trace_shows_history_message_counts():
    agent, client, tracer, _ = make(two_turn_script())
    conversation = Conversation()
    agent.run("Me llamo Diego", conversation=conversation)
    agent.run("Registra este recibo", IMAGE, conversation=conversation)

    user_inputs = [e.data for e in tracer.events if e.event_type == EventType.USER_INPUT]
    assert [(u["turn"], u["history_messages"]) for u in user_inputs] == [(1, 0), (2, 2)]
    decisions = [
        e.data for e in tracer.events
        if e.event_type == EventType.LLM_DECISION and e.data["kind"] == "tools"
    ]
    assert [d["history_messages"] for d in decisions] == [1, 3, 5]
    assert tracer.count(EventType.MEMORY_UPDATE) == 0  # reservado para la Etapa 10


def test_system_instruction_is_sent_each_call_but_not_stored_in_history():
    agent, client, tracer, _ = make(two_turn_script())
    conversation = Conversation()
    agent.run("Me llamo Diego", conversation=conversation)
    agent.run("Registra este recibo", IMAGE, conversation=conversation)

    for call in client.models.calls:
        assert call["config"].system_instruction.startswith(SECURITY_SCOPE_v1)
    assert {c.role for c in conversation.contents} <= {"user", "model"}
    assert "SECURITY_SCOPE" not in texts(conversation.contents)


def test_without_conversation_each_run_is_independent_single_turn():
    agent, client, tracer, _ = make([fc_response(text="uno"), fc_response(text="dos")])
    first = agent.run("Me llamo Diego")
    second = agent.run("¿Cómo me llamo?")
    assert len(first.messages) == 2 and len(client.models.calls[1]["contents"]) == 1
    assert "Diego" not in texts(client.models.calls[1]["contents"])


def test_name_is_not_hardcoded_in_app_source():
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "app").rglob("*.py")
        if "diego" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []


def test_max_steps_stop_commits_turn_with_safe_message_and_alternating_roles():
    agent, client, tracer, _ = make([], repeat=fc_response(("analizar_recibo", {"image_id": "img_1"})),
                                    max_steps=2)
    conversation = Conversation()
    result = agent.run("Analiza", IMAGE, conversation=conversation)
    assert result.stop_reason == "max_steps"
    # La llamada a tool no ejecutada de la decisión 2 no entra al historial.
    assert kinds(conversation.contents) == ["user:texto", "model:call", "user:resp", "model:texto"]
    assert conversation.contents[-1].parts[0].text == result.final_text


def test_llm_error_stop_keeps_user_message_and_adds_safe_reply():
    agent, client, tracer, _ = make([api_error(400, "INVALID_ARGUMENT"), fc_response(text="Hola de nuevo.")])
    conversation = Conversation()
    result = agent.run("Me llamo Diego", conversation=conversation)
    assert result.stop_reason == "error_llm"
    assert kinds(conversation.contents) == ["user:texto", "model:texto"]

    agent.run("Hola", conversation=conversation)
    sent = client.models.calls[1]["contents"]
    assert "Me llamo Diego" in sent[0].parts[0].text and len(sent) == 3


def test_empty_model_response_is_not_stored_but_safe_reply_is():
    from google.genai import types

    empty = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[]))]
    )
    agent, client, tracer, _ = make([empty])
    conversation = Conversation()
    result = agent.run("Hola", conversation=conversation)
    assert result.stop_reason == "respuesta_vacia"
    assert kinds(conversation.contents) == ["user:texto", "model:texto"]
    assert conversation.contents[1].parts[0].text == result.final_text


def test_image_ids_are_per_conversation_and_rails_stay_per_run():
    script = [
        fc_response(("analizar_recibo", {"image_id": "img_1"})),
        fc_response(text="ok 1"),
        fc_response(("analizar_recibo", {"image_id": "img_1"})),  # id viejo en el turno 2
        fc_response(("analizar_recibo", {"image_id": "img_2"})),
        fc_response(text="ok 2"),
    ]
    agent, client, tracer, tools = make(script)
    conversation = Conversation()
    agent.run("Analiza", IMAGE, conversation=conversation)
    agent.run("Analiza otro", IMAGE, conversation=conversation)

    assert list(conversation.images) == ["img_1", "img_2"]
    assert "image_id=img_2" in conversation.contents[4].parts[0].text
    results = [
        e.data["result"] for e in tracer.events if e.event_type == EventType.TOOL_RESULT
    ]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False and "img_2" in results[1]["error"]
    assert results[2]["ok"] is True
    assert len(tools["analizar_recibo"].calls) == 2


def test_summary_is_readable_and_has_no_secrets_or_bytes():
    agent, client, tracer, _ = make(two_turn_script())
    conversation = Conversation()
    agent.run("Me llamo Diego", conversation=conversation)
    agent.run("Registra este recibo", IMAGE, conversation=conversation)
    lines = conversation.summary()
    assert lines[0] == "1. user: Me llamo Diego"
    assert lines[1].startswith("2. model: Mucho gusto, Diego")
    assert any("[llamada a analizar_recibo]" in line for line in lines)
    assert any("[resultado de analizar_recibo]" in line for line in lines)
    assert not any("datos" in line or "Los Aromos" in line for line in lines)


def test_summary_masks_secrets_in_text():
    conversation = Conversation()
    agent, client, tracer, _ = make([fc_response(text="ok")])
    key = "AIza" + "x" * 35
    agent.run(f"mi clave es {key}", conversation=conversation)
    assert key not in " ".join(conversation.summary())
