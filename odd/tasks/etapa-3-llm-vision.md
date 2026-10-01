# Etapa 3 — LLM con visión y tool `analizar_recibo`

**Objetivo:** cliente LLM único con control de límites, prompts versionados y la tool `analizar_recibo` con salida validada por schema.
**Criterio de rúbrica:** LLM real y trazabilidad (modelo, configuración, prompts y traza de cada llamada).
**Modelo confirmado por el autor (2026-09-30):** `gemini-3.5-flash-lite`. SDK `google-genai==2.26.0`.
**Ruta:** delegated direct (writer trigger: 2+ archivos no triviales). Rama `feat/etapa-3-llm-vision`.
**TDD:** desactivado; pruebas funcionales con `pytest` (offline con cliente falso, y en vivo con marca `live`).
**Restricciones:**
- No existe `.env`, así que las llamadas reales quedan pendientes (adenda A2/A7).
- `.env.example` no es editable por el agente: el autor fija `LLM_MODEL=gemini-3.5-flash-lite`.

## Tareas
- [x] T1 Recibos sintéticos (normal, difícil e ilegible), `expected.json`, script generador y `data/README.md`.
- [x] T2 `app/prompts.py`: `SECURITY_SCOPE_v1` mínimo y `ANALYZER_PROMPT_v1` (el texto de la imagen es dato).
- [x] T3 `app/llm.py`: reintentos ante 429 con evento `RETRY`, pausa mínima, contadores y traza de modelo, parámetros y tokens.
- [x] T4 `app/tools/analyzer.py`: `analizar_recibo` con salida validada y `"desconocido"` para lo ilegible.
- [x] T5 Pruebas offline, pruebas `live` y `scripts/verify_stage_3.py` (humo de texto, visión y temperatura).
- [x] T6 Sección 2 del notebook (corre sin `.env`: omite las llamadas reales con un aviso).
- [x] T7 Bitácora en `docs/dev_prompts.md` (el commit lo hace el orquestador).
- [ ] T8 Verificación real con la clave del autor (pendiente de `.env`).

## Evidencia
- `pip install -r requirements.txt`: instala `google-genai==2.26.0` y `Pillow==12.3.0` sin errores.
- `GEMINI_API_KEY= LLM_MODEL= python -m pytest -q`: 86 passed, 4 skipped (las 4 `live`, "falta GEMINI_API_KEY/LLM_MODEL").
- `GEMINI_API_KEY= LLM_MODEL= python -m jupyter nbconvert --to notebook --execute notebooks/demo.ipynb`: ejecuta de principio a fin; la última celda imprime "omitido: falta GEMINI_API_KEY/LLM_MODEL".
- `GEMINI_API_KEY= LLM_MODEL= python scripts/verify_stage_3.py`: sale con código 2 y el mensaje de variables faltantes, sin red.
- Generador determinista: dos ejecuciones producen JPG idénticos (md5). Revisión visual: normal y difícil legibles; ilegible sin fecha ni total legibles.
- **Incidente (pytest sin aislar el entorno):** a mitad de la etapa apareció un `.env` del autor y un `pytest -q` ejecutó las pruebas `live` contra la API real (el agente nunca abrió `.env`). Traza `traces/live-stage3.jsonl` (modelo registrado: `gemini-3.5-flash`, **no** `-lite`): la llamada de texto con temperatura 0.0 terminó OK tras 3 reintentos por 429 (550 tokens: 195 prompt, 16 salida, 339 de razonamiento; 41 s); la llamada de visión sobre `receipt_normal.jpg` agotó 5 reintentos con 429 (`RESOURCE_EXHAUSTED`); la de `receipt_hard.jpg` no terminó. No hay resultado de extracción real todavía.
- Cambio de una prueba de la Etapa 1: `test_no_secrets_committed` ahora omite `.env` y `.env.*` (están en `.gitignore`), y su mensaje ya no incluye contenido.

## Pendiente de verificación real (T8)
`LLM_MODEL=gemini-3.5-flash-lite` en `.env`; luego `scripts/verify_stage_3.py` y `pytest -m live`.
