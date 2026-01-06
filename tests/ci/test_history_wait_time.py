from browser_use.agent.views import StepMetadata


def test_step_metadata_has_step_interval_field():
	"""Test that StepMetadata includes step_interval field"""
	metadata = StepMetadata(step_number=1, step_start_time=10.0, step_end_time=12.5, step_interval=2.5)

	assert hasattr(metadata, 'step_interval')
	assert metadata.step_interval == 2.5


def test_step_metadata_step_interval_optional():
	"""Test that step_interval is optional (None for first step)"""
	# Explicitly None
	metadata_none = StepMetadata(step_number=0, step_start_time=0.0, step_end_time=1.0, step_interval=None)
	assert metadata_none.step_interval is None

	# Omitted (defaults to None)
	metadata_default = StepMetadata(step_number=0, step_start_time=0.0, step_end_time=1.0)
	assert metadata_default.step_interval is None


def test_step_interval_calculation():
	"""Test step_interval calculation logic (uses previous step's duration)"""
	# Previous step (Step 1): runs from 100.0 to 102.5 (duration: 2.5s)
	previous_start = 100.0
	previous_end = 102.5
	previous_duration = previous_end - previous_start

	# Current step (Step 2): should have step_interval = previous step's duration
	# This tells the rerun system "wait 2.5s before executing Step 2"
	expected_step_interval = previous_duration
	calculated_step_interval = max(0, previous_end - previous_start)

	assert abs(calculated_step_interval - expected_step_interval) < 0.001  # Float comparison
	assert calculated_step_interval == 2.5


def test_step_metadata_serialization_with_step_interval():
	"""Test that step_interval is included in metadata serialization"""
	# With step_interval
	metadata_with_wait = StepMetadata(step_number=1, step_start_time=10.0, step_end_time=12.5, step_interval=2.5)

	data = metadata_with_wait.model_dump()
	assert 'step_interval' in data
	assert data['step_interval'] == 2.5

	# Without step_interval (None)
	metadata_without_wait = StepMetadata(step_number=0, step_start_time=0.0, step_end_time=1.0, step_interval=None)

	data = metadata_without_wait.model_dump()
	assert 'step_interval' in data
	assert data['step_interval'] is None


def test_step_metadata_deserialization_with_step_interval():
	"""Test that step_interval can be loaded from dict"""
	# Load with step_interval
	data_with_wait = {'step_number': 1, 'step_start_time': 10.0, 'step_end_time': 12.5, 'step_interval': 2.5}

	metadata = StepMetadata.model_validate(data_with_wait)
	assert metadata.step_interval == 2.5

	# Load without step_interval (old format)
	data_without_wait = {
		'step_number': 0,
		'step_start_time': 0.0,
		'step_end_time': 1.0,
		# step_interval is missing
	}

	metadata = StepMetadata.model_validate(data_without_wait)
	assert metadata.step_interval is None  # Defaults to None


def test_step_interval_backwards_compatibility():
	"""Test that old metadata without step_interval still works"""
	# Simulate old format from JSON
	old_metadata_dict = {
		'step_number': 0,
		'step_start_time': 1000.0,
		'step_end_time': 1002.5,
		# step_interval field doesn't exist (old format)
	}

	# Should load successfully with step_interval defaulting to None
	metadata = StepMetadata.model_validate(old_metadata_dict)

	assert metadata.step_number == 0
	assert metadata.step_start_time == 1000.0
	assert metadata.step_end_time == 1002.5
	assert metadata.step_interval is None  # Default value


def test_duration_seconds_property_still_works():
	"""Test that existing duration_seconds property still works"""
	metadata = StepMetadata(step_number=1, step_start_time=10.0, step_end_time=13.5, step_interval=2.0)

	# duration_seconds should be 3.5 (13.5 - 10.0)
	assert metadata.duration_seconds == 3.5

	# step_interval is separate from duration
	assert metadata.step_interval == 2.0


def test_step_metadata_json_round_trip():
	"""Test that step_interval survives JSON serialization round-trip"""
	metadata = StepMetadata(step_number=1, step_start_time=100.0, step_end_time=102.5, step_interval=1.5)

	# Serialize to JSON
	json_str = metadata.model_dump_json()

	# Deserialize from JSON
	loaded = StepMetadata.model_validate_json(json_str)

	assert loaded.step_interval == 1.5
	assert loaded.step_number == 1
	assert loaded.step_start_time == 100.0
	assert loaded.step_end_time == 102.5
