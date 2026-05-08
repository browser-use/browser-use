# 日常任务实验记录（Issues & Mitigations）

本文件用于**按任务类别 / 场景**固化实验中发现的问题与已采取的对策，方便迭代 `task_cards.json`、提示词和 CLI。**建议每次跑完一组 A/B/C/D 或改了任务卡后追加一行或一小节**，避免只在聊天里零散记忆。

运维说明：

- **不要**在本文件中粘贴 API Key、Cookie、手机号等机密。
- 与单次运行轨迹相关的细节仍可查：`tmp/daily_task_eval/agent_runs.json`、各任务目录下 `conversation.json`、`history.json`。
- 操作步骤见：**`DAILY_TASK_EXPERIMENT_GUIDE.md`**。

---

## 一、按任务类别汇总（living document）

模板：发现现象 → 可能原因 → 对策 / 文档或代码位置 → 是否仍需跟进。

### `read_only_query`（只读检索 / 比价 / 列表类）

| 日期 | TaskCard / 示例 | 实验配方 | 现象 | 原因（推断） | 对策（已做 / 待定） |
|------|-----------------|----------|------|--------------|---------------------|
| 2026-05-08 | `shopping_price_compare`（京东） | C 等 | 未登录无法用搜索完整完成三项比价；Agent 在同一页面反复滚动、extract、`evaluate`，未尽快 `done(success=False)` | JD 对部分路径强依赖登录；任务未明确「登录墙即停」；模型倾向继续尝试 | 已加强 `task_cards.json`（搜索≤2次、首页只读备选、硬性停止）；`prompts.build_agent_task_prompt` 增加全局 **Hard stop**；新增 `failure_modes.jd_login_wall` |
| 2026-05-08 | 同上（早期 Amazon） | D 等 | `ScreenshotWatchdog` 15s 超时、`CDP WebSocket` 断开、`Step timed out after 180s` | 重站点 + 大图 DOM + 截图链路过载；步级超时默认 180s | 可考虑换轻站或加大 `--llm-timeout` / 未来可加 `--step-timeout`；比价任务锚定京东见 `task_cards.json` |

### `form_workflow`

| 日期 | TaskCard | 实验配方 | 现象 | 原因 | 对策 |
|------|----------|----------|------|------|------|
| — | （待填写） | — | — | — | — |

### `download_export`

| 日期 | TaskCard | 实验配方 | 现象 | 原因 | 对策 |
|------|----------|----------|------|------|------|
| — | （待填空） | — | — | — | — |

---

## 二、按实验配方（A/B/C/D）的工程侧问题

| 日期 | 配方 | 现象 | 原因 | 对策 |
|------|------|------|------|------|
| 2026-05-08 | **A / B**（执行器 ChatBrowserUse） | `Free tier accounts are not allowed to use the LLM Gateway` | 免费 BU 账号禁止使用托管 LLM 网关 | 升级 [Cloud 订阅](https://cloud.browser-use.com/settings) 或改用 **C/D**（Qwen）等自备模型 |
| 2026-05-08 | **C / D**（Qwen OpenAI 兼容） | `401 invalid_api_key` | 兼容模式 `base_url` 与国内/国际控制台 Key 地域不一致 | 国内百炼 Key 使用 **`https://dashscope.aliyuncs.com/compatible-mode/v1`**（代码与 CLI 默认已对齐） |
| 2026-05-08 | **C / D** | `LLM call timed out after 75 seconds` | Agent 默认对非 DeepSeek/Gemini 类模型 LLM 超时偏短 | CLI 增加 **`--llm-timeout`**（默认 180），并传入 `Agent` |

---

## 三、待定 / idea backlog（可选）

- [ ] CLI 暴露 **`step_timeout`**，缓解「截图 + DOM」慢导致的整步 180s 爆掉。
- [ ] `run-agent` 支持 `--starting-url` 注入所有任务前缀（便于统一锚定站点）。
- [ ] 对 `shopping_*` 类任务自动生成「登录墙即失败」的子场景 `scenario_id`，便于报表对比。

---

## 四、如何追加一条记录（copy-paste）

在对应类别表格中**新的一行**填写即可；若为全新类别，可复制一节「表格模板」自建。

简述原则：**写清 task_id / experiment（A-D）/ 环境与参数（不写密钥）**，现象一句话，对策指到文件路径或 PR。

示例：

```text
| 2026-05-xx | shopping_cart_review | D | （现象） | （原因） | （task_cards / prompts / CLI 改动） |
```
