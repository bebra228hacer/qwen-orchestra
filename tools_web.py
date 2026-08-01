"""Веб-инструменты для локального агента (поиск и чтение страниц)."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser


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
    """Скачать страницу и извлечь текст."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "Ошибка: URL должен начинаться с http:// или https://"

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
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
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
