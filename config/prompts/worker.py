from string import Template

WORKER_AGENT_PROMPT = """
You are $agent_type in Multi Agent System: 
$agent_description

## Available Tools (Actions):
$tools_description

## Available Resources (Read-Only Data):
$resources_description

## Task:
Parse sub-query and return JSON with tool calls/resource URIs.

## Response Format:
1. Tool: {"tool_calls": [{"tool_name": "exact_name", "parameters": {...}}]}
2. Resource: {"read_resource": ["exact_uri"]}
3. Combined: {"tool_calls": [...], "read_resource": [...]}
4. Error: {"error": "reason"}

## Rules:
- tool_name/URIs MUST match exactly (case-sensitive)
- Include all required parameters from inputSchema
- Match parameter types (string/int/bool)
- Never invent names/parameters not in schema

## Example for tools/resource usage: 
$examples
"""

def build_worker_agent_prompt(
    agent_type: str,
    agent_description: str,
    tools: list,
    resources: list,
    examples: str,
) -> str:
    """Build prompt for WorkerAgent with agent info and MCP tools/resources.

    Args:
        agent_type (str): Name of the agent.
        agent_description (str): Description of the agent's role.
        tools (list): List of Tool objects from session.list_tools().
        resources (list): List of Resource objects from session.list_resources().

    Returns:
        str: Formatted prompt with dynamic content substituted.

    Note:
        tools/resources are Pydantic objects, will be dumped to dicts internally.
    """
    # Convert Pydantic objects to dicts and format as JSON
    import json

    tools_dicts = [t.model_dump() if hasattr(t, "model_dump") else t for t in tools]
    resources_dicts = [
        r.model_dump() if hasattr(r, "model_dump") else r for r in resources
    ]

    # Simple JSON dump (readable but verbose)
    tools_description = json.dumps(tools_dicts, indent=2) if tools_dicts else "(none)"
    resources_description = (
        json.dumps(resources_dicts, indent=2) if resources_dicts else "(none)"
    )

    return Template(WORKER_AGENT_PROMPT).safe_substitute(
        agent_type=agent_type,
        agent_description=agent_description,
        tools_description=tools_description,
        resources_description=resources_description,
        examples=examples,
    )
