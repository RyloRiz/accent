from pydantic import BaseModel


class StageOutput(BaseModel):
    state: dict = {}
    artifacts: dict = {}
