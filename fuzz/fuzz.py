from browser_use import Agent
import atheris
import sys

def TestOneInput(data):
    fdp = atheris.FuzzedDataProvider(data)
    task = fdp.ConsumeUnicodeNoSurrogates(100)
    api_key = fdp.ConsumeUnicodeNoSurrogates(50)
    model_name = fdp.ConsumeUnicodeNoSurrogates(50)

    try:
        agent = Agent(task=task)
        agent.run()
    except Exception as e:
        print(f"Exception occurred: {e}")

atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
