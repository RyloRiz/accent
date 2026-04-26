"""Intent Resolver stage — first step of the voice-guided UI pipeline.

Reads `transcript` and `context` from `Context.inputs`, runs the resolver chain,
and writes the resolved intent (`understanding` + optional `search_results`)
into `state["intent_resolver"]`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from orchestrator.chains.intent_resolver_chain import SearchTool, build_chain
from orchestrator.core.context import Context
from orchestrator.core.stage import Stage


class IntentResolverStage(Stage):
    name = "intent_resolver"

    def __init__(self, search_tool: Optional[SearchTool] = None):
        self.chain = build_chain(search_tool=search_tool)

    def invoke(self, context: Context) -> Dict[str, Any]:
        result = self.chain.invoke({
            "transcript": context.inputs.get("transcript", ""),
            "context": context.inputs.get("context", {}),
        })

        return {
            "state": {self.name: result},
        }
