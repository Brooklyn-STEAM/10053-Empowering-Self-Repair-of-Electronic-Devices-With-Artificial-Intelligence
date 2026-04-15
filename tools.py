from langchain.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun, WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from datetime import datetime


search = DuckDuckGoSearchRun()
wiki_api = WikipediaAPIWrapper()
wiki = WikipediaQueryRun(api_wrapper=wiki_api)


@tool
def search_tool(query: str) -> str:
    """Search the web for information."""
    return search.run(query)


@tool
def wiki_tool(query: str) -> str:
    """Search Wikipedia for information."""
    return wiki.run(query)


@tool
def save_tool(content: str) -> str:
    """Save research results to a local text file."""
    filename = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    return f"Saved research to {filename}"