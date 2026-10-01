# Etapa 12 — Golden set y evaluación — BONO +0,5

**Objetivo:** un golden set versionado y completo (`eval/golden_set_v1.json`), con entrada, expectativa y criterio verificable por caso; `eval/run_eval.py` lo ejecuta contra el sistema real y guarda los resultados por caso. Si algo falla, se corrige el sistema (nunca el caso), se versiona y se vuelve a ejecutar hasta pasar el 100%.
**Criterio de rúbrica:** bono "Evaluación con golden set" +0,5. No suma si faltan ejecuciones, quedan fallos o se eliminan casos (TF p.2).

## Decisiones de diseño (orquestador)
1. **Criterios por condición, no por texto exacto.** Por ejemplo: el monto coincide, cero tool calls, veredicto igual a RECHAZAR, la ruta esperada, o el nombre presente en la respuesta.
2. **Reproducibilidad con Google real.** Los casos que registran usan un recibo sintético generado desde una receta fija del golden set, con un sufijo de corrida en el comercio. Así una corrida nueva no choca con la deduplicación de la planilla. Los casos de extracción usan `data/receipts/` y se comparan contra `expected.json`.
3. **Cuota.** Pausa entre llamadas, total de llamadas reportado y reanudación desde el último caso pendiente si se corta por límite diario. Una corrida cortada no cuenta como aprobada.
4. **Historial de corridas** en `docs/evaluation.md`. Cada versión del sistema que corrige un fallo genera `results_vN.json`.

**Ruta:** delegated direct (el escritor construye el arnés; el orquestador ejecuta las corridas reales). Rama `feat/etapa-12-eval`.
**TDD:** desactivado; pruebas offline del arnés.

## Tareas
- [x] T1 `eval/golden_set_v1.json` con los 10 casos mínimos (el caso 8 se abre en una entrada por ruta).
- [x] T2 `eval/run_eval.py`: ejecución, criterios, contadores, reanudación y `results_vN.json`.
- [x] T3 Pruebas offline del arnés (criterios, reanudación y que una corrida cortada no apruebe).
- [x] T4 Sección 10 del notebook, `docs/evaluation.md`, `docs/bonos.md` y bitácora.
- [x] T5 Corrida real v1: 13/13 APROBADO (100%), 65 llamadas LLM, sin interrupción (`eval/results_v1.json`). No hubo fallos que corregir.

## Evidencia
- **T1:** `eval/golden_set_v1.json` con 13 casos (GS01 a GS07, GS08A a GS08D, GS09, GS10), las 7 categorías y 4 casos con Google (GS01, GS06, GS09, GS10). `validate_golden_set` devuelve cero problemas; la prueba `test_golden_set_*` comprueba ids, categorías, rutas del router y referencias a `expected.json` y a las imágenes.
- **T2:** `eval/run_eval.py` y `eval/criteria.py` (23 tipos de criterio). Estados APROBADO, FALLIDO, ERROR, PENDIENTE y OMITIDO; códigos de salida 0, 1, 2 y 3; escritura atómica después de cada caso; `--resume` solo ejecuta PENDIENTE, OMITIDO o nunca corridos; un archivo existente no se sobrescribe. Humo del cableado con el `ExpenseAssistant` real y un LLM falso: GS07 y GS08D salen APROBADO sin red.
- **T3:** `tests/test_stage12_eval.py`: 90 pruebas (pasa y falla de cada tipo de criterio, criterios no omitibles, cuota por excepción y por traza, 503, reanudación que conserva un FALLIDO, corrida interrumpida que no aprueba, Google ausente y `--no-google`, salida 2 sin red). Suite completa con variables en blanco: `448 passed, 20 deselected`.
- **T4:** Sección 10 del notebook (5 celdas; `RUN_EVAL = False`), ejecutada con `nbconvert` sin credenciales; `docs/evaluation.md` (casos, criterios, política de versionado y reanudación, costo estimado y tabla de historial vacía); fila del golden set en `docs/bonos.md`; fila 12 del README; bitácora en `docs/dev_prompts.md`.
- **T5:** corrida real v1 (2026-10-01): 13/13 APROBADO, 65 llamadas LLM medidas (la estimación era ~70), 119.912 tokens, sin interrupción. Historial en `docs/evaluation.md`.
- **Corrección A12 (orquestador):** se eliminaron las tools simuladas y `SIMULATED_URL`. Los casos sin Google corren las tools reales con `GOOGLE_OAUTH_CLIENT_SECRETS`, `GOOGLE_OAUTH_TOKEN`, `DRIVE_FOLDER_ID` y `SHEET_ID` en blanco (`google_blanked`, restauradas al salir) y reciben el error estructurado; `herramientas` es `reales` o `reales_sin_google`. Pruebas: ninguna ruta de éxito simulado y los casos sin Google nunca reportan URL de Drive ni fila. Criterios sin cambios (ninguno de los casos sin Google exigía un registro exitoso); solo se reescribió el texto de `expectativa` de GS02, GS03 y GS08A.
