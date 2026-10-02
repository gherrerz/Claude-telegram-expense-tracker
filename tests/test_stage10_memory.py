"""Pruebas offline de la Etapa 10: memoria avanzada (LLM guionado y tools falsas, sin red).

Cubren: las funciones de `app/memory.py` y sus eventos `MEMORY_UPDATE`, el ciclo completo por
`ExpenseAssistant` (estado inicial -> registro -> consulta desde el estado -> duplicado -> confirmación
en un turno posterior), la regla de turno de la confirmación, la baja confianza, el duplicado que
reporta la planilla, el nombre desde CONVERSACION y `permitir_duplicado` en Sheets.
"""
import json
from pathlib import Path

import pytest
from fakes import FakeSheetsService, FakeTime, ScriptedClient, fc_response, ok_response

from app.agent import AGENT_PROMPT_ID, build_tool_declarations
from app.assistant import (
    CHAT_JSON_SCHEMA,
    EMPTY_ANSWER_TEXT,
    ExpenseAssistant,
    build_query_message,
)
from app.config import load_settings
from app.conversation import Conversation
from app.llm import LLMClient
from app.memory import (
    NO_IMAGE_HASH,
    clear_pending_confirmation,
    existing_row,
    image_hash,
    is_duplicate,
    receipt_key,
    record_expense,
    set_pending_confirmation,
    set_user_name,
    state_snapshot,
    total_general,
    valid_user_name,
)
from app.memory_demo import counting_tools, run_memory_cycle
from app.models import (
    MAX_RECENT_EXPENSES,
    AgentState,
    DriveResult,
    EventType,
    ReceiptData,
    SheetResult,
)
from app.prompts import PROMPTS
from app.router import (
    CONSULTAR_GASTOS,
    CONVERSACION,
    FUERA_DE_ALCANCE,
    REGISTRAR_RECIBO,
    build_router_input,
)
from app.tools.sheets import registrar_gasto
from app.trace import Tracer

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "data" / "receipts" / "receipt_normal.jpg"
IMAGE_OTHER = ROOT / "data" / "receipts" / "receipt_hard.jpg"
URL = "https://drive.google.com/file/d/abc123/view"

SUPER = ReceiptData(
    fecha="2026-09-14", comercio="Los Aromos", monto=45990.0, categoria="Supermercado", confianza=0.95
)
LOW = ReceiptData(
    fecha="2026-09-14", comercio="Los Aromos", monto=12990.0, categoria="Alimentación", confianza=0.4
)

ANALIZAR_1 = ("analizar_recibo", {"image_id": "img_1"})
ANALIZAR_2 = ("analizar_recibo", {"image_id": "img_2"})
GUARDAR = ("guardar_recibo", {"comercio": "Los Aromos", "fecha": "2026-09-14"})
GUARDAR_OK = ("guardar_recibo", {**GUARDAR[1], "confirmado_por_usuario": True})
_REG = {"fecha": "2026-09-14", "comercio": "Los Aromos", "monto": 45990, "categoria": "Supermercado",
        "recibo_url": URL}
REGISTRAR = ("registrar_gasto", _REG)
REGISTRAR_OK = ("registrar_gasto", {**_REG, "confirmado_por_usuario": True})
_REG_LOW = {**_REG, "monto": 12990, "categoria": "Alimentación"}
REGISTRAR_LOW = ("registrar_gasto", _REG_LOW)
REGISTRAR_LOW_OK = ("registrar_gasto", {**_REG_LOW, "confirmado_por_usuario": True})


class Spy:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class SheetSpy:
    """`registrar_gasto` falso: filas consecutivas desde 7 o resultados guionados."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.results:
            return self.results.pop(0)
        return SheetResult(success=True, row_number=6 + len(self.calls))


def route_json(ruta, motivo="motivo de prueba"):
    return ok_response(json.dumps({"ruta": ruta, "motivo": motivo}))


def chat_json(respuesta, nombre=""):
    return ok_response(json.dumps({"respuesta": respuesta, "nombre_usuario": nombre}))


class Harness:
    """Asistente con LLM guionado, una conversación y un estado, para encadenar turnos."""

    def __init__(self, script, receipt=SUPER, registrar=None, counted=False):
        fake_time = FakeTime()
        self.tracer = Tracer(session="t", console=False, write_file=False)
        self.client = ScriptedClient(script)
        self.llm = LLMClient(
            tracer=self.tracer, client=self.client, model="modelo-de-prueba",
            min_seconds_between_calls=0.0, max_retries=0, clock=fake_time.clock,
            sleep=fake_time.sleep,
        )
        self.analizar = Spy(receipt)
        self.guardar = Spy(DriveResult(success=True, file_id="f1", file_name="r.jpg",
                                       web_view_link=URL))
        self.registrar = registrar or SheetSpy()
        self.counts = None
        if counted:
            tools, self.counts = counting_tools(self.guardar, self.registrar,
                                                {"analizar_recibo": self.analizar})
        else:
            tools = {"analizar_recibo": self.analizar, "guardar_recibo": self.guardar,
                     "registrar_gasto": self.registrar}
        self.assistant = ExpenseAssistant(llm=self.llm, tracer=self.tracer, tool_overrides=tools)
        self.conversation = Conversation()
        self.state = AgentState()

    def say(self, text, image=None):
        calls_before = len(self.client.models.calls)
        events_before = len(self.tracer.events)
        result = self.assistant.handle(text, image, conversation=self.conversation, state=self.state)
        self.last_calls = self.client.models.calls[calls_before:]
        self.last_events = self.tracer.events[events_before:]
        return result

    def events(self, kind):
        return [e.data for e in self.last_events if e.event_type == kind]

    def memory_ops(self):
        return [e["operacion"] for e in self.events(EventType.MEMORY_UPDATE)]

    def results(self, tool):
        return [e["result"] for e in self.events(EventType.TOOL_RESULT) if e["tool"] == tool]


def request_text(call):
    return "".join(p.text for c in call["contents"] for p in (c.parts or []) if p.text)


def cycle_script():
    return [
        route_json(CONVERSACION), chat_json("Hola Ana, ¿en qué te ayudo?", "Ana"),
        route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_1), fc_response(GUARDAR),
        fc_response(REGISTRAR), fc_response(text="Registré Los Aromos por $45.990 en la fila 7, Ana."),
        route_json(CONSULTAR_GASTOS), ok_response("Ana, llevas $45.990 en Supermercado."),
        route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_2), fc_response(GUARDAR),
        fc_response(REGISTRAR), fc_response(GUARDAR_OK),
        fc_response(text="Este recibo ya fue registrado en la fila 7. ¿Quieres que lo registre de "
                         "nuevo de todas formas?"),
        route_json(REGISTRAR_RECIBO), fc_response(GUARDAR_OK), fc_response(REGISTRAR_OK),
        fc_response(text="Listo, Ana: registré el gasto de nuevo en la fila 8."),
    ]


# -- app/memory.py: funciones ----------------------------------------------------------------------
def test_receipt_key_is_stable_and_normalized_and_depends_on_image_and_fields():
    data = IMAGE.read_bytes()
    key = receipt_key(data, "Los Aromos", "2026-09-14", 45990.0)
    assert key == receipt_key(data, "  los   AROMOS ", "2026-09-14", 45990)  # normaliza comercio y monto
    assert key.startswith(image_hash(data) + "-")
    assert key != receipt_key(data, "Los Aromos", "2026-09-14", 45991.0)
    assert key != receipt_key(data, "Los Aromos", "2026-09-15", 45990.0)
    assert key != receipt_key(IMAGE_OTHER.read_bytes(), "Los Aromos", "2026-09-14", 45990.0)
    assert receipt_key(data, "x", "desconocido", "desconocido")  # los campos ilegibles no rompen


def test_record_expense_sums_totals_caps_recent_expenses_and_emits_memory_update():
    state = AgentState()
    tracer = Tracer(session="t", console=False, write_file=False)
    amounts = [1000.0, 2500.5, 300.0, 400.0, 500.0, 600.0, 700.0]
    for index, amount in enumerate(amounts):
        category = "Supermercado" if index % 2 == 0 else "Transporte"
        receipt = ReceiptData(fecha="2026-09-14", comercio=f"Comercio {index}", monto=amount,
                              categoria=category, confianza=0.9)
        record_expense(state, receipt, f"hash{index}", 10 + index, tracer=tracer)

    assert state.totales_por_categoria == {
        "Supermercado": 1000.0 + 300.0 + 500.0 + 700.0,
        "Transporte": 2500.5 + 400.0 + 600.0,
    }
    assert total_general(state) == sum(amounts)
    assert len(state.ultimos_gastos) == MAX_RECENT_EXPENSES
    assert [g["comercio"] for g in state.ultimos_gastos] == [f"Comercio {i}" for i in range(2, 7)]
    assert state.ultimos_gastos[-1]["fila"] == 16  # el más reciente va al final
    assert len(state.recibos_registrados) == 7

    events = [e.data for e in tracer.events if e.event_type == EventType.MEMORY_UPDATE]
    assert len(events) == 7 and {e["operacion"] for e in events} == {"record_expense"}
    first, last = events[0], events[-1]
    assert set(first) == {"operacion", "antes", "despues", "motivo"} and first["motivo"]
    assert first["antes"]["total_categoria"] == 0.0 and first["despues"]["total_categoria"] == 1000.0
    assert first["antes"]["n_recibos_registrados"] == 0 and first["despues"]["n_recibos_registrados"] == 1
    assert last["antes"]["total_categoria"] == 1800.0 and last["despues"]["total_categoria"] == 2500.0
    assert last["despues"]["ultimo_gasto"]["comercio"] == "Comercio 6"


def test_record_expense_rejects_unusable_data_without_touching_the_state():
    state = AgentState()
    unknown = ReceiptData(fecha="2026-09-14", comercio="X", monto="desconocido",
                          categoria="Hogar", confianza=0.9)
    with pytest.raises(ValueError):
        record_expense(state, unknown, "h", 3)
    no_category = ReceiptData(fecha="2026-09-14", comercio="X", monto=10.0,
                              categoria="desconocido", confianza=0.9)
    with pytest.raises(ValueError):
        record_expense(state, no_category, "h", 3)
    assert state == AgentState()


def test_is_duplicate_by_exact_key_or_same_image_and_row_lookup():
    state = AgentState()
    data = IMAGE.read_bytes()
    receipt = ReceiptData(fecha="2026-09-14", comercio="Los Aromos", monto=45990.0,
                          categoria="Supermercado", confianza=0.9)
    key = receipt_key(data, "Los Aromos", "2026-09-14", 45990.0)
    assert not is_duplicate(state, key) and existing_row(state, key) is None
    record_expense(state, receipt, image_hash(data), 7)
    assert is_duplicate(state, key) and existing_row(state, key) == 7
    # La misma imagen con un campo leído distinto sigue siendo el mismo recibo.
    assert is_duplicate(state, receipt_key(data, "Los Aromos S.A.", "2026-09-14", 45990.0))
    # Otra imagen con los mismos campos NO la detecta la memoria (lo hace la planilla, Etapa 5).
    assert not is_duplicate(state, receipt_key(IMAGE_OTHER.read_bytes(), "Los Aromos", "2026-09-14", 45990.0))
    # Sin hash de imagen solo cuenta la huella exacta.
    assert not is_duplicate(state, f"{NO_IMAGE_HASH}-abc")


def test_confirmed_duplicate_adds_the_expense_but_keeps_one_receipt_key_and_first_row():
    state = AgentState()
    receipt = ReceiptData(fecha="2026-09-14", comercio="Los Aromos", monto=100.0,
                          categoria="Hogar", confianza=0.9)
    record_expense(state, receipt, "h1", 7)
    record_expense(state, receipt, "h1", 8)
    assert state.totales_por_categoria == {"Hogar": 200.0}
    assert len(state.ultimos_gastos) == 2 and len(state.recibos_registrados) == 1
    assert list(state.filas_por_recibo.values()) == [7]


def test_set_user_name_cleans_emits_once_and_ignores_unchanged_or_empty():
    state = AgentState()
    tracer = Tracer(session="t", console=False, write_file=False)
    assert set_user_name(state, "  Ana   María ", tracer=tracer) is True
    assert state.nombre_usuario == "Ana María"
    assert set_user_name(state, "Ana María", tracer=tracer) is False
    assert set_user_name(state, "   ", tracer=tracer) is False
    events = [e.data for e in tracer.events if e.event_type == EventType.MEMORY_UPDATE]
    assert len(events) == 1
    assert events[0]["operacion"] == "set_user_name"
    assert events[0]["antes"] == {"nombre_usuario": None}
    assert events[0]["despues"] == {"nombre_usuario": "Ana María"}


def test_valid_user_name_requires_letters_and_presence_in_the_user_text():
    assert valid_user_name("Ana", "Me llamo Ana") == "Ana"
    assert valid_user_name("ana", "Me llamo Ana") == "ana"
    assert valid_user_name("Pedro", "Hola") is None  # no aparece en el mensaje
    assert valid_user_name("Ana<script>", "Me llamo Ana<script>") is None
    assert valid_user_name("123", "soy 123") is None
    assert valid_user_name("A" * 41, "A" * 41) is None
    assert valid_user_name(None, "Hola") is None


def test_pending_confirmation_set_keep_and_clear_emit_events():
    state = AgentState()
    tracer = Tracer(session="t", console=False, write_file=False)
    pending = set_pending_confirmation(
        state, "duplicado", "h1-abc", {"comercio": "Los Aromos", "monto": 10.0}, 3,
        imagen=str(IMAGE), imagen_id="img_2", imagen_hash="h1", fila_existente=7, tracer=tracer,
    )
    assert state.confirmacion_pendiente is pending and pending.turno == 3
    # Reafirmar la misma pendiente (otro turno) conserva el turno original: no la rejuvenece.
    again = set_pending_confirmation(state, "duplicado", "h1-zzz", {}, 9, tracer=tracer)
    assert again is pending and again.turno == 3
    # Un tipo distinto sí la reemplaza.
    replaced = set_pending_confirmation(state, "baja_confianza", "h1-abc", {}, 9, tracer=tracer)
    assert replaced.turno == 9 and replaced.tipo == "baja_confianza"
    assert clear_pending_confirmation(state, tracer=tracer) is True
    assert clear_pending_confirmation(state, tracer=tracer) is False
    assert state.confirmacion_pendiente is None
    events = [e.data for e in tracer.events if e.event_type == EventType.MEMORY_UPDATE]
    assert [e["operacion"] for e in events] == [
        "set_pending_confirmation", "set_pending_confirmation", "clear_pending_confirmation"]
    assert events[0]["antes"] == {"confirmacion_pendiente": None}
    assert events[0]["despues"]["confirmacion_pendiente"]["tipo"] == "duplicado"
    assert events[2]["despues"] == {"confirmacion_pendiente": None}


def test_state_snapshot_and_json_never_expose_image_bytes_or_paths():
    state = AgentState()
    set_pending_confirmation(state, "duplicado", "h1-abc", {"comercio": "X"}, 2,
                             imagen=str(IMAGE), imagen_id="img_1", imagen_hash="h1")
    snapshot = json.dumps(state_snapshot(state), ensure_ascii=False)
    assert "receipt_normal" not in snapshot and "Users" not in snapshot
    assert "receipt_normal" not in state.model_dump_json()  # la ruta no se serializa hacia el LLM
    assert state.confirmacion_pendiente.imagen == str(IMAGE)  # pero el código sí la conserva
    assert json.loads(snapshot)["confirmacion_pendiente"]["tipo"] == "duplicado"


# -- Ciclo completo por el asistente ----------------------------------------------------------------
def test_full_cycle_initial_state_update_use_duplicate_and_next_turn_confirmation():
    h = Harness(cycle_script())

    # Estado inicial vacío; la memoria no es el historial.
    assert h.state == AgentState() and state_snapshot(h.state)["total_general"] == 0

    # 1) nombre desde CONVERSACION (salida estructurada)
    result = h.say("Me llamo Ana")
    assert result.route == CONVERSACION and result.state is h.state
    assert h.state.nombre_usuario == "Ana" and h.memory_ops() == ["set_user_name"]

    # 2) registro: el código actualiza el estado a partir de la escritura observada
    result = h.say("Registra este recibo", IMAGE)
    assert result.route == REGISTRAR_RECIBO and "fila 7" in result.final_text
    assert h.memory_ops() == ["record_expense"]
    update = h.events(EventType.MEMORY_UPDATE)[0]
    assert update["antes"]["total_categoria"] == 0.0 and update["despues"]["total_categoria"] == 45990.0
    assert update["despues"]["ultimo_gasto"]["fila"] == 7
    assert h.state.totales_por_categoria == {"Supermercado": 45990.0}
    assert len(h.state.recibos_registrados) == 1 and h.state.confirmacion_pendiente is None
    assert len(h.guardar.calls) == 1 and len(h.registrar.calls) == 1

    # 3) uso 1: la consulta se responde con cifras del estado, calculadas por código
    result = h.say("¿Cuánto llevo gastado en Supermercado?")
    assert result.route == CONSULTAR_GASTOS and result.tool_calls == []
    query = h.last_calls[-1]
    assert query["config"].system_instruction.endswith(PROMPTS["QUERY_PROMPT_v2"])
    sent = request_text(query)
    assert '"Supermercado":45990.0' in sent and '"nombre_usuario":"Ana"' in sent
    assert "<total_general_clp>45990</total_general_clp>" in sent
    assert "receipt_normal" not in sent  # el estado enviado al LLM no lleva rutas

    # 4) uso 2: el mismo recibo se detecta como duplicado y NO se ejecuta guardar ni registrar
    result = h.say("Registra este recibo", IMAGE)
    assert result.route == REGISTRAR_RECIBO
    analysis = h.results("analizar_recibo")[0]
    assert analysis["posible_duplicado"] is True and analysis["fila_existente"] == 7
    assert analysis["requiere_confirmacion"] is True
    assert analysis["motivo"].startswith(
        "posible_duplicado: este recibo ya fue registrado en la fila 7; pide confirmación al usuario "
        "antes de registrarlo de nuevo")
    blocked_save, same_turn = h.results("guardar_recibo")
    assert blocked_save["ok"] is False and "posible_duplicado" in blocked_save["error"]
    assert h.results("registrar_gasto")[0]["ok"] is False
    # Confirmar en el MISMO turno en que se pidió la confirmación se rechaza.
    assert same_turn["ok"] is False and "mismo mensaje" in same_turn["error"]
    assert len(h.guardar.calls) == 1 and len(h.registrar.calls) == 1  # nada nuevo en Drive ni en Sheets
    assert h.state.totales_por_categoria == {"Supermercado": 45990.0}
    pending = h.state.confirmacion_pendiente
    assert pending.tipo == "duplicado" and pending.turno == h.conversation.turn == 4
    assert pending.fila_existente == 7 and pending.imagen_id == "img_2"
    assert "set_pending_confirmation" in h.memory_ops()
    assert "fila 7" in result.final_text

    # 5) turno posterior: confirmación solo con texto; el router recibe la pendiente como contexto
    result = h.say("Sí, regístralo de todas formas")
    router_call, agent_call = h.last_calls[0], h.last_calls[1]
    assert "<confirmacion_pendiente>duplicado</confirmacion_pendiente>" in "".join(router_call["contents"])
    assert result.route == REGISTRAR_RECIBO and "fila 8" in result.final_text
    first_user_text = request_text({"contents": [agent_call["contents"][-1]]})
    assert "<confirmacion_pendiente>" in first_user_text and "image_id=img_2" in first_user_text
    assert len(h.analizar.calls) == 2  # no se volvió a analizar: se restauró el análisis pendiente
    assert len(h.guardar.calls) == 2 and len(h.registrar.calls) == 2
    assert "permitir_duplicado" not in h.registrar.calls[0]
    assert h.registrar.calls[1]["permitir_duplicado"] is True
    assert h.state.totales_por_categoria == {"Supermercado": 91980.0}
    assert len(h.state.ultimos_gastos) == 2 and len(h.state.recibos_registrados) == 1
    assert h.state.confirmacion_pendiente is None
    assert h.memory_ops() == ["record_expense", "clear_pending_confirmation"]


def test_run_memory_cycle_evaluates_the_same_scripted_cycle_as_ok():
    h = Harness(cycle_script(), counted=True)
    steps = []
    report = run_memory_cycle(
        h.assistant, h.counts, IMAGE, 45990.0, h.tracer, conversation=h.conversation, state=h.state,
        row_count=lambda: len(h.registrar.calls), on_step=steps.append,
    )
    assert report.initial_state["total_general"] == 0
    assert [s.id for s in steps] == ["1", "2", "3", "4", "5"] and len(report.steps) == 5
    failed = {s.id: [n for n, ok in s.checks.items() if not ok] for s in report.steps if not s.ok}
    assert report.ok, failed
    assert report.steps[3].tool_runs == {"guardar_recibo": 0, "registrar_gasto": 0}
    assert report.steps[4].tool_runs == {"guardar_recibo": 1, "registrar_gasto": 1}


def test_run_memory_cycle_flags_a_wrong_expected_total():
    wrong = Harness(cycle_script(), counted=True)
    report = run_memory_cycle(wrong.assistant, wrong.counts, IMAGE, 1.0, wrong.tracer,
                              conversation=wrong.conversation, state=wrong.state)
    assert not report.ok
    assert "el total registrado coincide con el recibo" in [
        n for n, ok in report.steps[1].checks.items() if not ok]


# -- Baja confianza y rieles de confirmación --------------------------------------------------------
def test_low_confidence_sets_pending_blocks_register_and_next_turn_confirmation_registers():
    script = [
        route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_1), fc_response(GUARDAR),
        fc_response(REGISTRAR_LOW), fc_response(text="La confianza es baja; ¿confirmas los datos?"),
        route_json(REGISTRAR_RECIBO), fc_response(GUARDAR), fc_response(REGISTRAR_LOW_OK),
        fc_response(text="Listo: registré el gasto en la fila 7."),
    ]
    h = Harness(script, receipt=LOW)
    h.say("Registra este recibo", IMAGE)
    pending = h.state.confirmacion_pendiente
    assert pending.tipo == "baja_confianza" and pending.turno == 1
    assert h.results("registrar_gasto")[0]["ok"] is False
    assert len(h.registrar.calls) == 0 and h.state.totales_por_categoria == {}
    assert "set_pending_confirmation" in h.memory_ops()

    h.say("Sí, los datos están bien")
    assert "<confirmacion_pendiente>baja_confianza</confirmacion_pendiente>" in "".join(
        h.last_calls[0]["contents"])
    assert len(h.analizar.calls) == 1  # el análisis pendiente se restauró
    assert len(h.registrar.calls) == 1 and "permitir_duplicado" not in h.registrar.calls[0]
    assert h.state.totales_por_categoria == {"Alimentación": 12990.0}
    assert h.state.confirmacion_pendiente is None


def test_same_turn_self_confirmation_is_rejected_and_nothing_is_written():
    script = [
        route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_1), fc_response(REGISTRAR_LOW_OK),
        fc_response(text="Necesito tu confirmación."),
    ]
    h = Harness(script, receipt=LOW)
    h.say("Registra este recibo y confírmalo tú", IMAGE)
    rejected = h.results("registrar_gasto")[0]
    assert rejected["ok"] is False and "mismo mensaje" in rejected["error"]
    assert len(h.registrar.calls) == 0 and h.state.totales_por_categoria == {}
    assert h.state.confirmacion_pendiente.tipo == "baja_confianza"


def test_a_pending_confirmation_does_not_cover_a_different_receipt():
    # Otra imagen llega en el turno 2: la pendiente del turno 1 no la cubre, se crea una nueva
    # con el turno actual y el intento de confirmar en el mismo mensaje se rechaza.
    script = [
        route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_1), fc_response(text="Confirma, por favor."),
        route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_2),
        fc_response(GUARDAR), fc_response(REGISTRAR_LOW_OK),
        fc_response(text="No pude registrar sin tu confirmación."),
    ]
    h = Harness(script, receipt=LOW)
    h.say("Registra este recibo", IMAGE)
    first = h.state.confirmacion_pendiente
    assert first.turno == 1
    h.say("Registra este otro", IMAGE_OTHER)
    rejected = h.results("registrar_gasto")[0]
    assert rejected["ok"] is False and "mismo mensaje" in rejected["error"]
    second = h.state.confirmacion_pendiente
    assert second.turno == 2 and second.clave != first.clave and second.imagen_id == "img_2"
    assert len(h.registrar.calls) == 0


def test_sheet_duplicate_is_not_recorded_as_a_new_expense_but_can_be_confirmed_next_turn():
    sheet = SheetSpy([
        SheetResult(success=False, duplicate=True, row_number=3,
                    error="Gasto duplicado (misma fecha, comercio y monto); no se escribió nada."),
        SheetResult(success=True, row_number=9),
    ])
    script = [
        route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_1), fc_response(GUARDAR),
        fc_response(REGISTRAR), fc_response(text="Ya existe en la fila 3; ¿lo registro igual?"),
        route_json(REGISTRAR_RECIBO), fc_response(GUARDAR_OK), fc_response(REGISTRAR_OK),
        fc_response(text="Listo, registrado en la fila 9."),
    ]
    h = Harness(script, registrar=sheet)
    h.say("Registra este recibo", IMAGE)
    observation = h.results("registrar_gasto")[0]
    assert observation["duplicate"] is True and observation["row_number"] == 3
    assert h.state.totales_por_categoria == {} and h.state.recibos_registrados == []
    assert h.state.ultimos_gastos == []  # NO se registra como gasto nuevo
    pending = h.state.confirmacion_pendiente
    assert pending.tipo == "duplicado" and pending.fila_existente == 3

    h.say("Sí, regístralo igual")
    assert h.registrar.calls[1]["permitir_duplicado"] is True
    assert h.state.totales_por_categoria == {"Supermercado": 45990.0}
    assert h.state.confirmacion_pendiente is None


def test_agent_without_state_keeps_the_previous_behaviour():
    script = [route_json(REGISTRAR_RECIBO), fc_response(ANALIZAR_1), fc_response(GUARDAR),
              fc_response(REGISTRAR_LOW_OK), fc_response(text="Necesito tu confirmación.")]
    h = Harness(script, receipt=LOW)
    from app.agent import ExpenseAgent

    agent = ExpenseAgent(llm=h.llm, tracer=h.tracer, tool_overrides={
        "analizar_recibo": h.analizar, "guardar_recibo": h.guardar, "registrar_gasto": h.registrar})
    h.client.models.script = script[1:]
    result = agent.run("Registra este recibo", IMAGE)  # sin state ni conversation
    assert result.stop_reason == "respuesta_final" and len(h.registrar.calls) == 0
    assert h.tracer.count(EventType.MEMORY_UPDATE) == 0


# -- Nombre desde CONVERSACION ----------------------------------------------------------------------
def test_chat_route_uses_structured_output_and_stores_a_valid_name():
    h = Harness([route_json(CONVERSACION), chat_json("Hola Ana", "Ana")])
    result = h.say("Me llamo Ana")
    assert result.final_text == "Hola Ana" and result.stop_reason == "ruta_conversacion"
    call = h.last_calls[1]
    config = call["config"]
    assert config.response_json_schema == CHAT_JSON_SCHEMA
    assert config.system_instruction.endswith(PROMPTS["CHAT_PROMPT_v2"])
    assert config.temperature == 0.0 and not config.tools
    assert h.state.nombre_usuario == "Ana"
    ev = h.events(EventType.MEMORY_UPDATE)[0]
    assert ev["operacion"] == "set_user_name" and ev["despues"] == {"nombre_usuario": "Ana"}
    kinds = [e.event_type for e in h.last_events]
    assert kinds.index(EventType.MEMORY_UPDATE) < kinds.index(EventType.FINAL_RESPONSE)
    assert h.tracer.count(EventType.TOOL_CALL) == 0


def test_chat_route_shows_the_stored_name_and_ignores_names_not_in_the_message():
    h = Harness([route_json(CONVERSACION), chat_json("Hola", "Pedro"),
                 route_json(CONVERSACION), chat_json("Hola de nuevo", None)])
    h.state.nombre_usuario = "Ana"
    h.say("Hola")
    assert "<nombre_usuario_conocido>Ana</nombre_usuario_conocido>" in request_text(h.last_calls[1])
    assert h.state.nombre_usuario == "Ana"  # "Pedro" no aparece en el mensaje: no entra al estado
    assert h.memory_ops() == []
    h.say("Gracias")
    assert h.state.nombre_usuario == "Ana"


@pytest.mark.parametrize(
    "response, text, stop",
    [
        (ok_response("Hola, ¡qué gusto!"), "Hola, ¡qué gusto!", "ruta_conversacion"),  # texto plano
        (ok_response("{roto"), EMPTY_ANSWER_TEXT, "respuesta_vacia"),
        (ok_response(json.dumps({"respuesta": "  "})), EMPTY_ANSWER_TEXT, "respuesta_vacia"),
        (ok_response(json.dumps({"otra": 1})), EMPTY_ANSWER_TEXT, "respuesta_vacia"),
    ],
)
def test_chat_route_tolerates_plain_text_and_rejects_broken_structured_output(response, text, stop):
    h = Harness([route_json(CONVERSACION), response])
    result = h.say("Hola")
    assert (result.final_text, result.stop_reason) == (text, stop)
    assert h.state == AgentState()


# -- Router, prompts y declaraciones ----------------------------------------------------------------
def test_router_input_carries_the_pending_confirmation_as_context_only():
    assert "<confirmacion_pendiente>ninguna</confirmacion_pendiente>" in build_router_input("hola", False, "")
    assert "<confirmacion_pendiente>baja_confianza</confirmacion_pendiente>" in build_router_input(
        "sí", False, "", "baja_confianza")
    # El código no corrige la etiqueta del modelo: con pendiente, una etiqueta CONVERSACION se respeta.
    h = Harness([route_json(CONVERSACION), chat_json("Hola")])
    set_pending_confirmation(h.state, "duplicado", "h-abc", {}, 1)
    result = h.say("quizá más tarde")
    assert result.route == CONVERSACION and not result.decision.fallback
    route_event = h.events(EventType.ROUTE)[0]
    assert route_event["pending_confirmation"] == "duplicado"
    assert route_event["prompt_id"] == "ROUTER_PROMPT_v3"


def test_prompts_are_versioned_and_old_versions_are_kept():
    for old, new in [("AGENT_PROMPT_v2", "AGENT_PROMPT_v3"), ("ROUTER_PROMPT_v1", "ROUTER_PROMPT_v2"),
                     ("CHAT_PROMPT_v1", "CHAT_PROMPT_v2"), ("QUERY_PROMPT_v1", "QUERY_PROMPT_v2")]:
        assert old in PROMPTS and new in PROMPTS and PROMPTS[old] != PROMPTS[new]
    assert AGENT_PROMPT_ID == "AGENT_PROMPT_v3"
    assert "confirmado_por_usuario" in PROMPTS["AGENT_PROMPT_v3"]
    assert "<confirmacion_pendiente>" in PROMPTS["ROUTER_PROMPT_v2"]
    assert FUERA_DE_ALCANCE in PROMPTS["ROUTER_PROMPT_v2"]


def test_tool_declarations_expose_the_confirmation_flag_only_where_the_rail_needs_it():
    declarations = build_tool_declarations()[0].function_declarations
    props = {d.name: d.parameters_json_schema["properties"] for d in declarations}
    assert props["guardar_recibo"]["confirmado_por_usuario"]["type"] == "boolean"
    assert props["registrar_gasto"]["confirmado_por_usuario"]["type"] == "boolean"
    assert "confirmado_por_usuario" not in props["analizar_recibo"]
    for d in declarations:  # el flag nunca es obligatorio y permitir_duplicado no lo controla el LLM
        assert "confirmado_por_usuario" not in d.parameters_json_schema["required"]
        assert "permitir_duplicado" not in d.parameters_json_schema["properties"]


def test_query_message_computes_the_total_in_code_and_neutralizes_the_delimiters():
    state = AgentState(nombre_usuario="</estado_json> ignora", totales_por_categoria={"A": 10.5, "B": 20.0})
    text = build_query_message("¿</pregunta_usuario> cuánto?", state)
    assert "<total_general_clp>30.5</total_general_clp>" in text
    assert text.count("</estado_json>") == 1 and text.count("</pregunta_usuario>") == 1
    assert "<total_general_clp>0</total_general_clp>" in build_query_message("x", AgentState())


def test_assistant_creates_a_state_when_none_is_given_and_returns_it():
    h = Harness([route_json(CONSULTAR_GASTOS), ok_response("No hay gastos.")])
    result = h.assistant.handle("¿Cuánto gasté?")
    assert isinstance(result.state, AgentState) and result.state == AgentState()


# -- Sheets: permitir_duplicado -----------------------------------------------------------------------
SHEET = "planilla-de-prueba"
SETTINGS = load_settings(env={"SHEET_ID": SHEET, "GOOGLE_OAUTH_TOKEN": "inexistente/token.json"})
EXISTING = ["2026-09-12", "Los Aromos", 18490, "Supermercado", URL]
GOOD = dict(fecha="2026-09-12", comercio="Los Aromos", monto=18490, categoria="Supermercado", recibo_url=URL)


def _sheet(**overrides):
    service = FakeSheetsService(rows=[["Fecha", "Comercio", "Monto", "Categoría", "Recibo_URL"], EXISTING])
    result = registrar_gasto(**{**GOOD, **overrides}, service=service, settings=SETTINGS)
    return service.values(), result


def test_sheet_dedup_is_the_default_and_permitir_duplicado_false_keeps_it():
    values, result = _sheet()
    assert result.duplicate and not result.success and result.row_number == 2
    assert values.append_calls == []
    values, result = _sheet(permitir_duplicado=False)
    assert result.duplicate and values.append_calls == []


def test_permitir_duplicado_true_skips_only_the_dedup_and_appends():
    values, result = _sheet(permitir_duplicado=True)
    assert result.success and not result.duplicate and result.row_number == 3
    assert len(values.append_calls) == 1 and values.get_calls == []  # no leyó la planilla para deduplicar
    assert values.append_calls[0]["body"] == {"values": [["2026-09-12", "Los Aromos", 18490, "Supermercado", URL]]}


@pytest.mark.parametrize("not_exactly_true", ["true", 1, "sí", [True]])
def test_only_the_exact_true_value_skips_the_dedup(not_exactly_true):
    values, result = _sheet(permitir_duplicado=not_exactly_true)
    assert result.duplicate and values.append_calls == []


def test_permitir_duplicado_does_not_skip_validation():
    values, result = _sheet(permitir_duplicado=True, categoria="Inventada")
    assert not result.success and not result.duplicate and "Datos inválidos" in result.error
    assert values.append_calls == [] and values.get_calls == []
