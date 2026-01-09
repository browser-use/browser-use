import bubus
import os

# Find the file where EventBus is defined
print(f"Bubus file: {bubus.__file__}")

# Read and search for timeout
bubus_dir = os.path.dirname(bubus.__file__)
service_path = os.path.join(bubus_dir, 'service.py')

if os.path.exists(service_path):
    print(f"Scanning {service_path}")
    with open(service_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            if "timeout" in line.lower() or "30" in line:
                print(f"{i+1}: {line.strip()}")
else:
    print("Service file not found")
