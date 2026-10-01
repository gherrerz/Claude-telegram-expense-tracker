"""Pruebas de higiene del repositorio (Etapa 1).

Verifican que la documentación obligatoria existe y cubre la rúbrica,
y que no hay secretos versionados.
"""
import re
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "AGENTS.md",
    "README.md",
    ".gitignore",
    ".env.example",
    "docs/use_case.md",
    "docs/architecture.md",
    "docs/bonos.md",
    "docs/mapa_curso.md",
    "docs/dev_prompts.md",
    "docs/prompt_maestro_v2.md",
    "notebooks/demo.ipynb",
]

SECRET_VARS = [
    "GEMINI_API_KEY",
    "GOOGLE_OAUTH_CLIENT_SECRETS",
    "GOOGLE_OAUTH_TOKEN",
    "TELEGRAM_BOT_TOKEN",
]

# Patrones típicos de secretos reales: claves de Google, de OpenRouter/OpenAI,
# tokens de bots de Telegram y claves privadas.
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"sk-(or-)?[0-9A-Za-z]{20,}"),
    re.compile(r"\b\d{8,10}:[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"-----BEGIN (RSA )?PRIVATE KEY-----"),
    # Client secret de OAuth de Google.
    re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}"),
]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", REQUIRED_FILES)
def test_required_file_exists(rel):
    assert (ROOT / rel).is_file(), f"Falta {rel}"


def test_use_case_covers_rubric_sections():
    text = read("docs/use_case.md").lower()
    for section in ["usuario", "entrada", "alcance", "salida esperada",
                    "criterio observable", "por qué hace falta un llm",
                    "por qué hacen falta herramientas"]:
        assert section in text, f"use_case.md no cubre: {section}"


def test_use_case_lists_allowed_categories():
    text = read("docs/use_case.md")
    for cat in ["Alimentación", "Supermercado", "Transporte", "Entretenimiento",
                "Salud", "Hogar", "Ropa", "Otros"]:
        assert cat in text


def test_architecture_diagram_has_key_components():
    text = read("docs/architecture.md")
    assert "```mermaid" in text
    for node in ["Router", "ReAct", "analizar_recibo", "guardar_recibo",
                 "registrar_gasto", "Juez", "AgentState", "Gemini",
                 "Drive", "Sheets"]:
        assert node in text, f"architecture.md no menciona {node}"
    assert "Desarrollo" in text and "Ejecución" in text


def test_bonos_declares_five_bonuses():
    text = read("docs/bonos.md")
    for bono in ["router", "Memoria avanzada", "acción", "Juez", "Golden set"]:
        assert bono.lower() in text.lower()
    assert "Independencia del juez" in text


def test_env_example_has_no_secret_values():
    values = {}
    for line in read(".env.example").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    for var in SECRET_VARS:
        assert var in values, f".env.example no declara {var}"
        assert values[var] == "", f"{var} tiene un valor en .env.example"


def test_gitignore_excludes_secrets():
    text = read(".gitignore")
    assert ".env" in text
    assert "!.env.example" in text
    assert "credentials" in text
    assert "token.json" in text
    assert "client_secret" in text
    assert "secrets/" in text


def test_no_secrets_committed():
    for path in ROOT.rglob("*"):
        # Se omiten el entorno virtual y cachés: no son código del proyecto.
        if not path.is_file() or {".git", ".venv", "__pycache__", ".pytest_cache"} & set(path.parts):
            continue
        # `.env` y `.env.*` (salvo `.env.example`) están en .gitignore: contienen
        # los secretos locales del autor y nunca se versionan ni se leen aquí.
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        # Credenciales OAuth locales (también ignoradas por git): no se leen.
        if path.name == "token.json" or path.name.startswith("client_secret"):
            continue
        if "secrets" in path.relative_to(ROOT).parts[:1]:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            # El mensaje no incluye el contenido, solo la ruta.
            if pattern.search(content):
                pytest.fail(f"Posible secreto en {path.relative_to(ROOT)}", pytrace=False)


def test_notebook_is_valid():
    nb = nbformat.read(ROOT / "notebooks/demo.ipynb", as_version=4)
    nbformat.validate(nb)
    sources = "\n".join(cell.source for cell in nb.cells)
    assert "Sección 1" in sources
