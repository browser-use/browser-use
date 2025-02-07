import os
import sys

from browser_use.logging_config import setup_logging

# Get the absolute path to the project root
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

setup_logging()
