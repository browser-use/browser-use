import json

from pydantic import Field, create_model

from browser_use.agent.views import AgentOutput
from browser_use.controller.registry.views import ActionModel

# Create a minimal action model
fields = {
    'test_action': (
        None,
        Field(default=None, description='Test action'),
    )
}

TestActionModel = create_model('ActionModel', __base__=ActionModel, **fields)

# Create AgentOutput with this action model
AgentOutput_ = AgentOutput.type_with_custom_actions(TestActionModel)

# Get the schema
schema = AgentOutput_.model_json_schema()

# Print the schema in a readable format
print(json.dumps(schema, indent=2))

# Check if all objects have additionalProperties
def check_additional_properties(obj, path="root"):
    issues = []
    
    if isinstance(obj, dict):
        # Check if this is an object schema
        if obj.get('type') == 'object' and 'additionalProperties' not in obj:
            issues.append(f"{path}: Missing additionalProperties")
        
        # Recurse through all values
        for key, value in obj.items():
            check_additional_properties(value, f"{path}.{key}")
    
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            check_additional_properties(item, f"{path}[{i}]")
    
    return issues

# Check for issues
issues = check_additional_properties(schema)
if issues:
    print("\nIssues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("\nNo issues found with additionalProperties")
