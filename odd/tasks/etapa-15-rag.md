# Etapa 15 — RAG con el Redis del curso — BONO +1,0

**Objetivo:** revertir la decisión "Sin RAG" (`docs/architecture.md`, sección 11). El agente responde preguntas sobre una política de rendición de gastos ficticia, recuperando fragmentos desde **el Redis del curso** solo cuando la pregunta lo necesita, y cita las fuentes.
**Criterio de rúbrica:** bono "RAG" +1,0 (TF p.2).
- **Exige:** la entrada y la decisión de recuperar; el corpus, el índice exacto, la carga y la configuración (embeddings, campos, dimensiones, métrica y algoritmo); los fragmentos, las fuentes y su uso en la respuesta.
- **No suma** si no usa el Redis del curso, si no recupera, o si recupera sin necesidad. Tampoco se admite un índice local alternativo.

**Decisión del autor (2026-10-02, adenda A14):** usar el Redis compartido del curso, con el prefijo de grupo `Grupo_03_TrabajoFinal_v1`. La URL, que incluye la contraseña, va solo en `.env` como `REDIS_URL` y nunca en código, docs, notebook ni trazas.

**Nota de nota:** los bonos declarados pasan de +3,5 a +4,5, con el mismo tope de +3,0. El RAG suma redundancia, no puntaje máximo.

**Ruta:** delegated direct. Rama `feat/etapa-15-rag`.
**TDD:** desactivado; pruebas offline y `live`.

## Tareas
- [x] T0 Verificar el modelo de embeddings (capa gratuita, dimensiones) y si el Redis del curso tiene RediSearch (solo lectura).
- [x] T1 `AGENTS.md` (excepción "Redis del curso, solo RAG") y adenda A14; config `REDIS_URL`, `REDIS_PREFIX`, `RAG_TOP_K` y `RAG_THRESHOLD`; dependencia `redis` fijada.
- [x] T2 Corpus sintético `data/corpus/` (política de rendición y guía de categorías) y `scripts/load_corpus.py` (fragmentación con solape, embeddings, índice y firma md5).
- [x] T3 `app/rag/`: almacén Redis, recuperador top-k por coseno y umbral que abstiene sin llamar al LLM; `LLMClient.embed()`; evento `RETRIEVAL`.
- [x] T4 Ruta `CONSULTAR_POLITICA` (`ROUTER_PROMPT_v3`), `RAG_PROMPT_v1` y `SECURITY_SCOPE_v3`; degradación honesta sin Redis.
- [x] T5 Pruebas offline, `live` y `scripts/verify_stage_15.py`; Sección 11 del notebook.
- [ ] T6 Golden set v2 (solo agrega casos) y corrida `results_v2`.
- [ ] T7 Documentación: `architecture.md` §11, `solution_architecture.md`, `bonos.md`, checklist, README, `setup_redis.md` y bitácora.

## Evidencia
- **T0 (2026-10-02, comprobación real de solo lectura):**
  - **Redis del curso.** `ping` ok, versión 8.4.0, módulos `search`, `vectorset`, `ReJSON`, `bf` y `timeseries`; `FT._LIST` devuelve 12 índices de otros grupos y el prefijo `Grupo_03_TrabajoFinal_v1` tiene 0 claves. Conclusión: hay RediSearch, así que se puede usar un índice vectorial nativo (HNSW o FLAT).
  - **Embeddings.** `gemini-embedding-2` responde con el ID estable: 3072 dimensiones por defecto, 768 con `output_dimensionality`, y en ambos casos la norma es 1.0000, es decir, viene normalizado. `gemini-embedding-2-preview` también responde. `gemini-embedding-001` truncado a 768 devuelve norma 0.5863, así que habría que normalizarlo a mano.
  - **Fuentes:** https://ai.google.dev/gemini-api/docs/embeddings, https://ai.google.dev/gemini-api/docs/deprecations y https://ai.google.dev/gemini-api/docs/pricing ("Free of charge" para `gemini-embedding-2`).
  - **Confirmado por el autor (2026-10-02):** `gemini-embedding-2`, 768 dimensiones, HNSW con coseno.
- **T1-T5 (2026-10-02, escritor `sonnet`, ruta delegated direct; implementadas con pruebas offline; la verificación real queda pendiente del orquestador):**
  - **T1.** `requirements.txt`: `redis==8.1.0` y `numpy==2.5.3`. `app/config.py`: grupo `rag` (`REDIS_URL` secreta y `REDIS_PREFIX` validada con `^[A-Za-z0-9_\-]+$`), `RAG_TOP_K` (3, de 1 a 10) y `RAG_THRESHOLD` (0,60 PROVISIONAL, de 0 a 1) opcionales y fuera de `ALL_VARIABLES` (código con valor por defecto; `.env.example` no está obligado a declararlos), y las constantes `EMBEDDING_MODEL` y `EMBEDDING_DIMS`. El trazador enmascara cualquier URL `redis`/`rediss` completa además del valor de `REDIS_URL`. `AGENTS.md` (excepción A14) y `docs/dev_prompts.md` (fila A14 y bitácora de la Etapa 15, estado IMPLEMENTADA — VERIFICACIÓN REAL PENDIENTE).
  - **T2.** `data/corpus/` (política v2, guía de categorías v1, preguntas frecuentes v1 y README; sintético, ficticio) y `scripts/load_corpus.py` (`--force`, `--dry-run`). 29 fragmentos, tamaño 500, solape 100. Firma md5 del corpus (con parámetros, modelo, dimensiones y plantillas): `67bdb44ba7b257ba804e71627131b0c0`.
  - **T3.** `app/rag/` (`chunking`, `corpus`, `formats`, `store`, `indexer`, `retriever`, `knowledge`, `demo`), `LLMClient.embed` con contadores propios (`EmbedStats`, `session_embed_stats`), evento `RETRIEVAL` y refactor del bucle de reintentos (`_send_with_retries`) compartido por generación y embeddings. Símbolos de redis-py 8.1.0 comprobados en el código instalado: `redis.commands.search.field` (`TagField`, `TextField`, `VectorField`), `redis.commands.search.index_definition` (`IndexDefinition`, `IndexType`), `redis.commands.search.query.Query` (`sort_by`, `return_fields`, `paging`, `dialect`), `client.ft(nombre)` con `create_index`, `dropindex(delete_documents=True)`, `info()` y `search(query, query_params)`.
  - **T4.** `ROUTER_PROMPT_v3` (etiqueta `CONSULTAR_POLITICA`), `RAG_PROMPT_v1` y `SECURITY_SCOPE_v3` (activo; v1 y v2 se conservan). Ruta `CONSULTAR_POLITICA` en `app/assistant.py`: abstención sin LLM de generación (`rag_abstencion`), respuesta con contexto (`ruta_politica`) y degradación honesta (`rag_no_disponible`).
  - **T5.** `tests/test_stage15_rag.py` (offline), `tests/test_stage15_live.py` (`live`), `scripts/calibrate_rag_threshold.py`, `scripts/verify_stage_15.py` y la Sección 11 del notebook (antes de «Resumen de consumo»).
  - **Cambios deliberados en pruebas anteriores:** conteo de `EventType` (11), `SECURITY_SCOPE_v3` como bloque vigente, `ROUTER_PROMPT_v3` y los casos del router (cinco etiquetas).
  - **Verificación offline:** `pytest -q -m "not live"` con las variables en blanco: ver el reporte de cierre. `nbconvert --execute` en blanco: 56 celdas, sin errores, el RAG real se omite con aviso. Los tres scripts salen con código 2 sin red cuando falta configuración.
  - **Pendiente (orquestador):** `scripts/load_corpus.py`, `scripts/calibrate_rag_threshold.py` (fijar `RAG_THRESHOLD`), `scripts/verify_stage_15.py` y `tests/test_stage15_live.py` con el Redis del curso y Gemini reales.
