from orchestrator.runtime.orchestrator import Orchestrator
from orchestrator.core.kernel import Kernel
from orchestrator.stages.summarizer import SummarizerStage
from orchestrator.stages.analyzer import AnalyzerStage


def build_app():
    kernel = Kernel()
    orch = Orchestrator(kernel)

    orch.add_stage(SummarizerStage(), "summarizer")
    orch.add_stage(AnalyzerStage(), "analyzer")

    orch.set_entry("summarizer")
    orch.connect("summarizer", "analyzer")

    return orch.compile()