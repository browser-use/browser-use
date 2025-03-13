# from src.strategy.server import Strategy, get_strategy_output, StrategyOutput
#
# class AgentServer:
#
#     def __init__(self):
#         pass
#
#     def handle_agent(self):
#         strategy = Strategy(name=co_instance_id, description="", content=content)
#         strategy_output: StrategyOutput = await get_strategy_output(strategy)
#         if strategy_output.is_research:
#             run_agent_start_time = time.time()
#             task = f'{strategy_output.research_content}, response format is markdown if exist table list'
#             response = await fastapi.run_agent(agent_id=RESEARCH_AGENT_ID, task=task)
#             run_agent_end_time = time.time()
#             logger.info(f"run agent time: {run_agent_end_time - run_agent_start_time}")
#             response_content = pydash.get(response.data, 'result')
#             if not check_valid_json(response_content):
#                 return response_content
#             dataframe = json.loads(response_content)
#             tsdb_query_start_time = time.time()
#             data = await fastapi.tsdb_query(user_id=gpt_user_id, dataframe_id=dataframe['dataframe_id'])
#             tsdb_query_end_time = time.time()
#             logger.info(f"tsdb_query time: {tsdb_query_end_time - tsdb_query_start_time}")
#             dataframe_data = pydash.get(data, 'data.dataframe.data')
#             token = pydash.get(dataframe_data, '0.token')
#             if not strategy_output.is_action:
#                 df = pandas.DataFrame(dataframe_data)
#                 ## 如果存在 timestamp 列则过滤掉 timestamp 的列
#                 if 'timestamp' in df.columns:
#                     df = df.drop(columns=['timestamp'])
#                 ## 只保留前面两列，且过滤掉 none，nan
#                 df = df.dropna(axis=1, how='any')
#                 # df = df.iloc[:, :3]
#                 dataframe_list = list(df.to_dict(orient='records'))
#                 dataframe_content = list_dict_to_markdown(dataframe_list)
#                 return dataframe_content
#         if strategy_output.is_action:
#             task = f'{strategy_output.action_content}, the token name : {token}' if token else \
#                 strategy_output.action_content
#             await browser_plugin_instance.status_queue.put(task)