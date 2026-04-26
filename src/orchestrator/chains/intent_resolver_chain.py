"""Intent Resolver chain.

Single multimodal LLM pass: given transcript + apps hint + screenshot,
produce a 'How do I do X in Y' question and an instruction-optimized search
query. Search ALWAYS runs after the LLM call; its output is appended to the
state untouched. The understanding is NEVER altered by the search results —
results are downstream context for the next stage to consume.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from orchestrator.core.llm import get_chat_model


SearchTool = Callable[[str], str]


def _noop_search(query: str) -> str:
    return ""


class _ResolverOutput(BaseModel):
    understanding: str = Field(
        description=(
            "The user's intent phrased as a short, to-the-point question of the "
            "form 'How do I do {XYZ} in {APP}'. {APP} is the application the "
            "user is operating inside; if that app is a web browser, {APP} must "
            "be the website or platform shown in the screenshot (e.g. ChatGPT, "
            "Gmail, GitHub) — never the browser name itself."
        )
    )
    search_query: str = Field(
        description=(
            "Focused web-search query optimized to surface step-by-step "
            "instructions or how-to guides answering the understanding question."
        )
    )


_SYSTEM_PROMPT = (
    "You are the Intent Resolver in a voice-guided UI automation pipeline. "
    "Your job is to convert a vague voice transcript into a precise procedural "
    "question of the form 'How do I do {XYZ} in {APP}'.\n\n"
    "Inputs you receive:\n"
    "- transcript: the user's raw speech (often vague, e.g. 'where's the images').\n"
    "- apps: a list of applications the macOS client detected as running "
    "on-screen. This is a HINT, not ground truth. Multiple apps may be open; "
    "the user is only acting in one of them. Pick the most likely target by "
    "cross-referencing the transcript and the screenshot.\n"
    "- screenshot: an image of the current screen. Use this to identify which "
    "app is actually focused and what the user is looking at.\n\n"
    "Rules for {APP}:\n"
    "1. If the focused app is a desktop app (Xcode, Finder, Slack, etc.), "
    "use its name.\n"
    "2. If the focused app is a web browser (Safari, Chrome, Arc, Firefox, "
    "etc.), DO NOT use the browser name. Identify the website or platform "
    "from the screenshot (ChatGPT, Gmail, GitHub, YouTube, Google Docs, etc.) "
    "and use that as {APP}.\n"
    "3. If the apps list is empty or unhelpful, infer {APP} entirely from the "
    "screenshot.\n\n"
    "Rules for {XYZ}:\n"
    "- Resolve deictic references ('that thing', 'the blue one') using the "
    "screenshot.\n"
    "- Keep it short and procedural — a question a step-by-step tutorial "
    "would answer. NOT a description of UI layout.\n"
    "- Do NOT pick UI elements or click targets — that is a downstream job.\n\n"
    "You must also produce a focused web-search query optimized to retrieve "
    "step-by-step instructions for the question. A query is ALWAYS required.\n\n"
    "If the intent is genuinely ambiguous and cannot be grounded even with "
    "the screenshot, say so plainly in `understanding`."
)

_HUMAN_TEMPLATE = (
    "Transcript: {transcript}\n\n"
    "Detected running apps (hint, not ground truth): {apps}\n"
    "Screenshot attached: {screenshot_available}"
)


def _format_apps(apps: Any) -> str:
    if not apps:
        return "(none detected)"
    if isinstance(apps, str):
        return apps
    try:
        return ", ".join(str(a) for a in apps)
    except TypeError:
        return str(apps)


def _build_human_message(text: str, image: Optional[dict]) -> HumanMessage:
    if image is None:
        return HumanMessage(content=text)
    fmt = (image.get("format") or "png").lower()
    b64 = image.get("data_b64") or ""
    data_url = f"data:image/{fmt};base64,{b64}"
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": data_url},
        ]
    )


class IntentResolverChain:
    def __init__(self, search_tool: Optional[SearchTool] = None, llm: Any = None):
        self._search = search_tool or _noop_search
        base_llm = llm or get_chat_model()
        self._llm = base_llm.with_structured_output(_ResolverOutput)

    def invoke(self, payload: dict) -> dict:
        inputs = payload.get("inputs") or {}
        artifacts = payload.get("artifacts") or {}
        transcript = inputs.get("transcript", "") or ""
        ctx = inputs.get("context") or {}
        images = artifacts.get("images") or []
        screenshot = images[0] if images else None

        human_text = _HUMAN_TEMPLATE.format(
            transcript=transcript,
            apps=_format_apps(ctx.get("apps")),
            screenshot_available="yes" if screenshot else "no",
        )

        result: _ResolverOutput = self._llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            _build_human_message(human_text, screenshot),
        ])

        search_results = self._search(result.search_query) or ""

        return {
            "understanding": result.understanding,
            "search_query": result.search_query,
            "search_results": search_results,
        }


def build_chain(search_tool: Optional[SearchTool] = None) -> IntentResolverChain:
    return IntentResolverChain(search_tool=search_tool)
