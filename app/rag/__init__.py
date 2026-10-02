"""RAG con el Redis del curso (Etapa 15, adenda A14).

Flujo: `data/corpus/*.md` -> fragmentación por secciones con solape (`chunking`) -> embeddings
(`LLMClient.embed`) -> índice vectorial HNSW/COSINE en el Redis del curso (`store`) -> recuperación
top-k con umbral que abstiene SIN llamar al LLM (`retriever`) -> respuesta citando las fuentes
(ruta `CONSULTAR_POLITICA` de `app/assistant.py`).

Módulos:
- `formats`: plantillas de texto de documentos y consultas (la tarea va en el texto).
- `chunking`: división de Markdown en fragmentos con `chunk_id` estable, fuente y sección.
- `corpus`: lectura del corpus y firma md5 para no reindexar si nada cambió.
- `store`: adaptador del Redis (índice, carga, KNN, nombres con el prefijo del grupo).
- `indexer`: carga idempotente del corpus (la usa `scripts/load_corpus.py`).
- `retriever`: embedding de la consulta, top-k, umbral y evento `RETRIEVAL`.
- `knowledge`: construcción de la base de conocimiento desde la configuración.
- `demo`: casos y comprobaciones compartidos por el script, la prueba `live` y el notebook.
"""
