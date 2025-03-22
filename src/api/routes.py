import asyncio
import json
import pydash
import logging
import time
import base64
import zlib
import pandas

from src.api.file_context import convert_file_context
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.action.action_agent_manger.server import ActionAgentManager
from src.action.models import ActionAgentConfig
from src.monitor.model import BrowserPluginMonitorAgent
from src.monitor.server import MonitorService
from src.proxy.fastapi import FastApi
from src.proxy.fastdataapi import FastDataApi
from src.api.model import (
    ActionResultRequest,
    ActionRequest,
    CheckTradeActionRequest,
    CheckTargetPageRequest,
    BrowserActionNlpRequest,
    BrowserActionNlpResponse,
    ChatMessage,
    AgentRegisterRequest,
    ContextCreateRequest,
    SaveStrategyRequest,
    UpdateStrategyRequest,
    RunStrategyRequest,
    DeleteStrategyRequest, Strategy
)
from src.action.models import CheckTradeAction, IsTargetPage, GetContentByImage
from src.prompt import CHECK_TRADE_ACTION, CHECK_TARGET_PAGE
from src.utils.llm import call_llm, call_llm_with_image
from src.const import GPT_ID, ANALYZE_AGENT_ID, EXECUTION_AGENT_ID, RESEARCH_AGENT_ID
from src.utils.content import list_dict_to_markdown, check_valid_json
from src.strategy.server import StrategyServer, get_strategy_output, StrategyOutput
from src.utils.oss import OSSUploader

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)
public_router = APIRouter(
    tags=["Tool"]  # 设置 API 分组标签为 Tool
)
monitor_service = MonitorService()

fastapi = FastApi()
fastDataApi = FastDataApi()

action_agent_manager = ActionAgentManager()

strategy_server = StrategyServer()


@router.post("/action/result")
async def action_result(request: ActionResultRequest):
    try:
        chat_request_id = request.chat_request_id
        action_agent_conf = ActionAgentConfig(task='', llm=None)
        action_agent = action_agent_manager.get_agent(chat_request_id, action_agent_conf)
        # 2. 调用模型获取下一步动作
        # 这里需要实例化您的 LLM 和 Agent
        # 注意：这部分可能需要根据您的具体需求进行调整
        result = await action_agent.set_action_result(result=request.result)
        return result
    except Exception as e:
        logger.error("action result err:", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/get_next_action")
async def get_next_action(request: ActionRequest):
    """
    获取下一步自动化操作

    参数:
        request: ActionRequest - 包含DOM树和任务信息的请求体

    返回:
        {
            "current_state": {
                "page_summary": "string",
                "evaluation_previous_goal": "string",
                "memory": "string",
                "next_goal": "string"
            },
            "action": [
                {
                    "click_element": {"index": 0},
                    "type_text": {"text": "example"},
                    "press_key": {"key": "Enter"}
                }
            ]
        }

    错误:
        500: 服务器内部错误
    """
    try:
        # 如果数据是 base64 编码的（通常 pako 压缩后会进行 base64 编码）
        decoded_data = base64.b64decode(request.compressed_data)

        # 解压数据
        # wbits=15+32 表示使用 zlib 格式并自动检测 gzip 头
        decompressed_data = zlib.decompress(decoded_data, wbits=15 + 32)

        # 将字节转换为字符串
        result = decompressed_data.decode('utf-8')
        json_res = json.loads(result)
        start_time = time.time()
        logger.info("========= start get next action =========")
        chat_request_id = json_res["chat_request_id"]
        action_agent_conf = ActionAgentConfig(task=json_res["task"],llm=None)
        action_agent = action_agent_manager.get_agent(chat_request_id, action_agent_conf)
        model_output = await action_agent.get_next_actions(json_res["dom_tree"], json_res["url"], json_res["title"], json_res["tabs"])
        end_time = time.time()
        serializable_selector_map = action_agent.get_selector_map_serializable()
        model_output.update({"selector_map": serializable_selector_map})
        logger.info(f"get next action time: {end_time - start_time}")
        return model_output
    except Exception as e:
        logger.error(f"action result err: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/check_trade_action")
async def check_trade_action(request: CheckTradeActionRequest):
    """
    检查是否是交易动作并解析详情

    参数:
        request: CheckTradeActionRequest - 包含自然语言描述的交易动作

    返回:
        CheckTradeAction - 解析后的交易动作详情

    示例请求:
        POST /api/check_trade_action
        {
            "nlp": "Buy 0.1 BTC at market price"
        }

    示例响应:
        {
            "is_trade_action": true,
            "action": "buy",
            "coin_name": "BTC",
            "amount": 0.1
        }
    """
    try:
        result = await call_llm(
            system_content=CHECK_TRADE_ACTION,
            human_content=f"""\n NLP: {request.nlp} \n""",
            schema=CheckTradeAction
        )
        return result
    except Exception as e:
        logger.error(f"check trade action error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/check_target_page")
async def check_target_page(request: CheckTargetPageRequest):
    try:
        result = await call_llm(
            system_content=CHECK_TARGET_PAGE,
            human_content=f"""\n Current url: {request.current_page_url}""",
            schema=IsTargetPage
        )
        return result
    except Exception as e:
        logger.error(f"check target page error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/register")
async def register_agent(request: AgentRegisterRequest):
    """SSE endpoint for monitoring agent progress"""
    agent_id = request.agent_id
    if agent_id in monitor_service.agents:
        logger.info("agent already register")
        return
    create_gpt_result = await fastapi.create_gpt_user()
    logger.info(f"create user result: {create_gpt_result}")
    user_id =create_gpt_result.data["user_id"]
    logger.info(f"user id: {user_id}")
    monitor_agent = BrowserPluginMonitorAgent(browser_plugin_id=agent_id, gpt_user_id=user_id)
    monitor_service.register_agent(agent_id, monitor_agent)
    return {"user_id": user_id}


@router.get("/agent/{agent_id}/monitor")
async def monitor_agent(agent_id: str, request: Request):
    """监控特定代理的SSE端点"""
    async def event_generator():
        async for update in monitor_service.get_agent_updates(agent_id):
            if await request.is_disconnected():
                break
            yield json.dumps(update)

    return EventSourceResponse(event_generator())


@public_router.post(
    "/tool/browser_action_nlp",
    response_model=BrowserActionNlpResponse,
    responses={
        200: {
            "description": "Successfully processed browser action",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "message": "start action: Click the login button on the page"
                    }
                }
            }
        }
    }
)
async def browser_action_nlp(request: BrowserActionNlpRequest):
    """
    Process natural language browser action descriptions

    This endpoint receives natural language browser operation instructions 
    and forwards them to the corresponding monitoring agent.

    Parameters:
        request: BrowserActionNlpRequest
            - context: Context information
                - gpt_id: GPT model ID
                - user_id: User ID
            - content: Natural language description of browser action

    Returns:
        BrowserActionNlpResponse:
            - status: Execution status (success/error)
            - message: Execution message with operation details

    Example:
        Request:
            POST /api/v1/tool/browser_action_nlp
            {
                "context": {
                    "gpt_id": "67ab0c86880303187f65d3a8",
                    "user_id": "user_123"
                },
                "content": "Click the login button on the page"
            }

        Success Response:
            {
                "status": "success",
                "message": "start action: Click the login button on the page"
            }

        Error Response:
            {
                "detail": "Monitor Agent not found"
            }

    Notes:
        - Ensure monitoring agent is registered before calling
        - Natural language description should be clear and specific
        - Valid GPT ID and user ID are required
    """
    user_id = request.context.user_id
    content = request.content
    agents = monitor_service.get_agents()
    match_agent = pydash.find(agents.values(), lambda a: a.get_gpt_user_id() == user_id)

    if match_agent is None:
        logger.error("agent not found")
        raise HTTPException(
            status_code=500, 
            detail="Monitor Agent not found"
        )
    await match_agent.status_queue.put(content)
    return BrowserActionNlpResponse(
        status="success",
        message=f"start action: {content}"
    )

@router.post("/chat")
async def chat(request: ChatMessage):
    try:
        # 设置超时时间为60分钟
        timeout = 3600  # 秒
        async with asyncio.timeout(timeout):  # 使用 asyncio.timeout 上下文管理器
            gpt_id = GPT_ID
            token = None
            dataframe_content = ''
            co_instance_id = request.co_instance_id
            if co_instance_id not in monitor_service.get_agents():
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to process chat message: agent not found"
                )
            browser_plugin_instance = monitor_service.get_agent(co_instance_id)
            gpt_user_id = browser_plugin_instance.get_gpt_user_id()
            
            content = f"user intend: {request.content}"

            strategy = Strategy(name=co_instance_id,description="",content=content)
            strategy_output: StrategyOutput = await get_strategy_output(strategy)
            if strategy_output.is_research:
                run_agent_start_time = time.time()
                task = f'''{strategy_output.research_content}, 
                response format: valid json and json is double quotes, not single quotes.
                output: only json content, not need other content'''
                if request.file_meta:
                    file_context = convert_file_context(request.file_meta, content)
                    task = f'base on the context : {file_context}, {task}'
                logger.debug(f"task:{task}")

                response = await fastapi.run_agent(agent_id=RESEARCH_AGENT_ID, task=task)
                run_agent_end_time = time.time()
                logger.info(f"run agent time: {run_agent_end_time - run_agent_start_time}")
                response_content = pydash.get(response.data, 'result')
                logger.debug(f"research result: {response_content}")
                response_content = response_content.replace("```json", "").replace("```", "")
                logging.info(f"research result: {response_content}")
                if not check_valid_json(response_content):
                    return response_content
                dataframe = json.loads(response_content)
                tsdb_query_start_time = time.time()
                data = await fastapi.tsdb_query(user_id=gpt_user_id, dataframe_id= dataframe['dataframe_id'])
                tsdb_query_end_time = time.time()
                logger.info(f"tsdb_query time: {tsdb_query_end_time - tsdb_query_start_time}")
                dataframe_data = pydash.get(data, 'data.dataframe.data')
                token = pydash.get(dataframe_data, '0.token')
                if not strategy_output.is_action:
                    df = pandas.DataFrame(dataframe_data)
                    ## 如果存在 timestamp 列则过滤掉 timestamp 的列
                    if 'timestamp' in df.columns:
                        df = df.drop(columns=['timestamp'])
                    ## 只保留前面两列，且过滤掉 none，nan
                    df = df.dropna(axis=1, how='any')
                    # df = df.iloc[:, :3]
                    dataframe_list = list(df.to_dict(orient='records'))
                    dataframe_content = list_dict_to_markdown(dataframe_list)
                    return dataframe_content
            if strategy_output.is_action:
                task = f'{strategy_output.action_content}, the token name : {token}' if token else \
                strategy_output.action_content
                await browser_plugin_instance.status_queue.put(task)
            return dataframe_content

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,  # 使用 504 Gateway Timeout
            detail=f"Request timed out after {timeout} seconds"
        )
    except Exception as e:
        logger.error(f"Exception: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat message: {str(e)}"
        )


@router.post("/context/create")
async def context_create(request: ContextCreateRequest):
    entity_type = "token"
    file_infos = request.file_infos
    file_meta = []

    for file_info in file_infos:
        if file_info['source_url'] is None:
            continue
            
        try:
            result = await fastDataApi.extract_tables(file_info['content'], file_info['source_url'])
            tables = pydash.get(result, 'data.data')
            
            # Skip if no tables were extracted
            if not tables:
                logger.warning(f"No tables extracted from {file_info['source_url']}")
                continue
                
            meta = {
                "source_url": file_info['source_url'],
                "title": file_info['title']
            }
            table_meta = []
            
            for table in tables:
                table_list = table['table']
                table_list = [{k.lower(): v for k, v in item.items()} for item in table_list]
                table_result = await fastapi.create_dataframe(
                    user_id=request.user_id, 
                    url=file_info['source_url'], 
                    table=table_list, 
                    entity_type=entity_type
                )
                table_meta.append(table_result)
                
            meta['table_meta'] = table_meta
            file_meta.append(meta)
            
        except Exception as e:
            logger.error(f"Error processing file {file_info['source_url']}: {str(e)}")
            continue

    return {"file_meta": file_meta}

@router.post("/strategy/create")
async def save_strategy(request: SaveStrategyRequest):
    result = await strategy_server.create_strategies(request.strategy)
    return result


@router.post("/strategy/list")
async def get_strategy(request: Request):
    result = await strategy_server.list_strategies()
    return result


@router.post("/strategy/update")
async def update_strategy(request: UpdateStrategyRequest):
    result = await strategy_server.update_strategies(request.strategy)
    return result


@router.post("/strategy/run")
async def update_strategy(request: RunStrategyRequest):
    co_instance_id = request.co_instance_id
    if co_instance_id not in monitor_service.get_agents():
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat message: agent not found"
        )
    browser_plugin_instance = monitor_service.get_agent(co_instance_id)
    gpt_user_id = browser_plugin_instance.get_gpt_user_id()
    result = await strategy_server.run_strategy(
        strategy_id=request.strategy_id,
        plugin_instance=browser_plugin_instance,
        user_id=gpt_user_id
    )
    return result

@router.post("/strategy/delete")
async def delete_strategy(request: DeleteStrategyRequest):
    try:
        result = await strategy_server.delete_strategies(strategy_id=request.strategy_id)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat message: {str(e)}"
        )

