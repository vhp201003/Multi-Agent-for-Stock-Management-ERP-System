from typing import List

from pydantic import BaseModel

from .base_schema import BaseSchema


class Query(BaseModel):
    agent_name: str
    sub_query: list[str]


class Dependency(BaseModel):
    agent_name: str
    dependencies: List[str]


class OrchestratorSchema(BaseSchema):
    agent_needed: List[str]
    sub_queries: List[Query]
    dependencies: List[Dependency]