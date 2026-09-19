from __future__ import annotations

from langchain.tools import tool


@tool
def search_tool(query: str) -> str:
    """
    Example search tool.

    This tool demonstrates how external capabilities can be exposed
    to LangChain pipelines. In a real system, this could call an API,
    a search engine, or an internal knowledge service.
    """

    # Placeholder implementation
    # Replace with real API or search integration
    return f"Search results for query: {query}"
