# Configuración del Redis del curso (RAG, Etapa 15)

El RAG de este proyecto (ruta `CONSULTAR_POLITICA`) guarda y consulta su índice vectorial en **el Redis del curso**. No existe un índice local alternativo: la pauta del bono no lo admite. Redis se usa **solo** para el RAG; el estado y la conversación del agente siguen en memoria.

## Qué es el Redis del curso
- Un Redis **compartido** que provee el docente a todos los grupos, con el módulo de búsqueda (RediSearch), necesario para el índice vectorial. En la comprobación de solo lectura del 2026-10-02 respondió Redis 8.4.0 con los módulos `search`, `vectorset`, `ReJSON`, `bf` y `timeseries`.
- Como es compartido, cada grupo trabaja bajo **su propio prefijo** (`REDIS_PREFIX`). Todo lo que crea este proyecto vive bajo ese prefijo y el código nunca lee, escribe ni borra nada fuera de él.
- Este proyecto no despliega ni administra ese Redis. No se agrega Docker ni otro servicio (ver `AGENTS.md`).

## 1. Variables en `.env`
La URL de conexión **la entrega el docente**, incluye la contraseña y es un secreto: va **solo** en `.env` como `REDIS_URL`. Nunca en el código, el notebook, las trazas, la documentación ni git (`.env` está ignorado por git).

```
REDIS_URL=<URL de conexión entregada por el docente>
REDIS_PREFIX=<prefijo de tu grupo>
```

- `REDIS_PREFIX`: el prefijo de grupo (el de este proyecto es `Grupo_03_TrabajoFinal_v1`). Es obligatorio y solo admite letras, números, guion y guion bajo (`[A-Za-z0-9_-]+`); un prefijo vacío o con otros caracteres se rechaza antes de tocar la red.
- `RAG_TOP_K` (opcional, de 1 a 10): cuántos fragmentos se recuperan. Por defecto 3.
- `RAG_THRESHOLD` (opcional, de 0 a 1): umbral de similitud bajo el cual el asistente se abstiene. Por defecto 0,75, el valor calibrado (ver más abajo). No hace falta declararlo.
- Además se necesitan `GEMINI_API_KEY` y `LLM_MODEL`, que usa el resto del proyecto. Los embeddings usan `gemini-embedding-2` con 768 dimensiones (constantes del código, no son variables).

El proyecto nunca imprime `REDIS_URL`: el trazador enmascara cualquier URL de Redis completa y los errores de conexión se reducen al nombre de la clase de la excepción (sin host).

## 2. Qué se crea en Redis
Todo bajo el prefijo del grupo:

| Elemento | Nombre |
|---|---|
| Índice RediSearch | `{REDIS_PREFIX}:rag:idx` (con el prefijo del grupo: `Grupo_03_TrabajoFinal_v1:rag:idx`) |
| Claves de fragmentos (HASH) | `{REDIS_PREFIX}:rag:chunk:*` |
| Firma del corpus | `{REDIS_PREFIX}:rag:firma` |

Configuración del índice: campos `chunk_id` (TAG), `fuente` (TAG), `seccion` (TEXT), `texto` (TEXT) y `embedding` (VECTOR); algoritmo HNSW, tipo FLOAT32, 768 dimensiones, métrica COSINE (M=16, ef_construction=200). La similitud es 1 menos la distancia coseno.

## 3. Cargar el corpus (antes de la Sección 11 del notebook)
El corpus sintético está en `data/corpus/` (ver `data/corpus/README.md`). Con `GEMINI_API_KEY`, `LLM_MODEL`, `REDIS_URL` y `REDIS_PREFIX` definidas:

```powershell
.venv\Scripts\python scripts\load_corpus.py --dry-run  # solo fragmenta y muestra la firma; no usa la red
.venv\Scripts\python scripts\load_corpus.py            # indexa; omite si el corpus no cambió
.venv\Scripts\python scripts\load_corpus.py --force    # reconstruye SOLO nuestro índice y nuestras claves
```

- **`--dry-run`:** lee y fragmenta el corpus y calcula la firma, sin llamar a Gemini ni a Redis. Resultado esperado con el corpus actual: 3 documentos, 29 fragmentos (tamaño 500, solape 100), firma `67bdb44ba7b257ba804e71627131b0c0`.
- **Carga normal:** calcula los embeddings de todos los fragmentos antes de tocar el índice, crea el índice si falta y escribe un HASH por fragmento. Guarda la firma md5 del corpus (archivos, parámetros de fragmentación, modelo, dimensiones y plantillas).
- **Omisión por firma:** si la firma guardada coincide con la actual y el índice está completo, no hace nada (cero llamadas de embeddings). Cambiar un documento, los parámetros, el modelo o las dimensiones cambia la firma y la siguiente ejecución reindexa.
- **`--force`:** borra y recrea el índice. El borrado solo alcanza el índice, las claves `{REDIS_PREFIX}:rag:chunk:*` y la firma propios; cada clave se vuelve a comprobar antes de borrarla.
- Carga real del 2026-10-02: 3 documentos, 29 fragmentos, 2 llamadas de embeddings (29 textos) y 0 reintentos; el índice quedó con 29 documentos.

## 4. Calibrar y verificar
```powershell
.venv\Scripts\python scripts\calibrate_rag_threshold.py   # umbral: preguntas dentro y fuera del corpus
.venv\Scripts\python scripts\verify_stage_15.py           # verificación real de las tres entradas
.venv\Scripts\python -m pytest -m live tests\test_stage15_live.py
```

- **Calibración** (solo embeddings y consultas al índice, sin generación): mejor parecido de las preguntas dentro del corpus 0,7933 (taxi), 0,8283 (plazos), 0,7929 (alcohol) y 0,8201 (farmacia a Salud); fuera del corpus 0,5622 (cazuela), 0,5148 (mundial), 0,6130 (teletrabajo) y 0,6988 (hotel en el extranjero). Peor acierto 0,7929, mejor fallo 0,6988, margen 0,0941: el umbral por defecto es **0,75**. El valor provisional de 0,60 habría aceptado dos preguntas ajenas.
- **Verificación** (`verify_stage_15.py`, 2026-10-02, `RESULTADO: OK`): una pregunta sobre propinas recupera y cita su fuente; «Hola» no recupera; una pregunta fuera del corpus se abstiene sin llamar al LLM de generación. Total: 5 llamadas de generación, 2 embeddings y 0 reintentos. `pytest -m live tests/test_stage15_live.py`: 4 passed.
- Los tres scripts salen con código 2, sin llamar a la red, si falta alguna variable.

## 5. Qué pasa sin Redis (modo degradado)
Nada se simula (decisión A12):
- **Sin `REDIS_URL` o `REDIS_PREFIX`**, o con el Redis caído o el índice ausente, la ruta `CONSULTAR_POLITICA` responde con honestidad que la base de conocimiento no está disponible y se detiene con `rag_no_disponible`. No hay embeddings ni llamada de generación.
- **El resto del agente no cambia:** registrar recibos, consultar gastos y conversar funcionan sin Redis. Solo el RAG se degrada.
- **Notebook:** la Sección 11 corre sin red la parte del corpus y la fragmentación, y omite con un aviso la parte real (`omitido: falta ...`).
- **Golden set v2:** los casos `rag: true` (GS11 a GS14) quedan `PENDIENTE` sin esta configuración (o `OMITIDO` con `--no-rag`); la corrida no queda completa (`docs/evaluation.md`).

## 6. Seguridad
- **Un solo prefijo.** Redis es compartido con otros grupos. Nunca ejecutes comandos manuales sobre claves que no empiecen con tu prefijo, ni uses `FLUSHDB`, `FLUSHALL` o borrados por patrón amplio. Si necesitas empezar de cero usa `--force`, que solo toca lo propio.
- **El corpus es dato, no instrucción.** Los fragmentos recuperados viajan entre `<contexto>` y `<pregunta>` y `SECURITY_SCOPE_v3` los trata como dato; una orden escondida en un documento no se ejecuta, y la ruta no tiene tools.
- **Corpus sintético.** `data/corpus/` contiene solo documentos ficticios; no cargues documentos reales ni datos personales en un Redis compartido.
- **Secretos.** Si la URL se filtrara, pide al docente que la rote; no la pegues en issues, chats ni commits.
