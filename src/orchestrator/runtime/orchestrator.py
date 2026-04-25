from langgraph.graph import StateGraph
from orchestrator.core.context import Context


class Orchestrator:
    def __init__(self, kernel):
        self.kernel = kernel
        self.graph = StateGraph(Context)
        self.stages = {}

    def add_stage(self, stage, name: str):
        self.stages[name] = stage
        self.graph.add_node(name, lambda ctx: self.kernel.run(stage, ctx))

    def connect(self, from_stage: str, to_stage: str):
        self.graph.add_edge(from_stage, to_stage)

    def set_entry(self, stage: str):
        self.graph.set_entry_point(stage)

    def compile(self):
        return self.graph.compile()
