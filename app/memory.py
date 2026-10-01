"""Memoria avanzada (Etapa 10): operaciones sobre `AgentState` con evento `MEMORY_UPDATE`.

`AgentState` es un estado estructurado, distinto del historial bruto (`Conversation`):

| Campo                    | Quién lo actualiza (código, nunca el LLM)                      |
|--------------------------|----------------------------------------------------------------|
| `nombre_usuario`         | `set_user_name`, desde la salida estructurada de CONVERSACION   |
| `totales_por_categoria`  | `record_expense`, tras una escritura confirmada en la planilla  |
| `ultimos_gastos`         | `record_expense` (5 más recientes; el más reciente va al final) |
| `recibos_registrados`    | `record_expense` (huella de cada recibo registrado)             |
| `confirmacion_pendiente` | `set_pending_confirmation` / `clear_pending_confirmation`       |

Dos usos posteriores del estado (los que acredita el bono):
1. Responder "¿cuánto llevo en Supermercado?" con cifras calculadas por el código.
2. Detectar un recibo repetido (`is_duplicate`) y exigir confirmación antes de registrarlo
   de nuevo.

Cada operación que cambia el estado registra un evento `MEMORY_UPDATE` con
`{operacion, antes, despues, motivo}`; `antes` y `despues` son el subconjunto relevante
del estado, nunca bytes de imágenes ni rutas. El estado vive en memoria: no hay persistencia
en disco (documentado como límite de la Etapa 10).

Huella del recibo (`receipt_key`): `<sha256 de los bytes de la imagen>-<resumen de los campos>`.
El resumen sale de comercio (minúsculas, espacios colapsados), fecha y monto normalizado.
Un recibo cuenta como repetido si la huella es idéntica O si la imagen es la misma
(mismo hash), aunque el LLM haya leído algún campo distinto: así la detección no depende
de que la extracción sea determinista. Otra FOTO del mismo recibo (otro hash) con los mismos
campos la sigue frenando la deduplicación de la planilla (Etapa 5), que es otro mecanismo.
"""
from __future__ import annotations

import hashlib
from typing import Any, Literal, Optional

from app.models import (
    UNKNOWN,
    AgentState,
    EventType,
    PendingConfirmation,
    ReceiptData,
)
from app.trace import Tracer

NO_IMAGE_HASH = "sin-imagen"
MAX_NAME_CHARS = 40

ConfirmationKind = Literal["duplicado", "baja_confianza"]


# -- Huellas ---------------------------------------------------------------------------
def image_hash(image_bytes: bytes) -> str:
    """SHA-256 (hex) de los bytes de la imagen."""
    return hashlib.sha256(image_bytes).hexdigest()


def _normalize_amount(monto: object) -> str:
    if isinstance(monto, (int, float)) and not isinstance(monto, bool):
        return f"{float(monto):.2f}"
    return UNKNOWN


def build_key(img_hash: Optional[str], comercio: object, fecha: object, monto: object) -> str:
    """Huella a partir de un hash de imagen ya calculado y los campos del recibo."""
    fields = "|".join(
        [
            " ".join(str(comercio).split()).casefold(),
            str(fecha).strip(),
            _normalize_amount(monto),
        ]
    )
    digest = hashlib.sha256(fields.encode("utf-8")).hexdigest()[:16]
    return f"{img_hash or NO_IMAGE_HASH}-{digest}"


def receipt_key(image_bytes: bytes, comercio: object, fecha: object, monto: object) -> str:
    """Huella del recibo: hash de la imagen + campos normalizados (ver el docstring del módulo)."""
    return build_key(image_hash(image_bytes), comercio, fecha, monto)


def _image_part(key: str) -> str:
    return key.rsplit("-", 1)[0]


def same_receipt(key_a: str, key_b: str) -> bool:
    """`True` si dos huellas son idénticas o tienen la misma imagen (hash conocido)."""
    if key_a == key_b:
        return True
    part = _image_part(key_a)
    return part != NO_IMAGE_HASH and part == _image_part(key_b)


def is_duplicate(state: AgentState, key: str) -> bool:
    """`True` si ya se registró esta huella o una con la misma imagen."""
    return existing_row_key(state, key) is not None


def existing_row_key(state: AgentState, key: str) -> Optional[str]:
    """Huella ya registrada que coincide con `key` (idéntica o de la misma imagen), o `None`."""
    return next((k for k in state.recibos_registrados if same_receipt(k, key)), None)


def existing_row(state: AgentState, key: str) -> Optional[int]:
    """Fila de la planilla del primer registro de este recibo, si se conoce."""
    match = existing_row_key(state, key)
    return state.filas_por_recibo.get(match) if match is not None else None


# -- Vistas del estado -----------------------------------------------------------------
def total_general(state: AgentState) -> float:
    """Suma de los totales por categoría (calculada por código)."""
    return round(sum(state.totales_por_categoria.values()), 2)


def _short(key: str) -> str:
    return key[:10] + "…" if len(key) > 10 else key


def _pending_view(pending: Optional[PendingConfirmation]) -> Optional[dict[str, Any]]:
    if pending is None:
        return None
    return {
        "tipo": pending.tipo,
        "turno": pending.turno,
        "clave": _short(pending.clave),
        "fila_existente": pending.fila_existente,
        "comercio": pending.datos.get("comercio"),
        "monto": pending.datos.get("monto"),
    }


def state_snapshot(state: AgentState) -> dict[str, Any]:
    """Vista legible del estado para el notebook y los scripts (sin bytes ni rutas)."""
    return {
        "nombre_usuario": state.nombre_usuario,
        "totales_por_categoria": dict(state.totales_por_categoria),
        "total_general": total_general(state),
        "ultimos_gastos": [dict(g) for g in state.ultimos_gastos],
        "recibos_registrados": [_short(k) for k in state.recibos_registrados],
        "confirmacion_pendiente": _pending_view(state.confirmacion_pendiente),
    }


def _emit(
    tracer: Optional[Tracer],
    operacion: str,
    antes: dict[str, Any],
    despues: dict[str, Any],
    motivo: str,
) -> None:
    if tracer is not None:
        tracer.record(
            EventType.MEMORY_UPDATE,
            {"operacion": operacion, "antes": antes, "despues": despues, "motivo": motivo},
        )


# -- Operaciones -----------------------------------------------------------------------
def record_expense(
    state: AgentState,
    receipt: ReceiptData,
    img_hash: Optional[str],
    row_number: int,
    tracer: Optional[Tracer] = None,
    motivo: str = "gasto registrado en la planilla",
) -> str:
    """Suma un gasto confirmado por la planilla a los totales y a los últimos gastos.

    Debe llamarse solo tras una escritura exitosa (`success=True`, no duplicada). Devuelve la
    huella del recibo. Si la huella ya estaba (registro confirmado de un duplicado) los totales
    y los últimos gastos sí suman el gasto, pero `recibos_registrados` no repite la huella y
    `filas_por_recibo` conserva la fila del primer registro.

    Raises:
        ValueError: si el monto o la categoría no son válidos (la planilla ya los validó).
    """
    if not isinstance(receipt.monto, (int, float)) or isinstance(receipt.monto, bool):
        raise ValueError("El monto debe ser numérico para registrarlo en la memoria.")
    if receipt.categoria == UNKNOWN:
        raise ValueError("La categoría debe estar definida para registrarla en la memoria.")
    amount = float(receipt.monto)
    category = receipt.categoria
    key = build_key(img_hash, receipt.comercio, receipt.fecha, amount)

    antes = {
        "categoria": category,
        "total_categoria": state.totales_por_categoria.get(category, 0.0),
        "n_ultimos_gastos": len(state.ultimos_gastos),
        "n_recibos_registrados": len(state.recibos_registrados),
    }
    state.totales_por_categoria[category] = round(
        state.totales_por_categoria.get(category, 0.0) + amount, 2
    )
    expense = {
        "fecha": receipt.fecha,
        "comercio": receipt.comercio,
        "monto": amount,
        "categoria": category,
        "fila": row_number,
    }
    state.add_expense(expense)
    if key not in state.recibos_registrados:
        state.recibos_registrados.append(key)
    state.filas_por_recibo.setdefault(key, row_number)
    despues = {
        "categoria": category,
        "total_categoria": state.totales_por_categoria[category],
        "n_ultimos_gastos": len(state.ultimos_gastos),
        "n_recibos_registrados": len(state.recibos_registrados),
        "ultimo_gasto": expense,
    }
    _emit(tracer, "record_expense", antes, despues, motivo)
    return key


def valid_user_name(name: object, source_text: str) -> Optional[str]:
    """Nombre limpio si es plausible y aparece en el mensaje del usuario; si no, `None`.

    El nombre lo propone el LLM en la salida estructurada de CONVERSACION, pero el código solo
    lo acepta si son letras (con espacios, apóstrofes, guiones o puntos), cabe en
    `MAX_NAME_CHARS` y está literalmente en el texto del usuario: un nombre inventado o
    deducido de otra parte no entra al estado.
    """
    if not isinstance(name, str):
        return None
    clean = " ".join(name.split())
    if not clean or len(clean) > MAX_NAME_CHARS or not clean[0].isalpha():
        return None
    if any(not (c.isalpha() or c in " '.-") for c in clean):
        return None
    return clean if clean.casefold() in source_text.casefold() else None


def set_user_name(
    state: AgentState,
    name: str,
    tracer: Optional[Tracer] = None,
    motivo: str = "el usuario dio su nombre en la ruta CONVERSACION",
) -> bool:
    """Guarda el nombre (limpio y acotado). Devuelve `False` si no cambia nada."""
    clean = " ".join(str(name).split())[:MAX_NAME_CHARS]
    if not clean or clean == state.nombre_usuario:
        return False
    antes = {"nombre_usuario": state.nombre_usuario}
    state.nombre_usuario = clean
    _emit(tracer, "set_user_name", antes, {"nombre_usuario": clean}, motivo)
    return True


def set_pending_confirmation(
    state: AgentState,
    kind: ConfirmationKind,
    key: str,
    datos: dict[str, Any],
    turn: int,
    *,
    imagen: Optional[str] = None,
    imagen_id: Optional[str] = None,
    imagen_hash: Optional[str] = None,
    fila_existente: Optional[int] = None,
    tracer: Optional[Tracer] = None,
    motivo: Optional[str] = None,
) -> PendingConfirmation:
    """Deja una confirmación pendiente para el recibo `key`, creada en el turno `turn`.

    Si ya hay una pendiente del mismo tipo y la misma huella, se conserva tal cual (con su
    turno original): reanalizar el recibo en el turno de confirmación no la rejuvenece.
    """
    current = state.confirmacion_pendiente
    if current is not None and current.tipo == kind and same_receipt(current.clave, key):
        return current
    pending = PendingConfirmation(
        tipo=kind,
        clave=key,
        imagen_hash=imagen_hash,
        datos=dict(datos),
        turno=turn,
        fila_existente=fila_existente,
        imagen_id=imagen_id,
        imagen=imagen,
    )
    antes = {"confirmacion_pendiente": _pending_view(current)}
    state.confirmacion_pendiente = pending
    _emit(
        tracer,
        "set_pending_confirmation",
        antes,
        {"confirmacion_pendiente": _pending_view(pending)},
        motivo or f"se pidió confirmación al usuario ({kind})",
    )
    return pending


def clear_pending_confirmation(
    state: AgentState, tracer: Optional[Tracer] = None, motivo: str = "confirmación resuelta"
) -> bool:
    """Borra la confirmación pendiente. Devuelve `False` si no había ninguna."""
    current = state.confirmacion_pendiente
    if current is None:
        return False
    state.confirmacion_pendiente = None
    _emit(
        tracer,
        "clear_pending_confirmation",
        {"confirmacion_pendiente": _pending_view(current)},
        {"confirmacion_pendiente": None},
        motivo,
    )
    return True
