"""Demo de Telegram (Etapa 13): adaptador de entrada/salida hacia `ExpenseAssistant.handle`.

El bot NO contiene lógica del agente: recibe texto o fotos, las entrega a
`ExpenseAssistant.handle(...)` (el mismo punto de entrada que usa el notebook) y responde con
`AssistantResult.final_text`. Router, tools, juez y memoria viven en `app/assistant.py`.

Decisiones de diseño:

- Una sesión por chat (`ChatSession`): su propia `Conversation`, su propio `AgentState` y su
  propio `Tracer` (`traces/telegram_<chat_id>.jsonl`), creados de forma perezosa y en memoria.
- `handle` es síncrono: se ejecuta en un hilo (`asyncio.to_thread`) y las llamadas de un mismo
  chat se serializan con un `asyncio.Lock` para conservar el orden del historial.
- Las fotos se descargan a un directorio temporal por chat que vive mientras dure el proceso:
  la confirmación pendiente de la Etapa 10 puede necesitar la ruta de una imagen de un turno
  anterior. El directorio se elimina al detener el bot.
- Acceso: si `TELEGRAM_ALLOWED_CHAT_IDS` está definida, los demás chats reciben una negativa
  sin llamar al agente. Si está vacía, el bot avisa con un WARNING al iniciar de que está abierto.
- El token del bot nunca debe aparecer en registros ni trazas. `httpx` y `telegram` registran
  la URL de la API (que incluye el token) a nivel INFO, por eso sus loggers se fijan en WARNING;
  además se enmascara el token en todo registro de logging y en la traza (defensa en profundidad).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.assistant import ExpenseAssistant
from app.config import ConfigError, Settings, load_settings
from app.conversation import Conversation
from app.models import AgentState
from app.trace import Tracer, mask_value

LOGGER = logging.getLogger("app.telegram_bot")

MAX_MESSAGE_CHARS = 4096  # límite de caracteres por mensaje de Telegram
DEFAULT_PHOTO_TEXT = "Registra este recibo"
QUIET_LOGGERS = ("httpx", "httpcore", "telegram", "telegram.ext")

START_TEXT = (
    "Hola. Soy un asistente de gastos: envíame la foto de un recibo y lo registro, "
    "o pregúntame por tus gastos (por ejemplo, «¿Cuánto llevo en Supermercado?»).\n"
    "Tu chat id es {chat_id}."
)
START_DENIED_TEXT = "Este bot es privado y tu chat no tiene acceso. Tu chat id es {chat_id}."
DENIED_TEXT = "Este bot es privado y tu chat no tiene acceso."
UNSUPPORTED_TEXT = "Por ahora solo acepto texto y fotos de recibos."
ERROR_TEXT = "Ocurrió un error al procesar tu mensaje. No se realizó ninguna acción; intenta de nuevo."
EMPTY_REPLY_TEXT = "No obtuve una respuesta. Intenta reformular tu mensaje."
PHOTO_ERROR_TEXT = "No pude descargar la foto. Inténtalo de nuevo."


@dataclass
class ChatSession:
    """Estado en memoria de un chat."""

    conversation: Conversation
    state: AgentState
    tracer: Tracer
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    temp_dir: Optional[Path] = None


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Divide un texto en trozos de a lo sumo `limit` caracteres, cortando en saltos de línea."""
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    chunks.append(rest)
    return [c for c in chunks if c.strip()] or [EMPTY_REPLY_TEXT]


class TokenMaskFilter(logging.Filter):
    """Enmascara el token del bot en el mensaje de cualquier registro que pase por el filtro."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = mask_value(message, [self._token])
        if masked != message:
            record.msg = masked
            record.args = ()
        return True


def install_log_protection(token: Optional[str]) -> None:
    """Silencia los loggers que exponen la URL de la API y enmascara el token en todo registro.

    `httpx`, `httpcore` y `telegram` registran a nivel INFO las URL `.../bot<TOKEN>/...`: se
    fijan en WARNING. Además se envuelve la fábrica de registros para que cualquier mensaje
    (de cualquier logger) salga sin el token.
    """
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if not token:
        return
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_telegram_token_mask", None) == token:
        return
    mask_filter = TokenMaskFilter(token)

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        mask_filter.filter(record)
        return record

    factory._telegram_token_mask = token  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


class TelegramBot:
    """Handlers de Telegram que adaptan E/S hacia `ExpenseAssistant.handle`."""

    def __init__(self, settings: Settings, assistant: ExpenseAssistant) -> None:
        self.settings = settings
        self.assistant = assistant
        self.allowed = frozenset(settings.telegram_allowed_chat_ids)
        self.sessions: dict[int, ChatSession] = {}
        self._secrets = [settings.telegram_bot_token] if settings.telegram_bot_token else []

    # -- sesiones y acceso ------------------------------------------------------------
    def session_for(self, chat_id: int) -> ChatSession:
        """Sesión del chat, creada la primera vez."""
        session = self.sessions.get(chat_id)
        if session is None:
            tracer = Tracer(session=f"telegram_{chat_id}", extra_secrets=self._secrets)
            session = ChatSession(Conversation(), AgentState(), tracer)
            self.sessions[chat_id] = session
        return session

    def is_allowed(self, chat_id: int) -> bool:
        return not self.allowed or chat_id in self.allowed

    def cleanup(self) -> None:
        """Elimina los directorios temporales de imágenes (al detener el bot)."""
        for session in self.sessions.values():
            if session.temp_dir is not None:
                shutil.rmtree(session.temp_dir, ignore_errors=True)
                session.temp_dir = None

    # -- handlers ---------------------------------------------------------------------
    async def on_start(self, update: Any, context: Any) -> None:
        chat_id = update.effective_chat.id
        template = START_TEXT if self.is_allowed(chat_id) else START_DENIED_TEXT
        await update.message.reply_text(template.format(chat_id=chat_id))

    async def on_text(self, update: Any, context: Any) -> None:
        chat_id = update.effective_chat.id
        if not await self._check_access(update, chat_id):
            return
        await self._run_turn(update, chat_id, update.message.text or "", None)

    async def on_photo(self, update: Any, context: Any) -> None:
        chat_id = update.effective_chat.id
        if not await self._check_access(update, chat_id):
            return
        session = self.session_for(chat_id)
        if session.temp_dir is None:
            session.temp_dir = Path(tempfile.mkdtemp(prefix=f"expense_tg_{chat_id}_"))
        destination = session.temp_dir / f"photo_{update.message.message_id}.jpg"
        try:
            telegram_file = await update.message.photo[-1].get_file()  # tamaño más grande
            await telegram_file.download_to_drive(custom_path=destination)
        except Exception as exc:  # noqa: BLE001 - se informa genérico; sin detalles ni traza
            self._log_error("descarga de foto", exc)
            await update.message.reply_text(PHOTO_ERROR_TEXT)
            return
        caption = (update.message.caption or "").strip() or DEFAULT_PHOTO_TEXT
        await self._run_turn(update, chat_id, caption, destination)

    async def on_other(self, update: Any, context: Any) -> None:
        chat_id = update.effective_chat.id
        if not await self._check_access(update, chat_id):
            return
        await update.message.reply_text(UNSUPPORTED_TEXT)

    # -- internos ---------------------------------------------------------------------
    async def _check_access(self, update: Any, chat_id: int) -> bool:
        if self.is_allowed(chat_id):
            return True
        LOGGER.info("Chat %s rechazado por la lista de acceso.", chat_id)
        await update.message.reply_text(DENIED_TEXT)
        return False

    async def _run_turn(
        self, update: Any, chat_id: int, text: str, image_path: Optional[Path]
    ) -> None:
        session = self.session_for(chat_id)
        async with session.lock:  # un turno a la vez por chat: conserva el orden del historial
            try:
                result = await asyncio.to_thread(
                    self.assistant.handle,
                    text,
                    image_path=image_path,
                    conversation=session.conversation,
                    state=session.state,
                    tracer=session.tracer,
                )
            except Exception as exc:  # noqa: BLE001 - respuesta genérica; detalle solo enmascarado
                self._log_error("agente", exc)
                await update.message.reply_text(ERROR_TEXT)
                return
        for chunk in split_message(result.final_text or EMPTY_REPLY_TEXT):
            await update.message.reply_text(chunk)

    def _log_error(self, where: str, exc: Exception) -> None:
        """Registra solo el tipo y el mensaje enmascarado (sin traza: podría incluir la URL)."""
        detail = mask_value(str(exc), self._secrets)
        LOGGER.error("Error en %s: %s: %s", where, type(exc).__name__, detail)


def build_application(
    settings: Settings,
    assistant_factory: Optional[Callable[[], ExpenseAssistant]] = None,
) -> Any:
    """Construye la `Application` de python-telegram-bot con los handlers registrados.

    No inicia el sondeo (`run_polling`): eso lo hace `main()`. El objeto `TelegramBot` queda en
    `application.bot_data["bot"]`.
    """
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    if not settings.telegram_bot_token:
        raise ConfigError(["TELEGRAM_BOT_TOKEN"], "Faltan variables de entorno")
    install_log_protection(settings.telegram_bot_token)
    if not settings.telegram_allowed_chat_ids:
        LOGGER.warning(
            "TELEGRAM_ALLOWED_CHAT_IDS está vacía: el bot está abierto a cualquier chat "
            "y cada mensaje consume cuota del LLM."
        )
    bot = TelegramBot(settings, (assistant_factory or ExpenseAssistant)())

    async def _cleanup(_application: Any) -> None:
        bot.cleanup()

    application = (
        Application.builder().token(settings.telegram_bot_token).post_shutdown(_cleanup).build()
    )
    application.bot_data["bot"] = bot
    application.add_handler(CommandHandler("start", bot.on_start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.on_text))
    application.add_handler(MessageHandler(filters.PHOTO, bot.on_photo))
    application.add_handler(MessageHandler(~filters.COMMAND, bot.on_other))
    return application


def main() -> int:
    """Punto de entrada: `python -m app.telegram_bot`. Se detiene con Ctrl+C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        settings = load_settings(["llm", "telegram"])
    except ConfigError as exc:
        print(f"Configuración incompleta: {exc}", file=sys.stderr)
        return 2
    application = build_application(settings)
    print("Bot en marcha. Detén con Ctrl+C.")
    application.run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
