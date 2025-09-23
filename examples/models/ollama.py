# 1. Install Ollama: https://github.com/ollama/ollama
# 2. Run `ollama serve` to start the server
# 3. In a new terminal, install the model you want to use: `ollama pull llama3.1:8b` (this has 4.9GB)


from browser_use import Agent, ChatOllama

llm = ChatOllama(model='llama3.1:8b')

Agent('find the founders of browser-use', llm=llm).run_sync()
