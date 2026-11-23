import re

from app.schemas import Location, QueryIntent

PLATFORM_DOMAINS = [
    ("linkedin.com/in", "LinkedIn"), ("instagram.com", "Instagram"),
    ("youtube.com/@", "YouTube"), ("x.com", "X"), ("facebook.com", "Facebook"),
    ("threads.net", "Threads"),
]
COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "u.s.a.": "United States",
    "united states": "United States", "united states of america": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "britain": "United Kingdom",
    "great britain": "United Kingdom", "united kingdom": "United Kingdom",
    "uae": "United Arab Emirates", "united arab emirates": "United Arab Emirates", "india": "India",
}
COUNTRY_PATTERN = re.compile(r"(?:\s+in\s+|\s*,\s*|\s+)" + "|".join(
    re.escape(x) for x in sorted(COUNTRY_ALIASES, key=len, reverse=True)
) + r"$", flags=re.I)
PERSON_AUDIENCE = re.compile(r"\b(owners?|founders?|co-founders?|ceos?|managers?|professionals?|creators?|lovers?|enthusiasts?)\b", re.I)
BUSINESS_AUDIENCE = re.compile(r"\b(businesses|companies|agencies|restaurants|startups|firms)\b", re.I)


def deterministic_intent(query: str) -> QueryIntent:
    text = query.strip()
    match = re.search(r"\b(?:in|from|near)\s+(.+)$", text, flags=re.I)
    raw_place = match.group(1).strip(" .,?!") if match else ""
    city = raw_place or None
    country = None
    if raw_place:
        for alias in sorted(COUNTRY_ALIASES, key=len, reverse=True):
            match_country = re.search(r"(?:\s+in\s+|\s*,\s*|\s+)" + re.escape(alias) + r"$", raw_place, re.I)
            if match_country:
                country = COUNTRY_ALIASES[alias]
                city = raw_place[:match_country.start()].strip(" ,") or None
                break
    state = None
    if city and re.fullmatch(r"washington\s+(?:dc|d\.c\.)", city, re.I):
        city, state = "Washington DC", "District of Columbia"

    audience_match = re.search(r"\b(?:in|from|near)\b", text, re.I)
    audience = text[:audience_match.start()].strip(" ,") if audience_match else text
    individual_target = bool(PERSON_AUDIENCE.search(audience))
    business_target = bool(BUSINESS_AUDIENCE.search(audience)) and not individual_target
    target = "business" if business_target else "individual"
    interest = re.sub(r"\b(owners?|founders?|co-founders?|ceos?|managers?|lovers?|enthusiasts?|professionals?)\b", "", audience, flags=re.I).strip() or audience
    keywords = list(dict.fromkeys(w.casefold() for w in re.findall(r"[\w-]+", interest) if len(w) > 2))
    return QueryIntent(interest=interest, audience=audience,
                       location=Location(city=city, state=state, country=country),
                       target_type=target, keywords=keywords)


def deterministic_queries(intent: QueryIntent) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for phrase in (intent.audience, intent.interest, *intent.keywords):
        for word in re.findall(r"[\w'-]+", phrase):
            normalized = word.casefold()
            if normalized not in seen:
                seen.add(normalized)
                words.append(word)
    terms = " ".join(words)
    location = intent.location.display() or ""
    domains = list(PLATFORM_DOMAINS)
    domains[0] = ("linkedin.com/company" if intent.target_type == "business" else "linkedin.com/in", "LinkedIn")
    return [f'site:{domain} "{terms}" {location}'.strip() for domain, _ in domains]


def normalize_intent_location(intent: QueryIntent) -> QueryIntent:
    country = intent.location.country
    if country:
        intent.location.country = COUNTRY_ALIASES.get(country.casefold().strip(), country.strip())
    if intent.location.city and re.fullmatch(r"washington\s+(?:dc|d\.c\.)", intent.location.city, re.I):
        intent.location.city = "Washington DC"
        intent.location.state = intent.location.state or "District of Columbia"
    return intent
