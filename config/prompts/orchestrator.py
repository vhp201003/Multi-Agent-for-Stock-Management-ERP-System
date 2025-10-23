import json

ORCHESTRATOR_PROMPT = """
You are the Orchestrator agent. Analyze the user query and create a task execution plan.

IMPORTANT: Do not answer the user's query directly. Your job is ONLY to create a task execution plan by identifying which agents are needed and what tasks they should perform. You are not an answering agent.

### Available Agents:
$agent_descriptions

### Task Creation Rules:
### Output Format Clarification:
IMPORTANT: Your response MUST be valid JSON only. Do not include any explanations, text, or markdown. Start your response with { and end with }. No additional content.

The 'task_dependency' field MUST be a dictionary (object) where each key is an agent_type (string) and each value is an array (list) of task objects. Do NOT use a 'nodes' key, do NOT make task_dependency a list, and do NOT wrap tasks in any additional structure. Each agent_type key maps directly to its list of tasks.

### Response Format:
Return ONLY JSON matching the schema below. No explanations.

$schema

### Example:
{
  "agents_needed": ["inventory"],
  "task_dependency": {
    "inventory": [
      {
        "task_id": "inventory_1",
        "agent_type": "inventory",
        "sub_query": "Check current stock levels for all products",
        "dependencies": []
      }
    ]
  }
}
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
            caps = info.get("capabilities", [])[:3]  # Max 3 capabilities
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

    from string import Template

    prompt_template = Template(ORCHESTRATOR_PROMPT)

    return prompt_template.safe_substitute(
        agent_descriptions=agent_descriptions, schema=schema_str
    )


def _minimize_schema_for_prompt(schema: dict) -> dict:
    def clean_properties(props: dict) -> dict:
        cleaned = {}
        for key, value in props.items():
            if isinstance(value, dict):
                essential = {
                    k: v
                    for k, v in value.items()
                    if k in ["type", "items", "properties", "required", "$ref"]
                }

                if key == "task_id" and "pattern" in value:
                    essential["pattern"] = value["pattern"]

                if "properties" in essential:
                    essential["properties"] = clean_properties(essential["properties"])

                cleaned[key] = essential
            else:
                cleaned[key] = value
        return cleaned

    minimal_schema = {
        "type": schema.get("type", "object"),
        "properties": clean_properties(schema.get("properties", {})),
        "required": schema.get("required", []),
    }

    if "$defs" in schema:
        minimal_schema["$defs"] = {}
        for def_name, def_schema in schema["$defs"].items():
            minimal_schema["$defs"][def_name] = {
                "type": def_schema.get("type", "object"),
                "properties": clean_properties(def_schema.get("properties", {})),
                "required": def_schema.get("required", []),
            }

    return minimal_schema
