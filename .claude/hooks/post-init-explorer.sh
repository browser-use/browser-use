#!/bin/bash
# Post-init-explorer hook
# This hook runs after the init-explorer agent completes
# It signals to the orchestrator that initialization is complete

echo "Init-explorer agent completed. Project context gathered and progress file updated."
echo "The next agent in the pipeline will now be invoked by init-explorer."
