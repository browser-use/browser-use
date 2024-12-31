import asyncio
from langchain_openai import ChatOpenAI
from browser_use import Agent
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

async def main():
    # Get task from user
    print("\nWelcome to Browser-Use CLI!")
    print("----------------------------")
    task = input("\nPlease enter your task (e.g. 'Find flights from NYC to London'): ")
    
    # Initialize the agent
    try:
        agent = Agent(
            task=task,
            llm=ChatOpenAI(model="gpt-4o"),
        )
        
        print("\nExecuting task...")
        result = await agent.run()
        print("\nTask completed!")
        print("\nResult:", result)
        
        # Ask if user wants to exit
        exit_choice = input("\nDo you want to exit? (yes/no): ").lower()
        if exit_choice != 'yes':
            await main()  # Restart the main function if user doesn't want to exit
        
    except Exception as e:
        print(f"\nError occurred: {str(e)}")
        print("\nPlease make sure you have:")
        print("1. Set up your OPENAI_API_KEY in .env file")
        print("2. Installed all required dependencies")
        print("3. Installed playwright ('playwright install')")
        
        # Ask if user wants to exit even after error
        exit_choice = input("\nDo you want to exit? (yes/no): ").lower()
        if exit_choice != 'yes':
            await main()  # Restart the main function if user doesn't want to exit

if __name__ == "__main__":
    asyncio.run(main())
