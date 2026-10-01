# Prompts de desarrollo y bitácora por etapa

La rúbrica pide adjuntar los prompts o instrucciones usados para desarrollar el proyecto. Este archivo registra el modelo de desarrollo, la adenda vigente y la instrucción recibida en cada etapa. La especificación completa está en [prompt_maestro_v2.md](prompt_maestro_v2.md).

## Modelo de desarrollo
- **Planificado originalmente:** OpenCode con `meta/muse-spark-1.3` vía OpenRouter.
- **Usado desde la Etapa 1:** Claude, en claude.ai (proyecto "Trabajo Curso Agentic IA"), por decisión del autor. Ver la adenda A1.
- El modelo de desarrollo no forma parte de la ejecución del agente. El revisor no lo necesita.

## Adenda al prompt maestro (vigente desde la Etapa 1)

| # | Ajuste | Motivo |
|---|---|---|
| A1 | Claude reemplaza a OpenCode como desarrollador. `docs/opencode_prompts.md` pasa a ser este archivo. Si más adelante se usa OpenCode, sus prompts también se registran aquí. | Cambio de ejecutor. |
| A2 | Nuevo estado de etapa: **IMPLEMENTADA — VERIFICACIÓN REAL PENDIENTE**. Las etapas que llaman a APIs externas incluyen `scripts/verify_stage_N.py`, que ejecuta el autor en su equipo. La etapa pasa a COMPLETADA solo con esa salida real. | El entorno de desarrollo no puede alcanzar Gemini, Google ni Telegram (el proxy responde `host_not_allowed`). |
| A3 | Cada etapa se entrega como `.zip` del repositorio. | El sistema de archivos del entorno de desarrollo puede reiniciarse entre turnos. |
| A4 | El proyecto se fija en Python 3.11; las pruebas offline del entorno de desarrollo corren en Python 3.12.3. | Versión disponible en el entorno de desarrollo. |

## Adenda para Claude Code (vigente desde 2026-09-30, antes de la Etapa 2)

| # | Ajuste | Motivo |
|---|---|---|
| A5 | Desde la Etapa 2 el desarrollo se hace con Claude Code (app de escritorio, modelo `claude-opus-5-5`) en el equipo Windows 11 del autor, directamente sobre esta carpeta. El prompt maestro v2 no cambia: donde dice "OpenCode", se lee "agente de desarrollo"; donde dice `docs/opencode_prompts.md`, se lee este archivo. | Cambio de ejecutor: de claude.ai a Claude Code local. |
| A6 | Queda sin efecto A3 (entrega en `.zip`). El repositorio local es persistente y es la fuente de verdad. | El sistema de archivos ya no se reinicia entre turnos. |
| A7 | Se mantiene A2, con un matiz: desde el equipo del autor sí se pueden alcanzar las APIs externas. Cuando el autor configure su `.env`, el agente de desarrollo ejecuta `scripts/verify_stage_N.py` y reporta la salida real. El agente nunca lee ni imprime el contenido de `.env`. **[SUPUESTO]** No se ha comprobado que haya conectividad hasta la primera llamada real. | Permite pasar etapas a COMPLETADA con evidencia propia. |
| A8 | El material del curso está en `../1-…` a `../7-…` (PDF exportados), no en `docs/curso/`. El análisis queda en `docs/curso_referencia.md` y el mapa en `docs/mapa_curso.md`. Es la fuente de verdad sobre la rúbrica: `tarea_final.pdf`, carpeta 6. | Corrige el pendiente de la Etapa 1. |
| A9 | Versión de Python: **Resuelto: Python 3.12, decisión del autor 2026-09-30.** El equipo tiene 3.12.3 y no tiene 3.11; el curso sugiere 3.12 (`Sesion1-18082026 - 01.pdf`, lám. 65). | A4 asumía un entorno distinto. |
| A10 | Riesgo de tope 3,0: si el flujo central (ReAct) depende de credenciales de Google y el revisor no las tiene, se activa el tope (TF p.4). **Decisión pendiente antes de la Etapa 4**: cómo degradar Drive y Sheets sin romper el flujo central. | Hallazgo del análisis de la pauta. |

## Bitácora

### Etapa 1 — Caso, criterio de éxito y arquitectura
- **Fecha:** 2026-09-30
- **Instrucción del autor:** "ahora quiero que ejecutes tu el prompt considera los ajustes o cambios necesarios al prompt antes de ejecutar."
- **Prompt aplicado:** `docs/prompt_maestro_v2.md`, sección "ETAPA 1", con la adenda A1–A4.
- **Resultado:** ver el reporte de cierre de la Etapa 1.

### Ajuste de entorno y material del curso (entre Etapas 1 y 2)
- **Fecha:** 2026-09-30
- **Modelo de desarrollo:** Claude Code, `claude-opus-5-5`. Un subagente `sonnet` analizó el material del curso.
- **Instrucción del autor (resumen):** continuar las etapas en esta carpeta local, analizar las carpetas 1–7 del curso como contexto y ajustar el prompt de referencia, pensado para OpenCode, para ejecutarlo con Claude Code.
- **Resultado:** adenda A5–A10, `docs/curso_referencia.md` creado y `docs/mapa_curso.md` completado.

### Etapa 2 — Proyecto Python base y trazador
- **Fecha:** 2026-09-30
- **Modelo de desarrollo:** Claude Code, `claude-opus-5-5` (orquestador) y un subagente `sonnet` (escritor).
- **Instrucción del autor:** "Python 3.12 y arrancá la Etapa 2".
- **Prompt aplicado:** `docs/prompt_maestro_v2.md`, sección "ETAPA 2", con la adenda A9 (Python 3.12).
- **Resultado:** `requirements.txt`, `app/config.py`, `app/models.py`, `app/trace.py`, pruebas `tests/test_stage2_*.py` y Sección 0 del notebook. Ver `odd/tasks/etapa-2-base-trazador.md` para la evidencia y el reporte de cierre de la Etapa 2.
