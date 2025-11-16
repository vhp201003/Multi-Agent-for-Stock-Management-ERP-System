from pydantic import BaseModel


class MCPToolOutputSchema(BaseModel):
    items: dict
    summary: dict
    filters_applied: dict
