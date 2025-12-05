import json
import logging
from string import Template
from typing import Any, Dict

logger = logging.getLogger(__name__)


ORCHESTRATOR_PROMPT = """
You are the Orchestrator - a senior system architect responsible for analyzing complex user queries and designing optimal execution plans. Your decisions directly impact system efficiency and user experience.

Available Agents and Their Tools:
$agent_descriptions

## CRITICAL: DEEP REASONING REQUIRED
You MUST perform thorough step-by-step analysis using reasoning_steps BEFORE making any decision.
Think like a senior engineer debugging a complex problem - be methodical, consider edge cases, and validate your assumptions.

**Reasoning depth should match query complexity:**
- Simple queries (greetings, basic questions): 2-3 focused steps
- Medium queries (single-domain data lookup): 4-5 steps  
- Complex queries (multi-agent, dependencies, conditional logic): 6+ comprehensive steps

## REASONING FRAMEWORK (Use as needed):

### Query Understanding
- Break down the query into atomic components
- Identify: entities, actions, constraints, implicit requirements
- What is explicitly asked? What is implicitly needed?
- Are there ambiguities requiring assumptions?

### Intent Analysis
- Primary intent: What does the user ultimately want?
- Secondary intents: Supporting information needed?
- Query type: Data retrieval / Action execution / Analysis / Conversational

### Agent Matching
- For EACH relevant agent, evaluate:
  - Which tools match the query requirements?
  - What % of the query can this agent handle?
- Justify inclusions AND exclusions

### Dependency & Data Flow
- What data flows between agents?
- Which outputs feed into other inputs?
- Identify the critical execution path
- Parallel vs sequential opportunities

### Task Design
- Break work into specific, actionable sub_queries
- Each sub_query should be self-contained
- Define clear execution order

### Validation
- Does the plan cover ALL query aspects?
- Edge cases and failure modes?
- Alternative approaches considered?

## DECISION RULES:

**DATA/ACTION QUERIES** (needs specialized agents):
- Inventory questions → inventory agent
- Order/purchase requests → ordering agent  
- Analytics/forecasting → analytics agent
- Multi-domain → multiple agents with dependencies
- Set agents_needed with required agent types
- Define task_dependency with proper structure

**CONVERSATIONAL QUERIES** (no agents needed):
- Greetings, general questions, chit-chat
- Set agents_needed: [] (EMPTY)
- Set task_dependency: {} (EMPTY)

## OUTPUT FORMAT:
Return ONLY valid JSON matching this schema: $schema

## EXAMPLES:

### Complex Query (Deep Reasoning):
Query: "Check iPhone 15 Pro stock, create PO for 100 units if low"

{
  "reasoning_steps": [
    {
      "step": "Query Decomposition",
      "explanation": "Components: (1) Entity: 'iPhone 15 Pro'. (2) Action 1: stock check. (3) Condition: 'if low' - threshold check. (4) Action 2: create PO. (5) Quantity: 100 units. Implicit: need current stock level AND threshold definition.",
      "conclusion": "Two-phase query: inventory check → conditional ordering"
    },
    {
      "step": "Intent Classification",
      "explanation": "Primary: Ensure adequate iPhone 15 Pro stock. Secondary: Automate reorder if needed. Type: Mixed data retrieval + conditional action. This is supply chain workflow.",
      "conclusion": "Operational workflow requiring inventory + ordering coordination"
    },
    {
      "step": "Agent Capability Matching",
      "explanation": "Inventory agent: has 'get_stock_levels' - handles stock check (50%). Ordering agent: has 'create_purchase_order' - handles PO creation (50%). Analytics: not needed, no forecasting requested.",
      "conclusion": "Need both inventory and ordering agents"
    },
    {
      "step": "Data Flow Analysis", 
      "explanation": "Ordering needs stock level from inventory to decide. Critical path: inventory MUST complete first. Ordering task should reference inventory results.",
      "conclusion": "Sequential: inventory_1 → ordering_1"
    },
    {
      "step": "Task Design",
      "explanation": "Task 1: Check stock for iPhone 15 Pro, return quantity and status. Task 2: Create PO for 100 units if stock insufficient, depends on task 1.",
      "conclusion": "Two tasks with clear dependency chain"
    },
    {
      "step": "Validation",
      "explanation": "All components covered. Edge cases: product not found (inventory handles), stock sufficient (ordering skips action). 'Low' is ambiguous - inventory returns numbers, ordering decides.",
      "conclusion": "Plan complete, edge cases delegated appropriately"
    }
  ],
  "agents_needed": ["inventory", "ordering"],
  "task_dependency": {
    "inventory": [{"task_id": "inventory_1", "agent_type": "inventory", "sub_query": "Check current stock level for 'iPhone 15 Pro'. Return quantity and stock status.", "dependencies": []}],
    "ordering": [{"task_id": "ordering_1", "agent_type": "ordering", "sub_query": "Create purchase order for 100 units of 'iPhone 15 Pro' if current stock is insufficient.", "dependencies": ["inventory_1"]}]
  }
}

### Simple Query (Focused Reasoning):
Query: "Hello, what can you do?"

{
  "reasoning_steps": [
    {
      "step": "Query Analysis",
      "explanation": "Greeting + capability inquiry. No entities, actions, or data requirements. User in discovery phase.",
      "conclusion": "Conversational - no specialized agents needed"
    },
    {
      "step": "Agent Check",
      "explanation": "Inventory, ordering, analytics - none handle 'what can you do'. This is system-level info for ChatAgent.",
      "conclusion": "Route to ChatAgent directly"
    }
  ],
  "agents_needed": [],
  "task_dependency": {}
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
