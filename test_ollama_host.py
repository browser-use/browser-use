
import asyncio
from ollama import AsyncClient

async def main():
    print("--- Testing OllamaAsyncClient Host Resolution ---")
    try:
        # Test 1: Default (host=None)
        client_default = AsyncClient(host=None)
        # Accessing internal httpx client base_url to see what it resolved to
        # The structure might vary, but usually it's under _client
        base_url = getattr(client_default, '_client', None)
        if base_url:
            print(f"Default (host=None) base_url: {base_url.base_url}")
        else:
            print("Could not access _client on default client")

        # Test 2: Explicit
        client_explicit = AsyncClient(host="http://127.0.0.1:11434")
        base_url_exp = getattr(client_explicit, '_client', None)
        if base_url_exp:
            print(f"Explicit (host='http://127.0.0.1:11434') base_url: {base_url_exp.base_url}")

    except Exception as e:
        print(f"Error during investigation: {e}")

if __name__ == "__main__":
    asyncio.run(main())
