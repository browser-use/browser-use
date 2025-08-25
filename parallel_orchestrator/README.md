# Browser Use Parallel Agents

A beautiful, interactive terminal interface for multi-agent browser orchestration using AI-driven task decomposition and parallel execution.

## 🚀 Features

- **Beautiful ASCII Art Banner** - Styled startup banner with grid-based text
- **Live Dashboard** - Real-time terminal interface with multiple panels
- **Task Queue Management** - Track all subtasks created by the base agent
- **Worker Agent Status** - Monitor up to 10 worker agents with live status updates
- **Shared Memory Output** - Live display of results from completed subtasks
- **Progress Tracking** - Visual progress bar showing completion status
- **Interactive Chat Interface** - Enter tasks and see results without closing the app
- **Clean Output Files** - Results saved to `final_answers.txt` for easy access

## 📋 Dashboard Panels

### Task Queue
- Shows all subtasks created by the base agent
- Status indicators: Pending ⏳ / Assigned 🔄 / Done ✅ / Failed ❌
- Task descriptions and assignment tracking

### Worker Agent Status
- Displays up to 10 worker agents
- Real-time status: Idle 💤 / Running 🔄 / Done ✅ / Failed ❌
- Progress tracking and retry attempts
- Current task assignments

### Shared Memory Output
- Live display of results from completed subtasks
- Truncated previews for long results
- Real-time updates as tasks complete

### Final Aggregated Output
- Clean, AI-processed final answers
- Formatted results ready for use
- Updates when all tasks are complete

### Progress Bar
- Visual progress indicator: ████░░░░░░ 4/10 tasks done
- Percentage completion tracking
- Real-time updates

## 🛠️ Installation

1. **Set your Gemini API key:**
```bash
export GOOGLE_API_KEY="your-actual-gemini-api-key-here"
```

2. **Install dependencies:**
```bash
pip install rich>=14.0.0
```

## 🎮 Usage

### Quick Start
```bash
python3.11 run_interface.py
```

### Manual Start
```bash
python3.11 terminal_interface.py
```

### Basic Example
```bash
python3.11 example.py
```

## 💬 Interactive Commands

Once the interface is running:

1. **Enter your task** - Type any natural language task
   ```
   Enter your task: Find the ages of Elon Musk and Sam Altman
   ```

2. **Watch the dashboard** - See real-time updates as:
   - Base Agent splits the task
   - Worker Agents are created
   - Tasks are assigned and executed
   - Results are aggregated

3. **View results** - See final answers in:
   - Terminal output
   - `final_answers.txt` file

4. **Continue chatting** - Enter 'q' to quit or enter another task

## 🎯 Example Tasks

- **"Find the ages of Elon Musk and Sam Altman"**
- **"Search for the latest iPhone and Samsung Galaxy prices"**
- **"Compare Tesla and Ford stock prices"**
- **"Find the weather in New York and Los Angeles"**
- **"Search for the top 3 AI companies and their CEOs"**

## 🔧 System Architecture

### Base Agent
- Uses AI to analyze and split complex tasks
- Creates optimal number of worker agents
- Aggregates results from all workers
- Generates clean, final answers

### Worker Agents
- Execute individual subtasks in parallel
- Use browser automation for web scraping
- Store results in shared memory
- Provide real-time status updates

### Shared Memory
- Thread-safe communication between agents
- Real-time status tracking
- Result storage and retrieval
- Dashboard data source

## 📊 Status Indicators

- **⏳ Pending** - Task created, waiting for assignment
- **🔄 Assigned** - Task assigned to worker, ready to run
- **🔄 Running** - Worker actively executing task
- **✅ Done** - Task completed successfully
- **❌ Failed** - Task failed with error
- **💤 Idle** - Worker available, no task assigned

## 🎨 Visual Features

- **Color-coded status** - Different colors for different states
- **Emoji indicators** - Visual status icons
- **Progress bars** - Visual completion tracking
- **Real-time updates** - Live dashboard refresh
- **Responsive layout** - Adapts to terminal size

## 🔍 Troubleshooting

### API Quota Issues
If you hit Gemini API quota limits:
- Wait for quota reset (midnight PT / noon Tbilisi time)
- Use a different API key
- Switch to a paid plan

### Browser Issues
If browser automation fails:
- Check internet connection
- Ensure Playwright is installed
- Try running in headless mode

### Import Errors
If you get import errors:
- Install missing dependencies: `pip install rich`
- Check you're in the correct directory
- Verify Python version (3.11+)

## 📝 Output Files

- **`final_answers.txt`** - Clean, formatted final results
- **`shared_memory_contents.txt`** - Detailed debug information
- **Terminal output** - Real-time dashboard and results

## 🚀 Advanced Usage

### Custom Tasks
The system can handle any natural language task that can be broken down into parallel subtasks:

- **Research tasks** - Find information about multiple topics
- **Comparison tasks** - Compare multiple items or services
- **Data collection** - Gather data from multiple sources
- **Monitoring tasks** - Check status of multiple systems

### Task Optimization
The Base Agent automatically:
- Analyzes task complexity
- Determines optimal number of workers
- Splits tasks for maximum parallelism
- Handles task dependencies

## 🎉 Success Stories

The system has successfully completed tasks like:
- Finding ages of multiple people in parallel
- Comparing stock prices across companies
- Researching multiple AI companies simultaneously
- Gathering weather data for multiple cities

## 🔮 Future Enhancements

- **Custom worker types** - Specialized agents for different tasks
- **Task scheduling** - Queue management for multiple tasks
- **Result caching** - Avoid re-running completed tasks
- **Advanced analytics** - Performance metrics and optimization
- **Web interface** - Browser-based dashboard option 
