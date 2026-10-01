# Etapa 10 — Memoria avanzada — BONO +1,0

**Objetivo:** un `AgentState` estructurado, distinto del historial bruto, con estado inicial, actualizaciones (`MEMORY_UPDATE`) y dos usos posteriores: responder "¿cuánto llevo en Supermercado?" desde el estado, y detectar un recibo duplicado para pedir confirmación antes de registrarlo de nuevo.
**Criterio de rúbrica:** bono "Memoria avanzada" +1,0. No suma si solo reenvía mensajes o guarda algo que nunca usa (TF p.2).

## Decisiones de diseño (orquestador)
1. **Quién actualiza el estado.** El código lo actualiza a partir de resultados observados, no de lo que diga el LLM:
   - totales, últimos gastos y recibos registrados, cuando `registrar_gasto` confirma la escritura;
   - el nombre, con una salida estructurada de la ruta `CONVERSACION`.
2. **Duplicado.** La clave es el hash de la imagen más comercio, fecha y monto. Se detecta en código antes de `guardar_recibo`, así no se sube otra copia a Drive. El riel bloquea y pide confirmación al usuario.
3. **Confirmación del usuario** (cierra el hueco de la Etapa 6):
   - Cuando un riel pide confirmación (duplicado o baja confianza), queda una confirmación pendiente en el estado.
   - En un turno POSTERIOR, el LLM puede reintentar con `confirmado_por_usuario=true`, y el código solo lo acepta si hay una confirmación pendiente de un turno anterior. Nunca dentro del mismo turno.
   - Si lo confirmado es un duplicado, `registrar_gasto` se llama con `permitir_duplicado=True`.
   - La llamada por defecto sigue siendo idempotente, así que el bono de acción de la Etapa 5 se mantiene.
4. **Persistencia en JSON.** Opcional; no se implementa en esta etapa y se documenta así.

**Ruta:** delegated direct. Rama `feat/etapa-10-memory`.
**TDD:** desactivado; pruebas offline y `live`.

## Tareas
- [x] T1 `app/memory.py`: operaciones sobre `AgentState` (registro, nombre, duplicado, pendiente) que emiten `MEMORY_UPDATE` con el antes y el después.
- [x] T2 Integración: rieles de duplicado y confirmación en el agente, `permitir_duplicado` en Sheets, nombre en la ruta `CONVERSACION` y consulta desde el estado.
- [x] T3 Pruebas offline del ciclo completo.
- [x] T4 `scripts/verify_stage_10.py` y prueba `live`, con un recibo sintético único generado en tiempo de ejecución.
- [x] T5 Sección 7 del notebook, `docs/bonos.md` y bitácora.
- [x] T6 Verificación real: `verify_stage_10.py` OK (los 5 pasos, filas 5 y 6, duplicado confirmado en un turno posterior); `pytest -m live` 1 passed.

## Evidencia
Escritor `sonnet`, ruta delegated direct. Sin commits (los hace el orquestador).

- **T1** `app/memory.py` (`record_expense`, `set_user_name`, `valid_user_name`, `receipt_key`/`build_key`/`image_hash`, `is_duplicate`, `existing_row`, `set_pending_confirmation`, `clear_pending_confirmation`, `state_snapshot`, `total_general`). Modelos nuevos en `app/models.py`: `PendingConfirmation` y los campos `filas_por_recibo` y `confirmacion_pendiente` de `AgentState` (las pruebas de la Etapa 2 siguen verdes). Desviación del encargo: `ultimos_gastos` queda con el más reciente AL FINAL (no primero), porque así lo fijan el validador de la Etapa 2, `AgentState.add_expense` y `QUERY_PROMPT`.
- **T2** `app/agent.py` (rieles `_confirmation_gate`, restauración del análisis pendiente, `record_expense` tras escritura exitosa, `state=` en `run`), `app/assistant.py` (estado por conversación, `_chat` estructurado, consulta con total calculado), `app/router.py` (contexto `<confirmacion_pendiente>`), `app/tools/sheets.py` (`permitir_duplicado`, solo el valor exacto `True`). Prompts versionados: `AGENT_PROMPT_v3`, `ROUTER_PROMPT_v2`, `CHAT_PROMPT_v2`, `QUERY_PROMPT_v2` (las anteriores se conservan). Se actualizaron los identificadores de prompt en `tests/test_stage6_agent.py`, `tests/test_stage8_security.py` y `tests/test_stage9_router.py`; ninguna otra expectativa cambió.
- **T3** `tests/test_stage10_memory.py`: 35 pruebas (funciones y eventos, ciclo completo por el asistente, regla de turno, baja confianza, duplicado de la planilla, nombre, prompts, declaraciones, `permitir_duplicado`).
- **T4** `scripts/verify_stage_10.py`, `tests/test_stage10_live.py`, `app/memory_demo.py` (ciclo y condiciones compartidos) y `generate_unique_receipt` en `scripts/generate_receipts.py`.
- **T5** Sección 7 del notebook (markdown + celda offline que siempre corre + celda real condicionada), `docs/bonos.md` (fila y sección de mecanismo y evidencia), `docs/architecture.md`, `README.md` (fila 10) y `docs/dev_prompts.md` (bitácora, estado IMPLEMENTADA — VERIFICACIÓN REAL PENDIENTE).
- **Verificación offline (sin variables de entorno):**
  - `pytest -q -m "not live"`: `325 passed, 19 deselected`.
  - `nbconvert --execute` del notebook: sin errores; la celda offline de la Sección 7 muestra estado inicial, `MEMORY_UPDATE`, los dos usos y la regla de turno; la celda real indica `omitido` y qué falta.
  - `scripts/verify_stage_10.py`: código de salida 2 con el mensaje de configuración faltante; `verify_stage_6` a `verify_stage_9`: código 2 (configuración), sin errores de importación.
- **Pendiente (T6):** ejecución real con Gemini, Drive y Sheets de `scripts/verify_stage_10.py` y `pytest -m live tests/test_stage10_live.py`.
  Riesgos a confirmar en vivo: (1) el router debe clasificar "Sí, regístralo de todas formas" como `REGISTRAR_RECIBO` con la pendiente como contexto; (2) el LLM debe usar `confirmado_por_usuario` solo en el turno posterior (si lo hace antes, el riel lo rechaza y la respuesta lo refleja); (3) la categoría del recibo único la decide el LLM (la consulta usa la categoría realmente registrada); (4) el esquema `{respuesta, nombre_usuario}` con `nombre_usuario` como cadena; (5) la extracción debe devolver el monto exacto del recibo único.
