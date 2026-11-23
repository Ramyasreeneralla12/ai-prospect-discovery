import re
from urllib.parse import urlsplit, urlunsplit


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    host = parts.netloc.casefold().removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")
    return urlunsplit(("https", host, path, "", ""))


def clean_title(value: str) -> str:
    # Search-engine title decorations are commonly split on these delimiters.
    return re.split(r"\s+[|–—-]\s+", value.strip(), maxsplit=1)[0].strip()
