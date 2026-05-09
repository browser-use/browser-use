## 项目简介

本仓库用于**日常任务（Daily Task）对比实验**：用 Browser Use 的 `Agent` 自动执行一组可重复的浏览器任务（Task Cards），并与人工 baseline 做结构化对比，输出可审阅的报告与轨迹文件。

- **实验入口脚本**：`examples/evaluation/daily_task_comparison.py`
- **核心实现模块**：`browser_use/experiments/daily_task_eval/`
- **完整操作手册**：`examples/evaluation/DAILY_TASK_EXPERIMENT_GUIDE.md`（强烈建议先通读）
- **Task Cards 设计参考**：`docs/daily_task_eval/daily_task_cards_document.md`

> 说明：本仓库基于开源项目 **browser-use** 演进（见文末“上游与致谢”）。README 以“跑实验”为第一优先。

---

## 快速开始（最常用）

### 1) 安装依赖（Python >= 3.11）

在仓库根目录执行：

```bash
uv sync
```

首次使用且本机没有浏览器依赖时（按需）：

```bash
uvx browser-use install
```

### 2) 配置密钥（`.env`，不要提交）

在仓库根目录创建 `.env`（根据你要跑的实验配方选择最小集合）：

```env
BROWSER_USE_API_KEY=你的_browser_use_密钥
DEEPSEEK_API_KEY=你的_deepseek_密钥
DASHSCOPE_API_KEY=你的_dashscope_qwen_密钥
```

不同实验配方的最小环境变量要求：

- **A**：`BROWSER_USE_API_KEY`（执行器：`ChatBrowserUse`）
- **B**：`BROWSER_USE_API_KEY` + `DEEPSEEK_API_KEY`（DeepSeek 领航员）
- **C**：`DASHSCOPE_API_KEY`（执行器：Qwen OpenAI 兼容接口）
- **D**：`DASHSCOPE_API_KEY` + `DEEPSEEK_API_KEY`

> 如果你使用的是 DashScope **国际站** Key，可能需要把 `base_url` 改到 `dashscope-intl`。详见 `examples/evaluation/DAILY_TASK_EXPERIMENT_GUIDE.md` 的“地域与 401”部分。

### 3) 初始化实验目录（生成模板文件）

```bash
uv run examples/evaluation/daily_task_comparison.py init
```

默认生成在 `tmp/daily_task_eval/`：

- `task_cards.json`：任务卡（你主要编辑这个）
- `human_runs.json`：人工 baseline（可选）
- `agent_runs.json`：每次跑 `run-agent` 会追加摘要
- `comparison_report.json`：跑 `compare` 生成的对比报告

### 4) 跑 Agent（A/B/C/D 四个实验配方）

```bash
# A：无领航员 + ChatBrowserUse
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment A

# B：DeepSeek 领航员 + ChatBrowserUse
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment B

# C：无领航员 + Qwen（OpenAI 兼容执行器）
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment C

# D：DeepSeek 领航员 + Qwen
uv run examples/evaluation/daily_task_comparison.py run-agent --experiment D
```

常用参数（更全的参数见 `--help`）：

```bash
uv run examples/evaluation/daily_task_comparison.py run-agent --help
```

### 5) 生成对比报告（human vs agent）

```bash
uv run examples/evaluation/daily_task_comparison.py compare
```

---

## 目录与代码地图（改逻辑时看这里）

### 命令行入口

- `examples/evaluation/daily_task_comparison.py`：子命令 `init` / `run-agent` / `compare`

### 核心实现

目录：`browser_use/experiments/daily_task_eval/`

- `experiment_presets.py`：实验配方 A/B/C/D；从 CLI 参数构建配置
- `executor.py`：执行器 LLM 配置与构建
- `navigator.py`：领航员（navigator）与规划逻辑
- `runner.py`：初始化、单任务运行、对比汇总
- `models.py`：`TaskCard` / `AgentRunSummary` / `HumanRunRecord` / `ComparisonRecord`
- `prompts.py`：实验相关提示词拼装

---

## 产出文件（你要找日志/轨迹/报告时）

默认输出目录：`tmp/daily_task_eval/`

- **结构化摘要**：`agent_runs.json`（每次 `run-agent` 追加）
- **详细轨迹**：每次运行会写入 `history.json`、`conversation.json` 等（按任务/实验划分目录）
- **对比报告**：`comparison_report.json`（`compare` 生成）

---

## 上游与致谢

本仓库基于开源项目 **browser-use**，并在其基础上增加了面向“日常任务评估”的实验模块与多模型/领航员配置能力。

- **上游文档**：`https://docs.browser-use.com`
