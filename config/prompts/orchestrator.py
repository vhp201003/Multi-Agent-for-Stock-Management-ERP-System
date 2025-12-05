import json
import logging
from string import Template
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ============================================================================
# PHASE 1: Chain of Thought Reasoning Prompt (Free-form analysis)
# ============================================================================
COT_REASONING_PROMPT = """
You are the Orchestrator reasoning engine. Your job is to THINK STEP-BY-STEP about how to handle this user query.

Available Agents and Their Tools:
$agent_descriptions

## YOUR TASK:
Analyze the user query and reason through the decision process. Think out loud.

## STEP-BY-STEP ANALYSIS:

1. **UNDERSTAND THE QUERY:**
   - What is the user asking for?
   - What type of request is this? (data retrieval, action, conversation, etc.)
   - Are there multiple parts to this request?

2. **IDENTIFY KEYWORDS & INTENT:**
   - List key terms/concepts in the query
   - Match these to agent capabilities
   - Note any ambiguities

3. **EVALUATE EACH AGENT:**
   - For each potentially relevant agent, explain WHY it matches or doesn't match
   - Be specific about which TOOLS would be used
   - Consider if the query needs domain-specific data or just conversation

4. **DETERMINE AGENT REQUIREMENTS:**
   - If NO specialized agents needed (greetings, general chat, "who are you", etc.):
     → Conclude: "This is a CONVERSATIONAL query, no agents needed"
   - If specialized agents ARE needed:
     → List which agents and why
     → Define dependencies (does agent B need data from agent A first?)

5. **FINAL DECISION:**
   - State your final routing decision clearly
   - If agents needed: specify agent types, sub-queries, and task order
   - If no agents: confirm this is for ChatAgent

Provide your reasoning in plain text. Be thorough but concise.
"""

# ============================================================================
# PHASE 2: Structured Decision Prompt (JSON output from reasoning)
# ============================================================================
COT_DECISION_PROMPT = """
Based on the reasoning analysis below, generate a structured JSON decision.

## REASONING ANALYSIS:
$reasoning

## OUTPUT REQUIREMENTS:
- Return ONLY a valid JSON object (no text, no markdown, no explanations)
- The JSON must match this exact schema: $schema
- If no agents needed (conversational query), return: {"agents_needed": [], "task_dependency": {}}
- If error, return: {"error": "description"}

## TASK STRUCTURE (when agents are needed):
- task_id: Unique identifier (e.g., "agent_type_1")
- agent_type: Name of the agent (must match available agents)
- sub_query: Clear instruction for what the agent should do
- dependencies: List of task_ids that must complete first

## Example:
{
  "agents_needed": ["inventory", "analytics"],
  "task_dependency": {
    "inventory": [{"task_id": "inventory_1", "agent_type": "inventory", "sub_query": "Get stock levels", "dependencies": []}],
    "analytics": [{"task_id": "analytics_1", "agent_type": "analytics", "sub_query": "Analyze trends", "dependencies": ["inventory_1"]}]
  }
}

Generate the JSON now:
"""

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


def _format_agent_descriptions(agents_info: Dict[str, Any]) -> str:
    """Format agent info dict into prompt-friendly string."""
    agents_desc = []
    for name, info in agents_info.items():
        if name == "orchestrator":
            continue

        desc = info.get("description", "No description")

        # Include tools with descriptions
        tools = info.get("tools", [])
        tools_str = ""
        if tools:
            if isinstance(tools[0], dict):
                # Format: tool_name (description)
                tools_str = "Tools: " + "; ".join(
                    f"{t.get('name', 'unknown')} ({t.get('description', 'no desc')})"
                    for t in tools
                )
            else:
                # Old format (backward compat)
                tools_str = "Tools: " + ", ".join(str(t) for t in tools)

        agents_desc.append(
            f"- **{name}**: {desc}\n  {tools_str}"
            if tools_str
            else f"- **{name}**: {desc}"
        )

    return "\n".join(agents_desc)


def _get_agents_info() -> Dict[str, Any]:
    """Lấy agents info: ưu tiên registry, fallback về file."""
    # Thử lấy từ registry trước
    try:
        from src.agents.registry import get_all_agents

        agents = get_all_agents()
        if agents:
            return agents
    except ImportError:
        pass

    # Fallback: đọc từ file
    try:
        with open("config/agents.json", "r") as f:
            logger.info("Using agents.json fallback (registry empty)")
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to read agents.json: {e}")
        return {}


def build_orchestrator_prompt(schema_model) -> str:
    """Build orchestrator system prompt với agent descriptions từ registry."""
    agents_info = _get_agents_info()
    agent_descriptions = _format_agent_descriptions(agents_info)

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


# ============================================================================
# Chain of Thought Prompt Builders
# ============================================================================
def build_cot_reasoning_prompt() -> str:
    """Build Phase 1 prompt: Free-form reasoning về query."""
    agents_info = _get_agents_info()
    agent_descriptions = _format_agent_descriptions(agents_info)
    prompt_template = Template(COT_REASONING_PROMPT)
    return prompt_template.safe_substitute(agent_descriptions=agent_descriptions)


def build_cot_decision_prompt(reasoning: str, schema_model) -> str:
    """Build Phase 2 prompt: Convert reasoning to structured JSON."""
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

    schema_str = json.dumps(schema, indent=1, separators=(",", ":"))
    prompt_template = Template(COT_DECISION_PROMPT)
    return prompt_template.safe_substitute(reasoning=reasoning, schema=schema_str)
