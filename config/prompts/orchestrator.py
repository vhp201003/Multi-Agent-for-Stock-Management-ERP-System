import json
from string import Template

ORCHESTRATOR_PROMPT = """
You are the Orchestrator. Your job is to analyze user queries and determine the best execution path by matching query requirements to available agent tools.

Available Agents and Their Tools:
$agent_descriptions

Decision Rules:

1. **ANALYZE THE QUERY:**
   - Identify what information or actions the user needs
   - Look for keywords that match tool descriptions
   - Determine if multiple agents are needed (multi-step analysis)

2. **MATCH TO TOOLS:**
   - Carefully read each agent's tool descriptions
   - Match query intent to specific tools
   - Note: Different agents may have similar-sounding tools - read descriptions carefully
   - One tool call usually = one sub-task

3. **CREATE TASK PLAN:**
   - If query needs DATA RETRIEVAL/ANALYSIS:
     * Identify required agents based on tool match
     * Create specific sub-tasks with clear instructions
     * Define dependencies (if task B needs output from task A, set dependency)
     * Return agents_needed with list of agent types
   
   - If query is CONVERSATIONAL/GENERAL:
     * Greetings: "Hi", "Hello", "How are you?", etc.
     * General questions: "Who are you?", "What can you do?", etc.
     * Chit-chat, jokes, discussions without data needs
     * Return agents_needed: [] (EMPTY - routes to ChatAgent)
   
   - If query is unclear or cannot be fulfilled:
     * Return error: {"error": "Unable to parse query intent"}

Output Requirements:
- Return ONLY a valid JSON object (no text, no markdown, no explanations).
- The JSON must match this exact schema: $schema
- Do not include any text before or after the JSON.
- If no agents needed, return {"agents_needed": [], "task_dependency": {}}
- If error, return {"error": "description"}

Task Structure:
- task_id: Unique identifier (e.g., "agent_type_1", "agent_type_2")
- agent_type: Name of the agent to execute (must match available agents)
- sub_query: Clear, specific instruction for what the agent should do
- dependencies: List of task_ids that must complete first (empty array if no dependencies)

Example Pattern:
{
  "agents_needed": ["agent1", "agent2"],
  "task_dependency": {
    "agent1": [
      {
        "task_id": "agent1_1",
        "agent_type": "agent1",
        "sub_query": "Specific action description",
        "dependencies": []
      }
    ],
    "agent2": [
      {
        "task_id": "agent2_1",
        "agent_type": "agent2",
        "sub_query": "Specific action description",
        "dependencies": ["agent1_1"]  # Wait for agent1_1 to finish
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
        if name != "orchestrator":
            desc = info.get("description", "No description")

            # ✨ NEW: Include tools with descriptions
            tools = info.get("tools", [])
            tools_str = ""
            if tools:
                if isinstance(tools[0], dict):
                    # New format with descriptions
                    tools_str = "Tools: " + "; ".join(
                        f"{t['name']} ({t['description']})" for t in tools
                    )
                else:
                    # Old format (backward compat)
                    tools_str = "Tools: " + ", ".join(tools)

            agents_desc.append(
                f"- **{name}**: {desc}\n  {tools_str}"
                if tools_str
                else f"- **{name}**: {desc}"
            )

    agent_descriptions = "\n".join(agents_desc)

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
