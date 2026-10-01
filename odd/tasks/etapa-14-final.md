# Etapa 14 — Notebook final, entrega y revisión contra la rúbrica

**Objetivo:** el notebook corre de principio a fin en un kernel limpio, con las secciones en el orden de la rúbrica. Quedan la ficha de reproducción, la medición de llamadas frente a los límites gratuitos, las trazas de ejemplo y el checklist de la rúbrica con evidencia localizable.
**Criterio de rúbrica:** todos. El notebook, el entorno, los prompts y las pruebas son la evidencia (TF p.1 y p.3–4).

## Decisiones de diseño (orquestador)
1. **Orden de secciones:** 0 Setup y ficha, 1 Caso, 2 LLM y prompts, 3 ReAct, 4 Historial, 5 Seguridad, 6 Router, 7 Memoria, 8 Acción, 9 Juez, 10 Golden set.
2. **Dos copias del notebook.** `notebooks/demo.ipynb` se versiona sin salidas, para que el revisor lo ejecute desde cero. `notebooks/demo_executed.ipynb` es la copia ejecutada con credenciales reales, como evidencia: la traza enmascara los secretos y antes de versionarla se revisa que no los tenga.
3. **Medición real.** Las llamadas del notebook completo y del golden set (65, corrida v1) se miden y se comparan con los límites gratuitos citando la fuente. Google no publica cifras por modelo, solo la página de rate limits y AI Studio: no se inventan números.
4. **Prompts de desarrollo.** El documento `docs/opencode_prompts.md` que pide el prompt maestro es `docs/dev_prompts.md` (adenda A1).

**Ruta:** delegated direct (el escritor reordena y documenta; el orquestador ejecuta y mide). Rama `feat/etapa-14-final`.

## Tareas
- [x] T1 Reordenar el notebook (secciones 0–10), ficha de reproducción en la Sección 0 y contador de llamadas al final.
- [x] T2 `docs/setup_llm.md`, la ficha en el README y `docs/trace_examples.md`, con trazas reales ya generadas.
- [x] T3 `docs/checklist_rubrica.md`: cada criterio y bono con estado, celda y prueba.
- [x] T4 Ejecución real completa del notebook: código de salida 0, 53 celdas sin errores, 73 llamadas, 137.042 tokens, unos 24 min y 42 reintentos 503; `notebooks/demo_executed.ipynb` sin secretos.
- [ ] T5 Suite completa en verde: 468 de 469 pasan. Falta la línea `TELEGRAM_ALLOWED_CHAT_IDS=` en `.env.example`, que agrega el autor.

## Evidencia
- **T1 (2026-10-01):** `notebooks/demo.ipynb` con 53 celdas y sin salidas. El orden ya era 0 a 10; se agregó la ficha de reproducción y la celda de parámetros (Sección 0, celdas #6 a #8), se corrigió texto desactualizado y se agregó el cierre «Resumen de consumo» (celdas #51 y #52). Acumulador de consumo: `session_stats()` en `app/llm.py` (prueba: `tests/test_stage14_session.py`, 4 pruebas). `nbconvert --execute` con las variables en blanco: sin errores. Sección 0 más cada sección por separado: corren sin errores.
- **T2 (2026-10-01):** `docs/setup_llm.md`, README con la ficha, pruebas, verificación por etapa, consumo (marcadores `<<MEDIR: …>>` para el orquestador), estado 1 a 14 y entregables, y `docs/trace_examples.md` con extractos de trazas reales (sin patrones de secretos; identificadores de Drive reemplazados).
- **T3 (2026-10-01):** `docs/checklist_rubrica.md` con la base, los cinco bonos declarados, RAG y MCP no declarados, la aritmética 3,5 frente a 3,0 y el tope 3,0. Todos los nombres de prueba citados existen (colectados con pytest).
- `pytest -q -m "not live"` (variables en blanco): 468 passed, 1 failed (`.env.example` sin `TELEGRAM_ALLOWED_CHAT_IDS`; lo corrige el autor).
- Pendiente para T4 y T5: corrida real del notebook, medición, copia ejecutada, completar `<<MEDIR: …>>` en el README y el estado de la fila 14.
