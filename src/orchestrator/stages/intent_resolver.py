"""Intent Resolver stage — first step of the voice-guided UI pipeline.

Receives a transcript, lightweight screen context, and an optional screenshot
artifact, then runs the resolver chain to produce an `understanding` (and
optional `search_results`) under `state["intent_resolver"]`.
"""

from __future__ import annotations

from typing import Optional

from orchestrator.chains.intent_resolver_chain import SearchTool, build_chain
from orchestrator.stages.langchain_stage import LangChainStage


class IntentResolverStage(LangChainStage):
    def __init__(self, search_tool: Optional[SearchTool] = None):
        super().__init__("intent_resolver", build_chain(search_tool=search_tool))
