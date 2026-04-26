"""Live web search via LangChain's DuckDuckGo wrapper.

Returns a single text blob — search results are LLM context, not structured
data, so downstream stages just need something to splice into a prompt.
Snippets are scrubbed of common date/timestamp noise before joining so the
prompt stays focused on procedural content.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

logger = logging.getLogger(__name__)


_DATE_PATTERNS = [
    re.compile(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b", re.IGNORECASE),
    re.compile(r"\b(?:Updated|Posted|Published|Last\s+modified)\s*[:\-]?\s*", re.IGNORECASE),
]

_TRIM_CHARS = " -·•|,;\u2013\u2014"


def _clean_snippet(text: str) -> str:
    if not text:
        return ""
    for pat in _DATE_PATTERNS:
        text = pat.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(_TRIM_CHARS)


def _format(results: list[dict]) -> str:
    lines: list[str] = []
    for r in results:
        title = (r.get("title") or "").strip()
        snippet = _clean_snippet(r.get("snippet") or "")
        if not title and not snippet:
            continue
        if title and snippet:
            lines.append(f"- {title}: {snippet}")
        else:
            lines.append(f"- {title or snippet}")
    return "\n".join(lines)


def default_search_tool(max_results: int = 5) -> Callable[[str], str]:
    wrapper = DuckDuckGoSearchAPIWrapper()

    def search(query: str) -> str:
        if not query or not query.strip():
            return ""
        try:
            results = wrapper.results(query, max_results=max_results) or []
        except Exception as exc:
            logger.warning("ddg search failed for %r: %s", query, exc)
            return ""
        return _format(results)

    return search
