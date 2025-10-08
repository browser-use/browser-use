# from dotenv import load_dotenv
# import os
# from browser_use import Agent, ChatGoogle

# # Load .env explicitly from project root
# load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# api_key = os.getenv("GOOGLE_API_KEY")
# print("GOOGLE_API_KEY loaded:", bool(api_key))
# if not api_key:
#     raise RuntimeError("GOOGLE_API_KEY not found!")

# # Pick a model from your available list
# agent = Agent(
#     task='Find the number of stars of the browser-use repo',
#     llm=ChatGoogle(model='gemini-2.5-flash'),  # chosen stable model
# )

# try:
#     agent.run_sync()
# except Exception as e:
#     print("Agent failed with error:", e)








from dotenv import load_dotenv

import os
print("GOOGLE_API_KEY loaded:", os.getenv("GOOGLE_API_KEY") is not None)


from browser_use import Agent, ChatGoogle

load_dotenv()

agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=ChatGoogle(model='gemini-2.5-flash'),

	# browser=Browser(use_cloud=True),  # Uses Browser-Use cloud for the browser
)

try:
    agent.run_sync()
except Exception as e:
    print("Agent failed with error:", e)


