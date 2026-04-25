from orchestrator.core.stage import Stage
from orchestrator.core.context import Context


class LangChainStage(Stage):
    def __init__(self, name: str, chain):
        self.name = name
        self.chain = chain  # LCEL Runnable (pipe-based chain)

    def invoke(self, context: Context):
        input_data = {
            "inputs": context.inputs,
            "state": context.state,
            "artifacts": context.artifacts,
        }

        result = self.chain.invoke(input_data)

        update = {
            "state": {
                self.name: result
            }
        }

        return update
