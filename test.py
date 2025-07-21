import os
import sys
import io

# 设置UTF-8编码解决emoji显示问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 跳过LLM API密钥验证
os.environ['SKIP_LLM_API_KEY_VERIFICATION'] = 'true'
# 禁用遥测和云同步，避免404警告
os.environ['ANONYMIZED_TELEMETRY'] = 'false'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'

from browser_use.browser.browser import Browser, BrowserConfig

from browser_use import Agent
import asyncio
# from dotenv import load_dotenv
# load_dotenv()
from datetime import datetime
from browser_use.controller.service import Controller

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

myapikeys = "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"
openrouter_v1 = "https://openrouterai.aidb.site/api/v1"
llm = ChatOpenAI(model='meta-llama/llama-4-maverick', api_key=SecretStr(myapikeys), base_url=openrouter_v1)

planner_llm = ChatOpenAI(model='qwen/qwen2.5-32b-instruct', api_key=SecretStr(myapikeys), base_url=openrouter_v1)
# planner_llm = ChatOpenAI(model='google/gemma-3-27b-it', api_key=SecretStr(myapikeys), base_url=openrouter_v1)
# planner_llm= ChatOpenAI(model='deepseek/deepseek-chat-v3-0324', api_key=SecretStr(myapikeys), base_url=openrouter_v1)

custom_controller = Controller()
# 使用时间戳创建唯一路径
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_path = f"log/conversation_{timestamp}"

embeddings_file = r"D:\supie\202506\browser-use-RL\state_embedder\obsidian_20250626_144509_350746_scored_embeddings.json"

async def main():
    agent = Agent(
        task="to the website https://obsidian.md/changelog/, then summarize changes about obsidian from 1.6.7 to the current latest version, this 1.6.7 version must exist. IMPORTANT: This changelog likely uses pagination - the current page may only show recent versions. You MUST look for and use pagination buttons (Next, More, Load More, etc.) or page navigation to access older versions. Do not use extract_structured_data until you have confirmed all relevant versions are visible on the current page.",
        llm=llm,

        # planner_llm=planner_llm,  # Separate model for planning
        # use_vision_for_planner=False,  # Disable vision for planner
        # planner_interval=2  # Plan every 4 steps
        # controller=custom_controller,  # For custom tool calling
        # use_vision=True,  # Enable vision capabilities

        save_conversation_path=log_path,
        save_json_log_path="./json_logs",
        json_session_name="obsidian",

        enable_experience_retrieval=True,
        embeddings_file= embeddings_file,
        experience_similarity_threshold=0.7,
        experience_top_k=5
    )
    await agent.run()


#
asyncio.run(main())


