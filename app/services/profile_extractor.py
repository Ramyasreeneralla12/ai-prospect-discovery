
import re

from app.schemas import Prospect, QueryIntent, SearchResult, SocialLink
from app.services.query_service import COUNTRY_ALIASES
from app.utils.validators import (
    is_valid_profile_url,
    platform_for_url,
    public_contacts,
)


ARTICLE_TERMS = re.compile(
    r"\b(article|blog|news|report|guide|top\s+\d+|event|meetup|"
    r"hashtag|content|post|funding|expansion)\b",
    re.I,
)

FOUNDER_RELATION = re.compile(
    r"\b(?:co[- ]?founder|founder)\b.{0,100}"
    r"(?:\b(?:of|at)\b|@)|"
    r"\bfounded\b.{0,100}\b(?:startup|company|business|venture)\b",
    re.I,
)

NAME_WORD = re.compile(r"^[A-Z][\w.'’-]*$")

NON_PERSON_TERMS = {
    "founder", "founders", "startup", "startups", "london",
    "future", "network", "community", "meetup", "hub",
    "group", "company", "agency", "restaurant", "official",
    "sports", "football", "cricket",
}

FOUNDER_QUERY = re.compile(
    r"\b(founders?|co-founders?)\b", re.I
)

OWNER_QUERY = re.compile(
    r"\b(owner|owners|proprietor|proprietors)\b", re.I
)

OWNER_EVIDENCE = re.compile(
    r"\b(owner|co-owner|business owner|restaurant owner|"
    r"agency owner|proprietor|owns|founded|founder|"
    r"co-founder|managing partner)\b",
    re.I,
)

AUDIENCE_INDICATORS = re.compile(
    r"\b(fan|fans|supporter|supporters|enthusiast|"
    r"enthusiasts|lover|lovers|follower|followers|"
    r"community|player|players|coach|coaches)\b",
    re.I,
)

PLATFORM_INTERESTS = {
    "cricket": re.compile(
        r"\b(cricket|batsman|batter|bowler|wicketkeeper|"
        r"ipl|test cricket|t20)\b",
        re.I,
    ),
    "football": re.compile(
        r"\b(football|soccer|footballer|fifa|premier league)\b",
        re.I,
    ),
}
LOCATION_ALIASES = {
    "washington dc": [
        "washington dc",
        "washington, dc",
        "washington d.c.",
        "washington, d.c.",
        "district of columbia",
        "washington district of columbia",
    ],
    "district of columbia": [
        "district of columbia",
        "washington dc",
        "washington, dc",
        "washington d.c.",
        "washington, d.c.",
    ],
}

def classify_result(
    result: SearchResult,
    target_type: str | None = None,
) -> str:
    """Classify public search records and reject editorial content."""
    url = str(result.url)
    platform = platform_for_url(url)

    if platform and is_valid_profile_url(url, target_type):
        path = result.url.path.strip("/").split("/")

        if platform == "LinkedIn" and path[0].casefold() == "company":
            return "business_profile"

        if target_type == "individual":
            return "individual_profile"

        if target_type == "business":
            return "business_profile"

        return "profile"

    path = result.url.path.casefold()
    title = result.title.casefold()

    if any(
        term in path
        for term in (
            "/posts/", "/activity/", "/recent-activity/",
            "/status/", "/reel/", "/p/", "/feed/",
        )
    ):
        return "social_post"

    if "hashtag" in title or re.search(r"#\w+", result.title):
        return "hashtag"

    if "event" in title or "meetup" in title:
        return "event"

    if ARTICLE_TERMS.search(result.title) or any(
        term in path
        for term in ("/article", "/blog/", "/news/", "/pulse/")
    ):
        return "article"

    return "general"

def _supported_text(
    value: str | None,
    evidence: str,
) -> bool:
    if not value:
        return False

    def normalize(text: str) -> str:
        text = text.casefold()
        text = re.sub(r"[.,]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    normalized_value = normalize(value)
    normalized_evidence = normalize(evidence)

    # Direct evidence match
    if normalized_value in normalized_evidence:
        return True

    # Equivalent location names
    aliases = LOCATION_ALIASES.get(normalized_value, [])

    for alias in aliases:
        if normalize(alias) in normalized_evidence:
            return True

    # Existing country aliases
    return any(
        normalize(alias) in normalized_evidence
        for alias, full in COUNTRY_ALIASES.items()
        if full.casefold() == value.casefold().strip()
    )


def evidence_location(
    raw: object,
    evidence: str,
) -> str | None:
    if isinstance(raw, str):
        return raw if _supported_text(raw, evidence) else None

    if not isinstance(raw, dict):
        return None

    supported = []

    for part in ("city", "state", "country"):
        value = raw.get(part)

        if isinstance(value, str) and _supported_text(
            value.strip(), evidence
        ):
            if part == "country":
                normalized = COUNTRY_ALIASES.get(
                    value.casefold(), value.strip()
                )
                supported.append(normalized)
            else:
                supported.append(value.strip())

    return ", ".join(supported) or None


def _audience_evidence(
    audience: str,
    evidence: str,
) -> str | None:
    """Find evidence that connects the result to the requested audience."""
    audience_lower = audience.casefold()
    evidence_lower = evidence.casefold()

    if FOUNDER_QUERY.search(audience):
        match = FOUNDER_RELATION.search(evidence)
        return match.group(0) if match else None

    if OWNER_QUERY.search(audience):
        match = OWNER_EVIDENCE.search(evidence)
        return match.group(0) if match else None

    for interest, pattern in PLATFORM_INTERESTS.items():
        if interest in audience_lower:
            interest_match = pattern.search(evidence)

            if not interest_match:
                return None

            audience_match = AUDIENCE_INDICATORS.search(evidence)

            if not audience_match:
                return None

            return (
                interest_match.group(0)
                + " "
                + audience_match.group(0)
            )

    # For other audiences, require meaningful query terms
    # instead of accepting one generic matching word.
    ignored = {
        "the", "and", "for", "with", "from",
        "people", "person", "individual",
    }

    terms = [
        word.casefold()
        for word in re.findall(r"[\w-]+", audience)
        if len(word) > 3 and word.casefold() not in ignored
    ]

    matched = [
        term for term in dict.fromkeys(terms)
        if re.search(rf"\b{re.escape(term)}\b", evidence_lower)
    ]

    if len(set(terms)) >= 2 and len(matched) >= 2:
        return " ".join(matched)

    if len(set(terms)) == 1 and matched:
        return matched[0]

    return None


def deterministic_assessment(
    result: SearchResult,
    intent: QueryIntent,
) -> dict:
    """Extract fields supported by a public profile result."""
    target_type = intent.target_type

    if classify_result(result, target_type) not in {
        "individual_profile",
        "business_profile",
        "profile",
    }:
        return {}

    evidence = f"{result.title}\n{result.snippet}"

    name = _name_from_result(result, target_type)

    if not name or name.casefold() not in evidence.casefold():
        return {}

    if target_type == "individual" and not _looks_like_person_name(name):
        return {}

    if target_type == "business" and (
        ARTICLE_TERMS.search(name) or name.startswith("#")
    ):
        return {}

    role_evidence = _audience_evidence(
        intent.audience,
        evidence,
    )

    if not role_evidence:
        return {}

    raw_location = {}

    for part in ("city", "state", "country"):
        expected = getattr(intent.location, part)

        if expected and _supported_text(expected, evidence):
            raw_location[part] = expected

    return {
        "entity_type": target_type,
        "is_profile": True,
        "name": name,
        "role_evidence": role_evidence,
        "location": raw_location,
        "score": 0.65,
        "rationale": (
            "Deterministic extraction using public profile, "
            "audience, and location evidence."
        ),
    }


def _name_from_result(
    result: SearchResult,
    target_type: str,
) -> str | None:
    """Extract a name actually present in the title or snippet."""
    title_prefix = re.split(
        r"\s+(?:\||·|[-–—])\s+",
        result.title,
        maxsplit=1,
    )[0].strip(" ,-")

    if target_type == "individual":
        if _looks_like_person_name(title_prefix):
            return title_prefix

        match = re.match(
            r"\s*([A-Z][\w.'’-]+"
            r"(?:\s+[A-Z][\w.'’-]+){1,4})"
            r"\s+(?:is\b|,|[-–—])",
            result.snippet,
        )

        if match and _looks_like_person_name(match.group(1)):
            return match.group(1)

        return None

    if (
        title_prefix
        and title_prefix.casefold()
        in f"{result.title}\n{result.snippet}".casefold()
    ):
        return title_prefix

    return None


def _founder_role_evidence(evidence: str) -> str | None:
    clauses = re.split(r"(?<=[.!?])\s+|[\r\n]+", evidence)

    for clause in clauses:
        if FOUNDER_RELATION.search(clause):
            return clause.strip()

    return None


def candidate_rejection_reason(
    result: SearchResult,
    assessed: dict | None,
    target_type: str,
    audience: str,
    intent: QueryIntent | None = None,
) -> str | None:
    """Explain why a candidate lacks sufficient supporting evidence."""
    url = str(result.url)
    platform = platform_for_url(url)

    if not platform:
        return "URL host is not a supported public profile platform"

    if not is_valid_profile_url(url, target_type):
        return (
            f"URL path is not an accepted "
            f"{target_type} profile path for {platform}"
        )

    kind = classify_result(result, target_type)

    if kind not in {
        "individual_profile",
        "business_profile",
        "profile",
    }:
        return f"Search result classified as {kind}, not a profile"

    evidence = f"{result.title}\n{result.snippet}"
    assessment = assessed or {}

    name = assessment.get("name")

    if not assessment:
        name = _name_from_result(result, target_type)

    if not isinstance(name, str) or not name.strip():
        return "No supported person or company name was extracted"

    if name.casefold() not in evidence.casefold():
        return "Extracted name is not present in the source evidence"

    if target_type == "individual" and not _looks_like_person_name(name.strip()):
        return "Source does not support a plausible individual name"

    if target_type == "business" and (
        ARTICLE_TERMS.search(name) or name.startswith("#")
    ):
        return "Extracted business name resembles editorial content"

    if assessment:
        if assessment.get("entity_type") != target_type:
            return f"Candidate type is not supported as {target_type}"

        if assessment.get("is_profile") is not True:
            return "Result is not confirmed as a profile"

    role_evidence = _audience_evidence(audience, evidence)

    if not role_evidence:
        return (
            "Public source does not provide sufficient evidence "
            "for the requested audience or role"
        )

    if intent is not None and intent.location.city:
        if not _supported_text(intent.location.city, evidence):
            return (
                f"Public source does not confirm the requested city: "
                f"{intent.location.city}"
            )

    if intent is not None and intent.location.state:
        if not _supported_text(intent.location.state, evidence):
            return (
                f"Public source does not confirm the requested state: "
                f"{intent.location.state}"
            )

    return None


def _looks_like_person_name(value: str) -> bool:
    words = value.split()

    return (
        2 <= len(words) <= 5
        and all(
            NAME_WORD.match(word.strip(".,"))
            for word in words
        )
        and not any(
            word.casefold().strip(".,") in NON_PERSON_TERMS
            for word in words
        )
    )


def extract_candidate(
    result: SearchResult,
    assessed: dict | None = None,
    target_type: str = "individual",
    audience: str = "",
    intent: QueryIntent | None = None,
) -> tuple[Prospect, list[str]] | None:
    assessment = assessed or {}

    rejection = candidate_rejection_reason(
        result,
        assessment,
        target_type,
        audience,
        intent,
    )

    if rejection:
        return None

    url = str(result.url)
    platform = platform_for_url(url)
    name = str(assessment["name"]).strip()

    evidence_text = f"{result.title}\n{result.snippet}"

    location = evidence_location(
        assessment.get("location"),
        evidence_text,
    )

    links = [
        SocialLink(
            platform=platform,
            link=url,
        )
    ]

    for kind, link in public_contacts(evidence_text):
        links.append(
            SocialLink(
                platform=kind,
                link=link,
            )
        )

    return (
        Prospect(
            name=name,
            location=location,
            social_link=links,
        ),
        [url],
    )
