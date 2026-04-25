from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser

from orchestrator.stages.langchain_stage import LangChainStage


def build_chain():
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Summarize the input clearly."),
        ("human", "{inputs[text]}")
    ])

    model = ChatOpenAI(model="gpt-4o-mini")

    return prompt | model | StrOutputParser()


class SummarizerStage(LangChainStage):
    def __init__(self):
        super().__init__("summarizer", build_chain())
