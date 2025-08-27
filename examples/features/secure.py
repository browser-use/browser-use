"""
Azure OpenAI example with data privacy and high-scale configuration.

Environment Variables Required:
- AZURE_OPENAI_KEY (or AZURE_OPENAI_API_KEY)
- AZURE_OPENAI_ENDPOINT
- AZURE_OPENAI_DEPLOYMENT (optional)

DATA PRIVACY WITH AZURE OPENAI:
✅ Good News: No Training on Your Data by Default

Azure OpenAI Service already protects your data:
✅ NOT used to train OpenAI models
✅ NOT shared with other customers
✅ NOT accessible to OpenAI directly
✅ NOT used to improve Microsoft/third-party products
✅ Hosted entirely within Azure (not OpenAI's servers)

⚠️ Default Data Retention (30 Days)
- Prompts and completions stored for up to 30 days
- Purpose: Abuse monitoring and compliance
- Access: Microsoft authorized personnel (only if abuse detected)

🔒 How to Disable Data Logging Completely
Apply for Microsoft's "Limited Access Program":
1. Contact Microsoft Azure support
2. Submit Limited Access Program request
3. Demonstrate legitimate business need
4. After approval: Zero data logging, immediate deletion, no human review

For high-scale deployments (500+ agents), consider:
- Multiple deployments across regions


How to Verify This Yourself, that there is no data logging:
- Network monitoring: Run with network monitoring tools
- Firewall rules: Block all domains except Azure OpenAI and your target sites

Contact us if you need help with this: support@browser-use.com
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

load_dotenv()


os.environ['ANONYMIZED_TELEMETRY'] = 'false'


from browser_use import Agent, BrowserProfile, ChatAzureOpenAI

# Configuration LLM
api_key = os.getenv('AZURE_OPENAI_KEY')
azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
llm = ChatAzureOpenAI(model='gpt-4.1-mini', api_key=api_key, azure_endpoint=azure_endpoint)

# Configuration Task
task = 'Find the founders of the sensitive company_name'

# Configuration Browser (optional)
browser_profile = BrowserProfile(allowed_domains=['*google.com', 'browser-use.com'], enable_default_extensions=False)

# Sensitive data (optional) - {key: sensitive_information} - we filter out the sensitive_information from any input to the LLM, it will only work with placeholder.
# By default we pass screenshots to the LLM which can contain your information. Set use_vision=False to disable this.
# If you trust your LLM endpoint, you don't need to worry about this.
sensitive_data: dict[str, str | dict[str, str]] = {'company_name': 'browser-use'}


# Create Agent
agent = Agent(task=task, llm=llm, browser_profile=browser_profile, sensitive_data=sensitive_data)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
