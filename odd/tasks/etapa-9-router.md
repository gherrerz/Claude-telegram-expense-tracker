# Etapa 9 — Workflow router — BONO +1,0

**Objetivo:** una llamada LLM previa al loop clasifica la entrada en `REGISTRAR_RECIBO`, `CONSULTAR_GASTOS`, `CONVERSACION` o `FUERA_DE_ALCANCE`, y cada ruta ejecuta un camino distinto con efecto observable.
**Criterio de rúbrica:** bono "Workflow adicional" +1,0. Exige trazas de la ruta elegida y de su efecto ejecutado (TF p.2).
**Decisión de diseño (orquestador):** `CONSULTAR_GASTOS` responde desde el `AgentState` sin tools de escritura. Mientras la Etapa 10 no lo complete, el estado parte vacío y la respuesta lo dice con honestidad. El router no es un filtro de seguridad: el alcance y los rieles siguen activos en todas las rutas.
**Ruta:** delegated direct. Rama `feat/etapa-9-router`.
**TDD:** desactivado; pruebas offline y `live`.

## Tareas
- [x] T1 `ROUTER_PROMPT_v1` y `app/router.py`: salida estructurada con etiqueta y motivo, temperatura 0, alcance incluido, ruta de respaldo segura y evento `ROUTE`.
- [x] T2 Punto de entrada único (`app/assistant.py`), que despacha según la ruta y mantiene el historial en todas.
- [x] T3 Pruebas offline: cada ruta ejecuta su camino, solo `REGISTRAR_RECIBO` habilita tools y una etiqueta inválida cae al respaldo.
- [x] T4 Prueba `live` y `scripts/verify_stage_9.py`: 4 entradas, una por ruta, más "Hola".
- [x] T5 Sección 6 del notebook, `docs/bonos.md` y bitácora.
- [x] T6 Verificación real: `verify_stage_9.py` OK (4 de 4 rutas correctas, con efecto observable); `pytest -m live` 4 passed.

## Evidencia
- T1: `ROUTER_PROMPT_v1`, `CHAT_PROMPT_v1`, `QUERY_PROMPT_v1` en `app/prompts.py`; `app/router.py` (enum, temperatura 0.0, respaldos, evento `ROUTE`). Observado: `tests/test_stage9_router.py` verde (parseo de cada etiqueta, JSON inválido, etiqueta desconocida, falla del LLM, entrada vacía sin llamada).
- T2: `app/assistant.py` (`ExpenseAssistant.handle`, `text_history`, `ROUTE_CASES`, `evaluate_route_case`). Rechazo de `FUERA_DE_ALCANCE` como texto fijo en código.
- T3: pruebas offline: `GEMINI_API_KEY= LLM_MODEL= ... python -m pytest -q -m "not live"`: 290 passed, 18 deselected (incluye las 31 de la Etapa 9; las de las Etapas 2 a 8 siguen verdes).
- T4: `tests/test_stage9_live.py` (4 omitidas sin Gemini) y `scripts/verify_stage_9.py`: sin clave sale con código 2 y sin llamadas de red. Ejecución real: pendiente (T6).
- T5: Sección 6 del notebook (nbconvert sin credenciales: celda "omitido"), `docs/bonos.md`, `docs/architecture.md`, README y bitácora (IMPLEMENTADA — VERIFICACIÓN REAL PENDIENTE).
- Ruta: delegated direct (un escritor, `sonnet`). Sin commit: lo decide el orquestador.
