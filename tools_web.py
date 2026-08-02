"""Веб-инструменты для локального агента (поиск и чтение страниц)."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        return "\n".join(self._chunks)


_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "kubernetes.default",
    "kubernetes.default.svc",
}


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _host_blocked(host: str) -> str | None:
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return "Ошибка: пустой хост в URL"
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        return "Ошибка: запрещён доступ к локальным адресам"
    # IP в URL без DNS
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(host):
            return "Ошибка: запрещён доступ к private/loopback IP"
        return None
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return f"Ошибка: не удалось разрешить хост ({exc})"
    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            return f"Ошибка: хост резолвится в запрещённый адрес ({ip})"
    return None


def _url_blocked(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "Ошибка: URL должен начинаться с http:// или https://"
    if parsed.username or parsed.password:
        return "Ошибка: URL с credentials запрещён"
    return _host_blocked(parsed.hostname or "")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Проверяем цель каждого редиректа (SSRF)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        err = _url_blocked(newurl)
        if err:
            raise urllib.error.HTTPError(newurl, 403, err, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def web_search(query: str, max_results: int = 5) -> str:
    """Поиск в интернете через DuckDuckGo."""
    query = (query or "").strip()
    if not query:
        return "Ошибка: пустой поисковый запрос."

    try:
        from ddgs import DDGS
    except ImportError:
        return "Ошибка: пакет ddgs не установлен. Выполните: pip install ddgs"

    try:
        results = list(DDGS().text(query, max_results=max_results))
    except Exception as exc:  # noqa: BLE001
        return f"Ошибка поиска: {exc}"

    if not results:
        return f"По запросу «{query}» ничего не найдено."

    lines = [f"Результаты поиска по «{query}»:"]
    for i, item in enumerate(results, 1):
        title = item.get("title") or "(без названия)"
        href = item.get("href") or ""
        body = item.get("body") or ""
        lines.append(f"{i}. {title}\n   URL: {href}\n   {body}")
    return "\n".join(lines)


def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Скачать страницу и извлечь текст (без private/loopback — защита от SSRF)."""
    url = (url or "").strip()
    blocked = _url_blocked(url)
    if blocked:
        return blocked

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
        method="GET",
    )
    # Читаем ограниченный объём байт (HTML раздут относительно текста)
    max_bytes = max(max_chars * 8, 64_000)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    try:
        with opener.open(req, timeout=20) as resp:
            final_url = resp.geturl() or url
            again = _url_blocked(final_url)
            if again:
                return again
            ctype = (resp.headers.get_content_type() or "").lower()
            if ctype and not any(
                x in ctype for x in ("text/", "html", "xml", "json", "javascript")
            ):
                return f"Пропуск {url}: нетекстовый Content-Type ({ctype})"
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(max_bytes)
    except urllib.error.HTTPError as exc:
        return f"HTTP ошибка {exc.code} при загрузке {url}"
    except Exception as exc:  # noqa: BLE001
        return f"Не удалось загрузить {url}: {exc}"

    try:
        html = raw.decode(charset, errors="replace")
    except LookupError:
        html = raw.decode("utf-8", errors="replace")

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        text = re.sub(r"<[^>]+>", " ", html)
    else:
        text = parser.text()

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[обрезано]"
    if not text:
        return f"Страница {url} загружена, но текст извлечь не удалось."
    return f"Содержимое {url}:\n{text}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Искать актуальную информацию в интернете. "
                "Используй для новостей, погоды, цен, фактов после даты обучения, "
                "проверки свежих данных."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Короткий поисковый запрос на русском или английском",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Открыть конкретный URL и прочитать текст страницы. "
                "Используй после поиска, когда нужен полный текст источника."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Полный URL страницы (https://...)",
                    }
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_IMPL = {
    "web_search": lambda args: web_search(args.get("query", "")),
    "fetch_url": lambda args: fetch_url(args.get("url", "")),
}
