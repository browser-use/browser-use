# 日常任务对比实验：完整操作手册

本文档说明如何在 **browser-use** 仓库中，使用 **`daily_task_comparison.py` CLI** 完成「人工 baseline ↔ Agent」的日常任务评估实验，以及如何阅读产出报告。

实验逻辑实现在 Python 包 **`browser_use.experiments.daily_task_eval`** 中；命令行入口在 **`examples/evaluation/daily_task_comparison.py`**。

**问题留痕（Qwen 工具 JSON / C vs D / 论文表述）**：见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**（与下文 §7 常见问题 7、9 交叉引用）。

---

## 一、实验在做什么

1. 用 **`TaskCard`**（JSON）描述一批可重复的浏览器任务（提示词、成功标准、禁止操作等）。
2. （可选）在 **`human_runs.json`** 中记录人工完成同一任务的步骤与结论，作为 baseline。
3. 用 **`run-agent`** 让 Browser Use **`Agent`** 自动执行任务；每种「实验配方」（A/B/C/D）对应不同的 **执行 LLM** 与是否启用 **领航员（navigator）**。
4. 每次运行会向 **`agent_runs.json`** 追加一条结构化摘要，并在磁盘写入 **`history.json`**、**`conversation.json`** 等详细轨迹。
5. 用 **`compare`** 读取任务卡、人工记录与 Agent 摘要，生成 **`comparison_report.json`**（差异与风险提示），并默认写出 **`experiment_resource_report.json`**（按任务/场景汇总的跨实验资源对比，可不依赖人工 baseline）。
6. （可选）按预设 **A/B/C/D** 维护人读归档表 **`EXPERIMENT_RECORD.md`**（与结构化 **`agent_runs.json`** 区分）；其中 **成功跑次时间线** 汇总 `agent_runs.json` 内全部 **`success: true`**。当 **`run-agent`** 本趟存在 **`success: true`** 时，控制台会额外提示：**成功跑次的结构化结果路径**及 **该归档文档路径**，便于你对齐表格内容后手工更新。

### 1.1 控制台 `cost` 日志、`🧠` / `🤖` 与本仓库 JSON 用量字段

这些是 **`browser_use.tokens.TokenCost`** 打出来的（logger 名通常为 **`cost`**），用来区分 **单次调用**与**按模型 id 聚合**：

| 形态 | 含义 |
|------|------|
| 带 `🧠` 的行（`model · 📥 · 📤`） | 单次 LLM **`ainvoke`** 的用量；`📥`≈prompt 侧、`📤`≈completion。可能是执行者、周期领航或其它已注册模型的某一次调用。 |
| 带 `🤖` 的行（总 tokens、`📞` 调用次数、`📈`/call） | 对该 **模型字符串**（如 `qwen3-max`、`deepseek-chat`）的 **任务内累计**。若领航与执行者 **模型 id 相同**，日志里只会合并到同一 id，**不能单靠一行日志区分角色**；请用下面 **`agent_runs.json`** 拆分字段或在实验中用不同模型名。 |

**`agent_runs.json`（本次 `run-agent`）在同一条记录中会多带：**

| 字段 | 内容 |
|------|------|
| **`usage_summary`** | `history.usage` 全量：总 tokens / `by_model` 明细（`tokens.views.UsageSummary` 序列化）。 |
| **`usage_executor_llm`** | `Agent.llm`（主执行回路；若 judge/extract 与执行者 **同模型 id** 会与执行者合计）。 |
| **`usage_navigator_cycle_llm`** | 仅在 **`--continuous-navigation`** 且领航 **模型 id ≠** 执行者时：周期领航在 Agent 内产生的累计。 |
| **`navigator_initial_plan_usage`** | 开场 **`navigator_plan`** 那一次 LLM 调用（不走 Agent TokenCost），原始 `usage`字典。 |
| **`usage_auxiliary_llm_models`** | 其余已注册模型的 `by_model` 条目（例如单独配置了其它 `*_llm` 且模型 id 不同）。 |

这些数据可直接用于事后 **按 preset / task 对齐比较 token 与调用次数**（费用需另配 `BROWSER_USE_CALCULATE_COST` 等与定价表）。

### 1.2 领航短子目标：`<current_step_focus>` 与执行者 `<navigator_current_step>`

为减轻「领航计划一大段埋在 `user_request` 里、执行者仍迷路」的问题，日常评测管线要求 **有领航** 时（`LLMNavigator.create_plan` 与 **`--continuous-navigation`** 周期回复）在全文 **最前**输出 **`<current_step_focus>...</current_step_focus>`**（1～3 行战术子目标，无 tool JSON）。运行时会：

- 把解析出的文本写入 **`AgentState.navigator_executor_subgoal`**，并在 **每一步** 的 **`agent_state`** 顶部以 **`<navigator_current_step priority="highest">`** 展示，迫使模型优先对齐「下一步只做一件事」；
- 从拼进任务的 **`Navigator plan:`** 段落中 **剔除** 该 XML 块，减少重复 token。

**注意**：该机制主要服务 **B/D**；**C** 无领航时该顶栏为空。步数骤降常与 **Early-finish**、**站点路径**、**是否开 vision** 等共同作用，详见 **`docs/issue-notes/navigator-current-step-executor-subgoal.md`**。

### 1.3 学术效率度量（Academic Agent Efficiency Metrics）

在 Token 与墙钟时长之外，`compare` 会为每次 Agent 跑次与按实验分桶的聚合统计计算三项**可写入论文**的效率指标（实现见 **`browser_use/experiments/daily_task_eval/models.py`** 中的 `compute_*` / `academic_efficiency_from_agent_run`）：

| 字段 | 中文名 | 公式 | 边界 |
|------|--------|------|------|
| **`navigator_overhead_ratio`** | 领航开销比 | `(usage_navigator_cycle_llm.total_tokens + navigator_initial_plan_usage.total_tokens) / usage_executor_llm.total_tokens` | 无领航或执行器 tokens ≤ 0 → **0.0** |
| **`execution_velocity`** | 任务执行速率 | `usage_summary.total_tokens / duration_seconds`（有效时长含墙钟回填，见 §5.2） | `duration_seconds` ≤ 0 → **0.0** |
| **`token_efficiency_score`** | Token 效率得分 | `(success ? 1 : 0) / (total_tokens / 1000)` | API 端 `total_cost` 常为 0 时的**千 Token 性价比**替代；tokens ≤ 0 → **0.0** |

**落盘位置**

- **`agent_runs.json`**：每条 **`AgentRunSummary`** 含上述三字段（`run-agent` 结束时写入）。
- **`experiment_resource_report.json`**：每组 **`snapshots[]`** 含三字段；**`statistics_by_experiment`** / **`pooled_statistics`** 对三字段做 **`n`、mean、std、min/max/median**（与 `duration_seconds`、`total_tokens` 等同结构）。
- **`compare` 终端**：默认打印 **【学术效率前沿分析 / Academic Efficiency Frontier Analysis】**，在同一 **`(task_id, scenario_id)`** 下对比 **实验 C（无领航）** 与 **实验 D（有领航）** 的 **`navigator_overhead_ratio`**、**`token_efficiency_score`**（及 **`execution_velocity`**）均值，作为高难度任务上「领航是否值得」的数据锚点。
- **`export-csv`**：`**_runs.csv`** / **`*_stats.csv`** 与 **`agent-runs` 模式** 均含对应列。

**解读提示**：`navigator_overhead_ratio` 依赖 **`usage_executor_llm`** / **`usage_navigator_cycle_llm`** 拆分；若历史 **`agent_runs.json`** 仅有 **`usage_summary`** 而无按角色拆分，该比率为 0，需用新版 **`run-agent`** 重跑后 **`compare`** 再分析。论文叙事与 RQ 占位见 **`PAPER_FRAMEWORK.md` §5.1**。

---

## 二、环境与密钥（运行前必须）

### 2.0 克隆后与可复现自检

从远程克隆本仓库后，**不会**自带 `tmp/daily_task_eval/`（该目录通常在 `.gitignore` 中）。组员复现时请按顺序确认：

1. `cd <你的克隆路径>/browser-use`（与 **`pyproject.toml`** 同级，下文称**仓库根目录**）。
2. **`uv sync`**（Python **≥ 3.11**）；按需 **`uvx browser-use install`**。
3. 在根目录创建 **`.env`**（勿提交），至少覆盖你将要跑的预设所需变量（见 **§2.3**）。
4. **`uv run examples/evaluation/daily_task_comparison.py init`** 生成 `tmp/daily_task_eval/*.json` 模板。
5. （可选）**`uv run pytest -q tests/ci/test_daily_task_comparison.py tests/ci/test_continuous_navigation.py`** 验证本机依赖与实验模块可导入。

更短的「从克隆到 `compare`」清单见仓库根目录 **`README.md`** 的「从克隆到第一次出报告」一节。

### 2.1 工作目录

始终在**仓库根目录**下执行命令（与 **`pyproject.toml`** 同级），这样：

- 默认路径 **`./tmp/daily_task_eval`** 会落到仓库内的 `tmp/daily_task_eval/`；
- 若你在项目根放了 **`.env`**，`run-agent` 内部会 **`load_dotenv()`** 加载密钥。

```powershell
Set-Location <你的克隆路径>\browser-use
```

```bash
cd /path/to/browser-use
```

### 2.2 Python 依赖

```powershell
uv sync
```

若本地尚未安装自动化所用的 Chromium，可按官方 README 执行（按需）：

```powershell
uvx browser-use install
```

### 2.3 `.env` 中与环境变量相关的密钥

| 实验 | 至少需要的环境变量 |
|------|---------------------|
| **A** | `BROWSER_USE_API_KEY`（Browser Use Cloud，供 **`ChatBrowserUse`**） |
| **B** | `BROWSER_USE_API_KEY` + **`DEEPSEEK_API_KEY`**（DeepSeek 领航员） |
| **C** | **`ARK_API_KEY`**（豆包 / Volcengine Ark OpenAI 兼容执行器，默认模型 `doubao-seed-2-0-pro-260215`） |
| **D** | **`ARK_API_KEY`** + **`DEEPSEEK_API_KEY`**（豆包执行器 + DeepSeek 领航员） |

说明：

- **执行器**为 **`ChatBrowserUse`** 时，读 **`BROWSER_USE_API_KEY`**（可在 [Browser Use Cloud](https://cloud.browser-use.com/new-api-key) 创建）。
- **执行器**为 **OpenAI 兼容** 时：预设 **C/D** 默认 **豆包（Ark）** → **`ARK_API_KEY`**；若用 **`--executor-model qwen3-max`** 等 Qwen 模型，则走 **`DASHSCOPE_API_KEY`**（`resolve_openai_compatible_credentials` 按模型 id 自动推断）。其它变量名可用 **`--executor-api-key-env`** 覆盖。
- **领航员**使用 DeepSeek 时，默认从 **`DEEPSEEK_API_KEY`** 读取（或用 **`--navigator-deepseek-api-key-env`** 改名）。

示例 `.env`（按需增减行，勿提交到 Git）：

```env
BROWSER_USE_API_KEY=你的_browser_use_密钥
DEEPSEEK_API_KEY=你的_deepseek_密钥
ARK_API_KEY=你的_火山方舟_豆包_密钥
DASHSCOPE_API_KEY=你的_DashScope_Qwen_密钥
```

（**C/D 跑豆包默认只需 `ARK_API_KEY`**；仅当 CLI 显式指定 Qwen 执行模型时才需要 `DASHSCOPE_API_KEY`。）

### 2.4 国内百炼 vs 新加坡等国际地域（避免 401）

阿里云 **OpenAI 兼容模式** 的 `base_url` 必须与 **API Key 签发地域** 一致，否则会 **`401 invalid_api_key`**：

| 地域 | 兼容模式 `base_url`（CLI 默认值已对齐国内） |
|------|-----------------------------------------------|
| **中国内地（北京，国内百炼控制台申请的 Key）** | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| **新加坡等国际** | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |

本仓库日常实验里，预设 **C/D 的执行器默认豆包（Volcengine Ark）**，不依赖 DashScope；若你改用 **Qwen**（**`--executor-model qwen3-max`** 等），**`ExecutorConfig` / 自定义领航（Qwen）** 的默认地址为 **国内 `dashscope.aliyuncs.com`**。若 Qwen Key 在 **国际控制台** 创建，请在命令行显式指定：

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment C `
  --executor-base-url https://dashscope-intl.aliyuncs.com/compatible-mode/v1 `
  --navigator-base-url https://dashscope-intl.aliyuncs.com/compatible-mode/v1
```

（仅当自定义领航员使用 Qwen 时需要 `--navigator-base-url`。）

---

## 三、代码与模块地图（你要改逻辑时去哪里找）

### 3.1 命令行入口（你只跑实验时通常只碰这个）

| 路径 | 作用 |
|------|------|
| **`examples/evaluation/daily_task_comparison.py`** | 子命令 **`init` / `run-agent` / `compare`** |

查看参数说明：

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent --help
```

### 3.2 核心库（扩展实验、改预设、接新模型）

包路径：**`browser_use/experiments/daily_task_eval/`**

| 模块 | 主要内容 |
|------|----------|
| **`experiment_presets.py`** | **`DailyExperimentId`**（A/B/C/D）、**`experiment_preset()`**、**`build_configs_from_args()`** |
| **`executor.py`** | **`ExecutorConfig`**、**`build_executor_llm()`**（执行用 LLM） |
| **`navigator.py`** | **`NavigatorConfig`**、**`LLMNavigator`**、**`NavigatorPlanProvider`** |
| **`runner.py`** | **`init_experiment()`**、**`run_agent_task()`**、**`compare_all()`** |
| **`models.py`** | **`TaskCard`**、**`AgentRunSummary`**、**`HumanRunRecord`**、**`ComparisonRecord`** |
| **`prompts.py`** | 拼装发给 Agent / 领航员的文本 |

在代码里程序化跑一次（等价于 CLI 的核心调用）：

```python
import asyncio
from pathlib import Path

from browser_use.experiments.daily_task_eval.experiment_presets import DailyExperimentId, experiment_preset
from browser_use.experiments.daily_task_eval.models import TaskCard, load_json_model_list
from browser_use.experiments.daily_task_eval.runner import run_agent_task


async def main():
	tasks = load_json_model_list(Path("tmp/daily_task_eval/task_cards.json"), TaskCard)
	task = tasks[0]
	executor_cfg, navigator_cfg = experiment_preset(DailyExperimentId.B)
	await run_agent_task(
		task,
		output_dir=Path("tmp/daily_task_eval"),
		scenario_id="normal",
		executor_config=executor_cfg,
		navigator_config=navigator_cfg,
		experiment_id="B",
		max_steps=30,
		headless=False,
	)


asyncio.run(main())
```

---

## 四、逐步操作：从初始化到出报告

### 步骤 1：初始化实验目录与模板文件

**组内共享任务卡（推荐）**：仓库跟踪 **`examples/evaluation/fixtures/task_cards.json`**。克隆后请先 **`mkdir tmp/daily_task_eval`**（若不存在），把该文件**复制**为 **`tmp/daily_task_eval/task_cards.json`**，再执行下面的 **`init`**（**勿**默认使用 **`--overwrite`**）。`init` 会读取已存在的 `task_cards.json`，并为缺失的 **`human_runs.json`** 生成与当前任务 id 对齐的占位；若你曾用旧任务卡跑过 `init`，替换任务卡后请**删除** `human_runs.json` 再 `init` 一次，以免 `task_id` 不一致。

在仓库根目录执行：

```powershell
uv run examples/evaluation/daily_task_comparison.py init
```

默认生成（相对于当前目录）：

| 文件 | 含义 |
|------|------|
| **`tmp/daily_task_eval/task_cards.json`** | 示例 **`TaskCard`** 列表，可整体替换或合并 |
| **`tmp/daily_task_eval/human_runs.json`** | 人工 baseline 占位模板 |
| **`tmp/daily_task_eval/agent_runs.json`** | 初始为空数组 **`[]`**，每次 **`run-agent`** 会追加摘要 |
| **`tmp/daily_task_eval/comparison_report.json`** | **`compare`** 前可为空；生成后为对比结果 |

若目录已存在且需覆盖，加 **`--overwrite`**：

```powershell
uv run examples/evaluation/daily_task_comparison.py init --overwrite
```

自定义输出根目录：

```powershell
uv run examples/evaluation/daily_task_comparison.py init --output-dir ./my_eval
```

后续所有命令保持 **`--output-dir`** / **`--task-cards`** 与之一致即可。

### 步骤 2：编辑任务卡 `task_cards.json`

- JSON 数组，每项符合 **`TaskCard`** schema（见 **`browser_use/experiments/daily_task_eval/models.py`**）。
- 字段 **`category`** 只能是：**`read_only_query`**、**`form_workflow`**、**`download_export`**。
- 你可参考仓库内 **`docs/daily_task_eval/daily_task_cards_document.md`** 里的任务设计与示例 JSON，复制进 **`task_cards.json`**。（本地运行时若自建副本，也可能出现在 `tmp/daily_task_eval/` 下；以仓库文档为准。）

**建议**：每个任务有明确的成功标准、禁止操作（尤其是涉及下单、付款、提交隐私场景）。

### 步骤 3：（可选）填写人工 baseline `human_runs.json`

若要用 **`compare`** 生成「人 vs Agent」对比报告，需要为对应 **`task_id`** + **`scenario_id`** 填写 **`HumanRunRecord`**。

- `scenario_id` 通常为 **`normal`**；若任务卡里定义了 **`failure_modes`**，可与 **`compare`** 逻辑一致地扩展场景（见 **`runner.compare_all`**）。

只做 Agent 跑分、不做人工对比时，可跳过本步，但 **`compare`** 结果里会出现 **`missing_human_baseline`** 类提示。

### 步骤 4：运行 Agent（四项实验 A/B/C/D）

在仓库根目录，对**同一批任务**分别跑四种预设时，每次指定 **`--experiment`**：

```powershell
# A：无领航员 + ChatBrowserUse
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment A

# B：DeepSeek 领航员 + ChatBrowserUse
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment B

# C：无领航员 + 豆包（Volcengine Ark 执行器）
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment C

# D：DeepSeek 领航员 + 豆包
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment D
```

常用可选参数：

| 参数 | 说明 |
|------|------|
| **`--task-id <id>`** | 只跑某一个 **`TaskCard.id`** |
| **`--scenario-id <id>`** | 场景 ID，默认 **`normal`** |
| **`--max-steps N`** | 单任务最大步数，默认 **30** |
| **`--llm-timeout N`** | 单次 LLM 调用超时（秒），默认 **180**（国内百炼若仍慢可调大到 **240** / **300**） |
| **`--max-actions-per-step N`** | 单步动作数上限。**默认按执行器自动**：Qwen / OpenAI 兼容 → **1**（避免多动作 JSON 串到 URL，例如 `%7D%7D`）；ChatBrowserUse → **3** |
| **`--step-timeout N`** | 单步总超时（秒，含 LLM + 浏览器 + DOM）。**默认沿用 Agent 上游 180s**。诊断 step 卡死时调小到 **60**，让超时更快发生，便于看到卡住前后的日志 |
| **`--heartbeat-seconds N`** | runner 心跳频率（秒），默认 **30**。每隔 N 秒打印一行 `[eval-runner] ... heartbeat: total=…s step=… step_elapsed=…s url=…`；**0 关闭** |
| **`--log-level {debug,info,warning,result}`** | 覆写 `BROWSER_USE_LOGGING_LEVEL`。**诊断 step 卡死时设为 `debug`**，可看到 DOM/CDP/bubus 事件耗时与 watchdog 警告 |
| **`--max-failures N`** | LLM 解析 / tool-call 连续失败容忍次数，默认 **3**。**Qwen 在大 DOM 上 tool-calling 偶发坏 JSON**，可调到 **6–8** 给它更多重试机会 |
| **`--use-vision {auto,true,false}`** | **覆盖本次 run 的执行器截图/视觉策略**（在 **`--experiment` 解析之后**再套上，不必改预设代码）。**`false`**：Agent **`use_vision=False`**，且不做每步 **CDP 状态截图**，适合 **`map.baidu.com` / `amap.com`** 等重型页面，减轻 **`ScreenshotWatchdog`** / **`captureScreenshot`** 拖死整条 **`BrowserStateRequest`**。**`auto`**：与 **`ExecutorConfig.use_vision='auto'`** 一致：ChatBrowserUse 为「仅在上一步用过 **`screenshot` 工具」时再进行状态截图」；OpenAI 兼容（Qwen）实验 harness 仍会像原来一样把 **`auto`** 映射成传给 Agent 的 **`False`**。**`true`**：每步都对浏览器状态做一次截图（多模态、负载最大）。原理与排查记录：**`docs/issue-notes/heavy-spa-screenshot-timeouts.md`** |
| **`--continuous-navigation`** | **持续领航（周期）**：在 Agent 多步循环中按策略调用与开场 **`NavigatorConfig` / `LLMNavigator`** 同源的领航 LLM，并把短子目标顶在执行者 **`agent_state`** 前（与仅写入一次 **`navigator_plan.md`** 不同）。**仅适用于已启用领航员的预设**（如 **B、D**）；与 **A、C** 组合会因无领航员而报错退出。与 **`EXPERIMENT_RECORD.md`** 中「持续领航 = 是/否」对齐时务必注明本开关是否开启。 |
| **`--headless`** | 无头浏览器 |

示例（只跑指定任务、实验 D、无头）：

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment D --task-id shopping_price_compare --headless
```

**持续领航**（**B / D** 示例；需已配置 DeepSeek 等领航密钥）：

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment D --continuous-navigation
```

在线地图或同类重 SPA（易触发截图看门狗超时）时可显式关视觉截图，例如：

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent `
  --experiment C --task-id nearby_hospital_phone_lookup --use-vision false
```

**注意**：**`agent_runs.json` 会累积追加**。同一任务同一 **`scenario_id`** 跑多次（例如 A 再跑 B），会产生多条记录；**`compare`** 会为匹配的每条 Agent 记录各生成一条对比（见下文）。

#### 不使用 `--experiment` 时的自定义组合

与 **`--experiment` 互斥**：不可同时使用 **`--use-navigator`** 与 **`--experiment`**。

自定义时需理解两组概念：

- **执行器**：**`--executor-backend chat_browser_use`** 或 **`openai_compatible`**
- **领航员**：**`--navigator-backend none | deepseek | openai_compatible`**

简写：**`--use-navigator`** 等价于 **`--navigator-backend openai_compatible`**（默认 Qwen 兼容接口）。

详见：

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent --help
```

### 步骤 5：生成对比报告 `comparison_report.json`

在仓库根目录：

```powershell
uv run examples/evaluation/daily_task_comparison.py compare
```

默认读取：

- **`tmp/daily_task_eval/task_cards.json`**
- **`tmp/daily_task_eval/human_runs.json`**
- **`tmp/daily_task_eval/agent_runs.json`**

写出：

- **`tmp/daily_task_eval/comparison_report.json`**
- **`tmp/daily_task_eval/experiment_resource_report.json`**（跨实验资源分组；可用 **`compare --no-resource-report`** 关闭）

终端另输出 **【学术效率前沿分析】**（实验 **C** vs **D** 的 `navigator_overhead_ratio` / `token_efficiency_score` 等），详见 **§1.3**。

若你的目录不同：

```powershell
uv run examples/evaluation/daily_task_comparison.py compare `
  --task-cards ./my_eval/task_cards.json `
  --human-runs ./my_eval/human_runs.json `
  --agent-runs ./my_eval/agent_runs.json `
  --output-path ./my_eval/comparison_report.json
```

---

## 五、报告与轨迹在哪里看

### 5.1 汇总级：`agent_runs.json`（推荐先看）

路径：**`<output-dir>/agent_runs.json`**

每条记录是一个 **`AgentRunSummary`**，包含例如：

- **`experiment_id`**：`A` / `B` / `C` / `D`（若用了 **`--experiment`**）
- **`executor_backend`**、**`executor_model`**
- **`navigator_enabled`**、**`navigator_model`**、**`navigator_backend`**
- **`success`**、**`is_done`**、**`duration_seconds`**、**`number_of_steps`**
- **`navigator_overhead_ratio`**、**`execution_velocity`**、**`token_efficiency_score`**（学术效率度量，见 **§1.3**）
- **`errors`**、**`urls`**、**`final_result`**
- **`history_path`**、**`conversation_path`**、**`navigator_plan_path`**：指向同一次运行的详细文件

便于横向对比四次实验时，可按 **`task_id`** + **`scenario_id`** + **`experiment_id`** 过滤。

**按任务类别（`TaskCard.category`）分组**：每条摘要含 **`task_category`**（与任务卡上的 **`read_only_query` / `form_workflow` / `download_export`** 一致；旧数据缺该字段时为 **`null`**）。便于只对比「表单类」或「只读查询类」的成功率与耗时。

若已安装 [jq](https://jqlang.github.io/jq/)，可例如只取表单类跑次：

```bash
jq '[.[] | select(.task_category == "form_workflow")]' tmp/daily_task_eval/agent_runs.json
```

对比报告 **`comparison_report.json`** 中每条 **`ComparisonRecord`** 同样带 **`task_category`**，可用相同方式过滤后再做表格式汇总。

### 5.2 跨实验资源：`experiment_resource_report.json`（不依赖人工 baseline）

每次 **`compare`** 默认还会写出与 **`comparison_report.json` 同目录** 的 **`experiment_resource_report.json`**（可用 **`--resource-report PATH`** 指定路径，或用 **`--no-resource-report`** 关闭）。

该文件把 **`agent_runs.json`** 按 **`(task_id, scenario_id)`** 分组；文件开头有 **`groups_index`**（与 **`groups`** 顺序一致：每项含 **`task_id` / `scenario_id` / `snapshot_count` / `experiment_ids`**），便于先扫任务再展开大块 **`snapshots`**。**`groups`** 内顺序默认与 **`compare`** 读入的 **`task_cards.json`** 中任务顺序一致（同一任务下场景按 **`normal`** 再按 **`failure_modes.id`** 排序）；若 **`agent_runs`** 里有任务卡未声明的 task，则排在最后并按 **`(task_id, scenario_id)`** 字典序追加。每组内 **`snapshots`** 按 **`started_at`** 排序；**`duration_seconds`** 若历史为 0 会用墙钟 **`started_at`/`finished_at`** 回填并标 **`duration_used_wall_clock_fallback`**。**`statistics_by_experiment`** / **`pooled_statistics`** 为描述统计（**`n`、均值、样本标准差、min/max/median**），除时长/步数/Token/费用外，亦包含 **§1.3** 三项学术效率指标的 per-run 聚合。**`compare` 完成后终端会打印 C vs D 的「学术效率前沿分析」摘要**（与 JSON 内数值一致）。**`analysis_hints`** 为英文对照提示。

**建议的分析方法**

1. **固定场景再比配方**：同一 **`task_id`** 下先按 **`scenario_id`** 拆开（**`normal`** 与各 **`failure_modes.id`**），只在同一场景里对比 A/B/C/D，避免把「失败注入场景」与主路径混算。
2. **多维表**：对每个 **`experiment_id`** 做一行，列 **`success`**、**`total_cost`**、**`total_tokens`**、**`duration_seconds`**、**`number_of_steps`**；成本与 token 缺失时先看时间与步数。
3. **Pareto 取舍**：优先「**`success: true`** 且 **`total_cost` 低**」；若更便宜但更慢，再结合 **`duration_seconds`** 与业务 SLA。
4. **领航员成本**：看组内 **`navigator_enabled`** 与原始 **`agent_runs` 条目里的 `navigator_initial_plan_usage`**（计划首调用通常不计入 **`usage_summary.total_cost`**，需单独扫一眼）。
5. **下游工具**：用 **`jq`** / 小脚本 **`pandas`** 读 **`experiment_resource_report.json`**，按 **`task_category`** 或 **`experiment_id`** 透视即可做横向图。也可在同一目录用 **`daily_task_comparison.py export-csv --input …/experiment_resource_report.json`** 生成 **`_runs.csv`** 与 **`_stats.csv`**（或用 **`--mode agent-runs --input …/agent_runs.json`** 导出单表 **`_export.csv`**）。

### 5.3 对比级：`comparison_report.json`

路径：**`<output-dir>/comparison_report.json`**

每条为 **`ComparisonRecord`**：人工状态、Agent 是否成功、耗时差、**`risk_flags`**、**`differences`**、**`recommended_next_changes`** 等。  
其中也会带上 Agent 侧的 **`experiment_id`**（若摘要中存在）。尚未填人工 baseline 时，常见 **`risk_flags`** 含 **`missing_human_baseline`**，可暂时忽略，改以 **`experiment_resource_report.json`** 做资源向对比。

### 5.4 单次运行目录（最细粒度）

每次 **`run-agent`** 会在 **`output_dir`** 下写入类似结构：

- **未使用 `--experiment`** 时：

  `agent_runs/<task_id>/<scenario_id>/<UTC时间戳>/`

- **使用 `--experiment B`** 时：

  `agent_runs/<task_id>/<scenario_id>/exp-B/<UTC时间戳>/`

该目录内常见文件：

| 文件 | 含义 |
|------|------|
| **`history.json`** | Agent 完整历史（步骤、动作等） |
| **`conversation.json`** | 对话与模型交互轨迹 |
| **`navigator_plan.md`** | 若启用领航员，预先生成的计划文本 |
| **`downloads/`** | 本次运行下载目录 |
| **`traces/`** | 调试轨迹（若启用） |

从 **`agent_runs.json`** 里对应条目的 **`history_path`** 等字段可直接打开这些文件。

### 5.5 人工 baseline：`human_runs.json`

用于 **`compare`** 与 **`ComparisonRecord`**；字段含义见 **`HumanRunRecord`**（**`models.py`**）。

---

## 六、实验设计对照表（A/B/C/D）

| 预设 | 领航员 | 执行 LLM | 典型环境变量 |
|------|--------|----------|----------------|
| **A** | 无 | **ChatBrowserUse**（`bu-latest`） | `BROWSER_USE_API_KEY` |
| **B** | **DeepSeek**（计划） | **ChatBrowserUse** | `BROWSER_USE_API_KEY` + `DEEPSEEK_API_KEY` |
| **C** | 无 | **豆包**（Volcengine Ark，`doubao-seed-2-0-pro-260215`） | **`ARK_API_KEY`** |
| **D** | **DeepSeek** | **豆包**（同上） | **`ARK_API_KEY`** + **`DEEPSEEK_API_KEY`** |

预设定义代码：**`browser_use/experiments/daily_task_eval/experiment_presets.py`** 中的 **`experiment_preset()`**（**`DEFAULT_DOUBAO_EXECUTOR_MODEL`**）。

**豆包 / Volcengine Ark 执行器**：预设 **C/D** 已默认使用豆包。**`build_executor_llm()`** 对 `doubao-*` / `ep-*`（或 Ark base URL）会设置 **`dont_force_structured_output=True`**、**`add_schema_to_system_prompt=True`**、**`temperature=0.0`**（Ark 不接受 OpenAI `response_format.type=json_schema`）。若改回 Qwen：**`--executor-model qwen3-max`**（自动切 **`DASHSCOPE_API_KEY`**）。

**与 `--continuous-navigation` 的关系**：上表只描述「谁当执行器 / 谁当领航员」。**B / D** 在默认 CLI 下仍会**先**写 **`navigator_plan.md`** 并注入上下文；是否在多步中**再**周期调用同一套领航配置，由 **`--continuous-navigation`** 单独决定。对比不同论文或内部结论时，请在 **`EXPERIMENT_RECORD.md`** 与原始命令行中显式标注是否开启持续领航（见该文档文首）。

---

## 七、常见问题

1. **`DEEPSEEK_API_KEY is not set`**  
   跑 **B** 或 **D** 前确认 `.env` 已加载且变量名正确，或在 Shell 中 **`$env:DEEPSEEK_API_KEY = "..."`**（PowerShell）。

2. **`ARK_API_KEY is not set`**（或执行器所用变量未设置）  
   跑 **C** 或 **D**（默认豆包执行器）时出现；在 `.env` 中配置 **`ARK_API_KEY`**。若你显式改用 Qwen（**`--executor-model qwen3-max`**），则需 **`DASHSCOPE_API_KEY`**，或用 **`--executor-api-key-env`** 指向实际变量名。

3. **`--use-navigator cannot be combined with --experiment`**  
   预设已固定领航员策略；不要用 **`--use-navigator`** 搭配 **`--experiment`**。

4. **`agent_runs.json` 越来越大**  
   属于追加写入设计；可备份后手动删减数组，或为每次大规模实验换一个新的 **`--output-dir`**。

5. **想用国内 DashScope 其它 endpoint / 模型名**  
   使用自定义模式下的 **`--executor-base-url`**、**`--executor-model`**、**`--navigator-base-url`**、**`--navigator-model`** 等覆盖默认值。

6. **`LLM call timed out after 75 seconds`（或仍偶发超时）**  
   本实验 CLI 已默认 **`--llm-timeout 180`** 传给 Agent。若百炼首包仍慢，可加大：例如 **`--llm-timeout 300`**。

7. **Qwen 给出的 URL 出现 `%7D%7D`（即 `}}`）或 `]` 残骸**  
   Qwen 在多动作输出时容易把后续动作的 JSON 闭括号串进前一个动作的字符串字段（常见为 URL）。Runner 现已对 OpenAI 兼容执行器自动设 **`max_actions_per_step=1`**；如需手动覆盖，使用 **`--max-actions-per-step`**。

8. **某一步卡很久 / `Step N timed out after 180 seconds`，但不知道卡在哪**  
   见下文 **§7.1 诊断卡死的 step**。

9. **页面已经成功打开，但 Agent 第 5 步直接 `done(success=False)`，理由是 *"failed to output in correct format for three consecutive attempts"***  
   这是 **Qwen tool-calling 在大 DOM 上不稳定**：page DOM 一变大（例如百度地图首页），Qwen 偶发输出无法被解析的 JSON，连续 3 次后触发 browser-use 内置 `max_failures=3` 强制终止。判定方法：
   - `history.json` 只有少量记录（步号不连续，例如只有 step 1 和 step 5）
   - conversation 末尾出现 `You failed 3 times. Therefore we terminate the agent.`
   - `<agent_history>` 里连续 **`Agent failed to output in the right format.`** 表示「上一轮没有成功解析出结构化 **`AgentOutput`**」，不是磁盘 `json` 文件损坏；机制说明见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**。
   
   **缓解**：
   1. 加大重试上限：**`--max-failures 8`**，给 Qwen 更多机会随机成功
   2. 打开 debug 看 Qwen 真实输出：**`--log-level debug`**，搜索 `Could not parse model output` 或 `tool_calls` 行
   3. 切换更稳的 tool-calling 模型：换 **`--executor-model qwen-plus`** 或 **`--executor-model qwen3-coder-plus`**；或干脆换实验 **B（DeepSeek 领航 + ChatBrowserUse）**
   4. 若任务会长时间停在百度地图等重页：加 **`--use-vision false`**，避免每步 CDP 状态截图与地图 WebGL/瓦片叠加导致超时（见常用参数表 **`--use-vision`**）

10. **`continuous_navigation requires navigator_config.enabled=True`（或类似报错）**  
   说明你对 **A** 或 **C** 加了 **`--continuous-navigation`**。该开关仅适用于 **B / D** 等「预设里已启用领航员」的组合；去掉开关或改用 **B / D**。

### 7.1 诊断卡死的 step（`Step N timed out` 排错三步法）

**症状**：日志只看到 **`Step 14:`** 之后空白很久，最后弹出 **`⏰ Step 14 timed out after 180 seconds`**，无法判断是 LLM 慢、浏览器卡、还是 DOM 提取死锁。

**原因**：单步整体超时（**`step_timeout`**，默认 180s）覆盖 LLM 调用、浏览器导航、截图、DOM 序列化、bubus 事件分发等所有阶段。普通 INFO 日志只在每阶段完成后才打印，所以阶段中途卡住时屏幕是静默的。

**对策（按顺序加开关，越往后越细）**：

**(1) 先打开心跳 + 调小单步超时，让卡死现象快速复现**

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent `
  --experiment C --task-id shopping_price_compare `
  --step-timeout 60 `
  --heartbeat-seconds 15
```

每 15 秒会打印类似：

```
INFO     [browser_use.experiments.daily_task_eval.runner] [eval-runner] shopping_price_compare/normal exp-C heartbeat: total=45s step=14 step_elapsed=30s url=https://www.jd.com/
```

- 同一 **`step=N`** 的 **`step_elapsed`** 持续增长 → 这一步真的卡住了。
- **`step_elapsed`** 不停归零、**`step=N`** 在自增 → 不是卡，是 step 真的多。

**(2) 再加 debug 日志，看是哪个阶段卡住**

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent `
  --experiment C --task-id shopping_price_compare `
  --step-timeout 60 --heartbeat-seconds 15 `
  --log-level debug
```

读 **`Step N`** 与 **`Step N+1`** 之间的日志关键字：

| 看到的关键字 | 阶段 | 解决方向 |
|---|---|---|
| `🤖 Calling LLM...` 之后无后续 | **LLM 调用慢** | 加大 **`--llm-timeout`**（百炼首包慢）；或换更快模型 **`--executor-model qwen3-plus`** |
| `LLM call timed out after Ns` | **LLM 调用超时** | 同上 |
| `EventBus_... handler ... has been running for >15s` | **浏览器/CDP 事件慢或死锁** | 看具体 handler 名（`on_NavigateToUrlEvent` / `on_ScreenshotEvent` / `on_BrowserStateRequestEvent`） |
| `Navigation failed: net::ERR_NETWORK_CHANGED` 或 `ERR_TIMED_OUT` | **网络问题** | 重新连接 / 换网络；URL 是否被 **`%7D%7D`** 污染（见问题 7） |
| `ScreenshotWatchdog` 相关警告 | **页面渲染太重 / 截图卡** | 优先试 **`--use-vision false`**（见步骤 4 常用参数）；仍不够再加大 **`--step-timeout`**；或 **`--headless`** + 降低分辨率；或换更轻的目标站点 |
| `dom` / `BrowserStateSummaryEvent` 长时间无回应 | **DOM 序列化慢**（页面 DOM 极大） | 在 task card 限制只在首页操作，避免进入产品列表瀑布流 |
| `Cannot navigate - browser not connected` / `Agent focus target ... detached` | **浏览器进程崩溃 / 标签被关** | 可能是杀进程或 OOM；改 **`--headless`** + 减少并发任务 |

**(3) 确认是 LLM 卡时，打开 LLM 客户端层面的 debug**

PowerShell 临时设置：

```powershell
$env:OPENAI_LOG = "debug"   # ChatOpenAI / DashScope 兼容客户端
```

然后重跑命令，会看到 HTTP 请求体与流式 chunk 时间，帮你判断是首包慢还是中途断流。

**经验默认搭配（推荐排错时使用）**：

```powershell
--step-timeout 90 --heartbeat-seconds 15 --log-level debug
```

排错完成后再恢复默认（去掉这三个参数）。

---

## 八、相关文件索引

| 用途 | 路径 |
|------|------|
| CLI 入口 | `examples/evaluation/daily_task_comparison.py` |
| **论文框架（章节占位，与实现对齐）** | `examples/evaluation/PAPER_FRAMEWORK.md` |
| 本手册 | `examples/evaluation/DAILY_TASK_EXPERIMENT_GUIDE.md` |
| **`agent_runs.json` LLM 用量字段** | 见上文 **§1.1**（`usage_summary`、`usage_executor_llm`、`usage_navigator_cycle_llm` 等） |
| **学术效率度量（三指标 + C/D 前沿分析）** | 见上文 **§1.3**；实现 **`models.py`** / **`runner.py`** |
| **成功跑次人读归档（按 A/B/C/D 分表）** | `examples/evaluation/EXPERIMENT_RECORD.md` |
| **实验问题与对策日志（按类别）** | `examples/evaluation/DAILY_TASK_EXPERIMENT_LOG.md` |
| **组员最短复现路径（克隆 → init → run → compare）** | 仓库根目录 **`README.md`** |
| 重型 SPA / 地图页与截图超时（问题记录） | `docs/issue-notes/heavy-spa-screenshot-timeouts.md` |
| 实验包 | `browser_use/experiments/daily_task_eval/` |
| 任务卡示例生成 | `runner.default_task_cards()` / `init` 写入的 JSON |

---

若你后续希望把「实验 ID + 时间戳」写入 **`scenario_id`** 或分拆多份 **`agent_runs.json`**，可以在 **`run_agent_command`** 外包一层 shell 脚本或在本仓库内扩展 CLI；当前设计以 **`experiment_id` 字段 + 目录 `exp-*`** 区分四次配方为主。
