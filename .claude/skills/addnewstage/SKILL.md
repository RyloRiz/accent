---
name: addnewstage
description: Create a new orchestration stage in a LangGraph + LangChain based orchestration system
---

# Skill: Add New Orchestrator Stage

## Purpose
This skill defines how to create a new stage in a Python orchestration system built on:
- LangChain (LCEL chains)
- LangGraph (graph execution)
- A shared Context object
- A Kernel that executes stages

A stage is a deterministic transformation:
Context → Context update (dict patch)

---

## Core Rule

A stage MUST:
- Accept a Context object
- Return a dict with optional keys:
  - "state"
  - "artifacts"
- Never mutate Context directly
- Never call other stages
- Never control orchestration flow

---

## Output Contract

Every stage returns:

```python
{
    "state": {
        "key": "value"
    },
    "artifacts": {
        "key": "value"
    }
}
```

---

## Where Code Goes

A new stage requires TWO files:

### 1. LangChain logic
```src/orchestrator/chains/<name>_chain.py```

### 2. Stage wrapper
```src/orchestrator/stages/<name>.py```

---

## Stage Template

```python
from orchestrator.core.context import Context
from orchestrator.chains.<name>_chain import build_chain


class MyStage:
    name = "<stage_name>"

    def __init__(self):
        self.chain = build_chain()

    def invoke(self, context: Context):
        result = self.chain.invoke({
            "text": context.inputs.get("text", "")
        })

        return {
            "state": {
                "<key>": result
            }
        }
```

---

## Registration

```python
from orchestrator.stages.my_stage import MyStage

orch.add_stage(MyStage(), "my_stage")
```

```python
orch.connect("previous_stage", "my_stage")
```

---

## Mental Model

You are NOT building chains of LLM calls.

You ARE building:
> A graph of state transformations where LLMs are internal tools

---

## What NOT to do

```python
def invoke(self, context):
    return llm.invoke(...)
```

---

## Correct Pattern

1. Extract from Context
2. Run chain
3. Normalize output
4. Return patch

---

## Summary

A stage is a pure transformation unit in a LangGraph orchestration system using LangChain internally.