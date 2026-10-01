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
| 3 | LLM con visión y `analizar_recibo` | Implementada — verificación real pendiente |
| 4 | `guardar_recibo` (Drive) | Implementada — verificación real pendiente |
| 5 | `registrar_gasto` (Sheets) | Implementada — verificación real pendiente |
| 6 | Loop ReAct | Completada |
| 7 | Historial simple | Completada |
| 8 | Seguridad basal | Completada |
| 9 | Router | Completada |
| 10 | Memoria avanzada | Completada |
| 11 | Juez LLM | Completada |
| 12 | Golden set | Implementada — corrida real pendiente |
| 13 | Demo Telegram | Pendiente |
| 14 | Notebook final y entrega | Pendiente |

## Instalación
En Windows (PowerShell), desde la raíz del repositorio:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
```

Copia `.env.example` a `.env` y completa los valores (`LLM_MODEL=gemini-3.5-flash-lite`). Las pruebas offline y el notebook funcionan sin `.env` y sin red: las llamadas reales se omiten con un aviso.

### Cómo ejecutar (Etapa 3)

```powershell
# Pruebas offline (las marcadas `live` se omiten si faltan GEMINI_API_KEY o LLM_MODEL)
.venv\Scripts\python -m pytest -q

# Pruebas en vivo contra la API real (consumen llamadas de la capa gratuita)
.venv\Scripts\python -m pytest -m live -v

# Verificación real: humo de texto, visión y temperatura 0.0 frente a 1.0
.venv\Scripts\python scripts\verify_stage_3.py

# Regenerar los recibos sintéticos de data/receipts/
.venv\Scripts\python scripts\generate_receipts.py
```

Con `.env` completo, `pytest -q` también ejecuta las pruebas `live`; para evitarlo usa `pytest -m "not live"`.

### Cómo ejecutar (Etapa 4)

```powershell
# Una vez: consentimiento OAuth en el navegador y creación de la carpeta de prueba
.venv\Scripts\python scripts\google_auth.py
.venv\Scripts\python scripts\setup_google_resources.py

# Verificación real: sube un recibo y confirma el file_id con files.get
.venv\Scripts\python scripts\verify_stage_4.py
```

## Requisitos (previstos)
- Python 3.12.
- Cuenta Google con una clave gratuita de Google AI Studio y un proyecto de Google Cloud con un cliente OAuth de escritorio (OAuth de usuario, scope `drive.file`) para usar una carpeta de Drive y una planilla de prueba. Pasos en [docs/setup_google.md](docs/setup_google.md).
- Opcional, solo para la demo: un bot de Telegram.

Las variables de entorno están descritas en [.env.example](.env.example).
