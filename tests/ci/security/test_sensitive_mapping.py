from collections import UserDict
from types import MappingProxyType

from browser_use.agent.views import AgentHistory
from browser_use.utils import collect_sensitive_data_values


def test_collect_sensitive_data_values_accepts_mapping_implementations():
	assert collect_sensitive_data_values(
		MappingProxyType({'username': 'user123', 'scoped': UserDict({'password': 'pass456'})})
	) == {'username': 'user123', 'password': 'pass456'}


def test_history_redacts_nested_values_with_mapping_sensitive_data():
	history = AgentHistory.model_construct()
	sensitive_data = MappingProxyType({'scoped': UserDict({'password': 'pass456'})})
	assert history._filter_sensitive_data_from_value({'rows': [('pass456',)]}, sensitive_data) == {
		'rows': [('<secret>password</secret>',)]
	}
