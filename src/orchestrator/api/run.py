from orchestrator.runtime.orchestrator import build_app
from orchestrator.core.context import Context


def main():
    app = build_app()

    context = Context(inputs={
        "text": "LangGraph enables powerful orchestration of LLM pipelines."
    })

    result = app.invoke(context)

    print("\nFINAL STATE:\n", result.state)
    print("\nHISTORY:\n", result.history)


if __name__ == "__main__":
    main()
