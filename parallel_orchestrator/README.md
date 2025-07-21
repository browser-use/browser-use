# Dynamic Parallel Orchestrator

A flexible, AI-driven parallel browser automation system that can handle any natural language task by automatically decomposing it into optimal subtasks and executing them with multiple worker agents.

## Features

- **Universal Task Handling**: Input any natural language prompt
- **AI-Driven Decomposition**: Automatically breaks down complex tasks into subtasks
- **Dynamic Worker Allocation**: Creates 1-10 browser workers based on task complexity
- **Parallel Execution**: Multiple workers run simultaneously for faster results
- **Clean Output**: AI-processed final results without technical bloat

## Setup

1. **Install Dependencies**:
   ```bash
   pip install browser-use langchain-google-genai
   ```

2. **Set Environment Variable**:
   ```bash
   export GOOGLE_API_KEY="your_gemini_api_key_here"
   ```

3. **Run the System**:
   ```bash
   python3.11 parallel_orchestrator/example.py
   ```

## Usage

1. Run the script
2. Enter any natural language task when prompted
3. The system will:
   - Analyze your task with AI
   - Create optimal number of workers
   - Execute tasks in parallel
   - Return clean, aggregated results

## Example Tasks

- "Find the ages of Elon Musk and Sam Altman"
- "Compare weather in New York, London, and Tokyo"
- "Research the latest AI developments from 5 companies"
- "Find contact information for 10 tech startups"

## Output Files

- `parallel_orchestrator/shared_answers.txt` - Raw worker results
- `parallel_orchestrator/final_answers.txt` - AI-cleaned final answers

## Architecture

- **Base Agent**: AI-driven task decomposition and result aggregation
- **Worker Agents**: Parallel browser automation for individual subtasks
- **Shared Memory**: Thread-safe communication between agents
- **Dynamic Scaling**: 1-10 workers based on task complexity

## Security

- No hardcoded API keys
- Uses environment variables only
- Safe for open source distribution 
