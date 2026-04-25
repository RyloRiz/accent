# How to Create Stages in This Orchestration System

This explains how to build stages in the orchestration framework.

A stage is the core compute unit of the system.

---

# Core Idea

A stage is NOT:
- a LangChain chain
- a standalone function
- an agent
- a pipeline

A stage IS:

> A deterministic transformation of Context → Context update

---

# Stage Contract

Every stage must follow this contract:

```python
def invoke(context) -> dict:
    return {
        "state": {...},
        "artifacts": {...}
    }
```

Rules:
- Must accept a Context
- Must return a partial update dict
- Must NOT mutate global state
- Must NOT call other stages

---

# How to Create a New Stage

## Step 1 — Create a file

Put your stage here:

```src/orchestrator/stages/my_new_stage.py```

---

## Step 2 — Define purpose

Example:
Extract structured tasks from input text

---

## Step 3 — Build internal LangChain logic

> Goes in: `src/orchestrator/chains/task_chain.py`

Stages can use LangChain internally.

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser


def build_chain():
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Extract a list of tasks from the input."),
        ("human", "{text}")
    ])

    model = ChatOpenAI(model="gpt-4o-mini")

    return prompt | model | StrOutputParser()
```

---

## Step 4 — Wrap it as a Stage

> Goes in: `src/orchestrator/stages/task_extractor.py`

```python
from orchestrator.core.context import Context


class TaskExtractorStage:
    name = "task_extractor"

    def __init__(self):
        self.chain = build_chain()

    def invoke(self, context: Context):
        text = context.inputs.get("text", "")

        result = self.chain.invoke({
            "text": text
        })

        return {
            "state": {
                "tasks": result
            }
        }
```

---

## Step 5 — Register the stage

> Goes in: `src/orchestrator/runtime/builder.py`

In your builder:

```python
from orchestrator.stages.my_new_stage import TaskExtractorStage

# def build_app():
    # kernel = Kernel()
    # orch = Orchestrator(kernel)

    # orch.add_stage(SummarizerStage(), "summarizer")
    # orch.add_stage(AnalyzerStage(), "analyzer")
    orch.add_stage(TaskExtractorStage(), "task_extractor")

    # orch.set_entry("summarizer")

    # orch.connect("summarizer", "analyzer")
    orch.connect("analyzer", "task_extractor")

    return orch.compile()
```

---

# Mental Model

You are NOT building chains of LLM calls.

You ARE building:

> A graph of state transformations where LLMs are internal tools

---

# What NOT to do

Bad:

```python
def stage():
    return llm.invoke(...)
```

Good:

Context → updated Context → next stage

---

# Standard Stage Structure

Every stage should follow:

Input mapping
↓
LLM / tool / logic
↓
Output normalization
↓
Context patch

---

# Example Pipeline

You now have:

- Summarizer → compress input
- Analyzer → extract insights
- Task Extractor → structured output

Each stage:
- independent
- composable
- testable

---

# Why This Works

- clear boundaries
- shared context
- graph orchestration (LangGraph)
- LLMs encapsulated inside stages

---

# Future Extensions

- plugin stage registry
- typed outputs (schemas)
- streaming execution
- tool-using agents
- multimodal pipelines
- distributed execution