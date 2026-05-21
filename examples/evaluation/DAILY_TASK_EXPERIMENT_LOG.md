# 日常任务实验记录（Issues & Mitigations）

本文件用于**按任务类别 / 场景**固化实验中发现的问题与已采取的对策，方便迭代 `task_cards.json`、提示词和 CLI。**建议每次跑完一组 A/B/C/D 或改了任务卡后追加一行或一小节**，避免只在聊天里零散记忆。

运维说明：

- **不要**在本文件中粘贴 API Key、Cookie、手机号等机密。
- 与单次运行轨迹相关的细节仍可查：`tmp/daily_task_eval/agent_runs.json`、各任务目录下 `conversation.json`、`history.json`。
- **`compare`** 产出的 **`experiment_resource_report.json`**（描述统计、pooled、墙钟时长等）与 **`export-csv`** 导出说明见 **`DAILY_TASK_EXPERIMENT_GUIDE.md` §5.2**。
- **Qwen / OpenAI 兼容执行器的结构化输出（JSON）与 C vs D 写作注意**：**`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**。
- 操作步骤见：**`DAILY_TASK_EXPERIMENT_GUIDE.md`**。

---

## 一、按任务类别汇总（living document）

模板：发现现象 → 可能原因 → 对策 / 文档或代码位置 → 是否仍需跟进。

### `read_only_query`（只读检索 / 比价 / 列表类）

| 日期 | TaskCard / 示例 | 实验配方 | 现象 | 原因（推断） | 对策（已做 / 待定） |
|------|-----------------|----------|------|--------------|---------------------|
| 2026-05-08 | `shopping_price_compare`（京东） | C 等 | 未登录无法用搜索完整完成三项比价；Agent 在同一页面反复滚动、extract、`evaluate`，未尽快 `done(success=False)` | JD 对部分路径强依赖登录；任务未明确「登录墙即停」；模型倾向继续尝试 | 已加强 `task_cards.json`（搜索≤2次、首页只读备选、硬性停止）；`prompts.build_agent_task_prompt` 增加全局 **Hard stop**；新增 `failure_modes.jd_login_wall` |
| 2026-05-08 | 同上（早期 Amazon） | D 等 | `ScreenshotWatchdog` 15s 超时、`CDP WebSocket` 断开、`Step timed out after 180s` | 重站点 + 大图 DOM + 截图链路过载；步级超时默认 180s | 可考虑换轻站或加大 `--llm-timeout` / 未来可加 `--step-timeout`；比价任务锚定京东见 `task_cards.json` |
| 2026-05-14 | `nearby_hospital_phone_lookup`（百度地图 / 龙岗坂田） | **C** | **5** 步成功：`navigate`×2 → `input` → `click` → `done`；列表页即满足成功标准 | **无**领航短子目标（C）；**Early-finish** + 未切高德深挖 + Qwen **每步单动作** | 与 **D（17 步）** 对比时注明 URL 路径差异；见 **`EXPERIMENT_RECORD.md`** 时间线、`navigator-current-step-executor-subgoal.md` |
| 2026-05-14 | 同上 | **D**（历史成功） | **17** 步：百度搜索畸形词、高德多点 POI | 多站深挖、验证路径长 | 若重跑 D，可叠加 **`--continuous-navigation`** + 短子目标以压缩迷路；artifact `20260509T064248Z` |
| 2026-05-14 | 同上 | **D**（失败/早停样例） | `history` 中连续 **`Agent failed to output in the right format.`**，随后仅 **`navigate`→`done(false)`** 或未到搜索即停；关 **`--use-vision false`** 后仍可出现 | **非**截图主因：执行器需输出整包 **`AgentOutput` JSON**；**D** 相对 **C** 多塞 **整份 `navigator_plan` + 子目标**，Qwen 上下文更长 → **结构化输出校验失败率**上升；失败记忆叠加后更易连环错 | 操作：**`--max-failures 6~8`**、换 **`--executor-model`**、或实验 **B**（BU 执行）；写作：勿把「C 稳 D 脆」单独归因于领航员本身，见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`** |

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
| 2026-05-08 | **C / D** | `ScreenshotWatchdog` / `captureScreenshot` 在百度地图等重 SPA 上频繁超时，前几步空转 | 重型页面 + 每步 CDP 状态截图链路慢 | **`run-agent --use-vision false`**（或按需 **`auto` / `true`**）；手册 **`DAILY_TASK_EXPERIMENT_GUIDE.md`** 步骤 4；详解 **`docs/issue-notes/heavy-spa-screenshot-timeouts.md`** |
| 2026-05-14 | **B / D**（领航 + 可选 `--continuous-navigation`） | 执行者在长 `user_request` 里迷失、畸形 `navigate` URL、步数膨胀 | 仅开场静态 plan；战术目标未顶在「每步最前」 | 已加 **`<current_step_focus>`** 与执行者 **`<navigator_current_step>`**（见 **`docs/issue-notes/navigator-current-step-executor-subgoal.md`**、**`DAILY_TASK_EXPERIMENT_GUIDE.md` §1.2**）；周期领航仍用 **`--continuous-navigation`** |
| 2026-05-14 | **C**（`nearby_hospital_phone_lookup` / normal） | 同任务较早期 **D（17 步）** 明显更少步即 `done` | **非**短子目标（C 无领航）；主因 **Early-finish** + 路径留在 **百度地图列表** + Qwen **单步单动作** | 写对比报告时勿把步数差单独归因于子目标；见 **`EXPERIMENT_RECORD.md`** 时间线第 2 行与 issue-note 文中「与效率的关系」 |
| 2026-05-14 | **C vs D**（同 `qwen3-max` 执行） | **C** 侧「工具 JSON / 畸形 URL」主观上更少 | **D** 把 **DeepSeek 领航全文 + 子目标** 拼进执行器 **`user_request`**，prompt 更长、更像自然语言长说明 → 与 **OpenAI 兼容 `response_format` + `AgentOutput.model_validate_json`** 叠加后更易漂 | 对照实验须 **控制**「进执行器的计划长度」或单列 **「仅注入短子目标 vs 全文 plan」** 消融；全文见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`** |

---

## 三、待定 / idea backlog（可选）

- [x] CLI 暴露 **`step_timeout`** → 已支持 **`--step-timeout`**。
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
