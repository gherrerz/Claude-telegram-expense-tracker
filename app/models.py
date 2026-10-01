"""Modelos Pydantic v2 del agente (solo estructura, sin lógica de LLM)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

UNKNOWN = "desconocido"

# Confianza mínima de una extracción para registrarla sin pedir confirmación.
CONFIDENCE_THRESHOLD = 0.7

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
    error: Optional[str] = None  # mensaje seguro (sin rutas ni tokens) si success es False


class SheetResult(BaseModel):
    """Resultado de agregar una fila en Google Sheets."""

    success: bool
    row_number: Optional[int] = None
    duplicate: bool = False  # True si la fila ya existía; en ese caso no se escribió nada
    error: Optional[str] = None  # mensaje seguro (sin rutas ni tokens) si success es False


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


class PendingConfirmation(BaseModel):
    """Confirmación que el código le pide al usuario antes de registrar un recibo (Etapa 10).

    Se crea cuando un riel bloquea el registro (recibo duplicado o extracción poco fiable) y
    solo se acepta en un turno POSTERIOR al que la creó. La ruta de la imagen se conserva
    para poder confirmar con texto solamente, pero no se serializa (ni hacia el LLM ni hacia
    la traza).
    """

    tipo: Literal["duplicado", "baja_confianza", "juez"]
    clave: str  # huella del recibo (hash de la imagen + campos normalizados)
    imagen_hash: Optional[str] = None
    datos: dict[str, Any] = Field(default_factory=dict)  # `ReceiptData` analizado, como dict
    turno: int  # `Conversation.turn` en que se pidió la confirmación
    fila_existente: Optional[int] = None  # solo para "duplicado", si se conoce
    imagen_id: Optional[str] = None
    imagen: Optional[str] = Field(default=None, exclude=True)  # ruta local; nunca sale del código
    # Etapa 11: veredicto del juez para este recibo (`JudgeVerdict` como dict); vacío si no se conoce.
    juicio: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    """Estado de memoria del agente, distinto del historial bruto de mensajes.

    Lo actualiza el código a partir de resultados observados (ver `app/memory.py`), no lo
    que diga el LLM. Vive en memoria, una instancia por conversación (sin persistencia).
    """

    nombre_usuario: Optional[str] = None
    totales_por_categoria: dict[str, float] = Field(default_factory=dict)
    ultimos_gastos: list[dict[str, Any]] = Field(default_factory=list)
    recibos_registrados: list[str] = Field(default_factory=list)
    # Etapa 10: fila de la planilla del primer registro de cada huella, y confirmación pendiente.
    filas_por_recibo: dict[str, int] = Field(default_factory=dict)
    confirmacion_pendiente: Optional[PendingConfirmation] = None
    # Etapa 11: huellas de los recibos que el juez rechazó; el bloqueo es definitivo para cada una.
    recibos_rechazados: list[str] = Field(default_factory=list)

    @field_validator("ultimos_gastos")
    @classmethod
    def _keep_newest(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # El más reciente va al final; se conservan los últimos N.
        return value[-MAX_RECENT_EXPENSES:]

    def add_expense(self, expense: dict[str, Any]) -> None:
        """Agrega un gasto y conserva solo los 5 más recientes."""
        self.ultimos_gastos = (self.ultimos_gastos + [expense])[-MAX_RECENT_EXPENSES:]
