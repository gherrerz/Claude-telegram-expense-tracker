"""Carga el corpus del RAG en el Redis del curso (Etapa 15, adenda A14).

Lee `data/corpus/*.md`, lo fragmenta (500 caracteres con 100 de solape), calcula los embeddings
(`gemini-embedding-2`, 768 dimensiones), crea el índice HNSW/COSINE si falta y escribe un HASH por
fragmento bajo `{REDIS_PREFIX}:rag:chunk:`. Guarda la firma del corpus en `{REDIS_PREFIX}:rag:firma`
y, si no cambió, omite la carga (sin llamadas de embeddings).

Uso:
    .venv\\Scripts\\python scripts\\load_corpus.py             indexa u omite según la firma
    .venv\\Scripts\\python scripts\\load_corpus.py --force     reconstruye SOLO nuestro índice y claves
    .venv\\Scripts\\python scripts\\load_corpus.py --dry-run   solo fragmenta y muestra la firma (sin red)

Requiere GEMINI_API_KEY, LLM_MODEL, REDIS_URL y REDIS_PREFIX (salvo con --dry-run). Si falta alguna
sale con código 2 sin llamar a la red. Nunca imprime la URL de Redis, y nunca toca otros prefijos:
el prefijo debe ser no vacío y solo de letras, números, guion y guion bajo.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.llm import EmbeddingError, LLMCallError, LLMClient  # noqa: E402
from app.rag.chunking import CHUNK_OVERLAP, CHUNK_SIZE, chunk_documents  # noqa: E402
from app.rag.corpus import corpus_signature, read_corpus  # noqa: E402
from app.rag.indexer import index_corpus  # noqa: E402
from app.rag.store import RagStoreError, RedisVectorStore  # noqa: E402
from app.trace import Tracer  # noqa: E402

REQUIRED = ("GEMINI_API_KEY", "LLM_MODEL", "REDIS_URL", "REDIS_PREFIX")


def print_index_info(store: RedisVectorStore) -> None:
    info = store.index_info()
    cfg = info["configurado"]
    print("\nÍndice del RAG")
    print(f"  Índice:            {info['indice']}")
    print(f"  Prefijo de claves: {info['prefijo_claves']}")
    print(f"  Clave de firma:    {info['clave_firma']}")
    print(f"  Documentos:        {info['num_docs']}")
    print(f"  Algoritmo:         {cfg['algoritmo']} | tipo: {cfg['tipo_vector']} | "
          f"dimensiones: {cfg['dimensiones']} | métrica: {cfg['metrica']}")
    print(f"  Embeddings:        {cfg['modelo_embeddings']}")
    print(f"  Campos:            {', '.join(cfg['campos'])}")
    print(f"  Atributos (FT.INFO): {info['atributos']}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = set(sys.argv[1:])
    unknown = args - {"--force", "--dry-run"}
    if unknown:
        print(f"ERROR: opciones desconocidas: {', '.join(sorted(unknown))}. Usa --force o --dry-run.")
        return 2
    try:
        documents = read_corpus()
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2
    chunks = chunk_documents(documents)
    signature = corpus_signature(documents)
    print(f"Corpus: {len(documents)} documentos, {len(chunks)} fragmentos "
          f"(tamaño {CHUNK_SIZE}, solape {CHUNK_OVERLAP}) | firma {signature}")
    if "--dry-run" in args:
        for name in sorted(documents):
            print(f"  {name}: {sum(1 for c in chunks if c.fuente == name)} fragmentos")
        print("--dry-run: no se llamó a la red.")
        return 0

    status = config_status()
    missing = [n for n in REQUIRED if status[n] == "falta"]
    if missing:
        print(
            f"ERROR: faltan variables de entorno: {', '.join(missing)}.\n"
            "Copia .env.example a .env y completa la clave de Gemini, LLM_MODEL, REDIS_URL y "
            "REDIS_PREFIX. No se hizo ninguna llamada de red."
        )
        return 2
    try:
        settings = load_settings(required=["llm", "rag"])
        store = RedisVectorStore.from_settings(settings)
    except (ConfigError, RagStoreError, ValueError) as error:
        print(f"ERROR: {error}")
        return 2

    llm = LLMClient(settings=settings, tracer=Tracer(console=False, write_file=False))
    print(f"Prefijo del grupo: {settings.redis_prefix} | índice: {store.index_name}")
    try:
        report = index_corpus(store, llm, documents, force="--force" in args)
        print(f"\nResultado: {report.accion} ({report.razon}); {report.fragmentos} fragmentos.")
        print(f"Embeddings: {llm.embed_stats.as_dict()}")
        print_index_info(store)
    except (RagStoreError, LLMCallError, EmbeddingError) as error:
        print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
