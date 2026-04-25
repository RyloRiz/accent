from orchestrator.core.kernel import Kernel
from orchestrator.core.stage import Stage
from orchestrator.core.context import Context


class DummyStage(Stage):
    name = "dummy"

    def invoke(self, context):
        return {"state": {"x": 1}}


def test_kernel():
    k = Kernel()
    s = DummyStage()

    ctx = Context(inputs={})
    out = k.run(s, ctx)

    assert out.state["x"] == 1
