from __future__ import annotations

from langchain_core.tools import BaseTool

from latest_ai_development.tools.custom_tool import search_tool


def get_tools() -> list[BaseTool]:
    """
    Return the list of tools available to the workflow.

    This central registry allows tools to be managed in one place
    and easily attached to LangChain pipelines.
    """

    return [
        search_tool,
    ]
