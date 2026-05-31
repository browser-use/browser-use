from __future__ import annotations

from typing import Any, Union, cast

from pydantic import Field, RootModel, create_model

from browser_use.tools.registry.views import ActionModel, RegisteredAction

ActionModelCacheKey = tuple[tuple[str, str, int, tuple[str, ...], bool], ...]


class ActionModelFactory:
	"""Builds and caches legacy dynamic action-list Pydantic models."""

	def __init__(self) -> None:
		self._cache: dict[ActionModelCacheKey, type[ActionModel]] = {}

	def clear_cache(self) -> None:
		self._cache.clear()

	def create(self, available_actions: dict[str, RegisteredAction]) -> type[ActionModel]:
		cache_key = self._cache_key(available_actions)
		if cache_key in self._cache:
			return self._cache[cache_key]

		result_model = self._create_uncached(available_actions)
		self._cache[cache_key] = result_model
		return result_model

	def _cache_key(self, available_actions: dict[str, RegisteredAction]) -> ActionModelCacheKey:
		return tuple(
			(
				name,
				action.description,
				id(action.param_model),
				tuple(action.domains or ()),
				action.terminates_sequence,
			)
			for name, action in available_actions.items()
		)

	def _create_uncached(self, available_actions: dict[str, RegisteredAction]) -> type[ActionModel]:
		individual_action_models = [self._individual_action_model(name, action) for name, action in available_actions.items()]

		if not individual_action_models:
			return cast(type[ActionModel], create_model('EmptyActionModel', __base__=ActionModel))

		if len(individual_action_models) == 1:
			return individual_action_models[0]

		return self._union_action_model(individual_action_models)

	def _individual_action_model(self, name: str, action: RegisteredAction) -> type[ActionModel]:
		field_definitions: dict[str, Any] = {
			name: (
				action.param_model,
				Field(description=action.description),
			)
		}
		return cast(
			type[ActionModel],
			create_model(
				f'{name.title().replace("_", "")}ActionModel',
				__base__=ActionModel,
				**field_definitions,
			),
		)

	def _union_action_model(self, individual_action_models: list[type[ActionModel]]) -> type[ActionModel]:
		union_type: Any = Union[tuple(individual_action_models)]  # type: ignore[misc]

		class ActionModelUnion(RootModel[union_type]):  # type: ignore[name-defined, valid-type]
			def get_index(self) -> int | None:
				root = cast(Any, self.root)
				if hasattr(root, 'get_index'):
					return root.get_index()
				return None

			def set_index(self, index: int):
				root = cast(Any, self.root)
				if hasattr(root, 'set_index'):
					root.set_index(index)

			def model_dump(self, **kwargs):
				root = cast(Any, self.root)
				if hasattr(root, 'model_dump'):
					return root.model_dump(**kwargs)
				return super().model_dump(**kwargs)

		ActionModelUnion.__name__ = 'ActionModel'
		ActionModelUnion.__qualname__ = 'ActionModel'

		return cast(type[ActionModel], ActionModelUnion)


def clear_action_model_cache(factory: ActionModelFactory | None) -> None:
	if factory is not None:
		factory.clear_cache()
