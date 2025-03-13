import aiohttp
import logging
import asyncio
import os

from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class ApiResponse(BaseModel):
    """Base model for API responses"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: datetime = datetime.now()

class FastApi:
    """External API service for making HTTP requests"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize the external API service
        
        Args:
            api_key: API key for authentication (if required)
        """
        self.base_url = base_url or os.getenv('FASTEST_HOST', "https://api.fastest.ai")
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        # 设置默认超时时间（秒）
        self.timeout = aiohttp.ClientTimeout(total=36000)

    async def _ensure_session(self):
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers=self._get_headers(),
                timeout=self.timeout  # 添加超时设置
            )

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        timeout: Optional[float] = None  # 允许单个请求覆盖默认超时
    ) -> ApiResponse:
        """
        Send HTTP request
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint
            data: Request body data
            params: URL parameters
            timeout: Request timeout in seconds
        """
        await self._ensure_session()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.info(f"url ====> {url}")
        logger.info(f"reqyest data =====> {data}")

        # 使用请求特定的超时或默认超时
        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else self.timeout

        try:
            async with self.session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=request_timeout
            ) as response:
                content = await response.read()
                logger.info(f"content: {content}")
                response_data = await response.json()
                logger.info(f"response_data: {response_data}")
                
                if response.status >= 400:
                    return ApiResponse(
                        success=False,
                        error=f"API error: {response.status} - {response_data.get('message', 'Unknown error')}"
                    )
                
                return ApiResponse(
                    success=True,
                    data=response_data
                )
                
        except asyncio.TimeoutError:
            logger.error("Request timed out")
            return ApiResponse(
                success=False,
                error="Request timed out"
            )
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return ApiResponse(
                success=False,
                error=f"Request failed: {str(e)}"
            )

    async def get_chat_response(self, user_id: str, content: str, gpt_id: str, agent_ids: Optional[List[str]] = []) -> ApiResponse:
        """
        Get chat response from API
        
        Args:
            user_id: User identifier
            content: Message content
            gpt_id: GPT model identifier
        """
        data = {
            "messages": [{
                "content": content,
                "role": "user",
                "timestamp": int(datetime.now().timestamp())
            }],
            "user_id": user_id,
            "gpt_id": gpt_id,
            "use_agent": True
        }
        if len(agent_ids) > 0:
            data.update({"team": {"agent_ids": agent_ids}})

        now = datetime.now()
        result = await self._request("POST", "/v2/chat", data=data, timeout=360000)
        logger.info(f'time comuse ===> {datetime.now() - now}')
        return result

    async def create_gpt_user(self):
        """Create a new GPT user"""
        data = {}
        return await self._request("POST", "/v1/user/create", data=data)


    async def create_gpt(self):
        data = {
          "name": "MEME Coin Trader",
          "profile": {
            "persona": "You are a professional meme coin trader"
            }
        }
        return await self._request("POST",'/v1/gpt/create', data=data)


    async def delete_agent(self, gpt_id: str, agent_id: str):
        """Delete agent from API"""
        data = {
            "gpt_id": gpt_id,
            "agent_id": agent_id
        }
        return await self._request("POST",'/v1/agent/delete', data=data)

    async def create_agent(self, agent_conf: dict, gpt_id: str):
        agent_conf.update({'gpt_id': gpt_id})
        data ={
            "agent_config": agent_conf
        }
        logger.info(agent_conf)
        return await self._request("POST", '/v1/agent/create', data=data)

    async def gpt_register_tool(self, gpt_id: str):
        data ={
            "tools_config": {
                "gpt_id": gpt_id,
                "host": os.getenv("SELF_HOST"),
                "openapi_config": {"openapi":"3.1.0","info":{"title":"API Service","version":"0.1.0"},"paths":{"/api/v1/tool/browser_action_nlp":{"post":{"tags":["Tool"],"summary":"Browser Action Nlp","description":"Process natural language browser action descriptions\n\nThis endpoint receives natural language browser operation instructions \nand forwards them to the corresponding monitoring agent.\n\nParameters:\n    request: BrowserActionNlpRequest\n        - context: Context information\n            - gpt_id: GPT model ID\n            - user_id: User ID\n        - content: Natural language description of browser action\n\nReturns:\n    BrowserActionNlpResponse:\n        - status: Execution status (success/error)\n        - message: Execution message with operation details\n\nExample:\n    Request:\n        POST /api/v1/tool/browser_action_nlp\n        {\n            \"context\": {\n                \"gpt_id\": \"67ab0c86880303187f65d3a8\",\n                \"user_id\": \"user_123\"\n            },\n            \"content\": \"Click the login button on the page\"\n        }\n\n    Success Response:\n        {\n            \"status\": \"success\",\n            \"message\": \"start action: Click the login button on the page\"\n        }\n\n    Error Response:\n        {\n            \"detail\": \"Monitor Agent not found\"\n        }\n\nNotes:\n    - Ensure monitoring agent is registered before calling\n    - Natural language description should be clear and specific\n    - Valid GPT ID and user ID are required","operationId":"browser_action_nlp_api_v1_tool_browser_action_nlp_post","requestBody":{"content":{"application/json":{"schema":{"$ref":"#/components/schemas/BrowserActionNlpRequest"}}},"required":True},"responses":{"200":{"description":"Successfully processed browser action","content":{"application/json":{"schema":{"$ref":"#/components/schemas/BrowserActionNlpResponse"},"example":{"status":"success","message":"start action: Click the login button on the page"}}}},"422":{"description":"Validation Error","content":{"application/json":{"schema":{"$ref":"#/components/schemas/HTTPValidationError"}}}}}}}},"components":{"schemas":{"BrowserActionNlpRequest":{"properties":{"context":{"$ref":"#/components/schemas/ContextRequest","description":"Context information"},"content":{"type":"string","minLength":1,"title":"Content","description":"Natural language description of browser action","example":"Click the login button on the page"}},"type":"object","required":["context","content"],"title":"BrowserActionNlpRequest","description":"Request model for browser action natural language processing"},"BrowserActionNlpResponse":{"properties":{"status":{"type":"string","enum":["success","error"],"title":"Status","description":"执行状态","example":"success"},"message":{"type":"string","title":"Message","description":"执行消息","example":"start action: 点击页面上的登录按钮"}},"type":"object","required":["status","message"],"title":"BrowserActionNlpResponse","description":"浏览器动作执行响应"},"ContextRequest":{"properties":{"gpt_id":{"type":"string","title":"Gpt Id"},"user_id":{"type":"string","title":"User Id","description":"user id"}},"type":"object","required":["user_id"],"title":"ContextRequest"},"HTTPValidationError":{"properties":{"detail":{"items":{"$ref":"#/components/schemas/ValidationError"},"type":"array","title":"Detail"}},"type":"object","title":"HTTPValidationError"},"ValidationError":{"properties":{"loc":{"items":{"anyOf":[{"type":"string"},{"type":"integer"}]},"type":"array","title":"Location"},"msg":{"type":"string","title":"Message"},"type":{"type":"string","title":"Error Type"}},"type":"object","required":["loc","msg","type"],"title":"ValidationError"}}}}
            }
        }
        return await self._request("POST", '/v1/gpt/register_tools', data=data)

    async def run_agent(self, agent_id: str, task: str):
        data = {
            "id": agent_id,
            "task": task,
        }
        return await self._request("POST", '/v1/agent/run', data=data)

    async def tsdb_query(self, user_id: str, dataframe_id: str):
        data = {
            "user_id": user_id,
            "dataframe":{
                "id": dataframe_id,
            },
            "query": ""
        }
        return await self._request("POST", '/v1/tool/tsdb/query', data=data)

    async def tabby_parse(self, url: str, context: str):
        data = {
            "url": url,
            "context": context,
            "generate_summary": False
        }
        return await self._request("POST", '/v1/tool/tabby/parse', data=data)

    async def create_dataframe(self, user_id: str, url: str, table: list, entity_type: str | None):
        data = {
            "user_id": user_id,
            "entity_type": "token" if entity_type is None else entity_type,
            "timestamp": int(datetime.now().timestamp()),
            "source": url,
            "data": table
        }
        return await self._request("POST", '/v1/tool/tsdb/create', data=data)

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def __aenter__(self):
        """Async context manager entry point"""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit point"""
        await self.close()

async def main():
    from src.const import GPT_ID, STRATEGY_AGENT_CONFIG, RESEARCH_FORMAT_AGENT_CONFIG
    fastapi = FastApi(base_url='https://api-dev.fastest.ai')
    result = await fastapi.create_agent(gpt_id='679095f2053c84baac0faa99', agent_conf=RESEARCH_FORMAT_AGENT_CONFIG)
    # result = await fastapi.delete_agent(GPT_ID, '67bd30729d7985a254ed05c2')
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

