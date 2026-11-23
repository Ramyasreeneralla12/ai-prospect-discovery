
import asyncio
import logging
import re
import time
from typing import Any

import httpx

from app.config import Settings
from app.platforms.facebook import FacebookAdapter
from app.platforms.instagram import InstagramAdapter
from app.platforms.linkedin import LinkedInAdapter
from app.platforms.threads import ThreadsAdapter
from app.platforms.x_platform import XAdapter
from app.platforms.youtube import YouTubeAdapter
from app.schemas import DiscoveryResponse, ProspectEvidence, QueryIntent, SearchResult
from app.services.deduplication_service import deduplicate
from app.services.llm_service import LLMError, LLMService
from app.services.profile_extractor import (
    candidate_rejection_reason,
    deterministic_assessment,
    extract_candidate,
)
from app.services.query_service import deterministic_intent, deterministic_queries
from app.services.relevance_service import assess_candidate_score, fallback_score
from app.services.search_service import SearchProvider
from app.utils.validators import is_valid_profile_url

logger = logging.getLogger(__name__)

ADAPTERS = [
    LinkedInAdapter,
    InstagramAdapter,
    YouTubeAdapter,
    XAdapter,
    FacebookAdapter,
    ThreadsAdapter,
]


class ProspectService:
    def __init__(
        self,
        settings: Settings,
        search: SearchProvider,
        llm: LLMService,
    ):
        self.settings = settings
        self.search = search
        self.llm = llm
        self.last_evidence: list[ProspectEvidence] = []

    async def discover(self, query: str) -> DiscoveryResponse:
        started = time.perf_counter()

        try:
            response = await self._discover(query)
        except Exception:
            logger.exception(
                "Prospect discovery failed duration_seconds=%.3f",
                time.perf_counter() - started,
            )
            raise

        logger.info(
            "Prospect discovery completed duration_seconds=%.3f prospect_count=%d",
            time.perf_counter() - started,
            response.total_prospects,
        )

        return response

    async def _discover(self, query: str) -> DiscoveryResponse:
        provider_name = getattr(
            self.search, "name", "Configured search provider"
        )

        warnings: list[str] = [
            "Unsupported direct platforms: Google and WhatsApp; "
            "Tavily searches publicly indexed profiles on LinkedIn, "
            "Instagram, YouTube, X, Facebook, and Threads."
        ]

        intent = deterministic_intent(query)
        generated_queries = deterministic_queries(intent)

        # Use Gemini only for complex queries to save API quota.
        if self._needs_ai_query_understanding(query) and self.llm.configured():
            try:
                intent, generated_queries = await self.llm.understand(query)
                generated_queries = (
                    generated_queries or deterministic_queries(intent)
                )
                logger.info("Query understanding completed using Gemini")

            except LLMError as exc:
                warnings.append(
                    self._gemini_fallback_warning(exc, "query parsing")
                )
                logger.warning(
                    "Gemini query understanding failed; "
                    "deterministic parsing used: %s",
                    exc,
                )
        else:
            logger.info(
                "Query understanding used deterministic parser; "
                "Gemini call skipped"
            )

        terms = " ".join(
            dict.fromkeys(
                [intent.audience, intent.interest, *intent.keywords]
            )
        ).strip()

        location = intent.location.display() or ""

        # Generate clean platform-specific search queries.
        queries: list[tuple[Any, str]] = []

        for index, adapter_type in enumerate(
            ADAPTERS[:self.settings.max_search_queries]
        ):
            adapter = adapter_type(self.search)

            if (
                adapter.name == "LinkedIn"
                and intent.target_type == "business"
            ):
                adapter.domain_query = "linkedin.com/company"

            phrase = (
                generated_queries[index]
                if index < len(generated_queries)
                else terms
            )

            # Remove any existing site filter.
            phrase = re.sub(
                r"\bsite:\S+",
                "",
                phrase,
                flags=re.I,
            )

            # Remove location if it is already included.
            if location:
                phrase = re.sub(
                    rf"\s+{re.escape(location)}\s*$",
                    "",
                    phrase,
                    flags=re.I,
                )

            # Remove leftover quotation marks and whitespace.
            phrase = phrase.strip().strip('"').strip() or terms

            search_query = adapter.make_query(phrase, location)

            logger.info(
                "Generated platform search query platform=%s query=%r",
                adapter.name,
                search_query,
            )

            queries.append((adapter, search_query))

        # Search all configured platforms concurrently.
        results = await asyncio.gather(
            *(self.search.search(search_query) for _, search_query in queries),
            return_exceptions=True,
        )

        source_names: list[str] = [provider_name]
        all_results: list[SearchResult] = []

        raw_result_count = 0
        profile_filter_count = 0
        search_failure_count = 0

        for (adapter, search_query), outcome in zip(queries, results):
            source_names.append(adapter.name)

            if isinstance(outcome, Exception):
                search_failure_count += 1
                warnings.append(
                    f"{adapter.name} discovery failed: {str(outcome)}"
                )

                logger.error(
                    "Search adapter failed adapter=%s query=%r error=%s",
                    adapter.name,
                    search_query,
                    outcome,
                )
                continue

            logger.info(
                "Search adapter completed adapter=%s result_count=%d query=%r",
                adapter.name,
                len(outcome),
                search_query,
            )

            for result in outcome:
                raw_result_count += 1
                url = str(result.url)

                extracted_text_length = len(result.title) + len(result.snippet)

                logger.info(
                    "Search result title=%r url=%r "
                    "extracted_text_length=%d source=%s",
                    result.title,
                    url,
                    extracted_text_length,
                    result.source,
                )

                if not adapter.accepts(url):
                    profile_filter_count += 1

                    logger.info(
                        "Candidate rejected title=%r url=%r "
                        "reason=result_does_not_match_adapter=%s",
                        result.title,
                        url,
                        adapter.name,
                    )
                    continue

                if not is_valid_profile_url(url, intent.target_type):
                    profile_filter_count += 1

                    logger.info(
                        "Candidate rejected title=%r url=%r "
                        "reason=invalid_%s_profile_url",
                        result.title,
                        url,
                        intent.target_type,
                    )
                    continue

                all_results.append(result)

        logger.info(
            "Search filtering summary raw_result_count=%d "
            "valid_profile_url_count=%d removed_by_profile_filter=%d",
            raw_result_count,
            len(all_results),
            profile_filter_count,
        )

        # Deduplicate identical profile URLs.
        unique: dict[str, SearchResult] = {}

        for result in all_results:
            normalized_url = str(result.url).rstrip("/").casefold()

            if normalized_url in unique:
                logger.info(
                    "Candidate rejected title=%r url=%r "
                    "reason=duplicate_profile_url",
                    result.title,
                    result.url,
                )
            else:
                unique[normalized_url] = result

        duplicate_count = len(all_results) - len(unique)
        over_limit_count = max(0, len(unique) - 40)
        unique_rows = list(unique.values())

        for result in unique_rows[40:]:
            logger.info(
                "Candidate rejected title=%r url=%r "
                "reason=maximum_candidate_limit",
                result.title,
                result.url,
            )

        rows = unique_rows[:40]

        # LLM-based candidate scoring.
        scored: dict[str, dict[str, Any]] = {}

        if self.llm.configured() and rows:
            candidates_for_llm = [
                {
                    "id": str(i),
                    "title": result.title[:300],
                    "url": str(result.url),
                    "snippet": result.snippet[:700],
                }
                for i, result in enumerate(rows)
            ]

            try:
                scored = await self.llm.score_candidates(
                    query,
                    intent,
                    candidates_for_llm,
                )

            except LLMError as exc:
                warnings.append(
                    self._gemini_fallback_warning(
                        exc,
                        "relevance scoring and evidence-based prospect extraction",
                    )
                )

        elif rows:
            warnings.append(
                f"{self.settings.llm_provider.title()} is not configured; "
                "deterministic relevance scoring and "
                "evidence-based prospect extraction were used."
            )

        candidates: list[tuple[Any, list[str]]] = []
        self.last_evidence = []

        relevance_rejected_count = 0
        extraction_rejected_count = 0

        for i, result in enumerate(rows):
            entry = scored.get(str(i), {})

            if entry:
                score, rationale = assess_candidate_score(
                    intent,
                    result,
                    entry,
                )
            else:
                score, rationale = fallback_score(intent, result)

            if score < self.settings.min_relevance_score:
                relevance_rejected_count += 1

                logger.info(
                    "Candidate rejected title=%r url=%r score=%.3f "
                    "threshold=%.3f reason=%s",
                    result.title,
                    result.url,
                    score,
                    self.settings.min_relevance_score,
                    rationale,
                )
                continue

            if not entry:
                entry = deterministic_assessment(result, intent)

            rejection = candidate_rejection_reason(
                result,
                entry,
                intent.target_type,
                intent.audience,
                intent,
            )

            if rejection:
                extraction_rejected_count += 1

                logger.info(
                    "Candidate rejected title=%r url=%r score=%.3f reason=%s",
                    result.title,
                    result.url,
                    score,
                    rejection,
                )
                continue

            extracted = extract_candidate(
                result,
                entry,
                intent.target_type,
                intent.audience,
            )

            if extracted:
                prospect, evidence = extracted

                candidates.append((prospect, evidence))

                self.last_evidence.append(
                    ProspectEvidence(
                        prospect=prospect,
                        evidence_urls=evidence,
                        score=score,
                        rationale=rationale,
                    )
                )

                logger.info(
                    "Prospect extracted name=%r profile_url=%r "
                    "score=%.3f evidence_url_count=%d",
                    prospect.name,
                    result.url,
                    score,
                    len(evidence),
                )

            else:
                extraction_rejected_count += 1

                logger.warning(
                    "Candidate rejected title=%r url=%r "
                    "reason=extraction_failed_without_reason",
                    result.title,
                    result.url,
                )

        merged = deduplicate(candidates)

        if raw_result_count == 0:
            if search_failure_count == len(queries):
                warnings.append(
                    f"Search failed: {provider_name} was unavailable "
                    "for all configured profile searches."
                )
            else:
                warnings.append(
                    f"{provider_name} search completed successfully "
                    "but returned zero search results."
                )

        elif not merged:
            warnings.append(
                f"{provider_name} returned {raw_result_count} results, "
                "but none met the public-profile and evidence requirements; "
                "no prospects matched."
            )

        logger.info(
            "Prospect extraction summary raw_results=%d "
            "filtered_profiles=%d duplicates=%d over_limit=%d "
            "relevance_rejected=%d extraction_rejected=%d "
            "prospects_extracted=%d prospects_after_deduplication=%d",
            raw_result_count,
            len(all_results),
            duplicate_count,
            over_limit_count,
            relevance_rejected_count,
            extraction_rejected_count,
            len(candidates),
            len(merged),
        )

        return DiscoveryResponse(
            query=query,
            total_prospects=len(merged),
            prospects=[item[0] for item in merged],
            sources_checked=list(dict.fromkeys(source_names)),
            warnings=warnings,
        )

    @staticmethod
    def _needs_ai_query_understanding(query: str) -> bool:
        return (
            len(query) >= 120
            or len(
                re.findall(
                    r"\b(and|or|who|that|which|with|without)\b",
                    query,
                    re.I,
                )
            )
            >= 2
        )

    def _gemini_fallback_warning(
        self,
        error: LLMError,
        fallback_step: str,
    ) -> str:
        provider = self.settings.llm_provider.casefold()
        detail = str(error)

        status = (
            getattr(self.llm, "gemini_availability", "")
            if provider == "gemini"
            else ""
        )

        lowered = f"{status} {detail}".casefold()

        if provider == "gemini" and (
            "quota_exhausted" in lowered
            or "quota" in lowered
            or "429" in lowered
        ):
            issue = "Gemini quota is exhausted"

        elif provider == "gemini" and (
            "temporary_service_unavailable" in lowered
            or "503" in lowered
            or "temporarily unavailable" in lowered
        ):
            issue = "Gemini is temporarily unavailable"

        elif provider == "gemini" and (
            "invalid_api_key" in lowered
            or "invalid api key" in lowered
        ):
            issue = "Gemini API key is invalid"

        elif provider == "gemini" and "unsupported_model" in lowered:
            issue = "The configured Gemini model is unsupported"

        else:
            issue = f"{self.settings.llm_provider.title()} is unavailable"

        return (
            f"{issue}; deterministic {fallback_step} was used. "
            f"Provider detail: {detail}"
        )
