# Telegram Expense Tracker

Agente de IA que recibe la foto de un recibo, extrae fecha, comercio y monto con un LLM con visión, categoriza el gasto, guarda la imagen en Google Drive y registra el gasto en Google Sheets con el enlace al recibo.

Proyecto académico: tarea final del curso de agentes de IA. La entrega evaluada es el notebook `notebooks/demo.ipynb`, ejecutable de principio a fin sin costo para el revisor.

> **Estado:** en desarrollo por etapas. Etapa 1 (caso, criterio de éxito y arquitectura) entregada. La instalación base está descrita en la sección «Instalación».

## Ejemplo de resultado

| Fecha | Comercio | Monto | Categoría | Recibo_URL |
|---|---|---|---|---|
| 30/09/2026 | Jumbo | 32490 | Supermercado | enlace devuelto por la API de Drive |

## Documentación
- [Caso de uso y criterio de éxito](docs/use_case.md)
- [Arquitectura](docs/architecture.md)
- [Ampliaciones declaradas (bonos)](docs/bonos.md)
- [Mapa frente a la materia del curso](docs/mapa_curso.md)
- [Prompts de desarrollo y bitácora por etapa](docs/dev_prompts.md)
- [Prompt maestro de desarrollo](docs/prompt_maestro_v2.md)
- [Reglas para agentes de código](AGENTS.md)

## Avance por etapas

| # | Etapa | Estado |
|---|---|---|
| 1 | Caso, criterio de éxito y arquitectura | Entregada |
| 2 | Proyecto Python base y trazador | Implementada (pendiente de cierre) |
| 3 | LLM con visión y `analizar_recibo` | Pendiente |
| 4 | `guardar_recibo` (Drive) | Pendiente |
| 5 | `registrar_gasto` (Sheets) | Pendiente |
| 6 | Loop ReAct | Pendiente |
| 7 | Historial simple | Pendiente |
| 8 | Seguridad basal | Pendiente |
| 9 | Router | Pendiente |
| 10 | Memoria avanzada | Pendiente |
| 11 | Juez LLM | Pendiente |
| 12 | Golden set | Pendiente |
| 13 | Demo Telegram | Pendiente |
| 14 | Notebook final y entrega | Pendiente |

## Instalación
En Windows (PowerShell), desde la raíz del repositorio:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
```

Copia `.env.example` a `.env` y completa los valores. Las pruebas y el notebook de la Etapa 2 funcionan sin `.env` y sin red.

## Requisitos (previstos)
- Python 3.12.
- Cuenta Google con una clave gratuita de Google AI Studio y una cuenta de servicio de Google Cloud con acceso a una carpeta de Drive y una planilla de prueba.
- Opcional, solo para la demo: un bot de Telegram.

Las variables de entorno están descritas en [.env.example](.env.example).
