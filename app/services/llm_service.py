import asyncio
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
import logging
import random
import re
import time
from typing import Any

import httpx
from google import genai
from google.genai import types as genai_types
from pydantic import ValidationError

from app.config import Settings
from app.schemas import QueryIntent
from app.services.query_service import PERSON_AUDIENCE, normalize_intent_location

logger = logging.getLogger(__name__)
GEMINI_MAX_RETRIES = 2
GEMINI_RESPONSE_CACHE_TTL_SECONDS = 300
GEMINI_RESPONSE_CACHE_MAX_ENTRIES = 256
GEMINI_PROVIDER_COOLDOWN_SECONDS = 30
GEMINI_RATE_LIMIT_COOLDOWN_SECONDS = 60
_CACHE_MISS = object()

QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "interest": {"type": "string"}, "audience": {"type": "string"},
        "location": {"type": "object", "properties": {
            "city": {"type": ["string", "null"]}, "state": {"type": ["string", "null"]},
            "country": {"type": ["string", "null"]}}, "required": ["city", "state", "country"]},
        "target_type": {"type": "string", "enum": ["individual", "business", "unknown"]},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "search_queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["interest", "audience", "location", "target_type", "keywords", "search_queries"],
}
CANDIDATES_SCHEMA: dict[str, Any] = {
    "type": "object", "properties": {"candidates": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "string"}, "score": {"type": "number"},
            "entity_type": {"type": "string", "enum": ["individual", "business", "invalid"]},
            "is_profile": {"type": "boolean"}, "name": {"type": ["string", "null"]},
            "role_evidence": {"type": ["string", "null"]},
            "location": {"type": "object", "properties": {
                "city": {"type": ["string", "null"]}, "state": {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]}}, "required": ["city", "state", "country"]},
            "rationale": {"type": "string"},
        },
        "required": ["id", "score", "entity_type", "is_profile", "name", "role_evidence", "location", "rationale"],
    }}}, "required": ["candidates"],
}


class LLMError(RuntimeError):
    pass


class LLMService:
    """JSON LLM integration with precise, credential-safe provider diagnostics."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
        self._owns_client = client is None
        self._gemini_client: genai.Client | None = None
        self.gemini_availability = "not_checked" if settings.gemini_api_key else "not_configured"
        self.gemini_last_error: str | None = None
        self._gemini_cooldown_until = 0.0
        self._gemini_cooldown_reason: str | None = None
        self._response_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
        if self._gemini_client is not None:
            await self._gemini_client.aio.aclose()
            self._gemini_client = None

    def configured(self) -> bool:
        return bool({
            "gemini": self.settings.gemini_api_key,
            "openai": self.settings.openai_api_key,
            "anthropic": self.settings.anthropic_api_key,
        }.get(self.settings.llm_provider.casefold(), ""))

    async def understand(self, query: str) -> tuple[QueryIntent, list[str]]:
        prompt = f"""Parse a natural-language prospect search. Return structured JSON with interest, audience, location (city/state/country; null when not stated), target_type (individual/business/unknown), keywords, and 4-6 search_queries without site: directives. Expand UK to United Kingdom, USA to United States, and UAE to United Arab Emirates. Owners and founders are individuals; company/business searches target businesses. Do not invent locations. Search phrases should find public profile pages rather than posts or articles. Query: {json.dumps(query)}"""
        payload = await self._generate_json(prompt, QUERY_SCHEMA)
        if not isinstance(payload, dict):
            raise LLMError("Gemini invalid response: expected a JSON object")
        intent_data = {k: payload.get(k) for k in ("interest", "audience", "location", "target_type", "keywords")}
        try:
            intent = QueryIntent.model_validate(intent_data)
        except ValidationError as exc:
            raise LLMError("Gemini invalid response: query intent does not match the required schema") from exc
        intent = normalize_intent_location(intent)
        if PERSON_AUDIENCE.search(intent.audience) or PERSON_AUDIENCE.search(query):
            intent.target_type = "individual"
        queries = payload.get("search_queries", [])
        if not isinstance(queries, list) or any(not isinstance(q, str) for q in queries):
            raise LLMError("Gemini invalid response: search_queries must be an array of strings")
        return intent, [q.strip() for q in queries if q.strip()]

    async def score_candidates(self, query: str, intent: QueryIntent, candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not candidates:
            return {}
        prompt = ("Classify each search result for prospect discovery. Use ONLY title, URL, and snippet. "
                  "Reject articles, blog posts, posts, hashtags, events, companies when a person is requested, and generic pages. "
                  "For startup-founder searches require an individual profile URL, a name in the title/snippet, and verbatim founder-to-company evidence in that same result; a post merely mentioning startups is insufficient. "
                  "Names and location must be explicit in source text. Return one candidate assessment per input id with score 0..1, "
                  "entity_type individual/business/invalid, is_profile boolean, name or null, short verbatim role_evidence or null, "
                  "location city/state/country with null for unsupported fields, and a concise rationale.\n"
                  f"Request: {json.dumps(query)}\nIntent: {intent.model_dump_json()}\nCandidates: {json.dumps(candidates, ensure_ascii=False)}")
        data = await self._generate_json(prompt, CANDIDATES_SCHEMA)
        if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
            raise LLMError("Gemini invalid response: candidate assessments are missing")
        assessments: dict[str, dict[str, Any]] = {}
        for row in data["candidates"]:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                assessments[row["id"]] = row
        return assessments

    async def _generate_json(self, prompt: str, schema: dict[str, Any] | None = None) -> Any:
        provider = self.settings.llm_provider.casefold()
        if provider == "gemini":
            return await self._generate_gemini_json(prompt, schema)
        try:
            if provider == "openai":
                key, model = self.settings.openai_api_key, self.settings.openai_model
                if not key:
                    raise LLMError("OPENAI_API_KEY is not configured")
                response = await self.client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
                    "model": model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "temperature": 0.1,
                })
                response.raise_for_status()
                body = response.json()["choices"][0]["message"]["content"]
            elif provider == "anthropic":
                key, model = self.settings.anthropic_api_key, self.settings.anthropic_model
                if not key:
                    raise LLMError("ANTHROPIC_API_KEY is not configured")
                response = await self.client.post("https://api.anthropic.com/v1/messages", headers={
                    "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
                }, json={"model": model, "max_tokens": 1200, "temperature": 0.1, "messages": [{"role": "user", "content": prompt}]})
                response.raise_for_status()
                body = response.json()["content"][0]["text"]
            else:
                raise LLMError(f"Unsupported LLM_PROVIDER: {provider}")
            return json.loads(body)
        except LLMError:
            raise
        except Exception as exc:
            kind, status, message = self._describe_provider_exception(exc)
            logger.error("LLM provider failure provider=%s type=%s status=%s kind=%s message=%s",
                         provider, type(exc).__name__, status, kind, message)
            raise LLMError(f"{provider} {kind}{f' (HTTP {status})' if status else ''}: {message}") from exc

    async def _generate_gemini_json(self, prompt: str, schema: dict[str, Any] | None) -> Any:
        if not self.settings.gemini_api_key:
            self.gemini_availability = "not_configured"
            raise LLMError("GEMINI_API_KEY is not configured")
        cache_key = self._response_cache_key(prompt, schema)
        cached = self._get_cached_response(cache_key)
        if cached is not _CACHE_MISS:
            logger.info("Gemini response cache hit key=%s", cache_key[:12])
            return cached
        if time.monotonic() < self._gemini_cooldown_until:
            remaining = max(1, int(self._gemini_cooldown_until - time.monotonic()))
            raise LLMError(
                f"Gemini {self._gemini_cooldown_reason or 'temporarily unavailable'}; "
                f"provider calls paused for {remaining}s after the previous failure"
            )
        if self._gemini_client is None:
            self._gemini_client = genai.Client(
                api_key=self.settings.gemini_api_key,
                # Disable the SDK's built-in retry loop; retries below are bounded
                # to two extra attempts and only cover transient HTTP responses.
                http_options=genai_types.HttpOptions(
                    timeout=int(self.settings.request_timeout_seconds * 1000),
                    retry_options=genai_types.HttpRetryOptions(attempts=1),
                ),
            )
        response_format = {"type": "text", "mime_type": "application/json"}
        if schema:
            response_format["schema"] = schema
        try:
            interaction = await self._create_gemini_interaction(prompt, response_format)
            output_text = interaction.output_text
            if not isinstance(output_text, str) or not output_text.strip():
                raise LLMError("Gemini invalid response: model returned no text")
            try:
                payload = json.loads(output_text)
            except json.JSONDecodeError as exc:
                raise LLMError("Gemini invalid response: output was not valid JSON") from exc
            self.gemini_availability = "available"
            self.gemini_last_error = None
            self._gemini_cooldown_until = 0.0
            self._gemini_cooldown_reason = None
            self._cache_response(cache_key, payload)
            return payload
        except LLMError as exc:
            self._record_gemini_failure("invalid_response", str(exc))
            logger.error("Gemini response failure kind=invalid_response message=%s", self._safe_message(str(exc)))
            raise
        except Exception as exc:
            kind, status, message = self._describe_provider_exception(exc)
            self._record_gemini_failure(kind, message)
            logger.error("Gemini request failure type=%s status=%s kind=%s message=%s",
                         type(exc).__name__, status, kind, message)
            raise LLMError(f"Gemini {kind.replace('_', ' ')}{f' (HTTP {status})' if status else ''}: {message}") from exc

    async def _create_gemini_interaction(self, prompt: str, response_format: dict[str, Any]) -> Any:
        assert self._gemini_client is not None
        for retry_index in range(GEMINI_MAX_RETRIES + 1):
            try:
                return await self._gemini_client.aio.interactions.create(
                    model=self.settings.gemini_model,
                    input=prompt,
                    response_format=response_format,
                    generation_config={"thinking_level": "low", "max_output_tokens": 5000},
                )
            except Exception as exc:
                status, message = getattr(exc, "code", None) or getattr(exc, "status_code", None), self._safe_message(str(exc))
                try:
                    status_code = int(status)
                except (TypeError, ValueError):
                    status_code = 0
                # Daily/free-tier quota exhaustion is terminal for this call and
                # must not be amplified by retries. Only server 5xx is retried.
                retryable = 500 <= status_code <= 599
                if not retryable or retry_index >= GEMINI_MAX_RETRIES:
                    raise
                base_delay = 0.5 * (2 ** retry_index)
                delay = base_delay + random.uniform(0, base_delay * 0.25)
                logger.warning(
                    "Gemini transient response; retrying model=%s status=%s retry=%d/%d delay_seconds=%.2f error=%s",
                    self.settings.gemini_model,
                    status_code,
                    retry_index + 1,
                    GEMINI_MAX_RETRIES,
                    delay,
                    message,
                )
                await asyncio.sleep(delay)

    def _response_cache_key(self, prompt: str, schema: dict[str, Any] | None) -> str:
        stable = json.dumps(
            {"model": self.settings.gemini_model, "prompt": prompt, "schema": schema},
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(stable.encode("utf-8")).hexdigest()

    def _get_cached_response(self, key: str) -> Any:
        cached = self._response_cache.get(key)
        if not cached:
            return _CACHE_MISS
        expires_at, payload = cached
        if expires_at <= time.monotonic():
            del self._response_cache[key]
            return _CACHE_MISS
        self._response_cache.move_to_end(key)
        return deepcopy(payload)

    def _cache_response(self, key: str, payload: Any) -> None:
        self._response_cache[key] = (time.monotonic() + GEMINI_RESPONSE_CACHE_TTL_SECONDS, deepcopy(payload))
        self._response_cache.move_to_end(key)
        while len(self._response_cache) > GEMINI_RESPONSE_CACHE_MAX_ENTRIES:
            self._response_cache.popitem(last=False)

    def _record_gemini_failure(self, kind: str, message: str) -> None:
        self.gemini_availability = kind
        self.gemini_last_error = message
        if kind == "quota_exhausted":
            cooldown = self.settings.gemini_quota_cooldown_seconds
        elif kind == "rate_limited":
            cooldown = GEMINI_RATE_LIMIT_COOLDOWN_SECONDS
        elif kind in {"temporary_service_unavailable", "provider_unavailable"}:
            cooldown = GEMINI_PROVIDER_COOLDOWN_SECONDS
        elif kind in {"invalid_api_key", "unsupported_model"}:
            cooldown = GEMINI_RATE_LIMIT_COOLDOWN_SECONDS
        else:
            cooldown = 0
        if cooldown:
            self._gemini_cooldown_until = time.monotonic() + cooldown
            self._gemini_cooldown_reason = kind.replace("_", " ")

    @staticmethod
    def _describe_provider_exception(exc: Exception) -> tuple[str, int | str | None, str]:
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        try:
            numeric_status = int(status)
        except (TypeError, ValueError):
            numeric_status = 0
        message = LLMService._safe_message(str(exc))
        type_name = type(exc).__name__.casefold()
        text = message.casefold()
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or "timeout" in type_name or "timed out" in text:
            kind = "network timeout"
        elif numeric_status == 429:
            # Treat every Gemini HTTP 429 as quota exhaustion for this process.
            # Google's 429 responses cover both request and daily quota limits;
            # probing again only creates more rejected requests and obscures the
            # fallback path. The configured cooldown bounds when we try again.
            kind = "quota_exhausted"
        elif numeric_status in {401, 403} or "api key not valid" in text or "api_key_invalid" in text:
            kind = "invalid_api_key"
        elif numeric_status == 404 or "model not found" in text or "not supported for generatecontent" in text:
            kind = "unsupported_model"
        elif numeric_status == 503:
            kind = "temporary_service_unavailable"
        elif isinstance(exc, (json.JSONDecodeError, KeyError, IndexError, TypeError)):
            kind = "invalid response"
        elif numeric_status >= 500:
            kind = "provider_unavailable"
        elif isinstance(exc, httpx.HTTPError):
            kind = "network error"
        else:
            kind = "provider error"
        return kind, status, message or type(exc).__name__

    @staticmethod
    def _safe_message(value: str) -> str:
        value = re.sub(r"(?i)AIza[0-9A-Za-z_-]{20,}", "[REDACTED_KEY]", value)
        value = re.sub(r"(?i)(?:tvly-|sk-ant-|sk-proj-)[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", value)
        value = re.sub(r"(?i)(api[_-]?key|x-subscription-token)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", value)
        return value[:600]
