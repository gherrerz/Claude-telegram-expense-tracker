# Etapa 13 — Demo Telegram (aparte, no evaluada en el notebook)

**Objetivo:** `app/telegram_bot.py` recibe la foto, la descarga, llama al MISMO punto de entrada del agente (`ExpenseAssistant.handle`) y responde por el chat, sin duplicar la lógica del agente.
**Criterio de rúbrica:** ninguno directo; es una demo aparte (prompt maestro, CONTEXTO).

## Decisiones de diseño (orquestador)
1. **Aislamiento por chat.** Cada `chat_id` tiene su propia `Conversation` y su propio `AgentState` en memoria (S6, lám. 37).
2. **El token nunca se filtra.** `TELEGRAM_BOT_TOKEN` sale solo del entorno. Los loggers de `httpx` y de la librería van a WARNING, porque a nivel INFO registran la URL de la API, que incluye el token. La traza enmascara el token (ya contemplado en `app/trace.py`).
3. **Acceso opcional.** `TELEGRAM_ALLOWED_CHAT_IDS` limita qué chats pueden usar el bot. Si está vacía, el bot avisa en consola de que está abierto.
4. **Sin lógica nueva.** Texto y foto (con su leyenda) van a `handle()`, y las respuestas salen de `AssistantResult.final_text`.

**Ruta:** delegated direct. Rama `feat/etapa-13-telegram`.
**TDD:** desactivado; pruebas offline con objetos falsos y una prueba manual del autor.

## Tareas
- [x] T1 Dependencia de Telegram fijada y variables (`TELEGRAM_BOT_TOKEN` y `TELEGRAM_ALLOWED_CHAT_IDS`).
- [x] T2 `app/telegram_bot.py`: handlers de texto y foto, sesión por chat, descarga a un directorio temporal y respuesta.
- [x] T3 Pruebas offline: el mismo `handle()`, el aislamiento por chat, la lista de acceso y que el token no aparezca en logs ni trazas.
- [x] T4 `docs/setup_telegram.md` (BotFather) y bitácora.
- [ ] T5 Prueba manual con la transcripción de la traza (requiere el token y un chat del autor).

## Evidencia
- T1: `python-telegram-bot==22.8` fijado en `requirements.txt` e instalado; `TELEGRAM_ALLOWED_CHAT_IDS` en `app/config.py` (`ALL_VARIABLES`, `Settings`, `config_status`) y prueba en `tests/test_stage2_config.py`. Pendiente del autor: declarar la variable en `.env.example` (la prueba estricta falla hasta entonces).
- T2: `app/telegram_bot.py` (`build_application`, `main`, `TelegramBot`); `import app.telegram_bot` OK; sin configuración, `python -m app.telegram_bot` sale con código 2 y un error que nombra las variables, sin red.
- T3: `tests/test_stage13_telegram.py`, 16 pruebas offline.
- T4: `docs/setup_telegram.md`, fila 13 del README y bitácora.
- Suite offline (`-m "not live"`): 464 passed, 1 failed (solo `test_every_settings_variable_is_declared_in_env_example`, por `.env.example`), 20 deselected.
- Ruta: delegated direct (un escritor). T5 abierta.
