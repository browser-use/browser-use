# ============================================================
# Script to run eval/service.py sequentially with different configurations
# ============================================================

# --- Configuration ---

# Shared arguments that will be added to all configs
$addToAllConfigs = "--model llama-4-maverick --parallel_runs 1 --start 0 --end 100 --max_steps 25 --eval-group 'L4-tests'"

# List of complete argument strings to run (without shared args)
$evalConfigs = @(
    "--no-vision --user-message 'No Vision'",
    "--headless --user-message 'Headless'",
    "--no-vision --headless --user-message 'No Vision and Headless'",
    "--max_steps 50 --user-message 'Max Steps 50'"


)


    # gemini-1.5-flash
    # gemini-2.0-flash-lite
    # gemini-2.0-flash
    # gemini-2.5-flash-preview
    # gemini-2.5-pro
    # gpt-4.1-nano
    # gpt-4.1-mini
    # gpt-4
    # gpt-4.1
    # claude-3.5-sonnet-exp
    # claude-3.7-sonnet-exp
    # gemma2-9b-it
    # llama-3.3-70b-versatile
    # llama-3.1-8b-instant
    # llama3-70b-8192
    # llama3-8b-8192
    # llama-4-maverick
    # llama-4-scout



# Path to the evaluation script
$scriptPath = ".\eval\service.py" # Use relative path

# --- Execution Logic ---

Write-Host "Starting sequential evaluations..."
$startTimestamp = Get-Date

foreach ($config in $evalConfigs) {
    # Combine the specific config with shared args
    $fullConfig = "$config $addToAllConfigs"
    
    # Extract model name from the config string for logging purposes
    $model = if ($config -match "--model\s+(\S+)") { $matches[1] } else { "unknown" }
    
    Write-Host "--------------------------------------------------"
    Write-Host "Starting evaluation with config: $fullConfig"
    Write-Host "Time: $(Get-Date)"
    Write-Host "--------------------------------------------------"

    # Construct the log file name
    $logFileName = "eval/logs/output.$($model).log"

    # Build the command with the script path and full config
    $command = "python $scriptPath $fullConfig"

    Write-Host "Running command: $command"
    Write-Host "Redirecting output to: $logFileName"

    # Execute the Python script and wait for it to complete
    try {
        Invoke-Expression "$command *> $logFileName"
        Write-Host "Finished evaluation for config. Log: $logFileName"
    } catch {
        Write-Host "ERROR running evaluation for config: $fullConfig"
        Write-Host "Error details: $_"
    }
}

Write-Host "=================================================="
$endTimestamp = Get-Date
$duration = $endTimestamp - $startTimestamp
Write-Host "All evaluations complete."
Write-Host "Total duration: $($duration.ToString())"
Write-Host "=================================================="
