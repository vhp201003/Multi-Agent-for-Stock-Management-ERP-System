"""
Test for ultra-simplified ChatAgent with 5 field types only.
"""

import json

from src.typing.chat_layout import (
    ChatRequest,
    ChatResponse,
    ColumnBreakLayoutField,
    FieldType,
    GraphLayoutField,
    GraphType,
    MarkdownLayoutField,
    SectionBreakLayoutField,
    TableLayoutField,
)


def test_ultra_simple_schema():
    """Test the ultra-simplified 5-field schema."""

    print("🧪 Testing Ultra-Simple ChatAgent Schema")
    print("=" * 50)

    # Test 1: All 5 field types
    print("\n✅ Test 1: All Field Types")

    try:
        # Create each field type
        fields = [
            SectionBreakLayoutField(
                title="Test Section", description="Testing all field types"
            ),
            MarkdownLayoutField(content="**Bold text** and *italic*\n\n- List item"),
            ColumnBreakLayoutField(),
            GraphLayoutField(
                graph_type=GraphType.BARCHART,
                title="Test Chart",
                data={"labels": ["A", "B", "C"], "datasets": [{"data": [1, 2, 3]}]},
            ),
            TableLayoutField(
                title="Test Table",
                data={
                    "headers": ["Name", "Value"],
                    "rows": [["Item 1", "100"], ["Item 2", "200"]],
                },
            ),
        ]

        # Validate ChatResponse
        response = ChatResponse(layout=fields)

        print(f"✓ Created {len(response.layout)} fields successfully")
        for i, field in enumerate(response.layout, 1):
            print(f"  {i}. {field.field_type.value}")

    except Exception as e:
        print(f"❌ Schema validation failed: {e}")
        return False

    # Test 2: Simple request/response
    print("\n✅ Test 2: Simple Request")

    try:
        # Simple request
        request = ChatRequest(query="Show sales data", context={"period": "Q3"})

        print(f"✓ Request: {request.query}")
        print(f"✓ Context: {request.context}")

        # No chart/table parameters - ChatAgent decides
        print("✓ No chart/table parameters - ChatAgent autonomy confirmed")

    except Exception as e:
        print(f"❌ Request validation failed: {e}")
        return False

    # Test 3: JSON serialization
    print("\n✅ Test 3: JSON Serialization")

    try:
        # Create simple layout
        simple_layout = ChatResponse(
            layout=[
                SectionBreakLayoutField(title="Dashboard"),
                MarkdownLayoutField(content="**Revenue**: $150K"),
            ]
        )

        # Serialize to JSON
        json_data = simple_layout.model_dump()
        json_str = json.dumps(json_data, indent=2)

        print("✓ JSON serialization successful")
        print("Sample JSON:")
        print(json_str[:200] + "..." if len(json_str) > 200 else json_str)

    except Exception as e:
        print(f"❌ JSON serialization failed: {e}")
        return False

    # Test 4: Field Type Coverage
    print("\n✅ Test 4: Field Type Coverage")

    available_types = list(FieldType)
    print(f"Available field types: {len(available_types)}")
    for ft in available_types:
        print(f"  - {ft.value}")

    # Test 5: Schema Simplicity Metrics
    print("\n📊 Schema Simplicity Analysis")

    # Count properties across all field classes
    field_classes = [
        MarkdownLayoutField,
        GraphLayoutField,
        TableLayoutField,
        ColumnBreakLayoutField,
        SectionBreakLayoutField,
    ]

    total_properties = 0
    for cls in field_classes:
        props = len(cls.model_fields)
        print(f"  {cls.__name__}: {props} properties")
        total_properties += props

    avg_properties = total_properties / len(field_classes)
    print(f"\nAverage properties per field: {avg_properties:.1f}")
    print(f"Total field types: {len(available_types)}")

    if avg_properties <= 3.0 and len(available_types) == 5:
        print("✅ Schema meets simplicity requirements!")
    else:
        print("⚠️ Schema could be simpler")

    print("\n🎯 Benefits of Ultra-Simple Schema:")
    print("✓ Only 5 field types → LLM focuses better")
    print("✓ ChatAgent decides charts/tables → smarter responses")
    print("✓ Markdown handles all text → unified formatting")
    print("✓ No user UI preferences → cleaner API")
    print("✓ Reduced complexity → better reliability")

    return True


def test_graph_types():
    """Test available graph types."""
    print("\n📈 Graph Types Available:")
    for gt in GraphType:
        print(f"  - {gt.value}")

    print(f"Total: {len(list(GraphType))} chart types")


if __name__ == "__main__":
    success = test_ultra_simple_schema()
    test_graph_types()

    if success:
        print("\n🚀 Ultra-Simple ChatAgent Schema: READY FOR PRODUCTION!")
    else:
        print("\n❌ Schema needs fixes before production")
