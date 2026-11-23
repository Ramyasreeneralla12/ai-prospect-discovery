from app.schemas import Prospect
from app.utils.normalizers import normalize_name, normalize_url


def deduplicate(prospects: list[tuple[Prospect, list[str]]]) -> list[tuple[Prospect, list[str]]]:
    """Merge exact URL duplicates and exact-name profiles with compatible locations only."""
    result: list[tuple[Prospect, list[str]]] = []
    by_url: dict[str, int] = {}
    by_identity: dict[tuple[str, str], int] = {}
    for prospect, evidence in prospects:
        profile_urls = [normalize_url(link.link) for link in prospect.social_link if link.platform not in {"Email", "Phone"}]
        location = normalize_name(prospect.location or "")
        match_index = next((by_url[url] for url in profile_urls if url in by_url), None)
        identity_key = (normalize_name(prospect.name), location)
        if match_index is None and identity_key[0] and location:
            # A name-only match is insufficient: cross-profile merges also require the same known location.
            match_index = next((idx for (name, loc), idx in by_identity.items()
                                if name == identity_key[0] and loc == location), None)
        if match_index is None:
            idx = len(result)
            result.append((prospect.model_copy(deep=True), list(evidence)))
            for url in profile_urls:
                by_url[url] = idx
            by_identity[identity_key] = idx
            continue
        existing, old_evidence = result[match_index]
        seen = {(link.platform, normalize_url(link.link) if link.link.startswith("http") else link.link) for link in existing.social_link}
        for link in prospect.social_link:
            key = (link.platform, normalize_url(link.link) if link.link.startswith("http") else link.link)
            if key not in seen:
                existing.social_link.append(link)
                seen.add(key)
        if not existing.location:
            existing.location = prospect.location
        result[match_index] = (existing, list(dict.fromkeys(old_evidence + evidence)))
        for url in profile_urls:
            by_url[url] = match_index
        by_identity[identity_key] = match_index
    return result
