from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from typing import Any, Type

async def call_llm(system_content: str, human_content: str, schema: Type[BaseModel]) -> Any:
    llm = ChatOpenAI(model_name="gpt-4o-mini")
    system_message = SystemMessage(content=system_content)
    human_message = HumanMessage(content=human_content)
    msg = [system_message, human_message]
    structured_llm = llm.with_structured_output(schema=schema, include_raw=True, method="function_calling")
    result = await structured_llm.ainvoke(msg)
    return result

async def call_llm_with_image(system_content: str, human_content: str, schema: Type[BaseModel], image_base64: str) -> Any:
    llm = ChatOpenAI(model_name="gpt-4o")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": system_content},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                }
            ],
        }
    ]
    result = llm.invoke(messages)
    return result