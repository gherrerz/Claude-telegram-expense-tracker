# Corpus del RAG (Etapa 15)

Documentos de la **política de rendición de gastos de una empresa FICTICIA**, "Consultora Andes Ficticia". Son la base de conocimiento de la ruta `CONSULTAR_POLITICA` del asistente.

## Origen y licencia

- **Sintéticos.** Se escribieron para este proyecto académico; no copian ningún documento real, ni de una empresa ni del curso. La empresa, los montos, los plazos y las reglas son inventados, y cada documento lo declara en su encabezado.
- **Licencia.** Sin datos personales ni material de terceros. Se pueden reutilizar y modificar libremente dentro del proyecto.
- **Coherencia con el agente.** Las categorías son las ocho que usa el agente: Alimentación, Supermercado, Transporte, Entretenimiento, Salud, Hogar, Ropa y Otros.

## Documentos

| Archivo | Versión | Contenido |
|---|---|---|
| `politica_rendicion_gastos_v2.md` | 2.0 (2026-03-01) | Qué se reembolsa, datos del comprobante, límites por categoría en CLP, propinas, alcohol, taxi y aplicaciones, plazos y aprobación |
| `guia_categorias_v1.md` | 1.0 (2026-03-01) | Cómo clasificar un gasto en las ocho categorías, con ejemplos y casos límite |
| `preguntas_frecuentes_v1.md` | 1.0 (2026-03-01) | Preguntas frecuentes sobre boletas perdidas, límites, pago y comprobantes borrosos |

Este `README.md` no forma parte del corpus: el cargador solo indexa los demás `.md` de la carpeta.

## Cómo (re)generar el índice

El índice vive en **el Redis del curso** (no hay índice local alternativo), bajo el prefijo de grupo `REDIS_PREFIX`. Con `GEMINI_API_KEY`, `LLM_MODEL`, `REDIS_URL` y `REDIS_PREFIX` definidas en `.env`:

```powershell
.venv\Scripts\python scripts\load_corpus.py            # indexa; omite si el corpus no cambió (firma md5)
.venv\Scripts\python scripts\load_corpus.py --force    # reconstruye SOLO nuestro índice y nuestras claves
.venv\Scripts\python scripts\load_corpus.py --dry-run  # solo fragmenta y muestra la firma; sin red
```

El cargador fragmenta cada documento por secciones (500 caracteres con 100 de solape), calcula los embeddings con `gemini-embedding-2` (768 dimensiones) y escribe un HASH por fragmento en `{REDIS_PREFIX}:rag:chunk:*`, con el índice `{REDIS_PREFIX}:rag:idx` (HNSW, FLOAT32, coseno) y la firma del corpus en `{REDIS_PREFIX}:rag:firma`. Nunca toca otros prefijos. Si cambias un documento, los parámetros de fragmentación, el modelo o las dimensiones, la firma cambia y la siguiente ejecución reindexa.
