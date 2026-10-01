"""Modelos Pydantic v2 del agente (solo estructura, sin lógica de LLM)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

UNKNOWN = "desconocido"

ALLOWED_CATEGORIES: tuple[str, ...] = (
    "Alimentación",
    "Supermercado",
    "Transporte",
    "Entretenimiento",
    "Salud",
    "Hogar",
    "Ropa",
    "Otros",
)

MAX_RECENT_EXPENSES = 5


class ReceiptData(BaseModel):
    """Datos extraídos de un recibo. Un dato ilegible vale "desconocido"."""

    fecha: str
    comercio: str
    monto: float | Literal["desconocido"]
    categoria: str
    confianza: float = Field(ge=0.0, le=1.0)

    @field_validator("categoria")
    @classmethod
    def _check_category(cls, value: str) -> str:
        if value != UNKNOWN and value not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"Categoría no permitida; use una de {ALLOWED_CATEGORIES} o '{UNKNOWN}'"
            )
        return value

    @field_validator("monto")
    @classmethod
    def _check_amount(cls, value: float | str) -> float | str:
        if value != UNKNOWN and value < 0:
            raise ValueError("El monto no puede ser negativo")
        return value


class DriveResult(BaseModel):
    """Resultado de guardar un recibo en Google Drive."""

    success: bool
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    web_view_link: Optional[str] = None


class SheetResult(BaseModel):
    """Resultado de agregar una fila en Google Sheets."""

    success: bool
    row_number: Optional[int] = None


class EventType(str, Enum):
    """Tipos de evento de la traza."""

    USER_INPUT = "USER_INPUT"
    ROUTE = "ROUTE"
    LLM_DECISION = "LLM_DECISION"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    JUDGE_VERDICT = "JUDGE_VERDICT"
    MEMORY_UPDATE = "MEMORY_UPDATE"
    RETRY = "RETRY"
    STOP = "STOP"
    FINAL_RESPONSE = "FINAL_RESPONSE"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceEvent(BaseModel):
    """Evento de la traza de ejecución."""

    timestamp: str = Field(default_factory=_utc_now_iso)
    event_type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    session: Optional[str] = None
    step: Optional[int] = None


class AgentState(BaseModel):
    """Estado de memoria del agente (solo estructura)."""

    nombre_usuario: Optional[str] = None
    totales_por_categoria: dict[str, float] = Field(default_factory=dict)
    ultimos_gastos: list[dict[str, Any]] = Field(default_factory=list)
    recibos_registrados: list[str] = Field(default_factory=list)

    @field_validator("ultimos_gastos")
    @classmethod
    def _keep_newest(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # El más reciente va al final; se conservan los últimos N.
        return value[-MAX_RECENT_EXPENSES:]

    def add_expense(self, expense: dict[str, Any]) -> None:
        """Agrega un gasto y conserva solo los 5 más recientes."""
        self.ultimos_gastos = (self.ultimos_gastos + [expense])[-MAX_RECENT_EXPENSES:]
