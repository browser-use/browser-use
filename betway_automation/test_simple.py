import asyncio
import os
from langchain_anthropic import ChatAnthropic
from browser_use import Agent

# Fix the import to work when running the script directly
try:
    from .controller import BetWayController
except ImportError:
    # Fallback for when running the script directly
    from controller import BetWayController


async def test_controller_registration():
    """
    Simple test to verify our controller and actions are registered correctly.
    """

    # Ensure you have your ANTHROPIC_API_KEY in your environment
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ Please set the ANTHROPIC_API_KEY environment variable.")
        return

    print("🧪 Testing BetWay Controller Registration...")

    # Create our specialized controller
    betway_controller = BetWayController()

    # Print available actions to see if our custom ones are registered
    print("\n📋 Available Actions:")
    print("=" * 50)

    # Check if our custom actions are available
    print("🔍 Checking controller registry...")
    print(f"Registry type: {type(betway_controller.registry)}")
    print(f"Registry attributes: {dir(betway_controller.registry)}")

    # Check if controller has actions
    if hasattr(betway_controller, "_registry"):
        print(f"Controller has _registry: {type(betway_controller._registry)}")

    print("✅ BetWayController created successfully!")

    # Create the LLM
    llm = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0)

    # Use absolute path for conversation saving
    conversation_path = os.path.join(os.getcwd(), "betway_simple_test.json")
    print(f"💾 Will save conversation to: {conversation_path}")

    # Test with a simple task that should trigger our login action
    agent = Agent(
        task="Go to www.betway.co.za and login to log in with username '0719368774' and password '98025'.",
        llm=llm,
        controller=betway_controller,
        use_vision=True,
        save_conversation_path=conversation_path,
    )

    try:
        print("🚀 Starting simple agent test...")
        result = await agent.run(max_steps=3)  # Limit steps for testing

        print("\n" + "=" * 50)
        print("🎯 SIMPLE TEST COMPLETED")
        print("=" * 50)
        print(f"Result: {result}")

    except Exception as e:
        print(f"❌ Error during agent execution: {e}")


if __name__ == "__main__":
    print("🔧 BetWay Controller Registration Test")
    print("=" * 40)

    # Run the test
    asyncio.run(test_controller_registration())
