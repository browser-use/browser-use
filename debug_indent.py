import sys


def repair():
	file_path = 'browser_use/dom/service.py'
	try:
		with open(file_path, 'r', encoding='utf-8') as f:
			lines = f.readlines()

		# Locate the lines
		# Look for "if dom_tree_node.content_document:"
		target_line_idx = -1
		for i, line in enumerate(lines):
			if 'if dom_tree_node.content_document:' in line:
				target_line_idx = i
				break

		if target_line_idx == -1:
			print('Target not found')
			return

		print(f'Found target at line {target_line_idx + 1}')
		print(f'Current content: {repr(lines[target_line_idx])}')
		print(f'Next line: {repr(lines[target_line_idx + 1])}')

		# Calculate indentation from the 'if' line (assuming it might be wrong or right,
		# but let's look at the PREVIOUS line 'else:' or comment)
		# Scan back for 'else:'
		else_idx = -1
		for i in range(target_line_idx, -1, -1):
			if 'else:' in lines[i].strip():
				else_idx = i
				break

		if else_idx != -1:
			# Get indentation of else
			else_indent = lines[else_idx][: len(lines[else_idx]) - len(lines[else_idx].lstrip())]
			print(f'Else indent: {repr(else_indent)}')

			# We want 'if' to be else_indent + '\t'
			# And 'return' to be else_indent + '\t\t'
			# And the 'try' block (which follows) to be else_indent + '\t'

			# Reconstruct lines
			# Line 751: if dom_tree_node.content_document:
			lines[target_line_idx] = else_indent + '\t' + 'if dom_tree_node.content_document:\n'

			# Line 752: return dom_tree_node
			lines[target_line_idx + 1] = else_indent + '\t\t' + 'return dom_tree_node\n'

			# Line 753: (empty?)
			# Check if line 753 is empty or try
			if lines[target_line_idx + 2].strip() == '':
				lines[target_line_idx + 2] = '\n'
			elif 'try:' in lines[target_line_idx + 2]:
				# Ensure try is indented correctly (same as if)
				lines[target_line_idx + 2] = else_indent + '\t' + 'try:\n'

			with open(file_path, 'w', encoding='utf-8') as f:
				f.writelines(lines)
			print('Fixed indentation.')

	except Exception as e:
		print(f'Error: {e}')


if __name__ == '__main__':
	repair()
