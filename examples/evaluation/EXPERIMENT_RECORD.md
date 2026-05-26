# Daily task eval — 成功跑次记录

操作与产出说明见 **[`DAILY_TASK_EXPERIMENT_GUIDE.md`](./DAILY_TASK_EXPERIMENT_GUIDE.md)**。本文件记入 **`agent_runs.json` 中全部 `success: true` 跑次**（见 **成功跑次时间线**），并在 **A/B/C/D 分表**中保留各预设**当前代表**的一条便于对照。持续领航 = `--continuous-navigation`（周期领航与初始 `NavigatorConfig` 同源）。**仅开场领航、不再随步更新** 的局限与对策见下节 **「关于领航员只在开头领航」**。

**资源与统计（不写进本表细节时）**：跑 **`compare`** 会生成 **`experiment_resource_report.json`**（按任务/场景分组，含 **`groups_index`**、每实验 **`statistics_by_experiment`**、全组合 **`pooled_statistics`**、时长墙钟回填，以及 **§1.3 学术效率三指标** 的聚合统计；终端打印 **C vs D 学术效率前沿分析**，见 **GUIDE §5.2 / §1.3**）。表格化可用 **`daily_task_comparison.py export-csv --input …/experiment_resource_report.json`**。执行器在 CLI 上除 Qwen 外可切 **豆包 / Volcengine Ark**（`doubao-*`、`ep-*` 等，环境变量 **`ARK_API_KEY`**），见 **GUIDE §6** 与 **`daily_task_comparison.py --help`**。

预设含义：A 无领航+BU；B DeepSeek 领航+BU；C 无领航+豆包（Ark）；D DeepSeek 领航+豆包。**注意**：预设 **B** 若跑 **`run-agent` 时未加 `--continuous-navigation`**，则仍只有开场 **`navigator_plan`** 注入执行者上下文，属于本节所述「只领航一次」配置，与 **D + 持续领航** 不宜直接当作同一机制对比。

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
| 3 | 2026-05-26 09:46 | **C**（Doubao 期） | `nearby_hospital_phone_lookup` | normal | 否 | `doubao-seed-2-0-pro-260215` / — | 8 | ~237s（10 invocations，118,755 tokens） | 同任务在豆包默认预设下首次成功；多出 3 步主要来自 `write_file todo.md` + `replace_file`（自我规划，**第 4 条复跑证明是偶发非规律**）；`extract_structured_data` 一次拿全 3 条电话+地址；**source URL 实际全为 not visible，Agent 在 done 中以搜索页 URL 兜底**（per-row source 严格不满足 success_criteria）。 |
| 4 | 2026-05-26 14:08 | **C**（Doubao 期，复跑） | `nearby_hospital_phone_lookup` | normal | 否 | `doubao-seed-2-0-pro-260215` / — | 6 | ~161s（8 invocations，90,917 tokens） | 同命令复跑 Doubao；**没有写 todo**，路径压缩到 `navigate→input→click→wait→extract→done`；本次 `extract` 出来的 **phone 全 not visible**（与第 3 条差异：原因可能是搜索关键词改成"附近医院/诊所"导致排序中夹入门诊部，更深站点信息缺失）；进一步证明 Doubao 自我规划是偶发；source URL 同样为搜索页兜底，仍属 **PARTIAL**。 |
| 5 | 2026-05-26 14:12 | **D**（Doubao 期，DeepSeek 领航 + 持续领航） | `nearby_hospital_phone_lookup` | normal | **是** | `doubao-seed-2-0-pro-260215` / `deepseek-chat` | **5** | ~119s（6 invocations，75,651 tokens） | Doubao 期 D 首次成功；路径 `navigate→input→click→wait→done`，**完全跳过 `extract` 工具**（Doubao 直接从 DOM 看见列表后在 `done` 里写出 3 家完整 phone+address）；3 家电话均为真实号码（与 2026-05-09 D 数据一致）。**但 `usage_navigator_cycle_llm: null`、`by_model` 中无 deepseek**：要么 DeepSeek 持续领航在本跑次未真正触发周期调用，要么调用未走 TokenCost 通道 → **当前无法证明"D 优于 C 是因为 navigator"**。 |

**Artifacts**：
- ① `agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260509T064248Z/`（D · Qwen 期）
- ② `agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260514T080341Z/`（C · Qwen 期）
- ③ `agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260526T094651Z/`（C · Doubao 期 · 8 步）
- ④ `agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260526T140809Z/`（C · Doubao 期 · 6 步复跑）
- ⑤ `agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260526T141221Z/`（D · Doubao 期 · 5 步）

均含 `history.json`、`conversation.json`；D 另含 `navigator_plan.md`。**失败 / JSON 形态早停样例**（如 `exp-D/20260514T110508Z`）与 **C vs D 写作注意** 见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**。

**模型版本切分点**：自 2026-05-21 提交 `48d1660b` 起，C/D 默认执行器从 **Qwen（`qwen3-max` · DashScope）** 改为 **Doubao（`doubao-seed-2-0-pro-260215` · Volcengine Ark）**。表中 2026-05-26 之后的 C/D 记录默认是 Doubao 时期；若仍用 Qwen 跑（`--executor-model qwen3-max`），请在备注中注明，避免混淆。

**Doubao 期初步统计**（基于 2026-05-26 ③④⑤ 3 条跑次 · 详见 `experiment_resource_report.json`）：

| 维度 | C（n=2） | D（n=1） | hint |
|---|---|---|---|
| `duration_seconds` mean | 199.0 (median 199.0, std 54.3) | 119.2 | D 最快，C 最慢 |
| `number_of_steps` mean | 7.00 (std 1.41) | 5.00 | D 最少步 |
| `total_tokens` mean | 104,836 (std 19,684) | 75,651 | D 最省 token |
| `navigator_overhead_ratio` mean | 0.0000 | 0.0000 | **两组都是 0**：要么没领航 token，要么领航周期未拆分 |
| `token_efficiency_score` mean | 0.0097 | 0.0132 | D 千 token 成功率较高 |
| `execution_velocity` mean (tok/s) | 533.2 | 634.9 | D 推理吞吐略高 |

> ⚠️ n=1 vs n=2 不足以下结论；并且 navigator 的 token 未被独立计入（见 ⑤ 备注），所以"D 是否真比 C 好"暂不可结论。下一步建议：**D 再跑 ≥2 次** + 排查为何 `usage_navigator_cycle_llm` 为 null。

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

## C — 无领航 · Qwen / Doubao 执行

| 日期 (UTC) | Task | Scenario | 持续领航 | 执行模型 | 墙钟 | 步数 | 摘要 |
|------------|------|----------|----------|----------|------|------|------|
| 2026-05-14 | `nearby_hospital_phone_lookup` | normal | 否 | `qwen3-max` | `08:03:41`→`08:14:15` Z（~10.5 min 墙钟；history 累加 ~83s） | 5（`usage` invocations 6） | 百度地图搜索列表直接产出 3 家：坂田医院 / 市人民医院坂田院区 / 远东妇产龙岗；电话与地址；来源为列表页检索 URL |
| 2026-05-26 09:46 | `nearby_hospital_phone_lookup` | normal | 否 | `doubao-seed-2-0-pro-260215` | `09:46:51`→`09:51:14` Z（~4.4 min 墙钟；history 累加 ~237s） | 8（`usage` invocations 10；118,755 tokens） | 豆包默认预设下的首条 C 成功；路径仍是百度地图列表 → `extract_structured_data` 一次拿全 3 条；**多出的 3 步是 `write_file todo.md` + `replace_file`（自我规划）+ `wait`**；source URL 实际抽取结果均为 `not visible`，Agent 在 `done.text` 用搜索页 URL 兜底（per-row source 严格不满足 success_criteria） |
| 2026-05-26 14:08 | `nearby_hospital_phone_lookup` | normal | 否 | `doubao-seed-2-0-pro-260215` | `14:08:09`→`14:10:50` Z（~2.7 min 墙钟；history 累加 ~161s） | 6（`usage` invocations 8；90,917 tokens） | 同命令复跑；**未写 todo**，路径压缩到 `navigate→input→click→wait→extract→done`；本次 `extract` 返回 **phone 全 not visible**（与 9:46 那条差异：搜索关键词改为"附近医院/诊所"夹入门诊部，更深层 phone 字段缺失）；进一步证明 Doubao 自我规划是**偶发非规律**；source URL 仍为搜索页兜底，仍 **PARTIAL** |

**Artifacts**：
- `tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260514T080341Z/`（Qwen 期）
- `tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260526T094651Z/`（Doubao 期 · 8 步）
- `tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260526T140809Z/`（Doubao 期 · 6 步复跑）

**备注**：
- 与 **D** 同任务对比，本趟**未开**持续领航；步数远少于 Qwen 期 D（17）主要因路径留在 **map.baidu.com** 且遵守 **Early-finish**，未再深挖高德 POI 页。执行器侧 **`navigator_current_step`** 仅在有领航注入时有值。
- **Doubao 期 C 两次跑次 6 vs 8 步**：差异来自"是否写 todo"；说明 Doubao 自我规划是**采样波动**而非稳定偏好——不能写成模型特性。引入 `productive_step_count = total_steps − todo_management_step_count` 做归一化更合理（Doubao 两次跑次 productive 都是 5~6 步，与 Qwen 期 5 步可比）。
- **Doubao 在百度地图 DOM-only 路径上未触发 JSON 漂移 / 畸形 URL**：客户端层对 `doubao-*` 关闭 `response_format.type=json_schema` 改用 prompt-stuffed schema（见 `browser_use/llm/openai/chat.py`），是 5/21 提交 `48d1660b` 引入的。
- **success 是 Agent 自报**：两条记录虽 `success=true`，但 source URL 实际为字段拼凑；且 9:46 那条 phone 真实而 14:08 那条 phone 全缺，**Agent 都未在 `final_result` 中标注这种字段质量差异** → 进一步说明需推动 `evidence_schema` 程序校验。

---

## D — DeepSeek 领航 · Qwen / Doubao 执行

| 日期 (UTC) | Task | Scenario | 持续领航 | 执行模型 | 领航模型 | 墙钟 | 步数 | 摘要 |
|------------|------|----------|----------|----------|----------|------|------|------|
| 2026-05-09 | `nearby_hospital_phone_lookup` | normal | 是 | `qwen3-max` | `deepseek-chat` | ~19 min (`06:42:59`→`07:02:11` Z) | 17 | 深圳市龙岗区坂田街道 3 家医院；名称 / 电话 / 地址 / 高德 POI 链接 |
| 2026-05-26 14:12 | `nearby_hospital_phone_lookup` | normal | **是** | `doubao-seed-2-0-pro-260215` | `deepseek-chat` | `14:12:21`→`14:14:20` Z（~2 min 墙钟；history 累加 ~119s） | **5**（`usage` invocations 6；75,651 tokens） | Doubao 期 D 首条成功；路径 `navigate→input→click→wait→done`，**完全跳过 `extract` 工具**——Doubao 直接从列表页 DOM 看见后在 `done` 里写出 3 家完整 phone+address（**号码与 2026-05-09 D 跑次一致：0755-89504000 / 0755-25566770 / 0755-23678999**）。**但 `usage_navigator_cycle_llm: null`、`by_model` 中无 deepseek**：DeepSeek 持续领航在本跑次未真正触发周期调用，或调用未走 TokenCost 通道 → 当前无法证明"D 优于 C 是因为 navigator"。 |

**Artifacts**：
- `tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260509T064248Z/`（Qwen 期 · 含 `navigator_plan.md`）
- `tmp/daily_task_eval/agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260526T141221Z/`（Doubao 期）

**备注**：
- **Doubao 期 D 没调 `extract` 工具就能写出真号码**：与 Qwen 期 D 完全不同的工具使用偏好——Doubao 倾向"看见即用"，Qwen 倾向"走工具→走 POI 详情"。是这次跑次 5 步 vs 历史 17 步差异的主要原因，**和 navigator 关系存疑**。
- **navigator 归因失踪问题**（关键）：本次 `usage_summary.by_model` 只看到 `doubao-seed-2-0-pro-260215`，没有 `deepseek-chat`；`usage_navigator_cycle_llm` 是 `null`。两种可能：
  1. DeepSeek 在本跑次根本没被调用（持续领航触发条件不满足，例如 5 步太短）；
  2. DeepSeek 被调用了但走的是独立 HTTP 客户端不经过 Agent 的 TokenCost。
  需要在下一次 D 跑次开 `--log-level debug` 验证，并核对 `browser_use/experiments/daily_task_eval/runner.py` 的 navigator 调用钩子。
- **Qwen 期 D（2026-05-09）的 17 步**：`yyk.99.com.cn` 导航失败未阻断；百度搜索词曾含 `'}}` 碎片；出现过畸形 `amap.com/...%7D%7D]%7D`。本跑在 **短子目标 / `<current_step_focus>`** 合入主线之前；B/D 若开 **`--continuous-navigation`**，执行者每步会多 **`navigator_current_step`** 顶栏（见 **`docs/issue-notes/navigator-current-step-executor-subgoal.md`**）。
- **success 是 Agent 自报**：Doubao 期 D 的 source URL 同样是搜索页兜底（per-row source 严格不满足 success_criteria），归类为 **PARTIAL**——但比两条 C 多了"真实电话"这一项关键事实。

---

## LLM 用量（与 `agent_runs.json` 对齐）

每台机器可读摘要记录在 **`agent_runs.json`** 对应条目中，关键字段：**`usage_summary`**（ totals + `by_model`）、**`usage_executor_llm`**（执行回路）、**`usage_navigator_cycle_llm`**（持续领航且不合并进执行者 id 时）、**`navigator_initial_plan_usage`**（开场计划单独一次）、**`usage_auxiliary_llm_models`**。控制台 **`cost`** 日志里 **`🧠`**=单次调用、**`🤖`**=按模型累计；语义说明见 **`DAILY_TASK_EXPERIMENT_GUIDE.md` §1.1**；领航 **短子目标** 见 **§1.2** 与 **`docs/issue-notes/navigator-current-step-executor-subgoal.md`**。若需在表中对比资源，可从上述 JSON 摘录 `prompt_tokens` / `completion_tokens` / `invocations`。
