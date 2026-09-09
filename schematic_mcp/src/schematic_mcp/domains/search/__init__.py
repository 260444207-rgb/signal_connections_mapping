from .tools import register_tools
from .prompts import register_prompts


def register(mcp):
    register_tools(mcp)
    register_prompts(mcp)
