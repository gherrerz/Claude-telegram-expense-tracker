"""Pruebas de la Etapa 13: demo de Telegram (sin red, con objetos falsos)."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import telegram_bot
from app.assistant import AssistantResult
from app.config import ConfigError, load_settings
from app.models import EventType
from app.telegram_bot import (
    DEFAULT_PHOTO_TEXT,
    ERROR_TEXT,
    MAX_MESSAGE_CHARS,
    TelegramBot,
    split_message,
)

ROOT = Path(__file__).resolve().parents[1]
FAKE_TOKEN = "123456789:" + "z" * 35  # sintético, construido en tiempo de ejecución


class FakeAssistant:
    """Sustituye a `ExpenseAssistant`: registra las llamadas y escribe un evento en la traza."""

    def __init__(self, reply="respuesta", fail=None):
        self.calls = []
        self.reply = reply
        self.fail = fail

    def handle(self, user_text, image_path=None, conversation=None, state=None, tracer=None):
        self.calls.append(
            {"text": user_text, "image": image_path, "conversation": conversation,
             "state": state, "tracer": tracer}
        )
        if self.fail is not None:
            raise self.fail
        tracer.record(EventType.USER_INPUT, {"text": user_text})
        return AssistantResult(route="CONVERSACION", final_text=self.reply)


class FakeFile:
    def __init__(self):
        self.downloaded = None

    async def download_to_drive(self, custom_path=None):
        self.downloaded = Path(custom_path)
        self.downloaded.write_bytes(b"jpg")
        return self.downloaded


class FakePhotoSize:
    def __init__(self, file):
        self._file = file

    async def get_file(self):
        return self._file


class FakeMessage:
    def __init__(self, text=None, photo=None, caption=None, message_id=1):
        self.text = text
        self.photo = photo or []
        self.caption = caption
        self.message_id = message_id
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


def make_update(chat_id, **kwargs):
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), message=FakeMessage(**kwargs))


def make_bot(tmp_path, monkeypatch, env_extra=None, assistant=None):
    monkeypatch.chdir(tmp_path)  # las trazas de la prueba van a tmp_path/traces
    env = {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN, **(env_extra or {})}
    settings = load_settings(env=env)
    assistant = assistant or FakeAssistant()
    return TelegramBot(settings, assistant), assistant


@pytest.fixture(autouse=True)
def _restore_logging():
    factory = logging.getLogRecordFactory()
    levels = {n: logging.getLogger(n).level for n in telegram_bot.QUIET_LOGGERS}
    yield
    logging.setLogRecordFactory(factory)
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)


def run(coro):
    return asyncio.run(coro)


def test_text_same_chat_shares_conversation_and_state(tmp_path, monkeypatch):
    bot, assistant = make_bot(tmp_path, monkeypatch)
    first, second = make_update(10, text="Hola"), make_update(10, text="Me llamo Ana")
    run(bot.on_text(first, None))
    run(bot.on_text(second, None))
    assert [c["text"] for c in assistant.calls] == ["Hola", "Me llamo Ana"]
    assert assistant.calls[0]["conversation"] is assistant.calls[1]["conversation"]
    assert assistant.calls[0]["state"] is assistant.calls[1]["state"]
    assert assistant.calls[0]["image"] is None
    assert first.message.replies == ["respuesta"]


def test_two_chats_are_isolated(tmp_path, monkeypatch):
    bot, assistant = make_bot(tmp_path, monkeypatch)
    run(bot.on_text(make_update(1, text="a"), None))
    run(bot.on_text(make_update(2, text="b"), None))
    one, two = assistant.calls
    assert one["conversation"] is not two["conversation"]
    assert one["state"] is not two["state"]
    assert one["tracer"].session == "telegram_1" and two["tracer"].session == "telegram_2"


def test_photo_is_downloaded_and_passed_with_caption(tmp_path, monkeypatch):
    bot, assistant = make_bot(tmp_path, monkeypatch)
    telegram_file = FakeFile()
    small, large = FakeFile(), telegram_file
    update = make_update(5, photo=[FakePhotoSize(small), FakePhotoSize(large)], caption="Cena")
    run(bot.on_photo(update, None))
    assert telegram_file.downloaded is not None and small.downloaded is None  # el más grande
    call = assistant.calls[0]
    assert call["image"] == telegram_file.downloaded and call["image"].exists()
    assert call["text"] == "Cena"
    run(bot.on_photo(make_update(5, photo=[FakePhotoSize(FakeFile())], message_id=2), None))
    assert assistant.calls[1]["text"] == DEFAULT_PHOTO_TEXT
    assert assistant.calls[0]["image"].parent == assistant.calls[1]["image"].parent  # por chat
    assert assistant.calls[0]["image"].exists()  # se conserva durante la sesión
    bot.cleanup()
    assert not assistant.calls[0]["image"].exists()


def test_photo_download_failure_gives_generic_reply(tmp_path, monkeypatch):
    bot, assistant = make_bot(tmp_path, monkeypatch)

    class Broken:
        async def get_file(self):
            raise RuntimeError(f"fallo https://api.telegram.org/bot{FAKE_TOKEN}/getFile")

    update = make_update(5, photo=[Broken()])
    run(bot.on_photo(update, None))
    assert assistant.calls == []
    assert len(update.message.replies) == 1 and FAKE_TOKEN not in update.message.replies[0]
    bot.cleanup()


def test_other_content_gets_brief_notice(tmp_path, monkeypatch):
    bot, assistant = make_bot(tmp_path, monkeypatch)
    update = make_update(3)
    run(bot.on_other(update, None))
    assert assistant.calls == []
    assert "texto y fotos" in update.message.replies[0]


def test_allowlist_blocks_other_chats_without_calling_agent(tmp_path, monkeypatch):
    bot, assistant = make_bot(tmp_path, monkeypatch, {"TELEGRAM_ALLOWED_CHAT_IDS": "7"})
    blocked = make_update(8, text="hola")
    run(bot.on_text(blocked, None))
    run(bot.on_photo(make_update(8, photo=[FakePhotoSize(FakeFile())]), None))
    run(bot.on_other(make_update(8), None))
    assert assistant.calls == [] and "privado" in blocked.message.replies[0]
    run(bot.on_text(make_update(7, text="hola"), None))
    assert len(assistant.calls) == 1


def test_start_shows_chat_id_even_when_blocked(tmp_path, monkeypatch):
    bot, _ = make_bot(tmp_path, monkeypatch, {"TELEGRAM_ALLOWED_CHAT_IDS": "7"})
    allowed, blocked = make_update(7), make_update(8)
    run(bot.on_start(allowed, None))
    run(bot.on_start(blocked, None))
    assert "7" in allowed.message.replies[0] and "gastos" in allowed.message.replies[0]
    assert "8" in blocked.message.replies[0] and "privado" in blocked.message.replies[0]


def test_long_reply_is_split(tmp_path, monkeypatch):
    long_text = "\n".join(f"línea {i} " + "x" * 90 for i in range(120))  # > 4096
    assert len(long_text) > MAX_MESSAGE_CHARS
    bot, _ = make_bot(tmp_path, monkeypatch, assistant=FakeAssistant(reply=long_text))
    update = make_update(1, text="hola")
    run(bot.on_text(update, None))
    assert len(update.message.replies) >= 2
    assert all(len(r) <= MAX_MESSAGE_CHARS for r in update.message.replies)
    assert "\n".join(update.message.replies).split() == long_text.split()


def test_split_message_without_newlines_and_empty():
    chunks = split_message("a" * (MAX_MESSAGE_CHARS * 2 + 5))
    assert [len(c) for c in chunks] == [MAX_MESSAGE_CHARS, MAX_MESSAGE_CHARS, 5]
    assert split_message("") == [telegram_bot.EMPTY_REPLY_TEXT]


def test_handle_exception_gives_generic_reply_and_masked_log(tmp_path, monkeypatch, caplog):
    boom = RuntimeError(f"fallo en https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage")
    bot, _ = make_bot(tmp_path, monkeypatch, assistant=FakeAssistant(fail=boom))
    update = make_update(1, text="hola")
    with caplog.at_level(logging.DEBUG):
        run(bot.on_text(update, None))
    assert update.message.replies == [ERROR_TEXT]
    assert "RuntimeError" in caplog.text and FAKE_TOKEN not in caplog.text


def test_token_never_in_logs_or_trace(tmp_path, monkeypatch, caplog):
    bot, assistant = make_bot(tmp_path, monkeypatch)
    telegram_bot.install_log_protection(FAKE_TOKEN)
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("otro.modulo").warning("url https://x/bot%s/getUpdates", FAKE_TOKEN)
        run(bot.on_text(make_update(1, text=f"mi token es {FAKE_TOKEN}"), None))
    assert FAKE_TOKEN not in caplog.text and "***" in caplog.text
    trace = assistant.calls[0]["tracer"].path.read_text(encoding="utf-8")
    assert FAKE_TOKEN not in trace and "***" in trace
    assert (tmp_path / "traces" / "telegram_1.jsonl").is_file()  # no escribe en el repo


def test_token_loggers_are_quiet_after_setup():
    for name in telegram_bot.QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)
    telegram_bot.install_log_protection(FAKE_TOKEN)
    for name in ("httpx", "telegram", "telegram.ext"):
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING


def test_build_application_registers_handlers_without_network(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    settings = load_settings(env={"TELEGRAM_BOT_TOKEN": FAKE_TOKEN})
    with caplog.at_level(logging.WARNING):
        application = telegram_bot.build_application(settings, assistant_factory=FakeAssistant)
    assert isinstance(application.bot_data["bot"], TelegramBot)
    assert len(application.handlers[0]) == 4  # /start, texto, foto, otros
    assert "abierto" in caplog.text and FAKE_TOKEN not in caplog.text  # aviso de bot abierto
    closed = load_settings(env={"TELEGRAM_BOT_TOKEN": FAKE_TOKEN, "TELEGRAM_ALLOWED_CHAT_IDS": "1"})
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        telegram_bot.build_application(closed, assistant_factory=FakeAssistant)
    assert "abierto" not in caplog.text


def test_build_application_requires_token():
    with pytest.raises(ConfigError) as exc:
        telegram_bot.build_application(load_settings(env={}), assistant_factory=FakeAssistant)
    assert "TELEGRAM_BOT_TOKEN" in str(exc.value)


def test_same_chat_turns_are_serialized(tmp_path, monkeypatch):
    bot, assistant = make_bot(tmp_path, monkeypatch)
    order = []
    original = assistant.handle

    def slow_handle(text, **kwargs):
        order.append(("start", text))
        import time
        time.sleep(0.05)
        order.append(("end", text))
        return original(text, **kwargs)

    assistant.handle = slow_handle

    async def both():
        await asyncio.gather(
            bot.on_text(make_update(1, text="uno"), None),
            bot.on_text(make_update(1, text="dos"), None),
        )

    run(both())
    assert [e[0] for e in order] == ["start", "end", "start", "end"]


def test_bot_module_has_no_agent_logic_imports():
    """El bot solo adapta E/S: no importa tools, LLM ni prompts."""
    tree = ast.parse((ROOT / "app" / "telegram_bot.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names if a.name.startswith("app"))
    assert imported <= {"app.assistant", "app.config", "app.trace", "app.conversation", "app.models"}
    source = (ROOT / "app" / "telegram_bot.py").read_text(encoding="utf-8")
    for forbidden in ("analizar_recibo", "guardar_recibo", "registrar_gasto", "google.genai", "LLMClient"):
        assert forbidden not in source
