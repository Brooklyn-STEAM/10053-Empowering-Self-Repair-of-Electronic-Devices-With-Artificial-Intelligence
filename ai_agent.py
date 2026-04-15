import langchain
from dotenv import load_dotenv
from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from tools import search_tool, wiki_tool, save_tool

load_dotenv()


class RepairGuide(BaseModel):
    topic: str
    summary: str
    sources: list[str]
    tools_used: list[str]


llm = ChatAnthropic(
    model="claude-3-5-haiku-20240620",
    temperature=0.7
)

parser = PydanticOutputParser(pydantic_object=RepairGuide)

prompt = ChatPromptTemplate.from_messages(
    [
        ("system",
         """

         You are a helpful assistant that provides repair guides for electronic devices.
         Answer the user query and use neccessary tools to find the answer. Always provide a summary of the answer, sources used, and tools used in the process.
         Wrapp the output in this format and provide no other text\n{format_instructions}

         """
         ),
        ("placeholder", "{chat_history}"),
        ("human", "{query}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
).partial(format_instructions=parser.get_format_instructions())


tools = [search_tool, wiki_tool, save_tool]

agent = create_tool_calling_agent(
    llm=llm,
    prompt=prompt,
    tools=tools,
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True
)


def run_agent(query: str):
    """
    Flask-safe function wrapper for your AI agent
    """
    raw_response = agent_executor.invoke({"query": query})

    try:
        structured_response = parser.parse(
            raw_response.get("output")
        )
        return structured_response.model_dump()

    except Exception as e:
        return {
            "error": str(e),
            "raw_output": raw_response
        }