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

class FastDataApi:
    """External API service for making HTTP requests"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize the external API service
        
        Args:
            api_key: API key for authentication (if required)
        """
        self.base_url = base_url or os.getenv('FASTEST_DATA_HOST')
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

    async def extract_tables(self, content: str, source_url: str):
        data = {
            "html": content,
            "source_url": source_url
        }
        return await self._request("POST", '/api/v1/extract/structured-data-tables', data=data)

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
    fast_data_api = FastDataApi(base_url='https://xc-data.xcelsior.ai')
    result = await fast_data_api.extract_tables(content='<html><body><table><thead><th>x</th><th>y</th></thead><tr><td>1</td><td>2</td></tr></table></body></html>')
    #result.data: {'data': [{'table_index': 0, 'table': [{'x': '1', 'y': '2'}]}], 'error': None}
    print(result.data)


if __name__ == "__main__":
    asyncio.run(main())

