# Etapa 5 — Tool `registrar_gasto` (Google Sheets) — BONO herramienta de acción

**Objetivo:** agregar la fila `Fecha | Comercio | Monto | Categoría | Recibo_URL` en la planilla de prueba y devolver `{success, row_number}`, validando antes de escribir.
**Criterio de rúbrica:** bono +0,5 "herramienta avanzada de edición o acción": llamada y estado anterior y posterior, repetible con seguridad (TF p.2).
**Decisión de diseño (orquestador):** deduplicación por (fecha, comercio, monto). Si la fila ya existe, no se escribe y se devuelve `duplicate=True`. Así repetir la llamada no cambia la planilla. Riesgo aceptado: dos compras idénticas el mismo día requieren confirmación (se verá con la memoria en la Etapa 10).
**Ruta:** delegated direct. Rama `feat/etapa-5-sheets`.
**TDD:** desactivado; pruebas funcionales offline y `live`.
**Restricciones:**
- Solo append, nunca borra ni sobrescribe.
- Scope `drive.file` **[SUPUESTO]** suficiente para leer y agregar filas en la planilla creada por la app (se comprueba en vivo).
- La verificación real espera a que el autor corrija `GOOGLE_OAUTH_TOKEN` en `.env`.

## Tareas
- [x] T1 `app/tools/sheets.py`: validación (categoría, monto > 0, URL de Drive), deduplicación, append y `row_number` desde la respuesta de la API.
- [x] T2 Utilidades de evidencia: conteo de filas y última fila (solo lectura).
- [x] T3 Pruebas offline, prueba `live` y `scripts/verify_stage_5.py` (antes, append, después y repetición sin cambio).
- [x] T4 Sección 8 del notebook: evidencia antes y después.
- [x] T5 Bitácora y `docs/bonos.md` (mecanismo de repetibilidad).
- [x] T6 Verificación real (2026-10-01): `verify_stage_5.py` OK (0 → 1 fila; la repetición se marca duplicada y el conteo no cambia); `pytest -m live` 1 passed. `drive.file` alcanza para Sheets.

## Evidencia
- T1 `app/tools/sheets.py` creado: `registrar_gasto` valida (categoría, monto > 0, fecha ISO, comercio, URL https `drive.google.com`) antes de cualquier llamada; deduplica leyendo `A:E`; agrega con `values.append(RAW, INSERT_ROWS)`; `row_number` sale de `updates.updatedRange`. `SheetResult` ganó `duplicate` y `error`.
- Símbolos verificados contra `googleapiclient/discovery_cache/documents/sheets.v4.json`: `values.append` (parámetros `valueInputOption` RAW|USER_ENTERED, `insertDataOption` OVERWRITE|INSERT_ROWS, respuesta `AppendValuesResponse.updates.updatedRange`), `values.get` (`valueRenderOption`), y el scope `drive.file` figura entre los scopes de ambos métodos. Fuente oficial citada: https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append (la página no se descargó).
- T2 `get_sheet_snapshot(service, settings)` -> `{"row_count", "last_row"}` (solo lectura).
- T3 `tests/test_stage5_sheets.py` (offline, `FakeSheetsService` en `tests/fakes.py`), `tests/test_stage5_live.py` (`live`, se omite sin config/token) y `scripts/verify_stage_5.py` (secciones ANTES, LLAMADA, DESPUÉS, REPETIR, `RESULTADO`).
  - `pytest -q -m "not live"` con variables en blanco: `184 passed, 6 deselected` (los 6 son `live`; la de Etapa 5 se omite sin config).
  - `verify_stage_5.py` con variables en blanco: salida con código 2 y mensaje claro, sin llamadas de red.
- T4 Sección 8 del notebook: celdas de validación offline y de evidencia ANTES/DESPUÉS/REPETIR (se omiten sin config). `nbconvert --execute` con variables en blanco: OK; la validación rechazó categoría, monto y URL inválidos, y la parte real imprimió "omitido".
- T5 `docs/bonos.md` (mecanismo y ubicación de la evidencia) y bitácora en `docs/dev_prompts.md`. Estado: IMPLEMENTADA — VERIFICACIÓN REAL PENDIENTE.
- T6 abierta: falta ejecutar `scripts/verify_stage_5.py` y `pytest -m live tests/test_stage5_live.py` con el token vigente del autor.
