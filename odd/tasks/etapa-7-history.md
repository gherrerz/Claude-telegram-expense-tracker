# Etapa 7 — Historial simple

**Objetivo:** el agente mantiene la lista de mensajes de la conversación y la reenvía al LLM en cada turno. En el turno 2 usa un dato del turno 1 (el nombre) sin que esté fijado en código.
**Criterio de rúbrica:** Historial simple (0,5).
**Ruta:** delegated direct. Rama `feat/etapa-7-history`.
**TDD:** desactivado; pruebas offline y `live`.
**Fuera de alcance:** registrar después de que el usuario confirme un recibo de baja confianza en un turno posterior. Necesita estado estructurado y se resuelve en la Etapa 10 (memoria avanzada).

## Tareas
- [x] T1 `Conversation`: historial por conversación (contenidos del modelo intactos, llamadas a tools y observaciones) e IDs de imagen por turno.
- [x] T2 `run()` acepta la conversación y la reenvía completa; la traza registra el tamaño del historial enviado.
- [x] T3 Pruebas offline: el turno 2 recibe el turno 1; prueba negativa sin historial; el nombre no está en el código.
- [x] T4 Prueba `live` y `scripts/verify_stage_7.py` (sin Google, para no gastar cuota de Drive): turno 1 "Me llamo Diego", turno 2 imagen y "Registra este recibo"; prueba negativa.
- [x] T5 Sección 4 del notebook y bitácora.
- [x] T6 Verificación real: `verify_stage_7.py` OK (el turno 2 usa "Diego" y la prueba negativa no); `pytest -m live` 2 passed.

## Evidencia
- T1: `app/conversation.py` (`Conversation`: `contents`, `turn`, registro `img_N`, `summary()` con enmascarado).
- T2: `ExpenseAgent.run(conversation=...)`; traza `turn` / `history_messages` en `USER_INPUT` y `LLM_DECISION`; `AGENT_PROMPT_v2`. Con `max_steps`/`error_llm`/`respuesta_vacia` se agrega el texto seguro al historial.
- T3: `tests/test_stage7_history.py`, 15 pruebas offline (turno 2 recibe el turno 1, negativa, 3 turnos con call/response, identidad del `Content`, traza, nombre ausente de `app/`).
- T4: `tests/test_stage7_live.py` (2 pruebas, se omiten sin Gemini) y `scripts/verify_stage_7.py` (sin Google por defecto; exit 2 sin configuración de Gemini, comprobado).
- T5: Sección 4 del notebook (ejecutado sin credenciales: "omitido") y bitácora en `docs/dev_prompts.md`.
- Pytest offline con variables vaciadas: ver reporte del escritor (todas pasan).
- T6 abierta: verificación real pendiente (la ejecuta el orquestador).
