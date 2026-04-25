from orchestrator.core.context import Context


def test_context():
    c = Context(inputs={"a": 1})
    assert c.inputs["a"] == 1
