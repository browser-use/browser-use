import asyncio
import os
import json
from dotenv import load_dotenv
from base_agent import BaseAgent

# Load environment variables
load_dotenv()

async def main():
    # Get API key from environment or use the known working key
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        # Use the working API key directly
        api_key = "AIzaSyBOq5ih4A1MfVI3HMdpfMtSoePl1OAHX4E"
        print("Using hardcoded API key")
    else:
        print("Using API key from environment")

    # Create base agent
    print("Creating base agent...")
    base_agent = BaseAgent(
        api_key=api_key,
        model="gemini-2.0-flash",
        max_workers=5,  # Always 5 workers
        headless=False  # Set to False to make browser tabs visible
    )

    # Initialize base agent
    print("Initializing base agent...")
    await base_agent.initialize()

    # Define the main task (reduced to 2 people for API quotas)
    main_task = "Find the ages of Elon Musk and Mark Zuckerberg"

    # Process the task
    print(f"Processing main task: {main_task}")
    results = await base_agent.process_task(main_task)

    # Cleanup
    print("Cleaning up...")
    await base_agent.cleanup()

    # Print aggregated results from shared memory
    print("\n================ FINAL AGGREGATED RESULTS ================")
    
    # Show clean aggregated results
    print("\n🎯 CLEAN RESULTS:")
    print("=" * 50)
    for person, result in results.items():
        print(f"\n{person}:")
        print(f"  {result}")
    
    print("\n" + "=" * 50)

    # Save the shared memory contents to a JSON file
    save_shared_memory_to_file(results)
    
    # Save clean results to a simple file
    save_clean_results_to_file(results)

def save_shared_memory_to_file(results):
    """Save shared memory contents to a readable text file."""
    filename = "shared_memory_contents.txt"
    
    with open(filename, 'w') as f:
        f.write("SHARED MEMORY CONTENTS\n")
        f.write("=" * 50 + "\n\n")
        
        for key, value in results.items():
            f.write(f"KEY: {key}\n")
            f.write(f"TYPE: {type(value).__name__}\n")
            f.write(f"CONTENT:\n{str(value)}\n")
            f.write("-" * 50 + "\n\n")
    
    print(f"📁 Shared memory contents saved to: {filename}")
    print(f"📂 Full path: {os.path.abspath(filename)}")

def save_clean_results_to_file(results):
    """Save only the clean, final answers to a simple file."""
    filename = "final_answers.txt"
    
    with open(filename, 'w') as f:
        f.write("FINAL ANSWERS\n")
        f.write("=" * 30 + "\n\n")
        
        for person, result in results.items():
            # Extract the final clean answer
            if hasattr(result, 'all_results') and result.all_results:
                # Look for the final "done" result
                final_answer = None
                for action_result in reversed(result.all_results):
                    if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
                        if "was born on" in action_result.extracted_content and "years old" in action_result.extracted_content:
                            final_answer = action_result.extracted_content
                            break
                
                if final_answer:
                    f.write(f"{person}: {final_answer}\n\n")
                else:
                    f.write(f"{person}: No final answer found\n\n")
            else:
                f.write(f"{person}: {str(result)}\n\n")
    
    print(f"📄 Clean answers saved to: {filename}")
    print(f"📂 Full path: {os.path.abspath(filename)}")

if __name__ == "__main__":
    asyncio.run(main()) 