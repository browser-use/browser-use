# 论文框架（Daily Task 对比实验 · 与代码对齐）

> 用途：在正式跑完四项配方（A/B/C/D）并做统计分析之前，先把**叙事骨架、贡献点占位、与实现对应关系**固定下来；跑完后把 `[待填]` 换成数字/图表/引用即可。  
> 关联仓库文档：`DAILY_TASK_EXPERIMENT_GUIDE.md`、`EXPERIMENT_RECORD.md`、`DAILY_TASK_EXPERIMENT_LOG.md`、`docs/issue-notes/*.md`（含 **`openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**）。

---

## 0. 元信息（投稿前填）

| 项 | 占位 |
|----|------|
| 暂定标题（中） | [待填：突出「日常 Web 任务 + 分层领航 / 用量归因」之一或组合] |
| 暂定标题（英，若投国际） | [TBD] |
| 目标 venue 类型 | [待填：workshop / 应用轨 / 中文期刊 / arXiv tech report] |
| 代码与数据版本 | [待填：`git rev-parse HEAD`、task_cards.json 版本说明、是否公开 artifact] |
| 作者与单位 | [待填] |

---

## 摘要（Abstract）

**背景（1–2 句）**  
[待填：大模型驱动的浏览器自动化在真实站点上的痛点——长任务、重型 SPA、多步 tool 调用不稳定等。]

**方法（2–4 句）**  
本工作基于 **browser-use** 扩展一套可复现的 **日常任务（Daily Task）评估协议**：结构化 **TaskCard**（成功标准、禁止操作、失败模式）、四种 **实验配方 A/B/C/D**（执行器：ChatBrowserUse vs Qwen 兼容接口；领航员：无 vs DeepSeek 开场规划），以及可选的 **持续领航**（`--continuous-navigation`）与 **短子目标**注入（`<current_step_focus>` / `<navigator_current_step>`，见实现与 `docs/issue-notes/navigator-current-step-executor-subgoal.md`）。

**测量（1–2 句）**  
每次运行产出 **`agent_runs.json`** 中的结构化摘要，并对 LLM 用量做 **按角色拆分**（如 `usage_executor_llm`、`usage_navigator_cycle_llm`、`navigator_initial_plan_usage` 等，见 `models.AgentRunSummary` 与指南 §1.1）。

**结果（跑完后填）**  
[待填：主要指标一句话 + 最亮对比一句；避免与「路径/站点不同」混淆，见 `DAILY_TASK_EXPERIMENT_LOG.md` 中 C vs D 的说明。]

**结论（1 句）**  
[待填。]

---

## 1. 引言（Introduction）

### 1.1 问题与动机

- [待填：为何选「日常任务」而非仅 benchmark 列表站。]
- [待填：真实 Web 带来的变量——登录墙、地图 SPA、截图链路等，可引用内部问题记录 `heavy-spa-screenshot-timeouts.md`、`DAILY_TASK_EXPERIMENT_LOG.md`。]

### 1.2 贡献声明（建议最终 3 条 bullet，下面先占位）

1. **协议与实现（Benchmark / harness）**  
   TaskCard schema、人工 baseline（`human_runs.json`）、Agent 摘要与对比报告（`comparison_report.json`）；CLI：`examples/evaluation/daily_task_comparison.py`（`init` / `run-agent` / `compare`）。

2. **分层领航与战术子目标（Method）**  
   开场 `navigator_plan.md` + 可选周期领航（`Agent.continuous_navigation` + `navigator_llm`，`browser_use/agent/service.py`）+ 短子目标顶栏注入（`message_manager/utils.py`、`agent/prompts.py`）；实验入口：`daily_task_eval/runner.py`。

3. **细粒度用量归因（Measurement）**  
   `AgentRunSummary` 中 executor / navigator 周期 / 开场领航 / 辅助模型等字段；[待填：你们将用这些字段回答什么研究问题，例如成本–成功率、领航边际成本等。]

### 1.3 论文结构

[待填：各节一句话导读。]

---

## 2. 相关工作（Related Work）

建议小节划分（按需删减）：

| 小节 | 内容占位 |
|------|-----------|
| LLM 浏览器 / Web Agent | [待填：WebArena、Mind2Web、同类；写清差异：你们强调「日常任务卡 + 真实站 + 人基线」。] |
| 规划与分层控制 | [待填：high-level planner + low-level executor 类工作；对齐你们的 navigator vs executor。] |
| 评估与成本 | [待填：若强调 token 拆分，写现有工作多报总量、少按角色拆。] |

---

## 3. 问题形式化（Problem / Setting）

### 3.1 任务与场景

- **任务定义**：`TaskCard`（`browser_use/experiments/daily_task_eval/models.py`）— `task_prompt`、`success_criteria`、`forbidden_actions`、`category`、`failure_modes`、`scenario_id`。
- **实际使用的任务集**（跑正式实验时以你们 frozen 的 `task_cards.json` 为准）：  
  [待填：列出 task id，例如 `shopping_price_compare`、`nearby_hospital_phone_lookup`；若保留模板任务 `readonly_lookup` / `form_validation` / `download_export` 亦注明。]
- **成功/失败判据**（与代码一致）：`history.is_successful()`、`is_done`、以及对比逻辑 `compare_runs` / `ComparisonRecord` 中的 risk 标记 [待填：是否额外人工 adjudication]。

### 3.2 四项实验配方（固定叙事）

| ID | 执行器 | 领航 | 代码来源 |
|----|--------|------|----------|
| **A** | ChatBrowserUse（`bu-latest`） | 无 | `experiment_presets.experiment_preset(A)` |
| **B** | ChatBrowserUse | DeepSeek 开场规划 | 预设 B；可选 `--continuous-navigation` |
| **C** | Qwen（OpenAI 兼容，`DEFAULT_QWEN_MODEL`） | 无 | 预设 C |
| **D** | Qwen | DeepSeek | 预设 D；可选 `--continuous-navigation` |

**重要区分（正文或 Limitations 必须写清）**：

- **仅开场领航** vs **持续领航**：与 `EXPERIMENT_RECORD.md` 文首一致；B/D 默认仍有 `navigator_plan.md`，是否叠加 `--continuous-navigation` 是独立自变量。
- **短子目标**：主要作用于有领航输出解析路径的配置；无领航的 C 上「步数少」等现象**不得单独归因于子目标**（见 `navigator-current-step-executor-subgoal.md` §「与效率的关系」）。

### 3.3 威胁与混淆因素（Threats / confounds）

[待填：登录态、地理、站点改版、模型版本日期、是否 headless、vision 开关 `--use-vision`、每任务固定 CLI 等。可直接升华自 `DAILY_TASK_EXPERIMENT_LOG.md` 表格。]

---

## 4. 方法（Method）

### 4.1 系统总览

**一张结构图建议包含**：TaskCard →（可选）Navigator `create_plan` → `Agent`（executor LLM + browser CDP）→ `history` / `conversation` 落盘 → `AgentRunSummary` 追加。

**代码地图（写论文时可缩成脚注）**：

- 编排：`browser_use/experiments/daily_task_eval/runner.py`（`run_agent_task`）
- 提示词拼装：`prompts.py`（`build_agent_task_prompt` 等）
- Agent 本体：`browser_use/agent/service.py`（持续领航注入 `_maybe_inject_continuous_navigation`）
- 子目标解析：`browser_use/agent/message_manager/utils.py`（`extract_navigator_step_focus`）

### 4.2 领航与子目标（若作为核心贡献写细）

[待填：算法式描述——输入输出、何时更新 `navigator_executor_subgoal`、XML 约定、与周期领航的时序。可直接摘要自 `docs/issue-notes/navigator-current-step-executor-subgoal.md`。]

### 4.3 可复现的工程约束（宜放主文一小段 + 附录表）

[待填：`--llm-timeout`、`--step-timeout`、`--max-actions-per-step`（Qwen 默认 1）、`--use-vision`、`--max-failures` 等；说明为何需要——引用 LOG 中 Qwen JSON、截图看门狗等条目。]

### 4.4 用量归因字段定义

用表格列出 `AgentRunSummary` 各 `usage_*` 字段语义及 **null / 合并** 条件（同模型 id 等），与指南 §1.1 一致。[待填：若投稿英文稿，此处翻译为英文定义表。]

---

## 5. 实验（Experiments）

### 5.1 研究问题（RQ）

建议先写 2–4 条，跑完用数据回答：

| RQ | 问题 | 计划用的指标 |
|----|------|----------------|
| **RQ1** | [待填：A/B/C/D 成功率与步数差异？] | success、number_of_steps、duration |
| **RQ2** | [待填：持续领航 + 子目标是否降低某类失败？] | errors、action_names、urls、必要时人工判畸形 URL |
| **RQ3** | [待填：用量拆分下 executor vs navigator 的成本占比？] | usage_* 字段、总 tokens、`navigator_overhead_ratio`（见 GUIDE §1.3） |
| **RQ3b** | [待填：C vs D 领航是否提升千 Token 成功率？] | `token_efficiency_score`、`execution_velocity`；`compare` 终端 **学术效率前沿分析** |
| **RQ4** | [待填：人与 Agent 差异？] | human_runs vs `ComparisonRecord` |

### 5.2 实验设置

| 项 | 占位 |
|----|------|
| 模型版本与日期 | [待填：BU / Qwen / DeepSeek 具体 model string 与快照日期] |
| 每任务每配方重复次数 | [待填：k 次随机种子或固定 k 次] |
| 浏览器 | Chromium；headless / headful [待填] |
| 固定 CLI（frozen command） | [待填：每条可复制命令或脚本路径] |

### 5.3 主结果表（跑完后填）

**表 1：按 task × preset 的成功率 / 步数 / 墙钟时间（中位数或 mean±std）**

| task_id | A | B | C | D | 备注 |
|---------|---|---|---|---|------|
| […] | [TBD] | [TBD] | [TBD] | [TBD] | [如：是否 continuous-nav] |

**表 2：用量（示例列，按你们最终选的字段删改）**

| task_id | preset | total tokens | executor | nav_cycle | nav_initial | [TBD] |
|---------|--------|--------------|----------|-----------|-------------|--------|
| … | … | … | … | … | … | … |

### 5.4 消融或对照（强烈建议至少 1 个）

[待填：例如 **D** vs **D + `--continuous-navigation`**；或 **vision on/off** 在同一 task 上；**必须控制**起始 URL / 任务文案版本。]

### 5.5 定性案例（Case study）

[待填：1–2 个 `history.json` / `conversation.json` 路径或匿名化摘录；说明失败恢复或子目标如何改变行为。]

---

## 6. 结果分析（Analysis）

- [待填：对应 RQ 逐条回答。]
- [待填：统计检验若样本小，写清采用非参数或仅描述性统计，并讨论功效。]
- [待填：与 LOG 中已知现象互证——例如京东登录墙、地图 SPA。]

---

## 7. 讨论（Discussion）

- [待填：机制何时有效 / 何时无效。]
- [待填：与纯「更大模型」或「更长 context」的边界。]
- [待填：伦理——仅只读任务、无真实支付；遵守站点 ToS 的声明。]

---

## 8. 局限与未来工作（Limitations）

- 样本量与任务多样性 [待填]  
- 用量字段在「同模型 id」时的不可分性 [待填，见指南 §1.1]  
- 依赖特定商业 API / 地域 [待填]  
- 人基线人数与一致性 [待填]  
- **执行器结构化输出稳定性**：OpenAI 兼容（如 Qwen）与 **ChatBrowserUse** 在 **`AgentOutput` JSON 校验通过率** 上可能系统差异；**C vs D** 除模型外还混有 **领航全文进入 `user_request` 的 prompt 负载**，写「专用模型更优」类结论前须控制或披露（见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**）。

---

## 9. 结论（Conclusion）

[待填：3 句以内收束 + 开源/artifact 声明若适用。]

---

## 附录 A：复现清单（与 README 对齐）

1. `uv sync`；按需 `uvx browser-use install`  
2. `.env`（不写密钥进论文）  
3. `uv run examples/evaluation/daily_task_comparison.py init`  
4. 四项 `run-agent --experiment {A,B,C,D}` [待填：是否加 `--continuous-navigation`、其它固定参数]  
5. `compare`  
6. [待填：commit hash、task_cards.json 哈希或附件名]

---

## 附录 B：图表清单（投稿前勾选）

| 图号 | 内容 | 状态 |
|------|------|------|
| Fig.1 | 系统架构 | [ ] |
| Fig.2 | 主结果（成功率/步数） | [ ] |
| Fig.3 | Token 拆分 / 成本 | [ ] |
| Fig.4 | 消融 | [ ] |

---

## 写作时注意（内部检查单）

- [ ] 凡写「子目标/持续领航 提升效率」，是否控制了 **URL 路径与 Early-finish**（见 LOG 与 issue-note）。  
- [ ] 是否明确 **B 默认仅开场领航**，与 **B + continuous-navigation** 不是同一实验。  
- [ ] `usage_*` 是否配套 **一张定义表 + 至少一张结果图**。  
- [ ] 人基线与 Agent 是否 **同一 task 文案版本**。  
- [ ] 凡写 **「ChatBrowserUse / BU 模型优于 Qwen」**，是否避免过强「微调/训练」断言，并披露 **prompt 长度（C vs D）、`max_actions_per_step`、`max_failures`、vision** 等混淆项（见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**）。

---

若你希望把本框架同步进 `README.md` 一条链接，可自行加一句指向：`examples/evaluation/PAPER_FRAMEWORK.md`。
