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
- Extend `LangChainStage` (not `Stage` directly — see "Extending Stage directly" below for the rare exception)
- Be constructed with a unique `name` and a chain that conforms to `Runnable`-style `.invoke(payload)`
- Never mutate Context directly
- Never call other stages
- Never control orchestration flow

---

## Output Contract

`LangChainStage.invoke` already produces the standard patch shape:

```python
{
    "state": {
        "<stage_name>": <chain result>
    }
}
```

If a stage needs to also write to artifacts (e.g. an image-generating stage), override `invoke` and merge `{"artifacts": {...}}` into the returned dict.

---

## Chain Input Contract

`LangChainStage.invoke` calls `chain.invoke(payload)` with this exact shape:

```python
{
    "inputs":    context.inputs,      # raw user-supplied inputs
    "state":     context.state,       # accumulated outputs of prior stages
    "artifacts": context.artifacts,   # multimodal slots: text, images, audio, structured
}
```

Your chain's `invoke` MUST accept this shape. Pull what you need from the right slot:
- `payload["inputs"]["transcript"]` — original transcript
- `payload["state"]["<earlier_stage_name>"]` — output from a prior stage
- `payload["artifacts"]["images"]` — list of `{name, format, data_b64, width?, height?}` dicts

---

## Where Code Goes

A new stage requires TWO files:

### 1. LangChain logic
```
src/orchestrator/chains/<name>_chain.py
```

### 2. Stage wrapper
```
src/orchestrator/stages/<name>.py
```

---

## Stage Template

```python
from orchestrator.stages.langchain_stage import LangChainStage
from orchestrator.chains.<name>_chain import build_chain


class MyStage(LangChainStage):
    def __init__(self):
        super().__init__("<stage_name>", build_chain())
```

That's it. No `invoke` override unless the stage writes artifacts.

### Reference example (real stage in this repo)

```python
# src/orchestrator/stages/intent_resolver.py
class IntentResolverStage(LangChainStage):
    def __init__(self, search_tool: Optional[SearchTool] = None):
        super().__init__("intent_resolver", build_chain(search_tool=search_tool))
```

---

## Chain Template

```python
class MyChain:
    def __init__(self):
        self._llm_chain = (
            ChatPromptTemplate.from_messages([...])
            | get_chat_model().with_structured_output(MyOutputModel)
        )

    def invoke(self, payload: dict) -> dict:
        inputs = payload.get("inputs") or {}
        state = payload.get("state") or {}
        artifacts = payload.get("artifacts") or {}

        # 1. Extract what you need
        # 2. Run LLM chain(s)
        # 3. Normalize and return a plain dict
        result = self._llm_chain.invoke({...})
        return result.model_dump()


def build_chain() -> MyChain:
    return MyChain()
```

---

## Registration

```python
from orchestrator.stages.my_stage import MyStage

orch.add_stage(MyStage(), "my_stage")
orch.connect("previous_stage", "my_stage")
```

---

## Mental Model

You are NOT building chains of LLM calls.

You ARE building:
> A graph of state transformations where LLMs are internal tools.

`LangChainStage` is the boundary that:
- Reads from Context (inputs / state / artifacts)
- Hands a normalized payload to your chain
- Writes the chain's result back into `state[<stage_name>]`

Your chain owns the LLM logic; the stage owns the Context glue.

---

## What NOT to do

```python
# Wrong — bypasses LangChainStage glue and skips kernel patching
class MyStage(Stage):
    def invoke(self, context):
        return llm.invoke(...)
```

```python
# Wrong — chains MUST accept the {inputs, state, artifacts} payload, not flat kwargs
def invoke(self, transcript, context):
    ...
```

---

## Extending Stage directly (rare)

Only override `Stage` directly if you need behavior `LangChainStage` cannot express — e.g. a stage that does no LLM work, or one that fans out to multiple chains and merges. Even then, prefer composing chains over a custom stage.

---

## Summary

A stage is a thin wrapper around a chain. Extend `LangChainStage`, pass a name and a chain, and let the kernel + LangGraph do the orchestration.
