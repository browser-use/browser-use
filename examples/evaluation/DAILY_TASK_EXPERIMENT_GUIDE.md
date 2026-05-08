# 日常任务对比实验：完整操作手册

本文档说明如何在 **browser-use** 仓库中，使用 **`daily_task_comparison.py` CLI** 完成「人工 baseline ↔ Agent」的日常任务评估实验，以及如何阅读产出报告。

实验逻辑实现在 Python 包 **`browser_use.experiments.daily_task_eval`** 中；命令行入口在 **`examples/evaluation/daily_task_comparison.py`**。

---

## 一、实验在做什么

1. 用 **`TaskCard`**（JSON）描述一批可重复的浏览器任务（提示词、成功标准、禁止操作等）。
2. （可选）在 **`human_runs.json`** 中记录人工完成同一任务的步骤与结论，作为 baseline。
3. 用 **`run-agent`** 让 Browser Use **`Agent`** 自动执行任务；每种「实验配方」（A/B/C/D）对应不同的 **执行 LLM** 与是否启用 **领航员（navigator）**。
4. 每次运行会向 **`agent_runs.json`** 追加一条结构化摘要，并在磁盘写入 **`history.json`**、**`conversation.json`** 等详细轨迹。
5. 用 **`compare`** 读取任务卡、人工记录与 Agent 摘要，生成 **`comparison_report.json`**（差异与风险提示）。

---

## 二、环境与密钥（运行前必须）

### 2.1 工作目录

始终在 **`browser-use-main` 仓库根目录** 下执行命令（与 **`pyproject.toml`** 同级），这样：

- 默认路径 **`./tmp/daily_task_eval`** 会落到仓库内的 `tmp/daily_task_eval/`；
- 若你在项目根放了 **`.env`**，`run-agent` 内部会 **`load_dotenv()`** 加载密钥。

```powershell
Set-Location d:\Agent\browser-use-main
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
| **C** | **`DASHSCOPE_API_KEY`**（或你在 CLI 里改的 `--executor-api-key-env` 指向的变量），用于 Qwen 兼容接口执行器 |
| **D** | `DASHSCOPE_API_KEY` + **`DEEPSEEK_API_KEY`** |

说明：

- **执行器**为 **`ChatBrowserUse`** 时，读 **`BROWSER_USE_API_KEY`**（可在 [Browser Use Cloud](https://cloud.browser-use.com/new-api-key) 创建）。
- **执行器**为 **OpenAI 兼容（Qwen）** 时，默认从环境变量 **`DASHSCOPE_API_KEY`** 读取 API Key；若你使用其它变量名，请用 CLI **`--executor-api-key-env`** 指定。
- **领航员**使用 DeepSeek 时，默认从 **`DEEPSEEK_API_KEY`** 读取（或用 **`--navigator-deepseek-api-key-env`** 改名）。

示例 `.env`（按需增减行，勿提交到 Git）：

```env
BROWSER_USE_API_KEY=你的_browser_use_密钥
DEEPSEEK_API_KEY=你的_deepseek_密钥
DASHSCOPE_API_KEY=你的_DashScope_Qwen_密钥
```

### 2.4 国内百炼 vs 新加坡等国际地域（避免 401）

阿里云 **OpenAI 兼容模式** 的 `base_url` 必须与 **API Key 签发地域** 一致，否则会 **`401 invalid_api_key`**：

| 地域 | 兼容模式 `base_url`（CLI 默认值已对齐国内） |
|------|-----------------------------------------------|
| **中国内地（北京，国内百炼控制台申请的 Key）** | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| **新加坡等国际** | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |

本仓库日常实验里，**实验 C / D** 以及 **`ExecutorConfig` / `NavigatorConfig`（Qwen）** 的默认地址已设为 **国内 `dashscope.aliyuncs.com`**。若你的 Key 是在 **国际控制台** 创建的，请在命令行显式指定：

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
- 你可参考仓库内 **`tmp/daily_task_eval/daily_task_cards_document.md`**（若你已自建）里的任务设计与示例 JSON，复制进 **`task_cards.json`**。

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

# C：无领航员 + Qwen（OpenAI 兼容执行器）
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment C

# D：DeepSeek 领航员 + Qwen
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
| **`--headless`** | 无头浏览器 |

示例（只跑指定任务、实验 D、无头）：

```powershell
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment D --task-id shopping_price_compare --headless
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
- **`errors`**、**`urls`**、**`final_result`**
- **`history_path`**、**`conversation_path`**、**`navigator_plan_path`**：指向同一次运行的详细文件

便于横向对比四次实验时，可按 **`task_id`** + **`scenario_id`** + **`experiment_id`** 过滤。

### 5.2 对比级：`comparison_report.json`

路径：**`<output-dir>/comparison_report.json`**

每条为 **`ComparisonRecord`**：人工状态、Agent 是否成功、耗时差、**`risk_flags`**、**`differences`**、**`recommended_next_changes`** 等。  
其中也会带上 Agent 侧的 **`experiment_id`**（若摘要中存在）。

### 5.3 单次运行目录（最细粒度）

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

### 5.4 人工 baseline：`human_runs.json`

用于 **`compare`** 与 **`ComparisonRecord`**；字段含义见 **`HumanRunRecord`**（**`models.py`**）。

---

## 六、实验设计对照表（A/B/C/D）

| 预设 | 领航员 | 执行 LLM | 典型环境变量 |
|------|--------|----------|----------------|
| **A** | 无 | **ChatBrowserUse**（`bu-latest`） | `BROWSER_USE_API_KEY` |
| **B** | **DeepSeek**（计划） | **ChatBrowserUse** | `BROWSER_USE_API_KEY` + `DEEPSEEK_API_KEY` |
| **C** | 无 | **Qwen**（OpenAI 兼容客户端） | `DASHSCOPE_API_KEY`（或可改 env 名） |
| **D** | **DeepSeek** | **Qwen** | `DASHSCOPE_API_KEY` + `DEEPSEEK_API_KEY` |

预设定义代码：**`browser_use/experiments/daily_task_eval/experiment_presets.py`** 中的 **`experiment_preset()`**。

---

## 七、常见问题

1. **`DEEPSEEK_API_KEY is not set`**  
   跑 **B** 或 **D** 前确认 `.env` 已加载且变量名正确，或在 Shell 中 **`$env:DEEPSEEK_API_KEY = "..."`**（PowerShell）。

2. **`DASHSCOPE_API_KEY is not set`**（或执行器所用变量未设置）  
   跑 **C** 或 **D** 时出现；在系统/用户环境变量中配置 **`DASHSCOPE_API_KEY`**，或改用 **`--executor-api-key-env`** 指向你实际使用的变量名。

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
   
   **缓解**：
   1. 加大重试上限：**`--max-failures 8`**，给 Qwen 更多机会随机成功
   2. 打开 debug 看 Qwen 真实输出：**`--log-level debug`**，搜索 `Could not parse model output` 或 `tool_calls` 行
   3. 切换更稳的 tool-calling 模型：换 **`--executor-model qwen-plus`** 或 **`--executor-model qwen3-coder-plus`**；或干脆换实验 **B（DeepSeek 领航 + ChatBrowserUse）**

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
| `ScreenshotWatchdog` 相关警告 | **页面渲染太重 / 截图卡** | 加大 step timeout；或对该任务 **`--headless`** + 降低分辨率；或换更轻的目标站点 |
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
| 本手册 | `examples/evaluation/DAILY_TASK_EXPERIMENT_GUIDE.md` |
| **实验问题与对策日志（按类别）** | `examples/evaluation/DAILY_TASK_EXPERIMENT_LOG.md` |
| 实验包 | `browser_use/experiments/daily_task_eval/` |
| 任务卡示例生成 | `runner.default_task_cards()` / `init` 写入的 JSON |

---

若你后续希望把「实验 ID + 时间戳」写入 **`scenario_id`** 或分拆多份 **`agent_runs.json`**，可以在 **`run_agent_command`** 外包一层 shell 脚本或在本仓库内扩展 CLI；当前设计以 **`experiment_id` 字段 + 目录 `exp-*`** 区分四次配方为主。
