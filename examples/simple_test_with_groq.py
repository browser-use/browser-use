import asyncio
import os
import argparse
import subprocess
import time
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import SecretStr
import logging

from browser_use import Agent, Browser, BrowserConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a filter to suppress retry messages
class RetryFilter(logging.Filter):
    def filter(self, record):
        # Filter out "Retrying request" messages
        return "Retrying request" not in record.getMessage()

# Apply filter to groq logger
groq_logger = logging.getLogger("groq._base_client")
groq_logger.addFilter(RetryFilter())

# Load environment variables
load_dotenv()

# Get Groq API key from environment variable or use the provided one
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Default Chrome debugging port
DEFAULT_CHROME_DEBUG_PORT = 9222

# List of available Groq models based on the provided list
# Ordered to minimize rate limit issues and optimize for browser automation tasks
GROQ_MODELS = [
    # Start with less commonly used models to avoid rate limits
    "gemma2-9b-it",              # Good for instruction following
    "llama-guard-3-8b",          # Alternative option
    "mistral-saba-24b",          # Alternative model family
    "llama3-8b-8192",            # Good balance of speed and capability
    "compound-beta-mini",        # Less commonly used
    "deepseek-r1-distill-llama-70b", # Specialized model
    "llama-3.3-70b-versatile",   # More powerful but might be slower
    "llama3-70b-8192",           # Most powerful option
    # Popular models that might hit rate limits more often
    "llama-3.1-8b-instant"       # Fast but popular (more likely to hit rate limits)
]

def launch_chrome_with_debugging(chrome_path, debug_port=DEFAULT_CHROME_DEBUG_PORT):
    """Launch Chrome with remote debugging enabled"""
    try:
        # Check if Chrome is already running with debugging
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', debug_port))
        sock.close()

        if result == 0:
            print(f"Chrome already running with debugging on port {debug_port}")
            return True

        # Launch Chrome with debugging enabled
        print(f"Launching Chrome with remote debugging on port {debug_port}")

        # Verify the Chrome path exists
        if not os.path.exists(chrome_path):
            print(f"Chrome executable not found at: {chrome_path}")
            # Try to find Chrome in the default location
            default_path = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            if os.path.exists(default_path):
                print(f"Using default Chrome path: {default_path}")
                chrome_path = default_path
            else:
                print("Could not find Chrome executable")
                return False

        chrome_args = [
            chrome_path,
            f"--remote-debugging-port={debug_port}",
            "--no-first-run",
            "--no-default-browser-check"
        ]

        subprocess.Popen(chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Wait for Chrome to start
        time.sleep(2)

        # Verify Chrome is running with debugging enabled
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', debug_port))
        sock.close()

        if result == 0:
            print(f"Successfully launched Chrome with debugging on port {debug_port}")
            return True
        else:
            print(f"Failed to launch Chrome with debugging on port {debug_port}")
            return False
    except Exception as e:
        print(f"Error launching Chrome: {e}")
        return False

class ModelFallbackAgent:
    """Agent that tries multiple models with fallback"""

    def __init__(self, task, browser, models=None, use_vision=False):
        self.task = task
        self.browser = browser
        self.use_vision = use_vision
        self.models = models or GROQ_MODELS
        self.current_model_index = 0
        self.max_retries = 3
        self.consecutive_failures = 0  # Track consecutive failures

    async def run(self, max_steps=20):
        """Run the agent with model fallback"""
        while self.current_model_index < len(self.models):
            model_name = self.models[self.current_model_index]
            logger.info(f"Trying model: {model_name}")

            try:
                # Create LLM with current model
                llm = ChatGroq(
                    model=model_name,
                    api_key=SecretStr(GROQ_API_KEY),
                    timeout=30,  # Shorter timeout - we'll switch models faster
                    max_retries=0  # Don't retry - just move to next model instead
                )

                # Create and run agent
                agent = Agent(
                    task=self.task,
                    llm=llm,
                    browser=self.browser,
                    use_vision=self.use_vision,
                )

                # Patch the agent's run method to handle rate limit errors better
                original_run = agent.run

                async def patched_run(*args, **kwargs):
                    try:
                        return await original_run(*args, **kwargs)
                    except Exception as e:
                        error_msg = str(e)
                        if "429" in error_msg or "rate limit" in error_msg.lower():
                            # Convert rate limit errors to a specific exception
                            raise Exception(f"Rate limit exceeded: {error_msg}")
                        # Re-raise other exceptions
                        raise

                agent.run = patched_run

                # Set a timeout for the entire agent run
                try:
                    # Create a task with timeout
                    agent_task = asyncio.create_task(agent.run(max_steps=max_steps))

                    # Set up a shorter timeout for initial response
                    initial_timeout = 30  # 30 seconds for initial response
                    full_timeout = 120     # 2 minutes overall

                    # First, wait for a short time to see if the model responds quickly
                    try:
                        return await asyncio.wait_for(agent_task, timeout=initial_timeout)
                    except asyncio.TimeoutError:
                        # If it takes longer than the initial timeout but hasn't failed,
                        # print a message but continue waiting up to the full timeout
                        print(f"\n⏳ Model {model_name} is taking longer than expected. Will wait up to {full_timeout-initial_timeout} more seconds...")
                        try:
                            return await asyncio.wait_for(agent_task, timeout=full_timeout-initial_timeout)
                        except asyncio.TimeoutError:
                            logger.warning(f"Model {model_name} timed out after {full_timeout} seconds. Switching to next model.")
                            raise Exception("Model timeout - switching to next model")
                except asyncio.TimeoutError:
                    logger.warning(f"Model {model_name} timed out. Switching to next model.")
                    raise Exception("Model timeout - switching to next model")

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error with model {model_name}: {error_msg}")

                # Check for specific API errors
                if "401" in error_msg or "authentication" in error_msg.lower():
                    logger.error("API key authentication error. Please check your GROQ_API_KEY.")
                    print("\nAPI KEY ERROR: Please set a valid GROQ_API_KEY environment variable.")
                    print("You can get a key from https://console.groq.com/\n")
                    raise Exception("Invalid Groq API key")

                # Check for rate limit errors
                if "429" in error_msg or "rate limit" in error_msg.lower() or "rate_limit_exceeded" in error_msg.lower():
                    logger.warning(f"Rate limit reached for model {model_name}. Immediately switching to next model.")
                    print(f"\n⚠️ RATE LIMIT: Model {model_name} has reached its rate limit. Switching to next model...")
                    # Skip to the next model immediately without going through the rest of the error handling
                    self.current_model_index += 1
                    self.consecutive_failures = 0  # Reset failure counter when switching models

                    if self.current_model_index >= len(self.models):
                        logger.error("All models failed. Giving up.")
                        print("\nAll Groq models failed. Please try again later or check your API key and internet connection.")
                        raise Exception("All models failed to complete the task")

                    next_model = self.models[self.current_model_index]
                    logger.info(f"Falling back to next model: {next_model}")
                    print(f"\n⚠️ Rate limit hit for {model_name}. Switching to {next_model}...")
                    continue  # Skip to the next iteration of the while loop

                # Check for retry messages or timeouts
                elif "Retrying request" in error_msg or "timeout" in error_msg.lower():
                    logger.warning(f"Model {model_name} is experiencing delays. Immediately switching to next model.")
                    # Continue to next model without additional logging

                # Try next model
                self.current_model_index += 1
                self.consecutive_failures = 0  # Reset failure counter when switching models

                if self.current_model_index >= len(self.models):
                    logger.error("All models failed. Giving up.")
                    print("\nAll Groq models failed. Please try again later or check your API key and internet connection.")
                    raise Exception("All models failed to complete the task")

                next_model = self.models[self.current_model_index]
                logger.info(f"Falling back to next model: {next_model}")
                print(f"\n⚠️ Model {model_name} failed or timed out. Switching to {next_model}...")

async def run_browser_task(task, max_steps=20, use_existing_browser=False, chrome_path="C:\Program Files\Google\Chrome\Application\chrome.exe"):
    """Run a browser task with the given prompt"""
    print(f"Running task: {task}")

    # Print information about the configuration
    print("\n=== Browser Automation Configuration ===")
    if use_existing_browser:
        print(f"- Using existing Chrome browser with debugging on port {DEFAULT_CHROME_DEBUG_PORT}")
    else:
        print("- Launching new browser instance")
    print(f"- Maximum steps: {max_steps}")
    print("- Using Groq API for language model")

    # Show model information
    if len(GROQ_MODELS) == 1:
        print(f"- Using model: {GROQ_MODELS[0]}")
    else:
        print(f"- Starting with model: {GROQ_MODELS[0]}")
        print(f"- Will try {len(GROQ_MODELS)} models in sequence if needed")
        if len(GROQ_MODELS) > 3:
            fallbacks = ", ".join(GROQ_MODELS[1:4])
            print(f"- Fallback models: {fallbacks}...")
        else:
            fallbacks = ", ".join(GROQ_MODELS[1:])
            print(f"- Fallback models: {fallbacks}")

    # Configure browser
    browser_config_args = {
        "headless": False,  # Make browser visible
    }

    # If using existing browser, update config
    if use_existing_browser and chrome_path:
        print(f"Using existing Chrome browser at: {chrome_path}")

        # Launch Chrome with debugging if needed
        if launch_chrome_with_debugging(chrome_path):
            # Connect to the existing Chrome instance using CDP
            browser_config_args["cdp_url"] = f"http://localhost:{DEFAULT_CHROME_DEBUG_PORT}"
        else:
            # Fallback to using browser_binary_path
            browser_config_args["browser_binary_path"] = chrome_path

    # Create browser with config
    browser_config = BrowserConfig(**browser_config_args)
    browser = Browser(config=browser_config)

    try:
        # Create fallback agent with all models
        fallback_agent = ModelFallbackAgent(
            task=task,
            browser=browser,
            use_vision=False
        )

        # Run the agent with fallback
        await fallback_agent.run(max_steps=max_steps)
    finally:
        # Close browser when done
        await browser.close()

def get_user_prompt():
    """Get a custom prompt from the user"""
    print("\n=== Browser Automation Prompt Interface ===")
    print("Enter your task for the browser to perform:")
    print("(Press Enter to use the default task)")

    user_input = input("> ").strip()

    if not user_input:
        return "Go to google.com and search for 'browser-use github'"

    return user_input

if __name__ == '__main__':
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(description='Run a browser automation task using Groq LLM')
    parser.add_argument('--task', type=str,
                        help='The task to perform (if not provided, will prompt for input)')
    parser.add_argument('--steps', type=int, default=20,
                        help='Maximum number of steps to run (default: 20)')
    parser.add_argument('--use-existing-browser', action='store_true',
                        help='Use existing Chrome browser instead of launching a new one')
    parser.add_argument('--chrome-path', type=str,
                        default="C:/Program Files/Google Chrome/Application/chrome.exe",
                        help='Path to Chrome executable (default: standard Chrome installation path)')
    parser.add_argument('--prompt', action='store_true',
                        help='Show prompt interface for entering a task')
    parser.add_argument('--model', type=str,
                        help='Specify a Groq model to try first (if not in the default list, will be added)')
    parser.add_argument('--only-model', action='store_true',
                        help='Use only the specified model without fallbacks')

    # Parse arguments
    args = parser.parse_args()

    # Get the task - either from command line, prompt interface, or default
    task = args.task
    if task is None or args.prompt:
        task = get_user_prompt()

    # If a specific model is requested
    if args.model:
        # Check if the model is in our list
        if args.model not in GROQ_MODELS:
            # If not, add it to the beginning of the list
            print(f"Adding custom model to the beginning of the model list: {args.model}")
            GROQ_MODELS.insert(0, args.model)
        else:
            # If it's in the list, move it to the beginning
            GROQ_MODELS.remove(args.model)
            GROQ_MODELS.insert(0, args.model)

        # Only use this model if --only-model flag is set
        if args.only_model:
            print(f"Using only the specified model: {args.model}")
            GROQ_MODELS = [args.model]

    # Run the task
    asyncio.run(run_browser_task(
        task=task,
        max_steps=args.steps,
        use_existing_browser=args.use_existing_browser,
        chrome_path=args.chrome_path
    ))

