"""Verificación real de la Etapa 15: RAG con el Redis del curso (la ejecuta el autor con su `.env`).

Imprime la configuración del índice (modelo, dimensiones, métrica, algoritmo, campos, prefijo y
cantidad de documentos) y pasa tres entradas por `ExpenseAssistant`, con Google DESACTIVADO (ninguna
ruta usa Drive ni Sheets):

  a) una pregunta cuya respuesta está en el corpus  -> recupera, cita las fuentes y responde
  b) "Hola"                                          -> respuesta directa, sin recuperar
  c) una pregunta que el corpus no cubre            -> abstención sin llamar al LLM de generación
                                                       (o rechazo, si el router la juzga ajena)

Por entrada muestra la ruta (`ROUTE`), la recuperación (`RETRIEVAL`: fragmentos, similitudes y
fuentes), la decisión, la respuesta y las comprobaciones; al final `RESULTADO`. La ruta que elige el
router depende del modelo: si no coincide con la esperada se informa FALLA, sin relajar el criterio.
Requiere el índice cargado (`scripts/load_corpus.py`).

Si falta GEMINI_API_KEY, LLM_MODEL, REDIS_URL o REDIS_PREFIX, sale con código 2 sin llamar a la red.
Nunca imprime la URL de Redis. Escribe las trazas en `traces/verify-stage15-<caso>.jsonl`.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_15.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.assistant import ExpenseAssistant  # noqa: E402
from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.models import AgentState, EventType  # noqa: E402
from app.prompts import SECURITY_SCOPE_ID  # noqa: E402
from app.rag.demo import RAG_CASES, evaluate_rag_case, retrieval_summary  # noqa: E402
from app.rag.knowledge import KnowledgeBase  # noqa: E402
from app.rag.store import RagStoreError, RedisVectorStore  # noqa: E402
from app.router import ROUTER_PROMPT_ID  # noqa: E402
from app.trace import Tracer  # noqa: E402

REQUIRED = ("GEMINI_API_KEY", "LLM_MODEL", "REDIS_URL", "REDIS_PREFIX")
GOOGLE_VARIABLES = (
    "GOOGLE_OAUTH_CLIENT_SECRETS", "GOOGLE_OAUTH_TOKEN", "DRIVE_FOLDER_ID", "SHEET_ID",
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    status = config_status()
    missing = [n for n in REQUIRED if status[n] == "falta"]
    if missing:
        print(
            f"ERROR: faltan variables de entorno: {', '.join(missing)}.\n"
            "Copia .env.example a .env y completa la clave de Gemini, LLM_MODEL, REDIS_URL y "
            "REDIS_PREFIX, y carga el índice con scripts/load_corpus.py. "
            "No se hizo ninguna llamada de red."
        )
        return 2
    for name in GOOGLE_VARIABLES:  # vacías, no ausentes: `load_dotenv(override=False)` no las llena
        os.environ[name] = ""
    try:
        settings = load_settings(required=["llm", "rag"])
        store = RedisVectorStore.from_settings(settings)
    except (ConfigError, RagStoreError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2

    print("Google: desactivado (ninguna ruta del RAG usa Drive ni Sheets)")
    print(f"Bloque de alcance: {SECURITY_SCOPE_ID} | router: {ROUTER_PROMPT_ID}")
    try:
        info = store.index_info()
    except RagStoreError as error:
        print(f"ERROR: {error}. ¿Se cargó el índice con scripts/load_corpus.py?")
        return 1
    cfg = info["configurado"]
    print("\n--- Configuración del índice ---")
    print(f"Prefijo del grupo:   {settings.redis_prefix}")
    print(f"Índice:              {info['indice']}  (claves {info['prefijo_claves']}*)")
    print(f"Documentos:          {info['num_docs']}")
    print(f"Embeddings:          {cfg['modelo_embeddings']} | {cfg['dimensiones']} dimensiones")
    print(f"Algoritmo y métrica: {cfg['algoritmo']} | {cfg['tipo_vector']} | {cfg['metrica']}")
    print(f"Campos:              {', '.join(cfg['campos'])}")
    print(f"Recuperación:        top_k={settings.rag_top_k} | umbral={settings.rag_threshold}")
    if info["num_docs"] == 0:
        print("ERROR: el índice no tiene documentos; ejecuta scripts/load_corpus.py.")
        return 1

    knowledge = KnowledgeBase(store, settings.rag_top_k, settings.rag_threshold)
    llm = LLMClient(settings=settings)
    all_ok = True
    for case in RAG_CASES:
        tracer = Tracer(session=f"verify-stage15-{case['id']}", console=False)
        assistant = ExpenseAssistant(llm=llm, tracer=tracer, knowledge_base=knowledge)
        result = assistant.handle(case["text"], None, state=AgentState(), tracer=tracer)
        route_event = next(e.data for e in tracer.events if e.event_type == EventType.ROUTE)
        retrieval = retrieval_summary(tracer)
        checks = evaluate_rag_case(case, result, tracer)
        print(f"\n--- Entrada {case['id']}) {case['name']} ---")
        print(f"Entrada:            {case['text']}")
        print(f"Evento ROUTE:       {json.dumps(route_event, ensure_ascii=False)}")
        if retrieval is None:
            print("RETRIEVAL:          (no hubo recuperación)")
        else:
            print(f"RETRIEVAL:          top_k={retrieval['top_k']} umbral={retrieval['umbral']} "
                  f"mejor={retrieval['mejor_similitud']} -> decisión: {retrieval['decision']}")
            for item in retrieval["resultados"]:
                print(f"    {item['similitud']:.4f}  [{item['fuente']} §{item['seccion']}]  "
                      f"({item['chunk_id']})")
        print(f"Motivo de parada:   {result.stop_reason}")
        print(f"Respuesta final:    {result.final_text}")
        for name, passed in checks.items():
            print(f"    {'OK ' if passed else 'FALLA'} {name}")
        all_ok = all_ok and all(checks.values())

    print(f"\nContadores LLM: {llm.stats.as_dict()}")
    print(f"Contadores de embeddings: {llm.embed_stats.as_dict()}")
    print("RESULTADO:", "OK" if all_ok else "CON FALLAS")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
