import asyncio
from inspect import iscoroutinefunction, signature
from typing import Any, Callable, Dict, Optional, Type

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, create_model

from browser_use.browser.context import BrowserContext
from browser_use.controller.registry.views import (
    ActionModel,
    ActionRegistry,
    RegisteredAction,
)
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import (
    ControllerRegisteredFunctionsTelemetryEvent,
    RegisteredFunction,
)


class Registry:
    """Service for registering and managing actions"""

    def __init__(self, exclude_actions: list[str] = []):
        self.registry = ActionRegistry()
        self.telemetry = ProductTelemetry()
        self.exclude_actions = exclude_actions

    def _create_param_model(self, function: Callable) -> Type[BaseModel]:
        """Creates a Pydantic model from function signature"""
        sig = signature(function)
        params = {
            name: (param.annotation, ... if param.default == param.empty else param.default)
            for name, param in sig.parameters.items()
            if name != 'browser' and name != 'page_extraction_llm'
        }
        # TODO: make the types here work
        return create_model(
            f'{function.__name__}_parameters',
            __base__=ActionModel,
            **params,  # type: ignore
        )

    def action(
        self,
        description: str,
        param_model: Optional[Type[BaseModel]] = None,
    ):
        """Decorator for registering actions"""

        def decorator(func: Callable):
            # Skip registration if action is in exclude_actions
            if func.__name__ in self.exclude_actions:
                return func

            # Create param model from function if not provided
            actual_param_model = param_model or self._create_param_model(func)

            # Wrap sync functions to make them async
            if not iscoroutinefunction(func):

                async def async_wrapper(*args, **kwargs):
                    return await asyncio.to_thread(func, *args, **kwargs)

                # Copy the signature and other metadata from the original function
                async_wrapper.__signature__ = signature(func)
                async_wrapper.__name__ = func.__name__
                async_wrapper.__annotations__ = func.__annotations__
                wrapped_func = async_wrapper
            else:
                wrapped_func = func

            action = RegisteredAction(
                name=func.__name__,
                description=description,
                function=wrapped_func,
                param_model=actual_param_model,
            )
            self.registry.actions[func.__name__] = action
            return func

        return decorator

    async def execute_action(
        self,
        action_name: str,
        params: dict,
        browser: Optional[BrowserContext] = None,
        page_extraction_llm: Optional[BaseChatModel] = None,
        sensitive_data: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute a registered action"""
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

            if sensitive_data:
                validated_params = self._replace_sensitive_data(validated_params, sensitive_data)

            # Prepare arguments based on parameter type
            if 'browser' in parameter_names and 'page_extraction_llm' in parameter_names:
                if not browser:
                    raise ValueError(f'Action {action_name} requires browser but none provided.')
                if not page_extraction_llm:
                    raise ValueError(f'Action {action_name} requires page_extraction_llm but none provided.')
                if is_pydantic:
                    return await action.function(validated_params, browser=browser, page_extraction_llm=page_extraction_llm)
                return await action.function(
                    **validated_params.model_dump(), browser=browser, page_extraction_llm=page_extraction_llm
                )

            if 'browser' in parameter_names:
                if not browser:
                    raise ValueError(f'Action {action_name} requires browser but none provided.')
                if is_pydantic:
                    return await action.function(validated_params, browser=browser)
                return await action.function(**validated_params.model_dump(), browser=browser)

            if 'page_extraction_llm' in parameter_names:
                if not page_extraction_llm:
                    raise ValueError(f'Action {action_name} requires page_extraction_llm but none provided.')
                if is_pydantic:
                    return await action.function(validated_params, page_extraction_llm=page_extraction_llm)
                return await action.function(**validated_params.model_dump(), page_extraction_llm=page_extraction_llm)

            if is_pydantic:
                return await action.function(validated_params)
            return await action.function(**validated_params.model_dump())

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

    def create_action_model(self) -> Type[ActionModel]:
        """Creates a Pydantic model from registered actions"""
        fields = {
            name: (
                Optional[action.param_model],
                Field(default=None, description=action.description),
            )
            for name, action in self.registry.actions.items()
        }

        self.telemetry.capture(
            ControllerRegisteredFunctionsTelemetryEvent(
                registered_functions=[
                    RegisteredFunction(name=name, params=action.param_model.model_json_schema())
                    for name, action in self.registry.actions.items()
                ]
            )
        )

        return create_model('ActionModel', __base__=ActionModel, **fields)  # type:ignore

    def get_prompt_description(self) -> str:
        """Get a description of all actions for the prompt"""
        return self.registry.get_prompt_description()
