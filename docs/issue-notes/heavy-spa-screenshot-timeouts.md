# 问题记录：重型网页（如在线地图）与截图超时

## 现象

在自动化任务中打开 **重型单页应用（SPA）**，尤其是 **在线地图**（例如 `map.baidu.com`、`amap.com` 等）时，常出现：

- 浏览器 **导航本身较快**，页面可见已加载；
- Agent **前几步反复失败**或长时间无进展；
- 日志中出现 **`ScreenshotWatchdog` / `Page.captureScreenshot` 超时**（例如约 15s）；
- 伴随 **`BrowserStateRequest` / DOM 状态收集变慢**，整步被 **`step_timeout`** 吃满。

根因侧写：地图类站点大量使用 **Canvas / WebGL / 瓦片与动效**，通过 CDP 做整页截图成本高、易阻塞，从而拖住「取浏览器状态」整条链路，而不是单纯「网速慢」。

## 建议对策

在做需要打开 **地图或同类重型控制台/大屏类页面** 的任务时，可 **优先考虑关闭或减弱截图依赖**，例如：

- **`Agent(use_vision=False)`**：不向 LLM 附截图，且不注册 `screenshot` 工具；自本仓库相关改动起，获取浏览器状态时 **也不再跑 CDP 干净截图**，可显著减轻 `map.baidu.com` 一类页面的 `ScreenshotWatchdog` 超时。
- **`Agent(..., use_vision='auto')`**：平时 **不截状态图**；仅当上一步执行了 **`screenshot` 工具**（其 `metadata` 会请求下一步观察带图）时，下一步才会走 CDP 截图。适合「大部分时间 DOM、偶尔要一眼」的流程。
- **`Agent(use_vision=True)`**：每步都会对浏览器状态做一次截图（多模态 + 更重页面负载）。
- 结合任务设计：**优先使用 DOM/文本友好的入口**（列表页、搜索聚合页、政府/医院公开目录等），避免在纯地图画布上长时间循环；
- 评估 **分标签 / 多标签** 与地图同开时的焦点与状态成本，必要时减少不必要的 `new_tab` 或尽快切回可读性更好的页面。

具体 API 参数以当前 `Browser` / `Agent` 文档与版本为准；本文件仅作 **问题与经验记录**，避免团队在同类站点上重复踩坑。

## 关联上下文

- 日常任务实验说明中已有「地图类站点截图昂贵、易触发截图看门狗超时」的提示，可与本记录对照。
- 关闭截图不等于关闭 Agent：**领航（规划与工具调用）仍依赖 DOM/文本状态与其它工具**；在 Canvas 主导的页面上，单靠 DOM 可能信息不足，需与「换入口」策略一并考虑。
- **领航短子目标**（`<current_step_focus>` / `<navigator_current_step>`）与「步数/迷路」另一类问题，见 **`docs/issue-notes/navigator-current-step-executor-subgoal.md`**。
- **Qwen 结构化输出 / C vs D prompt 负载 / 论文表述注意**：见 **`docs/issue-notes/openai-compatible-executor-json-output-and-c-vs-d-prompt-load.md`**。

## 记录日期

2026-05-09（正文）；关联短子目标记录链接：2026-05-14。
