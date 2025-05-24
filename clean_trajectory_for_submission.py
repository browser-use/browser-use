import json
import shutil
from pathlib import Path

# Define source and destination directories
SOURCE_DIR = Path('saved_trajectories')
DEST_DIR = Path('cleaned_trajectories')

# --- Start: Clear existing destination directory ---
if DEST_DIR.exists():
	print(f'Clearing existing destination directory: "{DEST_DIR}"...')
	try:
		shutil.rmtree(DEST_DIR)
		print(f'Successfully removed "{DEST_DIR}".')
	except OSError as e:
		print(f'Error removing directory "{DEST_DIR}": {e}. Please check permissions or close open files.')
		exit(1)
# --- End: Clear existing destination directory ---


# Create the destination directory (now guaranteed to be empty or non-existent)
try:
	DEST_DIR.mkdir(exist_ok=True)
	print(f'Created destination directory: "{DEST_DIR}"')
except OSError as e:
	print(f'Error creating destination directory "{DEST_DIR}": {e}')
	exit(1)


# Check if the source directory exists
if not SOURCE_DIR.is_dir():
	print(f'Error: Source directory "{SOURCE_DIR}" not found.')
	exit(1)

print(f'Starting cleanup process from "{SOURCE_DIR}" to "{DEST_DIR}"...')

# Iterate through each task folder in the source directory
for task_folder in SOURCE_DIR.iterdir():
	if task_folder.is_dir():
		task_id = task_folder.name
		print(f'Processing task: {task_id}')

		source_result_path = task_folder / 'result.json'
		source_trajectory_path = task_folder / 'trajectory'

		# Define destination paths
		dest_task_folder = DEST_DIR / task_id
		dest_result_path = dest_task_folder / 'result.json'
		dest_trajectory_path = dest_task_folder / 'trajectory'

		# Create the destination task folder
		dest_task_folder.mkdir(exist_ok=True)

		# 1. Copy the 'trajectory' folder
		if source_trajectory_path.is_dir():
			try:
				shutil.copytree(source_trajectory_path, dest_trajectory_path, dirs_exist_ok=True)
				print(f'  - Copied trajectory folder for {task_id}')
			except Exception as e:
				print(f'  - Error copying trajectory folder for {task_id}: {e}')
				continue  # Skip to next task if trajectory copy fails
		else:
			print(f'  - Warning: Trajectory folder not found for {task_id} in source.')
			# Create an empty trajectory folder in destination? Or skip? Let's create it for consistency.
			dest_trajectory_path.mkdir(exist_ok=True)

		# 2. Process and save the simplified 'result.json'
		if source_result_path.is_file():
			try:
				with open(source_result_path) as f:
					original_data = json.load(f)

				# Get evaluation data safely
				evaluation_data = original_data.get('Online_Mind2Web_evaluation', {})  # Default to empty dict if not found

				# Create the simplified dictionary
				cleaned_data = {
					'task_id': original_data.get('task_id', task_id),  # Use folder name as fallback
					'task': original_data.get('task'),
					'action_history': original_data.get('action_history'),
					'Online_Mind2Web_judgement': evaluation_data.get('judgement'),  # Get judgement, default to None if missing
					'Online_Mind2Web_score': evaluation_data.get('score', 0.0),  # Get score, default to 0.0 if missing
				}

				# Check if essential data is present
				if not cleaned_data['task'] or cleaned_data['action_history'] is None:
					print(
						f'  - Warning: Missing essential data (task or action_history) in result.json for {task_id}. Saving available data.'
					)

				# Write the cleaned data to the destination
				with open(dest_result_path, 'w') as f:
					json.dump(cleaned_data, f, indent=2)
				print(f'  - Created simplified result.json for {task_id}')

			except json.JSONDecodeError as e:
				print(f'  - Error reading JSON from {source_result_path}: {e}')
			except Exception as e:
				print(f'  - Error processing result.json for {task_id}: {e}')
		else:
			print(f'  - Warning: result.json not found for {task_id} in source.')

print(f'\nCleanup process finished. Cleaned trajectories saved in "{DEST_DIR}".')
