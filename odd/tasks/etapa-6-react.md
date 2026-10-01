# Etapa 6 — Loop ReAct (CRÍTICA para la rúbrica)

**Objetivo:** un loop explícito en `app/agent.py`. El LLM decide, se ejecuta la tool, la observación vuelve a los mensajes y el LLM decide de nuevo, con function calling nativo y parada explícita.
**Criterio de rúbrica:** ReAct integrado (1,0). Si falla en la revisión, la nota tiene tope 3,0 (TF p.4).
**Decisión del autor (2026-10-01, cierra A10):** degradación controlada sin simulaciones. Con solo la clave de Gemini, el flujo central funciona: `analizar_recibo` corre de verdad, y si faltan las credenciales de Google, `guardar_recibo` y `registrar_gasto` devuelven un error estructurado. Ese error es una observación que el LLM usa para responder con honestidad.
**Ruta:** delegated direct. Rama `feat/etapa-6-react`.
**TDD:** desactivado; pruebas offline con LLM falso y verificación `live`.

## Tareas
- [x] T1 `AGENT_PROMPT_v1` en `app/prompts.py` (con `SECURITY_SCOPE_v1`), incluida la regla de pedir confirmación ante confianza baja o categoría ambigua.
- [x] T2 Soporte de function calling en `app/llm.py`: declaraciones, respuesta con `function_calls`, historial que preserva las firmas de pensamiento y traza.
- [x] T3 `app/agent.py`: loop, despacho de tools, `MAX_STEPS=6`, eventos `STOP` con motivo y rieles de código (la URL de `registrar_gasto` tiene que venir de `guardar_recibo` en la misma ejecución).
- [x] T4 Pruebas offline: flujo normal, parada por respuesta, parada por `MAX_STEPS`, confianza baja, degradación sin Google y orden decidido por el LLM.
- [x] T5 `scripts/verify_stage_6.py`, prueba `live` y Sección 3 del notebook.
- [x] T6 Bitácora (decisión A12) y verificación real. Con Google: OK (fila 4, 5 llamadas). Sin Google: degradación honesta OK. `pytest -m live` 1 passed.

## Evidencia
- Ruta: delegated direct (un escritor `sonnet`). Disparador: 2+ archivos no triviales.
- T1: `AGENT_PROMPT_v1` registrado en `PROMPTS`; `CONFIDENCE_THRESHOLD = 0.7` en `app/models.py`.
- T2: `LLMClient.generate_with_tools` (modo AUTO, AFC desactivado, traza `LLM_DECISION` con `decision`). Contenido del modelo reenviado sin cambios; observaciones como `Part(function_response=FunctionResponse(id, name, response))` en `Content(role="user")`.
- T3: `app/agent.py` (`ExpenseAgent`, `MAX_STEPS = 6`, `STOP` con motivos `respuesta_final`, `max_steps`, `error_llm`, `respuesta_vacia`, rieles de código).
- T4: `tests/test_stage6_agent.py`, 22 pruebas offline. Suite completa con entorno vacío: `206 passed, 7 deselected`.
- T5: `scripts/verify_stage_6.py` (sin configuración: código 2), `tests/test_stage6_live.py` y Sección 3 del notebook. `nbconvert` con entorno vacío: OK (ejecución real omitida).
- T6 (abierta): falta la verificación real con Gemini (y Google si está configurado) y confirmar `AGENT_TEMPERATURE = 0.0`.
- Decisión A12 registrada en `docs/dev_prompts.md` (adenda y bitácora, estado IMPLEMENTADA — VERIFICACIÓN REAL PENDIENTE).
