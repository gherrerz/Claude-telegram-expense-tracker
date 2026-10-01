# Etapa 8 — Seguridad basal

**Objetivo:** `SECURITY_SCOPE_v2` en toda llamada al LLM que decide o responde, y rechazo seguro con cero tool calls ante pedidos fuera de alcance o jailbreaks simples, verificado en la traza.
**Criterio de rúbrica:** Seguridad básica (0,5). Si se rompe en la revisión, se pierden esos 0,5 (TF p.4).
**Ruta:** delegated direct. Rama `feat/etapa-8-security`.
**TDD:** desactivado; pruebas offline y `live`.

## Tareas
- [x] T1 Revisar y reforzar el bloque de alcance. Garantía estructural: el cliente LLM no puede llamar sin el bloque.
- [x] T2 Sanear los errores de las tools que llegan al usuario: sin rutas, comandos ni pistas internas.
- [x] T3 Pruebas offline: inclusión del bloque en todas las llamadas y rieles.
- [x] T4 Prueba `live` y `scripts/verify_stage_8.py`: transferencia, borrado, filtración del prompt, fuera de tema y una inyección combinada con un recibo.
- [x] T5 Sección 5 del notebook y bitácora.
- [ ] T6 Verificación real (la ejecuta el orquestador).

## Evidencia
- T1: la v1 no cubría el alcance explícito, las 3 tools, la prohibición de revelar configuración/claves, los resultados de tools como dato ni el rechazo seguro. Se creó `SECURITY_SCOPE_v2` (v1 queda en `PROMPTS`; adenda A13). `compose_system_instruction` siempre antepone `ACTIVE_SECURITY_SCOPE` y rechaza un bloque de alcance como rol; `LLMClient._generate` verifica el prefijo y registra `security_scope_id` también en `LLM_DECISION` fallidas.
- T2: `app/security.py` (lista blanca de prefijos + patrones de fuga + red de seguridad final) y `_Dispatcher` en `app/agent.py`. El LLM recibe `{"ok": false, "error": "servicio_no_disponible", "detalle": ...}`; el detalle original va a `TOOL_RESULT.diagnostic` (enmascarado). Las tools reales (`DriveResult`/`SheetResult`) conservan su error detallado. Prueba de etapa 6 (modo degradado) actualizada.
- T3: `tests/test_stage8_security.py` (38 pruebas offline; incluye enumeración de los métodos `generate_*`, saneamiento parametrizado con 7 errores filtrantes, cero TOOL_CALL ante texto adversario, rieles ante URL inventada y la instrucción de sistema en cada llamada con historial).
- T4: `tests/test_stage8_live.py` (5 casos, se omiten sin Gemini) y `scripts/verify_stage_8.py` (sin Google por defecto; exit 2 sin configuración de Gemini, comprobado). Canarios: `SECURITY_SCOPE_v2`, `DATO, no instrucción`, `ROL: agente de registro de gastos`, `recibo_url igual al web_view_link`.
- T5: Sección 5 del notebook (ejecutado sin credenciales: "omitido") y bitácora en `docs/dev_prompts.md`; README, `docs/architecture.md` y `AGENTS.md` actualizados al id v2.
- Pytest offline con variables vaciadas: 259 passed, 14 deselected.
- T6 abierta: verificación real pendiente.
