import inspect
import logging
from typing import Any, Callable, Dict, List

from pydantic import ValidationError, create_model
from pydantic.fields import FieldInfo

logger = logging.getLogger(__name__)


def extract_tool_schema(func: Callable) -> Dict[str, Any]:
    """
    Extract OpenAI/Groq-compatible tool schema from Pydantic-annotated function.

    Args:
        func: Async callable with all parameters using pydantic.Field()

    Returns:
        {
            "type": "function",
            "function": {
                "name": str,
                "description": str,
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        }

    Raises:
        TypeError: If func is not callable
        ValueError: If any parameter lacks Pydantic Field()
    """
    if not callable(func):
        raise TypeError(f"Expected callable, got {type(func).__name__}")

    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError) as e:
        raise TypeError(f"Cannot inspect {func.__name__}: {e}") from e

    docstring = inspect.getdoc(func) or "No description"
    first_line = (docstring.split("\n")[0] or "No description").strip()

    field_definitions: Dict[str, tuple] = {}

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        if not isinstance(param.default, FieldInfo):
            raise ValueError(
                f"Parameter '{param_name}' in {func.__name__}() missing Pydantic Field(). "
                f"All parameters must use Field(...) or Field(default=...)"
            )

        field_definitions[param_name] = (param.annotation, param.default)

    if not field_definitions:
        logger.warning(f"{func.__name__}() has no parameters")

    try:
        DynamicModel = create_model(f"{func.__name__}SchemaModel", **field_definitions)
    except ValidationError as e:
        raise ValueError(f"Failed to create Pydantic model: {e}") from e

    pydantic_schema = DynamicModel.model_json_schema(mode="serialization")
    properties = pydantic_schema.get("properties", {})
    required = pydantic_schema.get("required", [])

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": first_line,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def filter_mcp_tool_for_groq(tool_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(tool_dict, dict):
        raise TypeError(f"Expected dict, got {type(tool_dict).__name__}")

    if "inputSchema" not in tool_dict:
        raise ValueError("Tool missing 'inputSchema' field (invalid MCP tool)")

    name = tool_dict.get("name", "unknown_tool")
    description = tool_dict.get("description", "No description")
    input_schema = tool_dict.get("inputSchema", {})

    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    simplified_properties = _simplify_properties(properties)

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": simplified_properties,
                "required": required,
            },
        },
    }


def _simplify_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
    simplified = {}

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        simplified_prop: Dict[str, Any] = {}

        if "anyOf" in prop_schema:
            # Extract first non-null type
            for variant in prop_schema["anyOf"]:
                if variant.get("type") != "null":
                    simplified_prop.update(variant)
                    break
        else:
            simplified_prop.update(prop_schema)

        groq_keys = {
            "type",
            "description",
            "enum",
            "minimum",
            "maximum",
            "default",
            "items",
        }
        filtered = {k: v for k, v in simplified_prop.items() if k in groq_keys}

        if "items" in filtered and isinstance(filtered["items"], dict):
            if "$ref" in filtered["items"]:
                # Skip $ref references (Groq doesn't support them)
                filtered.pop("items")
            elif "properties" in filtered["items"]:
                filtered["items"] = _simplify_properties({"_": filtered["items"]})["_"]

        simplified[prop_name] = filtered

    return simplified


def extract_groq_tools(tools_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tools to Groq-compatible format for function calling.

    Args:
        tools_list: List of tool dicts from MCP list_tools() response

    Returns:
        List of Groq-compatible tool definitions ready for Groq API

    Example:
        >>> mcp_tools = [tool1_dict, tool2_dict, ...]
        >>> groq_tools = extract_groq_tools(mcp_tools)
        >>> # groq_tools ready for Groq API chat.completions.create(tools=...)
    """
    if not isinstance(tools_list, list):
        raise TypeError(f"Expected list, got {type(tools_list).__name__}")

    groq_tools = []
    for tool in tools_list:
        try:
            groq_tool = filter_mcp_tool_for_groq(tool)
            groq_tools.append(groq_tool)
        except (TypeError, ValueError) as e:
            logger.warning(f"Skipping tool {tool.get('name', '?')}: {e}")
            continue

    return groq_tools
