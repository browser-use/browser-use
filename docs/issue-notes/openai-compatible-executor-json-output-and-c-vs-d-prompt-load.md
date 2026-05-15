# 问题记录：OpenAI 兼容执行器下的 Agent 结构化输出（JSON）与 C / D 配方差异

## 现象

在日常评测（`daily_task_eval`）里，**实验 C**（无领航、Qwen 执行）与 **实验 D**（DeepSeek 开场领航 + Qwen 执行）对**同一 `TaskCard`** 复跑时，常见：

- 控制台或 `history.json` 的 `<agent_history>` 中出现 **`Agent failed to output in the right format.`**（可连续多次）；
- 随后出现 **`failed to output in the correct format for three consecutive attempts`**，触发 **`max_failures`** 后只能 **`done`** 或提前结束；
- `agent_runs.json` 里 **`urls`** 偶发 **`%7D%7D`**（即 `}}`）或 **`]}`** 等碎片拼进 **`navigate.url`**（Qwen 多动作或长上下文下更易发；本仓库已对 OpenAI 兼容执行器默认 **`max_actions_per_step=1`** 以减轻此类串场）。

关 **`--use-vision false`** 主要缓解 **CDP 截图 / 重型 SPA** 带来的 **步超时**，**不能**从根上消除「整包 `AgentOutput` JSON 校验失败」——二者是不同故障面。

## 根因侧写（实现层）

1. **结构化输出校验**  
   Qwen 经 DashScope **OpenAI 兼容**路径时，Agent 期望 **`message.content` 为整段 JSON**，并通过 **`AgentOutput.model_validate_json(...)`** 校验（见 **`browser_use/llm/openai/chat.py`** 中 `response_format` + `model_validate_json`）。  
   不合法则本步拿不到可用的 **`last_model_output`**。

2. **历史文案是泛化占位**  
   当某步没有可用的 **`model_output`** 写入消息管理器历史时，会追加一条 **`Agent failed to output in the right format.`**（见 **`browser_use/agent/message_manager/service.py`** 中 `prepare_step_state` → `_update_agent_history_description`）。  
   它**不**等价于「磁盘 JSON 文件坏了」，而是「上一轮没有成功解析出结构化 Agent 输出」的占位描述；具体异常需看同一步的 **`ActionResult.error`**、**`step_trace_*.txt`**（若启用 **`save_conversation_path`**）或 **`--log-level debug`**。

3. **C 与 D 的可比性**  
   **D** 会把 **`navigator_plan.md` 全文**（及 **`navigator_current_step` / 子目标**）拼进执行者的 **`user_request`**（见 **`browser_use/experiments/daily_task_eval/prompts.py`** 的 **`build_agent_task_prompt`** 与 **`runner.run_agent_task`**）。  
   **C** 无该长块文本 → **同模型**下，执行器上下文更短、干扰更少，**结构化 JSON 失败率往往更低**。  
   因此：**不宜**把「C 稳、D 脆」单独写成「领航员有害」——更稳妥的表述是 **「在控制 prompt 长度与注入内容后，比较有无领航 / 有无短子目标 / 有无持续领航」**。

## 论文 / 报告写作注意（避免过强因果）

若观察到 **ChatBrowserUse（实验 A/B）** 比 **Qwen 兼容（C/D）** 在 **工具 JSON 合法率 / 完成率** 上更好：

- 可报告为 **「与 browser-use 栈协同的执行模型 vs 通用 OpenAI 兼容聊天模型」** 的对照；
- **避免**在缺乏公开训练细节时写成「我们证明微调优于预训练」之类过强结论；
- 必须在 **Limitations / Threats** 中披露：**prompt 负载、领航全文、地图 SPA、vision、max_actions_per_step、max_failures** 等混淆变量（见 **`examples/evaluation/PAPER_FRAMEWORK.md`** 内部检查单）。

## 缓解（操作面）

- 提高 **`--max-failures`**（例如 6–8）给 Qwen 更多解析重试窗口；  
- 换更稳的 **`--executor-model`**，或实验 **B**（BU 执行 + DeepSeek 领航）；  
- **D** 上若仍脆：缩短进执行器的计划正文、或只对齐 **当前一步** 子目标（已有 **`<current_step_focus>` / `navigator_current_step`** 机制）；  
- 需要证据链时：开 **`--log-level debug`** + **`save_conversation_path`**（见评测指南 **§7**）。

## 关联文档

- **`examples/evaluation/DAILY_TASK_EXPERIMENT_GUIDE.md`**（常见问题 7 / 9、参数表）  
- **`examples/evaluation/DAILY_TASK_EXPERIMENT_LOG.md`**（按任务 / 配方汇总表）  
- **`examples/evaluation/PAPER_FRAMEWORK.md`**（局限与写作检查单）  
- **`examples/evaluation/EXPERIMENT_RECORD.md`**（成功跑次与 C/D 路径差异说明）  
- 地图截图与步超时：**`docs/issue-notes/heavy-spa-screenshot-timeouts.md`**  
- 短子目标与领航：**`docs/issue-notes/navigator-current-step-executor-subgoal.md`**

## 记录日期

2026-05-14
