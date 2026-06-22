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

---

## 五、[2026-05] 关于 Agent 原生交互步数少于人类的现象分析与 LCS 指标修正

### 现象（Observation）

在 **简单只读检索类任务**（典型：`nearby_hospital_phone_lookup` / 百度地图查附近医院电话）上，对比 **人类专家 baseline**（`human_runs.json` 的 `steps`）与 **自主 Agent**（`history.json` → `action_names`）时，出现一项 **反直觉** 结果：

| 维度 | 人类（示例） | Agent（exp-C，20260523T071122Z） |
|------|-------------|----------------------------------|
| 微观 tool 步数 | 10（含 3×`extract`） | 5（`navigate`→`input`→`click`×2→`done`） |
| 任务结果 | 成功列出 3 家机构 | 成功列出 3 家机构（Judge PASS） |
| 全序列 LCS | — | ≈ **0.50**（5/10） |

**步数显著更少，但任务同样成功**——若仅用「步数越少越好」或单一 LCS 解读，容易误判 Agent「路径不像人 = 能力差」；实际需区分 **感官适应开销** 与 **核心导航决策**。

### 根因（Root cause）

1. **人类：视口约束（Viewport-bound interaction）**  
   物理浏览器中信息受 **可视区域** 限制；专家 baseline 中常显式记录 `scroll`、`wait`，以及将「停下来抄录字段」记为 **`extract`**（一次独立的采集 episode），以把屏幕外/列表中的条目 **拉入可处理范围**。

2. **Agent：DOM 全局可见性（DOM-global grounding）**  
   Browser-Use 每步向执行 LLM 注入 **`<browser_state>`**（可交互元素 + 可见文本摘要）。在地图列表页等场景，**电话、地址已在 DOM 中可见**时，Agent 可直接 **Direct Grounding**（读 DOM → 写入 `done.text`），**无需**调用 `extract` tool（后者会另启 `page_extraction_llm` 做 markdown 抽取）。

3. **策略叠加**  
   TaskCard 中的 **Early-finish** 规则与 system prompt「信息已在 `browser_state` 则勿 `extract`」一致，进一步 **压缩** 轨迹，使 **`micro_action_count` ≪ 人类 `steps`** 成为 **模态代差（modality gap）** 下的常态，而非单纯「Agent 更懒/更聪明」。

4. **指标含义**  
   未修正的 **Unfiltered LCS** 会把人类多出的 `extract` / `scroll` / `wait` 计为 **路径差异**，惩罚「DOM 原生捷径」，混淆 **环境适应** 与 **决策对齐**。

### 对策：双 LCS 指标 + 语义动作过滤器（Mitigation）

**原则**：不操纵 Agent 原生行为（不强制每步 `extract`、不人为膨胀步数），而在 **评估层** 对称清洗人类与 Agent 轨迹，分别汇报：

| 指标 | CSV 字段 | 含义 |
|------|----------|------|
| **Unfiltered LCS** | `trajectory_lcs_similarity` | 全 tool 序列对齐；**保留** scroll / extract / wait 等环境适应开销，反映「含感官策略」的整体相似度。 |
| **Filtered LCS（Navigation LCS）** | `trajectory_lcs_navigation` | 经 **语义动作过滤器** 清洗后再算 LCS；隔离 **核心语义/导航决策**，降低视口–DOM 模态差带来的评估偏差。 |

**实现**：`browser_use/experiments/daily_task_eval/run_csv.py` — `FILTERED_OUT_TOOLS`、`get_filtered_trajectory()`、`trajectory_lcs_navigation()`；人类 `steps` 与 Agent `action_names` **同一规则、先 `normalize_action_token` 再过滤**。

#### 过滤分桶（Filter buckets）

**被过滤（被动 / 非导航 / 不改变页面交互状态）** — 自轨迹中剔除后再算 Filtered LCS：

`scroll`, `find_text`, `dropdown_options`, `extract`（含 `extract_structured_data` 等前缀归一）, `search_page`, `find_elements`, `screenshot`, `evaluate`, `write_file`, `read_file`, `replace_file`, `wait`, `save_as_pdf`

**被保留（状态改变 / 导航–交互骨架）** — 参与 Filtered LCS：

`navigate`, `search`, `go_back`, `click`, `input`, `upload_file`, `select_dropdown`, `send_keys`, `switch`, `close`, `save_as_pdf`, `done`

> 注：早期讨论稿曾写作「Maps」，规范 token 为 **`navigate`**。`search`（跳转搜索引擎）保留；`search_page`（页内 grep）过滤。  
> **实现说明**：当前 `run_csv.py` 的 `FILTERED_OUT_TOOLS` 将 `save_as_pdf` 与 `write_file` 同类暂归入**过滤桶**（被动文件导出、不改变网页 DOM 交互态）；若实验叙事将其视为任务交付动作，可在后续版本移入保留桶并与 CSV 重算对齐。

#### 同一 hospital 样例（Filter 后）

- 人类：`navigate → input → click → click → click → click → done`（7 步；去掉 3×`extract`）
- Agent：`navigate → input → click → click → done`（5 步）
- Navigation LCS ≈ **5/7 ≈ 0.71**（高于 Unfiltered ≈ 0.50），更反映 **点击链/导航骨架** 对齐而非 extract 策略差。

### 写作与报表（Follow-up）

- 论文叙事占位：**`PAPER_FRAMEWORK.md` §6.1**（*Structural DOM Capabilities vs. Visual Viewport Constraints*）。
- 对比跑批：旧 CSV 行无 `trajectory_lcs_navigation` 列；新 `run-agent` 自动写入，旧表 append 时 **表头自动迁移**（见 `run_csv._migrate_csv_to_headers`）。
- 勿将「C 步数少于人」单独作为效率优势结论，须 **并列报告** Unfiltered / Filtered LCS 及 `micro_action_count` vs `human_micro_action_count`。

---

## 六、[2026-05] 跨站点 Fallback：Recovery rule 「unreachable」语义歧义

### 现象（Observation）

`complex_travel_package_booking` × **exp-D**（Doubao 执行 + DeepSeek 领航）在 **Booking.com** 上反复跑次出现 **同一种行为分叉**：

| Run 时间戳 (UTC) | Step | Final | cost | success | cup | LCS / LCS_nav | 关键事件 |
|------------------|------|-------|------|---------|-----|----------------|----------|
| `20260524T074847Z` | 52 | FAIL | $0.87 | false | 0 | 0.288 / 0.469 | 留在 Booking 国际版 package flow；点 Update Search 后 **站点返回 "We're unable to complete your search"**；Agent 二次重试同错 → `done(success=False)` |
| `20260524T084259Z` | 40 | PASS | $0.69 | **true** | 0 | 0.375 / 0.536 | Booking 中文版找不到「机+酒」入口；scroll 3 页 + `search_page("机+酒")` 0 命中后，**自主 `navigate https://www.trip.com`**，在 Trip.com 完成 package flow |
| `20260524T095254Z` | 50 | PASS | $0.92 | true | 0 | 0.306 / 0.484 | 同上跨站模式（3 次 `navigate`，跨多个域名） |

### 根因（Root cause）

task card `complex_travel_package_booking.starting_conditions` 明文写：

> **"If Booking.com is unreachable, use one comparable mainstream travel site and state which site you used."**

`navigator_plan` recovery plan 也呼应：「If Booking.com is unreachable: Use Expedia or Kayak.」

Agent **把「unreachable」从网络层语义（DNS 失败 / `net::ERR_*` / 长 timeout）扩展解释为功能层语义**（「该站点本地化版本不提供所需 sub-flow」）。在 CN 网络 + 中文 Booking 上，**「机+酒」package 入口** 确实在中文版被裁掉，所以 Agent 触发 fallback，迁去 **Trip.com**，在新站点上从零开始 package flow 并走到 guest info 页，Judge 判 success=true。

人类 baseline 在同一 task 上的等价行为 **不同**：人类没有跨站，而是 **在 Booking 内部降级**——找不到出发地输入框，于是放弃 package、改走纯酒店 flow，最终停在「奥兰治村旅舍三人间」的入住信息页（`human_runs.json` 第 102 条 `notes` 明文记录）。即：

| 主体 | 降级方向 | 终点站点 | 终点 flow |
|------|----------|----------|------------|
| 人类 | **垂直**（package → hotel-only） | Booking.com | 酒店 guest info |
| Agent (D) | **水平**（Booking → Trip.com） | Trip.com | package guest info |

两个 fallback 都不违反 task card，但 **落点完全不同**，导致 `trajectory_lcs_*` 在 site / flow 两个维度都对不齐，单纯比 LCS 数值会失真。

### 对策与写作约束（Mitigation）

1. **保留 task card 现状**（不收紧 「unreachable」语义）：跨站 fallback 反映 Agent 真实策略空间，是有论文价值的负面/中性证据；强行禁止 = 强制 Agent 失败，掩盖现象。
2. **CSV 行解读须分桶**：在论文表里把 `complex_travel_package_booking` 的 D 行 **分两子组**：
   - `flow=package_cross_site`（Trip.com）
   - `flow=site_blocked_no_fallback`（Booking 卡 site-side error）
   并在脚注注明「人类对照走的是 `flow=hotel_only_in_site`」。
3. **不要直接拿 D 的 trajectory_lcs_* 和人类对比作为「相似度」结论**——至少加一条 caveat：两者在不同站点 / 不同子 flow。
4. （可选）后续若做严格对照，增加 **`scenario_id: "booking_only_strict"`**：在 task card 复制一份并写明「`Site lock-in: do not navigate to any non-booking.com domain even when feature is missing`」，与现有宽松版并列做消融。
5. 论文位置：**`PAPER_FRAMEWORK.md` §7 Discussion** 新增 bullet `Recovery rule semantic gap: 'unreachable' as network failure vs. capability gap`；§8 Limitations 提示 LCS 对比需同 site / 同 flow 才有效。
6. 成本提示：单次 D 跨站完成约 **40–50 步、$0.7–$0.9、~1M tokens**；批量重跑前要权衡。
