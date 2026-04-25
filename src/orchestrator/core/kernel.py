from typing import Callable, List
from orchestrator.core.context import Context


Middleware = Callable[[Context, Callable], Context]


class Kernel:
    def __init__(self):
        self.middlewares: List[Middleware] = []

    def add_middleware(self, mw: Middleware):
        self.middlewares.append(mw)

    def run(self, stage, context: Context):
        def call_chain(ctx, i=0):
            if i < len(self.middlewares):
                return self.middlewares[i](ctx, lambda c: call_chain(c, i + 1))
            return self._execute_stage(stage, ctx)

        return call_chain(context)

    def _execute_stage(self, stage, context: Context):
        context.metadata["current_stage"] = stage.name

        update = stage.invoke(context)

        # merge update into context
        if "state" in update:
            context.state.update(update["state"])

        if "artifacts" in update:
            context.artifacts.update(update["artifacts"])

        context.history.append({
            "stage": stage.name,
            "update": update
        })

        return context
