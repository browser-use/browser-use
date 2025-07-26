import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from aiohttp import web  # make sure to install aiohttp: pip install aiohttp

from browser_use import Agent, Controller
from browser_use.llm import ChatOpenAI

# Define a simple HTML page
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Custom Select Div</title>
  <style>
    .custom-select {
      position: relative;
      width: 200px;
      font-family: Arial, sans-serif;
      margin-bottom: 20px;
    }

    .select-display {
      padding: 10px;
      border: 1px solid #ccc;
      background-color: #fff;
      cursor: pointer;
    }

    .select-options {
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      border: 1px solid #ccc;
      border-top: none;
      background-color: #fff;
      display: none;
      max-height: 150px;
      overflow-y: auto;
      z-index: 100;
    }

    .select-option {
      padding: 10px;
      cursor: pointer;
    }

    .select-option:hover {
      background-color: #f0f0f0;
    }
  </style>
</head>
<body>
  <div class="custom-select">
    <div class="select-display">Select a fruit</div>
    <div class="select-options">
      <div class="select-option" data-value="option1">Apples</div>
      <div class="select-option" data-value="option2">Oranges</div>
      <div class="select-option" data-value="option3">Pineapples</div>
    </div>
  </div>

  <div class="custom-select">
    <div class="select-display">Select a fruit</div>
    <div class="select-options">
      <div class="select-option" data-value="option1">Apples</div>
      <div class="select-option" data-value="option2">Oranges</div>
      <div class="select-option" data-value="option3">Pineapples</div>
    </div>
  </div>
  
  <div class="custom-select">
    <div class="select-display">Select a fruit</div>
    <div class="select-options">
      <div class="select-option" data-value="option1">Apples</div>
      <div class="select-option" data-value="option2">Oranges</div>
      <div class="select-option" data-value="option3">Pineapples</div>
    </div>
  </div>
  
  <div class="custom-select">
    <div class="select-display">Select a fruit</div>
    <div class="select-options">
      <div class="select-option" data-value="option1">Apples</div>
      <div class="select-option" data-value="option2">Oranges</div>
      <div class="select-option" data-value="option3">Pineapples</div>
    </div>
  </div>

  <label for="cars">Choose a car:</label>
  <select name="cars" id="cars">
    <option value="volvo">Volvo</option>
    <option value="bmw">BMW</option>
    <option value="mercedes">Mercedes</option>
    <option value="audi">Audi</option>
  </select>

  <button onclick="alert('I told you!')">Don't click me</button>

  <script>
    document.querySelectorAll('.custom-select').forEach(customSelect => {
      const selectDisplay = customSelect.querySelector('.select-display');
      const selectOptions = customSelect.querySelector('.select-options');
      const options = customSelect.querySelectorAll('.select-option');

      selectDisplay.addEventListener('click', (e) => {
        // Close all other dropdowns
        document.querySelectorAll('.select-options').forEach(opt => {
          if (opt !== selectOptions) opt.style.display = 'none';
        });

        // Toggle current dropdown
        const isVisible = selectOptions.style.display === 'block';
        selectOptions.style.display = isVisible ? 'none' : 'block';

        e.stopPropagation();
      });

      options.forEach(option => {
        option.addEventListener('click', () => {
          selectDisplay.textContent = option.textContent;
          selectDisplay.dataset.value = option.getAttribute('data-value');
          selectOptions.style.display = 'none';
        });
      });
    });

    // Close all dropdowns if clicking outside
    document.addEventListener('click', () => {
      document.querySelectorAll('.select-options').forEach(opt => {
        opt.style.display = 'none';
      });
    });
  </script>
</body>
</html>

"""


# aiohttp request handler to serve the HTML content
async def handle_root(request):
	return web.Response(text=HTML_CONTENT, content_type='text/html')


# Function to run the HTTP server
async def run_http_server():
	app = web.Application()
	app.router.add_get('/', handle_root)
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, 'localhost', 8000)
	await site.start()
	print('HTTP server running on http://localhost:8000')
	# Keep the server running indefinitely.
	await asyncio.Event().wait()


# Your agent tasks and other logic
controller = Controller()


async def main():
	# Start the HTTP server in the background.
	server_task = asyncio.create_task(run_http_server())

	# Example tasks for the agent.
	xpath_task = 'Open http://localhost:8000/, click element with the xpath "/html/body/div/div[1]" and then click on Oranges'
	css_selector_task = 'Open http://localhost:8000/, click element with the selector div.select-display and then click on apples'
	text_task = 'Open http://localhost:8000/, click the third element with the text "Select a fruit" and then click on Apples, then click the second element with the text "Select a fruit" and then click on Oranges'
	select_task = 'Open http://localhost:8000/, choose the car BMW'
	button_task = 'Open http://localhost:8000/, click on the button'

	llm = ChatOpenAI(model='gpt-4.1')
	# llm = ChatGoogleGenerativeAI(
	#     model="gemini-2.0-flash-lite",
	# )

	# Run different agent tasks.
	for task in [xpath_task, css_selector_task, text_task, select_task, button_task]:
		agent = Agent(
			task=task,
			llm=llm,
			controller=controller,
		)
		await agent.run()

	# Wait for user input before shutting down.
	input('Press Enter to close...')
	# Cancel the server task once finished.
	server_task.cancel()
	try:
		await server_task
	except asyncio.CancelledError:
		print('HTTP server stopped.')


if __name__ == '__main__':
	asyncio.run(main())
