<!--
IMPORTANT: This file is a localized version of README.md. 
When updating README.md, please ensure that the corresponding changes are also applied to this file to maintain parity.
-->

<picture>
  <source media="(prefers-color-scheme: light)" srcset="https://github.com/user-attachments/assets/2ccdb752-22fb-41c7-8948-857fc1ad7e24">
  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/774a46d5-27a0-490c-b7d0-e65fcbbfa358">
  <img alt="Shows a black Browser Use Logo in light color mode and a white one in dark color mode." src="https://github.com/user-attachments/assets/2ccdb752-22fb-41c7-8948-857fc1ad7e24"  width="full">
</picture>

<div align="center">
    <picture>
    <source media="(prefers-color-scheme: light)" srcset="https://github.com/user-attachments/assets/9955dda9-ede3-4971-8ee0-91cbc3850125">
    <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/6797d09b-8ac3-4cb9-ba07-b289e080765a">
    <img alt="The AI browser agent." src="https://github.com/user-attachments/assets/9955dda9-ede3-4971-8ee0-91cbc3850125"  width="400">
    </picture>
</div>

<div align="center">
<a href="https://cloud.browser-use.com"><img src="https://media.browser-use.tools/badges/package" height="48" alt="Browser-Use Package Download Statistics"></a>
</div>

---

<div align="center">
<a href="#演示-demos"><img src="https://media.browser-use.tools/badges/demos" alt="Demos"></a>
<img width="16" height="1" alt="">
<a href="https://docs.browser-use.com"><img src="https://media.browser-use.tools/badges/docs" alt="Docs"></a>
<img width="16" height="1" alt="">
<a href="https://browser-use.com/posts"><img src="https://media.browser-use.tools/badges/blog" alt="Blog"></a>
<img width="16" height="1" alt="">
<a href="https://browsermerch.com"><img src="https://media.browser-use.tools/badges/merch" alt="Merch"></a>
<img width="100" height="1" alt="">
<a href="https://github.com/browser-use/browser-use"><img src="https://media.browser-use.tools/badges/github" alt="Github Stars"></a>
<img width="4" height="1" alt="">
<a href="https://x.com/intent/user?screen_name=browser_use"><img src="https://media.browser-use.tools/badges/twitter" alt="Twitter"></a>
<img width="4" height="1" alt="">
<a href="https://link.browser-use.com/discord"><img src="https://media.browser-use.tools/badges/discord" alt="Discord"></a>
<img width="4" height="1" alt="">
<a href="https://cloud.browser-use.com"><img src="https://media.browser-use.tools/badges/cloud" height="48" alt="Browser-Use Cloud"></a>
</div>

<br/>

<p align="center">
  <a href="README.md">English</a> ·
  <strong>中文</strong>
</p>

🌤️ 想跳过环境配置？使用我们的 <b>[云服务](https://cloud.browser-use.com)</b>，获得更快、可扩展且具备隐身防检测能力的浏览器自动化体验！

# 🤖 LLM 快速开始

1. 将您最喜欢的编程 Agent（Cursor, Claude Code 等）指向 [Agents.md](https://docs.browser-use.com/llms-full.txt)
2. 直接开始写 Prompt 吧！

<br/>

# 👋 人类快速开始

**1. 创建环境并使用 [uv](https://docs.astral.sh/uv/) 安装 Browser-Use (Python>=3.11):**
```bash
uv init && uv add browser-use && uv sync
# uvx browser-use install  # 如果您没有安装 Chromium，请运行此命令
```

**2. 从 [Browser Use Cloud](https://cloud.browser-use.com/new-api-key) 获取您的 API Key:**
```
# .env
BROWSER_USE_API_KEY=your-key
# GOOGLE_API_KEY=your-key
# ANTHROPIC_API_KEY=your-key
```

**3. 运行您的第一个 Agent:**
```python
from browser_use import Agent, Browser, ChatBrowserUse
# from browser_use import ChatGoogle  # ChatGoogle(model='gemini-3-flash-preview')
# from browser_use import ChatAnthropic  # ChatAnthropic(model='claude-sonnet-4-6')
import asyncio

async def main():
    browser = Browser(
        # use_cloud=True,  # 在 Browser Use Cloud 上使用隐身浏览器
    )

    agent = Agent(
        task="Find the number of stars of the browser-use repo",
        llm=ChatBrowserUse(),
        # llm=ChatGoogle(model='gemini-3-flash-preview'),
        # llm=ChatAnthropic(model='claude-sonnet-4-6'),
        browser=browser,
    )
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
```

查看 [代码库文档](https://docs.browser-use.com/open-source/introduction) 和 [云服务文档](https://docs.cloud.browser-use.com) 获取更多信息！

<br/>

# 演示 (Demos)

### 📋 填写表单 (Form-Filling)
#### 任务 = "Fill in this job application with my resume and information." (用我的简历和信息填写这份求职申请)
![Job Application Demo](https://github.com/user-attachments/assets/57865ee6-6004-49d5-b2c2-6dff39ec2ba9)
[代码示例 ↗](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/apply_to_job.py)

### 🍎 购买杂货 (Grocery-Shopping)
#### 任务 = "Put this list of items into my instacart." (把这些商品加到我的 instacart 购物车)

https://github.com/user-attachments/assets/a6813fa7-4a7c-40a6-b4aa-382bf88b1850

[代码示例 ↗](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/buy_groceries.py)

### 💻 个人助理 (Personal-Assistant)
#### 任务 = "Help me find parts for a custom PC." (帮我找组装定制电脑的配件)

https://github.com/user-attachments/assets/ac34f75c-057a-43ef-ad06-5b2c9d42bf06

[代码示例 ↗](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/pcpartpicker.py)

### 💡在此查看 [更多示例 ↗](https://docs.browser-use.com/examples) 并且给我们点个 Star 吧！

<br/>

# 🚀 模板快速开始

**想更快上手？** 生成一个开箱即用的模板：

```bash
uvx browser-use init --template default
```

这将创建一个包含可用示例的 `browser_use_default.py` 文件。可选的模板有：
- `default` - 快速入门的最小化设置
- `advanced` - 包含所有配置选项及详细注释
- `tools` - 自定义工具和扩展 Agent 能力的示例

您也可以指定自定义的输出路径：
```bash
uvx browser-use init --template default --output my_agent.py
```

<br/>

# 💻 CLI (命令行工具)

通过命令行实现快速、持久的浏览器自动化：

```bash
browser-use open https://example.com    # 导航到指定的 URL
browser-use state                       # 查看可点击的元素
browser-use click 5                     # 通过索引点击元素
browser-use type "Hello"                # 输入文本
browser-use screenshot page.png         # 截取屏幕截图
browser-use close                       # 关闭浏览器
```

CLI 会在命令之间保持浏览器处于运行状态，以便快速迭代开发。有关所有命令的说明，请参阅 [CLI 文档](browser_use/skill_cli/README.md)。

### Claude Code 技能 (Skill)

对于 [Claude Code](https://claude.ai/code) 用户，安装此技能以启用 AI 辅助的浏览器自动化：

```bash
mkdir -p ~/.claude/skills/browser-use
curl -o ~/.claude/skills/browser-use/SKILL.md \
  https://raw.githubusercontent.com/browser-use/browser-use/main/skills/browser-use/SKILL.md
```

<br/>

## 集成、托管、自定义工具、MCP 等更多内容，请访问我们的 [文档 ↗](https://docs.browser-use.com)

<br/>

# 常见问题 (FAQ)

<details>
<summary><b>使用什么模型最好？</b></summary>

我们针对浏览器自动化任务专门优化了 **ChatBrowserUse()** 模型。它的任务完成速度平均比其他模型快 3-5 倍，并具有 SOTA（业内领先）的准确率。

**定价 (每 1M tokens):**
- 输入 tokens: $0.20
- 缓存输入 tokens: $0.02
- 输出 tokens: $2.00

对于其他 LLM 提供商，请参阅我们的 [支持的模型文档](https://docs.browser-use.com/supported-models)。
</details>

<details>
<summary><b>如果使用开源的预览版模型，我还需要使用 Browser Use 的系统提示词吗？</b></summary>

是的。如果您在常规的 `Agent(...)` 中使用了 `ChatBrowserUse(model='browser-use/bu-30b-a3b-preview')`，Browser Use 依然会为您发送默认的 Agent 系统提示词。

您**不需要**仅仅因为切换到了开源预览版模型，就去添加一个单独的自定义 "Browser Use 系统消息"。只有在您明确想要为特定任务自定义默认行为时，才使用 `extend_system_message` 或 `override_system_message`。

如果您想要获得最佳的默认速度和准确率，我们仍然推荐使用较新的托管版本 `bu-*` 模型。如果您想使用开源预览版模型，除了 `model=` 的值之外，设置保持不变。
</details>

<details>
<summary><b>我可以为 Agent 添加自定义工具吗？</b></summary>

可以！您可以添加自定义工具来扩展 Agent 的能力：

```python
from browser_use import Tools

tools = Tools()

@tools.action(description='这里写明该工具的功能描述。')
def custom_tool(param: str) -> str:
    return f"结果: {param}"

agent = Agent(
    task="您的任务",
    llm=llm,
    browser=browser,
    tools=tools,
)
```

</details>

<details>
<summary><b>这个项目是免费的吗？</b></summary>

是的！Browser-Use 是开源且免费使用的。您只需要选择一个 LLM 提供商（比如 OpenAI, Google, ChatBrowserUse，或是使用 Ollama 运行本地模型）。
</details>

<details>
<summary><b>服务条款 (Terms of Service)</b></summary>

这个开源代码库采用 MIT 许可证。有关 Browser Use 服务及数据政策的信息，请参阅我们的 [服务条款](https://browser-use.com/legal/terms-of-service) 和 [隐私政策](https://browser-use.com/privacy/)。
</details>

<details>
<summary><b>如何处理身份验证 (Authentication)？</b></summary>

查看我们的身份验证示例：
- [使用真实的浏览器配置文件](https://github.com/browser-use/browser-use/blob/main/examples/browser/real_browser.py) - 重用您现有的 Chrome 配置文件和保存的登录信息
- 如果您想使用带收件箱的临时账户，请选择 AgentMail
- 要将您的身份验证配置文件同步到远程浏览器，请按照 [官方文档](https://docs.browser-use.com/) 中推荐的安全步骤配置您的 `BROWSER_USE_API_KEY`。

这些示例展示了如何无缝地保持会话状态和处理身份验证。
</details>

<details>
<summary><b>如何解决验证码 (CAPTCHAs) 问题？</b></summary>

为了处理 CAPTCHA，您需要更好的浏览器指纹和代理服务器。请使用 [Browser Use Cloud](https://cloud.browser-use.com)，它提供了专为规避检测和通过 CAPTCHA 挑战而设计的隐身浏览器。
</details>

<details>
<summary><b>如何投入生产环境 (Production)？</b></summary>

Chrome 会消耗大量内存，而且同时并行运行许多 Agent 在管理上可能非常棘手。

对于生产用例，请使用我们的 [Browser Use Cloud API](https://cloud.browser-use.com)，它能为您处理：
- 可扩展的浏览器基础设施
- 内存管理
- 代理轮换 (Proxy rotation)
- 隐身浏览器指纹识别 (Stealth browser fingerprinting)
- 高性能的并行执行
</details>

<br/>

<div align="center">

**告诉你的电脑该做什么，它就会为你办妥。**

<img src="https://github.com/user-attachments/assets/06fa3078-8461-4560-b434-445510c1766f" width="400"/>

[![Twitter Follow](https://img.shields.io/twitter/follow/Magnus?style=social)](https://x.com/intent/user?screen_name=mamagnus00)
&emsp;&emsp;&emsp;
[![Twitter Follow](https://img.shields.io/twitter/follow/Gregor?style=social)](https://x.com/intent/user?screen_name=gregpr07)

</div>

<div align="center"> Made with ❤️ in Zurich and San Francisco </div>

---

*本文档由 [@JasonYeYuhe](https://github.com/JasonYeYuhe) 翻译并维护。如果您发现任何翻译问题或需要补充内容，欢迎提交 Issue 或与我联系。*