from pydantic import BaseModel


class MCPToolOutputSchema(BaseModel):
    success: bool = True
    error: str | None = None
