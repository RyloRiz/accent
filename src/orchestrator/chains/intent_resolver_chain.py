"""Intent Resolver chain.

Two-pass disambiguation: a structured draft pass decides whether a web search
is needed; if so, results are folded into a refinement pass. Search is injected
as a callable so the chain runs offline by default.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from orchestrator.core.llm import get_chat_model


class SearchResult(BaseModel):
    title: str
    snippet: str
    url: str


class _ResolverDraft(BaseModel):
    understanding: str = Field(
        description="Concrete one-or-two sentence statement of the user's intent in the current app."
    )
    needs_search: bool = Field(
        description="True iff resolving this intent requires external/domain knowledge."
    )
    search_query: Optional[str] = Field(
        default=None,
        description="Focused web-search query iff needs_search is True; null otherwise.",
    )


class _ResolverFinal(BaseModel):
    understanding: str = Field(
        description="Final concrete intent statement, refined using search results."
    )


class SearchTool(Protocol):
    def __call__(self, query: str) -> list[dict]: ...


def _noop_search(query: str) -> list[dict]:
    return []


_DRAFT_SYSTEM = (
    "You are the Intent Resolver in a voice-guided UI automation pipeline. "
    "Given a raw voice transcript and lightweight screen context, produce a "
    "concrete, detailed natural-language statement of what the user wants to "
    "accomplish. Do NOT pick UI elements or click targets — that is a downstream "
    "job. Resolve deictic references ('that thing', 'the blue one') using the "
    "provided context whenever possible. Always qualify the understanding with "
    "the application context.\n\n"
    "Decide whether a web search is needed. Search ONLY when the transcript "
    "references a concept, setting, feature, or error that requires "
    "external/domain knowledge to interpret confidently. Do NOT search for "
    "self-evident UI commands like 'click submit' or 'open settings'. When "
    "search is needed, provide a focused query.\n\n"
    "If the intent is genuinely ambiguous and cannot be grounded even with "
    "context, say so plainly in `understanding`."
)

_DRAFT_HUMAN = (
    "Transcript: {transcript}\n\n"
    "Context:\n"
    "- app_name: {app_name}\n"
    "- window_title: {window_title}\n"
    "- url: {url}\n"
    "- active_element: {active_element}"
)

_FINAL_SYSTEM = (
    "You are refining the Intent Resolver's understanding after a web search. "
    "Use the search results to ground the understanding more concretely. Keep "
    "it to one or two sentences. Do not invent UI navigation paths you are not "
    "certain about."
)

_FINAL_HUMAN = (
    "Transcript: {transcript}\n\n"
    "Context:\n"
    "- app_name: {app_name}\n"
    "- window_title: {window_title}\n"
    "- url: {url}\n"
    "- active_element: {active_element}\n\n"
    "Initial understanding: {initial_understanding}\n\n"
    "Search results:\n{search_results}"
)


def _format_search_results(results: list[dict]) -> str:
    if not results:
        return "(no results)"
    return "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('url', '')})" for r in results
    )


class IntentResolverChain:
    def __init__(self, search_tool: Optional[SearchTool] = None, llm: Any = None):
        self._search = search_tool or _noop_search
        base_llm = llm or get_chat_model()
        self._draft_chain = (
            ChatPromptTemplate.from_messages([("system", _DRAFT_SYSTEM), ("human", _DRAFT_HUMAN)])
            | base_llm.with_structured_output(_ResolverDraft)
        )
        self._final_chain = (
            ChatPromptTemplate.from_messages([("system", _FINAL_SYSTEM), ("human", _FINAL_HUMAN)])
            | base_llm.with_structured_output(_ResolverFinal)
        )

    def invoke(self, payload: dict) -> dict:
        transcript = payload.get("transcript", "") or ""
        ctx = payload.get("context", {}) or {}
        prompt_vars = {
            "transcript": transcript,
            "app_name": ctx.get("app_name", ""),
            "window_title": ctx.get("window_title", ""),
            "url": ctx.get("url") or "(not available)",
            "active_element": ctx.get("active_element") or "(not available)",
        }

        draft: _ResolverDraft = self._draft_chain.invoke(prompt_vars)

        if not draft.needs_search or not draft.search_query:
            return {"understanding": draft.understanding}

        raw = self._search(draft.search_query) or []
        search_results = [SearchResult(**r).model_dump() for r in raw[:3]]

        refined: _ResolverFinal = self._final_chain.invoke({
            **prompt_vars,
            "initial_understanding": draft.understanding,
            "search_results": _format_search_results(search_results),
        })

        out: dict = {"understanding": refined.understanding}
        if search_results:
            out["search_results"] = search_results
        return out


def build_chain(search_tool: Optional[SearchTool] = None) -> IntentResolverChain:
    return IntentResolverChain(search_tool=search_tool)
