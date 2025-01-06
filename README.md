# Browser-Use CLI

A command-line interface tool that uses AI to automate browser-based tasks.

## Features

- Interactive CLI interface for task execution
- Powered by GPT-4 for intelligent browser automation
- Built with Playwright for reliable web automation
- Continuous operation mode with exit prompt

## Prerequisites

- Python 3.8 or higher
- OpenAI API key
- Playwright browser automation tool

## Installation

1. Clone the repository:
```bash
git clone https://github.com/PierrunoYT/browser-use-script
cd browser-use-script
```

2. Create and activate a virtual environment:

On Windows:
```bash
python -m venv venv
.\venv\Scripts\activate
```

On macOS/Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install required packages:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install
```

4. Set up environment variables:
   - Copy `.env.example` to `.env`
   - Add your OpenAI API key to `.env`
   - (Optional) Add Anthropic API key if using Claude models
   - Configure telemetry settings as needed

## Usage

1. Run the CLI:
```bash
python cli.py
```

2. Enter your task when prompted (e.g., "Find flights from NYC to London")

3. The tool will execute your task using browser automation

4. After task completion, you can:
   - View the detailed action history
   - Save results to a file
   - Continue with another task (enter "no" at exit prompt)
   - Exit the program (enter "yes" at exit prompt)

## Dependencies

All required dependencies are listed in `requirements.txt`:
- langchain
- langchain-openai
- python-dotenv
- browser-use
- playwright
- lxml
- lxml-html-clean

## Error Handling

If you encounter errors, ensure:
1. Your OpenAI API key is correctly set in `.env`
2. All dependencies are properly installed
3. Playwright browsers are installed

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
