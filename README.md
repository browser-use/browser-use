## 项目简介

本仓库用于**日常任务（Daily Task）对比实验**：用 Browser Use 的 `Agent` 自动执行一组可重复的浏览器任务（Task Cards），并与人工 baseline 做结构化对比，输出可审阅的报告与轨迹文件。

- **实验入口脚本**：`examples/evaluation/daily_task_comparison.py`
- **核心实现模块**：`browser_use/experiments/daily_task_eval/`
- **完整操作手册**：`examples/evaluation/DAILY_TASK_EXPERIMENT_GUIDE.md`（排错、用量字段、地域与 401 等以手册为准）
- **Task Cards 设计参考**：`docs/daily_task_eval/daily_task_cards_document.md`
- **论文框架（章节占位 + 与代码对齐）**：`examples/evaluation/PAPER_FRAMEWORK.md`（跑完实验后把 `[待填]` / 表格换成结果即可）
- **成功跑次人读归档（按 A/B/C/D）**：`examples/evaluation/EXPERIMENT_RECORD.md`
- **实验问题与对策日志**：`examples/evaluation/DAILY_TASK_EXPERIMENT_LOG.md`

相对上游 **browser-use**，本仓库还包含：**Agent 侧「持续领航」**（`continuous_navigation` + 周期注入领航子目标）、**实验 CLI 全套超时/视觉/心跳/重试开关**、**`agent_runs.json` 中的 LLM 用量拆分字段**，以及 **`browser_use/cli_navigator.py`**（主 CLI TUI 在开启持续领航时解析领航用 LLM）。重型地图 SPA 与截图超时背景见 **`docs/issue-notes/heavy-spa-screenshot-timeouts.md`**。

> 说明：本仓库基于开源项目 **browser-use** 演进（见文末「上游与致谢」）。README 以「组员能复现跑实验」为第一优先。

---

## 从克隆到第一次出报告（复现清单，推荐组员按序执行）

以下均在**仓库根目录**（与 `pyproject.toml` 同级）执行。`tmp/` 在 `.gitignore` 中，克隆后本地**不会**自带 `tmp/daily_task_eval/`，必须先 `init`。

1. **克隆并进入目录**

   ```bash
   git clone <你们的仓库 URL> browser-use
   cd browser-use
   ```

2. **Python 与依赖**（需 Python **≥ 3.11**，与 `pyproject.toml` 一致）

   ```bash
   uv sync
   ```

   若尚未安装本机 Chromium（按需）：

   ```bash
   uvx browser-use install
   ```

3. **环境变量**  
   在根目录创建 **`.env`**（勿提交）。最小可跑 **实验 A** 仅需 `BROWSER_USE_API_KEY`。A/B/C/D 各预设所需变量见下文「密钥与实验配方」；地域与 DashScope `base_url` 见手册 **§2.4**。

4. **初始化实验目录**（生成 `task_cards.json`、`human_runs.json` 等）

   - **与组内仓库对齐的任务卡**：先把 **`examples/evaluation/fixtures/task_cards.json`** 复制到 **`tmp/daily_task_eval/task_cards.json`**（没有目录就先建 `tmp/daily_task_eval`），再执行下面的 **`init`**。**不要**加 **`--overwrite`**（否则会清空并写回内置三张示例任务卡）。此时若还没有 **`human_runs.json`**，会根据**当前** `task_cards.json` 自动生成占位条目。  
   - 若你**先** `init` 过、**后**才替换任务卡，请**删掉** `tmp/daily_task_eval/human_runs.json` 再跑一次 **`init`**（仍不要 `--overwrite`），否则会沿用旧 `human_runs` 里的 `task_id`，与新区不匹配。  
   - **从零只要模板**：不复制 fixtures，直接 **`init`** 即可。

   ```bash
   uv run examples/evaluation/daily_task_comparison.py init
   ```

5. **跑一轮 Agent**（示例：预设 A；可加 `--task-id <id>` 只跑一张任务卡）

   ```bash
   uv run examples/evaluation/daily_task_comparison.py run-agent --experiment A
   ```

   需要**周期领航**（与仅生成开场 `navigator_plan.md` 不同）时，在 **B / D** 上附加 **`--continuous-navigation`**（要求预设已启用领航员）。详见 `EXPERIMENT_RECORD.md` 文首说明与手册 **§四** 参数表。

6. **生成对比报告**（需按需填写 `human_runs.json`；未填则报告中会有缺失 baseline 类提示）

   ```bash
   uv run examples/evaluation/daily_task_comparison.py compare
   ```

7. **（可选）自检本模块 CI 测试**

   ```bash
   uv run pytest -q tests/ci/test_daily_task_comparison.py tests/ci/test_continuous_navigation.py
   ```

**Windows PowerShell**：多行命令可用反引号 `` ` `` 续行；或写成一行。**Git Bash** 可用 `\` 续行。

---

## 快速参考：密钥与实验配方（A/B/C/D）

在根目录 `.env` 中按需配置：

```env
BROWSER_USE_API_KEY=你的_browser_use_密钥
DEEPSEEK_API_KEY=你的_deepseek_密钥
DASHSCOPE_API_KEY=你的_dashscope_qwen_密钥
```

| 预设 | 至少需要的环境变量 |
|------|---------------------|
| **A** | `BROWSER_USE_API_KEY`（`ChatBrowserUse`） |
| **B** | `BROWSER_USE_API_KEY` + `DEEPSEEK_API_KEY`（DeepSeek 领航） |
| **C** | `DASHSCOPE_API_KEY`（Qwen OpenAI 兼容执行器） |
| **D** | `DASHSCOPE_API_KEY` + `DEEPSEEK_API_KEY` |

运行示例：

```bash
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment A
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment B
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment C
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment D
```

常用调参（完整列表见 **`run-agent --help`** 与手册 **§四**）：`--continuous-navigation`、`--llm-timeout`、`--step-timeout`、`--heartbeat-seconds`、`--max-failures`、`--use-vision {auto,true,false}`、`--log-level`、`--max-actions-per-step`、`--headless` 等。

---

## 目录与代码地图（改逻辑时看这里）

### 命令行入口

- `examples/evaluation/daily_task_comparison.py`：子命令 `init` / `run-agent` / `compare`

### 日常实验核心包

目录：`browser_use/experiments/daily_task_eval/`

- `experiment_presets.py`：实验配方 A/B/C/D；从 CLI 参数构建配置
- `executor.py`：执行器 LLM 配置与构建
- `navigator.py`：领航员（navigator）与规划逻辑
- `runner.py`：初始化、单任务运行、对比汇总；心跳与 `continuous_navigation` 传入 Agent
- `models.py`：`TaskCard` / `AgentRunSummary` / `HumanRunRecord` / `ComparisonRecord`（含用量相关字段说明）
- `prompts.py`：实验相关提示词拼装

### Agent / CLI 中与「持续领航」相关的上游改动位置

- `browser_use/agent/service.py`：周期领航注入与 `navigator_llm`
- `browser_use/agent/views.py`：`AgentSettings` 等
- `browser_use/cli_navigator.py`：主 **`browser-use` TUI CLI** 解析领航用 LLM（避免 TUI 侧重复实现）

---

## 产出文件（日志 / 轨迹 / 报告）

默认输出目录：`tmp/daily_task_eval/`（本地生成，不进版本库）

- **结构化摘要**：`agent_runs.json`（每次 `run-agent` 追加；含 `usage_summary`、`usage_executor_llm`、`usage_navigator_cycle_llm`、`navigator_initial_plan_usage` 等，见手册 **§1.1**）
- **单次运行目录**：`agent_runs/<task_id>/<scenario_id>/exp-<A|B|C|D>/<UTC>/` 下的 `history.json`、`conversation.json`、`navigator_plan.md` 等
- **对比报告**：`comparison_report.json`（`compare` 生成）

---

## 上游与致谢

本仓库基于开源项目 **browser-use**，并在其基础上增加了面向「日常任务评估」的实验模块、多模型与领航员配置、持续领航与用量拆分等能力。

- **上游文档**：https://docs.browser-use.com
