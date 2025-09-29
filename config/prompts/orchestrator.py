import json

ORCHESTRATOR_PROMPT = """
You are the Orchestrator agent. Analyze the user query and decide which agents to use, what sub-queries to send them, and their dependencies.

### Available Agents:
$agent_descriptions

### Response Schema (return ONLY JSON matching this):
$schema

### Instructions:
1. **Identify agents needed**: Choose ONLY from the available agents listed above. Do not invent or select any agents not in the list (e.g., only 'sql' and 'chat' if they are available).
2. **Create sub_queries**: Break query into specific tasks for each agent (e.g., SQL queries for 'sql'). Return as a list of objects.
3. **Set dependencies**: Specify order (e.g., 'chat' depends on 'sql' for data). Return as a list of objects.

Return ONLY a JSON object with 'agent_needed', 'sub_queries', 'dependencies'. No extra text.
"""


def build_orchestrator_prompt(schema_model) -> str:
    agents_info = {}
    with open("config/agents.json", "r") as f:
        agents_info = json.load(f)
    agents_desc = []
    for name, info in (agents_info or {}).items():
        if name != "orchestrator":
            desc = info.get("description", "")
            caps = ", ".join(info.get("capabilities", []))
            agents_desc.append(f"- {name}: {desc} (Capabilities: {caps})")
    agent_descriptions = "\n".join(agents_desc)

    # Get schema JSON from provided model
    try:
        schema = (
            schema_model.model_json_schema()
            if hasattr(schema_model, "model_json_schema")
            else schema_model
        )
    except Exception:
        schema = {}
    schema_str = json.dumps(schema, indent=2)
    schema_str = schema_str.replace("{", "{{").replace("}", "}}")

    # Substitute into template using $ placeholders
    from string import Template

    prompt_template = Template(ORCHESTRATOR_PROMPT)
    return prompt_template.safe_substitute(
        agent_descriptions=agent_descriptions, schema=schema_str
    )
