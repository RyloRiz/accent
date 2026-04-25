from typing import Callable
from orchestrator.core.context import Context

Middleware = Callable[[Context, Callable], Context]
