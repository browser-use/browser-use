# Daily task eval — 成功跑次记录

操作与产出说明见 **[`DAILY_TASK_EXPERIMENT_GUIDE.md`](./DAILY_TASK_EXPERIMENT_GUIDE.md)**。本文件记入 **`agent_runs.json` 中全部 `success: true` 跑次**（见 **成功跑次时间线**），并在 **A/B/C/D 分表**中保留各预设**当前代表**的一条便于对照。持续领航 = `--continuous-navigation`（周期领航与初始 `NavigatorConfig` 同源）。**仅开场领航、不再随步更新** 的局限与对策见下节 **「关于领航员只在开头领航」**。

预设含义：A 无领航+BU；B DeepSeek 领航+BU；C 无领航+Qwen；D DeepSeek 领航+Qwen。**注意**：预设 **B** 若跑 **`run-agent` 时未加 `--continuous-navigation`**，则仍只有开场 **`navigator_plan`** 注入执行者上下文，属于本节所述「只领航一次」配置，与 **D + 持续领航** 不宜直接当作同一机制对比。

### 关于「领航员只在开头领航」与效果

早期管线里，领航员仅在任务开始时调用一次 **`create_plan`**，把 **`navigator_plan.md`** 全文拼进执行者的 **`task`/`user_request`**（见 **`build_agent_task_prompt`**）。之后多步里**不再**根据真实页面、失败重试或分支更新该计划。由此常见现象包括：

- 执行者在长任务里**偏离**开场计划（DOM、验证码、地图 SPA 超时等与计划假设不一致），但上下文里仍是一大段**静态**文字，模型容易在长规则里「迷路」或产出畸形 **`navigate` URL**（例如把 JSON 碎片拼进 URL）。
- 开场计划**无法**在卡住或换路径时及时纠偏；与「每步都能看见当前浏览器状态」相比，**战术层**缺位，对比带 **`--continuous-navigation`** 的 B/D 往往更不稳定。

当前实验设计中的对应关系：**表里的「持续领航 = 是」** 表示启用了 **`--continuous-navigation`**（周期调用与初始 **`NavigatorConfig` / `LLMNavigator.create_plan`** 同源），用于缓解上述「只领航一次」问题；另有 **`navigator_current_step`** / **`<current_step_focus>`** 机制把领航员给出的**短子目标**顶在执行者每步 **`agent_state`** 最前，便于对齐「下一步只做一件事」。若某次跑次未开持续领航，可在备注中写明，避免与「仅开头注入计划」的旧配置混淆。归档里若只有 **`navigator_plan.md`** 而无周期领航相关说明，可据此推断为曾用「只开头领航」管线，与后续改进后的 B/D 对比时需在结论中区分配置。

### 成功跑次时间线（`tmp/daily_task_eval/agent_runs.json` 中 `success: true`，按 `started_at` 升序）

以下与下方 **A/B/C/D 分表** 对齐；分表仍表示「各预设当前归档的一条代表跑次」，时间线用于一眼看到**全部**已成功记录。

| # | 日期 (UTC) | 预设 | Task | Scenario | 持续领航 | 执行 / 领航 | 步数 | `duration_seconds`（history 累加） | 摘要 |
|---|------------|------|------|----------|----------|-------------|------|--------------------------------------|------|
| 1 | 2026-05-09 | **D** | `nearby_hospital_phone_lookup` | normal | 是 | `qwen3-max` / `deepseek-chat` | 17 | ~420s | 龙岗坂田 3 家医院；高德 POI 链接；曾走百度搜索畸形词与 amap 畸形 URL |
| 2 | 2026-05-14 | **C** | `nearby_hospital_phone_lookup` | normal | 否 | `qwen3-max` / — | 5 | ~83s | 同一任务在百度地图列表页凑齐 3 条即 `done`（Early-finish）；首跳 URL 曾带 `}}` 碎片后纠正 |

**Artifacts**：① `tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260509T064248Z/` ② `tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260514T080341Z/`（均含 `history.json`、`conversation.json`；D 另含 `navigator_plan.md`）。**失败 / JSON 形态早停样例**（如 `exp-D/20260514T110508Z`）与 **C vs D 写作注意** 见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**。

---

## A — 无领航 · ChatBrowserUse 执行

| 日期 (UTC) | Task | Scenario | 持续领航 | 墙钟 | 步数 | 摘要 |
|------------|------|----------|----------|------|------|------|
| — | — | — | — | — | — | *暂无成功记录* |

---

## B — DeepSeek 领航 · ChatBrowserUse 执行

| 日期 (UTC) | Task | Scenario | 持续领航 | 墙钟 | 步数 | 摘要 |
|------------|------|----------|----------|------|------|------|
| — | — | — | — | — | — | *暂无成功记录* |

---

## C — 无领航 · Qwen 执行

| 日期 (UTC) | Task | Scenario | 持续领航 | 墙钟 | 步数 | 摘要 |
|------------|------|----------|----------|------|------|------|
| 2026-05-14 | `nearby_hospital_phone_lookup` | normal | 否 | `08:03:41`→`08:14:15` Z（~10.5 min 墙钟；history 累加 ~83s） | 5（`usage` invocations 6） | 百度地图搜索列表直接产出 3 家：坂田医院 / 市人民医院坂田院区 / 远东妇产龙岗；电话与地址；来源为列表页检索 URL |

**Artifacts**：`tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260514T080341Z/`

**备注**：与 **D** 同任务对比，本趟**未开**持续领航；步数远少于 D（17）主要因路径留在 **map.baidu.com** 且遵守 **Early-finish**，未再深挖高德 POI 页。执行器侧 **`navigator_current_step`** 仅在有领航注入时有值；C 成功仍受益于任务提示与 Qwen 单步动作约束等（见 **`DAILY_TASK_EXPERIMENT_LOG.md`**、`docs/issue-notes/navigator-current-step-executor-subgoal.md`）。

---

## D — DeepSeek 领航 · Qwen 执行

| 日期 (UTC) | Task | Scenario | 持续领航 | 执行 | 领航 | 墙钟 | 步数 | 摘要 |
|------------|------|----------|----------|------|------|------|------|------|
| 2026-05-09 | `nearby_hospital_phone_lookup` | normal | 是 | `qwen3-max` | `deepseek-chat` | ~19 min (`06:42:59`→`07:02:11` Z) | 17 | 深圳市龙岗区坂田街道 3 家医院；名称 / 电话 / 地址 / 高德 POI 链接 |

**Artifacts**：`tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260509T064248Z/`（含 `navigator_plan.md`、`history.json`、`conversation.json`）

**备注**：`yyk.99.com.cn` 导航失败未阻断；百度搜索词曾含 `'}}` 碎片；出现过畸形 `amap.com/...%7D%7D]%7D`。本跑在 **短子目标 / `<current_step_focus>`** 合入主线之前；B/D 若开 **`--continuous-navigation`**，执行者每步会多 **`navigator_current_step`** 顶栏（见 **`docs/issue-notes/navigator-current-step-executor-subgoal.md`**）。

---

## LLM 用量（与 `agent_runs.json` 对齐）

每台机器可读摘要记录在 **`agent_runs.json`** 对应条目中，关键字段：**`usage_summary`**（ totals + `by_model`）、**`usage_executor_llm`**（执行回路）、**`usage_navigator_cycle_llm`**（持续领航且不合并进执行者 id 时）、**`navigator_initial_plan_usage`**（开场计划单独一次）、**`usage_auxiliary_llm_models`**。控制台 **`cost`** 日志里 **`🧠`**=单次调用、**`🤖`**=按模型累计；语义说明见 **`DAILY_TASK_EXPERIMENT_GUIDE.md` §1.1**；领航 **短子目标** 见 **§1.2** 与 **`docs/issue-notes/navigator-current-step-executor-subgoal.md`**。若需在表中对比资源，可从上述 JSON 摘录 `prompt_tokens` / `completion_tokens` / `invocations`。
