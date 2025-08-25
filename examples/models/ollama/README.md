# Ollama Examples with browser-use

This directory contains examples of using Ollama with browser-use.

## Basic Example

The [example.py](./example.py) file shows how to use the `BrowserUseOllama` wrapper class that was added to fix compatibility issues with browser-use 0.4.2+.

## Available Ollama Models

You can use any model available in your local Ollama installation, including:
- llama3
- mistral
- qwen3:14b
- codellama
- and more

To list available models:
```bash
ollama list
```

To pull a new model:
```bash
ollama pull qwen3:14b
```

See [Ollama's documentation](https://github.com/ollama/ollama) for more details.
