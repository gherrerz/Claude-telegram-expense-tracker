# Ampliaciones declaradas (bonos)

Tope de la rúbrica: +3,0. Se declaran +3,5 para tener margen si algún bono no se acredita.
Cada bono usa un mecanismo distinto para no pedir doble crédito.

| Bono | Puntos | Mecanismo | Dónde se ejecuta (notebook) | Test | Etapa |
|---|---|---|---|---|---|
| Workflow adicional: router | +1,0 | Llamada LLM previa que elige 1 de 4 rutas; cada ruta ejecuta un camino distinto. | Sección 6 | `tests/test_router.py` | 9 |
| Memoria avanzada | +1,0 | `AgentState` estructurado, distinto del historial: estado inicial → actualización → uso en consulta y en detección de duplicados. | Sección 7 | `tests/test_memory.py` | 10 |
| Herramienta de acción | +0,5 | `registrar_gasto`: agrega una fila en una planilla de prueba; validación en código, solo append y deduplicación; estado antes/después visible. | Sección 8 | `tests/test_stage5_sheets.py`, `tests/test_stage5_live.py` | 5 |
| Juez LLM | +0,5 | Llamada LLM independiente que emite un veredicto; el código lo aplica antes de `registrar_gasto`. | Sección 9 | `tests/test_judge.py` | 11 |
| Golden set | +0,5 | `eval/golden_set_v*.json` versionado, ejecutado con `eval/run_eval.py`, con resultados por caso. | Sección 10 | `tests/test_evaluation.py` | 12 |

## Por qué no hay doble crédito
- **Router frente a seguridad basal.** El router clasifica el flujo y decide qué camino se ejecuta. La seguridad basal es un bloque de instrucciones presente en todas las llamadas. Son mecanismos distintos.
- **Juez frente a seguridad basal.** El juez es una llamada separada, con su propio prompt (`JUDGE_PROMPT_v1`), que no ve el razonamiento del agente. Su veredicto lo aplica el código, no el LLM del agente. No duplica el prompt basal: verifica la coherencia de los datos frente a la imagen y detecta inyección dentro de ella.
- **Memoria avanzada frente a historial.** El historial reenvía mensajes (criterio base). `AgentState` es un estado estructurado que se actualiza por eventos y se usa para decidir; no es el historial bruto.
- **Acción frente a consulta.** `registrar_gasto` modifica estado externo (agrega una fila). `analizar_recibo` es la herramienta básica de consulta del criterio ReAct.

## Herramienta de acción: `registrar_gasto` (mecanismo y evidencia)
Mecanismo (`app/tools/sheets.py`), todo aplicado por código y no por el prompt:
- **Validación previa a escribir.** Categoría dentro del conjunto permitido (`desconocido` no vale), monto numérico y positivo, fecha ISO real, comercio no vacío y URL `https` con host exacto `drive.google.com`. Si algo falla, `success=False` y no se hace ninguna llamada a la API.
- **Solo agregar.** Usa únicamente `spreadsheets.values.append` (`insertDataOption=INSERT_ROWS`) y `values.get` para leer. El módulo no usa `update`, `clear` ni `delete`; una prueba lo verifica.
- **Repetible con seguridad.** Antes de agregar, lee las filas existentes; si hay una con la misma fecha, comercio normalizado (sin distinguir mayúsculas ni espacios) y monto (comparación numérica), no escribe y devuelve `duplicate=True` con el número de la fila existente. Repetir la llamada no cambia la planilla.
- **`row_number` desde la API.** Se extrae de `updates.updatedRange` de la respuesta; nunca se calcula contando filas.
- **`valueInputOption=RAW`.** Guarda los valores tal cual: un comercio que empiece con `=` no se evalúa como fórmula y el monto enviado como número sigue siendo numérico. Con `USER_ENTERED` ambos casos cambiarían.
- Referencia oficial: <https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append>. Los símbolos se contrastaron con el documento de descubrimiento incluido en `googleapiclient` (`sheets.v4.json`).

Dónde está la evidencia:
- Notebook, Sección 8: validación offline y, si hay credenciales, ANTES (conteo y última fila) → llamada → DESPUÉS (+1 fila) → repetición (`duplicate=True`, conteo igual).
- Pruebas offline con un servicio falso: `tests/test_stage5_sheets.py`. Prueba real: `tests/test_stage5_live.py` (`-m live`).
- Script de verificación real: `scripts/verify_stage_5.py` (secciones ANTES, LLAMADA, DESPUÉS y REPETIR; línea final `RESULTADO`).
- Estado: la evidencia real queda **pendiente** hasta que el autor ejecute el script con su token vigente. **[SUPUESTO]** El scope `drive.file` basta para leer y agregar filas en la planilla creada por la app; se comprueba en vivo.
- Riesgo aceptado: dos compras idénticas el mismo día (misma fecha, comercio y monto) se toman como duplicado; el agente deberá pedir confirmación (Etapa 10).

## Independencia del juez
- Se ejecuta por código inmediatamente después de cada `analizar_recibo`; el LLM del agente no puede omitirlo.
- Recibe solo la imagen y los datos extraídos, no el historial ni el razonamiento del agente.
- Usa el mismo modelo de ejecución (Gemini Flash), pero en una llamada separada con prompt propio. Esto se declara de forma explícita.
- Solo `APROBAR` habilita `registrar_gasto`. `PEDIR_CONFIRMACION` y `RECHAZAR` bloquean el registro y se reflejan en la traza (`JUDGE_VERDICT`).

## Bonos no solicitados
RAG y MCP. Ver la justificación en `docs/architecture.md`, sección 11.
