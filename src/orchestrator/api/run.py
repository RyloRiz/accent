from orchestrator.core.context import Context
from orchestrator.runtime.builder import build_app


def main():
    app = build_app()

    context = Context(inputs={
        "transcript": "why can't I see far away",
        "context": {
            "app_name": "Minecraft",
            "window_title": "Minecraft 1.21.1",
        },
    })

    result = app.invoke(context)

    print("\nRESOLVED INTENT:\n", result.state.get("intent_resolver"))
    print("\nHISTORY:\n", result.history)


if __name__ == "__main__":
    main()
