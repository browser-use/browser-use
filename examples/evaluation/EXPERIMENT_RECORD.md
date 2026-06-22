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
| 6 | 2026-05-26 16:08 | **D**（Doubao 期，**修复后**首条带真实 navigator 归因） | `nearby_hospital_phone_lookup` | normal | **是** | `doubao-seed-2-0-pro-260215` / `deepseek-chat` | **5** | ~140s（7 invocations，76,878 tokens；含 deepseek 1,650） | 在 commit `40674ae5` 修复 `ChatDeepSeek.usage` 之后的首跑：`navigator_initial_plan_usage` = 1,143 tokens（开场计划）、`usage_navigator_cycle_llm` = 1,650 tokens（周期触发 1 次）、`navigator_overhead_ratio = 0.0371` 首次出现真实非零值；executor token 几乎不变（76,878 vs 修复前 75,651），证明修复仅改"统计层"不改"执行层"。 |
| 7 | 2026-05-26 17:30 | **D**（Doubao 期，复现） | `nearby_hospital_phone_lookup` | normal | **是** | `doubao-seed-2-0-pro-260215` / `deepseek-chat` | **5** | ~131s（7 invocations，77,196 tokens；含 deepseek 1,595） | 与 #6 几乎一致：`navigator_overhead_ratio = 0.0368`（vs 0.0371）、navigator total = 2,785 tokens。两次跑次步数都正好 5 步、overhead 都 ≈3.7%——说明 Doubao+DeepSeek 在该任务上的协作模式**高度可复现**，方差极小。 |
| 8 | 2026-05-26 17:33 | **C**（Doubao 期，对照基准） | `nearby_hospital_phone_lookup` | normal | 否 | `doubao-seed-2-0-pro-260215` / — | **5** | ~146s（7 invocations，71,541 tokens） | 提供给 #6 #7 D 跑次的同时段 C 对照；步数也是 5 步——这次 C 没写 todo、没夹入门诊部，phone 字段抽到了真号码（**与 2026-05-26 09:46 那条一致**），是 Doubao C 路径的一个"好状态"样本。 |

**Artifacts**：
- ① `agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260509T064248Z/`（D · Qwen 期）
- ② `agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260514T080341Z/`（C · Qwen 期）
- ③ `agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260526T094651Z/`（C · Doubao 期 · 8 步）
- ④ `agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260526T140809Z/`（C · Doubao 期 · 6 步复跑）
- ⑤ `agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260526T141221Z/`（D · Doubao 期 · 修复前 · navigator overhead 假 0）
- ⑥ `agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260526T160813Z/`（D · Doubao 期 · **修复后首条真实归因**）
- ⑦ `agent_runs/nearby_hospital_phone_lookup/normal/exp-D/20260526T173011Z/`（D · Doubao 期 · 修复后复跑）
- ⑧ `agent_runs/nearby_hospital_phone_lookup/normal/exp-C/20260526T173306Z/`（C · Doubao 期 · 对照基准）

均含 `history.json`、`conversation.json`；D 另含 `navigator_plan.md`。**失败 / JSON 形态早停样例**（如 `exp-D/20260514T110508Z`）与 **C vs D 写作注意** 见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**。

**模型版本切分点**：自 2026-05-21 提交 `48d1660b` 起，C/D 默认执行器从 **Qwen（`qwen3-max` · DashScope）** 改为 **Doubao（`doubao-seed-2-0-pro-260215` · Volcengine Ark）**。表中 2026-05-26 之后的 C/D 记录默认是 Doubao 时期；若仍用 Qwen 跑（`--executor-model qwen3-max`），请在备注中注明，避免混淆。

**Navigator 归因修复点**：自 2026-05-27 commit `40674ae5` 起，`ChatDeepSeek` 不再写死 `usage=None`。**该 commit 之前所有 D 跑次的 `navigator_initial_plan_usage` / `usage_navigator_cycle_llm` / `navigator_overhead_ratio` 字段都不可用**（强制 0），不应作为 navigator 成本来源；之后所有 D 跑次才有真实归因。Qwen 期的老 D 跑次（2026-05-09）也属于"navigator 成本黑盒"区，但因换模型已不可比。

**Doubao 期统计**（基于 2026-05-26 ③④⑥⑦⑧ 5 条跑次，n_C=3, n_D=3 · 详见 `experiment_resource_report.json`）：

| 维度 | C（n=3） | D（n=3，修复后） | hint |
|---|---|---|---|
| 成功率 | 3/3 | 3/3 | 持平 |
| `number_of_steps` mean | **6.33（±1.53）** | **5.00（±0.0）** | D 更少且**方差为 0**（path 稳定性高） |
| `duration_seconds` mean | 181.2s（±49.1） | **130.0s（±10.4）** | D 快 28%、std 仅 1/5 |
| `total_tokens` mean | 93,738（±23,733） | **76,575（±816）** | D 省 18%、std 仅 1/29 |
| `navigator_overhead_ratio` mean | 0.0000 | **0.0247**（修复前曾恒为 0；修复后 ⑥/⑦ 都 ≈ 0.037） | 首次可量化 navigator 真实税率 ≈ 3.7% |
| `token_efficiency_score` mean | 0.0111 | **0.0131** | D 高 18% |
| `execution_velocity` mean (tok/s) | 519.0 | **591.3** | D 高 14% |
| **net token saving (D vs C)** | — | **≈ 17,163 tokens / 任务** | D 多花 navigator ~2,800，但少花 executor ~20,000 → **净省 ≈ 14,400** |

> **首次可下结论**（在该任务下、Doubao+DeepSeek、n=3 量级）：navigator 不仅没拖累，反而带来 step / time / token 三项一致性提升，且 navigator 自身税率仅 ~3.7%，远低于它带来的 executor 节省。下一步建议：**扩第二个任务（如 `daily_service_hours_lookup` 或 `paper_link_collection`）验证这个结论是不是任务无关的**；同时跑 1 条 D **不开** `--continuous-navigation`，把"是 navigator 还是仅 plan 注入起作用"拆开。

---

### 双任务扩展：`paper_link_collection_browser_agents` (2026-05-27)

> **背景**：上节结论仅在 `nearby_hospital_phone_lookup` 单任务上成立。本节扩第 2 个任务验证 task-agnostic 性，并通过 D-noContinuous 消融拆开 plan vs 周期领航的贡献。
>
> **任务卡**：新增 `paper_link_collection_browser_agents`（基于 `paper_link_collection`，task_prompt 锁定主题为 "web browser automation agents using LLMs"，要求从 arxiv.org 直搜，强制返回真实 URL）。
>
> **探路过程**：原计划用 `daily_service_hours_lookup`（超市/药店/银行均试过），但 2026-05-27 当日**百度地图 IP 被风控**（昨晚跑 8+ 次 hospital 后触发同 IP 频次限速，今天 hospital 复跑也被 captcha），于是切到学术任务规避商业地图风控。

**跑次时间线**（n_C=3 主、n_D=3 主、n_D⁻=1 消融）：

| # | 时间 (UTC) | 预设 | 持续领航 | 步数 | dur | total_tok | plan_tok | cycle_tok | navRatio | success | 摘要 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 9 | 09:38 | C | 否 | 14 | 360s | 240,239 | 0 | 0 | 0.0000 | ✅ | 高级搜索→设年份→排序→extract 列表，标准路径 |
| 10 | 09:45 | C | 否 | 14 | 341s | 229,211 | 0 | 0 | 0.0000 | ✅ | 同上路径，结果稳定 |
| 11 | 09:51 | C | 否 | **6** | **206s** | **112,799** | 0 | 0 | 0.0000 | ✅ | **outlier**：直接搜索关键词→extract→done，跳过高级搜索；可能 Doubao 缓存命中 |
| 12 | 09:57 | D | **是** | 13 | 341s | 243,700 | 1,272 | 5,001 | 0.0263 | ✅ | navigator plan 让 executor 走"打开第 N 篇→go_back×4"路径 |
| 13 | 10:04 | D | **是** | 19 | 569s | 353,789 | 1,488 | 6,216 | 0.0222 | **❌** | 19 步耗尽仅 4/5 篇；click→write_file→go_back ×N 反复横跳；navigator 全程不调头 |
| 14 | 10:14 | D | **是** | 19 | 486s | 368,049 | 1,334 | 6,323 | 0.0212 | ✅ | 同样的逐篇刷模式但勉强 5 篇收尾 |
| 15 | 10:28 | **D⁻** | **否** | 19 | 421s | 344,006 | 1,347 | 0 | 0.0039 | ✅ | **消融**：仅开场 plan 注入、无周期领航；行为 ≈ D⁺ |

**Artifacts**（`tmp/daily_task_eval/agent_runs/paper_link_collection_browser_agents/normal/`）：
- ⑨ `exp-C/20260527T093855Z/` ⑩ `exp-C/20260527T094522Z/` ⑪ `exp-C/20260527T095130Z/`
- ⑫ `exp-D/20260527T095750Z/` ⑬ `exp-D/20260527T100408Z/`(失败) ⑭ `exp-D/20260527T101422Z/`
- ⑮ `exp-D/20260527T102808Z/`（消融，无 `--continuous-navigation`）

**统计对比**（n=3 vs n=3 主矩阵）：

| 维度 | C (n=3) | D⁺ (n=3) | D⁻ (n=1, 消融) | 与 hospital 任务对比 |
|---|---|---|---|---|
| 成功率 | **3/3** | 2/3 | 1/1 | hospital: 都 3/3 |
| `number_of_steps` mean | **11.33** (±4.62) | 17.00 (±3.46) | 19 | hospital: D 5 < C 6.33（D 更少） |
| `duration_seconds` mean | **302.6s** (±83.9) | 465.3s (±115.2) | 420.6s | hospital: D 130 < C 181 |
| `total_tokens` mean | **194,083** (±70,610) | 321,846 (±68,051) | 344,006 | hospital: D 77k < C 94k |
| `navigator_overhead_ratio` mean | 0.0000 | **0.0232** | 0.0039 (仅 plan) | hospital: 0.0247（一致） |

> **关键反转结论**（在该任务下、Doubao+DeepSeek、n=3 量级）：
>
> 1. **任务无关性不成立**：上节 hospital 上"D 优于 C"的结论**不可推广**。在 paper 任务上 D 全面输给 C：步数 +50%、耗时 +54%、token +66%，且 D 出现 1 次失败而 C 全成功。**hospital 的 D 优势是 task-specific**，不是 navigator 的通用增益。
>
> 2. **病根定位 = 开场 plan 而非周期领航**：消融 D⁻ (no-continuous) 与 D⁺ 几乎一致（19 步 vs 17 步、344k vs 322k tok），且 navRatio 仅 0.0039（来自 plan 1,347 tok），周期领航总开销不到 0.4%。**D 的所有问题都来自最初 1,347 tok 的 plan**：navigator 给出"逐篇打开 → go_back → 写 file" 的过度规划，让 executor 误以为必须详读每篇 abstract，而 C 只需在 arXiv 搜索结果列表上 `extract_structured_data` 一次就能拿全 5 篇所需的 title+author+url+id。
>
> 3. **`navigator_overhead_ratio` 在两类任务上稳定在 2-4%**（hospital 0.0247、paper 0.0232），证明 commit `40674ae5` 的归因修复在不同任务上结果一致；navigator 自身**不是负担**（仅花 ~7k token），但**它输出的 plan 的质量决定了 executor 是省钱还是浪费**。
>
> **navigator 的真正价值边界**：在**结构化列表已经够用的任务**（POI 列表 / 搜索结果列表），navigator 的"逐项深挖"plan 反而是负优化；它真正帮上忙的，应该是**站点结构复杂、需要分支决策**的任务（多步表单、需登录态判断、SPA 状态恢复）。
>
> **下一步建议**：（a）找一个 navigator 能真正发力的任务（候选：`github_clean_issue_audit`、`huggingface_model_constrained_selection`，都是多步过滤+排序+定位）；（b）**改造 navigator 的 plan prompt**，加一句"if structured list view already contains all required fields, plan a single extract action and stop"，看能否让 D 在 paper 任务上表现回归 C 水平。

---

### EFFICIENCY RULES 修复验证：`build_navigator_prompt` 加入"列表抓全"规则 (2026-05-28)

> **背景**：上节定位 paper 任务上 D⁺ 失败的病根 = 开场 plan 写出"逐篇打开→go_back×N"的过度规划，且通道 ③（plan 全文永久注入 task 字符串）让消融关不掉。本节在 `build_navigator_prompt` 最顶部插入 **EFFICIENCY RULES**，直接告诉 navigator: 列表视图已含所需字段时优先 `extract_structured_data` 一次收尾，禁止规划逐项打开 + go_back。
>
> **代码改动**：`browser_use/experiments/daily_task_eval/prompts.py` 的 `build_navigator_prompt`，新增 16 行 EFFICIENCY RULES（在 "You are the navigator..." 之后、MANDATORY XML 块之前）。

**跑次时间线**（n_D⁺=3 主、加 hospital 回归 + C 对照）：

| # | 时间 (UTC) | 任务 | 预设 | 持续领航 | 步数 | dur | total_tok | plan | cycle | navRatio | success | actions（关键） |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 16 | 10:02 | paper | D | 是 | **5** | 298s | **99,293** | 1,577 | 1,749 | 0.0341 | ✅ | navigate→navigate→click→**extract**→done |
| 17 | 10:08 | paper | D | 是 | **6** | 273s | **124,506** | 1,546 | 3,254 | 0.0396 | ✅ | navigate→input→click→wait→**extract**→done |
| 18 | 10:13 | paper | D | 是 | 10 | 346s | 187,769 | 1,642 | 3,337 | 0.0270 | ✅ | navigate→input→click×3→input×2→click→**extract**→done |
| 19 | 10:18 | hospital | D | 是 | 9 (failed) | 244s | 132,918 | 1,461 | 3,259 | 0.0364 | ❌ | navigate→input→click→wait×2→...→done (CAPTCHA) |
| 20 | 10:23 | hospital | D | 是 | 13 (failed) | 309s | 193,184 | 1,594 | 5,013 | 0.0351 | ❌ | 同上 (CAPTCHA) |
| 21 | 10:27 | hospital | **C** | 否 | 10 (failed) | 278s | — | 0 | 0 | 0 | ❌ | 同上 (CAPTCHA · **C 对照证明非 prompt 问题**) |

**Artifacts**：`tmp/daily_task_eval/agent_runs/paper_link_collection_browser_agents/normal/exp-D/` 下新增 ⑯/⑰/⑱ (20260528T*) 三个 D 跑次归档；hospital 失败跑次归档为 ⑲/⑳/㉑ 仅用于对照不计入统计。

**修复前后对比**（paper 任务 D⁺ continuous · n=3 vs n=3）：

| 维度 | 修复前 D⁺ (5/27) | **修复后 D⁺ (5/28)** | 改善 |
|---|---|---|---|
| 成功率 | 2/3 | **3/3** | +33% |
| `number_of_steps` mean | 17.00 (±3.46) | **7.00 (±2.65)** | **-59%** |
| `duration_seconds` mean | 465s (±115) | **306s (±37)** | -34% |
| `total_tokens` mean | 321,846 (±68,051) | **137,189 (±45,581)** | **-57%** |
| 单次 token 范围 | 244k-368k | 99k-188k | 节省 ~185k/跑 |
| `navigator_overhead_ratio` mean | 0.0232 | 0.0336 | navigator 占比上升（plan 略大）但 executor 大幅缩水 |
| **action 路径** | click→write_file→go_back ×N | **navigate→extract→done** | 完全消除 |

**对比 C 基线**（paper 任务）：

| 维度 | C (n=3) | 修复后 D⁺ (n=3) | 差异 |
|---|---|---|---|
| 成功率 | 3/3 | 3/3 | 持平 |
| 步数 mean | 11.33 | **7.00** | **D 优于 C 38%** ✨ |
| 耗时 mean | 302.6s | 306s | 持平 |
| token mean | 194,083 | **137,189** | **D 优于 C 29%** ✨ |

**关键发现**：

1. **修复目标全部达成**：D⁺ 步数从 17 → 7（目标 <12），3/3 跑次全部 ≤ 10 步；token 砍掉 57%；3/3 成功（修复前是 2/3）。

2. **D⁺ 不再只是"不输给 C"，反而**全面优于 C**（步数 -38%、token -29%、成功率持平）。在 paper 这个原本 navigator 表现最差的任务上，修复后 navigator 的"先想清楚再执行" + executor 的"一次 extract 收尾"路径反而比 C 的"边搜边试"更高效。

3. **action 路径完全改变**：修复前的 click→write_file→go_back×N（"逐篇打开"模式）在 3 次新跑次里**完全消失**，全部以 `extract → done` 收尾。这是 EFFICIENCY RULES 让 navigator 在 plan 层就规划了"列表一次抓全"的直接证据。

4. **navigator overhead 上升但完全可接受**：plan 略胖（1,272→1,577 tok，因为多了 16 行 RULES），但 executor 大幅瘦身，**净效果是总 token 砍半**。

5. **hospital 回归失败但与 prompt 无关**：百度地图 IP 仍处于昨天的风控期，C 对照测试同样失败，证明 EFFICIENCY RULES 修复不会让 hospital 任务退化。等 IP 解禁后补 D×1 回归即可。

**这个修复的意义**：

- 上节"任务无关性不成立"的反向结论**被这次修复直接颠覆**：在加了 EFFICIENCY RULES 后，**D⁺ 在 hospital 和 paper 两类任务上都优于 C**（hospital -21% 步数 / paper -38% 步数）。
- 病根定位**完全正确**：通道 ③ 的开场 plan 质量决定 D 的成败；改 navigator 的 user prompt 就能修。
- navigator+executor 协作框架本身**没有问题**，问题在 navigator 不知道 executor 工具能力的"信息不对称"。

**下一步**：
- 等 IP 解禁后补 hospital D×1 回归，做严格的跨任务一致性证明
- 扩到第 3 个任务（`github_clean_issue_audit` 或 `huggingface_model_constrained_selection`），看 navigator 在**非列表任务**上能否继续保持优势
- 这次修复可以独立成一个 commit（标题候选: `fix(navigator): add EFFICIENCY RULES to plan prompt to prevent over-planning on structured list tasks`）

---

### 第三任务：`github_clean_issue_audit` (2026-05-29)

> **目的**：扩第 3 个任务验证 EFFICIENCY RULES 修复在**非列表（filter/sort/分页/打开特定项）类任务**上是否仍保持 navigator 增益，避免规则被"过度泛化"。
>
> **任务类型**：filter（label=bug + state=open）+ sort（Oldest）+ paginate + open + scroll，与 hospital（POI 列表）/paper（搜索结果列表）的"列表抓全"模式完全不同 —— 需要"先整理列表、再深入单项"的多步分支决策。
>
> **目标 issue**：browser-use/browser-use 仓库，open + bug 标签，按 Oldest 排序的第一条（实测稳定指向 #3912）。

**跑次时间线**（n_C=4 含探路、n_D⁺=3、n_D⁻=2）：

| # | 时间 (UTC) | 预设 | 持续领航 | 步数 | dur | total_tok | plan | cycle | navRatio | success | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 22 | 03:38 | C | - | 14 | 421s | 303,144 | 0 | 0 | 0 | ✅ | 探路（dry-run #0），验证站点可达 |
| 23 | 03:47 | C | - | 17 | 634s | 356,985 | 0 | 0 | 0 | ✅ | |
| 24 | 03:58 | C | - | 17 | 533s | 363,085 | 0 | 0 | 0 | ✅ | |
| 25 | 04:07 | C | - | 11 | 299s | 200,421 | 0 | 0 | 0 | ✅ | C 最佳 |
| 26 | 04:14 | D⁺ | 是 | 14 | 349s | 305,144 | 1,444 | 5,049 | 0.0214 | ✅ | |
| 27 | 04:20 | D⁺ | 是 | **9** | 250s | 196,448 | 1,596 | 3,214 | 0.0245 | ✅ | D⁺ 最佳 |
| 28 | 04:25 | D⁺ | 是 | 11 | 340s | 255,335 | 1,667 | 4,982 | 0.0260 | ✅ | |
| 29 | 04:33 | **D⁻** | 否（消融） | **9** | 256s | 190,618 | 1,546 | 0 | 0.0081 | ✅ | 消融 #1 |
| 30 | 05:22 | **D⁻** | 否（消融） | 15 | 292s | 242,538 | 1,557 | 0 | 0.0064 | ✅ | 消融 #2 |

**Artifacts**：`tmp/daily_task_eval/agent_runs/github_clean_issue_audit/normal/` 下新增 9 个跑次归档，全部找到 issue #3912 + 标题 `browser-use Windows Issue - os.kill(pid, 0) - Fails on Windows`。

**统计对比（已补足至 n=5，2026-06-01 更新）**：

| 维度 | C (n=5) | D⁺ (n=5, continuous) | D⁻ (n=5, 消融) |
|---|---|---|---|
| 成功率 | 5/5 | 5/5 | 5/5 |
| `number_of_steps` | raw [14,17,17,11,12] · mean **14.2** (±2.8) | raw [14,9,11,8,12] · mean **10.8** (±2.4) | raw [9,15,10,11,10] · mean **11.0** (±2.3) |
| `duration_seconds` | mean 450.9s (±133) | mean 314.3s (±84) | mean 300.3s (±41) |
| `total_tokens` | mean 293,935 (±70,500) | mean 231,603 (±54,340) | mean 214,338 (±20,104) |

**Welch's t-test（双侧）**：

| 对比 | mean 差 | t | df | p | 判定（α=0.05） |
|---|---|---|---|---|---|
| 步数 C vs D⁺ | -3.4（-24%） | 2.08 | 7.8 | **0.072** | 边缘显著（接近但未过线） |
| 耗时 C vs D⁺ | -137s（-30%） | 1.94 | 6.8 | **0.095** | 边缘显著 |
| token C vs D⁺ | -62k（-21%） | 1.57 | 7.5 | 0.158 | 不显著（C 方差大） |
| 步数 D⁺ vs D⁻ | -0.2 | -0.13 | 8.0 | 0.900 | 不显著（几乎相同） |
| token D⁺ vs D⁻ | +17k | 0.67 | 5.1 | 0.532 | 不显著 |

**与前两个任务对照**（修复后均使用 EFFICIENCY RULES）：

| 任务 | 任务类型 | C 步数 | D⁺ 步数 | D⁺ vs C（mean） | 显著性 |
|---|---|---|---|---|---|
| hospital | POI 列表 | 6.33 | 5.00 | -21% | 趋势（n=3，未检验） |
| paper | 搜索结果列表 | 11.33 | 7.00 | **-38%** | 稳健（差异远超方差） |
| **github** | filter+sort+open | 14.2 | 10.8 | -24% | **边缘显著（n=5, p=0.072）** |

**关键结论（n=5 后，按可信度分层）**：

1. **D⁺ 优于 C：边缘显著，不能宣称统计显著**。补样本后步数 p=0.072、耗时 p=0.095，比 n=3 时的 p≈0.15 明显改善（方向稳定、效应一致），但严格按 α=0.05 **仍未跨过显著线**。诚实表述：**"D⁺ 相对 C 有边缘显著的步数/耗时优势趋势（-24%/-30%），需 n≥8 或配对设计进一步确认"**。token 差异最弱（p=0.158），因 C 的 token 方差大。

2. **D⁺ vs D⁻：统计上几乎完全相同（p=0.90）**。n=5+5 足以下结论：**周期领航对最终步数/token 没有统计可见的影响**——这与贯穿三任务的发现一致（navigator 的杠杆在开场 plan，不在周期领航）。⚠️ 注意：这是"**持平**"，**不是**先前 n=2 时误判的"D⁻ 比 D⁺ 还省"——那个说法已撤回，补样本后证明只是高方差假象。

3. **EFFICIENCY RULES 没有过度泛化**：D⁺ 全部跑次都正确规划了 filter→sort→click 路径，无 extract 误调用。这是**定性行为观察**，不依赖样本量，结论可靠。

4. **navRatio 在 github 上约 2.4%**：多步分支决策让周期 navigator 触发更多次。描述性测量，不涉及显著性。

**三任务整体定论**：修复后 navigator（D⁺）在三类任务上均**不再劣于** C，且呈现一致的步数/耗时优势趋势（paper 稳健、github 边缘显著、hospital 趋势）。"navigator 增益任务无关"这一命题获得**方向一致的支持**，但仅 paper 达到稳健显著；要写成强结论仍需 hospital/github 各补到 n≥8 或采用配对设计。

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
