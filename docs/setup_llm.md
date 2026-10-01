# Acceso al LLM: clave gratuita de Google AI Studio

El agente usa un solo proveedor y un solo modelo: Gemini, a través del SDK oficial `google-genai` y la capa gratuita de Google AI Studio. No hace falta tarjeta de crédito. Esta guía explica cómo obtener la clave, configurarla y comprobar que funciona.

## 1. Crear la clave

1. Inicia sesión con una cuenta Google en [Google AI Studio](https://aistudio.google.com/apikey).
2. Crea una clave de API desde esa página (el botón de crear clave) y cópiala. **[SUPUESTO]** Los nombres exactos de los botones pueden variar con la versión de la interfaz; la página indicada es la de gestión de claves.
3. Trata la clave como una contraseña: no la pegues en el código, en el notebook, en una captura ni en un mensaje. Si la expones por error, elimínala en AI Studio y crea otra.

## 2. Configurar el entorno

Copia `.env.example` a `.env` (el archivo está en `.gitignore`) y completa dos variables:

```
GEMINI_API_KEY=<tu clave de AI Studio>
LLM_MODEL=gemini-3.5-flash-lite
```

`gemini-3.5-flash-lite` es el ID de modelo confirmado por el autor el 2026-09-30 (fuentes en [la ficha del modelo](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) y [la página de precios](https://ai.google.dev/gemini-api/docs/pricing)). El código no escribe el ID: lo lee de `LLM_MODEL`. Las variables opcionales `LLM_MAX_RETRIES` y `LLM_MIN_SECONDS_BETWEEN_CALLS` ajustan los reintentos ante 429 y la pausa entre llamadas (ver `.env.example`).

Con solo estas dos variables el flujo central del notebook funciona: Drive y Sheets son opcionales (ver `docs/setup_google.md` y el modo degradado en el README).

## 3. Comprobar que funciona

Desde la raíz del repositorio, en PowerShell:

```powershell
# Verificación real mínima: una llamada de texto, una de visión y los 3 recibos (unas 8 llamadas)
.venv\Scripts\python scripts\verify_stage_3.py

# O solo las pruebas en vivo de la Etapa 3
.venv\Scripts\python -m pytest -m live tests/test_stage3_live.py -v
```

Las pruebas sin `live` y las celdas del notebook no necesitan clave: las llamadas reales se omiten con un aviso.

## 4. Datos que se envían: solo recibos sintéticos

En la capa gratuita de la API de Gemini, Google puede usar los datos enviados para mejorar sus productos (ver los [términos de la API de Gemini](https://ai.google.dev/gemini-api/terms), en su versión vigente). Por eso este proyecto solo envía **recibos sintéticos** (`data/receipts/`, generados con `scripts/generate_receipts.py`, con comercios ficticios). No envíes fotos de recibos reales ni datos personales.

## 5. Límites de uso gratuitos

La capa gratuita limita las solicitudes por minuto, los tokens por minuto y las solicitudes por día. Los límites dependen del modelo y de la cuenta, y pueden cambiar. Fuentes oficiales:

- Documentación: <https://ai.google.dev/gemini-api/docs/rate-limits>
- Los límites **de tu cuenta**, en AI Studio: <https://aistudio.google.com/rate-limit>

Google no publica en esas páginas cifras fijas por modelo, así que este repositorio no las cita: quien revisa consulta sus propios límites en AI Studio y los compara con el consumo medido (ver «Consumo medido» en el `README.md`). La documentación consultada en la Etapa 3 está listada en `docs/dev_prompts.md`.

Cómo se comporta el proyecto frente a los límites:

- `LLM_MIN_SECONDS_BETWEEN_CALLS` deja una pausa mínima entre llamadas (4,0 s por defecto).
- Ante 429 (`RESOURCE_EXHAUSTED`) o 503 (`UNAVAILABLE`) reintenta hasta `LLM_MAX_RETRIES` veces con espera exponencial (2 s, 4 s, 8 s, hasta 60 s). Cada reintento queda como evento `RETRY` en la traza.
- Si los reintentos se agotan, la celda informa que la API falló y el notebook continúa. En el golden set el caso queda `PENDIENTE` (no `FALLIDO`) y la corrida se reanuda con `--resume` (ver `docs/evaluation.md`).
- Si se agota el límite diario, ejecuta el notebook por secciones: después de la Sección 0 son independientes (ver la ficha de reproducción en el README).

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| Celdas con `omitido: falta GEMINI_API_KEY/LLM_MODEL` | `.env` ausente o con alguna de las dos variables vacía. La celda de la Sección 0 muestra cuáles faltan (sin valores). |
| 429 `RESOURCE_EXHAUSTED` repetido | Límite por minuto o por día agotado, o un `LLM_MODEL` distinto del confirmado. Observado: con `gemini-3.5-flash` (ID erróneo) la primera verificación de la Etapa 3 recibió 429 en todos los reintentos; con `gemini-3.5-flash-lite` pasó (ver `docs/trace_examples.md`). Verifica el ID y, si es el correcto, aumenta `LLM_MIN_SECONDS_BETWEEN_CALLS`, espera o retoma al día siguiente. |
| 400/403 al llamar | Clave inválida, eliminada o restringida. Crea otra en AI Studio. |
