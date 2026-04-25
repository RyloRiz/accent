from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class Context(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)
    state: Dict[str, Any] = Field(default_factory=dict)

    artifacts: Dict[str, Any] = Field(default_factory=lambda: {
        "text": None,
        "images": None,
        "audio": None,
        "structured": None,
    })

    history: List[Dict[str, Any]] = Field(default_factory=list)

    metadata: Dict[str, Any] = Field(default_factory=lambda: {
        "current_stage": None,
    })
