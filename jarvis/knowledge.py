"""Optional, sourced encyclopedia lookup without changing the local AI provider.

Only an explicitly requested topic is sent to English Wikipedia. This module
does not browse arbitrary links, execute article text, or require an API key.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request


API_URL = "https://en.wikipedia.org/w/api.php"
TIMEOUT = 8
JSON_MAX_BYTES = 256 * 1024
QUERY_MAX_CHARS = 300
SUMMARY_MAX_CHARS = 1400
USER_AGENT = (
    "JarvisDesktop/1.3 (personal desktop assistant; "
    "https://github.com/xavierpring1-svg/SAY-CHEESE-PIZZA)"
)


def _allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "en.wikipedia.org"
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
        )
    except (TypeError, ValueError):
        return False


class _WikipediaRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not _allowed_url(new_url):
            raise RuntimeError("Wikipedia redirected to an unexpected server. Try again later.")
        return super().redirect_request(request, response, code, message, headers, new_url)


def _open(request, timeout):
    # Keep the platform's proxy and normal HTTPS certificate validation.
    return urllib.request.build_opener(_WikipediaRedirects()).open(request, timeout=timeout)


def _request_json(params: dict) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    if not _allowed_url(url):
        raise RuntimeError("The encyclopedia endpoint is unavailable.")
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with _open(request, timeout=TIMEOUT) as response:
            if not _allowed_url(response.geturl()):
                raise RuntimeError("Wikipedia responded from an unexpected server. Try again later.")
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    too_large = int(length) < 0 or int(length) > JSON_MAX_BYTES
                except (ValueError, TypeError):
                    raise RuntimeError("Wikipedia returned an invalid response. Try again later.")
                if too_large:
                    raise RuntimeError("Wikipedia returned too much data. Try a more specific topic.")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise RuntimeError("Wikipedia returned an invalid response. Try again later.")
            content = response.read(JSON_MAX_BYTES + 1)
            if len(content) > JSON_MAX_BYTES:
                raise RuntimeError("Wikipedia returned too much data. Try a more specific topic.")
        data = json.loads(content.decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise RuntimeError(
            "I couldn't reach Wikipedia. Check your internet connection and try again."
        ) from error
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise RuntimeError("Wikipedia returned an invalid response. Try again later.") from error
    if not isinstance(data, dict) or "error" in data:
        raise RuntimeError("Wikipedia couldn't complete that lookup. Try a more specific topic.")
    return data


def _clean(value: str) -> str:
    # Extracts are plain text; remove non-printing characters before displaying
    # or speaking network content. Never treat the result as an instruction.
    return re.sub(r"\s+", " ", "".join(c for c in value if c.isprintable() or c.isspace())).strip()


def _topic(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("Tell me a topic to look up.")
    if (not query.strip() or len(query) > QUERY_MAX_CHARS
            or any(not c.isprintable() for c in query)):
        raise ValueError("Use a topic of 1 to 300 characters on one line.")
    return query.strip()


def _page(query: str) -> dict | None:
    data = _request_json({
        # MediaWiki uses a pipe as the normal multi-value separator. Prefix a
        # unit separator when the literal topic includes one, so it is still
        # a single title rather than an unintended list of unrelated pages.
        "action": "query", "titles": "\x1f" + query if "|" in query else query, "redirects": "1",
        "prop": "extracts|pageprops", "exintro": "1", "explaintext": "1",
        "exsentences": "3", "ppprop": "disambiguation",
    })
    section = data.get("query")
    pages = section.get("pages") if isinstance(section, dict) else None
    if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
        raise RuntimeError("Wikipedia returned an incomplete response. Try again later.")
    page = pages[0]
    if "missing" in page or "invalid" in page:
        return None
    return page


def _search(query: str) -> list[str]:
    data = _request_json({
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": "3", "srnamespace": "0", "srprop": "",
    })
    section = data.get("query")
    results = section.get("search") if isinstance(section, dict) else None
    if not isinstance(results, list):
        raise RuntimeError("Wikipedia returned an incomplete response. Try again later.")
    titles = []
    for result in results:
        title = result.get("title") if isinstance(result, dict) else None
        if isinstance(title, str) and title.strip() and len(title) <= QUERY_MAX_CHARS:
            titles.append(title)
    return titles


def lookup(query: str) -> str:
    """Return a short Wikipedia extract with its title and HTTPS source URL.

    Exact topics resolve first. Search fallbacks are labelled as the closest
    encyclopedia match, and ambiguous or absent topics never become invented
    answers. Raises ValueError for invalid input and RuntimeError when online
    lookup fails. General local conversation remains available independently.
    """
    topic = _topic(query)
    page = _page(topic)
    approximate = page is None
    if page is None:
        titles = _search(topic)
        if not titles:
            return f'I couldn\'t find an encyclopedia article for "{topic}". Try a more specific topic.'
        page = _page(titles[0])
        if page is None:
            return f'I couldn\'t find a readable encyclopedia article for "{topic}". Try another topic.'
    title = page.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > QUERY_MAX_CHARS:
        raise RuntimeError("Wikipedia returned an incomplete response. Try again later.")
    title = _clean(title)
    if not title:
        raise RuntimeError("Wikipedia returned an incomplete response. Try again later.")
    source = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="()")
    props = page.get("pageprops", {})
    if isinstance(props, dict) and "disambiguation" in props:
        return (
            f'"{title}" has several meanings. Tell me which one you mean or use a more specific topic. '
            f"Source: {source}"
        )
    extract = page.get("extract")
    if not isinstance(extract, str) or not _clean(extract):
        return f"I found {title}, but no short encyclopedia summary is available. Source: {source}"
    extract = _clean(extract)
    if len(extract) > SUMMARY_MAX_CHARS:
        extract = extract[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    label = "Closest encyclopedia match: " if approximate else ""
    return f"{label}{title}. {extract}\nSource: {source}"
