# Mapa de etapas frente a la materia del curso

**Estado: COMPLETADO** (2026-09-30, adenda A8 de [dev_prompts.md](dev_prompts.md)).

El material del curso está fuera del repositorio, en las carpetas `1-` a `7-` de `Curso 1 Agentic IA/`. Son PDF exportados desde las láminas, no `docs/curso/`. El análisis completo, con citas por archivo y lámina, está en [curso_referencia.md](curso_referencia.md). Las láminas se citan con el número de página del PDF.

Abreviaturas:
- S1b = `Sesion1-18082026 - 02.pdf`
- S2a = `Sesion 2-01.pptx.pdf`
- S2b = `Sesion 2- 02.pptx.pdf`
- S3 = `Sesion_3.pptx.pdf`
- S6 = `Sesion_6_Clase.pptx.pdf`
- S7 = `Sesion_7_Seguridad_.pptx.pdf`
- TF = `tarea_final.pdf` (carpeta 6), la pauta oficial de la tarea final.

| Etapa | Concepto del curso aplicado | Fuente (archivo, lámina) |
|---|---|---|
| 1 — Caso y arquitectura | Agent Contract y criterios success/stop/escalate. Single-agent con router interno. | S1b, láms. 37–40; S2b, láms. 28–30; TF p.1 |
| 2 — Base y trazador | Un solo lector de configuración. Telemetría sin secretos ni datos personales. Traza con latencia y tokens. Ficha de reproducción. | S6, lám. 46; S2a, lám. 15; TF p.3 |
| 3 — LLM con visión | VLM frente a OCR. Salida estructurada con schema. Temperatura baja. Abstenerse en vez de inventar. | S3, láms. 23 y 37; S6, lám. 40; S1b, lám. 31 |
| 4 — Drive | Acción con efecto, mínimo privilegio y recursos de prueba reutilizables. | S6, láms. 7–8 y 37; TF p.4 |
| 5 — Sheets (bono de acción) | Idempotencia: un append duplica filas. Validación estructural antes de escribir. Estado antes y después. | S6, láms. 8 y 40; TF p.2 |
| 6 — ReAct | Micro-loop adaptativo. Controles `max_steps`, `max_retries` y presupuesto. Riesgo de bucle infinito. | S2a, láms. 25–30; S2b, lám. 34; S3, lám. 34; TF p.1 y p.4 |
| 7 — Historial | La API no guarda estado; el historial lo reenvía la aplicación. Segundo turno con el nombre. | S2a, lám. 13; TF p.1 y p.4 |
| 8 — Seguridad basal | Alcance en cada llamada que decide o responde. Prioridad del SYSTEM y su límite. Inyección indirecta en datos de tools. | S7, láms. 8–10; S6, láms. 41–42; TF p.1 |
| 9 — Router | Router como clasificación de intención. Modelo rápido. Rama segura por defecto. | S2b, lám. 5; S3, lám. 30; TF p.2 |
| 10 — Memoria avanzada | Estado estructurado más allá del historial. Higiene de contexto. | S1b, láms. 18 y 32; S2a, lám. 13; TF p.2 |
| 11 — Juez | Criterios de precisión y respaldo. Salida estructurada. La aplicación abre o cierra el paso. Evitar el sesgo de juez y parte. | S6, láms. 26–28 y 36; S7, láms. 13–15; S2b, láms. 18–19 |
| 12 — Golden set | Casos, criterios y comparación. Reglas de código. Repetir los casos anteriores para detectar regresiones. | S6, láms. 22, 24, 32 y 45; TF p.2 |
| 13 — Telegram | No figura en la pauta: es una demo fuera del camino crítico. Aislar la memoria por usuario. | S6, lám. 37 |
| 14 — Notebook final | Se ejecuta desde cero y en orden. Ficha mínima, prompts de desarrollo adjuntos y trazas. | TF p.3–4 |

## Puntos de la pauta que afectan al plan
1. **Tope 3,0.** Se aplica si el flujo central falla en la revisión (TF p.4). Por eso ese flujo no debería depender de credenciales de Google que el revisor quizá no tenga. Queda como decisión pendiente antes de la Etapa 4.
2. **Bonos.** Los declarados suman +3,5 y el tope es +3,0 (TF p.2). El 0,5 extra sirve de margen.
3. **Repetibilidad del bono de acción.** El bono exige que la acción pueda repetirse con seguridad (TF p.2), así que `registrar_gasto` necesita deduplicación.
4. **Alcance en todas las llamadas.** `SECURITY_SCOPE_v1` va en el router, el juez y cualquier otra llamada LLM nueva (TF p.1). El juez no puede duplicar el prompt basal (TF p.2).
