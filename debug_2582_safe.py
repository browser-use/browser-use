import sys

from browser_use.agent.views import ActionResult


def verify_fix():
	print('Verifying Issue #2582 Fix...')

	# Check field existence
	if 'include_extracted_content_only_once' in ActionResult.model_fields:
		print("[PASS] ActionResult has 'include_extracted_content_only_once' field")
	else:
		print(f'[FAIL] ActionResult missing field. Fields found: {ActionResult.model_fields.keys()}')
		sys.exit(1)


if __name__ == '__main__':
	verify_fix()
