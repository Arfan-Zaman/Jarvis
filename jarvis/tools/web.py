"""Internet tools: search and read the public web (permission level `web_read`).

Search uses services that permit automated use without a key: Wikipedia's
search API and DuckDuckGo's instant-answer API. Full web search comes from
the owner's own SearXNG (free, self-hosted, no key or quota) when
`JARVIS_SEARXNG_URL` is set, and from Brave Search when `JARVIS_BRAVE_API_KEY` is set.
DuckDuckGo's HTML results page is deliberately NOT used: it challenges
automated clients, and JARVIS does not try to get around bot detection.

`web.fetch` reads one public page. It refuses non-http(s) URLs and any address
on this machine or a private network, including after redirects, so a web page
cannot trick JARVIS into reading local services.

Requests identify JARVIS with a generic User-Agent and carry no personal data.
"""

from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from ..common import JarvisError, ValidationError
from ..safety import ActionCategory
from .registry import Tool, ToolRegistry

USER_AGENT = "JARVIS/0.1 (personal assistant; +local)"
TIMEOUT = 15
MAX_DOWNLOAD = 2_000_000
WIKIPEDIA_URL = "https://en.wikipedia.org/w/rest.php/v1/search/page"
WIKIPEDIA_PAGE = "https://en.wikipedia.org/wiki/"
DDG_URL = "https://api.duckduckgo.com/"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class WebError(JarvisError):
    """A web request could not be completed."""


# --- address safety -----------------------------------------------------------
def is_public_host(host: str) -> bool:
    """True only if every address the host resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)


def check_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValidationError("url is required")
    url = url.strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValidationError("only http and https web addresses can be read")
    if not is_public_host(parts.hostname):
        raise ValidationError(f"{parts.hostname} is not a public internet address, so JARVIS will not read it")
    return url


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)                      # a redirect may not lead somewhere private
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirects)


def _get(url: str, headers: dict | None = None, opener=None) -> tuple[bytes, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with (opener or _opener).open(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_DOWNLOAD + 1)
            return body[:MAX_DOWNLOAD], response.headers.get("Content-Type", ""), response.geturl()
    except urllib.error.HTTPError as exc:
        exc.close()
        raise WebError(f"{urllib.parse.urlsplit(url).hostname} answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WebError(f"could not reach {urllib.parse.urlsplit(url).hostname}: {exc}") from exc


def _json(url: str, headers: dict | None = None) -> dict:
    body, _, _ = _get(url, {"Accept": "application/json", **(headers or {})},
                      opener=urllib.request.build_opener())    # fixed, trusted API endpoints
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError as exc:
        raise WebError(f"{urllib.parse.urlsplit(url).hostname} returned something that is not JSON") from exc


def _plain(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", value or "")).split())


# --- page text extraction -------------------------------------------------------
class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe", "template"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


# --- search providers -------------------------------------------------------------
def _wikipedia(query: str, limit: int) -> list[dict]:
    data = _json(f"{WIKIPEDIA_URL}?{urllib.parse.urlencode({'q': query, 'limit': limit})}")
    return [{"title": page.get("title", ""), "url": WIKIPEDIA_PAGE + urllib.parse.quote(page.get("key", ""), safe="()_,:'"),
             "snippet": _plain(page.get("excerpt") or page.get("description") or ""), "source": "wikipedia"}
            for page in data.get("pages", [])]


def _duckduckgo(query: str, limit: int) -> list[dict]:
    data = _json(f"{DDG_URL}?{urllib.parse.urlencode({'q': query, 'format': 'json', 'no_html': 1, 'skip_disambig': 1})}")
    results = []
    if data.get("Answer"):
        results.append({"title": "Instant answer", "url": data.get("AbstractURL") or "https://duckduckgo.com",
                        "snippet": _plain(str(data["Answer"])), "source": "duckduckgo"})
    if data.get("AbstractText"):
        results.append({"title": data.get("Heading") or query, "url": data.get("AbstractURL", ""),
                        "snippet": _plain(data["AbstractText"]), "source": "duckduckgo"})
    for topic in data.get("RelatedTopics", []):
        if isinstance(topic, dict) and topic.get("FirstURL") and topic.get("Text"):
            results.append({"title": _plain(topic["Text"]).split(" - ")[0][:120], "url": topic["FirstURL"],
                            "snippet": _plain(topic["Text"]), "source": "duckduckgo"})
    return results[:limit]


def _brave(query: str, limit: int, key: str = "") -> list[dict]:
    data = _json(f"{BRAVE_URL}?{urllib.parse.urlencode({'q': query, 'count': limit})}",
                 {"X-Subscription-Token": key})
    return [{"title": item.get("title", ""), "url": item.get("url", ""),
             "snippet": _plain(item.get("description", "")), "source": "brave"}
            for item in (data.get("web") or {}).get("results", [])]


def _searxng(query: str, limit: int, base: str = "") -> list[dict]:
    """The owner's own SearXNG: it asks several search engines and merges the results."""
    data = _json(f"{base}/search?{urllib.parse.urlencode({'q': query, 'format': 'json', 'language': 'en'})}")
    return [{"title": item.get("title", ""), "url": item.get("url", ""),
             "snippet": _plain(item.get("content", "")), "source": "searxng"}
            for item in data.get("results", [])[:limit] if item.get("url", "").startswith(("http://", "https://"))]


def providers(key: str = "", searxng: str = "") -> list[tuple[str, callable]]:
    chosen = [("searxng", lambda query, limit: _searxng(query, limit, searxng))] if searxng else []
    chosen += [("brave", lambda query, limit: _brave(query, limit, key))] if key else []
    return chosen + [("wikipedia", _wikipedia), ("duckduckgo", _duckduckgo)]


# --- tool handlers ------------------------------------------------------------------
def web_search(app, inputs, actor):
    query = inputs["query"].strip()
    if not query:
        raise ValidationError("query is required")
    limit = max(1, min(inputs.get("limit", 5), 10))
    results, used, errors, seen = [], [], [], set()
    key = app.config.brave_api_key or os.environ.get("JARVIS_BRAVE_API_KEY", "").strip()
    searxng = getattr(app.config, "searxng_url", "") or os.environ.get("JARVIS_SEARXNG_URL", "").strip().rstrip("/")
    if os.environ.get("JARVIS_BROWSER", "local") not in ("off", "0") and "browser.search" in app.tools.names():
        try:                                  # the whole web, through JARVIS's own Chrome (free)
            from .browser import browser_search
            found = browser_search(app, {"query": query, "limit": limit}, actor)
            return {"query": query, "results": found["results"], "searched": [f"browser ({found['engine']})"],
                    "errors": [], "note": None}
        except JarvisError as exc:
            errors.append(f"browser: {exc}")
    for name, search in providers(key, searxng):
        try:
            found = search(query, limit)
        except JarvisError as exc:
            errors.append(f"{name}: {exc}")
            continue
        used.append(name)
        for item in found:
            if item["url"] and item["url"] not in seen:
                seen.add(item["url"])
                results.append(item)
    if not used:
        raise WebError("every search service failed: " + "; ".join(errors))
    return {"query": query, "results": results[:limit * 2], "searched": used, "errors": errors,
            "note": None if any(p in ("brave", "searxng") for p in used) else
            "Searched Wikipedia and DuckDuckGo instant answers only (no full web search configured)."}


def web_fetch(app, inputs, actor):
    url = check_url(inputs["url"])
    limit = max(500, min(inputs.get("max_chars", 8000), 20000))
    body, content_type, final_url = _get(url)
    charset = re.search(r"charset=[\"']?([\w-]+)", content_type)
    try:
        text = body.decode(charset.group(1) if charset else "utf-8", "replace")
    except LookupError:                 # a charset Python does not know (e.g. "utf8mb4"): read it as UTF-8
        text = body.decode("utf-8", "replace")
    kind = content_type.split(";")[0].strip().lower()
    if kind in ("text/html", "application/xhtml+xml", ""):
        parser = _TextExtractor()
        parser.feed(text)
        title, text = " ".join(parser.title.split()), parser.text()
    elif kind.startswith("text/") or kind == "application/json":
        title = ""
    else:
        raise WebError(f"that address returns {kind}, which JARVIS cannot read as text")
    focused = False
    if inputs.get("focus") and len(text) > limit:
        text, focused = _focus(text, inputs["focus"], limit), True
    return {"url": final_url, "title": title, "text": text[:limit], "truncated": len(text) > limit,
            "characters": len(text), "focused_on": inputs.get("focus") if focused else None}


def _focus(text: str, focus: str, limit: int) -> str:
    """Keep the lines of a long page that mention the focus words, in page order.

    A line repeated on the page (menus, banners, share buttons) is kept once, and a
    line too long for the space left is skipped rather than ending the search."""
    words = {w for w in re.findall(r"[a-z0-9]{3,}", focus.lower())}
    lines = text.splitlines()
    scored = sorted(range(len(lines)), key=lambda i: -sum(w in lines[i].lower() for w in words))
    keep, seen, size = set(), set(), 0
    for i in scored:
        if not any(w in lines[i].lower() for w in words):
            break                                   # sorted: no later line mentions them either
        if lines[i] in seen or size + len(lines[i]) > limit:
            continue
        seen.add(lines[i])
        keep.add(i)
        size += len(lines[i]) + 1
    return "\n".join(lines[i] for i in sorted(keep)) or text


def register_web(registry: ToolRegistry) -> None:
    web = ActionCategory.WEB_READ
    registry.register(Tool(
        "web.search", "Search the internet for current or factual information; returns titles, links and snippets.",
        web, web_search, {"query": {"type": "string", "description": "What to search for.", "required": True},
                          "limit": {"type": "integer", "description": "How many results (1 to 10)."}}))
    registry.register(Tool(
        "web.fetch", "Read the text of one public web page.", web, web_fetch,
        {"url": {"type": "string", "description": "The http(s) address to read.", "required": True},
         "max_chars": {"type": "integer", "description": "Most characters of text to return."},
         "focus": {"type": "string", "description": "Key words of the question; on long pages, return the parts that mention them."}}))
