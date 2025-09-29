from mcp.server.fastmcp import FastMCP

# Tạo MCP Server với Streamable HTTP
mcp = FastMCP(
    name="SimpleMCP",
    stateless_http=True,
    # debug=True,
    host="127.0.0.1",
    port=8001,
)


# Resource: Lời chào
@mcp.resource("greeting://{name}/{age}")
def get_greeting(name: str, age: int) -> str:
    return f"Hello, {name}! You are {age} years old."


# Tool: Cộng hai số
@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
