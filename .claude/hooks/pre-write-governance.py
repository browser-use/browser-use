#!/usr/bin/env python3
import sys
import json
import re
import os

# Read hook input
try:
    input_data = sys.stdin.read()
    if not input_data or not input_data.strip():
        sys.stderr.write("Error: Empty input received for governance hook\n")
        sys.exit(1)
    data = json.loads(input_data)
except json.JSONDecodeError as e:
    sys.stderr.write(f"Error: Invalid JSON input for governance hook: {e}\n")
    sys.exit(1)
except Exception as e:
    sys.stderr.write(f"Error: Unexpected failure in governance hook: {e}\n")
    sys.exit(1)

tool = data.get("tool_name")
tool_input = data.get("tool_input", {})
file_content = tool_input.get("content", "")
file_path = tool_input.get("path", "")

# Only check Write/Edit operations
if tool not in ["Write", "Edit", "create_file", "edit_file"]:
    sys.exit(0)

# 1. Check Line Count
line_count = len(file_content.splitlines())
if line_count > 500:
    print(json.dumps({
        "error": f"GOVERNANCE REJECTION: File '{file_path}' exceeds 500 lines ({line_count}). You MUST split this class/module."
    }))
    sys.exit(1) # Block the action

# 2. Check Env Vars (Regex for common patterns)
env_var_patterns = [
    r"os\.environ[\.\[]",           # Python: os.environ.get or os.environ['key']
    r"os\.getenv\s*\(",             # Python: os.getenv(
    r"os\.Getenv\s*\(",             # Go: os.Getenv(
    r"GetEnvironmentVariable\s*\(", # C#/.NET: GetEnvironmentVariable(
    r"process\.env",                # Node.js: process.env
    r"System\.getenv\s*\(",         # Java: System.getenv(
    r"ENV\["                        # Ruby: ENV['KEY']
]

# More explicit entry point detection
entry_points = {'main.py', 'main.go', 'program.cs', 'startup.cs', 'app.py', '__main__.py'}
file_name = os.path.basename(file_path).lower()

# Check if filename matches entry point convention
if file_name in entry_points:
    # Ensure it is not in a test or spec directory
    # We check path components to avoid partial matches (e.g. 'latest' contains 'test')
    path_parts = set(file_path.replace('\\', '/').lower().split('/'))
    forbidden_dirs = {'tests', 'test', 'spec', 'specs', 'mock', 'mocks'}
    
    # It is an entry point if it DOES NOT contain any forbidden directories
    is_entry_point = not (path_parts & forbidden_dirs)
else:
    is_entry_point = False

for pattern in env_var_patterns:
    if re.search(pattern, file_content):
        # Allow in main/program entry points
        if not is_entry_point:
            print(json.dumps({
                "error": f"GOVERNANCE REJECTION: Detected env var access in '{file_path}'. Values must be passed via arguments."
            }))
            sys.exit(1)

sys.exit(0) # Allow the action
