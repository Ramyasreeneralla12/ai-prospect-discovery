import re

from app.schemas import QueryIntent, SearchResult
from app.services.profile_extractor import FOUNDER_RELATION, classify_result, evidence_location
from app.utils.validators import is_valid_profile_url


def assess_candidate_score(intent: QueryIntent, result: SearchResult, assessment: dict) -> tuple[float, str]:
    """Combine model judgment with deterministic identity, role, location, and URL checks."""
    text = f"{result.title}\n{result.snippet}"
    lowered = text.casefold()
    profile_kind = classify_result(result, intent.target_type)
    authentic_profile = profile_kind in {"individual_profile", "business_profile", "profile"} and is_valid_profile_url(str(result.url), intent.target_type)
    name = assessment.get("name")
    name_supported = isinstance(name, str) and bool(name.strip()) and name.casefold() in lowered
    entity_supported = assessment.get("entity_type") == intent.target_type
    model_score = assessment.get("score")
    model_score = float(model_score) if isinstance(model_score, (int, float)) else 0.0
    model_score = max(0.0, min(1.0, model_score))

    founder_request = bool(re.search(r"\bfounders?\b|\bco-founders?\b", intent.audience, re.I))
    role_quote = assessment.get("role_evidence")
    role_supported = isinstance(role_quote, str) and role_quote.casefold() in lowered
    if founder_request:
        role_supported = role_supported and bool(FOUNDER_RELATION.search(role_quote or ""))
    else:
        role_words = [word for word in re.findall(r"[\w-]+", intent.audience.casefold()) if len(word) > 3]
        role_supported = role_supported or any(word in lowered for word in role_words)

    requested_parts = [part for part in (intent.location.city, intent.location.state, intent.location.country) if part]
    supported_location = (evidence_location(assessment.get("location"), text) or "").casefold()
    if requested_parts:
        if any(part.casefold() in supported_location for part in requested_parts):
            location_score = 1.0
        elif any(part.casefold() in lowered for part in requested_parts):
            location_score = 0.8
        else:
            location_score = 0.0
    else:
        location_score = 0.5

    if not authentic_profile or not name_supported or not entity_supported:
        return 0.0, "Rejected: profile URL, name, or target type is not supported by source evidence."
    if founder_request and not role_supported:
        return min(0.35, model_score), "Rejected: source does not connect this person to a founder role at a startup or company."
    if requested_parts and location_score == 0:
        return min(0.55, model_score), "Rejected: public source does not support the requested location."

    score = 0.35 * model_score + 0.20 * float(authentic_profile) + 0.20 * float(name_supported) + 0.15 * float(role_supported) + 0.10 * location_score
    rationale = str(assessment.get("rationale") or "Evidence-backed relevance assessment")[:500]
    return round(min(1.0, score), 3), rationale


def fallback_score(intent: QueryIntent, result: SearchResult) -> tuple[float, str]:
    """Conservative fallback used when the LLM is unavailable; never confirms identity."""
    text = f"{result.title} {result.snippet}".casefold()
    terms = [term.casefold() for term in [intent.interest, intent.audience, *intent.keywords] if term and len(term) > 2]
    unique = list(dict.fromkeys(terms))
    hit_ratio = sum(1 for term in unique if term in text) / max(len(unique), 1)
    profile_authentic = is_valid_profile_url(str(result.url), intent.target_type)
    founder_request = bool(re.search(r"\bfounders?\b|\bco-founders?\b", intent.audience, re.I))
    founder_connection = bool(FOUNDER_RELATION.search(text))
    if founder_request and not founder_connection:
        return 0.0, "No explicit founder-to-company evidence in the public result."
    score = 0.12 + 0.38 * hit_ratio + 0.25 * float(profile_authentic) + 0.10 * float(founder_connection)
    requested_locations = [part.casefold() for part in (intent.location.city, intent.location.state, intent.location.country) if part]
    if requested_locations:
        if any(part in text for part in requested_locations):
            score += 0.15
        else:
            score -= 0.20
    return max(0.0, min(0.72, round(score, 3))), "Deterministic title/snippet heuristic; identity and role remain unconfirmed."
