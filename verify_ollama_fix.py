
import asyncio
from browser_use.llm.ollama.chat import ChatOllama

async def main():
    print("--- Verifying ChatOllama Default Host Fix ---")
    try:
        # Initialize ChatOllama without providing host
        chat = ChatOllama(model="llama3.1:8b")
        
        # Check the host property on the wrapper
        print(f"ChatOllama.host: {chat.host}")
        
        if chat.host != 'http://127.0.0.1:11434':
            print("FAIL: ChatOllama.host default is NOT http://127.0.0.1:11434")
            exit(1)
            
        # Get the client and check its configuration
        client = chat.get_client()
        base_url = getattr(client, '_client', None).base_url if hasattr(client, '_client') else None
        
        print(f"Client base_url: {base_url}")
        
        if str(base_url).rstrip('/') != 'http://127.0.0.1:11434':
            # Note: httpx.URL might have a trailing list, so string comparison should handle that
            print(f"FAIL: Client base_url {base_url} does not match expected http://127.0.0.1:11434/")
            exit(1)
            
        print("PASS: ChatOllama defaults to explicit local host.")

    except Exception as e:
        print(f"Error during verification: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
