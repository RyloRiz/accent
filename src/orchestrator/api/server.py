"""FastAPI server exposing the orchestration pipeline.

The client (SwiftUI menu bar app) captures voice locally — Apple's `Speech`
framework produces the transcript — then POSTs `{transcript, context}` to
`/resolve`. The server runs the LangGraph pipeline and returns the full
accumulated `state` plus the per-stage `history`.

Bind defaults to localhost; override with ACCENT_HOST / ACCENT_PORT.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from orchestrator.core.context import Context
from orchestrator.runtime.builder import build_app


class ScreenContext(BaseModel):
    apps: List[str] = Field(
        default_factory=list,
        description=(
            "All apps the macOS client detects as running on-screen. Treated "
            "as a hint, not ground truth — the resolver picks the most likely "
            "target by cross-referencing the transcript and screenshot."
        ),
        examples=[["Safari", "Xcode", "Slack"]],
    )


class ScreenshotInput(BaseModel):
    """Base64-encoded screenshot of the current screen.

    `data_b64` is the raw base64 payload (no `data:image/...;base64,` prefix).
    """

    format: Literal["png", "jpeg"] = "png"
    data_b64: str
    width: Optional[int] = None
    height: Optional[int] = None


class ResolveRequest(BaseModel):
    transcript: str = Field(..., description="Client-side voice transcript.")
    context: ScreenContext = Field(default_factory=ScreenContext)
    screenshot: Optional[ScreenshotInput] = None


class IntentResolverOutput(BaseModel):
    """Shape of `state.intent_resolver` returned by the pipeline."""

    understanding: str = Field(
        ...,
        description=(
            "User intent as a 'How do I do {XYZ} in {APP}' question. {APP} is "
            "the website/platform when the focused app is a browser."
        ),
    )
    search_query: str = Field(..., description="Instruction-optimized web-search query.")
    search_results: str = Field(
        ...,
        description="Cleaned text blob of top web-search results; passed downstream untouched.",
    )


class ResolveState(BaseModel):
    intent_resolver: Optional[IntentResolverOutput] = None


class ResolveResponse(BaseModel):
    state: ResolveState
    history: List[Dict[str, Any]]


app = FastAPI(title="Accent Orchestrator")
_pipeline = build_app()


def _attr_or_key(result: Any, name: str, default: Any) -> Any:
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/resolve", response_model=ResolveResponse)
def resolve(req: ResolveRequest) -> ResolveResponse:
    artifacts: Dict[str, Any] = {
        "text": None,
        "images": None,
        "audio": None,
        "structured": None,
    }
    if req.screenshot is not None:
        artifacts["images"] = [{
            "name": "screenshot",
            "format": req.screenshot.format,
            "data_b64": req.screenshot.data_b64,
            "width": req.screenshot.width,
            "height": req.screenshot.height,
        }]

    ctx = Context(
        inputs={
            "transcript": req.transcript,
            "context": req.context.model_dump(exclude_none=True),
        },
        artifacts=artifacts,
    )
    result = _pipeline.invoke(ctx)
    return ResolveResponse(
        state=ResolveState.model_validate(_attr_or_key(result, "state", {}) or {}),
        history=_attr_or_key(result, "history", []),
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("ACCENT_HOST", "127.0.0.1")
    port = int(os.environ.get("ACCENT_PORT", "8765"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
