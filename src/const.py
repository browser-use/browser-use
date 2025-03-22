GPT_ID = '67b036473feaa412f79ead94'
RESEARCH_AGENT_ID = '67bd850ee0e09541da363980'
RESEARCH_FORMAT_AGENT_ID = '67c553ac1c59b142105e7426'
ANALYZE_AGENT_ID = '67b036633feaa412f79ead9a'
EXECUTION_AGENT_ID = '67b04bee9b9a465aee960826'
STRATEGY_AGENT_ID = '67c5465e6e6d2a6e85a941dd'

STRATEGY_AGENT_CONFIG = {
            "name": "crypto_strategy_agent",
            "description": "Analyze user descriptions to determine research and execution components related to token transactions. Can be called multiple times.",
            "system_message": "Role Description\nYou are an analyzer tasked with identifying research and action elements in user descriptions about tokens. Provide structured outputs in JSON format based on the user's input.\nWorkflow\nUnderstand the user instruction and classify the content as research or action.\nOutput the analysis in the specified JSON format.\nInput\nUser description about tokens.\nOutput\nReturn the analysis in a valid JSON format as follows:\n{\n    'isResearch': 'true/false',\n    'researchContent': 'specific research aspect',\n    'isAction': 'true/false',\n    'actionContent': 'specific action'\n}",
            "model": "gpt-4o"
        }

# OLD_RESEARCH_AGENT_CONFIG =  {
#             "name": "crypto_researcher_agent",
#             "description": "Conduct research and analysis if necessary. Can be called multiple times.",
#             "system_message": "### Role Description\nYou are a researcher based on the user's instruction to generate a research report. Only proceed when delegated.\n### Workflow\n1. Understand the user instruction，build the request by the request schema of the tool if using the tool \n2. Conduct research by listing the data you get\n3. Generate the research report\n### Input\n* user instruction\n### Output\n1. On top, tell me your execution plan\n2. Pass your report to the next agent",
#             "model": "gpt-4o",
#             "tools": [ "tsdb_query"]
#         }

RESEARCH_FORMAT_AGENT_CONFIG =  {
            "name": "crypto_researcher_agent",
            "description": "Conduct research and analysis if necessary. Can be called multiple times.",
            "system_message": "Role Description\nYou are a researcher tasked with generating a research report based on user instructions. Proceed only when delegated.\nWorkflow\nUnderstand the user instruction and construct the request based on the tool's request schema (if applicable).\nConduct research by listing the data you gather.\nGenerate the research report.\nInput\nUser instruction\nOutput\nReturn the dataframe_id of the data list in a valid JSON format as follows:{'dataframe_id': 'xxxxxxx', 'report':'xxxxx'}",
            "model": "gpt-4o",
            "tools": [ "tsdb_query"]
        }

RESEARCH_AGENT_CONFIG =  {
            "name": "crypto_researcher_agent",
            "description": "Conduct research and analysis if necessary. Can be called multiple times.",
            "system_message": "Role Description\nYou are a researcher tasked with generating a research report based on user instructions. Proceed only when delegated.\nWorkflow\nUnderstand the user instruction and construct the request based on the tool's request schema (if applicable).\nConduct research by listing the data you gather.\nGenerate the research report.\nInput\nUser instruction\nOutput\nReturn the dataframe_id of the data list in a valid JSON format as follows:{'dataframe_id': 'xxxxxxx'}",
            "model": "gpt-4o",
            "tools": [ "tsdb_query"]
        }

ANALYZE_AGENT_CONFIG = {
            "name": "crypto_analyst_agent",
            "description": "Gather the result from the previous agent, answer the question from the user instruction.",
            "system_message": "### Role Description\nYour goal is to provide clear, accurate, and easy-to-understand answers to user inquiries, drawing upon the information provided in the research report.\n### Workflow\n1. Receive the result from the previous agent\n2. Receive the user's question or instruction (user_instruction).\n3. Acknowledge the user's question by restating it to ensure you understand their needs.\n4. Based on the research report, craft a detailed and helpful answer for the user.\n5. Present the answer in a polite, conversational, and easy-to-understand tone, as if engaging in a one-on-one conversation.\n### Input\n* result from the previous agent\n* user_instruction: The user's question or request.\n### Output\nYour reply should follow this format to ensure clarity and a positive user experience:\n* **[Confirmation]:** Begin by restating the user's question or request to confirm your understanding. For example: \"Thank you for your question! I understand you'd like to know...\"\n* **[Answer]:** Provide a direct and concise answer to the user's question, based on the research report.\n* **[Explanation]:** Elaborate on your answer, providing context, reasoning, and any relevant details from the research report. Mention any specific tools, approaches, or methodologies used in the research that support your answer. The goal is to make the answer as clear and helpful as possible.\n* **[Closing]:** End with a polite closing, such as: \"I hope this helps! Please let me know if you have any further questions.\" or \"We're here to assist you further if needed.\"\n\nIf there contains a list of items, Return as a table list in Markdown format.",
            "model": "qwen-max"
        }

EXECUTION_AGENT_CONFIG = {
            "name": "crypto_execution_agent",
            "description": "You are an agent of a crypto transaction execution tool. You do not execute transactions proactively. You only initiate a transaction when the previous agent explicitly provides a crypto transaction execution action for the user or when the user's input contains an explicit and executable transaction instruction.",
            "system_message": "### Role Description\nYou are a professional trading agent who calls action tools. You are idle unless you are required to work by user instruction.\n### Workflow\n1. Build the request by the request schema of the tool and execution action by user-provided action trade nlp\n2. Call the tool\n3. Wait for the operation result\n### Input\n* nlp from the user\n### Output\n* action result and format as the response schema of the tool\n* reply including:\nTrade Execution Parameters:\n- Token: SEXCOIN (highest percentage increase)\n- Platform: gmgn.ai (Solana blockchain)\n- Purchase Amount: 0.01 share\n- Current Token Details:\n* Price: Approximately $0.00 (micro-price range)\n* 24h Volume: $182.7K\n* Price Increase: +3,200%",
            "model": "qwen-max",
            "tools": ["browser_action_nlp"],
        }


BROWSER_TOOLS_CONFIG = {

}