import asyncio
import logging
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

# Cấu hình logging để xem chi tiết
logging.basicConfig(level=logging.INFO)

async def run_client():
    server_url = "http://localhost:8001/mcp"
    try:
        async with streamablehttp_client(server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize session
                await session.initialize()
                logging.info("Session initialized successfully.")

                # Gọi tool (fix access result)
                try:
                    tool_result = await session.call_tool("add_numbers", {"a": 5, "b": 10})
                    logging.info(f"Tool Result: {tool_result}")  # Print full result để debug
                    # Access đúng: tool_result.content[0].text nếu là text
                    if tool_result.content:
                        logging.info(f"Tool Content: {tool_result.content[0].text}")  # Kỳ vọng: "15"
                except Exception as e:
                    logging.error(f"Error calling tool: {e}")

                # Đọc resource (fix access content)
                try:
                    content, mime_type = await session.read_resource("greeting://Alice")
                    logging.info(f"Resource Content: {content}, MIME: {mime_type}")  # Kỳ vọng: "Hello, Alice!", text/plain
                except Exception as e:
                    logging.error(f"Error reading resource: {e}")
                    
                # sử dụng list_tools để kiểm tra các tool có sẵn
                try:
                    tools = await session.list_tools()
                    logging.info(f"Available Tools: {tools}")
                    for tool in tools:
                        logging.info(f"Tool Name: {tool.name}, Description: {tool.description}")
                except Exception as e:
                    logging.error(f"Error listing tools: {e}")
                    
                # sử dụng list_resources để kiểm tra các resource có sẵn
                try:
                    resources = await session.list_resources()
                    logging.info(f"Available Resources: {resources}")
                    for resource in resources:
                        logging.info(f"Resource : {resource}")
                except Exception as e:
                    logging.error(f"Error listing resources: {e}")

    except Exception as e:
        logging.error(f"Error during client run: {e}")

if __name__ == "__main__":
    asyncio.run(run_client())