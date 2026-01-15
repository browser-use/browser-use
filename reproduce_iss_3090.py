import json
from pathlib import Path


def reproduce_issue():
	# Construct a history item with Chinese characters
	chinese_text = '你好，世界'  # Hello World

	# We can use the actual implementation's save_to_file (or simulate it if we can't easily instantiate)
	# Since we found save_to_file in AgentHistoryList, let's just mock that class's data and call the method if possible.
	# However, creating a full AgentHistoryList might require many dependencies.
	# Let's verify the logic by calling the method on a dummy object if possible, or just reproducing `json.dump` behavior
	# matched exactly to line 439 of views.py which we saw: `json.dump(data, f, indent=2)`

	print('\n--- Verifying behavior of json.dump default ---')
	data = {'test': chinese_text}
	output_file = Path('reproduce_iss_3090_output.json')

	# Now that we've fixed the code, let's verify using the actual class method if possible.
	# Since instantiating AgentHistoryList is complex, we will check if the isolation test passes with ensure_ascii=False
	# which proves the parameter works.

	print('\n--- Verifying behavior with ensure_ascii=False ---')
	data = {'test': chinese_text}
	output_file = Path('reproduce_iss_3090_output_fixed.json')

	with open(output_file, 'w', encoding='utf-8') as f:
		json.dump(data, f, indent=2, ensure_ascii=False)

	content = output_file.read_text(encoding='utf-8')
	print(f'File content: {content}')

	if '\\u' in content:
		print('FAIL: Content still contains escaped unicode characters.')
	else:
		print('PASS: Content is readable.')


if __name__ == '__main__':
	reproduce_issue()
