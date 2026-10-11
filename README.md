# Telegram Expense Tracker

Agente de IA que recibe la foto de un recibo, extrae fecha, comercio y monto con un LLM con visión, categoriza el gasto, guarda la imagen en Google Drive y registra el gasto en Google Sheets con el enlace al recibo.

Proyecto académico: tarea final del curso de agentes de IA. La entrega evaluada es el notebook `notebooks/demo.ipynb`, ejecutable de principio a fin sin costo para el revisor. La demo de Telegram es aparte y no se evalúa.

> **Estado:** desarrollo en la Etapa 14 (notebook final, entrega y revisión contra la rúbrica). Ver «Avance por etapas» y `docs/checklist_rubrica.md`.

## Ejemplo de resultado

| Fecha | Comercio | Monto | Categoría | Recibo_URL |
|---|---|---|---|---|
| 30/09/2026 | Jumbo | 32490 | Supermercado | enlace devuelto por la API de Drive |

## Documentación
- [Caso de uso y criterio de éxito](docs/use_case.md)
- [Arquitectura](docs/architecture.md)
- [Arquitectura de la solución implementada (diagramas)](docs/solution_architecture.md)
- [Acceso al LLM: clave gratuita de Google AI Studio y límites](docs/setup_llm.md)
- [Configuración de Google Drive y Sheets](docs/setup_google.md)
- [Configuración del Redis del curso (RAG, Etapa 15)](docs/setup_redis.md)
- [Ampliaciones declaradas (bonos)](docs/bonos.md)
- [Evaluación con golden set e historial de corridas](docs/evaluation.md)
- [Corpus sintético del RAG y su origen](data/corpus/README.md)
- [Checklist final contra la rúbrica](docs/checklist_rubrica.md)
- [Ejemplos de trazas reales](docs/trace_examples.md)
- [Mapa frente a la materia del curso](docs/mapa_curso.md)
- [Demo de Telegram (BotFather, ejecución y prueba manual)](docs/setup_telegram.md)
- [Prompts de desarrollo y bitácora por etapa](docs/dev_prompts.md)
- [Prompt maestro de desarrollo](docs/prompt_maestro_v2.md)
- [Reglas para agentes de código](AGENTS.md)
- [Configuración paso a paso (Gemini, Google, Redis y Telegram)](#configuración-paso-a-paso)

## Configuración paso a paso

Guía para configurar tus propias credenciales gratuitas desde un clon limpio. Solo `GEMINI_API_KEY` y `LLM_MODEL` son obligatorias para el flujo central del notebook; Google, Redis y Telegram son opcionales (ver «Qué hace cada sección» en la ficha de reproducción). Los ejemplos usan marcadores `<...>`: nunca subas valores reales a git.

### a. Requisitos previos

1. Instala Python 3.12 y ten a mano una cuenta Gmail (la usarás en Google AI Studio y Google Cloud).
2. Desde la raíz del repositorio, crea el entorno virtual `.venv`:
   ```bash
   py -3.12 -m venv .venv
   ```
3. Instala las dependencias en `.venv`:
   ```bash
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
4. Ejecuta siempre los scripts con `.venv\Scripts\python` y abre el notebook con el kernel de `.venv`. Con el Python global aparece `ModuleNotFoundError`.

Detalle: [Ficha de reproducción, punto 3](#3-dependencias-e-instalación).

### b. Crear `.env` a partir de `.env.example`

1. Copia la plantilla:
   ```bash
   copy .env.example .env
   ```
2. Edita `.env` y completa los valores en los pasos siguientes. `.env` está en `.gitignore`: no lo subas ni lo pegues en capturas o chats.
3. Escribe cada variable como `NOMBRE=valor`, sin comillas ni espacios alrededor del `=`. **[SUPUESTO]** El formato sin comillas es el que usan las guías; `python-dotenv` también admite comillas, pero no se probó.

Detalle: [Ficha de reproducción, punto 4 (variables de entorno)](#4-variables-de-entorno-nombres-y-función-sin-valores).

### c. Gemini (Google AI Studio)

1. Inicia sesión en <https://aistudio.google.com/apikey> con tu cuenta Google y crea una clave de API (no pide tarjeta). **[SUPUESTO]** Los nombres exactos de los botones pueden variar con la interfaz.
2. Pega la clave en `.env` y fija el modelo confirmado:
   ```
   GEMINI_API_KEY=<tu-clave>
   LLM_MODEL=gemini-3.5-flash-lite
   ```
3. Opcional: `LLM_MAX_RETRIES` (reintentos ante 429 y 503; 5 por defecto) y `LLM_MIN_SECONDS_BETWEEN_CALLS` (pausa entre llamadas; 4,0 s por defecto).
4. Verifica con una llamada real (consume cuota gratuita):
   ```bash
   .venv\Scripts\python scripts\verify_stage_3.py
   ```
5. Los límites de uso dependen del modelo y de tu cuenta, y Google no publica cifras fijas por modelo: consulta los tuyos en <https://aistudio.google.com/rate-limit>.
6. Envía solo recibos sintéticos (`data/receipts/`): en la capa gratuita Google puede usar los datos enviados.

Detalle: [docs/setup_llm.md](docs/setup_llm.md).

### d. Google Drive y Sheets (OAuth, opcional)

1. En [Google Cloud Console](https://console.cloud.google.com/) crea un proyecto nuevo.
2. En *APIs y servicios > Biblioteca* habilita **Google Drive API** y **Google Sheets API**.
3. En *APIs y servicios > Pantalla de consentimiento de OAuth* elige tipo de usuario **Externo**, estado de publicación **Testing**, y agrega tu propia cuenta Gmail en **Usuarios de prueba**.
4. En *Credenciales > Crear credenciales > ID de cliente de OAuth* elige **Aplicación de escritorio** y descarga el JSON.
5. Guarda el JSON en `secrets/` (por ejemplo, `secrets/client_secret.json`). `secrets/` está en `.gitignore`.
6. En `.env` pon la **ruta** al JSON, no el secreto que contiene:
   ```
   GOOGLE_OAUTH_CLIENT_SECRETS=secrets/client_secret.json
   GOOGLE_OAUTH_TOKEN=secrets/token.json
   ```
7. Autoriza con tu cuenta (se abre el navegador; Google avisará de «app no verificada» porque está en Testing: continúa):
   ```bash
   .venv\Scripts\python scripts\google_auth.py
   ```
8. Deja `DRIVE_FOLDER_ID` y `SHEET_ID` en blanco en `.env` y crea la carpeta y la planilla de prueba. El script no crea un recurso cuyo ID ya esté definido:
   ```bash
   .venv\Scripts\python scripts\setup_google_resources.py
   ```
9. Pega en `.env` las dos líneas que imprime el script:
   ```
   DRIVE_FOLDER_ID=<id-de-la-carpeta>
   SHEET_ID=<id-de-la-planilla>
   ```
10. Verifica Drive y luego Sheets (cada script termina con `RESULTADO: OK` si todo funciona):
    ```bash
    .venv\Scripts\python scripts\verify_stage_4.py
    ```
    ```bash
    .venv\Scripts\python scripts\verify_stage_5.py
    ```

Con el scope `drive.file` la aplicación solo ve lo que creó ella misma: no uses carpetas ni planillas creadas a mano. Con la app en modo Testing el token caduca a los 7 días (ver «Problemas frecuentes»).

Detalle: [docs/setup_google.md](docs/setup_google.md).

### e. Redis del curso (RAG, opcional)

1. Pide al docente la URL de conexión del Redis del curso (incluye la contraseña) y el prefijo de tu grupo.
2. Agrégalos a `.env`. El prefijo admite solo letras, números, guion y guion bajo:
   ```
   REDIS_URL=<url-de-redis-entregada-por-el-docente>
   REDIS_PREFIX=<prefijo-de-tu-grupo>
   ```
3. Opcional: `RAG_TOP_K` (1 a 10; 3 por defecto) y `RAG_THRESHOLD` (0 a 1; 0,75 por defecto). No hace falta declararlos.
4. Comprueba la fragmentación del corpus sin red (solo lee y fragmenta):
   ```bash
   .venv\Scripts\python scripts\load_corpus.py --dry-run
   ```
5. Carga el corpus antes de la Sección 11 del notebook (se omite si no cambió; `--force` reconstruye solo tu índice):
   ```bash
   .venv\Scripts\python scripts\load_corpus.py
   ```
6. Verifica el RAG (termina con `RESULTADO: OK`):
   ```bash
   .venv\Scripts\python scripts\verify_stage_15.py
   ```

Redis es compartido: trabaja solo bajo tu prefijo y no pegues la URL en código, chats ni commits. Sin Redis solo se degrada el RAG; el resto del agente funciona.

Detalle: [docs/setup_redis.md](docs/setup_redis.md).

### f. Bot de Telegram (demo, opcional)

1. En Telegram abre `@BotFather`, envía `/newbot`, indica un nombre visible y un nombre de usuario único que termine en `bot`. BotFather responde con el token.
2. Agrega el token a `.env`:
   ```
   TELEGRAM_BOT_TOKEN=<token-de-botfather>
   ```
3. Arranca el bot (deja esa terminal abierta y ejecuta una sola instancia):
   ```bash
   .venv\Scripts\python -m app.telegram_bot
   ```
4. En Telegram envía `/start` a tu bot: responde con tu chat id.
5. Agrega el chat id a `.env` (varios, separados por comas). Sin esta variable el bot queda abierto a cualquiera y escribe un WARNING al iniciar:
   ```
   TELEGRAM_ALLOWED_CHAT_IDS=<tu-chat-id>
   ```
6. Detén el bot con `Ctrl+C` y reinícialo con el comando del paso 3.

Detalle: [docs/setup_telegram.md](docs/setup_telegram.md).

### g. Ejemplo de `.env` completo

Los valores son marcadores: reemplázalos por los tuyos.

```
# Gemini (obligatorio)
GEMINI_API_KEY=<tu-clave>
LLM_MODEL=gemini-3.5-flash-lite
LLM_MAX_RETRIES=5
LLM_MIN_SECONDS_BETWEEN_CALLS=4.0

# Google Drive y Sheets (opcional)
GOOGLE_OAUTH_CLIENT_SECRETS=secrets/client_secret.json
GOOGLE_OAUTH_TOKEN=secrets/token.json
DRIVE_FOLDER_ID=<id-de-la-carpeta>
SHEET_ID=<id-de-la-planilla>

# Redis del curso, RAG (opcional)
REDIS_URL=<url-de-redis-entregada-por-el-docente>
REDIS_PREFIX=<prefijo-de-tu-grupo>
# RAG_TOP_K=3
# RAG_THRESHOLD=0.75

# Telegram, demo (opcional)
TELEGRAM_BOT_TOKEN=<token-de-botfather>
TELEGRAM_ALLOWED_CHAT_IDS=<tu-chat-id>
```

Detalle: [docs/setup_llm.md](docs/setup_llm.md), [docs/setup_google.md](docs/setup_google.md), [docs/setup_redis.md](docs/setup_redis.md) y [docs/setup_telegram.md](docs/setup_telegram.md).

### h. Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `ModuleNotFoundError` al ejecutar un script o el notebook | Se usó el Python global en vez de `.venv` | Ejecuta con `.venv\Scripts\python ...` y selecciona el kernel de `.venv` en el notebook; si falta algún paquete, repite el `pip install -r requirements.txt` del punto a |
| Error de configuración que nombra `GOOGLE_OAUTH_CLIENT_SECRETS` o `GOOGLE_OAUTH_TOKEN` («se espera la ruta a un archivo .json, no el secreto») | La variable contiene el secreto del cliente (`GOCSPX-<...>`) o un valor que no termina en `.json` | Pon la ruta al archivo, por ejemplo `secrets/client_secret.json`; el secreto queda dentro del JSON |
| Mensaje de credenciales vencidas al guardar en Drive o Sheets | Con la app en modo Testing, el token caduca a los 7 días | Vuelve a ejecutar `.venv\Scripts\python scripts\google_auth.py` |
| Error 403 `access_denied` al autorizar | Tu cuenta no está en **Usuarios de prueba**, o el JSON pertenece a otro proyecto de Google Cloud | Agrega tu cuenta como usuario de prueba y descarga el JSON desde el mismo proyecto donde habilitaste las APIs y configuraste la pantalla de consentimiento |
| Error 404 en Drive o Sheets tras cambiar de cliente OAuth | `drive.file` solo ve lo que creó ese mismo cliente | Deja `DRIVE_FOLDER_ID` y `SHEET_ID` en blanco, ejecuta `scripts\google_auth.py` y luego `scripts\setup_google_resources.py` con `.venv\Scripts\python`, y actualiza ambos IDs en `.env` |
| El bot no responde a `/start`, o el log muestra `Conflict` | El proceso no está corriendo, o hay dos instancias del bot con el mismo token | Ejecuta `.venv\Scripts\python -m app.telegram_bot` y deja la terminal abierta; cierra cualquier otra instancia (otra terminal u otro equipo) y deja solo una |

Detalle: [Google](docs/setup_google.md), [LLM](docs/setup_llm.md), [Redis](docs/setup_redis.md) y [Telegram](docs/setup_telegram.md).

## Ficha de reproducción

Esta ficha reúne lo que otra persona necesita para repetir la ejecución: modelo, dependencias, variables y datos. Las celdas de la Sección 0 del notebook imprimen los mismos datos leídos del código y de la configuración, sin mostrar valores secretos.

### 1. Modelo del agente

| Campo | Valor |
|---|---|
| Proveedor | Google AI Studio (Gemini Developer API), capa gratuita |
| SDK | `google-genai==2.26.0` (SDK oficial) |
| ID exacto del modelo | `gemini-3.5-flash-lite`, confirmado por el autor el 2026-09-30. El código no lo escribe: lo lee de `LLM_MODEL`, y la celda siguiente imprime el valor configurado |
| Fuentes del modelo | <https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite> y <https://ai.google.dev/gemini-api/docs/pricing> |
| Un solo modelo | Todas las llamadas usan el mismo ID. El juez es una llamada aparte con prompt propio, no un modelo distinto |
| Bloque de alcance | `SECURITY_SCOPE_v3` se antepone a la instrucción de sistema de cada llamada de generación (garantía estructural en `LLMClient._generate`, `app/llm.py`); los embeddings no lo llevan porque no deciden ni redactan nada |
| Pausa y reintentos | `LLM_MIN_SECONDS_BETWEEN_CALLS` (4,0 s por defecto) y hasta `LLM_MAX_RETRIES` (5 por defecto) reintentos con espera exponencial (2 s, 4 s, hasta 60 s) ante 429 y 503; cada reintento queda como evento `RETRY` |

Parámetros de cada tipo de llamada (todos desde constantes de `app/llm.py`):

| Llamada | Prompt (ID) | Temperatura | Modo de salida |
|---|---|---|---|
| Extracción del recibo (`analizar_recibo`) | `ANALYZER_PROMPT_v1` | `EXTRACTION_TEMPERATURE` = 0,0 | JSON con esquema (`response_json_schema`) |
| Agente ReAct | `AGENT_PROMPT_v3` | `AGENT_TEMPERATURE` = 0,0 | *Function calling* nativo en modo `AUTO`; ejecución automática del SDK desactivada |
| Router | `ROUTER_PROMPT_v3` | `ROUTER_TEMPERATURE` = 0,0 | JSON con esquema; la ruta es un enum de cinco etiquetas |
| Juez | `JUDGE_PROMPT_v1` | `JUDGE_TEMPERATURE` = 0,0 | JSON con esquema `{veredicto, motivo, senales}` |
| Respuesta de conversación | `CHAT_PROMPT_v2` | `ANSWER_TEMPERATURE` = 0,0 | JSON con esquema `{respuesta, nombre_usuario}` |
| Respuesta de consulta de gastos | `QUERY_PROMPT_v2` | `ANSWER_TEMPERATURE` = 0,0 | Texto libre |
| Respuesta de política (RAG) | `RAG_PROMPT_v1` | `ANSWER_TEMPERATURE` = 0,0 | Texto libre con citas `[archivo §sección]`; los fragmentos van como dato |

No se fijan `thinking_level`, `top_p`, `top_k` ni el máximo de tokens de salida: rige el valor por defecto del modelo. Google recomienda una temperatura de 1,0 en Gemini 3 (<https://ai.google.dev/gemini-api/docs/gemini-3>); se usa 0,0 por reproducibilidad y la verificación real de la Etapa 3 lo confirmó (las extracciones con 0,0 coinciden con las de 1,0, sin bucles; ver `docs/dev_prompts.md`).

Prompts en uso, todos en `app/prompts.py` y registrados en `PROMPTS`: `SECURITY_SCOPE_v3` (en todas las llamadas de generación), `ANALYZER_PROMPT_v1`, `AGENT_PROMPT_v3`, `ROUTER_PROMPT_v3`, `CHAT_PROMPT_v2`, `QUERY_PROMPT_v2`, `RAG_PROMPT_v1` y `JUDGE_PROMPT_v1`. Se conservan por trazabilidad, sin uso en el flujo vigente: `SECURITY_SCOPE_v1` y `v2`, `AGENT_PROMPT_v1` y `v2`, `ROUTER_PROMPT_v1` y `v2`, `CHAT_PROMPT_v1` y `QUERY_PROMPT_v1`. `SMOKE_PROMPT_v1` solo lo usa la prueba de humo de `scripts/verify_stage_3.py`.

#### Embeddings y RAG (Etapa 15)

| Campo | Valor |
|---|---|
| Modelo de embeddings | `gemini-embedding-2` (ID estable, capa gratuita), con `output_dimensionality=768`; los vectores salen normalizados. No admite `task_type`: la tarea va en el texto (documentos `title: … \| text: …`, consultas `task: search result \| query: …`). Las constantes están en `app/config.py` (`EMBEDDING_MODEL`, `EMBEDDING_DIMS`) |
| Almacén | El Redis del curso (compartido; RediSearch), solo para el RAG y bajo el prefijo del grupo `REDIS_PREFIX`. La URL (con contraseña) va solo en `.env` como `REDIS_URL`. Pasos en `docs/setup_redis.md` |
| Índice | `{REDIS_PREFIX}:rag:idx` sobre HASH `{REDIS_PREFIX}:rag:chunk:*`; campos `chunk_id` y `fuente` (TAG), `seccion` y `texto` (TEXT) y `embedding` (VECTOR HNSW, FLOAT32, 768 dimensiones, COSINE) |
| Recuperación | `RAG_TOP_K` fragmentos (3 por defecto) y umbral `RAG_THRESHOLD` (0,75 por defecto, calibrado con `scripts/calibrate_rag_threshold.py`: peor acierto 0,7929 frente a mejor fallo 0,6988). Bajo el umbral el asistente se abstiene sin llamar al LLM de generación |
| Origen del corpus | `data/corpus/`: la política de rendición de gastos de una empresa **ficticia** («Consultora Andes Ficticia»), escrita para este proyecto; sintético, sin datos reales ni material de terceros (`data/corpus/README.md`). 3 documentos, 29 fragmentos (500 caracteres, solape 100) |

### 2. Modelo de desarrollo (declarado aparte)

El código del agente se desarrolló con Claude Code (aplicación de escritorio): orquestador `claude-opus-5-5` y subagentes `sonnet` como escritores. La Etapa 1 se hizo con Claude en claude.ai. Estaba planificado OpenCode con `meta/muse-spark-1.3` vía OpenRouter, y no se usó. El modelo de desarrollo no forma parte de la ejecución del agente y el revisor no lo necesita. Los prompts de desarrollo y la bitácora por etapa están en `docs/dev_prompts.md`.

### 3. Dependencias e instalación

Python 3.12 (el equipo del autor usa 3.12.3 en Windows 11). Todas las dependencias están fijadas en `requirements.txt`:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Incluye el SDK de Gemini (`google-genai`), el cliente de Redis (`redis`) y `numpy` (solo el RAG), las bibliotecas de Google Drive y Sheets, `pydantic`, `python-dotenv`, `Pillow` (solo para generar los recibos sintéticos; no es OCR), `nbformat`, `nbconvert` e `ipykernel` (notebook), `pytest` y `python-telegram-bot` (solo la demo de Telegram).

### 4. Variables de entorno (nombres y función, sin valores)

Se copian de `.env.example` a `.env`, que está en `.gitignore`. El notebook solo muestra si cada una está definida o falta.

| Variable | Función | Se necesita para |
|---|---|---|
| `GEMINI_API_KEY` | Clave gratuita de Google AI Studio (secreta). Pasos en `docs/setup_llm.md` | Las celdas con LLM de las Secciones 2 a 7, 9, 10 y 11 |
| `LLM_MODEL` | ID del modelo (`gemini-3.5-flash-lite`) | Igual que la anterior |
| `LLM_MAX_RETRIES` | Reintentos ante 429 y 503 (opcional, 5 por defecto) | Opcional |
| `LLM_MIN_SECONDS_BETWEEN_CALLS` | Pausa mínima entre llamadas (opcional, 4,0 por defecto) | Opcional |
| `GOOGLE_OAUTH_CLIENT_SECRETS` | Ruta al JSON del cliente OAuth de escritorio (secreta). Pasos en `docs/setup_google.md` | Drive y Sheets (Secciones 3 con Google, 7, 8, 9 y 10) |
| `GOOGLE_OAUTH_TOKEN` | Ruta del token OAuth (opcional; por defecto `secrets/token.json`) | Drive y Sheets |
| `DRIVE_FOLDER_ID` | Carpeta de prueba de Drive | Drive |
| `SHEET_ID` | Planilla de prueba de Sheets | Sheets |
| `REDIS_URL` | URL de conexión del Redis del curso, que entrega el docente e incluye la contraseña (secreta; solo en `.env`) | La ruta de política (RAG): Sección 11 y los casos `rag: true` del golden set |
| `REDIS_PREFIX` | Prefijo de grupo bajo el que vive todo el RAG (letras, números, guion y guion bajo) | Igual que la anterior |
| `RAG_TOP_K`, `RAG_THRESHOLD` | Fragmentos recuperados (3 por defecto) y umbral de similitud (0,75 por defecto); opcionales y no hace falta declararlos | Opcional |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | Token y lista de chats de la demo de Telegram | Solo la demo (`docs/setup_telegram.md`); el notebook no las usa |

### 5. Datos de prueba

`data/receipts/` contiene recibos **sintéticos**: `receipt_normal.jpg`, `receipt_hard.jpg`, `receipt_illegible.jpg` y `receipt_injection.jpg`, dibujados con `scripts/generate_receipts.py` (Pillow, semilla fija, comercios ficticios) y sin datos personales. `data/receipts/expected.json` declara los valores esperados por archivo. Los casos con Google generan en tiempo de ejecución un recibo único (`generate_unique_receipt`, comercio ficticio con sufijo de corrida) para no chocar con la deduplicación de la planilla. El golden set vigente es `eval/golden_set_v2.json` (los 13 casos de v1 más 4 del RAG); `eval/golden_set_v1.json` y su corrida real `eval/results_v1.json` se conservan. `data/corpus/` contiene el corpus **sintético** del RAG (una empresa ficticia, sin datos reales). En la capa gratuita Google puede usar los datos enviados para mejorar sus productos, por eso solo se envían recibos sintéticos (ver `docs/setup_llm.md`).

### 6. Cómo ejecutar

1. Instalar las dependencias (punto 3) y abrir `notebooks/demo.ipynb` con el kernel de `.venv` (*Run All*), o ejecutarlo desde la terminal: `.venv\Scripts\python -m jupyter nbconvert --to notebook --execute notebooks/demo.ipynb --output-dir <carpeta de salida>`. Hay que ejecutar las celdas en orden y desde cero.
2. Crear `.env` con `GEMINI_API_KEY` y `LLM_MODEL` (`docs/setup_llm.md`). Es lo único obligatorio para el flujo central.
3. Opcional: configurar Google (`docs/setup_google.md`) para que el agente guarde de verdad en Drive y Sheets.
4. Opcional: configurar el RAG (`docs/setup_redis.md`): definir `REDIS_URL` y `REDIS_PREFIX` en `.env` y **cargar el corpus antes de la Sección 11** con `.venv\Scripts\python scripts\load_corpus.py` (`--dry-run` solo fragmenta y muestra la firma; `--force` reconstruye solo el índice propio; si el corpus no cambió, la carga se omite).

Qué hace cada sección según lo que esté configurado:

| Sección | Sin `.env` | Solo Gemini | Gemini y Google |
|---|---|---|---|
| 0, 1 | Corren completas | Igual | Igual |
| 2, 4, 5, 6 | Muestran la configuración y omiten la celda con LLM | Ejecutan el LLM real | Igual (las Secciones 4, 5 y 6 dejan Google en blanco a propósito para no gastar cuota de Drive ni de Sheets) |
| 3 | Omite la celda del agente | El agente corre en modo degradado | Registra de verdad en Drive y Sheets |
| 7, 8, 9 | Corren las celdas sin red (estado, validación, veredictos fijos) y omiten las reales | Igual | Ejecutan además el ciclo real (escriben en la carpeta y la planilla de prueba) |
| 10 | Valida el golden set y muestra `eval/results_v1.json` | Igual | Igual (`RUN_EVAL = False` por defecto) |
| 11 (RAG) | Corre sin red el corpus, la fragmentación y las plantillas; omite la parte real | Igual (la parte real necesita además `REDIS_URL`, `REDIS_PREFIX` y el índice cargado) | Con Gemini y el Redis del curso: configuración real del índice y tres entradas (con recuperación, sin recuperar y fuera del corpus) |

**Sin Redis.** Solo se degrada el RAG: la ruta de política responde con honestidad que la base de conocimiento no está disponible (`rag_no_disponible`) y nada se simula; registrar recibos, consultar gastos y conversar siguen funcionando.

**Modo degradado (decisión A12).** Con solo la clave de Gemini el flujo central funciona: `analizar_recibo` corre de verdad y, si faltan la configuración o el token de Google, `guardar_recibo` y `registrar_gasto` devuelven un error estructurado que vuelve al LLM como observación; el agente responde con honestidad y nunca se simula un éxito de Drive o Sheets. Sin clave de Gemini las celdas con LLM se omiten con el aviso `omitido: …` y el notebook termina igual.

**Cuota.** La capa gratuita tiene límites por minuto y por día. Google no publica cifras fijas por modelo en la documentación (<https://ai.google.dev/gemini-api/docs/rate-limits>): cada cuenta consulta los suyos en <https://aistudio.google.com/rate-limit>. El notebook deja una pausa entre llamadas y reintenta ante 429. Después de la Sección 0 las secciones son independientes: si se agota el límite diario, se vuelve a ejecutar la Sección 0 y desde la sección interrumpida el día siguiente. La celda final del notebook, «Resumen de consumo», informa cuántas llamadas y tokens consumió la sesión.

## Pruebas

```powershell
# Pruebas offline (sin red ni credenciales)
.venv\Scripts\python -m pytest -q -m "not live"

# Pruebas en vivo contra la API real (consumen llamadas de la capa gratuita; requieren .env)
.venv\Scripts\python -m pytest -m live -v
```

Las pruebas `live` se omiten solas si faltan `GEMINI_API_KEY` o `LLM_MODEL` (y las de Drive y Sheets, si falta su configuración). Con `.env` completo, `pytest -q` sin filtro también las ejecuta; usa `-m "not live"` para evitarlo.

## Verificación real por etapa

Cada etapa que llama a una API externa tiene un script que imprime una línea final `RESULTADO: OK` o la falla. Consumen cuota de la capa gratuita y se ejecutan desde la raíz:

| Etapa | Script | Qué verifica | Necesita |
|---|---|---|---|
| 3 | `scripts/verify_stage_3.py` | Humo de texto, visión y temperatura 0,0 frente a 1,0 | Gemini |
| 4 | `scripts/verify_stage_4.py` | Sube un recibo a Drive y confirma el `file_id` con `files.get` | Google |
| 5 | `scripts/verify_stage_5.py` | Estado antes y después de `registrar_gasto` y la repetición sin duplicar | Google |
| 6 | `scripts/verify_stage_6.py` | Loop ReAct completo (con Google, o degradado sin él) | Gemini (Google opcional) |
| 7 | `scripts/verify_stage_7.py [--with-google]` | Segundo turno con el nombre del primero y prueba negativa | Gemini |
| 8 | `scripts/verify_stage_8.py [--with-google]` | Cinco casos de seguridad | Gemini |
| 9 | `scripts/verify_stage_9.py [--with-google]` | Una entrada por ruta del router | Gemini |
| 10 | `scripts/verify_stage_10.py` | Ciclo de memoria en cinco pasos | Gemini y Google |
| 11 | `scripts/verify_stage_11.py` | Juez: caso benigno y adversarial | Gemini y Google |

Preparación de Google (una sola vez; detalle en `docs/setup_google.md`):

```powershell
.venv\Scripts\python scripts\google_auth.py
.venv\Scripts\python scripts\setup_google_resources.py
```

Regenerar los recibos sintéticos: `.venv\Scripts\python scripts\generate_receipts.py`.

## Evaluación con golden set (Etapa 12)

```powershell
.venv\Scripts\python eval\run_eval.py --system-version v1 --out eval\results_v1.json
.venv\Scripts\python eval\run_eval.py --system-version v1 --out eval\results_v1.json --resume
```

Desde la Etapa 15 el golden set por defecto es el **v2** (`eval/golden_set_v2.json`), que agrega 4 casos del RAG (GS11 a GS14, `rag: true`, necesitan el Redis del curso): `.venv\Scripts\python eval\run_eval.py --system-version v2 --out eval\results_v2.json`. Sin `REDIS_URL` y `REDIS_PREFIX` esos casos quedan `PENDIENTE` y con `--no-rag` quedan `OMITIDO`.

La corrida v1 pasó 13 de 13 casos (100 %), con 65 llamadas al LLM y 119.912 tokens, sin interrupciones. **La corrida del golden set v2 (17 casos) sobre el sistema con RAG está pendiente** y no se cita como resultado. Detalle, criterios y política de versionado en `docs/evaluation.md` y en `eval/results_v1.json`. La Sección 10 del notebook valida el golden set y muestra ese resultado; no vuelve a ejecutarlo salvo que se cambie `RUN_EVAL` a `True`.

## Demo de Telegram (Etapa 13)

Demo aparte, no evaluada en el notebook. Reutiliza el mismo `ExpenseAssistant.handle` que el notebook. Con `TELEGRAM_BOT_TOKEN` (y opcionalmente `TELEGRAM_ALLOWED_CHAT_IDS`) en `.env`:

```powershell
.venv\Scripts\python -m app.telegram_bot
```

Creación del bot con BotFather y prueba manual en `docs/setup_telegram.md`.

## Consumo medido

Las llamadas se miden con los contadores del propio código (`LLMClient.stats` por cliente y `session_stats()` para toda la sesión del notebook; la última celda del notebook imprime el total). Una «llamada» es una solicitud lógica; cada reintento ante 429 o 503 se cuenta aparte.

| Ejecución | Llamadas LLM | Reintentos | Tokens | Duración | Fuente |
|---|---|---|---|---|---|
| Golden set v1 (13 casos, `eval/run_eval.py`) | 65 | 0 | 119.912 | 14 min 38 s (12:53:51 a 13:08:29, -03:00) | `eval/results_v1.json` (medido) |
| Notebook completo (Secciones 0 a 11, `RUN_EVAL = False`), con Gemini, Google y el Redis del curso | 80 de generación (0 fallidas) + 2 de embeddings | 6 (ningún 429 por cuota) | 163.016 | ~22 min (1.332 s) | Celda «Resumen de consumo» de `notebooks/demo_executed.ipynb` (2026-10-02) |
| Corrida anterior, sin RAG (Secciones 0 a 10) | 73 (2 fallidas tras agotar reintentos) | 42, todos 503 `UNAVAILABLE` | 137.042 | ~24 min (1.450 s) | 2026-10-01; reemplazada por la fila anterior |

Referencia de las verificaciones reales anteriores, ya registradas en `docs/dev_prompts.md`: las celdas equivalentes del notebook consumieron 3 llamadas (Sección 2), 5 (Etapa 6, con Google), 9 (Etapa 7), 8 (Etapa 8), 10 (Etapa 9), 18 (Etapa 10) y 14 (Etapa 11), 67 en total. Las de las Etapas 6 a 10 se midieron antes de agregar el juez, que suma una llamada por cada análisis de recibo; por eso el total del notebook completo será mayor. **[SUPUESTO]** Es una referencia, no una medición del notebook final.

**Comparación con los límites gratuitos.** Los límites dependen del modelo y de la cuenta, y Google no publica cifras fijas por modelo en su documentación ([rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)). Cada cuenta consulta los suyos en [AI Studio](https://aistudio.google.com/rate-limit); este repositorio no inventa cifras. Observación del autor en AI Studio: **pendiente**. El agente de desarrollo no tiene acceso a la cuenta del autor, así que no se registra ninguna cifra.

Resultado frente al consumo (observado el 2026-10-01): en la misma jornada se ejecutaron el notebook completo (73 llamadas), el golden set (65) y las verificaciones de las Etapas 3 a 11, y no apareció ningún 429 por cuota con `gemini-3.5-flash-lite`. Los únicos 429 de todo el desarrollo ocurrieron en la primera prueba de la Etapa 3, con un ID de modelo equivocado. Sí aparecieron errores 503 `UNAVAILABLE`, que son sobrecarga transitoria del servicio de Google: en la corrida del notebook dos llamadas fallaron tras 5 reintentos, y el notebook lo informó con honestidad, sin inventar datos. Si al revisor le pasa lo mismo, basta con volver a ejecutar esa celda o subir `LLM_MAX_RETRIES` en `.env`.

**Si se agota el límite diario.** Después de la Sección 0 las secciones del notebook son independientes: se ejecuta la Sección 0 y luego solo las secciones pendientes (por ejemplo, 2 a 6 un día y 7 a 10 el siguiente; cada celda con LLM se omite sola si falta la clave). El golden set se reanuda con `--resume` (los casos cortados por cuota quedan `PENDIENTE`, nunca `FALLIDO`).

## Avance por etapas

| # | Etapa | Estado |
|---|---|---|
| 1 | Caso, criterio de éxito y arquitectura | Entregada |
| 2 | Proyecto Python base y trazador | Completada |
| 3 | LLM con visión y `analizar_recibo` | Completada |
| 4 | `guardar_recibo` (Drive) | Completada |
| 5 | `registrar_gasto` (Sheets) | Completada |
| 6 | Loop ReAct | Completada |
| 7 | Historial simple | Completada |
| 8 | Seguridad basal | Completada |
| 9 | Router | Completada |
| 10 | Memoria avanzada | Completada |
| 11 | Juez LLM | Completada |
| 12 | Golden set | Completada (v1: 13/13) |
| 13 | Demo Telegram | Completada (prueba manual parcial del 2026-10-02; ver `docs/trace_examples.md` §8) |
| 14 | Notebook final y entrega | Completada; pendientes del autor: límites en AI Studio y la línea de `.env.example` |
| 15 | RAG con el Redis del curso (bono +1,0) | Completada (RAG verificado en real el 2026-10-02: `verify_stage_15.py` OK y `pytest -m live` 4 passed); golden set v2: 17/17 |

## Entregables

Entrega mínima del prompt maestro (Etapa 14) y el archivo que la cubre:

| Entregable del prompt maestro | Archivo en el repositorio |
|---|---|
| `.ipynb` | `notebooks/demo.ipynb` (sin salidas; la copia ejecutada con credenciales reales, si se adjunta, es `notebooks/demo_executed.ipynb`) |
| `requirements.txt` | `requirements.txt` |
| `data/` con las imágenes de prueba | `data/receipts/` y `data/README.md` |
| `prompts.py` | `app/prompts.py` |
| Trazas | `docs/trace_examples.md` (extractos de trazas reales); las trazas completas se generan en `traces/` al ejecutar (ignoradas por git) |
| `docs/opencode_prompts.md` | `docs/dev_prompts.md` (por la adenda A1 se reemplaza el nombre del archivo y el desarrollador) |
| Ficha de reproducción | Este README y la Sección 0 del notebook |
| Acceso al LLM | `docs/setup_llm.md` |
| Checklist de la rúbrica | `docs/checklist_rubrica.md` |
| Resultados del golden set | `eval/golden_set_v1.json` y `eval/results_v1.json` (corrida real v1), `eval/golden_set_v2.json` y `eval/results_v2.json` (vigente; corrida real v2: 17/17) y `docs/evaluation.md` |
| Configuración del Redis del curso y corpus del RAG | `docs/setup_redis.md` y `data/corpus/` |
