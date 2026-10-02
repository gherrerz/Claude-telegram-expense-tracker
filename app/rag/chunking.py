"""Fragmentación de documentos Markdown (Etapa 15).

Dos pasos:
1. Se divide el documento por encabezados (`#`, `##`, `###`). Cada sección conserva su ruta de
   encabezados (por ejemplo `Política de rendición / 3. Límites por categoría`), que se guarda como
   `seccion` y sirve de cita.
2. Si el cuerpo de una sección supera `CHUNK_SIZE` caracteres, se parte en ventanas con solape de
   `CHUNK_OVERLAP`, cortando de preferencia en un salto de párrafo, de línea o fin de frase.

Parámetros (en caracteres): `CHUNK_SIZE = 500` y `CHUNK_OVERLAP = 100`. El taller del curso usa 500 y
150 para PDF sin estructura; aquí la división por secciones ya aísla cada tema, así que el solape solo
cubre las secciones largas y 100 (20 %) basta para no cortar una regla por la mitad sin duplicar de
más. Son constantes del código y entran en la firma del corpus: cambiarlas fuerza a reindexar.

Cada fragmento lleva un `chunk_id` estable: hash del archivo, la sección, la posición y el texto, con
saltos de línea normalizados; el mismo corpus produce los mismos identificadores en cualquier equipo.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
_BREAKS = ("\n\n", "\n", ". ", " ")
SECTION_SEPARATOR = " / "


@dataclass(frozen=True)
class Chunk:
    """Fragmento del corpus listo para indexar."""

    chunk_id: str
    fuente: str  # nombre del archivo, por ejemplo `politica_rendicion_gastos_v2.md`
    seccion: str  # ruta de encabezados, por ejemplo `Título / 3. Límites`
    texto: str


def normalize_text(text: str) -> str:
    """Normaliza saltos de línea (`\\r\\n` y `\\r` pasan a `\\n`) para que los hashes sean estables."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _sections(text: str, fallback_title: str) -> list[tuple[str, str]]:
    """`[(ruta_de_encabezados, cuerpo)]` en orden; ignora las secciones sin cuerpo."""
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = []
    current: list[str] = []
    path = fallback_title

    def flush() -> None:
        if any(line.strip() for line in current):
            sections.append((path, list(current)))

    for line in normalize_text(text).split("\n"):
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level, title = len(match.group(1)), match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = SECTION_SEPARATOR.join(t for _, t in stack)
            current = []
        else:
            current.append(line)
    flush()
    return [(p, "\n".join(lines).strip()) for p, lines in sections]


def split_with_overlap(body: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Parte `body` en ventanas de hasta `size` caracteres con `overlap` de solape.

    Corta de preferencia en un salto de párrafo, de línea, fin de frase o espacio, dentro de la mitad
    final de la ventana; el siguiente fragmento arranca `overlap` caracteres antes del corte, en el
    siguiente límite de palabra. Garantiza progreso en cada vuelta.
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Se requiere size > 0 y 0 <= overlap < size")
    body = body.strip()
    if len(body) <= size:
        return [body] if body else []
    pieces: list[str] = []
    start = 0
    while start < len(body):
        end = min(start + size, len(body))
        if end < len(body):
            floor = start + size // 2
            for token in _BREAKS:
                cut = body.rfind(token, floor, end)
                if cut != -1:
                    end = cut + len(token)
                    break
        piece = body[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(body):
            break
        next_start = max(end - overlap, start + 1)
        # Evita arrancar a mitad de palabra: avanza al siguiente espacio o salto de línea.
        boundary = next_start
        while boundary < end and not body[boundary - 1].isspace():
            boundary += 1
        start = boundary if boundary < end else next_start
    return pieces


def chunk_id_for(fuente: str, seccion: str, index: int, texto: str) -> str:
    """Identificador estable (16 hex de SHA-1) del fragmento."""
    raw = f"{fuente}\x1f{seccion}\x1f{index}\x1f{texto}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def chunk_markdown(
    text: str, fuente: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    """Fragmenta un documento Markdown en `Chunk` con fuente, sección e identificador estables."""
    chunks: list[Chunk] = []
    for path, body in _sections(text, fallback_title=fuente):
        for index, piece in enumerate(split_with_overlap(body, size, overlap)):
            chunks.append(Chunk(chunk_id_for(fuente, path, index, piece), fuente, path, piece))
    return chunks


def chunk_documents(
    documents: dict[str, str], size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    """Fragmenta varios documentos `{nombre_de_archivo: texto}` en orden alfabético del nombre."""
    chunks: list[Chunk] = []
    for name in sorted(documents):
        chunks.extend(chunk_markdown(documents[name], name, size, overlap))
    return chunks
