# 问题记录：领航「短子目标」与执行者顶栏 `<navigator_current_step>`

## 背景问题

在 **B/D** 等「有领航员」的日常实验里，若领航只在开场生成 **`navigator_plan.md`** 并整块拼进执行者的 **`user_request`**，执行者在长任务中容易：

- 在长规则与静态计划里 **迷路**，与当前 DOM 脱节；
- 产出 **畸形 `navigate` URL**（例如把 JSON 闭合符号拼进 `https://...`）；
- **步数膨胀**（反复验证、换站、多点详情），与「地图 SPA + 截图链」叠加后更易触发整步超时。

周期领航（**`--continuous-navigation`**）缓解「计划不随步更新」；本记录描述与之配套的 **短子目标** 机制。

## 实现要点（代码位置）

1. **约定标签**：领航输出（开场 plan + 周期回复）须以 XML 块开头：
   - `<current_step_focus>` … `</current_step_focus>`（内层 **1～3 行**，只写「下一步要做的战术目标」，不要 action JSON）。
2. **解析与去重**：`browser_use/agent/message_manager/utils.py` 中的 **`extract_navigator_step_focus`** 从全文抽出子目标，并把该块从拼进 **`Navigator plan:`** 的正文中剥掉，避免重复占 token。
3. **执行者上下文**：`browser_use/agent/prompts.py`（`AgentMessagePrompt`）在每步 **`agent_state`** 的 **`<user_request>` 之前** 注入 **`<navigator_current_step priority="highest">`**，当且仅当 `AgentState.navigator_executor_subgoal` 非空。
4. **谁写入 `navigator_executor_subgoal`**：
   - **开场**：`daily_task_eval/runner.py` 在 `create_plan` 后解析并传入 **`Agent(navigator_executor_subgoal=...)`**。
   - **周期**：`browser_use/agent/service.py` 的 **`_maybe_inject_continuous_navigation`** 在领航返回后解析并 **覆盖** `state.navigator_executor_subgoal`；若某次未写标签则 **保留上一轮子目标**。

## 与「效率」的关系（务必读）

- **B/D**：短子目标 + 周期领航，意在 **减少跑偏与无效多步**，不保证每任务都变快。
- **C（无领航）**：例如 `nearby_hospital_phone_lookup` **2026-05-14** 一次 **5 步**成功，主要仍来自 **任务里的 Early-finish**、**单步单动作（Qwen）**、以及 **留在百度地图列表即收工** 的路径选择；**不能**简单归因于「顶栏子目标」（该字段在无领航时为空）。
- **与旧 D（17 步）对比**：同任务下 D 曾走 **百度搜索 → 高德多点 POI**；C 成功趟 **未走**该长链，故步数差异 **不等于** 仅由子目标机制解释。写报告时应并列 **`action_names` / `urls`**。

## 关联文档

- 日常实验总手册：**`examples/evaluation/DAILY_TASK_EXPERIMENT_GUIDE.md`** §1.2。
- 问题与对策流水：**`examples/evaluation/DAILY_TASK_EXPERIMENT_LOG.md`**（工程侧表格）。
- 成功跑次人读表：**`examples/evaluation/EXPERIMENT_RECORD.md`**（含时间线）。
- 地图 SPA 截图超时（另一类「慢」）：**`docs/issue-notes/heavy-spa-screenshot-timeouts.md`**。

## 记录日期

2026-05-14
