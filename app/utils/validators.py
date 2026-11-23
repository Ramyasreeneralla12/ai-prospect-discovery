
import re
from urllib.parse import urlsplit

import phonenumbers
from email_validator import EmailNotValidError, validate_email


PLATFORM_HOSTS = {
    "LinkedIn": {"linkedin.com"},
    "Instagram": {"instagram.com"},
    "YouTube": {"youtube.com"},
    "X": {"x.com", "twitter.com"},
    "Facebook": {"facebook.com"},
    "Threads": {"threads.net"},
    "WhatsApp": {"wa.me", "whatsapp.com"},
}

BLOCKED_PATHS = {
    "search", "explore", "about", "watch", "reels",
    "hashtag", "hashtagged", "intent", "home", "feed",
    "posts", "pulse", "activity", "events", "groups",
    "company-feed", "marketplace", "gaming",
}

RESERVED_INSTAGRAM_PATHS = {
    "accounts", "developer", "directory", "stories",
    "p", "reel", "reels", "explore", "about",
}

RESERVED_X_PATHS = {
    "i", "intent", "search", "explore", "home",
    "notifications", "messages", "settings",
}


def platform_for_url(url: str) -> str | None:
    try:
        host = (
            urlsplit(url).hostname or ""
        ).casefold().removeprefix("www.")
    except ValueError:
        return None

    for platform, hosts in PLATFORM_HOSTS.items():
        if any(
            host == allowed or host.endswith("." + allowed)
            for allowed in hosts
        ):
            return platform

    return None


def is_valid_profile_url(
    url: str,
    target_type: str | None = None,
) -> bool:
    try:
        parts = urlsplit(url)
        platform = platform_for_url(url)

        if (
            not platform
            or parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            return False

        host = parts.hostname.casefold().removeprefix("www.")
        segments = [
            segment.casefold()
            for segment in parts.path.strip("/").split("/")
            if segment
        ]

        if not segments:
            return False

        first = segments[0]

        if first in BLOCKED_PATHS:
            return False

        if platform == "LinkedIn":
            is_person = (
                len(segments) >= 2
                and first in {"in", "pub"}
                and bool(segments[1])
            )
            is_company = (
                len(segments) >= 2
                and first == "company"
                and bool(segments[1])
            )

            if target_type == "individual":
                return is_person

            if target_type == "business":
                return is_company

            return is_person or is_company

        if platform == "YouTube":
            return (
                host == "youtube.com"
                and (
                    (
                        len(segments) == 1
                        and first.startswith("@")
                        and len(first) > 1
                    )
                    or (
                        len(segments) == 2
                        and first in {"channel", "c", "user"}
                        and bool(segments[1])
                    )
                )
            )

        if platform == "Instagram":
            return (
                len(segments) == 1
                and first not in RESERVED_INSTAGRAM_PATHS
                and bool(first)
            )

        if platform == "X":
            return (
                len(segments) == 1
                and first not in RESERVED_X_PATHS
                and bool(first)
            )

        if platform == "Threads":
            return (
                len(segments) == 1
                and first.startswith("@")
                and len(first) > 1
            )

        if platform == "Facebook":
            is_username = (
                len(segments) == 1
                and first not in BLOCKED_PATHS
                and first != "profile.php"
            )
            is_page = (
                len(segments) == 3
                and first == "pages"
            )
            is_numeric_profile = (
                first == "profile.php"
                and bool(parts.query)
                and bool(
                    re.search(r"(?:^|&)id=\d+", parts.query)
                )
            )

            return is_username or is_page or is_numeric_profile

        # WhatsApp contact URLs are not prospect profile URLs.
        return False

    except (ValueError, TypeError):
        return False


def valid_email(value: str) -> str | None:
    try:
        return validate_email(
            value,
            check_deliverability=False,
        ).normalized
    except EmailNotValidError:
        return None


def valid_phone(
    value: str,
    region: str | None = None,
) -> str | None:
    try:
        parsed = phonenumbers.parse(value, region)

        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed,
                phonenumbers.PhoneNumberFormat.E164,
            )

        return None

    except phonenumbers.NumberParseException:
        return None


def public_contacts(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    # Extract and validate public email addresses.
    email_pattern = (
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
    )

    for raw in re.findall(email_pattern, text, flags=re.I):
        email = valid_email(raw)

        if email:
            found.append(("Email", f"mailto:{email}"))

    # Extract public WhatsApp contact links.
    whatsapp_pattern = (
        r"(?:https?://)?"
        r"(?:wa\.me/\d+|api\.whatsapp\.com/send\?phone=\d+)"
    )

    for raw in re.findall(whatsapp_pattern, text, flags=re.I):
        url = (
            raw if raw.startswith("http")
            else f"https://{raw}"
        )
        found.append(("WhatsApp", url))

    # Accept explicitly international phone numbers only.
    phone_pattern = r"(?<!\w)\+\d[\d\s().-]{7,}\d(?!\w)"

    for raw in re.findall(phone_pattern, text):
        phone = valid_phone(raw)

        if phone:
            found.append(("Phone", f"tel:{phone}"))

    return list(dict.fromkeys(found))
