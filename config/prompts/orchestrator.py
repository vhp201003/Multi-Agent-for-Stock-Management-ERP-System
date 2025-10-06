import json

ORCHESTRATOR_PROMPT = """
You are the Orchestrator agent. Analyze the user query and create a task execution plan.

### Available Agents:
$agent_descriptions

### Task Creation Rules:
- task_id format: {agent_type}_{number} (e.g., "inventory_1", "ordering_2")
- Each agent gets 1-3 specific tasks
- Use dependencies to set execution order
- Be precise and actionable in task descriptions

### Response Format:
Return ONLY JSON matching the schema below. No explanations.

$schema

### Example:
{
  "agents_needed": ["inventory", "ordering"],
  "task_dependency": {
    "nodes": {
      "inventory": {
        "tasks": [{"task_id": "inventory_1", "agent_type": "inventory", "sub_query": "Check stock levels", "dependencies": []}]
      },
      "ordering": {
        "tasks": [{"task_id": "ordering_1", "agent_type": "ordering", "sub_query": "Create purchase order", "dependencies": ["inventory_1"]}]
      }
    }
  }
}
"""


def build_orchestrator_prompt(schema_model) -> str:
    try:
        with open("config/agents.json", "r") as f:
            agents_info = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        agents_info = {}
    
    agents_desc = []
    for name, info in agents_info.items():
        if name != "orchestrator":  # Skip self-reference
            desc = info.get("description", "No description")
            caps = info.get("capabilities", [])[:3]  # Max 3 capabilities
            caps_str = ", ".join(caps) if caps else "general tasks"
            agents_desc.append(f"- **{name}**: {desc} ({caps_str})")
    
    agent_descriptions = "\n".join(agents_desc) if agents_desc else "No agents available"

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
                "task_dependency": {"type": "object"}
            },
            "required": ["agents_needed", "task_dependency"]
        }
    
    schema_str = json.dumps(schema, indent=1, separators=(',', ':'))  # Compact formatting
    
    from string import Template
    prompt_template = Template(ORCHESTRATOR_PROMPT)
    
    return prompt_template.safe_substitute(
        agent_descriptions=agent_descriptions,
        schema=schema_str
    )


def _minimize_schema_for_prompt(schema: dict) -> dict:
    def clean_properties(props: dict) -> dict:
        cleaned = {}
        for key, value in props.items():
            if isinstance(value, dict):
                essential = {k: v for k, v in value.items() 
                           if k in ["type", "items", "properties", "required", "$ref"]}
                
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
        "required": schema.get("required", [])
    }
    
    if "$defs" in schema:
        minimal_schema["$defs"] = {}
        for def_name, def_schema in schema["$defs"].items():
            minimal_schema["$defs"][def_name] = {
                "type": def_schema.get("type", "object"),
                "properties": clean_properties(def_schema.get("properties", {})),
                "required": def_schema.get("required", [])
            }
    
    return minimal_schema