# Demo de Telegram (Etapa 13)

El bot de Telegram es una demo aparte: la entrega evaluada es `notebooks/demo.ipynb`. `app/telegram_bot.py` solo adapta la entrada y la salida de Telegram hacia `ExpenseAssistant.handle` (el mismo punto de entrada del notebook); no contiene lógica del agente.

## 1. Crear el bot con @BotFather
1. En Telegram, abre una conversación con `@BotFather`.
2. Envía `/newbot`.
3. Indica un nombre visible (por ejemplo, «Expense Tracker Demo»).
4. Indica un nombre de usuario único que termine en `bot` (por ejemplo, `mi_expense_demo_bot`).
5. BotFather responde con el **token** del bot. Trátalo como una contraseña.

## 2. Configurar el entorno
Agrega el token al archivo `.env` (nunca al código, al notebook ni a git):

```
TELEGRAM_BOT_TOKEN=<token entregado por BotFather>
```

Las demás variables (`GEMINI_API_KEY`, `LLM_MODEL`, Google) son las mismas del resto del proyecto; ver `.env.example`.

### Lista de acceso (opcional, recomendada)
Sin restricción, cualquiera que encuentre el bot puede usarlo y consumir tu cuota del LLM. Para limitarlo:

1. Inicia el bot sin la variable y envíale `/start`: responde con tu **chat id**.
2. Agrega a `.env` los chats permitidos, separados por comas:

```
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

3. Reinicia el bot. Los demás chats reciben una negativa y el agente no se invoca. Si la variable está vacía, el bot escribe un WARNING al iniciar indicando que está abierto.

## 3. Ejecutar

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app.telegram_bot
```

Si falta una variable, el bot termina con un mensaje que nombra la variable (sin valores). Se detiene con `Ctrl+C`.

## 4. Guion de la prueba manual
Desde tu chat con el bot, en este orden:

1. `Hola`
2. `Me llamo <tu nombre>`
3. Una foto de un recibo de `data/receipts/` (con o sin leyenda; sin leyenda se usa «Registra este recibo»). Si el agente pide confirmación, responde en el siguiente mensaje.
4. `¿Cuánto llevo en Supermercado?`

Después, guarda la transcripción: la traza de tu chat está en `traces/telegram_<chat_id>.jsonl` (una por chat). La consola también muestra cada evento. Pega un extracto en la bitácora (`docs/dev_prompts.md`) como evidencia de la prueba manual.

## 5. Cómo funciona
- Una sesión por chat: cada `chat_id` tiene su propia `Conversation`, su propio `AgentState` y su propia traza, en memoria (se pierden al detener el bot).
- Texto → `handle(texto)`. Foto → se descarga la versión más grande a un directorio temporal por chat y se llama a `handle(leyenda, image_path=...)`. Las imágenes se conservan mientras el bot esté activo, porque una confirmación pendiente puede necesitar una imagen de un turno anterior, y se eliminan al detenerlo.
- Otros tipos de mensaje reciben un aviso breve («solo acepto texto y fotos»).
- `handle` es síncrono: corre en un hilo y los turnos de un mismo chat se serializan.
- Las respuestas largas se dividen en mensajes de hasta 4096 caracteres.
- Si `handle` falla, el usuario recibe un mensaje genérico; el detalle (enmascarado) queda solo en el log y la traza.

## 6. Seguridad
- **Token:** solo por variable de entorno. Los loggers de `httpx` y `telegram` se fijan en WARNING porque a nivel INFO registran la URL de la API, que contiene el token; además todo registro y toda traza pasan por un enmascarado del token. Si sospechas una filtración, genera uno nuevo con `/revoke` en BotFather.
- **Bot abierto:** sin `TELEGRAM_ALLOWED_CHAT_IDS`, cualquier usuario puede escribirle. Usa la lista de acceso.
- **Cuota:** cada mensaje puede consumir varias llamadas al LLM de la capa gratuita; el agente ya aplica pausa y reintentos (`LLM_MIN_SECONDS_BETWEEN_CALLS`).
- **Alcance del agente:** las reglas de seguridad (`SECURITY_SCOPE`), el router y el juez son los mismos que en el notebook; el bot no agrega herramientas.
- **Datos:** usa solo recibos sintéticos o anonimizados.

## Referencias
- python-telegram-bot 22.8 (versión fijada en `requirements.txt`): https://docs.python-telegram-bot.org. Los símbolos usados (`Application.builder().token()`, `CommandHandler`, `MessageHandler`, `filters.PHOTO`, `filters.TEXT & ~filters.COMMAND`, `File.download_to_drive`, `Message.reply_text`, `run_polling`) se verificaron en el código fuente instalado; el sitio de documentación no se consultó en esta etapa **[no verificado]**.
