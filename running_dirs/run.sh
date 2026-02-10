#!/bin/bash

# Multiagent Browser-Use Runner
# Basic bash script to run the multiagent orchestrator

# Default values
CONFIG="configs/multiagent_default.yaml"
TASK=""
HEADLESS=""
MAX_STEPS=""
LOG_LEVEL=""
LOG_DIR=""

# Help message
show_help() {
	cat << EOF
Usage: ./running_dirs/run.sh [OPTIONS]

Options:
  -c, --config CONFIG       Path to config file (default: configs/multiagent_default.yaml)
  -t, --task TASK          Task description (required)
  --headless               Run in headless mode
  --max-steps STEPS        Maximum number of steps
  --log-level LEVEL        Log level (DEBUG, INFO, WARNING, ERROR)
  --log-dir DIR            Custom log directory
  -h, --help               Show this help message

Examples:
  ./running_dirs/run.sh -t "Search for the latest Python release"
  ./running_dirs/run.sh -c configs/multiagent_azure.yaml -t "Find laptop prices" --headless
  ./running_dirs/run.sh -t "Research topic" --log-dir my_logs/ --log-level DEBUG

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
	case $1 in
		-c|--config)
			CONFIG="$2"
			shift 2
			;;
		-t|--task)
			TASK="$2"
			shift 2
			;;
		--headless)
			HEADLESS="--headless"
			shift
			;;
		--max-steps)
			MAX_STEPS="--max-steps $2"
			shift 2
			;;
		--log-level)
			LOG_LEVEL="--log-level $2"
			shift 2
			;;
		--log-dir)
			LOG_DIR="--log-dir $2"
			shift 2
			;;
		-h|--help)
			show_help
			exit 0
			;;
		*)
			echo "Unknown option: $1"
			show_help
			exit 1
			;;
	esac
done

# Check required arguments
if [ -z "$TASK" ]; then
	echo "Error: --task is required"
	show_help
	exit 1
fi

# Get script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Change to project root
cd "$PROJECT_ROOT" || exit 1

# Build command
CMD="uv run python running_dirs/run_multiagent.py --config $CONFIG --task \"$TASK\" $HEADLESS $MAX_STEPS $LOG_LEVEL $LOG_DIR"

# Print command for transparency
echo "Running: $CMD"
echo ""

# Execute
eval $CMD
