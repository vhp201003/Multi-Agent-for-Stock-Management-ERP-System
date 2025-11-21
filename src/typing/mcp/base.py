from pydantic import BaseModel


class MCPToolOutputSchema(BaseModel):
    success: bool = True
