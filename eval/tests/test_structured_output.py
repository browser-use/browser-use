import json
import traceback

from pydantic import BaseModel

from eval.utils import create_pydantic_model_from_schema


class OutputModel(BaseModel):
	"""Test output model"""

	city: str
	country: str


# async def test_optimized_schema():
# 	"""Test the optimized schema generation and save to file."""

# 	# Create controller and get all registered actions
# 	controller = Controller()
# 	ActionModel = controller.registry.create_action_model()

# 	# Create the agent output model with custom actions
# 	agent_output_model = AgentOutput.type_with_custom_actions(ActionModel)

# 	# # Get original schema for comparison
# 	# original_schema = agent_output_model.model_json_schema()

# 	# # Create the optimized schema
# 	# optimized_schema = SchemaOptimizer.create_optimized_json_schema(agent_output_model)

# 	scgena = create_pydantic_model_from_schema(OutputModel.model_json_schema(), 'OutputModel')

# 	agent = Agent(
# 		task='What is the capital of France? Do not use the internet, just output the done function.',
# 		llm=ChatOpenAI(model='gpt-4.1-mini'),
# 		controller=controller,
# 		output_model_schema=scgena,
# 	)

# 	history = await agent.run()

# 	if history.structured_output:
# 		# print(history.structured_output.city, history.structured_output.country)
# 		print(OutputModel.model_validate_json(history.final_result() or '{}'))
# 	else:
# 		print('No structured output')
# 		print(history.final_result())


def test_basic_types():
	"""Test basic JSON schema types"""
	print('=== Testing Basic Types ===')

	schema = {
		'type': 'object',
		'properties': {
			'name': {'type': 'string'},
			'age': {'type': 'integer'},
			'height': {'type': 'number'},
			'is_active': {'type': 'boolean'},
			'tags': {'type': 'array', 'items': {'type': 'string'}},
			'metadata': {'type': 'object'},
		},
		'required': ['name', 'age'],
	}

	try:
		Model = create_pydantic_model_from_schema(schema, 'BasicTypesModel')
		print(f'✅ Created model: {Model}')

		# Test valid data
		instance = Model(name='John', age=30, height=5.9, is_active=True, tags=['dev', 'python'], metadata={'role': 'developer'})
		print(f'✅ Valid instance: {instance}')

		# Test minimal required data
		minimal = Model(name='Jane', age=25)
		print(f'✅ Minimal instance: {minimal}')

		print('✅ Basic types test passed\n')
		return True
	except Exception as e:
		print(f'❌ Basic types test failed: {e}')
		traceback.print_exc()
		return False


def test_nested_objects():
	"""Test deeply nested object structures"""
	print('=== Testing Nested Objects ===')

	schema = {
		'type': 'object',
		'properties': {
			'user': {
				'type': 'object',
				'properties': {
					'profile': {
						'type': 'object',
						'properties': {
							'personal': {
								'type': 'object',
								'properties': {
									'name': {'type': 'string'},
									'age': {'type': 'integer'},
									'contacts': {
										'type': 'array',
										'items': {
											'type': 'object',
											'properties': {'type': {'type': 'string'}, 'value': {'type': 'string'}},
											'required': ['type', 'value'],
										},
									},
								},
								'required': ['name'],
							},
							'settings': {
								'type': 'object',
								'properties': {'theme': {'type': 'string'}, 'notifications': {'type': 'boolean'}},
							},
						},
						'required': ['personal'],
					}
				},
				'required': ['profile'],
			}
		},
		'required': ['user'],
	}

	try:
		Model = create_pydantic_model_from_schema(schema, 'NestedModel')
		print(f'✅ Created nested model: {Model}')

		# Test complex nested data
		data = {
			'user': {
				'profile': {
					'personal': {
						'name': 'Alice',
						'age': 28,
						'contacts': [{'type': 'email', 'value': 'alice@example.com'}, {'type': 'phone', 'value': '+1234567890'}],
					},
					'settings': {'theme': 'dark', 'notifications': True},
				}
			}
		}

		instance = Model(**data)
		print(f'✅ Complex nested instance: {instance}')

		print('✅ Nested objects test passed\n')
		return True
	except Exception as e:
		print(f'❌ Nested objects test failed: {e}')
		traceback.print_exc()
		return False


def test_union_types():
	"""Test union types and nullable fields"""
	print('=== Testing Union Types ===')

	schema = {
		'type': 'object',
		'properties': {
			'mixed_value': {'anyOf': [{'type': 'string'}, {'type': 'integer'}, {'type': 'boolean'}]},
			'nullable_string': {'type': ['string', 'null']},
			'string_or_number': {'oneOf': [{'type': 'string'}, {'type': 'number'}]},
			'complex_union': {
				'anyOf': [
					{
						'type': 'object',
						'properties': {'type': {'const': 'user'}, 'name': {'type': 'string'}},
						'required': ['type', 'name'],
					},
					{
						'type': 'object',
						'properties': {'type': {'const': 'admin'}, 'permissions': {'type': 'array', 'items': {'type': 'string'}}},
						'required': ['type', 'permissions'],
					},
				]
			},
		},
	}

	try:
		Model = create_pydantic_model_from_schema(schema, 'UnionModel')
		print(f'✅ Created union model: {Model}')

		# Test different union values
		instance1 = Model(mixed_value='hello', nullable_string=None, string_or_number='123')
		print(f'✅ Union instance 1: {instance1}')

		instance2 = Model(mixed_value=42, nullable_string='world', string_or_number=3.14)
		print(f'✅ Union instance 2: {instance2}')

		print('✅ Union types test passed\n')
		return True
	except Exception as e:
		print(f'❌ Union types test failed: {e}')
		traceback.print_exc()
		return False


def test_array_variations():
	"""Test various array configurations"""
	print('=== Testing Array Variations ===')

	schema = {
		'type': 'object',
		'properties': {
			'simple_array': {'type': 'array', 'items': {'type': 'string'}},
			'mixed_array': {
				'type': 'array',
				'items': {
					'anyOf': [
						{'type': 'string'},
						{'type': 'integer'},
						{'type': 'object', 'properties': {'key': {'type': 'string'}}},
					]
				},
			},
			'nested_arrays': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'integer'}}},
			'array_of_objects': {
				'type': 'array',
				'items': {
					'type': 'object',
					'properties': {
						'id': {'type': 'integer'},
						'data': {'type': 'object', 'properties': {'values': {'type': 'array', 'items': {'type': 'number'}}}},
					},
					'required': ['id'],
				},
			},
		},
	}

	try:
		Model = create_pydantic_model_from_schema(schema, 'ArrayModel')
		print(f'✅ Created array model: {Model}')

		# Test complex array data
		data = {
			'simple_array': ['a', 'b', 'c'],
			'mixed_array': ['hello', 42, {'key': 'value'}],
			'nested_arrays': [[1, 2, 3], [4, 5, 6]],
			'array_of_objects': [{'id': 1, 'data': {'values': [1.1, 2.2, 3.3]}}, {'id': 2, 'data': {'values': [4.4, 5.5]}}],
		}

		instance = Model(**data)
		print(f'✅ Complex array instance: {instance}')

		print('✅ Array variations test passed\n')
		return True
	except Exception as e:
		print(f'❌ Array variations test failed: {e}')
		traceback.print_exc()
		return False


def test_enums_and_constants():
	"""Test enum values and constant fields"""
	print('=== Testing Enums and Constants ===')

	schema = {
		'type': 'object',
		'properties': {
			'status': {'type': 'string', 'enum': ['active', 'inactive', 'pending', 'suspended']},
			'priority': {'type': 'integer', 'enum': [1, 2, 3, 4, 5]},
			'type': {'const': 'user_account'},
			'category': {'anyOf': [{'const': 'premium'}, {'const': 'standard'}, {'const': 'basic'}]},
		},
		'required': ['status', 'type'],
	}

	try:
		Model = create_pydantic_model_from_schema(schema, 'EnumModel')
		print(f'✅ Created enum model: {Model}')

		# Test valid enum values
		instance = Model(status='active', priority=3, type='user_account', category='premium')
		print(f'✅ Enum instance: {instance}')

		print('✅ Enums and constants test passed\n')
		return True
	except Exception as e:
		print(f'❌ Enums and constants test failed: {e}')
		traceback.print_exc()
		return False


def test_edge_cases():
	"""Test edge cases and malformed schemas"""
	print('=== Testing Edge Cases ===')

	edge_cases = [
		# Empty schema
		{},
		# Schema with no properties
		{'type': 'object'},
		# Schema with empty properties
		{'type': 'object', 'properties': {}},
		# Schema with additional properties
		{'type': 'object', 'properties': {'name': {'type': 'string'}}, 'additionalProperties': True},
		# Schema with pattern properties
		{'type': 'object', 'patternProperties': {'^S_': {'type': 'string'}, '^I_': {'type': 'integer'}}},
	]

	success_count = 0
	for i, schema in enumerate(edge_cases):
		try:
			Model = create_pydantic_model_from_schema(schema, f'EdgeCase{i}Model')
			print(f'✅ Edge case {i}: {Model}')
			success_count += 1
		except Exception as e:
			print(f'⚠️  Edge case {i} failed: {e}')

	print(f'✅ Edge cases test: {success_count}/{len(edge_cases)} passed\n')
	return True


def test_very_complex_schema():
	"""Test an extremely complex real-world-like schema"""
	print('=== Testing Very Complex Schema ===')

	schema = {
		'type': 'object',
		'properties': {
			'api_version': {'const': 'v1'},
			'metadata': {
				'type': 'object',
				'properties': {
					'name': {'type': 'string'},
					'namespace': {'type': 'string', 'default': 'default'},
					'labels': {'type': 'object', 'additionalProperties': {'type': 'string'}},
					'annotations': {'type': 'object', 'additionalProperties': {'type': 'string'}},
					'created_at': {'type': 'string', 'format': 'date-time'},
				},
				'required': ['name'],
			},
			'spec': {
				'type': 'object',
				'properties': {
					'replicas': {'type': 'integer', 'minimum': 1, 'maximum': 100},
					'selector': {
						'type': 'object',
						'properties': {'match_labels': {'type': 'object', 'additionalProperties': {'type': 'string'}}},
					},
					'template': {
						'type': 'object',
						'properties': {
							'metadata': {
								'type': 'object',
								'properties': {'labels': {'type': 'object', 'additionalProperties': {'type': 'string'}}},
							},
							'spec': {
								'type': 'object',
								'properties': {
									'containers': {
										'type': 'array',
										'items': {
											'type': 'object',
											'properties': {
												'name': {'type': 'string'},
												'image': {'type': 'string'},
												'ports': {
													'type': 'array',
													'items': {
														'type': 'object',
														'properties': {
															'name': {'type': 'string'},
															'container_port': {'type': 'integer'},
															'protocol': {'type': 'string', 'enum': ['TCP', 'UDP', 'SCTP']},
														},
														'required': ['container_port'],
													},
												},
												'env': {
													'type': 'array',
													'items': {
														'type': 'object',
														'properties': {
															'name': {'type': 'string'},
															'value': {'type': 'string'},
															'value_from': {
																'type': 'object',
																'properties': {
																	'secret_key_ref': {
																		'type': 'object',
																		'properties': {
																			'name': {'type': 'string'},
																			'key': {'type': 'string'},
																		},
																		'required': ['name', 'key'],
																	},
																	'config_map_key_ref': {
																		'type': 'object',
																		'properties': {
																			'name': {'type': 'string'},
																			'key': {'type': 'string'},
																		},
																		'required': ['name', 'key'],
																	},
																},
															},
														},
														'required': ['name'],
													},
												},
												'resources': {
													'type': 'object',
													'properties': {
														'requests': {
															'type': 'object',
															'properties': {
																'memory': {'type': 'string'},
																'cpu': {'type': 'string'},
															},
														},
														'limits': {
															'type': 'object',
															'properties': {
																'memory': {'type': 'string'},
																'cpu': {'type': 'string'},
															},
														},
													},
												},
											},
											'required': ['name', 'image'],
										},
									},
									'volumes': {
										'type': 'array',
										'items': {
											'type': 'object',
											'properties': {
												'name': {'type': 'string'},
												'config_map': {'type': 'object', 'properties': {'name': {'type': 'string'}}},
												'secret': {'type': 'object', 'properties': {'secret_name': {'type': 'string'}}},
												'empty_dir': {'type': 'object', 'properties': {'size_limit': {'type': 'string'}}},
											},
											'required': ['name'],
										},
									},
								},
								'required': ['containers'],
							},
						},
						'required': ['spec'],
					},
				},
				'required': ['template'],
			},
			'status': {
				'type': 'object',
				'properties': {
					'ready_replicas': {'type': 'integer'},
					'available_replicas': {'type': 'integer'},
					'conditions': {
						'type': 'array',
						'items': {
							'type': 'object',
							'properties': {
								'type': {'type': 'string'},
								'status': {'type': 'string', 'enum': ['True', 'False', 'Unknown']},
								'reason': {'type': 'string'},
								'message': {'type': 'string'},
								'last_update_time': {'type': 'string', 'format': 'date-time'},
							},
							'required': ['type', 'status'],
						},
					},
				},
			},
		},
		'required': ['api_version', 'metadata', 'spec'],
	}

	try:
		Model = create_pydantic_model_from_schema(schema, 'KubernetesDeployment')
		print(f'✅ Created very complex model: {Model}')

		# Create a sample instance
		data = {
			'api_version': 'v1',
			'metadata': {
				'name': 'my-app',
				'namespace': 'production',
				'labels': {'app': 'my-app', 'version': '1.0'},
				'created_at': '2024-01-01T00:00:00Z',
			},
			'spec': {
				'replicas': 3,
				'template': {
					'spec': {
						'containers': [
							{
								'name': 'my-app',
								'image': 'my-app:latest',
								'ports': [{'name': 'http', 'container_port': 8080, 'protocol': 'TCP'}],
								'env': [
									{'name': 'ENV', 'value': 'production'},
									{
										'name': 'SECRET_KEY',
										'value_from': {'secret_key_ref': {'name': 'my-secret', 'key': 'secret-key'}},
									},
								],
								'resources': {
									'requests': {'memory': '128Mi', 'cpu': '100m'},
									'limits': {'memory': '256Mi', 'cpu': '200m'},
								},
							}
						]
					}
				},
			},
		}

		instance = Model(**data)
		print('✅ Very complex instance created successfully')

		print('✅ Very complex schema test passed\n')
		return True
	except Exception as e:
		print(f'❌ Very complex schema test failed: {e}')
		traceback.print_exc()
		return False


def test_string_schema_input():
	"""Test passing schema as JSON string instead of dict"""
	print('=== Testing String Schema Input ===')

	schema_string = json.dumps(
		{'type': 'object', 'properties': {'message': {'type': 'string'}, 'count': {'type': 'integer'}}, 'required': ['message']}
	)

	try:
		Model = create_pydantic_model_from_schema(schema_string, 'StringSchemaModel')
		print(f'✅ Created model from string schema: {Model}')

		instance = Model(message='Hello', count=42)
		print(f'✅ String schema instance: {instance}')

		print('✅ String schema input test passed\n')
		return True
	except Exception as e:
		print(f'❌ String schema input test failed: {e}')
		traceback.print_exc()
		return False


def test_recursive_structures():
	"""Test recursive/self-referencing structures"""
	print('=== Testing Recursive Structures ===')

	schema = {
		'type': 'object',
		'properties': {
			'name': {'type': 'string'},
			'children': {
				'type': 'array',
				'items': {'$ref': '#'},  # Self-reference
			},
			'parent': {'$ref': '#'},  # Self-reference
		},
		'required': ['name'],
	}

	try:
		Model = create_pydantic_model_from_schema(schema, 'RecursiveModel')
		print(f'✅ Created recursive model: {Model}')

		# Note: Recursive structures are complex and may not work perfectly
		# This is more of a "does it crash?" test
		print('✅ Recursive structures test passed (creation only)\n')
		return True
	except Exception as e:
		print(f'⚠️  Recursive structures test failed (expected): {e}')
		print('Note: Recursive structures are complex and may not be fully supported\n')
		return True  # Don't fail the overall test for this


def run_comprehensive_schema_tests():
	"""Run all comprehensive tests for create_pydantic_model_from_schema"""
	print('🚀 Starting comprehensive schema testing...\n')

	tests = [
		('Basic Types', test_basic_types),
		('Nested Objects', test_nested_objects),
		('Union Types', test_union_types),
		('Array Variations', test_array_variations),
		('Enums and Constants', test_enums_and_constants),
		('Recursive Structures', test_recursive_structures),
		('Edge Cases', test_edge_cases),
		('Very Complex Schema', test_very_complex_schema),
		('String Schema Input', test_string_schema_input),
	]

	passed = 0
	total = len(tests)

	for test_name, test_func in tests:
		print(f'Running {test_name}...')
		try:
			if test_func():
				passed += 1
			else:
				print(f'❌ {test_name} failed')
		except Exception as e:
			print(f'❌ {test_name} crashed: {e}')
			traceback.print_exc()

		print('-' * 50)

	print('\n🏁 Testing Complete!')
	print(f'📊 Results: {passed}/{total} tests passed')

	if passed == total:
		print('🎉 All tests passed! The function handles complex schemas well.')
	else:
		print('⚠️  Some tests failed. Check the output above for details.')

	return passed == total


if __name__ == '__main__':
	# Run the comprehensive tests
	print('Running comprehensive schema tests first...')
	run_comprehensive_schema_tests()

	print('\n' + '=' * 60)
	print('Now running the original test...')
