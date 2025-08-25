# Parallel Orchestrator for Browser-Use

A multi-agent system that automatically splits complex tasks into parallel subtasks and executes them simultaneously using Browser-Use.

## What It Does

Give it any task like "Find the ages of Elon Musk and Sam Altman" and it will:
1. Split the task into subtasks (one for each person)
2. Create worker agents to handle each subtask in parallel
3. Execute all subtasks simultaneously using browser automation
4. Combine the results into a final answer

## Features

- **Smart Task Splitting**: Uses AI to break down complex tasks into parallel subtasks
- **True Parallelism**: Runs multiple browser automation tasks at the same time
- **Beautiful Interface**: Real-time progress tracking with a clean terminal UI
- **Error Recovery**: Handles failures gracefully without stopping the entire process
- **Resource Management**: Automatically cleans up browser sessions

## Quick Start

1. **Install Browser-Use**:
   ```bash
   pip install browser-use
   ```

2. **Set your API key**:
   ```bash
   export GOOGLE_API_KEY='your-google-api-key-here'
   ```

3. **Run the system**:
   ```bash
   python3.11 parallel_orchestrator/real_interface.py
   ```

## Usage

### Interactive Mode
Run the interface and enter tasks interactively:
```bash
python3.11 parallel_orchestrator/real_interface.py
```

The system will show you:
- Real-time progress as workers execute tasks
- Final results in the terminal
- Option to run multiple tasks in sequence

### Programmatic Mode
```python
from parallel_orchestrator.base_agent import BaseAgent
import asyncio

async def main():
    base_agent = BaseAgent(
        api_key="your-api-key",
        model='gemini-1.5-flash',
        max_workers=10,
        headless=True
    )
    
    results = await base_agent.process_task("Find the ages of Elon Musk and Sam Altman")
    print(results)

asyncio.run(main())
```

## Example Tasks

The system works well with tasks that can be broken into parallel parts:

- "Find the ages of Elon Musk and Sam Altman"
- "When were Apple, Microsoft and Google founded?"
- "Compare Tesla and Ford stock prices"
- "Find weather in New York and Los Angeles"
- "Search for the top 3 AI companies and their CEOs"

## How It Works

1. **Task Analysis**: AI analyzes your task and determines how to split it
2. **Worker Creation**: Creates worker agents for each subtask
3. **Parallel Execution**: All workers run simultaneously using Browser-Use
4. **Result Collection**: Results are gathered and combined
5. **Final Output**: Clean, formatted answer is displayed in the terminal

## Configuration

- **API Key**: Set `GOOGLE_API_KEY` environment variable
- **Model**: Uses Gemini 1.5 Flash by default
- **Max Workers**: Up to 10 parallel workers (configurable)
- **Headless Mode**: Runs browsers in background by default

## Troubleshooting

- **API Key Issues**: Make sure `GOOGLE_API_KEY` is set correctly
- **Browser Problems**: Ensure Chrome/Chromium is installed
- **Rate Limits**: The system handles API limits gracefully

## Architecture

- **BaseAgent**: Orchestrates task splitting and result aggregation
- **WorkerAgent**: Executes individual subtasks using Browser-Use
- **SharedMemory**: Thread-safe communication between agents

## License

MIT License - same as Browser-Use 
