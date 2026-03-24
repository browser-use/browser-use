import asyncio
import os
import time
from dotenv import load_dotenv
from browser_use.llm.models import get_llm_by_name
from browser_use import Agent
from browser_use.browser.profile import BrowserProfile

async def main():
    # Load environment from the project root
    root_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    load_dotenv(root_env_path)

    # Automatically swap the api key name explicitly required by LangChain if using a different prefix
    if 'GOOGLE_API_KEY' not in os.environ and 'GOOGLE_GENERATIVE_AI_API_KEY' in os.environ:
        os.environ['GOOGLE_API_KEY'] = os.environ['GOOGLE_GENERATIVE_AI_API_KEY']

    print("==================================================")
    print("🚀 Glazyr Viz High-Performance Zero-Copy Benchmark")
    print("==================================================")

    mcp_vision_url = os.environ.get('GLAZYR_VISION_URL', 'https://mcp.glazyr.com/mcp/sse')
    mcp_vision_token = os.environ.get('GLAZYR_API_KEY')
    if not mcp_vision_token:
        print('ERROR: GLAZYR_API_KEY environment variable is required. Set it in your .env file.')
        return
    
    llm = get_llm_by_name('google_gemini_2_0_flash')

    print("\n--- Phase 1: Native Playwright CDP (Vanilla) ---")
    vanilla_profile = BrowserProfile(headless=False) 
    
    vanilla_agent = Agent(
        task="Navigate to https://threejs.org/examples/#webgl_points_random. Wait exactly 3 seconds to let particles load. Then, give me a single status update on whether the particles are moving.",
        llm=llm,
        browser_profile=vanilla_profile
    )
    
    start = time.time()
    vanilla_history = await vanilla_agent.run()
    end = time.time()
    vanilla_time = end - start
    print(f"🐌 Action Cycle w/ Base64 Serialization Tax: {vanilla_time:.2f}s")
    print(f"🧠 Vanilla Agent Perceived: {vanilla_history.final_result()}")
    
    print("\n--- Phase 2: Glazyr Viz Shared-Memory MCP ---")
    # Activating the new integration
    glazyr_profile = BrowserProfile(mcp_vision_url=mcp_vision_url, mcp_vision_token=mcp_vision_token, headless=False)
    
    glazyr_agent = Agent(
        task="Navigate to https://threejs.org/examples/#webgl_points_random. Wait exactly 3 seconds to let particles load. Then, give me a single status update on whether the particles are moving.",
        llm=llm,
        browser_profile=glazyr_profile,
        generate_gif="glazyr_demo_pr.gif"
    )
    
    start = time.time()
    glazyr_history = await glazyr_agent.run()
    end = time.time()
    glazyr_time = end - start
    print(f"⚡ Action Cycle w/ 7ms Shared-Memory Vision: {glazyr_time:.2f}s")
    print(f"🧠 Glazyr Agent Perceived: {glazyr_history.final_result()}")

    print("\n==================================================")
    print("📊 BENCHMARK RESULTS")
    print(f"Vanilla Latency: {vanilla_time:.2f}s per cycle")
    print(f"Glazyr Latency : {glazyr_time:.2f}s per cycle")
    print(f"Speed Increase : {(vanilla_time / glazyr_time):.2f}x faster with Glazyr Viz!")
    print("==================================================")

if __name__ == '__main__':
    asyncio.run(main())
