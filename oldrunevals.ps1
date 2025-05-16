# ============================================================
# Script to run eval/service.py sequentially with different models
# ============================================================

# --- Configuration ---

# List of models to evaluate (modify this list as needed)
$modelsToRun = @(
    # "gemini-1.5-flash",
    # "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    # "gemini-2.5-flash-preview",
    "gemini-2.5-pro",
    # "gemini-2.5-pro-preview-05-06"
    # "gpt-4.1-nano",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4.1",

    "claude-3.5-sonnet-exp"
    # "claude-3.7-sonnet-exp"

    # "gemma2-9b-it",
    # "llama-3.3-70b-versatile",
    # "llama-3.1-8b-instant",
    # "llama3-70b-8192",
    # "llama3-8b-8192"

    # "llama-4-maverick",
    # "llama-4-scout"
)

# Common parameters for the evaluation script
$commonParams = @{
    parallel_runs = 1
    start = 0
    end = 100
    max_steps = 25
}

# Path to the evaluation script
$scriptPath = ".\eval\service.py" # Use relative path

# --- Execution Logic ---

Write-Host "Starting sequential evaluations..."
$startTimestamp = Get-Date

foreach ($model in $modelsToRun) {
    Write-Host "--------------------------------------------------"
    Write-Host "Starting evaluation for model: $model"
    Write-Host "Time: $(Get-Date)"
    Write-Host "--------------------------------------------------"

    # Construct the log file name
    $logFileName = "eval/logs/output.$($model).log"

    # Build the arguments array dynamically
    $arguments = @($scriptPath)
    $commonParams.GetEnumerator() | ForEach-Object {
        # Handle boolean flags (like --headless)
        if ($_.Value -is [bool]) {
            if ($_.Value -eq $true) {
                $arguments += "--$($_.Name)"
            }
            # If $false, we don't add the flag
        } else {
            # Handle flags with values
            $arguments += "--$($_.Name)", "$($_.Value)"
        }
    }
    # Add the model-specific argument
    $arguments += "--model", $model
    # $arguments += "--eval_model", "gemini-2.5-pro"
    $arguments += "--user-message", "No Vision"
    $arguments += "--no-vision"

    Write-Host "Running command: python $($arguments -join ' ')"
    Write-Host "Redirecting output to: $logFileName"

    # Execute the Python script and wait for it to complete.
    try {
        python @arguments *> $logFileName
        Write-Host "Finished evaluation for model: $model. Log: $logFileName"
    } catch {
        Write-Host "ERROR running evaluation for model: $model"
        Write-Host "Error details: $_"
    }
}

Write-Host "=================================================="
$endTimestamp = Get-Date
$duration = $endTimestamp - $startTimestamp
Write-Host "All evaluations complete."
Write-Host "Total duration: $($duration.ToString())"
Write-Host "=================================================="
