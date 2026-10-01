# Notas de referencia del curso (Certificado Agentic AI, Curso 1) para el proyecto Telegram Expense Tracker

Alcance: carpetas 1 a 7 de `Curso 1 Agentic IA`. Se excluyó `Claude-telegram-expense-tracker` y la carpeta `telegram-expense-tracker`. No se abrió ningún archivo `.env`. Las diapositivas se citan como `archivo, lámina N` (PDF exportado desde slides; N = página del PDF).

Convenciones de este documento: **[SUPUESTO]** = inferencia mía, no dicha por el material. Lo que no pude extraer se declara en la sección "Limitaciones".

Abreviaturas de archivos (nombres reales abreviados):
- S1a = `1-.../Sesion1-18082026 - 01.pdf`, S1b = `1-.../Sesion1-18082026 - 02.pdf`
- S2a = `2-.../Sesion 2-01.pptx.pdf`, S2b = `2-.../Sesion 2- 02.pptx.pdf`
- S3 = `3-.../Sesion_3.pptx.pdf`, T1 = `3-.../Taller1_Generador_Recetas_Ecommerce.pdf`
- S4 = `4-.../Sesion_4.pdf`, T2g = `4-.../Taller 2 - Guia del alumno.pdf`, T2py = `4-.../Taller 2.py`
- S5 = `5-.../Sesion_5.pptx.pdf`
- S6 = `6-.../Sesion_6_Clase.pptx.pdf`, TF = `6-.../tarea_final.pdf`, GC = `6-.../Guia_de_Conceptos_prompt_01.pdf`
- S7 = `7-.../Sesion_7_Seguridad_.pptx.pdf`

---------------------------------------------------------------------------------------------------

## 0. Hallazgo principal: la pauta de la tarea final (LEER PRIMERO)

Fuente única y completa: `6-Control.../tarea_final.pdf` (4 páginas, "Pauta de tarea final"). Es el único documento de todo el material con rúbrica de nota. Transcribo los criterios con precisión (parafraseo mínimo).

### 0.1 Objetivo y forma de entrega (TF p.1 y p.3)
- "Tarea final: un agente para su proyecto". Elegir un problema propio o laboral; delimitar qué resolverá y cómo se reconocerá un resultado correcto; desarrollar funciones y herramientas. "Cumplan la base obligatoria y agreguen solo las ampliaciones que aporten a su solución: no tienen que usar todas las técnicas del curso." El agente debe funcionar y otra persona debe poder ejecutarlo y revisarlo (TF p.1).
- Entrega: **notebook Jupyter `.ipynb` ejecutable, con instrucciones para repetirlo** (TF p.3). Entrega mínima: `.ipynb`, especificación del entorno, datos o receta de obtención, prompts del agente y trazas de ejecución. Si usaron OpenCode, adjuntar por separado los prompts de desarrollo (TF p.3). Si declaran ampliaciones, sumar archivos y configuraciones para probarlas.
- Secuencia de trabajo sugerida (TF p.3): 1 delimitar el caso (usuario, entrada, salida, límites, prueba de éxito observable); 2 preparar entorno (versión de Python, dependencias, acceso al LLM, sin credenciales reales); 3 seleccionar información y herramientas (datos autorizados, herramienta básica útil); 4 dejar visibles las instrucciones (documentar prompts, roles y parámetros de cada llamada al LLM; adjuntar prompts de OpenCode, sin claves ni datos privados); 5 implementar ciclo ReAct (llamada a herramienta, observación devuelta al LLM, nueva decisión, parada); 6 conservar historial (reenviar mensajes, demostrar segundo turno) y luego integrar ampliaciones.
- Ficha mínima para reproducirlo (TF p.3): **Modelo** (proveedor o runtime, identificador exacto, versión y parámetros relevantes; si es local, cómo obtenerlo); **Dependencias** (`requirements.txt`, `environment.yml` o equivalente, con versiones e instalación); **Variables** (nombres y función de las variables de entorno, sin valores secretos; el revisor configura sus propias credenciales si usa una API); **Datos** (origen, versión y modo de obtener o reconstruir datos y ejemplos de prueba autorizados).

### 0.2 Base obligatoria "para optar al 4,0" (TF p.1)
Escala textual: "1,0 inicial + hasta 3,0 de estos cinco criterios = 4,0". Los cinco criterios y su peso:

| Peso | Criterio | Requisito textual resumido (TF p.1) |
|---|---|---|
| 0,5 | Caso y criterio de éxito | Usuario, entrada, alcance, salida esperada y una comprobación observable. El caso justifica el uso de un LLM y una herramienta. |
| 0,5 | LLM real y trazabilidad | Llamada ejecutada por API o modelo local. Identificar modelo, configuración, fuentes y prompts de las llamadas al LLM; dejar una traza legible. |
| 1,0 | ReAct integrado | El LLM solicita una herramienta básica pertinente; su observación vuelve al LLM. Hay decisión de repetir o responder y una condición de parada explícita. |
| 0,5 | Historial simple | Reenviar mensajes al LLM. En un segundo turno debe usar un dato dado en el primero (ej. el nombre) sin una respuesta fijada en código. |
| 0,5 | Seguridad básica | Instrucciones de alcance y acciones permitidas **en cada llamada al LLM que pueda decidir o responder**. Ante petición fuera de alcance o jailbreak sencillo debe respetar los límites y no ejecutar acciones prohibidas. "Corrijan y repitan si se rompe." |

Aclaración: "El notebook, el entorno, los prompts y las pruebas son evidencia de los criterios, no un sexto rubro" (TF p.1). Nota: los pesos de los cinco criterios suman 3,0; el 1,0 inicial parece otorgarse por cumplir/entregar [SUPUESTO: el texto no dice cómo se gana el 1,0 inicial].

### 0.3 Ampliaciones opcionales: del 4,0 al 7,0 (TF p.2)
"Pueden combinar categorías; no deben hacerlas todas. Cada bono exige una prueba ejecutada y reproducible. La suma de bonos tiene tope +3,0." Regla común: "Declaren los bonos que solicitan y dónde se ejecutan. No hay doble crédito por el mismo mecanismo; otra API o el nombre de una tecnología no suman por sí solos."

| Bono | Qué | Prueba exigida | No suma si |
|---|---|---|---|
| +1,0 Memoria avanzada | Resumen o estado útil más allá del historial bruto | Estado inicial, actualización y uso posterior en una respuesta o decisión. Persistencia opcional. | Solo reenvía mensajes o guarda algo que nunca usa. |
| +1,0 Workflow adicional | Ej.: router que elige ruta, planificador que ordena pasos, refinamiento iterativo que evalúa y mejora respuestas | Trazas de ruta seleccionada, plan adaptado o respuesta revisada; mostrar su efecto. | Solo hay un diagrama o no se ejecuta la ruta, el plan o la revisión. |
| +1,0 RAG | Recuperar documentos **con el Redis del curso** cuando la respuesta necesite el corpus. "No se admite un índice local alternativo." | Entrada y decisión de recuperar; corpus, índice exacto, carga y configuración (embeddings, campos, dimensiones, métrica y algoritmo); fragmentos, fuentes y uso en la respuesta. | No usa Redis del curso, no recupera o lo invoca sin necesidad. |
| +1,0 MCP | Servidor libre y gratuito, invocado solo si el agente necesita su herramienta o recurso | Entrada, decisión, descubrimiento y llamada real; nombre/versión, host/URL o comando, instalación y datos de prueba; claves: obtención gratuita y variables, sin secretos. | Solo está configurado, se llama para toda entrada o depende de acceso privado/pago inaccesible. |
| +0,5 Herramienta avanzada de edición o acción | Acción autorizada distinta de la consulta básica | Llamada y **estado anterior/posterior en un entorno controlado**. | Es otra lectura o **no puede repetirse con seguridad**. |
| +0,5 Evaluación con golden set | Casos con expectativa y criterio explícitos | Golden set **versionado, completo y ejecutado**: entradas, expectativas, veredictos y resultados por caso. Corregir los casos fallidos y volver a ejecutar; la corrida final debe cumplir los criterios. | Faltan ejecuciones, quedan fallos sin resolver o eliminan casos fallidos para ocultarlos. |
| +0,5 c/u Guardrail avanzado o juez | Control independiente por encima de la seguridad basal | Caso benigno y adversarial, veredicto y decisión aplicada. Si hay juez LLM: modelo, prompt y veredictos. | Duplica el prompt basal, no aplica el veredicto o repite otro control. |

Cuándo usar RAG o MCP (TF p.2): "Hola" = respuesta directa, sin RAG ni MCP; pregunta sobre el corpus = RAG con Redis del curso; tarea que necesita una herramienta del servidor = MCP. Mostrar entradas con y sin necesidad de uso, la decisión del agente y la llamada solo cuando corresponda.

### 0.4 Pruebas y revisión (TF p.4)
Cada caso debe mostrar entrada, ejecución observada y resultado. Pruebas antes de entregar:
- Caso normal: entrada válida, herramienta llamada, observación que regresa al LLM, decisión final y parada.
- Segundo turno: un dato anterior (ej. nombre) se usa desde el historial enviado al LLM; "una respuesta fija no cuenta".
- Seguridad básica: petición fuera de alcance y jailbreak sencillo; respeta límites, responde de forma segura y no ejecuta acciones prohibidas; si se rompe, corregir y repetir.
- Verificación final: todas las pruebas y evaluaciones declaradas completas y cumpliendo criterios. Si apareció un fallo al desarrollar o probar, arreglar y re-ejecutar antes de entregar. "No se pide provocar un fallo."
- Cómo revisa el docente: "instalará el entorno, preparará los datos y ejecutará el notebook **desde cero y en orden**. Verificará la traza del LLM, la herramienta, el historial y la condición de salida. Después repetirá solo las ampliaciones declaradas y contrastará sus evidencias con lo ejecutado."

### 0.5 Consecuencias en la nota (TF p.4)
- **Flujo central**: si en la revisión sigue sin funcionar LLM, ReAct, herramienta, devolución de observación, parada o historial, "la nota final tiene **tope 3,0**". Un error anterior corregido y verificado no activa el tope.
- **Seguridad basal**: si en la revisión una petición fuera de alcance o un jailbreak sencillo rompe los límites, pierde sus 0,5; no impone por sí solo otro tope 3,0.
- **Bonos**: una ampliación fallida no suma, pero no quita una base que funciona. Tope +3,0 y no se acredita dos veces el mismo mecanismo.
- "No publiquen claves, datos personales ni recursos privados. Para acciones externas, utilicen recursos de prueba que otra persona pueda usar con seguridad." (TF p.4)

### 0.6 Otras menciones de evaluación en el material
- S1a lámina 9 ("¿Cómo se evalúa?", plantilla general del certificado): nota de cada curso = 30% talleres aplicados, 30% examen/debate, 30% tarea final grupal ("entregable integrador defendido ante panel simulado"), 10% participación; **nota mínima de aprobación 4,0**. El texto habla de talleres "sobre la propia organización" y de debate de criterios estratégicos: parece plantilla genérica del programa y no coincide en detalle con la pauta técnica de TF [SUPUESTO]. La pauta TF manda para la tarea final.
- T1 (`Taller1_Generador_Recetas_Ecommerce.pdf` p.3): rúbrica del Taller 1 (no es la tarea final): recetas con 2 tools 25 pts; pedidos 20; horarios 10; conversación con memoria 15; router enruta correctamente las 8 preguntas 15; prompts afinados 15; bonus flujo adicional +15 (suma 100 + 15).
- T2g (Taller 2 guía del alumno, p.2-4): ejercicios 1 a 6 + bonus y lista de control (ver 4.3). La guía dice "la rúbrica está en la documentación de la clase"; esa rúbrica numérica no está en los archivos.
- No se encontró fecha de entrega de la tarea final en ningún archivo. El curso 1 figura del 18 ago al 29 sep (S1a lámina 5).

---------------------------------------------------------------------------------------------------

## 1. Carpeta 1 - Fundamentos de autonomía: de LLM a sistema agéntico

### Archivos analizados
- `Sesion1-18082026 - 01.pdf` (67 láminas): presentación del certificado, GenAI, LLM, stack, ejemplos de herramientas, preparación del entorno.
- `Sesion1-18082026 - 02.pdf` (41 láminas): de LLM a agente, 6 capas, loop, fallos de autonomía, Agent Contract.
- `Clase 2026-08-18.md`: archivo **vacío** (0 bytes).

### Conceptos clave
- **Agente clásico**: percepción, decisión, acción sobre un entorno (Russell & Norvig) (S1b, lám. 5). Un mejor modelo no es un agente: es una pieza; al LLM le faltan intención/objetivo, estado, acción, evaluación y control (S1b, lám. 9).
- **Chatbot vs copiloto vs agente**: entrada-salida de texto; propone y el humano aprueba; recibe meta, ejecuta y verifica. "La autonomía está en el sistema que se construye alrededor, el harness" (S1b, lám. 8, 13).
- **Human-in-the-loop proporcional al riesgo**: resumen bajo, correo medio, modificar BD alto, desplegar a producción crítico; "no es lo mismo que una IA se equivoque respondiendo a que se equivoque ejecutando" (S1b, lám. 10-11). "Si no puedes definir cómo termina, todavía no deberías darle autonomía" (S1b, lám. 11).
- **Workflow vs agente**: si el proceso se puede escribir como reglas estables, probablemente no se necesita autonomía (S1b, lám. 15). Para el proyecto: justificar en el notebook por qué el caso necesita LLM+herramienta (criterio "Caso" de TF).
- **Las 6 capas**: Intención y objetivo, Cognitiva, Estado (working memory/persistente), Acción (tools/APIs), Evaluación (validación, evidencia), Control (seguridad, observabilidad, costo, auditoría, permisos, retries) (S1b, lám. 18-19).
- **Loop del agente**: OBSERVE -> THINK -> PLAN -> ACT -> VERIFY -> UPDATE; "una respuesta termina; un agente vuelve a observar hasta alcanzar una condición de éxito, parada o escalamiento" (S1b, lám. 20). Código conceptual `while not done: observation=observe(state) ... state=update(state, verdict)` (S1b, lám. 21). Ejemplo de dos vueltas donde VERIFY obliga a cambiar de estrategia (lám. 22). Referencia citada: ReAct (react-lm.github.io) (S1b, lám. 4).
- **Fallos de la autonomía** (S1b, láms. 29-33): loop infinito (controles `max_steps`, `max_retries`, `timeout`, `budget`); objetivo ambiguo; "cuando el agente no sabe que no sabe" (acciones posibles: ACT, TOOL/SEARCH, VERIFY, ESCALATE, ABSTAIN); higiene de contexto (resumir, estructurar estado, recuperar bajo demanda, versionar evidencia; "la memoria útil no es guardar todo, es recuperar lo correcto en el momento correcto"); **costo del flujo** (ejemplo: tarea de valor US$ 4 con flujo de US$ 17 -> "¿vale más de lo que cuesta ejecutarlo?").
- **Autonomía bajo control**: definir SUCCESS, STOP y ESCALATE antes de ejecutar (ej.: 3 retries, timeout, budget agotado; diferencia >5%) (S1b, lám. 37).
- **Agent Contract** (taller): objetivo, entradas/salidas, estado, tools, autoridad (qué puede ejecutar sin aprobación), restricciones, success/stop, escalate, riesgos, métricas (S1b, láms. 38-40). Regla: Problema -> Contrato -> Arquitectura -> Decisiones de implementación -> Producción. Contrato a código: tools = schemas/APIs/MCP; estado = store/checkpoints/RAG; autoridad = permisos/scopes; success/stop = políticas de runtime; escalate = HITL; métricas = logs + evaluaciones (lám. 40).
- Fundamentos LLM (S1a, láms. 11-21): tokens (1 token ~ 3-4 caracteres; 100 tokens ~ 70 palabras), embeddings, ventana de contexto, temperatura (baja ~0 para reportes/procedimientos), respuesta directa vs razonamiento, alucinaciones; "verificar siempre datos críticos". El stack declarado: Python 3.12 "estándar sugerido del curso", VS Code, extensiones Python/Jupyter, Git; recomendados: Google Cloud CLI, Node LTS, JupyterLab, uv (S1a, lám. 65). Checklist con `.venv`, `requirements.txt`, notebook de chequeo `00_environment_check.ipynb` que importa `openai`, `from google import genai`, `anthropic`, `langgraph` (lám. 66).
- Frameworks mencionados: LangGraph, OpenAI Agents SDK, Google ADK, CrewAI; "mismo Agent Contract, distintas maneras de implementarlos" (S1b, lám. 24).

### Patrones y convenciones
- Contrato operativo por agente (success/stop/escalate) como artefacto de diseño previo al código.
- El caso demostrativo del docente ("Bello", asistente jurídico) no tiene relación con gastos; sirve de ejemplo de 3 niveles de delegación (S1b, lám. 13).

### Rúbrica/requisitos
- Solo la plantilla genérica de evaluación (S1a, lám. 9), ver 0.6.

### Librerías/modelos
- Mencionados solo como stack: OpenAI, Gemini (`from google import genai`), Anthropic, LangGraph (S1a, lám. 66).

---------------------------------------------------------------------------------------------------

## 2. Carpeta 2 - Arquitecturas agénticas modernas: patrones robustos y multi-agente

### Archivos analizados
- `Sesion 2-01.pptx.pdf` (48 láminas), `Sesion 2- 02.pptx.pdf` (36 láminas), `Lab 1 - Entendiendo la plataforma.ipynb` (2 celdas: markdown de requisitos y una celda "Hola Mundo" vacía de contenido útil).

### Conceptos clave
- **API de LLM stateless**: la continuidad vive fuera del modelo. Sin historial, la segunda llamada no sabe que existió la primera; "memoria simple = historial; en LangGraph evoluciona a un State estructurado" (S2a, lám. 13). Ejemplo de código directo Gemini: `genai.Client().models.generate_content(model=..., contents=...)` (lám. 12); equivalente LangChain `ChatGoogleGenerativeAI(...).invoke(...)` (lám. 19). Esto es el sustento directo del criterio "Historial simple".
- **Function calling / tools**: ejemplo "presidente de Chile": sin tool el modelo responde desactualizado; con `web_search` correcto (S2a, lám. 14). LangChain ofrece `@tool`, `bind_tools`, `ToolMessage`, structured output con Pydantic (lám. 17).
- **Ecosistema**: LangFlow prototipa, LangChain construye, LangGraph orquesta, LangSmith observa y evalúa (trazas con entradas, salidas, latencia, tokens, datasets) (S2a, láms. 15-16). LangGraph: State, Nodes, Edges, Conditional edges, Checkpointer; API mínima `StateGraph(State)`, `add_node`, `add_edge`, `add_conditional_edges`, `compile()`, `invoke` (lám. 22). Regla: chain si la ruta es una línea recta; grafo si hay que decidir, volver atrás o reanudar (lám. 20).
- **Los 5 patrones** (S2a, láms. 24-46 y tabla de dolor/gana/riesgo lám. 45):
  - ReAct: "no conozco el siguiente paso"; gana adaptación; riesgos: bucles infinitos, tool calls innecesarios, costo creciente, contexto acumulado (S2a lám. 25-29; S2b lám. 34).
  - Plan-and-Execute: camino conocido, trazabilidad, dependencias; sacrifica adaptabilidad (lám. 33-35).
  - Iterative Refinement (generar-criticar-refinar): calidad; riesgo auto-confirmación; self-refinement vs verificación con evidencia (lám. 36-38).
  - Agentic Workflow: reglas/gates deterministas (ej. monto > $100M -> humano) (lám. 39-41). "El agente razona dentro del flujo; el workflow controla estados, gates y rutas permitidas."
  - Hierarchical Agents: supervisor + workers con autoridad limitada ("juez y parte") (lám. 42-44).
  - Los patrones se combinan por capas, no son excluyentes (lám. 46).
- **RPWE** (Router-Planner-Workers-Evaluator): clasificar, planificar, ejecutar y aceptar son decisiones distintas (S2b, láms. 3-8). Router entrega intención, riesgo, ruta; Planner pasos + dependencias; Workers `result + evidence + status`; Evaluator `SUCCESS / RETRY / STOP / ESCALATE` (lám. 4-7). "La autonomía se diseña como política observable, no como magia del prompt" (lám. 10). Ejemplos de umbrales: variación >20% escala; amount > $100M escala; `steps = 6 = max_steps` detiene (lám. 12, 32).
- **Single vs multi-agente**: separar solo si ganas especialización, autoridad distinta, verificación independiente, paralelismo o aislamiento de riesgo; "multi-agente teatral" (varios prompts con nombres sin ganancia); regla de simplificación (fusionar dos agentes: si no pierdes nada, nunca necesitaste dos); "la arquitectura mínima que controla correctamente el problema suele ser la mejor" (S2b, láms. 14-30). Esto respalda mantener el proyecto como agente único con router interno.
- Laboratorio: política editable en YAML (`finance_worker: can/cannot`, `evaluator: max_retries 2, max_steps 6`, `success`, `escalate`) y 4 ejecuciones (SUCCESS, RETRY->SUCCESS, STOP o ESCALATE con explicación) (S2b, láms. 32-33).
- Plataforma del curso (Cloud Run) para trabajar "sin instalar nada" (S2a, lám. 8). La lámina contiene una contraseña de acceso; **no se copia** aquí.

### Patrones y convenciones de código
- Estado compartido tipado, nodos como funciones, aristas condicionales con función de decisión que devuelve una etiqueta (S2a, lám. 22).
- Salidas de control con vocabulario cerrado (SUCCESS/RETRY/STOP/ESCALATE) y razón explícita (`reason=missing_data`) (S2b, lám. 8).
- Controles de loop: `max_steps`, `max_retries`, `timeout`, `budget` (S2a, lám. 30).

### Rúbrica/requisitos
- Ninguno numérico. El lab pide entregar 3 corridas con explicación (S2b, lám. 33) y el taller de arquitectura "una página" con diagrama single-agent y MAS (S2b, lám. 31); no son la tarea final.

### Librerías/modelos
- `langchain`, `langchain-core`, `langchain-google-genai`, `requests` (Lab 1, celda markdown). Modelos citados: `gemini-3.6-flash` ("para las pruebas y laboratorios siguientes", Lab 1), `gemini-2.5-flash` y `gpt-4o-mini` en ejemplos de código de las láminas (S2a, láms. 12 y 19).

---------------------------------------------------------------------------------------------------

## 3. Carpeta 3 - Modelos fundacionales como motor cognitivo: composición, routing y presupuesto

### Archivos analizados
- `Sesion_3.pptx.pdf` (38 láminas), `Taller1.pdf` (1 p.) y `Taller1_Generador_Recetas_Ecommerce.pdf` (4 p., guía del profesor con soluciones).

### Conceptos clave
- **Patrones mapeados a la taxonomía de Anthropic**: ReAct ~ agent loop; Plan-and-Execute ~ orchestrator dinámico; Iterative Refinement ~ evaluator-optimizer; Agentic Workflow ~ prompt chaining + routing; Hierarchical ~ orchestrator-workers (S3, lám. 9). Glosario: workflow = LLM en rutas de código predefinidas; agente = el LLM dirige sus acciones según feedback del entorno (S3, lám. 36). "Si usas un framework, entiende el código subyacente" (lám. 15).
- **Gate**: control determinista (regla, no el modelo) decide continuar, detener o escalar; en LangGraph conditional edge + `interrupt()` (S3, lám. 12).
- **Motor cognitivo**: no usar el modelo premium para todo ("el mejor modelo para todo es una mala arquitectura", lám. 24). Mapa de modelos por rol: generalista, reasoning, especializado, modalidades separadas del texto, local (lám. 25). VLM vs OCR: "OCR extrae caracteres (qué dice); VLM interpreta imagen + texto (qué significa): layout, tablas, sellos" (lám. 23 y glosario lám. 37). Es la base conceptual para elegir un modelo con visión para recibos.
- **Cascada cheap-first**: FAST -> STANDARD -> REASONING -> HUMANO; PASS se queda, UNCERTAIN sube un nivel, COMPLEX sube directo; "trigger observable" = condición medible (confidence < umbral, schema FAIL, retry >= 1), nunca "si parece difícil" (S3, láms. 26 y 37).
- **MoE a nivel aplicación** = tu router entre modelos (lám. 27); **Fallback** de proveedor con el mismo contrato de salida ante timeout, rate limit, provider error o bad output (lám. 28-29). LangChain: `with_fallbacks()` (lám. 30).
- **Presupuesto como política** (S3, láms. 33-34): costo por interacción, por proceso, por usuario/mes; "budget caps y alertas antes del corte"; "batch y caching: el ahorro más barato es la llamada que no se hace". El controlador de costo decide modelo (cascada), cuántos pasos (máx. de iteraciones/replanning), qué herramientas (tools caras solo con justificación del plan) y cuándo escalar a humano (riesgo alto o presupuesto agotado -> ESCALATE). "En LangGraph: contadores en el estado del grafo + conditional edge de presupuesto." Medir en el lab: correcto, JSON válido, latencia, tokens, costo relativo (lám. 30).
- Caso del taller de cierre del lab: "modelo mínimo suficiente != modelo mínimo" (lám. 30).

### Patrones y convenciones
- Router con modelo FAST + salida estructurada (Pydantic + `Literal`) y delegación por conditional edges (T1 p.1). Ruta por defecto ante falla de clasificación.
- Taller 1 (solo ejemplo): tools simuladas con datos locales (5 recetas, catálogo, 3 pedidos) para que corra sin APIs; nodos `receta/pedido/horarios/conversar`; pregunta de diseño "¿cuándo NO hace falta un LLM en un nodo?" (T1 p.1-2). Tools se invocan con `.invoke({"arg": valor})`; envolver la respuesta del LLM con una función `texto(...)` porque el contenido puede venir como lista de bloques (T1 p.4).
- Batería de 8 preguntas de prueba del router incluyendo bordes (pedido inexistente 9999, comuna sin cobertura) (T1 p.3).

### Rúbrica/requisitos
- Rúbrica del Taller 1 (T1 p.3) ya citada en 0.6. Entrega "Notebook .ipynb o apellido_nombre.py/.txt" (T1 p.1).

### Librerías/modelos
- LangChain + LangGraph (S3, lám. 5). Ejemplos de proveedor A/B: "gpt 5.6" y "gemini 3.7 flash" como fallback compatible (S3, lám. 28). Recursos de comparación: livebench.ai, huggingface.co/models (lám. 25).

---------------------------------------------------------------------------------------------------

## 4. Carpeta 4 - Memoria como infraestructura cognitiva: RAG enterprise y vector stores

### Archivos analizados
- `Sesion_4.pdf` (32 láminas; **mayormente imágenes**, texto extraíble mínimo; revisé visualmente las láminas 7, 18-20, 22-24, 27, 29, 31 y las flechas de transición 5/8/10/12/15/26).
- `Taller 2 - Guia del alumno.pdf` (4 p.), `Taller 2.py`, `Taller 2 · Tu propio RAG paso a paso.ipynb` (34 celdas), `Taller_2_RAG_Colab_equipo3.ipynb` (46 celdas, trabajo de un equipo con ejercicios resueltos), `Tabla.xlsx` (tablas de ejercicios 1-4 de ese equipo, trabajo del alumno, no material docente), `Normativa_Devoluciones_y_Responsables_Sesion4.pdf` (18 p., corpus ficticio "Comercial Nexo", política de devoluciones v3 + directorio v2 + extracto histórico v2 no vigente; "fecha de consulta del ejercicio 08 sep 2026"), `2023_UNAB_MTT630_...pdf` (72 p., presentación académica sobre arquitectura empresarial usada como PDF de prueba del RAG).

### Conceptos clave (de la sesión)
- Ingeniería de contexto = diseñar y gestionar toda la información que recibe el agente (prompts, memoria, historial, herramientas, documentos, metadatos); prompt engineering = instrucciones directas; "primero elegimos el modelo según rol cognitivo y tarea; luego la ingeniería de contexto" (S4, láms. 8-9, 11, 14 y flechas).
- **Memoria agéntica**: almacenar, recuperar y utilizar información previa para mantener contexto, aprender y mejorar decisiones; decidir qué conservar, recuperar o descartar (S4, lám. 11 y lámina 10 visual).
- Mapa de modelos por rol cognitivo (generalista, reasoning, especializado, modalidades, local) (S4, lám. 7).
- **RAG con LangChain + Redis**: PDF -> carga -> fragmentación -> embeddings (OpenAI o Gemini) -> Redis Vector Store -> embedding de consulta -> búsqueda KNN/coseno -> Top-K -> LLM -> respuesta (S4, láms. 18, 27). Chunking con solape y su objetivo: mejor recuperación, menos ruido, más precisión (lám. 19). Panorama de bases vectoriales (lám. 20); KNN en espacio vectorial (láms. 22-23); distancia euclídea vs similitud coseno ("encontrar un fragmento parecido no basta; también debe corresponder al caso y estar permitido para esta consulta", lám. 24).
- **Triángulo costo / performance / inteligencia**: "ningún modelo maximiza las tres; puedes optimizar dos" (S4, lám. 29).
- Flujo de 8 pasos del laboratorio "RAG paso a paso": preparar, conectar a Redis, embedding, fragmentar, indexar y buscar, responder con RAG, umbral de confianza, grafo/GraphRAG (S4, lám. 31).
- Tipos de RAG (simple -> adaptativo, híbrido, agéntico, nativo) se mencionan en láms. 25-26 sin texto extraíble más allá del título.

### Patrones y convenciones de código (`Taller 2.py` y notebooks)
- Modelo de chat `ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite")` y embeddings `GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")` (vectores de 3072 dimensiones según la salida del notebook del equipo) (T2py celda 1).
- Variables del taller por entorno: `PREFIJO`, `UMBRAL=0.65`, `TOP_K=3`, `CHUNK_SIZE=500`, `CHUNK_OVERLAP=150`, `ARCHIVOS`, `REDIS_URL`, `GOOGLE_API_KEY` (T2py).
- Redis sin RediSearch: un HASH por fragmento (`texto`, `fuente`, `vector` como JSON) + SET de ids + clave `firma` (md5 del contenido) para no reindexar si no cambió (T2py celda 5). Coseno implementado a mano. Prefijo por equipo para no pisarse en el Redis compartido (T2g p.1).
- Cadena LCEL: `{contexto, pregunta} | ChatPromptTemplate(system, human) | llm | StrOutputParser()`; SYSTEM_PROMPT con 4 reglas (exclusividad de contexto, citas `[archivo p.N]`, negativas justificadas, frase fija si está fuera de contexto); USER_PROMPT con delimitadores `<contexto>` y `<pregunta>` (T2py celda 6).
- Umbral de confianza con `RunnableBranch`: si el mejor parecido < UMBRAL no se llama al modelo y se responde "No tengo información suficiente..." (ahorra tokens) (T2py celda 7). Mismo flujo en LangGraph: `buscar -> decidir -> responder | no_se` (celda 9).
- Memoria en LangGraph: `MemorySaver` con `thread_id` por conversación; "y si es un producto fresco?" funciona porque el grafo recuerda la pregunta anterior (notebook `Taller 2 · ...ipynb`, celdas 30-32). Ejercicio bonus: historial en lista Redis (`rpush`/`lrange`) con hora y mejor parecido (T2g p.4).
- Nodo `verificar` (ejercicio 6 opción B) con contador `intentos`/`MAX_INTENTOS` para evitar ciclo infinito (T2g p.4; notebook equipo, celda 39).
- Calibración de umbral: tabla con 3 preguntas dentro y 3 fuera del documento y elegir el umbral en el margen (T2g p.3).

### Rúbrica/requisitos (taller, no tarea final)
- Entregables por ejercicio: tabla chunking (T2g p.2), top-3 por métrica (p.2), system prompt antes/después (p.3), tabla umbral con 6 preguntas (p.3), documento extra (p.4), nodo LangGraph con traza (p.4), bonus historial Redis (p.4). Lista de control: prefijo único visible al conectar, notebook corre de principio a fin, cada ejercicio con tabla o explicación, respuestas citan fuente y dicen cuando no hay información, traza del grafo visible (T2g p.4).

### Librerías/modelos
- `langchain`, `langchain-community`, `langchain-google-genai`, `langchain-core`, `langchain-text-splitters`, `langgraph`, `redis`, `pypdf` (+ `pandas` en el notebook del equipo). Redis "compartido del curso" cuya URL entrega el profesor; el notebook `Taller 2 · ...ipynb` (celda 6) trae la URL de Redis escrita en el código: **antipatrón** frente a la regla de credenciales, no se copia.
- Relevancia para el proyecto: **RAG no es parte de las 14 etapas**; solo sería un bono (+1,0) y exige el Redis del curso. Los conceptos de umbral/abstención y "ingeniería de contexto" sí son aprovechables para memoria avanzada y para el juez.

---------------------------------------------------------------------------------------------------

## 5. Carpeta 5 - Tool-use real: APIs, RPA, MCP y ejecución controlada

### Archivos analizados
- `Sesion_5.pptx.pdf` (46 láminas): agentes de código y construcción de agentes con OpenCode.
- `agentes-opencode.zip` (duplicado de la carpeta extraída) y carpeta `agentes-opencode/`: `AGENTS.md`, `plan.json`, `opencode.json`, `.env.example`, `opencode/agents/{implementator,test-code,validator,review,notebook}.md`, `opencode/examples/implementator.md`, y el proyecto `agente-colombia/` (config, state, main, nodes, tools, services, mcp, prompts).
- `Taller/`: `primer agente.ipynb` (23 celdas), `README.md`, `requirements.txt`, `.gitignore`.

### Conceptos clave
- **Agente de código = bucle ReAct** con tools (leer archivos, correr tests, terminal) que convierte instrucciones en cambios del proyecto; ciclo: dar objetivo, referencias y límites -> el agente escribe -> probar y revisar -> ajustar (S5, láms. 7-8). Advertencias: "agentes de código no significan seguridad; no ingresar información de tu empresa"; modelos gratuitos usan tus datos para reentrenamiento; "pueden cometer errores o modificar más de lo pedido: revisa los cambios y limita sus permisos" (S5, láms. 3, 10, 12, 22).
- Clase eligió **OpenCode** (multi-proveedor, modelos gratuitos). Ranking del docente: Codex o Claude Code primera elección, Cursor, OpenCode (elegido para la clase), Antigravity/Kiro, Pi, Copilot (S5, lám. 11).
- **Estructura de prompt para encargar un agente al agente de código** (S5, láms. 31 y 46; "estructura de prompt, no copiar y pegar"): ROL, OBJETIVO, ALCANCE, ENTORNO Y DEPENDENCIAS, CONFIGURACIÓN Y SEGURIDAD, ORGANIZACIÓN DEL PROYECTO, COMPORTAMIENTO, FLUJO Y MEMORIA, INTERACCIÓN Y CONTROLES, PRUEBAS Y ENTREGA. Prompts de revisión de equipo "sin instalar ni cambiar nada" y de instalación (láms. 27, 29).
- **ReAct conectado a MCP** (S5, láms. 43-46): modelo + cliente MCP <-> servidor MCP de API Colombia; la respuesta vuelve al agente con su fuente y fecha de consulta; "dos nodos: agente y herramientas"; incorporar límites de llamadas; comprobar conexión MCP, herramientas y recorrido completo. Sin herramientas el LLM no consulta fuente (lám. 43).
- Primer agente (etapa 1): chatbot con grafo mínimo `START -> chatbot -> END` y memoria en RAM (`InMemorySaver` + `thread_id`), secretos en `.env` (S5, láms. 26, 35-36; `primer agente.ipynb`).

### Patrones y convenciones de código (los más útiles para el proyecto)
- **Plan de trabajo por pasos** (`plan.json`): un paso por invocación, `estado` solo `pendiente|hecho`, un paso solo se marca `hecho` si su verificación pasó ejecutada ("un plan que miente no sirve"), cada paso deja el proyecto ejecutable, nadie reescribe el plan; pasos: estructura-base, grafo-mínimo, modo-debug, api, mcp, itinerario-excel, retirar-placeholder, robustez, documentación, validación-50-preguntas, notebook-estudio (`AGENTS.md`, `plan.json`).
- **División de agentes de desarrollo**: `implementator` (único que edita código), `test-code` (solo ejecuta; lo pendiente es N/A; hasta 3 ciclos de corrección), `validator` (banco estable de 50 preguntas en xlsx + harness), `review` (solo lectura, hallazgos Bloqueante/Importante/Menor con `archivo:línea`), `notebook` (genera notebook didáctico de 12 secciones con `nbformat`, salidas vacías, sin claves) (`opencode/agents/*.md`).
- **Arquitectura del código**: `main.py` solo arma el grafo y expone `app` importable; bucle de consola bajo `if __name__ == "__main__"`; nodos en `nodes/`, tools en `tools/`, servicios en `services/`, prompts en `prompts/{nodo}_prompt.py` (un archivo por nodo con LLM); `config.py` es el **único** lector de variables de entorno; credenciales solo en `.env`; "no inventar imports ni clases: verificar antes de usar" (`AGENTS.md`, `implementator.md` secciones 3-5 y 8). Esto coincide casi 1 a 1 con las reglas del `AGENTS.md` del proyecto (prompts en `app/prompts.py` versionados es una variante propia; el curso usa un archivo por nodo).
- **Router**: Pydantic `Literal` con las etiquetas, `llm.with_structured_output(RouterOutput)`, `temperature=0`, atajo sin LLM para entrada vacía o de ≤2 caracteres, y **fallback a la rama conversacional** ante excepción; las 4 ramas convergen en un nodo de consolidación (`agente-colombia/nodes/router.py`, `main.py`). Función de decisión que valida la etiqueta y cae a un default (`main.py`).
- **Trazabilidad**: lista `trace` en el estado, modo `DEBUG=1`/`--debug` que imprime por stderr entrada de cada nodo, decisión del router, tool/endpoint con argumentos, tiempo por nodo; utilidad `fuentes_consultadas(trace)` para responder "¿pasó por MCP, por API o ninguno?" (`tools/debug.py`, plan paso 03).
- **Robustez** (plan paso 08): fallo de red/timeout con mensaje útil sin traceback crudo; respuesta vacía -> decirlo en vez de inventar; fuera de dominio -> conversacional sin fabricar; entrada vacía no rompe; tolerancia a faltas/tildes (`nodes/consulta_informacion.py` usa normalización + `difflib`). Cada nodo tiene `try/except` "red de seguridad: el grafo nunca se tumba".
- **MCP**: `langchain_mcp_adapters.client.MultiServerMCPClient`, transporte `streamable_http` (no `sse`), sin auth, `await client.get_tools()` (async); primero `list_colombia_resources` para descubrir claves (`implementator.md` sec. 5; `mcp/client.py`). Servidor público "API Colombia" con 11 tools; la URL sale de la variable `MCP_URL`.
- **Harness de validación** (`validator.md`): hoja `Preguntas` con `rama_esperada`, `espera_mcp/api/excel`, `tipo` (casos límite incluidos); `astream(..., stream_mode="updates")` para capturar la traza de nodos; excepciones por pregunta sin abortar las demás; métricas por rama (no solo total), latencia media/min/max/p95, hojas `Detalle`, `Resumen`, `Fallos`; "Nunca reportes un número que no salga del Excel que acabas de generar"; el banco "no se regenera entre ejecuciones" para comparar corridas.
- **Taller `primer agente.ipynb`**: 10 secciones (00 objetivo/alcance, 01 entorno, 02 configuración, 03 prompts, 04 fuentes, 05 herramientas, 06 estado-memoria-flujo, 07 visualización, 08 errores-límites-métricas, 09 comprobaciones, 10 conversar). Constantes `TIMEOUT_SEGUNDOS=30`, `MAX_REINTENTOS=2`; clasificación de errores del proveedor en códigos (`clave_ausente`, `clave_invalida`, `modelo_inaccesible`, `cuota`, `limite_solicitudes`, `red`, `timeout`, `respuesta_vacia`); el `SYSTEM_PROMPT` se antepone en cada llamada **sin** guardarse en el historial; `.text` para extraer texto plano de la respuesta; "matriz de comprobaciones" con estados `VERIFICADO` / `IMPLEMENTADO SIN VERIFICAR` (muy cercano a la regla de veracidad del proyecto).

### Rúbrica/requisitos
- Ninguna nota numérica en esta carpeta. Los entregables de los agentes de desarrollo son criterios internos del flujo OpenCode.

### Librerías/modelos
- `Taller/requirements.txt` (versiones fijadas en el material): `langchain==1.4.0`, `langgraph==1.2.11`, `langchain-google-genai==4.4.0`, `python-dotenv==1.2.3`, `ipykernel==7.3.0`. `agente-colombia/requirements.txt` sin versiones: `langgraph, langchain, langchain-core, langchain-google-genai, langchain-mcp-adapters, openpyxl, python-dotenv, httpx, pydantic, mcp`.
- Variables: `GOOGLE_API_KEY`, `GOOGLE_MODEL` (ej. `gemini-3.5-flash-lite`), `MCP_URL`, `DEBUG` (`.env.example`); en el taller `GEMINI_MODEL=gemini-3.5-flash-lite`. Modelos en la cabecera de los agentes OpenCode: `openai/gpt-5.6-luna`. No verifiqué que estos IDs existan; el proyecto no debe asumirlos.
- Se usa Gemini vía Google AI Studio ("no Vertex AI") (`Taller/README.md`).

---------------------------------------------------------------------------------------------------

## 6. Carpeta 6 - Control, evaluación y gobernanza: guardrails, red teaming y observabilidad

### Archivos analizados
- `tarea_final.pdf` (ver sección 0), `Sesion_6_Clase.pptx.pdf` (49 láminas), `Guia_de_Conceptos_prompt_01.pdf` (19 p.), `seccion 5- seguridad.zip` (duplicado de la carpeta extraída; contiene un `.env` que **no se abrió**), carpeta `seccion 5- seguridad/seguridad2.0/` (AGENTS.md, README, plan.json, `.opencode/agents/{check,hacking,implementador,jupyter,promptfoo,spec}.md`, `agent-seguridad/` con main, servidor, nodes, prompts, services, tests, notebook `itinerario/estudio_ejecucion.ipynb`, `odd/tasks/flujo-clima.md`).

### Conceptos clave (Sesión 6)
- **Herramientas con efecto**: escribir un archivo es más riesgoso que leer; las lecturas son repetibles sin cambiar nada, las escrituras duplican datos si se ejecutan dos veces; "antes de reintentar una acción que modifica datos, comprobamos si el intento anterior ya produjo el cambio" (idempotencia, RFC 9110 §9.2.2; "idempotencia no equivale a permiso ni ausencia de riesgo") (S6, láms. 7-8). Ejemplo de tool `@tool def editar_archivo` en modo append (lám. 7). Verbos HTTP GET/POST/PUT/DELETE (lám. 11).
- **API vs MCP**: una API es interfaz para procesos/humanos; MCP estandariza cómo un LLM descubre, llama y recibe resultados de tools; FastMCP empaqueta tools/resources/prompts (`@mcp.tool`, schema, downstream) y "no reemplaza el diseño de permisos, contratos ni gestión de riesgos" (S6, láms. 13-19). Una conexión no garantiza actualidad: revisar cobertura y fecha de la fuente (lám. 9).
- **Evaluación de agentes** (S6, láms. 21-32): superar el "vibe check" -> flujo, pauta, criterios, puntajes, tipos de evaluación. Pasos: casos preparados, ejecutar el agente, comprobar criterios, comparar resultados (lám. 22). Tres evaluadores: **reglas de código** (100% automático, rígido; comprueba formato, campos, cantidad, rangos, no si es buena la recomendación), **revisión humana** (flexible, no escala), **juez LLM** (escalable, algo impredecible, exige rúbricas precisas) (láms. 23-25). "La evaluación no es lo mismo que un nodo evaluador" (lám. 21).
- **Criterios de calidad** compartidos por humano y juez LLM: Precisión, Respaldo (grounding), Completitud, Consistencia, Cumplimiento de reglas (S6, lám. 26). Puntaje difuso con grados intermedios en vez de binario (lám. 27); ejemplo de salida `{"criterio": "respaldo", "puntaje": 82}` (lám. 28).
- **Calibrar al juez**: comparar con casos revisados por personas, entender el desacuerdo (¿recibió la evidencia?), ajustar rúbrica con esquema obligatorio, comprobar de nuevo incluyendo casos nuevos; "el juez puede favorecer estilo, longitud u orden" (S6, lám. 28). Un modelo clasificador puede ser alternativa más rápida/barata al juez LLM (láms. 30-31, datos de la lámina sin fuente extraíble).
- **Corregir y no sobreajustar**: revisar nodo por nodo (inputs, outputs, prompts, tools, transmisión), corregir la causa, probar el flujo completo; "probar con los casos anteriores + preguntas nuevas, no utilizadas durante el ajuste" (S6, lám. 32). Lo mismo con red teaming: repetir el caso que falló con la misma regla de aceptación y repetir consultas legítimas para detectar bloqueos injustificados o regresiones; "cero fallos observados limita la evidencia a los casos que realmente probamos" (láms. 44-45).
- **Seguridad** (S6, láms. 33-49):
  - Minimización de datos: retirar datos innecesarios (ej. correo) antes de enviarlos al modelo (lám. 34). Guardrails = controles que detectan una condición y permiten, transforman o detienen el paso.
  - **Middleware / dónde se aplica el control**: antes del modelo, alrededor de la herramienta (comprobar operación y argumentos antes de permitir su efecto), antes de entregar la respuesta (lám. 35).
  - **Tres comprobaciones distintas**: estructura (regla/esquema), contenido (crítico o persona), autorización (la aplicación permite o rechaza) (lám. 36). "El crítico evalúa la calidad. Los permisos y controles limitan lo que puede ejecutarse."
  - **Mínimo privilegio y aislamiento de datos** por usuario también en memoria, logs y tools (lám. 37).
  - **Intervención según consecuencias**: bajo (leer) permitir; medio (guardar localmente) confirmar contenido y destino; alto (enviar datos de otro usuario) bloquear y alertar (lám. 38). "La falta de evidencia no convierte por sí sola una consulta en riesgo alto."
  - **Revisión humana antes de una acción**: mostrar destino, contenido y si reemplazará algo; aprobar, editar o rechazar; los cambios se re-validan (lám. 39).
  - JSON Schema para estructura ("pasar la validación no demuestra que el lugar exista ni autoriza una acción"); si falló solo parte de la consulta, conservar lo confirmado y reintentar solo el paso recuperable con límite de intentos, sin inventar datos (lám. 40).
  - **Prompt injection** directa e indirecta (en datos/tools); fuga de datos, jailbreak, manipulación de herramientas; **red teaming** = pruebas adversariales controladas; campaña con ficha de caso (entrada, esperado, observar respuesta/tools/decisión de controles; ámbito aislado y datos ficticios) (láms. 41-45).
  - **Telemetría**: la traza reconstruye el recorrido; duración por paso; llamadas repetidas y errores; tokens, costo y decisiones de controles; "sin secretos ni datos personales innecesarios" (lám. 46).
  - Respuesta a incidentes: contener, conservar evidencia, corregir, agregar el caso a las pruebas, verificar antes de reanudar (lám. 47). Tabla fallo observado -> dónde investigar -> cómo comprobar (inventó un horario; consultó otra región; obedeció orden dentro de un dato) (lám. 48).
- **Guía de conceptos** (GC; material de otra sesión del certificado, "Prompt Engineering 4 Gen AI", docente distinto): define 49 conceptos. Útiles: método CLARO (Contexto, Límites, Acción, Rol, Output) con rúbrica de autoevaluación (GC p.17), delimitadores para separar instrucciones de datos y mitigar inyección (GC p.10 y p.13), "persona en el circuito", "barreras de seguridad: ninguna es infalible, diseñar asumiendo que alguien intentará saltársela" (GC p.13), anonimización, "la IA redacta, usted firma" (GC p.12), multimodal: "para cifras críticas en una imagen, verifique" (GC p.6, relevante para recibos), "si necesita precisión numérica pídale que calcule con una herramienta" (GC p.16).

### Patrones y convenciones de código (`seguridad2.0`)
- Grafo `router -> {conversacion | generacion-informe | consulta-clima} -> unificador -> juez-llm -> END`, con `build_graph(incluir_juez: bool)` y `graph = build_graph(True)` importable; CLI `--juez` en `servidor.py` (`agent-seguridad/main.py`, `servidor.py`).
- Estado `TypedDict` con `trace: Annotated[list[str], operator.add]` (traza aditiva) (`state.py`).
- `llm.py` crea el modelo de forma diferida (se puede importar/compilar sin credenciales); `config.py` con dataclass congelada y error que **no** expone valores (`RuntimeError("Falta configurar ...")`).
- `services/system_message.py` compone el system prompt inyectando entrada, rama, resultado, borrador y traza, y envía un turno humano fijo ("Responde según las instrucciones del sistema") porque la API de Google GenAI rechaza una conversación sin mensaje de usuario (error `contents are required`).
- `services/response_normalizer.py`: extrae solo bloques `type=text` de la respuesta (evita exponer bloques internos/firmas).
- Servidor HTTP mínimo: `POST /` con `{"input": ...}` -> `{"response": ...}`, 400/404/500 sin exponer detalles, sin loguear cuerpos (`servidor.py`).
- **Tests deterministas sin red ni credenciales**: `pytest`, `monkeypatch` de `get_llm` y de nodos en el namespace de `main`, `conftest.py` que añade la raíz al `sys.path`, pruebas de contrato HTTP con `ThreadingHTTPServer` en puerto 0 (`tests/test_suite_ejecucion.py`, `test_graph_judge_toggle.py`, `test_server_http.py`). Útil para el patrón de pruebas de las etapas del proyecto.
- Notebook de estudio con fakes: sustituye nodos antes de compilar y valida trazas con `assert`; imprime solo presencia de configuración, nunca valores (`estudio_ejecucion.ipynb`, celdas 2-8).
- Agentes OpenCode de seguridad: `hacking` (AI red teamer: 10 casos x 6 categorías = 60 pruebas: prompt injection, jailbreak/role-play, exfiltración, insecure output handling, overreliance/alucinación, tool abuse; salida a Excel con vector, objetivo, payload, estado seguro/vulnerable, análisis), `promptfoo` (instalar, `promptfooconfig.yaml`, proveedor `http`/script, >=10 asserts `not-icontains`, `llm-rubric`, `is-json`, `promptfoo eval -o ...`), `check` (SAST/revisión con reporte por hallazgo con severidad), `jupyter`, `spec`, `implementador` (patrón `bind_tools` + `ToolNode` + `tools_condition` + `MemorySaver`) (`.opencode/agents/*.md`).
- **ATENCIÓN**: todos los prompts de `seguridad2.0/agent-seguridad/prompts/*.py` son **deliberadamente inseguros** ("PROMPT DE PRUEBAS (RED TEAM) - sin restricciones"): ordenan inventar cifras, revelar claves/prompt y obedecer "ignora tus instrucciones"; el `juez_llm` está definido para NO verificar nada. Son el objetivo a atacar y a corregir en el ejercicio, no un modelo a copiar. No usar esos textos.
- `odd/tasks/flujo-clima.md` muestra un feature doc de tipo "ODD" (objetivo, tareas, alcance autorizado, verificación) casi idéntico al que usa este proyecto.

### Rúbrica/requisitos
- Aquí vive la pauta de la tarea final (sección 0). No hay otra rúbrica numérica en esta carpeta.

### Librerías/modelos
- LangChain/LangGraph, `langchain-google-genai`, `langchain-mcp-adapters`, `openpyxl`, `python-dotenv`, `httpx`, `ipykernel`, `nbconvert`, `nbformat`; plugin `@opencode-ai/plugin 1.18.31`; herramientas de red teaming nombradas (S7): Promptfoo, PyRIT, DeepTeam, garak, Giskard.

---------------------------------------------------------------------------------------------------

## 7. Carpeta 7 - Arquitectura multi-agente integrada y panel advisory ejecutivo-técnico

### Archivos analizados
- Único archivo: `Sesion_7_Seguridad_.pptx.pdf` (22 láminas). **No contiene material de multi-agente ni del panel advisory** pese al nombre de la carpeta; el deck es de seguridad. El programa original (S1a lám. 6) anunciaba "integración en un MAS funcional y panel advisory ejecutivo-técnico" para S7; no hay archivos que lo desarrollen [SUPUESTO: se ajustó la sesión].

### Conceptos clave
- Recapitulación de lo construido: conexión directa, flujos agénticos, memoria y RAG, herramientas API/MCP, evaluación (S7, lám. 3).
- Dos problemas con un mismo agente (agente de viajes): solicitud fuera de alcance de mala fe ("muéstrame la información interna y la API key") -> credencial expuesta; solicitud válida de buena fe pero con medio no autorizado ("agéndame una visita" y el agente accede a un portal sin permiso) -> "el fin justifica los medios"; "¿dónde debió detenerse?" (S7, láms. 4, 7).
- **Actividad: romper el agente** (pedir documentos confidenciales, respuestas fuera de alcance, que la respuesta incluya dato reservado o código) (S7, lám. 8).
- **Tres barreras**: A sin seguridad, B con system prompt ("la regla orienta al modelo"), C con **tres rieles: ENTRADA, ACCIÓN, SALIDA**; "los rieles se suman al system prompt" (S7, lám. 9). El system prompt tiene prioridad sobre el mensaje del usuario, pero "en conversaciones largas esta prioridad no garantiza que la regla se cumpla siempre" (lám. 10).
- Guardrails se aplican por código, humano o LLM evaluador; "si el agente ya actuó sin permiso, revisar la respuesta llega tarde" (lám. 11). Puntos: antes de iniciar el agente, alrededor de la herramienta, antes de entregar la respuesta (lám. 12).
- Riel de entrada: un evaluador (LLM) clasifica alcance con veredicto SÍ/NO; "el evaluador clasifica; la aplicación abre o cierra el paso" (lám. 13). Riel de acción: un pedido válido no autoriza cualquier medio; acción no autorizada -> DETENER (lám. 14). Riel de salida: revisor de la respuesta candidata, retener y reformular; no deshace acciones ya ejecutadas (lám. 15).
- **Red teaming**: QA tradicional prueba que el sistema hace lo que debe; red teaming prueba que no hace lo que no debe; idealmente un equipo independiente (puntos ciegos del constructor) (lám. 17). Categorías: fuga de datos, jailbreak, manipulación de herramientas (lám. 18). Método: LLM adversarial genera inputs maliciosos, se guardan respuesta y llamadas a tools, un juez compara con la política, se mide la tasa, se corrige y se repiten pruebas (lám. 19). Herramientas: Promptfoo, PyRIT, DeepTeam, garak, Giskard (lám. 20).
- Piezas completas del agente: modelo e instrucciones, flujos y workflows, herramientas/API/MCP, memoria y RAG, evaluación y seguridad (entrada, acción, salida), pruebas adversariales (lám. 22).

### Rúbrica/requisitos
- Ninguna.

---------------------------------------------------------------------------------------------------

## 8. Relación con las etapas del proyecto

Leyenda de cobertura de rúbrica: [BASE] = criterio de la base obligatoria; [BONO] = ampliación (tope +3,0).

### Aritmética de nota (TF p.1-2)
Base 4,0 (1,0 inicial + 0,5 caso + 0,5 LLM/traza + 1,0 ReAct + 0,5 historial + 0,5 seguridad). Bonos que el plan podría pedir: Herramienta de acción +0,5 (Sheets), Workflow adicional +1,0 (router), Memoria avanzada +1,0, Juez +0,5, Golden set +0,5 = **3,5 declarables > tope 3,0**. Se alcanza el 7,0 con margen de 0,5; si un bono falla, los otros lo cubren. No hace falta RAG ni MCP.

### Etapa 1 - Caso/arquitectura
- Criterio [BASE] "Caso y criterio de éxito" (TF p.1): usuario, entrada, alcance, salida esperada, comprobación observable, y justificar por qué el caso necesita LLM + herramienta.
- Usar el Agent Contract (S1b, láms. 38-40): objetivo, entradas/salidas, estado, tools, autoridad, restricciones, success/stop/escalate, riesgos, métricas. Respaldo adicional: "¿necesita autonomía?" (S1b, lám. 15) y arquitectura mínima / single-agent con router interno (S2b, láms. 28-30; S3, lám. 20 "multi-agente teatral").
- Definir success/stop/escalate para el agente de gastos (S1b, lám. 37; S2b, láms. 11-12): p. ej. SUCCESS = fila registrada y confirmada; STOP = max_steps/reintentos; ESCALATE = confianza baja o monto fuera de regla [SUPUESTO: ejemplos míos aplicados al caso].

### Etapa 2 - Base Python y trazador
- Criterio [BASE] "LLM real y trazabilidad" (TF p.1): identificar modelo, configuración, fuentes y prompts de cada llamada y dejar traza legible.
- Patrones del curso: `config.py` único lector del entorno; `.env`/`.env.example`; `llm.py` con creación diferida; trazado con lista aditiva `trace` (operator.add) y modo DEBUG a stderr con tiempo por nodo (`agente-colombia/tools/debug.py`, `seguridad2.0/state.py`); clasificación de errores del proveedor y `TIMEOUT`/`MAX_REINTENTOS` (`Taller/primer agente.ipynb`, sección 06 y 08); telemetría sin secretos ni PII (S6, lám. 46); `LangSmith` como idea de traza con latencia y tokens (S2a, lám. 15).
- Ficha de reproducibilidad: Python (el curso sugiere 3.12, S1a lám. 65), dependencias con versiones, variables (TF p.3).

### Etapa 3 - LLM con visión + `analizar_recibo`
- Conceptos: VLM vs OCR (S3, láms. 23, 37); multimodal "para cifras críticas verifique" (GC p.6); salida estructurada con Pydantic/schema para resultados verificables (S2a, lám. 17; S6, lám. 40 JSON Schema); temperatura baja para extracción (S1a lám. 19; GC p.6); abstención/"no inventar" cuando falta dato (S1b, lám. 31; S6, lám. 48 "inventó un horario"); `texto(...)`/`normalize_response` para manejar respuestas en bloques (T1 p.4; `seguridad2.0/services/response_normalizer.py`).
- Aviso: el curso no muestra ningún ejemplo de visión; los IDs de modelo del material (`gemini-3.5-flash-lite`, `gemini-3.6-flash`) no están declarados como multimodales en las láminas. [SUPUESTO] verificar el modelo de visión real antes de fijarlo en la ficha de modelo.

### Etapa 4 - Drive `guardar_recibo`
- Herramienta de acción con efecto: principio de lectura vs escritura, idempotencia y comprobación del estado previo antes de reintentar (S6, láms. 7-8). Mínimo privilegio: una sola carpeta de prueba (S6, lám. 37). Recurso de prueba reutilizable por el revisor (TF p.4).
- Posible mapeo de bono "Herramienta avanzada de edición o acción" (+0,5) (TF p.2): requiere prueba de estado anterior/posterior en entorno controlado y que se pueda repetir con seguridad.

### Etapa 5 - Sheets `registrar_gasto` (herramienta de acción)
- Candidato principal al bono +0,5 "Herramienta avanzada de edición o acción" (TF p.2). Condiciones textuales: acción autorizada distinta de la consulta básica; llamada y estado anterior/posterior en entorno controlado; "no suma si ... no puede repetirse con seguridad".
- Riesgo directo con "solo agregar filas": append no es idempotente; duplica si se ejecuta dos veces (S6, lám. 8). Hace falta evidencia de deduplicación (clave/ID de recibo o comprobar antes de agregar) y conteo de filas antes/después en una hoja de prueba.
- Autoridad por consecuencias: guardar es riesgo medio -> confirmar contenido y destino antes de guardar (S6, láms. 38-39); revisión humana "aprobar, editar o rechazar" con re-validación.
- Validación estructural previa (campos obligatorios/tipos, `additionalProperties` no permitidos) antes de la escritura (S6, lám. 40).

### Etapa 6 - Loop ReAct
- Criterio [BASE] de mayor peso (1,0) (TF p.1): el LLM **solicita** una herramienta básica pertinente, la observación vuelve al LLM, hay decisión de repetir o responder y **condición de parada explícita**. Prueba: caso normal con herramienta llamada, observación devuelta, decisión final y parada (TF p.4). Si falla en la revisión: tope 3,0 en la nota final (TF p.4).
- Referencias: loop OBSERVE-THINK-PLAN-ACT-VERIFY-UPDATE (S1b, láms. 20-22); ReAct = micro-loop adaptativo (S2a, láms. 25-29); riesgos: bucle infinito, tool calls innecesarios, costo creciente (S2b, lám. 34); controles `max_steps`, `max_retries`, `timeout`, `budget` (S2a, lám. 30; S1b, lám. 29); Evaluator con SUCCESS/RETRY/STOP/ESCALATE (S2b, láms. 4-6); presupuesto como política con contadores en el estado (S3, lám. 34); implementación estándar `bind_tools` + nodo de herramientas + `tools_condition` + retorno al agente (`seguridad2.0/.opencode/agents/implementador.md`); prompt de S5 "dos nodos: agente y herramientas, incorporar límites de llamadas" (S5, lám. 46).
- Nota: el proyecto de referencia `agente-colombia` NO es un ReAct real (router + nodos deterministas), así que no sirve como modelo del criterio ReAct. El criterio exige function calling iniciado por el LLM.

### Etapa 7 - Historial simple
- Criterio [BASE] (0,5): reenviar mensajes; segundo turno usa un dato del primero **sin respuesta fijada en código** (TF p.1, p.4). Base conceptual: API stateless, el historial lo guarda la aplicación (S2a, lám. 13); ejemplo "Me llamo Camila" -> "¿recuerdas cómo me llamo?" (T1 p.2-3); `SYSTEM_PROMPT` anteponerse en cada llamada sin guardarse en el historial; `InMemorySaver`/`thread_id` (`Taller/primer agente.ipynb`, sección 06). La prueba debe quedar en el notebook y en la traza (el historial enviado al LLM debe verse).

### Etapa 8 - Seguridad basal (scope prompt `SECURITY_SCOPE_v1`)
- Criterio [BASE] (0,5): instrucciones de alcance y acciones permitidas **en cada llamada al LLM que pueda decidir o responder** (TF p.1). Implicación: el router (etapa 9), el resumidor de memoria si usa LLM (10) y el juez (11) también deben incluir el scope; el agente ya lo hace por regla del proyecto.
- Prueba mínima: petición fuera de alcance + jailbreak sencillo; respeta límites y no ejecuta acciones prohibidas; si se rompe, corregir y repetir (TF p.4). Pérdida solo de los 0,5 si rompe en la revisión (TF p.4).
- Respaldo: S7, láms. 8-10 (romper el agente, prioridad SYSTEM vs USER y su límite); delimitadores `<...>` para datos no confiables (GC p.10); inyección indirecta en datos de tools: el OCR/texto de un recibo puede contener instrucciones (S6, láms. 41-42); mínimo privilegio y "un pedido válido no autoriza cualquier medio" (S7, lám. 14; S6, lám. 37).
- Guardrails de código sobre el prompt: el system prompt solo orienta; los rieles ENTRADA/ACCIÓN/SALIDA se suman (S7, lám. 9). La restricción "Sheets solo agregar" debería aplicarse en la herramienta (autorización por código, S6, lám. 36) y no solo en el prompt.

### Etapa 9 - Router
- Bono [BONO] "Workflow adicional" +1,0 (TF p.2): router que elige ruta; prueba = trazas de ruta seleccionada y su efecto; no suma si solo hay diagrama o no se ejecuta la ruta.
- Patrón: Pydantic `Literal` + `with_structured_output` + `temperature=0` + fallback a una rama segura + atajo para entrada vacía + función de decisión que valida etiqueta (`agente-colombia/nodes/router.py`, `main.py`); descripción de cada etiqueta con ejemplos y casos que NO van (fuera de dominio) en el prompt del router (`router_prompt.py`); router como clasificación de intención y riesgo (S2b, lám. 5); modelo FAST para clasificar (S3, lám. 30); batería de preguntas de prueba del router incluyendo bordes (T1 p.3); el "Hola" debe responderse sin herramientas (TF p.2). Medir acierto del router por rama (`validator.md`).

### Etapa 10 - Memoria avanzada
- Bono [BONO] +1,0 (TF p.2): "resumen o estado útil más allá del historial bruto"; prueba = estado inicial, actualización y uso posterior en una respuesta o decisión; persistencia opcional; no suma si solo reenvía mensajes o guarda algo que nunca usa.
- Referencias: capa Estado (S1b, lám. 18); higiene de contexto: resumir, estructurar estado, recuperar bajo demanda, versionar evidencia (S1b, lám. 32); "memoria simple evoluciona a State estructurado" (S2a, lám. 13); memoria agéntica = decidir qué conservar, recuperar o descartar (S4, lám. 11); ingeniería de contexto (S4, lám. 9); aislamiento de memoria por usuario (S6, lám. 37; relevante para Telegram multiusuario); historial persistido en Redis como opcional (T2g p.4, solo si se usara Redis; no es necesario).
- Ideas de estado útil [SUPUESTO]: gasto acumulado del mes por categoría, último recibo, preferencias de categoría; debe consumirse luego en una respuesta/decisión (p. ej. alertar si un gasto supera el promedio).

### Etapa 11 - Juez LLM
- Bono [BONO] "Guardrail avanzado o juez" +0,5 c/u (TF p.2): control independiente por encima de la seguridad basal; prueba con caso benigno y adversarial, veredicto y decisión aplicada; modelo, prompt y veredictos. No suma si duplica el prompt basal, no aplica el veredicto o repite otro control.
- Diseño: criterios Precisión, Respaldo (grounding), Completitud, Consistencia, Cumplimiento (S6, lám. 26); salida estructurada con puntaje (S6, lám. 28); la aplicación abre o cierra el paso según el veredicto (S7, láms. 13, 15); distinguir estructura (reglas de código), contenido (juez) y autorización (permisos) (S6, lám. 36); calibrar el juez con casos revisados por humanos y verificar sus propios errores (S6, lám. 28; S7, lám. 19).
- Antipatrones del material: el juez de `seguridad2.0` está escrito para NO verificar (rol de práctica de red team); no usarlo como modelo. Ojo con el sesgo "juez y parte" (S2b, láms. 18-19): usar un prompt/rol distinto del agente.
- Posible aplicación: juez de salida que contrasta los campos extraídos del recibo con la evidencia (respaldo) antes de registrar el gasto.

### Etapa 12 - Golden set / evaluación
- Bono [BONO] +0,5 (TF p.2): golden set versionado, completo y ejecutado (entradas, expectativas, veredictos, resultados por caso); corregir fallos y re-ejecutar; la corrida final debe cumplir los criterios; no se pueden eliminar casos fallidos.
- Referencias: casos preparados -> ejecutar -> criterios -> comparar (S6, lám. 22); reglas de código para formato, campos, cantidad, rangos (S6, lám. 24); loop nodo por nodo, no sobreajustar (casos anteriores + nuevos) (S6, lám. 32); banco estable no regenerado + harness con traza por pregunta + excepciones por caso + métricas por categoría + hoja `Fallos` (`validator.md`); ficha del caso adversarial y repetición de casos legítimos para detectar regresiones (S6, lám. 45); `promptfoo` con `llm-rubric`/`not-icontains`/`is-json` como herramienta opcional para el set adversarial (`promptfoo.md`, S7 lám. 20). No hay golden set de ejemplo con recibos.
- Para recibos: incluir casos con total ilegible, fecha ausente, recibo falso/fuera de alcance, inyección dentro del recibo [SUPUESTO: tipos de caso sugeridos por S6 lám. 41 y lám. 48].

### Etapa 13 - Demo Telegram
- No aparece en la rúbrica ni en el material del curso; la tarea final exige un notebook ejecutable (TF p.3) y la propia AGENTS.md del proyecto ya dice que Telegram es una demo aparte. Sin respaldo para puntos; riesgo de que el revisor no pueda reproducirlo (necesita bot token). Aislamiento de memoria por usuario si se mantiene (S6, lám. 37). Un servidor HTTP mínimo con contrato `{"input"} -> {"response"}` está en `seguridad2.0/servidor.py` como referencia de superficie de integración.

### Etapa 14 - Notebook final y checklist de rúbrica
- Entrega TF p.3: `.ipynb` ejecutable "desde cero y en orden", instrucciones para repetirlo, ficha mínima (modelo, dependencias con versiones, variables, datos), prompts, trazas; adjuntar por separado los prompts usados con el agente de código ("si usaron OpenCode") (TF p.3) [SUPUESTO: aplicarlo también a Claude Code; la pauta dice OpenCode explícitamente] -> encaja con `docs/dev_prompts.md` del proyecto.
- Estructuras de notebook modelo: 10 secciones de `primer agente.ipynb` (objetivo/alcance, entorno, configuración, prompts, fuentes, herramientas, estado/memoria/flujo, visualización, errores/límites/métricas, comprobaciones, conversación) y las 12 del agente `notebook` (portada, entorno, config, estado, grafo con mermaid, conexiones, recorrido paso a paso, prompts, resultados de validación, zona libre). Reglas: guardar con salidas vacías o sin secretos, `try/except` en celdas que salen a la red, matriz de comprobaciones `VERIFICADO / IMPLEMENTADO SIN VERIFICAR`, mostrar solo presencia de variables (`notebook.md`, `estudio_ejecucion.ipynb`).
- Checklist propuesto a partir de TF (todo debe tener evidencia ejecutada en el notebook):
  1. Caso: usuario, entrada, alcance, salida, comprobación observable, justificación LLM+tool.
  2. Traza legible con modelo, configuración, fuentes y prompt de cada llamada.
  3. ReAct: tool solicitada por el LLM, observación devuelta, decisión repetir/responder, parada explícita; caso normal ejecutado.
  4. Historial: segundo turno con dato del primero, sin respuesta fija.
  5. Seguridad: fuera de alcance y jailbreak simple respetados; scope en cada llamada LLM; si se rompió, corregido y repetido.
  6. Bonos declarados y dónde se ejecutan (memoria, router, acción Sheets, juez, golden set), cada uno con prueba reproducible y sin doble crédito del mismo mecanismo.
  7. Ficha de reproducibilidad (Python, requirements con versiones, variables sin valores, datos sintéticos).
  8. Revisor ejecuta desde cero: el flujo central no debe depender de recursos privados.
  9. Sin claves ni datos personales; recursos externos de prueba utilizables por otra persona.

---------------------------------------------------------------------------------------------------

## 9. Conflictos y puntos que deberían cambiar el plan

1. **Riesgo de tope 3,0 por dependencia de Google Drive/Sheets en el flujo central.** TF p.4: si el flujo central (LLM, ReAct, herramienta, devolución de observación, parada, historial) no funciona en la revisión, tope 3,0; el revisor "configurará sus propias credenciales" para APIs y debe poder ejecutar con "recursos de prueba que otra persona pueda usar con seguridad". Recomendación: que la "herramienta básica pertinente" del ReAct sea `analizar_recibo` (solo requiere la API key de Gemini y un recibo sintético), y que Drive/Sheets sean la ampliación declarada con modo de ejecución seco/simulado o con instrucciones y recursos de prueba claramente separados, para que un fallo de credenciales Google no active el tope. [SUPUESTO: el plan actual encadena Drive/Sheets dentro del flujo; verificar].
2. **Los bonos planificados suman 3,5 > tope 3,0.** No requiere eliminar etapas, pero conviene decidir cuál es el más débil; el golden set (0,5) y el juez (0,5) son los más fáciles de invalidar por "duplica otro control", "no aplica el veredicto" o "fallos sin resolver".
3. **Sheets "solo agregar filas" vs. "puede repetirse con seguridad".** El bono de acción exige repetibilidad segura y estado anterior/posterior (TF p.2); append duplica (S6, lám. 8). El plan debe incluir deduplicación/idempotencia (p. ej. comprobar si el recibo ya fue registrado) y evidencia de conteo antes/después en una hoja de prueba.
4. **Stack y versión de Python.** AGENTS.md del proyecto fija Python 3.11 y "SDK oficial de Gemini" sin LangChain/LangGraph; el curso sugiere Python 3.12 (S1a, lám. 65) y trabaja con LangChain+LangGraph (`Taller/requirements.txt` con versiones). La pauta no exige ningún framework; basta declarar versión exacta de Python, dependencias con versiones y modelo exacto (TF p.3). Un ReAct propio con el SDK es admisible mientras muestre las trazas; solo hay que no usar nada fuera del stack permitido por el propio AGENTS.md. Decisión del usuario sobre 3.11 vs 3.12 [SUPUESTO: el revisor instala el entorno desde cero; declarar la versión resuelve el riesgo].
5. **Seguridad basal también en router, memoria y juez.** TF p.1 exige scope "en cada llamada al LLM que pueda decidir o responder". Las etapas 9-11 introducen nuevas llamadas LLM (clasificar, resumir, juzgar): cada una debe llevar `SECURITY_SCOPE_v1`. Además, el juez no debe ser un duplicado del scope prompt (TF p.2, "no suma si duplica el prompt basal").
6. **Los rieles de seguridad no son solo prompt.** S7 lám. 9-15: ENTRADA/ACCIÓN/SALIDA se suman al system prompt y revisar la salida "llega tarde" si la acción ya ocurrió. Recomendación: validar permisos y argumentos de `guardar_recibo`/`registrar_gasto` en código antes de ejecutar y no confiar solo en el prompt ni en el juez de salida.
7. **ReAct debe ser genuino (tool call iniciado por el LLM).** El único proyecto de referencia (`agente-colombia`) es router + nodos fijos; no ilustra el criterio. La referencia correcta es `implementador.md` (`bind_tools`/`tools_condition`) y S2a láms. 25-29. La condición de parada (`max_steps`, etc.) debe ser explícita y visible en la traza (TF p.1).
8. **Inyección indirecta vía recibo.** Texto dentro de la imagen del recibo puede contener instrucciones (S6, láms. 41-42). Incluir al menos un recibo adversarial sintético en las pruebas de seguridad y en el golden set.
9. **Telegram (etapa 13) y datos del curso.** Sin respaldo en rúbrica; mantenerlo fuera del camino crítico. RAG y MCP (+1,0 cada uno) no están en el plan y exigen Redis del curso / servidor MCP gratuito invocado solo si hace falta; opcional, no recomendado a menos que sobren puntos que cubrir.
10. **Prompts de desarrollo.** TF p.3 exige adjuntar por separado los prompts dados al agente de código (OpenCode en el texto); el proyecto usa Claude Code. Mantener `docs/dev_prompts.md` actualizado y limpio de claves. S5 láms. 31 y 46 dan la estructura de prompt de construcción (ROL, OBJETIVO, ALCANCE, ENTORNO, CONFIGURACIÓN Y SEGURIDAD, ORGANIZACIÓN, COMPORTAMIENTO, FLUJO Y MEMORIA, INTERACCIÓN Y CONTROLES, PRUEBAS Y ENTREGA).
11. **Convención de prompts.** El curso exige un archivo `prompts/{nodo}_prompt.py` por nodo con LLM; el proyecto concentra los prompts en `app/prompts.py` versionados (`NOMBRE_PROMPT_vN`). No hay conflicto con la rúbrica (pide prompts visibles y documentados), solo diferencia de organización.
12. **Veracidad de modelos.** Los IDs que aparecen en el curso (`gemini-3.5-flash-lite`, `gemini-3.6-flash`, `gemini-2.5-flash`, `gemini-embedding-001`) no están confirmados como válidos ni con visión; la regla del proyecto "no inventes IDs de modelo" se mantiene. Confirmar el modelo de visión en la documentación oficial antes de fijarlo en la ficha de modelo.
13. **Seguridad de credenciales en el material del curso.** Hay un `.env` dentro de `seccion 5- seguridad.zip`, una contraseña de plataforma en S2a lám. 8 y una URL de Redis escrita en `Taller 2 · ...ipynb` (celda 6): no reutilizar ni copiar; refuerza la regla del proyecto de credenciales solo por variables de entorno.

---------------------------------------------------------------------------------------------------

## 10. Limitaciones del análisis

- `Sesion_4.pdf` es casi todo imagen; el texto extraíble es mínimo. Revisé 16 láminas por render visual (7, 8, 10, 12, 15, 18, 19, 20, 22, 23, 24, 26, 27, 29, 31 y la portada 5 con su infografía); no inspeccioné individualmente las láminas 1-4, 6, 9, 11, 13, 14, 16, 17, 21, 25, 28, 30, 32 más allá del texto extraído.
- En S2a, S2b, S3, S6 y S7 solo usé el texto extraíble; los diagramas e imágenes (ejemplos de demos, capturas de OpenCode, figuras de LangChain/Microsoft/Google) no se interpretaron.
- S6 láms. 29-31 ("Última hora", modelo clasificador como alternativa al juez) tienen casi todo su contenido en imágenes: lo citado proviene de dos líneas de texto extraíbles; las cifras ("200 veces más rápido", "400 veces menos") figuran sin fuente en el texto.
- `Clase 2026-08-18.md` está vacío. `Lab 1 - Entendiendo la plataforma.ipynb` solo tiene 2 celdas. No hay en los archivos la rúbrica numérica del Taller 2 ni la fecha de entrega de la tarea final.
- Los `.zip` son copias de las carpetas extraídas (se listaron nombres, sin abrir el `.env`).
- `Tabla.xlsx` y `Taller_2_RAG_Colab_equipo3.ipynb` son trabajo de un equipo, no material docente: se usaron solo para ver la estructura de entregables.
- `2023_UNAB_MTT630...pdf` y `Normativa_Devoluciones...pdf` son corpus para el RAG de ejemplo y no se analizaron en detalle (no aportan al proyecto salvo como ejemplo de corpus ficticio con versiones y fuente no vigente).
