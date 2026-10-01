# Etapa 2 — Proyecto Python base y trazador

**Objetivo:** base Python 3.12 con configuración, modelos Pydantic y trazador con enmascarado de secretos (prompt maestro v2, Etapa 2; adenda A9: Python 3.12).
**Criterio de rúbrica:** LLM real y trazabilidad (traza legible), aún sin llamadas LLM.
**Ruta:** delegated direct (writer trigger: 2+ archivos no triviales).
**TDD:** desactivado (sin configuración de proyecto); se ejecutan pruebas funcionales con `pytest`.
**Restricción:** `.env.example` está bloqueado por los permisos del agente de desarrollo; el autor lo actualiza con el contenido propuesto.

## Tareas
- [x] T1 `requirements.txt` con versiones fijadas y `.venv` con Python 3.12.
- [x] T2 `app/config.py`: lee el entorno, falla con mensaje claro y sin imprimir valores.
- [x] T3 `app/models.py`: `ReceiptData`, `DriveResult`, `SheetResult`, `TraceEvent`, `AgentState`.
- [x] T4 `app/trace.py`: 10 tipos de evento, consola legible, JSONL en `traces/`, enmascarado.
- [x] T5 Pruebas `tests/test_stage2_*.py` y suite completa en verde.
- [x] T6 Sección del notebook que corre sin `.env`.
- [x] T7 Documentación: Python 3.12 en AGENTS.md y README, bitácora en `docs/dev_prompts.md`.
- [ ] T8 `.env.example` (lo actualiza el autor).

## Evidencia
- `py -3.12 -m venv .venv` + `pip install` (versiones fijadas en `requirements.txt`): Python 3.12.3, instalación correcta.
- `.venv\Scripts\python -m pytest -q`: `56 passed` (incluye `test_repo_hygiene.py` y las pruebas `test_stage2_*`; la prueba que exige las 8 variables en `.env.example` pasó).
- `.venv\Scripts\python -m jupyter nbconvert --to notebook --execute notebooks/demo.ipynb --output-dir <scratchpad> --output demo_executed.ipynb`: ejecución sin errores, sin `.env` ni red; las 8 variables salen como `falta` y el secreto falso aparece como `***` en consola y JSONL (`El secreto aparece en el JSONL: False`). El notebook versionado conserva las salidas vacías.
- Ajuste: `tests/test_repo_hygiene.py` ahora omite `.venv` y cachés en `test_no_secrets_committed` (el entorno virtual contiene claves de prueba de terceros).
- Corrección del orquestador: el enmascarado por nombre de campo se acotó para no ocultar métricas (`prompt_token_count`) ni claves de deduplicación, y solo se aplica a valores de texto. Se agregó una prueba. Resultado: `.venv\Scripts\python -m pytest -q` → `57 passed`; el notebook se ejecuta sin errores.
- T8 queda abierta: la actualiza el autor.
