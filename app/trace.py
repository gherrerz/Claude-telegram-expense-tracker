"""Trazador con enmascarado de secretos.

Cada evento se enmascara ANTES de mostrarse en consola y de escribirse en
`traces/<sesión>.jsonl`.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from app.config import secret_values
from app.models import EventType, TraceEvent

MASK = "***"

# Nombres de campo que contienen secretos. Se acotan para no ocultar métricas
# como `prompt_token_count` ni claves de deduplicación como `dedup_key`.
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|passw(or)?d|authorization|credential|private[_-]?key"
    r"|(^|[_-])token$)",
    re.IGNORECASE,
)

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"\b\d{8,10}:[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"Bearer\s+[0-9A-Za-z._~+/=\-]+", re.IGNORECASE),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)",
        re.DOTALL,
    ),
    # Rutas a archivos de credenciales (con separadores de Windows o POSIX).
    re.compile(
        r"[^\s\"',;]*(?:credentials|service[-_]account)[^\s\"',;]*\.json",
        re.IGNORECASE,
    ),
    re.compile(r"[^\s\"',;]*[\\/]secrets[\\/][^\s\"',;]*", re.IGNORECASE),
]


def mask_value(value: Any, extra_secrets: Optional[list[str]] = None) -> Any:
    """Enmascara recursivamente secretos en dicts, listas y cadenas."""
    secrets = sorted(
        {s for s in (extra_secrets or []) + secret_values() if len(s) >= 4},
        key=len,
        reverse=True,
    )
    return _mask(value, secrets)


def _mask_str(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def _mask(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            safe_key = _mask_str(str(key), secrets)
            if _SECRET_KEY_RE.search(str(key)) and isinstance(item, str) and item:
                result[safe_key] = MASK
            else:
                result[safe_key] = _mask(item, secrets)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_mask(item, secrets) for item in value]
    if isinstance(value, str):
        return _mask_str(value, secrets)
    return value


class Tracer:
    """Registra eventos, los muestra en consola y los guarda en JSONL."""

    def __init__(
        self,
        session: Optional[str] = None,
        trace_dir: str | Path = "traces",
        console: bool = True,
        write_file: bool = True,
        extra_secrets: Optional[list[str]] = None,
    ) -> None:
        self.session = session or uuid.uuid4().hex[:8]
        self.trace_dir = Path(trace_dir)
        self.console = console
        self.write_file = write_file
        self.extra_secrets = list(extra_secrets or [])
        self.events: list[TraceEvent] = []
        self._step = 0

    @property
    def path(self) -> Path:
        return self.trace_dir / f"{self.session}.jsonl"

    def record(
        self,
        event_type: EventType | str,
        data: Optional[dict[str, Any]] = None,
        step: Optional[int] = None,
    ) -> TraceEvent:
        """Registra un evento ya enmascarado y lo devuelve."""
        self._step += 1
        safe_data = mask_value(data or {}, self.extra_secrets)
        event = TraceEvent(
            event_type=EventType(event_type),
            data=safe_data,
            session=self.session,
            step=step if step is not None else self._step,
        )
        self.events.append(event)
        if self.console:
            print(self.format_event(event), file=sys.stdout)
        if self.write_file:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
        return event

    @staticmethod
    def format_event(event: TraceEvent) -> str:
        """Formato legible de una línea por evento."""
        payload = json.dumps(event.data, ensure_ascii=False, default=str)
        return (
            f"[{event.timestamp}] #{event.step} "
            f"{event.event_type.value:<14} {payload}"
        )

    def count(self, event_type: EventType | str) -> int:
        """Cantidad de eventos de un tipo (p. ej. TOOL_CALL)."""
        kind = EventType(event_type)
        return sum(1 for e in self.events if e.event_type == kind)
