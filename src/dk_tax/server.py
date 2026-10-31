"""MCP layer: thin tool wrappers over the dk_tax logic."""

from mcp.server import MCPServer

server = MCPServer(
    "dk-tax",
    instructions="Danish personal tax figures and calculators. Not tax advice.",
)


@server.tool()
def hello(name: str) -> str:
    """Say hello. A placeholder tool to check that the server is wired up."""
    return f"Hej {name}, dk-tax is running."
