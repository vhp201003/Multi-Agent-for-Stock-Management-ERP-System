import json
from string import Template

ORCHESTRATOR_PROMPT = """
You are the Orchestrator. Your ONLY job is to analyze user queries and create task execution plans. NEVER answer queries directly.

Available Agents:
$agent_descriptions

Task Creation Rules:
- Identify required agents based on query.
- Break down into specific tasks with dependencies.
- Use agent_type as keys in task_dependency dict.

Output Requirements:
- Return ONLY a valid JSON object (no text, no markdown, no explanations).
- The JSON must match this exact schema: $schema
- Do not include any text before or after the JSON.
- If no tasks needed, return {"agents_needed": [], "task_dependency": {}}
- If error, return {"error": "description"}

Example:
{"agents_needed": ["inventory"], "task_dependency": {"inventory": [{"task_id": "inventory_1", "agent_type": "inventory", "sub_query": "Check stock for LAPTOP-001", "dependencies": []}]}}
"""


def build_orchestrator_prompt(schema_model) -> str:
    try:
        with open("config/agents.json", "r") as f:
            agents_info = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        agents_info = {}

    agents_desc = []
    for name, info in agents_info.items():
        if name != "orchestrator":  # Skip self-reference
            desc = info.get("description", "No description")
            caps = info.get("capabilities", [])
            caps_str = ", ".join(caps) if caps else "general tasks"
            agents_desc.append(f"- **{name}**: {desc} ({caps_str})")

    agent_descriptions = (
        "\n".join(agents_desc) if agents_desc else "No agents available"
    )

    try:
        if hasattr(schema_model, "model_json_schema"):
            schema = schema_model.model_json_schema()
            schema = _minimize_schema_for_prompt(schema)
        else:
            schema = schema_model
    except Exception:
        schema = {
            "type": "object",
            "properties": {
                "agents_needed": {"type": "array", "items": {"type": "string"}},
                "task_dependency": {"type": "object"},
            },
            "required": ["agents_needed", "task_dependency"],
        }

    schema_str = json.dumps(
        schema, indent=1, separators=(",", ":")
    )  # Compact formatting

    prompt_template = Template(ORCHESTRATOR_PROMPT)

    return prompt_template.safe_substitute(
        agent_descriptions=agent_descriptions, schema=schema_str
    )


def _minimize_schema_for_prompt(schema: dict) -> dict:
    essential_keys = ["type", "items", "properties", "required", "$ref"]

    def clean_dict(d: dict) -> dict:
        return {k: v for k, v in d.items() if k in essential_keys}

    minimal = clean_dict(schema)

    if "properties" in minimal:
        minimal["properties"] = {
            k: clean_dict(v) if isinstance(v, dict) else v
            for k, v in minimal["properties"].items()
        }

    if "$defs" in schema:
        minimal["$defs"] = {
            name: clean_dict(def_schema) for name, def_schema in schema["$defs"].items()
        }

    return minimal
