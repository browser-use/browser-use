# Browser Task Automation with Gemini AI 🤖

A powerful web automation application that combines Google's Gemini AI with browser automation capabilities to perform intelligent web tasks through natural language instructions.

![Browser Task Automation Demo](1.png)

## Features ✨

- 🧠 Natural Language Task Processing
- 🌐 Automated Browser Control
- 🎯 User-friendly Gradio Interface
- 🔒 Secure API Key Handling
- 📊 Rich Task History Visualization
- 🤖 Multiple Gemini AI Models Support

## Prerequisites 📋

Before running the application, ensure you have Python installed and the following dependencies:

```bash
gradio>=4.0.0
python-dotenv>=1.0.0
langchain-google-genai>=0.0.5
rich>=13.7.0
pydantic>=2.0.0
browser-use>=0.1.0
playwright>=1.40.0
```

## Installation 🚀

1. Clone the repository:
   ```bash
   git clone https://github.com/falahgs/browser_task_automation.git
   cd browser-task-automation
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root and add your Gemini API key:
   ```
   GEMINI_API_KEY=your_api_key_here
   ```

## Usage 💡

1. Start the application:
   ```bash
   python app-gradio.py
   ```

2. Open your browser and navigate to `http://localhost:7860`

3. Enter your Gemini API key in the secure input field

4. Choose a task type from the examples or write your own task description

5. Select your preferred Gemini model:
   - gemini-1.5-flash-latest
   - gemini-2.0-flash-exp
   - gemini-1.5-flash-002
   - gemini-1.5-flash-8b
   - gemini-1.5-pro-latest
   - gemini-1.5-pro-002
   - gemini-exp-1206

6. Click "Run Task" and watch as the AI performs your requested task

## Example Tasks 📝

### Web Research
- Find latest AI news on TechCrunch
- Compare prices for iPhone 15 Pro
- Research climate change statistics

### Data Collection
- Extract product reviews from Amazon
- Gather contact info from company websites
- Collect real estate listings data

### Automation
- Fill out contact forms
- Schedule appointments
- Monitor price changes

## Project Structure 📁

```
browser-task-automation/
├── app-gradio.py        # Main application file
├── requirements.txt     # Project dependencies
├── .env                # Environment variables (create this)
└── .gitignore         # Git ignore rules
```

## Features in Detail 🔍

### AI-Powered Browser Control
The application uses Gemini AI to understand natural language task descriptions and convert them into browser automation sequences.

### Rich Task History
Track the progress of your tasks with detailed history logging and formatted console output.

### Secure API Handling
API keys are securely handled using environment variables and secure input fields.

### Modern UI
Clean, responsive interface built with Gradio, featuring:
- Intuitive task input
- Model selection
- Real-time output display
- Example task suggestions

## Contributing 🤝

Contributions are welcome! Feel free to:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License 📄

This project is licensed under the MIT License - see the LICENSE file for details.

## Author ✍️

**Falah G. Salieh**

## Acknowledgments 🙏

- Google Gemini AI for providing the language model
- Gradio for the web interface framework
- Browser Use AI Agent for automation capabilities

---
Made with ❤️ using Python and Gemini AI
