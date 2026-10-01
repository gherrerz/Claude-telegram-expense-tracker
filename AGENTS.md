# AGENTS.md — Reglas para agentes de código en este repositorio

Este archivo resume las reglas que debe seguir cualquier agente de desarrollo (Claude, OpenCode u otro) que modifique el proyecto. La especificación completa está en `docs/prompt_maestro_v2.md`.

## Qué es el proyecto
Agente académico "Telegram Expense Tracker": foto de recibo → LLM con visión → Google Drive + Google Sheets → confirmación. La entrega evaluada es `notebooks/demo.ipynb`; Telegram es una demo aparte.

## Forma de trabajo
- El desarrollo avanza en 14 etapas. Implementa solo la etapa en curso y no avances sin confirmación explícita del usuario.
- Cada etapa termina con pruebas ejecutadas, la sección del notebook actualizada, una entrada en `docs/dev_prompts.md` y el reporte de cierre.
- Si un fallo afecta una etapa anterior, corrígelo primero y repite sus pruebas.

## Stack permitido
Python 3.12, el SDK oficial de Gemini y las APIs de Google Drive y Sheets. Para la demo, una librería de Telegram. No agregues AWS, Docker, bases de datos, frontend, OCR externo, Redis, microservicios, OpenRouter ni otros proveedores de LLM en el código del agente.

## Seguridad
- Credenciales solo por variables de entorno (ver `.env.example`). Nunca en código, notebook, trazas ni git.
- Todas las llamadas al LLM incluyen el bloque de alcance vigente, `SECURITY_SCOPE_v2` (la v1 se conserva por trazabilidad; ver A13 en `docs/dev_prompts.md`).
- El agente nunca transfiere, paga, borra, modifica cuentas ni ejecuta herramientas ante peticiones fuera de alcance.
- `data/` contiene solo recibos sintéticos o anonimizados.
- Drive y Sheets: solo una carpeta y una planilla de prueba; Sheets solo admite agregar filas.

## Veracidad
- No inventes datos de recibos, URLs, números de fila, IDs de modelo, límites de uso ni resultados de pruebas.
- Marca los supuestos con **[SUPUESTO]**.
- Una etapa sin verificación real no es COMPLETADA. Usa BLOQUEADA o IMPLEMENTADA — VERIFICACIÓN REAL PENDIENTE.

## Convenciones
- Código y nombres de archivo en inglés, excepto las tools `analizar_recibo`, `guardar_recibo` y `registrar_gasto`.
- Docstrings y documentación en español.
- Prompts del sistema solo en `app/prompts.py`, versionados (`NOMBRE_PROMPT_vN`).
- Categorías permitidas: Alimentación, Supermercado, Transporte, Entretenimiento, Salud, Hogar, Ropa y Otros.
