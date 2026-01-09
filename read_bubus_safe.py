import bubus
import os

bubus_dir = os.path.dirname(bubus.__file__)
service_path = os.path.join(bubus_dir, 'service.py')

if os.path.exists(service_path):
    with open(service_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if "os.environ" in line:
                print(f"Found os.environ at line {i+1}: {line.strip()}")
