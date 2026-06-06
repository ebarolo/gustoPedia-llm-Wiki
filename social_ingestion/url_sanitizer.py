from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from social_ingestion.models import Platform


def sanitize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    host = parsed.hostname or ""

    if "youtube.com" in host:
        params = parse_qs(parsed.query)
        v = params.get("v", [None])[0]
        new_query = urlencode({"v": v}) if v else ""
        return urlunparse(parsed._replace(query=new_query))

    # Instagram and all others: strip all query params
    return urlunparse(parsed._replace(query=""))


def detect_platform(url: str) -> Platform:
    if "instagram.com" in url:
        return Platform.INSTAGRAM
    if "youtube.com" in url or "youtu.be" in url:
        return Platform.YOUTUBE
    raise ValueError(f"Unsupported platform for URL: {url}")
