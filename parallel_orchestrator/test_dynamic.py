import asyncio
import os
from base_agent import BaseAgent

async def main():
    """Test the dynamic parallel orchestrator with a single task."""
    
    # Get API key from environment
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set")
        return
    
    # Create base agent
    base_agent = BaseAgent(
        api_key=api_key,
        model="gemini-1.5-flash",
        max_workers=5,
        headless=False
    )
    
    await base_agent.initialize()
    
    # Test with a simple task that should create 2 workers
    print("\n" + "="*60)
    print("TESTING DYNAMIC TASK DECOMPOSITION")
    print("="*60)
    
    task = "Find the ages of Elon Musk and Sam Altman"
    print(f"Task: {task}")
    print("Expected: 2 workers (one for each person)")
    
    try:
        results = await base_agent.process_task(task)
        print("\n✅ SUCCESS! Results:")
        print("="*40)
        for key, result in results.items():
            print(f"\n{key}:")
            print(f"  {result}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Cleanup
    await base_agent.cleanup()
    
    print("\n" + "="*60)
    print("TEST COMPLETED")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main()) 