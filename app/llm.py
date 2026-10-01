"""Cliente LLM único (SDK oficial `google-genai`).

Responsabilidades:
- Crear el cliente de Gemini de forma perezosa desde la configuración (grupo "llm").
- Pausa mínima entre llamadas y reintentos con espera exponencial ante 429 /
  RESOURCE_EXHAUSTED (y 503 / UNAVAILABLE), cada reintento como evento `RETRY`.
- Contadores por sesión (llamadas, reintentos, tokens).
- Traza de cada llamada como `LLM_DECISION` con modelo exacto, parámetros,
  identificadores de prompt, uso de tokens y latencia.

Nunca registra la clave de API, el texto de los prompts ni los bytes de las imágenes.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.config import Settings, load_settings
from app.models import EventType
from app.prompts import SECURITY_SCOPE_ID, compose_system_instruction
from app.trace import Tracer

# Temperatura para extracción: 0.0 según el prompt maestro. Google recomienda
# 1.0 en Gemini 3 (bajarla puede causar bucles), pero la verificación real del
# 2026-09-30 (scripts/verify_stage_3.py) mostró que gemini-3.5-flash-lite acepta
# 0.0 y extrae igual que con 1.0 en los 3 recibos, sin bucles ni reintentos.
EXTRACTION_TEMPERATURE = 0.0

# Temperatura de la decisión del agente (qué tool llamar o cuándo responder).
# Se elige 0.0 por determinismo, con la misma evidencia de la Etapa 3 (el modelo
# acepta 0.0 sin bucles en extracción). Google advierte que en Gemini 3 bajar de
# 1.0 puede degradar el razonamiento o producir bucles; aquí el riesgo está
# acotado por `MAX_STEPS` (app/agent.py). El comportamiento del loop con 0.0
# se confirma SOLO en la ejecución real (scripts/verify_stage_6.py); si
# apareciera un bucle, volver a 1.0 cambiando esta constante.
AGENT_TEMPERATURE = 0.0

RETRYABLE_CODES = frozenset({429, 503})
RETRYABLE_STATUSES = frozenset({"RESOURCE_EXHAUSTED", "UNAVAILABLE"})
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0


class LLMCallError(Exception):
    """Falla de una llamada al LLM. El mensaje solo incluye código y estado."""

    def __init__(self, code: Optional[int], status: Optional[str], attempts: int) -> None:
        self.code = code
        self.status = status
        self.attempts = attempts
        super().__init__(
            f"Falló la llamada al LLM (código={code}, estado={status}, intentos={attempts})"
        )


@dataclass
class UsageStats:
    """Contadores acumulados de la sesión."""

    calls: int = 0
    failed_calls: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class ToolCallRequest:
    """Llamada a función pedida por el modelo."""

    name: str
    args: dict[str, Any]
    id: Optional[str] = None


@dataclass
class ToolLLMResult:
    """Decisión del modelo con tools: llamadas a función o texto final.

    `content` es el `Content` del candidato SIN modificar: se reenvía tal cual
    en el historial para conservar las firmas de pensamiento (Gemini 3).
    """

    text: Optional[str]
    function_calls: list[ToolCallRequest] = field(default_factory=list)
    content: Any = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 1
    model: str = ""


@dataclass
class LLMResult:
    """Resultado de una llamada: texto, JSON (si aplica) y metadatos."""

    text: Optional[str]
    data: Any = None
    json_error: Optional[str] = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 1
    model: str = ""


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def extract_usage(response: Any) -> dict[str, int]:
    """Lee `response.usage_metadata` con los nombres reales del SDK."""
    meta = getattr(response, "usage_metadata", None)
    return {
        "prompt_token_count": _int(getattr(meta, "prompt_token_count", 0)),
        "candidates_token_count": _int(getattr(meta, "candidates_token_count", 0)),
        "thoughts_token_count": _int(getattr(meta, "thoughts_token_count", 0)),
        "total_token_count": _int(getattr(meta, "total_token_count", 0)),
    }


class LLMClient:
    """Cliente único del LLM con control de límites y trazabilidad."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        tracer: Optional[Tracer] = None,
        client: Any = None,
        model: Optional[str] = None,
        min_seconds_between_calls: Optional[float] = None,
        max_retries: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        backoff_base: float = BACKOFF_BASE_SECONDS,
        backoff_max: float = BACKOFF_MAX_SECONDS,
    ) -> None:
        """Crea el cliente sin tocar la red ni exigir la clave todavía.

        Args:
            settings: configuración ya cargada; si se omite se carga al primer uso.
            tracer: trazador; por defecto uno en memoria (sin consola ni archivo).
            client: objeto con `.models.generate_content(...)` (cliente falso en
                pruebas). Si se omite se crea `genai.Client` al primer uso.
            model: ID del modelo; si se omite se lee de `LLM_MODEL`.
            clock, sleep: relojes inyectables para pruebas.
        """
        self.tracer = tracer if tracer is not None else Tracer(console=False, write_file=False)
        self.stats = UsageStats()
        self._settings = settings
        self._client = client
        self._model = model
        self._min_seconds = min_seconds_between_calls
        self._max_retries = max_retries
        self._clock = clock
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._last_attempt_at: Optional[float] = None
        self._call_seq = 0

    # -- configuración perezosa ------------------------------------------------
    def _load(self) -> Settings:
        if self._settings is None:
            self._settings = load_settings(required=["llm"])
        return self._settings

    @property
    def model(self) -> str:
        if self._model is None:
            self._model = self._load().llm_model
        assert self._model
        return self._model

    @property
    def min_seconds(self) -> float:
        if self._min_seconds is None:
            self._min_seconds = self._load().llm_min_seconds_between_calls
        return self._min_seconds

    @property
    def max_retries(self) -> int:
        if self._max_retries is None:
            self._max_retries = self._load().llm_max_retries
        return self._max_retries

    def _sdk(self) -> Any:
        if self._client is None:
            from google import genai  # import perezoso: solo si se usa el LLM real

            self._client = genai.Client(api_key=self._load().gemini_api_key)
        return self._client

    # -- control de límites ----------------------------------------------------
    def _throttle(self) -> None:
        if self._last_attempt_at is not None:
            wait = self.min_seconds - (self._clock() - self._last_attempt_at)
            if wait > 0:
                self._sleep(wait)
        self._last_attempt_at = self._clock()

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        code = getattr(error, "code", None)
        status = getattr(error, "status", None)
        return code in RETRYABLE_CODES or status in RETRYABLE_STATUSES

    def _backoff(self, retry_number: int) -> float:
        return min(self._backoff_base * (2 ** (retry_number - 1)), self._backoff_max)

    # -- llamada común ---------------------------------------------------------
    def _generate(
        self,
        kind: str,
        contents: Any,
        system_prompt_id: str,
        temperature: float,
        thinking_level: Optional[str] = None,
        schema: Optional[dict[str, Any]] = None,
        schema_name: Optional[str] = None,
        tools: Optional[list[Any]] = None,
        decision_fn: Optional[Callable[[Any], dict[str, Any]]] = None,
    ) -> Any:
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "system_instruction": compose_system_instruction(system_prompt_id),
            "temperature": temperature,
            # El ciclo ReAct ejecuta las tools de forma explícita; el SDK nunca
            # debe llamarlas por su cuenta.
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if thinking_level is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
        if schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_json_schema"] = schema
        tool_names: Optional[list[str]] = None
        if tools:
            config_kwargs["tools"] = tools
            # AUTO: el modelo decide entre llamar a una función o responder.
            config_kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO
                )
            )
            tool_names = [
                d.name for tool in tools for d in (tool.function_declarations or [])
            ]
        config = types.GenerateContentConfig(**config_kwargs)

        self._call_seq += 1
        call_id = self._call_seq
        self.stats.calls += 1
        started = self._clock()
        attempts = 0
        while True:
            attempts += 1
            self._throttle()
            try:
                response = self._sdk().models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                break
            except Exception as error:  # noqa: BLE001 - se reclasifica abajo
                code = getattr(error, "code", None)
                status = getattr(error, "status", None)
                retries_done = attempts - 1
                if self._is_retryable(error) and retries_done < self.max_retries:
                    wait = self._backoff(retries_done + 1)
                    self.stats.retries += 1
                    self.tracer.record(
                        EventType.RETRY,
                        {
                            "call_id": call_id,
                            "model": self.model,
                            "attempt": retries_done + 1,
                            "max_retries": self.max_retries,
                            "wait_seconds": wait,
                            "error_code": code,
                            "error_status": status,
                        },
                    )
                    self._sleep(wait)
                    continue
                self.stats.failed_calls += 1
                self.tracer.record(
                    EventType.LLM_DECISION,
                    {
                        "call_id": call_id,
                        "kind": kind,
                        "model": self.model,
                        "status": "error",
                        "error_code": code,
                        "error_status": status,
                        "attempts": attempts,
                        "system_prompt_id": system_prompt_id,
                    },
                )
                raise LLMCallError(code, status, attempts) from error

        latency_ms = int(round((self._clock() - started) * 1000))
        usage = extract_usage(response)
        self.stats.prompt_tokens += usage["prompt_token_count"]
        self.stats.output_tokens += usage["candidates_token_count"]
        self.stats.thinking_tokens += usage["thoughts_token_count"]
        self.stats.total_tokens += usage["total_token_count"]
        self.tracer.record(
            EventType.LLM_DECISION,
            {
                "call_id": call_id,
                "kind": kind,
                "model": self.model,
                "status": "ok",
                "system_prompt_id": system_prompt_id,
                "security_scope_id": SECURITY_SCOPE_ID,
                "params": {
                    "temperature": temperature,
                    "thinking_level": thinking_level,
                    "response_mime_type": "application/json" if schema is not None else None,
                    "response_schema": schema_name,
                    **({"tools": tool_names, "function_calling_mode": "AUTO"} if tool_names else {}),
                },
                **({"decision": decision_fn(response)} if decision_fn else {}),
                "usage": usage,
                "latency_ms": latency_ms,
                "attempts": attempts,
            },
        )
        return response, usage, latency_ms, attempts

    # -- API pública -----------------------------------------------------------
    def generate_text(
        self,
        contents: Any,
        system_prompt_id: str = "SMOKE_PROMPT_v1",
        temperature: float = EXTRACTION_TEMPERATURE,
        thinking_level: Optional[str] = None,
    ) -> LLMResult:
        """Llamada de texto libre (por ejemplo, la prueba de humo)."""
        response, usage, latency, attempts = self._generate(
            "text", contents, system_prompt_id, temperature, thinking_level
        )
        return LLMResult(
            text=getattr(response, "text", None),
            usage=usage,
            latency_ms=latency,
            attempts=attempts,
            model=self.model,
        )

    def generate_structured(
        self,
        system_prompt_id: str,
        contents: Any,
        schema: dict[str, Any],
        schema_name: str = "schema",
        temperature: float = EXTRACTION_TEMPERATURE,
        thinking_level: Optional[str] = None,
    ) -> LLMResult:
        """Llamada con salida JSON según `schema` (JSON Schema).

        `LLMResult.data` contiene el JSON ya interpretado, o `None` y
        `json_error` si el texto no es JSON válido. La validación de contenido
        la hace quien llama (por ejemplo, con Pydantic).
        """
        response, usage, latency, attempts = self._generate(
            "structured", contents, system_prompt_id, temperature, thinking_level,
            schema=schema, schema_name=schema_name,
        )
        text = getattr(response, "text", None)
        data: Any = None
        json_error: Optional[str] = None
        if not isinstance(text, str) or not text.strip():
            json_error = "respuesta vacía"
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as error:
                json_error = f"JSON inválido: {error.msg}"
        return LLMResult(
            text=text,
            data=data,
            json_error=json_error,
            usage=usage,
            latency_ms=latency,
            attempts=attempts,
            model=self.model,
        )

    def generate_with_tools(
        self,
        contents: Any,
        tools: list[Any],
        system_prompt_id: str,
        temperature: float = AGENT_TEMPERATURE,
    ) -> ToolLLMResult:
        """Una decisión del agente con function calling nativo (modo AUTO).

        Devuelve las llamadas a función pedidas (`function_calls`) o el texto
        final. La traza `LLM_DECISION` incluye la decisión: nombres y argumentos
        de las llamadas, o `final_text`. El ciclo de ejecución de las tools vive
        en `app/agent.py`; el SDK nunca las ejecuta por su cuenta.
        """
        response, usage, latency, attempts = self._generate(
            "tools", contents, system_prompt_id, temperature,
            tools=tools, decision_fn=_describe_decision,
        )
        calls = _extract_calls(response)
        candidates = getattr(response, "candidates", None)
        content = candidates[0].content if candidates else None
        return ToolLLMResult(
            text=_extract_text(content),
            function_calls=calls,
            content=content,
            usage=usage,
            latency_ms=latency,
            attempts=attempts,
            model=self.model,
        )


def _extract_calls(response: Any) -> list[ToolCallRequest]:
    """Convierte `response.function_calls` del SDK en `ToolCallRequest`."""
    return [
        ToolCallRequest(
            name=call.name or "",
            args=dict(call.args) if call.args else {},
            id=getattr(call, "id", None),
        )
        for call in (getattr(response, "function_calls", None) or [])
    ]


def _extract_text(content: Any) -> Optional[str]:
    """Texto visible del contenido (ignora partes de pensamiento y llamadas)."""
    parts = getattr(content, "parts", None) or []
    texts = [
        part.text
        for part in parts
        if isinstance(getattr(part, "text", None), str) and not getattr(part, "thought", False)
    ]
    return "".join(texts) if texts else None


def _describe_decision(response: Any) -> dict[str, Any]:
    """Decisión para la traza: llamadas a función (nombre y argumentos) o texto final."""
    calls = _extract_calls(response)
    if calls:
        return {"type": "function_calls", "calls": [{"name": c.name, "args": c.args} for c in calls]}
    return {"type": "final_text"}
