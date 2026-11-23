import logging

import httpx
from typing import Protocol
from pydantic import ValidationError

from app.config import Settings
from app.schemas import SearchResult

logger = logging.getLogger(__name__)


class SearchUnavailable(RuntimeError):
    pass


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str) -> list[SearchResult]: ...
    async def close(self) -> None: ...


class TavilySearchService:
    """Tavily Search API using its documented POST endpoint and bearer authentication."""
    name = "Tavily Search"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
        self._owns_client = client is None
        self.availability = "not_checked" if settings.tavily_api_key else "not_configured"
        self.last_error: str | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def search(self, query: str) -> list[SearchResult]:
        if not self.settings.tavily_api_key:
            self.availability = "not_configured"
            self.last_error = "TAVILY_API_KEY is not configured"
            raise SearchUnavailable("TAVILY_API_KEY is not configured")
        try:
            logger.info(
                "Tavily request endpoint=%s query=%r depth=basic max_results=%d",
                self.endpoint,
                query,
                self.settings.search_results_per_query,
            )
            response = await self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.settings.tavily_api_key}", "Content-Type": "application/json"},
                json={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": self.settings.search_results_per_query,
                    "include_answer": False,
                    "include_raw_content": False,
                    "safe_search": True,
                },
            )
            logger.info("Tavily response http_status=%d query=%r", response.status_code, query)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("results", []), list):
                self.availability = "invalid_response"
                self.last_error = "Tavily response did not contain a results list"
                raise SearchUnavailable(self.last_error)
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            logger.info("Tavily raw_result_count=%d query=%r", len(rows), query)
            results: list[SearchResult] = []
            for index, row in enumerate(rows):
                title, url = row.get("title"), row.get("url")
                snippet = row.get("content") or ""
                logger.info(
                    "Tavily raw_result index=%d title=%r url=%r extracted_text_length=%d",
                    index,
                    title,
                    url,
                    len(snippet),
                )
                if not title or not url:
                    logger.warning("Tavily result discarded index=%d reason=missing_title_or_url", index)
                    continue
                try:
                    results.append(SearchResult(title=title, url=url, snippet=snippet, source=self.name))
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "Tavily result discarded index=%d title=%r url=%r reason=invalid_result type=%s",
                        index,
                        title,
                        url,
                        type(exc).__name__,
                    )
            logger.info("Tavily valid_search_result_count=%d query=%r", len(results), query)
            self.availability = "available"
            self.last_error = None
            return results
        except httpx.TimeoutException as exc:
            self.availability = "temporarily_unavailable"
            self.last_error = "Tavily Search timed out"
            logger.error("Tavily request timed out query=%r error=%s", query, type(exc).__name__)
            raise SearchUnavailable("Tavily Search timed out") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                self.availability, reason = "invalid_api_key", "invalid API key"
            elif status in {429, 432}:
                self.availability, reason = "quota_exhausted", "rate limited or free credits exhausted"
            elif status == 503 or status >= 500:
                self.availability, reason = "temporarily_unavailable", f"HTTP {status}"
            else:
                self.availability, reason = "request_failed", f"HTTP {status}"
            self.last_error = f"Tavily Search {reason}"
            logger.error("Tavily request failed http_status=%d reason=%s query=%r", status, reason, query)
            raise SearchUnavailable(f"Tavily Search {reason}") from exc
        except SearchUnavailable:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, ValidationError) as exc:
            self.availability = "temporarily_unavailable" if isinstance(exc, httpx.HTTPError) else "invalid_response"
            self.last_error = f"Tavily Search response/network error ({type(exc).__name__})"
            logger.exception("Tavily response processing failed query=%r", query)
            raise SearchUnavailable(f"Tavily Search network or response error ({type(exc).__name__})") from exc


def build_search_service(settings: Settings) -> SearchProvider:
    provider = settings.search_provider.casefold().strip()
    if provider == "tavily":
        return TavilySearchService(settings)
    raise ValueError(f"Unsupported SEARCH_PROVIDER: {provider}; this project is configured for Tavily")
