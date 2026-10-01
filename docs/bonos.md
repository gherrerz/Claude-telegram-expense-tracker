# Ampliaciones declaradas (bonos)

Tope de la rúbrica: +3,0. Se declaran +3,5 para tener margen si algún bono no se acredita.
Cada bono usa un mecanismo distinto para no pedir doble crédito.

| Bono | Puntos | Mecanismo | Dónde se ejecuta (notebook) | Test | Etapa |
|---|---|---|---|---|---|
| Workflow adicional: router | +1,0 | Llamada LLM previa (`ROUTER_PROMPT_v1`, salida JSON `{ruta, motivo}`) que elige 1 de 4 rutas; cada ruta ejecuta un camino distinto con efecto observable en la traza. | Sección 6 | `tests/test_stage9_router.py`, `tests/test_stage9_live.py`, `scripts/verify_stage_9.py` | 9 |
| Memoria avanzada | +1,0 | `AgentState` estructurado, distinto del historial y de la deduplicación de la planilla: estado inicial → actualización por código (`MEMORY_UPDATE`) → dos usos: responder "¿cuánto llevo en X?" con cifras del estado y frenar un recibo duplicado hasta que el usuario confirme en un turno posterior. | Sección 7 | `tests/test_stage10_memory.py`, `tests/test_stage10_live.py`, `scripts/verify_stage_10.py` | 10 |
| Herramienta de acción | +0,5 | `registrar_gasto`: agrega una fila en una planilla de prueba; validación en código, solo append y deduplicación; estado antes/después visible. | Sección 8 | `tests/test_stage5_sheets.py`, `tests/test_stage5_live.py` | 5 |
| Juez LLM | +0,5 | Llamada LLM independiente que emite un veredicto; el código lo aplica antes de `registrar_gasto`. | Sección 9 | `tests/test_judge.py` | 11 |
| Golden set | +0,5 | `eval/golden_set_v*.json` versionado, ejecutado con `eval/run_eval.py`, con resultados por caso. | Sección 10 | `tests/test_evaluation.py` | 12 |

## Por qué no hay doble crédito
- **Router frente a seguridad basal.** El router clasifica el flujo y decide qué camino se ejecuta. La seguridad basal es un bloque de instrucciones presente en todas las llamadas. Son mecanismos distintos.
- **Juez frente a seguridad basal.** El juez es una llamada separada, con su propio prompt (`JUDGE_PROMPT_v1`), que no ve el razonamiento del agente. Su veredicto lo aplica el código, no el LLM del agente. No duplica el prompt basal: verifica la coherencia de los datos frente a la imagen y detecta inyección dentro de ella.
- **Memoria avanzada frente a historial.** El historial reenvía mensajes (criterio base). `AgentState` es un estado estructurado que se actualiza por eventos y se usa para decidir; no es el historial bruto.
- **Memoria avanzada frente a la deduplicación de la planilla.** La deduplicación de `registrar_gasto` (Etapa 5, bono de acción) vive en Sheets, compara fecha, comercio y monto contra las filas y por defecto siempre rige. La memoria detecta el MISMO recibo (hash de la imagen más campos) antes de subir nada a Drive, guarda una confirmación pendiente y decide qué herramientas se bloquean; solo después de la confirmación del usuario pide a la planilla omitir su deduplicación (`permitir_duplicado=True`).
- **Acción frente a consulta.** `registrar_gasto` modifica estado externo (agrega una fila). `analizar_recibo` es la herramienta básica de consulta del criterio ReAct.

## Router (mecanismo y evidencia)
Mecanismo (`app/router.py`, `app/assistant.py`):
- **Clasificación previa.** `route_message` hace una llamada estructurada (enum de 4 etiquetas, temperatura 0.0) antes de cualquier loop y registra el evento `ROUTE` con `ruta`, `motivo`, `fallback` y `has_image`.
- **Un camino distinto por ruta.** `ExpenseAssistant.handle` despacha: `REGISTRAR_RECIBO` ejecuta el loop ReAct con las tres tools; `CONSULTAR_GASTOS` hace una llamada de texto con el `AgentState` como dato (`QUERY_PROMPT_v1`); `CONVERSACION` hace una llamada de texto (`CHAT_PROMPT_v1`); `FUERA_DE_ALCANCE` devuelve un rechazo fijo en código. Solo la primera declara tools: en las otras tres hay cero eventos `TOOL_CALL`.
- **Respaldos seguros.** Entrada vacía → `CONVERSACION` sin llamar al LLM; falla del LLM, JSON inválido o etiqueta desconocida → `FUERA_DE_ALCANCE`. Todos con `fallback=true` en la traza.
- **Distinto de la seguridad basal.** El router decide el flujo; no filtra. `SECURITY_SCOPE_v2` y los rieles de las tools siguen activos en todas las rutas, y la llamada del router también lleva el bloque.

Dónde está la evidencia:
- Notebook, Sección 6: 4 entradas (una por ruta) con el evento `ROUTE`, las tools llamadas o no y la parada, solo con Gemini configurado.
- Pruebas offline con un LLM guionado: `tests/test_stage9_router.py`. Prueba real: `tests/test_stage9_live.py` (`-m live`).
- Script de verificación real: `scripts/verify_stage_9.py` (línea final `RESULTADO`).
- Estado: la evidencia real queda **pendiente** hasta que se ejecute el script con Gemini. La precisión del router depende del modelo; si una ruta no coincide se informa como falla y no se relaja el criterio.
- Límite conocido (Etapa 9): `CONSULTAR_GASTOS` leía un `AgentState` que partía vacío y respondía con honestidad que no había gastos registrados. Desde la Etapa 10 el estado se actualiza (ver Memoria avanzada); con un estado nuevo la respuesta sigue siendo esa.

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
- Riesgo aceptado: dos compras idénticas el mismo día (misma fecha, comercio y monto) se toman como duplicado. Desde la Etapa 10 el agente pide confirmación: si el usuario la da en un turno posterior, el agente llama con `permitir_duplicado=True` (parámetro explícito, por defecto `False`; la idempotencia de este bono no cambia).

## Memoria avanzada (mecanismo y evidencia)
Mecanismo (`app/memory.py`, `app/models.py`, `app/agent.py`, `app/assistant.py`):
- **Estado estructurado, no historial.** `AgentState` guarda `nombre_usuario`, `totales_por_categoria`, `ultimos_gastos` (5, el más reciente al final), `recibos_registrados` (huella de cada recibo), `filas_por_recibo` y `confirmacion_pendiente`. Una instancia por conversación; el historial (`Conversation`) sigue reenviando mensajes y no extrae nada.
- **Lo actualiza el código con lo que observa, no el LLM.** `record_expense` corre solo cuando `registrar_gasto` confirma la escritura (no en un duplicado de la planilla); `set_user_name` corre con la salida estructurada de `CONVERSACION` (`CHAT_PROMPT_v2`, `{respuesta, nombre_usuario}`), solo si el nombre son letras y aparece en el mensaje del usuario. Cada cambio emite `MEMORY_UPDATE` con `operacion`, `antes`, `despues` y `motivo`.
- **Huella del recibo.** `<sha256 de la imagen>-<resumen de comercio normalizado, fecha y monto>`. Es duplicado si la huella coincide o si la imagen es la misma (aunque el LLM lea un campo distinto).
- **Uso 1 (respuesta).** `CONSULTAR_GASTOS` envía el estado serializado y el total general calculado por código (`QUERY_PROMPT_v2`); el modelo solo redacta las cifras.
- **Uso 2 (decisión).** Tras `analizar_recibo`, si la huella ya está registrada la observación dice `posible_duplicado` con la fila existente, queda una confirmación pendiente y `guardar_recibo` y `registrar_gasto` se bloquean para ese recibo: cero subidas a Drive y cero filas nuevas. La baja confianza (riel de la Etapa 6) también deja una pendiente, pero solo bloquea `registrar_gasto`.
- **Regla de confirmación (cierra el hueco de la Etapa 6).** `confirmado_por_usuario=true` solo se acepta si hay una confirmación pendiente del mismo recibo y tipo creada en un turno ANTERIOR (`pendiente.turno < Conversation.turn`). En el mismo turno se rechaza con un error como observación. En el turno de confirmación el agente restaura el análisis y la imagen pendientes (bloque `<confirmacion_pendiente>`), así que se confirma solo con texto y sin volver a analizar. El router recibe la pendiente como contexto (`ROUTER_PROMPT_v2`) y no hay reglas de código sobre su etiqueta.
- **Duplicado confirmado.** El código llama a Sheets con `permitir_duplicado=True` (solo ese valor exacto omite la deduplicación; el LLM no controla el parámetro). Si la planilla reporta un duplicado que la memoria no conocía (otra foto, otra sesión), no se registra como gasto nuevo y queda una pendiente que el usuario puede confirmar después.
- **Sin persistencia.** El estado vive en memoria (opcional según el prompt maestro; no implementado). Un nuevo proceso empieza vacío. Sin `Conversation` el turno es siempre 1, así que no hay confirmación posible.
- **Prompts versionados.** `AGENT_PROMPT_v3`, `ROUTER_PROMPT_v2`, `CHAT_PROMPT_v2` y `QUERY_PROMPT_v2`; las versiones anteriores se conservan en `PROMPTS`.

Dónde está la evidencia:
- Notebook, Sección 7: la celda offline siempre corre (estado inicial, actualizaciones con `MEMORY_UPDATE`, los dos usos y la regla de turno); la celda real, solo con Gemini y Google, ejecuta el ciclo completo con un recibo sintético único.
- Pruebas offline con un LLM guionado: `tests/test_stage10_memory.py` (ciclo completo, regla de turno, baja confianza, duplicado de la planilla, nombre, `permitir_duplicado`). Prueba real: `tests/test_stage10_live.py` (`-m live`).
- Script de verificación real: `scripts/verify_stage_10.py` (cinco pasos, estado tras cada uno, línea final `RESULTADO`).
- Estado: la evidencia real queda **pendiente** hasta ejecutar el script con Gemini y Google. Riesgos a confirmar en vivo: que el router clasifique "Sí, regístralo de todas formas" como `REGISTRAR_RECIBO` con la pendiente como contexto, que el LLM use `confirmado_por_usuario` solo en el turno posterior y que la respuesta de consulta contenga el total del estado.

## Independencia del juez
- Se ejecuta por código inmediatamente después de cada `analizar_recibo`; el LLM del agente no puede omitirlo.
- Recibe solo la imagen y los datos extraídos, no el historial ni el razonamiento del agente.
- Usa el mismo modelo de ejecución (Gemini Flash), pero en una llamada separada con prompt propio. Esto se declara de forma explícita.
- Solo `APROBAR` habilita `registrar_gasto`. `PEDIR_CONFIRMACION` y `RECHAZAR` bloquean el registro y se reflejan en la traza (`JUDGE_VERDICT`).

## Bonos no solicitados
RAG y MCP. Ver la justificación en `docs/architecture.md`, sección 11.
