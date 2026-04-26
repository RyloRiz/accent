from orchestrator.runtime.orchestrator import Orchestrator
from orchestrator.core.kernel import Kernel
from orchestrator.stages.intent_resolver import IntentResolverStage
from orchestrator.tools.search import default_search_tool


def build_app():
    kernel = Kernel()
    orch = Orchestrator(kernel)

    orch.add_stage(IntentResolverStage(search_tool=default_search_tool()), "intent_resolver")
    orch.set_entry("intent_resolver")

    return orch.compile()
