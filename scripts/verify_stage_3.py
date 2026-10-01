"""Verificación real de la Etapa 3 (la ejecuta el autor con su `.env`).

Pasos (consume unas 8 llamadas de la capa gratuita):
1. Llamada de humo de texto.
2. Llamada de visión sobre `receipt_normal.jpg`.
3. Los 3 recibos con temperatura 0.0 y con 1.0, comparados con `expected.json`.

Imprime una tabla resumen y escribe la traza en `traces/verify-stage3.jsonl`.
Si faltan GEMINI_API_KEY o LLM_MODEL, sale con código 2 sin llamar a la red.

Uso:
    .venv\\Scripts\\python scripts\\verify_stage_3.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ConfigError, config_status, load_settings  # noqa: E402
from app.llm import LLMCallError, LLMClient  # noqa: E402
from app.models import UNKNOWN, ReceiptData  # noqa: E402
from app.tools.analyzer import analizar_recibo  # noqa: E402
from app.trace import Tracer  # noqa: E402

RECEIPTS = ROOT / "data" / "receipts"
TEMPERATURES = (0.0, 1.0)


def matches_expected(name: str, receipt: ReceiptData, expected: dict) -> bool:
    """Criterio de las pruebas `live`: normal/difícil exactos; ilegible desconocido."""
    if name == "receipt_illegible.jpg":
        return (receipt.monto == UNKNOWN or receipt.fecha == UNKNOWN) and receipt.confianza <= 0.5
    return (
        receipt.fecha == expected["fecha"]
        and receipt.monto == expected["monto"]
        and expected["comercio"].lower() in receipt.comercio.lower()
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    status = config_status()
    missing = [n for n in ("GEMINI_API_KEY", "LLM_MODEL") if status[n] == "falta"]
    if missing:
        print(
            f"ERROR: faltan variables de entorno: {', '.join(missing)}.\n"
            "Copia .env.example a .env, complétalas (LLM_MODEL=gemini-3.5-flash-lite) "
            "y vuelve a ejecutar. No se hizo ninguna llamada de red."
        )
        return 2
    try:
        settings = load_settings(required=["llm"])
    except ConfigError as error:
        print(f"ERROR: {error}")
        return 2

    expected = json.loads((RECEIPTS / "expected.json").read_text(encoding="utf-8"))
    tracer = Tracer(session="verify-stage3", console=False)
    llm = LLMClient(settings=settings, tracer=tracer)
    print(f"Modelo configurado (LLM_MODEL): {settings.llm_model}")
    ok = True

    print("\n[1] Humo de texto")
    try:
        text = llm.generate_text("Responde con una frase corta confirmando que funcionas.")
        print(f"    respuesta: {(text.text or '').strip()[:120]!r}")
        print(f"    tokens: {text.usage}  latencia: {text.latency_ms} ms")
    except LLMCallError as error:
        print(f"    FALLÓ: {error}")
        ok = False

    print("\n[2] Visión sobre receipt_normal.jpg")
    try:
        receipt = analizar_recibo(RECEIPTS / "receipt_normal.jpg", llm=llm)
        print(f"    {receipt.model_dump()}")
    except LLMCallError as error:
        print(f"    FALLÓ: {error}")
        ok = False

    print("\n[3] Temperatura 0.0 frente a 1.0")
    rows = []
    for temperature in TEMPERATURES:
        for name, exp in expected.items():
            try:
                receipt = analizar_recibo(RECEIPTS / name, llm=llm, temperature=temperature)
                verdict = "OK" if matches_expected(name, receipt, exp) else "DIFIERE"
                detail = f"{receipt.fecha} | {receipt.comercio} | {receipt.monto}"
            except LLMCallError as error:
                verdict, detail = "ERROR", f"código={error.code} estado={error.status}"
            rows.append((temperature, name, verdict, detail))
            if temperature == 1.0 and verdict != "OK":
                ok = False  # 1.0 es la recomendación de Google para Gemini 3

    print(f"\n{'temp':<5} {'archivo':<24} {'resultado':<9} extraído")
    for temperature, name, verdict, detail in rows:
        print(f"{temperature:<5} {name:<24} {verdict:<9} {detail}")

    stats = llm.stats.as_dict()
    print(f"\nContadores de la sesión: {stats}")
    print(f"Traza: {tracer.path}")
    print("\nRESULTADO:", "OK" if ok else "CON FALLAS (revisar la tabla)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
