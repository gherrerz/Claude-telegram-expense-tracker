"""Historial simple de una conversación (Etapa 7).

`Conversation` guarda la lista de mensajes (`google.genai.types.Content`) tal como
se enviaron y se recibieron: turnos del usuario, contenido del modelo SIN modificar
(conserva las firmas de pensamiento de Gemini 3), llamadas a tools y sus
observaciones. `ExpenseAgent.run(..., conversation=...)` reenvía la lista completa
al LLM en cada turno y le agrega lo nuevo al terminar.

Este historial NO extrae ni guarda datos: el nombre del usuario, por ejemplo, solo
viaja dentro de los mensajes reenviados. La memoria estructurada
(`AgentState`) es de la Etapa 10.

Por conversación se lleva además un registro de imágenes (`img_1`, `img_2`, ...)
que asocia cada identificador con su ruta. El LLM nunca recibe bytes, solo el
identificador. Los rieles de las tools (análisis previo, URL de Drive) siguen
acotados a UNA ejecución de `run()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.trace import mask_value

SUMMARY_TEXT_CHARS = 80


@dataclass
class Conversation:
    """Mensajes y metadatos de una conversación entre el usuario y el agente."""

    contents: list[Any] = field(default_factory=list)
    turn: int = 0  # turnos iniciados (llamadas a `run` con esta conversación)
    images: dict[str, Path] = field(default_factory=dict)  # {image_id: ruta}

    def start_turn(self) -> int:
        """Inicia un turno nuevo y devuelve su número (el primero es 1)."""
        self.turn += 1
        return self.turn

    def register_image(self, path: str | Path) -> str:
        """Registra una imagen adjunta y devuelve su identificador (`img_N`)."""
        image_id = f"img_{len(self.images) + 1}"
        self.images[image_id] = Path(path)
        return image_id

    def __len__(self) -> int:
        return len(self.contents)

    def summary(self, max_chars: int = SUMMARY_TEXT_CHARS) -> list[str]:
        """Resumen legible del historial: rol, texto corto y nombres de tools.

        No incluye bytes de imágenes, argumentos ni resultados de las tools, y el
        texto pasa por el enmascarado de secretos del trazador.
        """
        lines: list[str] = []
        for index, content in enumerate(self.contents, start=1):
            pieces: list[str] = []
            for part in getattr(content, "parts", None) or []:
                text = getattr(part, "text", None)
                call = getattr(part, "function_call", None)
                response = getattr(part, "function_response", None)
                if call is not None:
                    pieces.append(f"[llamada a {call.name}]")
                elif response is not None:
                    pieces.append(f"[resultado de {response.name}]")
                elif isinstance(text, str) and text.strip() and not getattr(part, "thought", False):
                    flat = " ".join(mask_value(text).split())
                    pieces.append(flat if len(flat) <= max_chars else flat[: max_chars - 1] + "…")
            role = getattr(content, "role", None) or "?"
            lines.append(f"{index}. {role}: {' '.join(pieces) or '(sin texto)'}")
        return lines
