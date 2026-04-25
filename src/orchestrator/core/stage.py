from abc import ABC, abstractmethod
from typing import Any, Dict
from orchestrator.core.context import Context


class Stage(ABC):
    name: str

    @abstractmethod
    def invoke(self, context: Context) -> Dict[str, Any]:
        """
        Must return a partial update to Context
        """
        pass
