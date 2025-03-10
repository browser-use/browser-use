from inspect import signature
from typing import Any, Dict, Generic, Optional, Type, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, create_model

from browser_use.controller.registry.service import Registry
from browser_use.telemetry.views import (
    ControllerRegisteredFunctionsTelemetryEvent,
    RegisteredFunction,
)
from supatest.browser.context import SupatestBrowserContext

from supatest.controller.registry.views import SupatestActionModel, SupatestActionRegistry, SupatestRegisteredAction

Context = TypeVar('Context')


class SupatestRegistry(Registry[Context]):
    """Extended version of Registry that supports supatest action model format"""
    
    def __init__(self, exclude_actions: list[str] = []):
        """Initialize with our custom SupatestActionRegistry instead of the base ActionRegistry"""
        # Initialize base attributes but replace registry with our custom one
        super().__init__(exclude_actions)
        self.registry = SupatestActionRegistry()
    
    # Override the action decorator to use SupatestRegisteredAction
    def action(self, description: str, param_model: Optional[Type[BaseModel]] = None):
        """Decorator for registering actions with supatest format"""
        def decorator(func):
            if self.exclude_actions and func.__name__ in self.exclude_actions:
                return func

            if param_model is None:
                # Create param model from function signature
                created_param_model = self._create_param_model(func)
            else:
                created_param_model = param_model

            # Use SupatestRegisteredAction instead of RegisteredAction
            self.registry.actions[func.__name__] = SupatestRegisteredAction(
                name=func.__name__,
                description=description,
                function=func,
                param_model=created_param_model,
            )

            return func

        return decorator
    
    def create_action_model(self,include_actions: Optional[list[str]] = None) -> Type[SupatestActionModel]:
        """Creates a Pydantic model from registered actions with supatest format"""
        fields = {
			name: (
				Optional[action.param_model],
				Field(default=None, description=action.description),
			)
			for name, action in self.registry.actions.items()
			if include_actions is None or name in include_actions
		}

        self.telemetry.capture(
            ControllerRegisteredFunctionsTelemetryEvent(
                registered_functions=[
                    RegisteredFunction(name=name, params=action.param_model.model_json_schema())
                    for name, action in self.registry.actions.items()
                    if include_actions is None or name in include_actions
                ]
            )
        )

        model = create_model('ActionModel', __base__=SupatestActionModel, **fields)  # type: ignore
        return model

    async def execute_action(
        self,
        action_name: str,
        params: dict,
        browser: Optional[SupatestBrowserContext] = None,
        page_extraction_llm: Optional[BaseChatModel] = None,
        sensitive_data: Optional[Dict[str, str]] = None,
        available_file_paths: Optional[list[str]] = None,
        context: Context | None = None,
    ) -> Any:
        """Execute a registered action with supatest format"""
        if action_name not in self.registry.actions:
            raise ValueError(f'Action {action_name} not found')

        action = self.registry.actions[action_name]
        try:
            # Create the validated Pydantic model
            validated_params = action.param_model(**params)

            # Check if the first parameter is a Pydantic model
            sig = signature(action.function)
            parameters = list(sig.parameters.values())
            is_pydantic = parameters and issubclass(parameters[0].annotation, BaseModel)
            parameter_names = [param.name for param in parameters]

            # Replace sensitive data if provided
            if sensitive_data:
                validated_params = self._replace_sensitive_data(validated_params, sensitive_data)

            # Check if required parameters are provided
            if 'browser' in parameter_names and not browser:
                raise ValueError(f'Action {action_name} requires browser but none provided.')
            if 'page_extraction_llm' in parameter_names and not page_extraction_llm:
                raise ValueError(f'Action {action_name} requires page_extraction_llm but none provided.')
            if 'available_file_paths' in parameter_names and not available_file_paths:
                raise ValueError(f'Action {action_name} requires available_file_paths but none provided.')
            if 'context' in parameter_names and not context:
                raise ValueError(f'Action {action_name} requires context but none provided.')

            # Prepare arguments based on parameter type
            extra_args = {}
            if 'context' in parameter_names:
                extra_args['context'] = context
            if 'browser' in parameter_names:
                extra_args['browser'] = browser
            if 'page_extraction_llm' in parameter_names:
                extra_args['page_extraction_llm'] = page_extraction_llm
            if 'available_file_paths' in parameter_names:
                extra_args['available_file_paths'] = available_file_paths
            if action_name == 'input_text' and sensitive_data:
                extra_args['has_sensitive_data'] = True

            # Execute the action with validated parameters
            if is_pydantic:
                return await action.function(validated_params, **extra_args)
            return await action.function(**validated_params.model_dump(), **extra_args)

        except Exception as e:
            raise RuntimeError(f'Error executing action {action_name}: {str(e)}') from e
        
    def _replace_sensitive_data(self, params: BaseModel, sensitive_data: Dict[str, str]) -> BaseModel:

        """Replaces the sensitive data in the params"""
        # if there are any str with <secret>placeholder</secret> in the params, replace them with the actual value from sensitive_data
        import re

        secret_pattern = re.compile(r'<secret>(.*?)</secret>')

        def replace_secrets(value):
            if isinstance(value, str):
                matches = secret_pattern.findall(value)
                for placeholder in matches:
                    if placeholder in sensitive_data:
                        value = value.replace(f'<secret>{placeholder}</secret>', sensitive_data[placeholder])
                return value
            elif isinstance(value, dict):
                return {k: replace_secrets(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [replace_secrets(v) for v in value]
            return value

        for key, value in params.model_dump().items():
            params.__dict__[key] = replace_secrets(value)
        return params

    def get_prompt_description(self) -> str:
        """Get a description of all actions for the prompt in supatest format"""
        return self.registry.get_prompt_description()