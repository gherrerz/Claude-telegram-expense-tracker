"""Calibra el umbral del RAG (Etapa 15), con el patrón del taller del curso.

Corre una lista fija de preguntas con respuesta en el corpus y otras sin ella (`app/rag/demo.py`),
imprime el MEJOR parecido (coseno) de cada una y propone un umbral en el margen entre ambos grupos.
Solo usa embeddings (una llamada por pregunta) y consultas al índice: NO hace llamadas de generación.

El valor propuesto se pone en `.env` como `RAG_THRESHOLD=<valor>`; mientras no se calibre rige el
provisional de `app/config.py` (`DEFAULT_RAG_THRESHOLD`).

Requiere GEMINI_API_KEY, LLM_MODEL, REDIS_URL, REDIS_PREFIX y el índice cargado
(`scripts/load_corpus.py`). Si falta algo sale con código 2 sin llamar a la red.

Uso:
    .venv\\Scripts\\python scripts\\calibrate_rag_threshold.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_RAG_THRESHOLD, ConfigError, config_status, load_settings  # noqa: E402
from app.llm import EmbeddingError, LLMCallError, LLMClient  # noqa: E402
from app.rag.demo import CALIBRATION_IN, CALIBRATION_OUT, suggest_threshold  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402
from app.rag.store import RagStoreError, RedisVectorStore  # noqa: E402
from app.trace import Tracer  # noqa: E402

REQUIRED = ("GEMINI_API_KEY", "LLM_MODEL", "REDIS_URL", "REDIS_PREFIX")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    status = config_status()
    missing = [n for n in REQUIRED if status[n] == "falta"]
    if missing:
        print(
            f"ERROR: faltan variables de entorno: {', '.join(missing)}.\n"
            "No se hizo ninguna llamada de red."
        )
        return 2
    try:
        settings = load_settings(required=["llm", "rag"])
        store = RedisVectorStore.from_settings(settings)
    except (ConfigError, RagStoreError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2

    llm = LLMClient(settings=settings, tracer=Tracer(console=False, write_file=False))
    scores: dict[str, list[float]] = {"dentro": [], "fuera": []}
    print(f"Índice: {store.index_name} | top_k: {settings.rag_top_k} | "
          f"umbral provisional: {DEFAULT_RAG_THRESHOLD}\n")
    print(f"{'grupo':<7} {'mejor':>7}  {'fuente / sección':<62} pregunta")
    try:
        for group, questions in (("dentro", CALIBRATION_IN), ("fuera", CALIBRATION_OUT)):
            for question in questions:
                result = retrieve(question, store, llm, None, settings.rag_top_k, 0.0)
                scores[group].append(result.mejor_similitud)
                top = result.fragmentos[0] if result.fragmentos else {"fuente": "-", "seccion": "-"}
                where = f"{top['fuente']} / {top['seccion'].split(' / ')[-1]}"
                print(f"{group:<7} {result.mejor_similitud:>7.4f}  {where[:62]:<62} {question}")
    except (RagStoreError, LLMCallError, EmbeddingError) as error:
        print(f"ERROR: {error}")
        return 1

    result = suggest_threshold(scores["dentro"], scores["fuera"])
    print(f"\nPeor acierto (dentro): {result['min_dentro']} | mejor desacierto (fuera): {result['max_fuera']}"
          f" | margen: {result['margen']}")
    if result["separable"]:
        print(f"Umbral sugerido: RAG_THRESHOLD={result['sugerido']}  (agrégalo a .env)")
    else:
        print("Los grupos se solapan: ningún umbral los separa con estas preguntas. "
              "Revisa el corpus, las preguntas o la plantilla de los embeddings.")
    print(f"Embeddings: {llm.embed_stats.as_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
