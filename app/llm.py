"""Cliente LLM único (SDK oficial `google-genai`).

Responsabilidades:
- Crear el cliente de Gemini de forma perezosa desde la configuración (grupo "llm").
- Pausa mínima entre llamadas y reintentos con espera exponencial ante 429 /
  RESOURCE_EXHAUSTED (y 503 / UNAVAILABLE), cada reintento como evento `RETRY`.
- Contadores por sesión (llamadas, reintentos, tokens).
- Traza de cada llamada como `LLM_DECISION` con modelo exacto, parámetros,
  identificadores de prompt, uso de tokens y latencia.

Embeddings (Etapa 15, RAG): `LLMClient.embed` reutiliza la misma pausa, los mismos reintentos y la
misma traza (`LLM_DECISION` con `kind="embedding"`), pero con contadores propios (`EmbedStats`).

Nunca registra la clave de API, el texto de los prompts ni los bytes de las imágenes.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.config import EMBEDDING_DIMS, EMBEDDING_MODEL, Settings, load_settings
from app.models import EventType
from app.prompts import ACTIVE_SECURITY_SCOPE, SECURITY_SCOPE_ID, compose_system_instruction
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

# Temperatura del router (Etapa 9): clasificar es una decisión discreta y debe ser
# reproducible, así que se usa 0.0 como en la extracción y el agente. El riesgo de bucles
# que Google describe para Gemini 3 no aplica: es una sola llamada con salida JSON acotada.
# Si la precisión por ruta bajara en la verificación real, probar 1.0 cambiando esta constante.
ROUTER_TEMPERATURE = 0.0

# Temperatura de las respuestas directas (CONVERSACION y CONSULTAR_GASTOS, Etapa 9).
# 0.0 prioriza fidelidad al estado entregado (no inventar cifras) sobre variedad de redacción.
ANSWER_TEMPERATURE = 0.0

# Temperatura del juez (Etapa 11): un veredicto de verificación debe ser reproducible. Es una sola
# llamada con salida JSON acotada, así que el riesgo de bucles de Gemini 3 con 0.0 no aplica.
JUDGE_TEMPERATURE = 0.0

# Propósitos válidos de `LLMClient.embed`. `gemini-embedding-2` no admite `task_type`: la tarea se
# indica en el texto (ver `app/rag/formats.py`) y el propósito solo queda en la traza.
EMBED_PURPOSES = ("documento", "consulta")

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

    def add(self, name: str, amount: int = 1) -> None:
        setattr(self, name, getattr(self, name) + amount)


# Acumulador de TODAS las instancias de `LLMClient` del proceso (por ejemplo, de una sesión del
# notebook, donde cada sección crea su propio cliente). Cada cliente suma aquí lo mismo que en su
# `stats`. Es solo de lectura para quien reporta: `session_stats()` devuelve una copia.
_SESSION_STATS = UsageStats()


def session_stats() -> UsageStats:
    """Copia de los contadores acumulados por todos los clientes LLM del proceso."""
    return UsageStats(**_SESSION_STATS.as_dict())


def reset_session_stats() -> None:
    """Pone en cero el acumulador del proceso (para pruebas o para medir un tramo)."""
    for name in list(_SESSION_STATS.__dict__):
        setattr(_SESSION_STATS, name, 0)
    for name in list(_SESSION_EMBED.__dict__):
        setattr(_SESSION_EMBED, name, 0)


@dataclass
class EmbedStats:
    """Contadores de las llamadas de embeddings, separados de los de generación."""

    calls: int = 0
    failed_calls: int = 0
    retries: int = 0
    texts: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)

    def add(self, name: str, amount: int = 1) -> None:
        setattr(self, name, getattr(self, name) + amount)


# Acumulador de proceso de las llamadas de embeddings (equivale a `_SESSION_STATS`).
_SESSION_EMBED = EmbedStats()


def session_embed_stats() -> EmbedStats:
    """Copia de los contadores de embeddings acumulados por todos los clientes del proceso."""
    return EmbedStats(**_SESSION_EMBED.as_dict())


class EmbeddingError(Exception):
    """La respuesta de embeddings no tiene la forma esperada. Nunca incluye los vectores."""


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
        self.embed_stats = EmbedStats()
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

    def _count(self, name: str, amount: int = 1) -> None:
        """Suma al contador del cliente y al acumulador del proceso."""
        self.stats.add(name, amount)
        _SESSION_STATS.add(name, amount)

    def _count_embed(self, name: str, amount: int = 1) -> None:
        """Suma al contador de embeddings del cliente y al acumulador del proceso."""
        self.embed_stats.add(name, amount)
        _SESSION_EMBED.add(name, amount)

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

    def _send_with_retries(
        self,
        send: Callable[[], Any],
        call_id: int,
        model_name: str,
        count: Callable[[str], None],
        on_failure: Callable[[Any, Any, int], None],
    ) -> tuple[Any, int]:
        """Ejecuta `send` con pausa mínima y reintentos con espera exponencial (429 y 503).

        Cada reintento se cuenta con `count("retries")` y se registra como `RETRY`. Al agotarse
        los reintentos (o ante un error no reintentable) llama a `on_failure(code, status,
        intentos)` y lanza `LLMCallError`. Devuelve `(respuesta, intentos)`.
        """
        attempts = 0
        while True:
            attempts += 1
            self._throttle()
            try:
                return send(), attempts
            except Exception as error:  # noqa: BLE001 - se reclasifica abajo
                code = getattr(error, "code", None)
                status = getattr(error, "status", None)
                retries_done = attempts - 1
                if self._is_retryable(error) and retries_done < self.max_retries:
                    wait = self._backoff(retries_done + 1)
                    count("retries")
                    self.tracer.record(
                        EventType.RETRY,
                        {
                            "call_id": call_id,
                            "model": model_name,
                            "attempt": retries_done + 1,
                            "max_retries": self.max_retries,
                            "wait_seconds": wait,
                            "error_code": code,
                            "error_status": status,
                        },
                    )
                    self._sleep(wait)
                    continue
                on_failure(code, status, attempts)
                raise LLMCallError(code, status, attempts) from error

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

        # Garantía estructural: toda llamada pasa por aquí y su instrucción de sistema
        # siempre empieza con el bloque de alcance vigente (Etapa 8).
        system_instruction = compose_system_instruction(system_prompt_id)
        if not system_instruction.startswith(ACTIVE_SECURITY_SCOPE):
            raise RuntimeError("La instrucción de sistema no incluye el bloque de alcance.")
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
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
        # Mensajes (`Content`) enviados en la llamada con tools: historial + turno.
        history = {"history_messages": len(contents)} if kind == "tools" else {}
        self._count("calls")
        started = self._clock()

        def on_failure(code: Any, status: Any, attempts: int) -> None:
            self._count("failed_calls")
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
                    "security_scope_id": SECURITY_SCOPE_ID,
                    **history,
                },
            )

        response, attempts = self._send_with_retries(
            lambda: self._sdk().models.generate_content(
                model=self.model, contents=contents, config=config
            ),
            call_id, self.model, self._count, on_failure,
        )

        latency_ms = int(round((self._clock() - started) * 1000))
        usage = extract_usage(response)
        self._count("prompt_tokens", usage["prompt_token_count"])
        self._count("output_tokens", usage["candidates_token_count"])
        self._count("thinking_tokens", usage["thoughts_token_count"])
        self._count("total_tokens", usage["total_token_count"])
        self.tracer.record(
            EventType.LLM_DECISION,
            {
                "call_id": call_id,
                "kind": kind,
                "model": self.model,
                "status": "ok",
                "system_prompt_id": system_prompt_id,
                "security_scope_id": SECURITY_SCOPE_ID,
                **history,
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

    def embed(self, texts: list[str], purpose: str = "documento") -> list[list[float]]:
        """Embeddings de `texts` (un vector por texto, en el mismo orden) con `gemini-embedding-2`.

        Los textos llegan YA formateados con la plantilla de su propósito (`app/rag/formats.py`):
        el modelo no admite `task_type`, así que la tarea va dentro del texto. `purpose`
        ("documento" o "consulta") se registra en la traza. Se envía un `Content` por texto, de
        modo que cada uno produce su propio vector (varias partes en un `Content` se agregarían
        en uno solo). Los vectores salen con `EMBEDDING_DIMS` dimensiones y ya normalizados.

        Sin bloque de alcance a propósito: una llamada de embeddings no decide ni redacta nada
        (no hay instrucción de sistema, solo un vector numérico), de modo que no puede obedecer
        una orden incrustada ni producir una acción. Las llamadas de generación sí lo llevan.

        Usa la misma pausa y los mismos reintentos que las demás llamadas, pero cuenta aparte
        (`embed_stats`). La traza es un `LLM_DECISION` con `kind="embedding"`, que no incluye
        ni los textos ni los vectores.

        Raises:
            ValueError: si `purpose` no es válido o `texts` está vacío o tiene textos vacíos.
            LLMCallError: si la llamada falla tras los reintentos.
            EmbeddingError: si la respuesta no trae un vector de las dimensiones esperadas por texto.
        """
        from google.genai import types

        if purpose not in EMBED_PURPOSES:
            raise ValueError(f"purpose debe ser uno de {EMBED_PURPOSES}")
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("texts debe ser una lista no vacía de textos no vacíos")

        config = types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMS)
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
        self._call_seq += 1
        call_id = self._call_seq
        self._count_embed("calls")
        started = self._clock()
        base = {"call_id": call_id, "kind": "embedding", "model": EMBEDDING_MODEL,
                "purpose": purpose, "n_texts": len(texts), "dims": EMBEDDING_DIMS}

        def on_failure(code: Any, status: Any, attempts: int) -> None:
            self._count_embed("failed_calls")
            self.tracer.record(
                EventType.LLM_DECISION,
                {**base, "status": "error", "error_code": code, "error_status": status,
                 "attempts": attempts},
            )

        response, attempts = self._send_with_retries(
            lambda: self._sdk().models.embed_content(
                model=EMBEDDING_MODEL, contents=contents, config=config
            ),
            call_id, EMBEDDING_MODEL, self._count_embed, on_failure,
        )
        vectors = [list(e.values or []) for e in (getattr(response, "embeddings", None) or [])]
        if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIMS for v in vectors):
            self._count_embed("failed_calls")
            self.tracer.record(
                EventType.LLM_DECISION,
                {**base, "status": "error", "error_status": "respuesta_invalida",
                 "attempts": attempts, "n_vectors": len(vectors)},
            )
            raise EmbeddingError(
                f"La respuesta de embeddings no coincide con lo esperado "
                f"({len(vectors)} vectores para {len(texts)} textos, {EMBEDDING_DIMS} dimensiones)"
            )
        self._count_embed("texts", len(texts))
        self.tracer.record(
            EventType.LLM_DECISION,
            {**base, "status": "ok",
             "latency_ms": int(round((self._clock() - started) * 1000)), "attempts": attempts},
        )
        return vectors


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
