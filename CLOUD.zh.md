<!--
IMPORTANT: This file is a localized version of CLOUD.md. 
When updating CLOUD.md, please ensure that the corresponding changes are also applied to this file to maintain parity.
-->

# Cloud.md (云服务文档)
供 AI Agent 使用的指令，用于协助用户使用 Browser Use Cloud。

## 什么是 Browser Use Cloud？
Browser Use 是一个用于与网页浏览器交互的 AI Agent 框架。
Browser Use Cloud 是由 Browser Use 提供的完全托管产品，旨在帮助用户实现基于 Web 任务的自动化。
用户以提示词（Prompt，包含文本以及可选的文件和图像）的形式提交任务，通过 API 请求，云端会按需启动远程浏览器和 Agent 来完成这些任务。
计费采用基于使用量模式，通过 API Key 系统进行管理。
账单、API Key 管理、实时会话查看、任务结果、账户设置和配置文件管理均通过 Browser Use Cloud 网页应用完成，网址为：https://cloud.browser-use.com/

## 核心概念：
Browser Use Cloud 的核心产品是完成用户任务。
- **会话 (Session)**：是 Browser Use Cloud 提供的完整基础设施包。目前会话的运行时间限制为 15 分钟。每个会话都有一个正在运行的浏览器，用户可以在会话中运行 Agent 来完成任务。一个会话仅限于一个且只有一个浏览器，该浏览器在会话的整个持续期间都将保持打开状态。用户一次只能在一个会话上运行最多一个 Agent，由该 Agent 控制浏览器。一个 Agent 完成后，用户可以在同一个会话中运行另一个 Agent，仅受会话最大持续时间的限制。
- **浏览器 (Browser)**：简而言之，就是在 Browser Use Cloud 基础设施（会话）上运行的浏览器。作为一项服务，浏览器可以通过 CDP URL 进行控制。用户可以使用 Agent 控制浏览器，也可以请求 CDP URL 并使用任何脚本或外部自动化工具控制托管的浏览器。然而，我们主要鼓励使用 Browser Use Agent 来控制浏览器，因为它们经过优化，可以协同工作。这些官方的 Browser Use 浏览器是从 Chromium 分叉出来的，但进行了大量专有优化，使其运行极快、轻量级、无法被追踪且不会被识别为机器人，并预装了广告拦截器和其他提升生活质量的功能。使用 Browser Use 托管浏览器可显著提升性能。
- **Agent**：是工具、提示词和框架的集合，使大语言模型 (LLM) 能够与浏览器进行交互。Agent 的目标是完成给定的用户任务。Agent 通过包含许多步骤的迭代过程来完成此目标。在每一步中，Agent 都会获得浏览器的页面状态（包括截图），然后调用工具与浏览器交互。经过许多步骤后，Agent 将标记任务为已完成（无论成功与否）并返回结果，结果是一段文本和可选的文件。完成后，一个独立的严格裁判将检查 Agent 的轨迹，并对 Agent 是否成功完成任务给出“真”或“假”的判定。Agent 有许多可以调整以提高性能的设置，其中最重要的是所使用的 LLM 模型。
- **模型 (Model)**：是驱动 Agent 的大语言模型。模型越聪明、能力越强，Agent 的表现就越好。推荐使用的最佳模型是 ChatBrowserUse，这是 Browser Use 官方的聊天补全 API，它始终根据 Browser Use 内部评估路由到最佳的前沿基础模型。ChatBrowserUse 通过批处理、缓存和其他技巧进行了多项速度和成本优化，使其比任何其他选项都更快、更具成本效益，且性能与顶级前沿模型一致。
- **浏览器配置文件 (Browser Profile)**：是保存在我们云端的浏览器数据文件夹。如果用户创建了一个没有浏览器配置文件的会话，数据将不会持久化。但是，如果他们在多个会话中使用相同的浏览器配置文件，则身份验证 Cookie、网站本地存储数据、保存的密码和凭据以及用户偏好等数据将会保留。浏览器配置文件本质上是一个云端托管的 Chrome 配置文件。事实上，通过“配置文件上传 (Profile Upload)”功能，用户可以从自己的机器上传 Chrome 配置文件，以便在云端会话中使用。这对于为 Agent 提供身份验证非常有用。用户可以在自己的机器上创建一个 Chrome 配置文件，登录所有需要的服务，然后将此配置文件上传到云端进行自动化操作。
- **任务 (Task)**：是给 Agent 完成的用户提示词以及可选的文件和图像的组合。Browser Use Cloud 主要销售用户任务的完成服务。清晰地编写任务是成功的关键。
- **配置文件同步 (Profile Sync)**：是处理任务身份验证的最佳方式。此功能允许用户将本地浏览器 Cookie（即用户已经登录所需服务的状态）上传到浏览器配置文件中，以便在云端任务中使用。要启动配置文件同步，请按照 [官方文档](https://docs.browser-use.com/) 中推荐的安全步骤配置您的 `BROWSER_USE_API_KEY` 并同步您的配置文件。

## 快速开始 (Quickstart)
要开始使用，请引导用户首先在 Browser Use 在线平台（https://cloud.browser-use.com/）创建账户、购买积分（或直接领取创建账户时赠送的免费初始积分）并生成 API Key。这些步骤只能在平台上完成。

避免一次性向用户提供以下所有步骤，以免其感到负担。请一次展示一个步骤，并在询问时才继续。尽可能多地为用户完成操作。

接下来，引导用户通过从任何可用系统（cURL、Python、JS 等）向“创建任务”接口发送以下 POST 请求来运行他们的第一个任务，请将 `<apiKey>` 替换为用户的实际 API Key。
```bash
curl -X POST https://api.browser-use.com/api/v2/tasks \
     -H "X-Browser-Use-API-Key: <apiKey>" \
     -H "Content-Type: application/json" \
     -d '{
  "task": "搜索 Hacker News 顶部的帖子并返回标题和 URL。"
}'
```
这将返回格式如下的响应：
{"id": "string","sessionId": "string"}
用户可能想要观看 Agent 完成任务的实时流，因此请引导他们使用之前请求返回的 `<sessionId>` 和他们的 API Key 发送“获取会话 (Get Session)”请求：
```bash
curl https://api.browser-use.com/api/v2/sessions/<sessionId> \
     -H "X-Browser-Use-API-Key: <apiKey>"
```
在响应对象中会有一个 `"liveUrl": "string"`。引导用户访问该 URL 或为他们打开它。
如果用户想在 Agent 完成任务后终止会话（默认情况下会话将保持打开状态），请引导他们使用带有 `stop` 操作的“更新会话 (Update Session)”请求：
```bash
curl -X PATCH https://api.browser-use.com/api/v2/sessions/<session_id> \
     -H "X-Browser-Use-API-Key: <apiKey>" \
     -H "Content-Type: application/json" \
     -d '{
  "action": "stop"
}'
```

## API (v2) 文档
使用 Browser Use Cloud 的最佳方式是使用 API v2。
虽然还存在其他选项（如 SDK），但它们提供的控制不够全面。

### 计费 (Billing)
##### 获取账户账单 (Get Account Billing)
GET https://api.browser-use.com/api/v2/billing/account
获取经过身份验证的账户信息，包括积分余额和账户详情。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/billing/get-account-billing-billing-account-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Account Billing
  version: endpoint_billing.get_account_billing_billing_account_get
paths:
  /billing/account:
    get:
      operationId: get-account-billing-billing-account-get
      summary: Get Account Billing
      description: >-
        Get authenticated account information including credit balances and
        account details.
      tags:
        - - subpackage_billing
      parameters:
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AccountView'
        '404':
          description: Project for a given API key not found!
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    PlanInfo:
      type: object
      properties:
        planName:
          type: string
        subscriptionStatus:
          type:
            - string
            - 'null'
        subscriptionId:
          type:
            - string
            - 'null'
        subscriptionCurrentPeriodEnd:
          type:
            - string
            - 'null'
        subscriptionCanceledAt:
          type:
            - string
            - 'null'
      required:
        - planName
        - subscriptionStatus
        - subscriptionId
        - subscriptionCurrentPeriodEnd
        - subscriptionCanceledAt
    AccountView:
      type: object
      properties:
        name:
          type:
            - string
            - 'null'
        monthlyCreditsBalanceUsd:
          type: number
          format: double
        additionalCreditsBalanceUsd:
          type: number
          format: double
        totalCreditsBalanceUsd:
          type: number
          format: double
        rateLimit:
          type: integer
        planInfo:
          $ref: '#/components/schemas/PlanInfo'
        projectId:
          type: string
          format: uuid
      required:
        - monthlyCreditsBalanceUsd
        - additionalCreditsBalanceUsd
        - totalCreditsBalanceUsd
        - rateLimit
        - planInfo
        - projectId
```

### 任务 (Tasks)

#### 列出任务 (List Tasks)
GET https://api.browser-use.com/api/v2/tasks
获取 AI Agent 任务的分页列表，可选择按会话和状态进行过滤。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/list-tasks-tasks-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: List Tasks
  version: endpoint_tasks.list_tasks_tasks_get
paths:
  /tasks:
    get:
      operationId: list-tasks-tasks-get
      summary: List Tasks
      description: >-
        Get paginated list of AI agent tasks with optional filtering by session
        and status.
      tags:
        - - subpackage_tasks
      parameters:
        - name: pageSize
          in: query
          required: false
          schema:
            type: integer
        - name: pageNumber
          in: query
          required: false
          schema:
            type: integer
        - name: sessionId
          in: query
          required: false
          schema:
            type:
              - string
              - 'null'
            format: uuid
        - name: filterBy
          in: query
          required: false
          schema:
            oneOf:
              - $ref: '#/components/schemas/TaskStatus'
              - type: 'null'
        - name: after
          in: query
          required: false
          schema:
            type:
              - string
              - 'null'
            format: date-time
        - name: before
          in: query
          required: false
          schema:
            type:
              - string
              - 'null'
            format: date-time
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TaskListResponse'
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    TaskStatus:
      type: string
      enum:
        - started
        - paused
        - finished
        - stopped
    TaskItemView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        sessionId:
          type: string
          format: uuid
        llm:
          type: string
        task:
          type: string
        status:
          $ref: '#/components/schemas/TaskStatus'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
        metadata:
          type: object
          additionalProperties:
            description: Any type
        output:
          type:
            - string
            - 'null'
        browserUseVersion:
          type:
            - string
            - 'null'
        isSuccess:
          type:
            - boolean
            - 'null'
      required:
        - id
        - sessionId
        - llm
        - task
        - status
        - startedAt
    TaskListResponse:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/TaskItemView'
        totalItems:
          type: integer
        pageNumber:
          type: integer
        pageSize:
          type: integer
      required:
        - items
        - totalItems
        - pageNumber
        - pageSize
```

#### 创建任务 (Create Task)
POST https://api.browser-use.com/api/v2/tasks
Content-Type: application/json
您可以选择：
1. 开始一个新任务（自动创建一个新的简单会话）
2. 在现有会话中开始一个新任务（您可以在开始任务之前创建一个自定义会话，并将其重新用于后续任务）
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/create-task-tasks-post
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Create Task
  version: endpoint_tasks.create_task_tasks_post
paths:
  /tasks:
    post:
      operationId: create-task-tasks-post
      summary: Create Task
      description: >-
        You can either:

        1. Start a new task (auto creates a new simple session)

        2. Start a new task in an existing session (you can create a custom
        session before starting the task and reuse it for follow-up tasks)
      tags:
        - - subpackage_tasks
      parameters:
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '202':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TaskCreatedResponse'
        '400':
          description: Session is stopped or has running task
          content: {}
        '404':
          description: Session not found
          content: {}
        '422':
          description: Request validation failed
          content: {}
        '429':
          description: Too many concurrent active sessions
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateTaskRequest'
components:
  schemas:
    SupportedLLMs:
      type: string
      enum:
        - browser-use-llm
        - gpt-4.1
        - gpt-4.1-mini
        - o4-mini
        - o3
        - gemini-2.5-flash
        - gemini-2.5-pro
        - gemini-flash-latest
        - gemini-flash-lite-latest
        - claude-sonnet-4-20250514
        - gpt-4o
        - gpt-4o-mini
        - llama-4-maverick-17b-128e-instruct
        - claude-3-7-sonnet-20250219
    CreateTaskRequestVision:
      oneOf:
        - type: boolean
        - type: string
          enum:
            - auto
    CreateTaskRequest:
      type: object
      properties:
        task:
          type: string
        llm:
          $ref: '#/components/schemas/SupportedLLMs'
        startUrl:
          type:
            - string
            - 'null'
        maxSteps:
          type: integer
        structuredOutput:
          type:
            - string
            - 'null'
        sessionId:
          type:
            - string
            - 'null'
          format: uuid
        metadata:
          type:
            - object
            - 'null'
          additionalProperties:
            type: string
        secrets:
          type:
            - object
            - 'null'
          additionalProperties:
            type: string
        allowedDomains:
          type:
            - array
            - 'null'
          items:
            type: string
        opVaultId:
          type:
            - string
            - 'null'
        highlightElements:
          type: boolean
        flashMode:
          type: boolean
        thinking:
          type: boolean
        vision:
          $ref: '#/components/schemas/CreateTaskRequestVision'
        systemPromptExtension:
          type: string
      required:
        - task
    TaskCreatedResponse:
      type: object
      properties:
        id:
          type: string
          format: uuid
        sessionId:
          type: string
          format: uuid
      required:
        - id
        - sessionId
```

#### 获取任务 (Get Task)
GET https://api.browser-use.com/api/v2/tasks/{task_id}
获取详细的任务信息，包括状态、进度、步骤和文件输出。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/get-task-tasks-task-id-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Task
  version: endpoint_tasks.get_task_tasks__task_id__get
paths:
  /tasks/{task_id}:
    get:
      operationId: get-task-tasks-task-id-get
      summary: Get Task
      description: >-
        Get detailed task information including status, progress, steps, and
        file outputs.
      tags:
        - - subpackage_tasks
      parameters:
        - name: task_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TaskView'
        '404':
          description: Task not found
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    TaskStatus:
      type: string
      enum:
        - started
        - paused
        - finished
        - stopped
    TaskStepView:
      type: object
      properties:
        number:
          type: integer
        memory:
          type: string
        evaluationPreviousGoal:
          type: string
        nextGoal:
          type: string
        url:
          type: string
        screenshotUrl:
          type:
            - string
            - 'null'
        actions:
          type: array
          items:
            type: string
      required:
        - number
        - memory
        - evaluationPreviousGoal
        - nextGoal
        - url
        - actions
    FileView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        fileName:
          type: string
      required:
        - id
        - fileName
    TaskView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        sessionId:
          type: string
          format: uuid
        llm:
          type: string
        task:
          type: string
        status:
          $ref: '#/components/schemas/TaskStatus'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
        metadata:
          type: object
          additionalProperties:
            description: Any type
        steps:
          type: array
          items:
            $ref: '#/components/schemas/TaskStepView'
        output:
          type:
            - string
            - 'null'
        outputFiles:
          type: array
          items:
            $ref: '#/components/schemas/FileView'
        browserUseVersion:
          type:
            - string
            - 'null'
        isSuccess:
          type:
            - boolean
            - 'null'
      required:
        - id
        - sessionId
        - llm
        - task
        - status
        - startedAt
        - steps
        - outputFiles
```

#### 更新任务 (Update Task)
PATCH https://api.browser-use.com/api/v2/tasks/{task_id}
Content-Type: application/json
通过停止、暂停、恢复或停止任务和会话等操作来控制任务执行。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/update-task-tasks-task-id-patch
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Update Task
  version: endpoint_tasks.update_task_tasks__task_id__patch
paths:
  /tasks/{task_id}:
    patch:
      operationId: update-task-tasks-task-id-patch
      summary: Update Task
      description: >-
        Control task execution with stop, pause, resume, or stop task and
        session actions.
      tags:
        - - subpackage_tasks
      parameters:
        - name: task_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TaskView'
        '404':
          description: Task not found
          content: {}
        '422':
          description: Request validation failed
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UpdateTaskRequest'
components:
  schemas:
    TaskUpdateAction:
      type: string
      enum:
        - stop
        - pause
        - resume
        - stop_task_and_session
    UpdateTaskRequest:
      type: object
      properties:
        action:
          $ref: '#/components/schemas/TaskUpdateAction'
      required:
        - action
    TaskStatus:
      type: string
      enum:
        - started
        - paused
        - finished
        - stopped
    TaskStepView:
      type: object
      properties:
        number:
          type: integer
        memory:
          type: string
        evaluationPreviousGoal:
          type: string
        nextGoal:
          type: string
        url:
          type: string
        screenshotUrl:
          type:
            - string
            - 'null'
        actions:
          type: array
          items:
            type: string
      required:
        - number
        - memory
        - evaluationPreviousGoal
        - nextGoal
        - url
        - actions
    FileView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        fileName:
          type: string
      required:
        - id
        - fileName
    TaskView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        sessionId:
          type: string
          format: uuid
        llm:
          type: string
        task:
          type: string
        status:
          $ref: '#/components/schemas/TaskStatus'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
        metadata:
          type: object
          additionalProperties:
            description: Any type
        steps:
          type: array
          items:
            $ref: '#/components/schemas/TaskStepView'
        output:
          type:
            - string
            - 'null'
        outputFiles:
          type: array
          items:
            $ref: '#/components/schemas/FileView'
        browserUseVersion:
          type:
            - string
            - 'null'
        isSuccess:
          type:
            - boolean
            - 'null'
      required:
        - id
        - sessionId
        - llm
        - task
        - status
        - startedAt
        - steps
        - outputFiles
```

#### 获取任务日志 (Get Task Logs)
GET https://api.browser-use.com/api/v2/tasks/{task_id}/logs
获取任务执行日志的安全下载 URL，包含每一步的详细信息。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/get-task-logs-tasks-task-id-logs-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Task Logs
  version: endpoint_tasks.get_task_logs_tasks__task_id__logs_get
paths:
  /tasks/{task_id}/logs:
    get:
      operationId: get-task-logs-tasks-task-id-logs-get
      summary: Get Task Logs
      description: >-
        Get secure download URL for task execution logs with step-by-step
        details.
      tags:
        - - subpackage_tasks
      parameters:
        - name: task_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TaskLogFileResponse'
        '404':
          description: Task not found
          content: {}
        '422':
          description: Validation Error
          content: {}
        '500':
          description: Failed to generate download URL
          content: {}
components:
  schemas:
    TaskLogFileResponse:
      type: object
      properties:
        downloadUrl:
          type: string
      required:
        - downloadUrl
```

### 会话 (Sessions)

#### 列出会话 (List Sessions)
GET https://api.browser-use.com/api/v2/sessions
获取 AI Agent 会话的分页列表，可选择按状态进行过滤。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/list-sessions-sessions-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: List Sessions
  version: endpoint_sessions.list_sessions_sessions_get
paths:
  /sessions:
    get:
      operationId: list-sessions-sessions-get
      summary: List Sessions
      description: Get paginated list of AI agent sessions with optional status filtering.
      tags:
        - - subpackage_sessions
      parameters:
        - name: pageSize
          in: query
          required: false
          schema:
            type: integer
        - name: pageNumber
          in: query
          required: false
          schema:
            type: integer
        - name: filterBy
          in: query
          required: false
          schema:
            oneOf:
              - $ref: '#/components/schemas/SessionStatus'
              - type: 'null'
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SessionListResponse'
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    SessionStatus:
      type: string
      enum:
        - active
        - stopped
    SessionItemView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/SessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - id
        - status
        - startedAt
    SessionListResponse:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/SessionItemView'
        totalItems:
          type: integer
        pageNumber:
          type: integer
        pageSize:
          type: integer
      required:
        - items
        - totalItems
        - pageNumber
        - pageSize
```

#### 创建会话 (Create Session)
POST https://api.browser-use.com/api/v2/sessions
Content-Type: application/json
创建一个包含新任务的新会话。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/create-session-sessions-post
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Create Session
  version: endpoint_sessions.create_session_sessions_post
paths:
  /sessions:
    post:
      operationId: create-session-sessions-post
      summary: Create Session
      description: Create a new session with a new task.
      tags:
        - - subpackage_sessions
      parameters:
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '201':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SessionItemView'
        '404':
          description: Profile not found
          content: {}
        '422':
          description: Request validation failed
          content: {}
        '429':
          description: Too many concurrent active sessions
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateSessionRequest'
components:
  schemas:
    ProxyCountryCode:
      type: string
      enum:
        - us
        - uk
        - fr
        - it
        - jp
        - au
        - de
        - fi
        - ca
        - in
    CreateSessionRequest:
      type: object
      properties:
        profileId:
          type:
            - string
            - 'null'
          format: uuid
        proxyCountryCode:
          oneOf:
            - $ref: '#/components/schemas/ProxyCountryCode'
            - type: 'null'
        startUrl:
          type:
            - string
            - 'null'
    SessionStatus:
      type: string
      enum:
        - active
        - stopped
    SessionItemView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/SessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - id
        - status
        - startedAt
```

#### 获取会话 (Get Session)
GET https://api.browser-use.com/api/v2/sessions/{session_id}
获取详细的会话信息，包括状态、URL 和任务详情。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/get-session-sessions-session-id-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Session
  version: endpoint_sessions.get_session_sessions__session_id__get
paths:
  /sessions/{session_id}:
    get:
      operationId: get-session-sessions-session-id-get
      summary: Get Session
      description: >-
        Get detailed session information including status, URLs, and task
        details.
      tags:
        - - subpackage_sessions
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SessionView'
        '404':
          description: Session not found
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    SessionStatus:
      type: string
      enum:
        - active
        - stopped
    TaskStatus:
      type: string
      enum:
        - started
        - paused
        - finished
        - stopped
    TaskItemView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        sessionId:
          type: string
          format: uuid
        llm:
          type: string
        task:
          type: string
        status:
          $ref: '#/components/schemas/TaskStatus'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
        metadata:
          type: object
          additionalProperties:
            description: Any type
        output:
          type:
            - string
            - 'null'
        browserUseVersion:
          type:
            - string
            - 'null'
        isSuccess:
          type:
            - boolean
            - 'null'
      required:
        - id
        - sessionId
        - llm
        - task
        - status
        - startedAt
    SessionView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/SessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
        tasks:
          type: array
          items:
            $ref: '#/components/schemas/TaskItemView'
        publicShareUrl:
          type:
            - string
            - 'null'
      required:
        - id
        - status
        - startedAt
        - tasks
```

#### 更新会话 (Update Session)
PATCH https://api.browser-use.com/api/v2/sessions/{session_id}
Content-Type: application/json
停止会话及其所有正在运行的任务。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/update-session-sessions-session-id-patch
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Update Session
  version: endpoint_sessions.update_session_sessions__session_id__patch
paths:
  /sessions/{session_id}:
    patch:
      operationId: update-session-sessions-session-id-patch
      summary: Update Session
      description: Stop a session and all its running tasks.
      tags:
        - - subpackage_sessions
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SessionView'
        '404':
          description: Session not found
          content: {}
        '422':
          description: Request validation failed
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UpdateSessionRequest'
components:
  schemas:
    SessionUpdateAction:
      type: string
      enum:
        - stop
    UpdateSessionRequest:
      type: object
      properties:
        action:
          $ref: '#/components/schemas/SessionUpdateAction'
      required:
        - action
    SessionStatus:
      type: string
      enum:
        - active
        - stopped
    TaskStatus:
      type: string
      enum:
        - started
        - paused
        - finished
        - stopped
    TaskItemView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        sessionId:
          type: string
          format: uuid
        llm:
          type: string
        task:
          type: string
        status:
          $ref: '#/components/schemas/TaskStatus'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
        metadata:
          type: object
          additionalProperties:
            description: Any type
        output:
          type:
            - string
            - 'null'
        browserUseVersion:
          type:
            - string
            - 'null'
        isSuccess:
          type:
            - boolean
            - 'null'
      required:
        - id
        - sessionId
        - llm
        - task
        - status
        - startedAt
    SessionView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/SessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
        tasks:
          type: array
          items:
            $ref: '#/components/schemas/TaskItemView'
        publicShareUrl:
          type:
            - string
            - 'null'
      required:
        - id
        - status
        - startedAt
        - tasks
```

#### 获取会话公开分享 (Get Session Public Share)
GET https://api.browser-use.com/api/v2/sessions/{session_id}/public-share
获取公开分享信息，包括 URL 和使用统计数据。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/get-session-public-share-sessions-session-id-public-share-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Session Public Share
  version: >-
    endpoint_sessions.get_session_public_share_sessions__session_id__public_share_get
paths:
  /sessions/{session_id}/public-share:
    get:
      operationId: get-session-public-share-sessions-session-id-public-share-get
      summary: Get Session Public Share
      description: Get public share information including URL and usage statistics.
      tags:
        - - subpackage_sessions
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ShareView'
        '404':
          description: Session or share not found
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    ShareView:
      type: object
      properties:
        shareToken:
          type: string
        shareUrl:
          type: string
        viewCount:
          type: integer
        lastViewedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - shareToken
        - shareUrl
        - viewCount
```

#### 创建会话公开分享 (Create Session Public Share)
POST https://api.browser-use.com/api/v2/sessions/{session_id}/public-share
为会话创建或返回现有的公开分享。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/create-session-public-share-sessions-session-id-public-share-post
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Create Session Public Share
  version: >-
    endpoint_sessions.create_session_public_share_sessions__session_id__public_share_post
paths:
  /sessions/{session_id}/public-share:
    post:
      operationId: create-session-public-share-sessions-session-id-public-share-post
      summary: Create Session Public Share
      description: Create or return existing public share for a session.
      tags:
        - - subpackage_sessions
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '201':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ShareView'
        '404':
          description: Session not found
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    ShareView:
      type: object
      properties:
        shareToken:
          type: string
        shareUrl:
          type: string
        viewCount:
          type: integer
        lastViewedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - shareToken
        - shareUrl
        - viewCount
```

#### 删除会话公开分享 (Delete Session Public Share)
DELETE https://api.browser-use.com/api/v2/sessions/{session_id}/public-share
移除会话的公开分享。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/delete-session-public-share-sessions-session-id-public-share-delete
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Delete Session Public Share
  version: >-
    endpoint_sessions.delete_session_public_share_sessions__session_id__public_share_delete
paths:
  /sessions/{session_id}/public-share:
    delete:
      operationId: delete-session-public-share-sessions-session-id-public-share-delete
      summary: Delete Session Public Share
      description: Remove public share for a session.
      tags:
        - - subpackage_sessions
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '204':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: >-
                  #/components/schemas/Sessions_delete_session_public_share_sessions__session_id__public_share_delete_Response_204
        '404':
          description: Session not found
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    Sessions_delete_session_public_share_sessions__session_id__public_share_delete_Response_204:
      type: object
      properties: {}
```

### 文件 (Files)

#### 用户上传文件预签名 URL (User Upload File Presigned Url)
POST https://api.browser-use.com/api/v2/files/sessions/{session_id}/presigned-url
Content-Type: application/json
生成用于上传文件的安全预签名 URL，AI Agent 在执行任务期间可以使用这些文件。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/files/user-upload-file-presigned-url-files-sessions-session-id-presigned-url-post
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: User Upload File Presigned Url
  version: >-
    endpoint_files.user_upload_file_presigned_url_files_sessions__session_id__presigned_url_post
paths:
  /files/sessions/{session_id}/presigned-url:
    post:
      operationId: >-
        user-upload-file-presigned-url-files-sessions-session-id-presigned-url-post
      summary: User Upload File Presigned Url
      description: >-
        Generate a secure presigned URL for uploading files that AI agents can
        use during tasks.
      tags:
        - - subpackage_files
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UploadFilePresignedUrlResponse'
        '400':
          description: Unsupported content type
          content: {}
        '404':
          description: Session not found
          content: {}
        '422':
          description: Validation Error
          content: {}
        '500':
          description: Failed to generate upload URL
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UploadFileRequest'
components:
  schemas:
    UploadFileRequestContentType:
      type: string
      enum:
        - image/jpg
        - image/jpeg
        - image/png
        - image/gif
        - image/webp
        - image/svg+xml
        - application/pdf
        - application/msword
        - >-
            application/vnd.openxmlformats-officedocument.wordprocessingml.document
        - application/vnd.ms-excel
        - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
        - text/plain
        - text/csv
        - text/markdown
    UploadFileRequest:
      type: object
      properties:
        fileName:
          type: string
        contentType:
          $ref: '#/components/schemas/UploadFileRequestContentType'
        sizeBytes:
          type: integer
      required:
        - fileName
        - contentType
        - sizeBytes
    UploadFilePresignedUrlResponse:
      type: object
      properties:
        url:
          type: string
        method:
          type: string
          enum:
            - POST
        fields:
          type: object
          additionalProperties:
            type: string
        fileName:
          type: string
        expiresIn:
          type: integer
      required:
        - url
        - method
        - fields
        - fileName
        - expiresIn
```

#### 用户上传文件预签名 URL 浏览器 (User Upload File Presigned Url Browser)
POST https://api.browser-use.com/api/v2/files/browsers/{session_id}/presigned-url
Content-Type: application/json
生成用于上传文件的安全预签名 URL，AI Agent 在执行任务期间可以使用这些文件。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/files/user-upload-file-presigned-url-browser-files-browsers-session-id-presigned-url-post
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: User Upload File Presigned Url Browser
  version: >-
    endpoint_files.user_upload_file_presigned_url_browser_files_browsers__session_id__presigned_url_post
paths:
  /files/browsers/{session_id}/presigned-url:
    post:
      operationId: >-
        user-upload-file-presigned-url-browser-files-browsers-session-id-presigned-url-post
      summary: User Upload File Presigned Url Browser
      description: >-
        Generate a secure presigned URL for uploading files that AI agents can
        use during tasks.
      tags:
        - - subpackage_files
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UploadFilePresignedUrlResponse'
        '400':
          description: Unsupported content type
          content: {}
        '404':
          description: Session not found
          content: {}
        '422':
          description: Validation Error
          content: {}
        '500':
          description: Failed to generate upload URL
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UploadFileRequest'
components:
  schemas:
    UploadFileRequestContentType:
      type: string
      enum:
        - image/jpg
        - image/jpeg
        - image/png
        - image/gif
        - image/webp
        - image/svg+xml
        - application/pdf
        - application/msword
        - >-
            application/vnd.openxmlformats-officedocument.wordprocessingml.document
        - application/vnd.ms-excel
        - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
        - text/plain
        - text/csv
        - text/markdown
    UploadFileRequest:
      type: object
      properties:
        fileName:
          type: string
        contentType:
          $ref: '#/components/schemas/UploadFileRequestContentType'
        sizeBytes:
          type: integer
      required:
        - fileName
        - contentType
        - sizeBytes
    UploadFilePresignedUrlResponse:
      type: object
      properties:
        url:
          type: string
        method:
          type: string
          enum:
            - POST
        fields:
          type: object
          additionalProperties:
            type: string
        fileName:
          type: string
        expiresIn:
          type: integer
      required:
        - url
        - method
        - fields
        - fileName
        - expiresIn
```

#### 获取任务输出文件预签名 URL (Get Task Output File Presigned Url)
GET https://api.browser-use.com/api/v2/files/tasks/{task_id}/output-files/{file_id}
获取由 AI Agent 生成的输出文件的安全下载 URL。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/files/get-task-output-file-presigned-url-files-tasks-task-id-output-files-file-id-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Task Output File Presigned Url
  version: >-
    endpoint_files.get_task_output_file_presigned_url_files_tasks__task_id__output_files__file_id__get
paths:
  /files/tasks/{task_id}/output-files/{file_id}:
    get:
      operationId: >-
        get-task-output-file-presigned-url-files-tasks-task-id-output-files-file-id-get
      summary: Get Task Output File Presigned Url
      description: Get secure download URL for an output file generated by the AI agent.
      tags:
        - - subpackage_files
      parameters:
        - name: task_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: file_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TaskOutputFileResponse'
        '404':
          description: Task or file not found
          content: {}
        '422':
          description: Validation Error
          content: {}
        '500':
          description: Failed to generate download URL
          content: {}
components:
  schemas:
    TaskOutputFileResponse:
      type: object
      properties:
        id:
          type: string
          format: uuid
        fileName:
          type: string
        downloadUrl:
          type: string
      required:
        - id
        - fileName
        - downloadUrl
```

### 配置文件 (Profiles)

#### 列出配置文件 (List Profiles)
GET https://api.browser-use.com/api/v2/profiles
获取配置文件的分页列表。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/list-profiles-profiles-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: List Profiles
  version: endpoint_profiles.list_profiles_profiles_get
paths:
  /profiles:
    get:
      operationId: list-profiles-profiles-get
      summary: List Profiles
      description: Get paginated list of profiles.
      tags:
        - - subpackage_profiles
      parameters:
        - name: pageSize
          in: query
          required: false
          schema:
            type: integer
        - name: pageNumber
          in: query
          required: false
          schema:
            type: integer
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProfileListResponse'
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    ProfileView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        name:
          type:
            - string
            - 'null'
        lastUsedAt:
          type:
            - string
            - 'null'
          format: date-time
        createdAt:
          type: string
          format: date-time
        updatedAt:
          type: string
          format: date-time
        cookieDomains:
          type:
            - array
            - 'null'
          items:
            type: string
      required:
        - id
        - createdAt
        - updatedAt
    ProfileListResponse:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/ProfileView'
        totalItems:
          type: integer
        pageNumber:
          type: integer
        pageSize:
          type: integer
      required:
        - items
        - totalItems
        - pageNumber
        - pageSize
```

#### 创建配置文件 (Create Profile)
POST https://api.browser-use.com/api/v2/profiles
Content-Type: application/json
配置文件允许您在任务之间保留浏览器状态。
它们最常用于允许用户在 Agent 的不同任务之间保留登录状态。
通常，您会为每个用户创建一个配置文件，然后将其用于该用户的所有任务。
您可以通过调用此端点创建一个新配置文件。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/create-profile-profiles-post
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Create Profile
  version: endpoint_profiles.create_profile_profiles_post
paths:
  /profiles:
    post:
      operationId: create-profile-profiles-post
      summary: Create Profile
      description: >-
        Profiles allow you to preserve the state of the browser between tasks.
        They are most commonly used to allow users to preserve the log-in state
        in the agent between tasks.
        You'd normally create one profile per user and then use it for all their
        tasks.
        You can create a new profile by calling this endpoint.
      tags:
        - - subpackage_profiles
      parameters:
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '201':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProfileView'
        '402':
          description: Subscription required for additional profiles
          content: {}
        '422':
          description: Request validation failed
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ProfileCreateRequest'
components:
  schemas:
    ProfileCreateRequest:
      type: object
      properties:
        name:
          type:
            - string
            - 'null'
    ProfileView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        name:
          type:
            - string
            - 'null'
        lastUsedAt:
          type:
            - string
            - 'null'
          format: date-time
        createdAt:
          type: string
          format: date-time
        updatedAt:
          type: string
          format: date-time
        cookieDomains:
          type:
            - array
            - 'null'
          items:
            type: string
      required:
        - id
        - createdAt
        - updatedAt
```

#### 获取配置文件 (Get Profile)
GET https://api.browser-use.com/api/v2/profiles/{profile_id}
获取配置文件详情。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/get-profile-profiles-profile-id-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Profile
  version: endpoint_profiles.get_profile_profiles__profile_id__get
paths:
  /profiles/{profile_id}:
    get:
      operationId: get-profile-profiles-profile-id-get
      summary: Get Profile
      description: Get profile details.
      tags:
        - - subpackage_profiles
      parameters:
        - name: profile_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProfileView'
        '404':
          description: Profile not found
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    ProfileView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        name:
          type:
            - string
            - 'null'
        lastUsedAt:
          type:
            - string
            - 'null'
          format: date-time
        createdAt:
          type: string
          format: date-time
        updatedAt:
          type: string
          format: date-time
        cookieDomains:
          type:
            - array
            - 'null'
          items:
            type: string
      required:
        - id
        - createdAt
        - updatedAt
```

#### 删除浏览器配置文件 (Delete Browser Profile)
DELETE https://api.browser-use.com/api/v2/profiles/{profile_id}
永久删除浏览器配置文件及其配置。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/delete-browser-profile-profiles-profile-id-delete
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Delete Browser Profile
  version: endpoint_profiles.delete_browser_profile_profiles__profile_id__delete
paths:
  /profiles/{profile_id}:
    delete:
      operationId: delete-browser-profile-profiles-profile-id-delete
      summary: Delete Browser Profile
      description: Permanently delete a browser profile and its configuration.
      tags:
        - - subpackage_profiles
      parameters:
        - name: profile_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '204':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: >-
                  #/components/schemas/Profiles_delete_browser_profile_profiles__profile_id__delete_Response_204
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    Profiles_delete_browser_profile_profiles__profile_id__delete_Response_204:
      type: object
      properties: {}
```

#### 更新配置文件 (Update Profile)
PATCH https://api.browser-use.com/api/v2/profiles/{profile_id}
Content-Type: application/json
更新浏览器配置文件的信息。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/update-profile-profiles-profile-id-patch
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Update Profile
  version: endpoint_profiles.update_profile_profiles__profile_id__patch
paths:
  /profiles/{profile_id}:
    patch:
      operationId: update-profile-profiles-profile-id-patch
      summary: Update Profile
      description: Update a browser profile's information.
      tags:
        - - subpackage_profiles
      parameters:
        - name: profile_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProfileView'
        '404':
          description: Profile not found
          content: {}
        '422':
          description: Validation Error
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ProfileUpdateRequest'
components:
  schemas:
    ProfileUpdateRequest:
      type: object
      properties:
        name:
          type:
            - string
            - 'null'
    ProfileView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        name:
          type:
            - string
            - 'null'
        lastUsedAt:
          type:
            - string
            - 'null'
          format: date-time
        createdAt:
          type: string
          format: date-time
        updatedAt:
          type: string
          format: date-time
        cookieDomains:
          type:
            - array
            - 'null'
          items:
            type: string
      required:
        - id
        - createdAt
        - updatedAt
```

### 浏览器 (Browsers)

#### 列出浏览器会话 (List Browser Sessions)
GET https://api.browser-use.com/api/v2/browsers
获取浏览器会话的分页列表，可选择按状态进行过滤。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/list-browser-sessions-browsers-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: List Browser Sessions
  version: endpoint_browsers.list_browser_sessions_browsers_get
paths:
  /browsers:
    get:
      operationId: list-browser-sessions-browsers-get
      summary: List Browser Sessions
      description: Get paginated list of browser sessions with optional status filtering.
      tags:
        - - subpackage_browsers
      parameters:
        - name: pageSize
          in: query
          required: false
          schema:
            type: integer
        - name: pageNumber
          in: query
          required: false
          schema:
            type: integer
        - name: filterBy
          in: query
          required: false
          schema:
            oneOf:
              - $ref: '#/components/schemas/BrowserSessionStatus'
              - type: 'null'
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BrowserSessionListResponse'
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    BrowserSessionStatus:
      type: string
      enum:
        - active
        - stopped
    BrowserSessionItemView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/BrowserSessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        cdpUrl:
          type:
            - string
            - 'null'
        timeoutAt:
          type: string
          format: date-time
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - id
        - status
        - timeoutAt
        - startedAt
    BrowserSessionListResponse:
      type: object
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/BrowserSessionItemView'
        totalItems:
          type: integer
        pageNumber:
          type: integer
        pageSize:
          type: integer
      required:
        - items
        - totalItems
        - pageNumber
        - pageSize
```

#### 创建浏览器会话 (Create Browser Session)
POST https://api.browser-use.com/api/v2/browsers
Content-Type: application/json
创建一个新的浏览器会话。
**定价**：浏览器会话的费用为每小时 0.05 美元。
会话开始时预先扣除全额小时费用。
当您停止会话时，任何未使用的时间将按比例自动退还。
计费按分钟向上取整（最少 1 分钟）。
例如，如果您在 30 分钟后停止会话，将退还 0.025 美元。
**会话限制**：
- 免费用户（没有有效订阅）：每个会话最多 15 分钟
- 付费订阅者：每个会话最多 4 小时
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/create-browser-session-browsers-post
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Create Browser Session
  version: endpoint_browsers.create_browser_session_browsers_post
paths:
  /browsers:
    post:
      operationId: create-browser-session-browsers-post
      summary: Create Browser Session
      description: >-
        Create a new browser session.
        **Pricing:** Browser sessions are charged at $0.05 per hour.
        The full hourly rate is charged upfront when the session starts.
        When you stop the session, any unused time is automatically refunded
        proportionally.
        Billing is rounded to the nearest minute (minimum 1 minute).
        For example, if you stop a session after 30 minutes, you'll be refunded
        $0.025.
        **Session Limits:**
        - Free users (without active subscription): Maximum 15 minutes per
        session
        - Paid subscribers: Up to 4 hours per session
      tags:
        - - subpackage_browsers
      parameters:
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '201':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BrowserSessionItemView'
        '403':
          description: Session timeout limit exceeded for free users
          content: {}
        '404':
          description: Profile not found
          content: {}
        '422':
          description: Request validation failed
          content: {}
        '429':
          description: Too many concurrent active sessions
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateBrowserSessionRequest'
components:
  schemas:
    ProxyCountryCode:
      type: string
      enum:
        - us
        - uk
        - fr
        - it
        - jp
        - au
        - de
        - fi
        - ca
        - in
    CreateBrowserSessionRequest:
      type: object
      properties:
        profileId:
          type:
            - string
            - 'null'
          format: uuid
        proxyCountryCode:
          oneOf:
            - $ref: '#/components/schemas/ProxyCountryCode'
            - type: 'null'
        timeout:
          type: integer
    BrowserSessionStatus:
      type: string
      enum:
        - active
        - stopped
    BrowserSessionItemView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/BrowserSessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        cdpUrl:
          type:
            - string
            - 'null'
        timeoutAt:
          type: string
          format: date-time
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - id
        - status
        - timeoutAt
        - startedAt
```

#### 获取浏览器会话 (Get Browser Session)
GET https://api.browser-use.com/api/v2/browsers/{session_id}
获取详细的浏览器会话信息，包括状态和 URL。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/get-browser-session-browsers-session-id-get
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Get Browser Session
  version: endpoint_browsers.get_browser_session_browsers__session_id__get
paths:
  /browsers/{session_id}:
    get:
      operationId: get-browser-session-browsers-session-id-get
      summary: Get Browser Session
      description: Get detailed browser session information including status and URLs.
      tags:
        - - subpackage_browsers
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BrowserSessionView'
        '404':
          description: Session not found
          content: {}
        '422':
          description: Validation Error
          content: {}
components:
  schemas:
    BrowserSessionStatus:
      type: string
      enum:
        - active
        - stopped
    BrowserSessionView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/BrowserSessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        cdpUrl:
          type:
            - string
            - 'null'
        timeoutAt:
          type: string
          format: date-time
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - id
        - status
        - timeoutAt
        - startedAt
```

#### 更新浏览器会话 (Update Browser Session)
PATCH https://api.browser-use.com/api/v2/browsers/{session_id}
Content-Type: application/json
停止浏览器会话。
**退款**：当您停止会话时，未使用的时间将自动退还。
如果会话运行时间不足 1 小时，您将收到按比例退还的款项。
计费按分钟向上取整（最少 1 分钟）。
参考：https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/update-browser-session-browsers-session-id-patch
OpenAPI 规范
```yaml
openapi: 3.1.1
info:
  title: Update Browser Session
  version: endpoint_browsers.update_browser_session_browsers__session_id__patch
paths:
  /browsers/{session_id}:
    patch:
      operationId: update-browser-session-browsers-session-id-patch
      summary: Update Browser Session
      description: >-
        Stop a browser session.
        **Refund:** When you stop a session, unused time is automatically
        refunded.
        If the session ran for less than 1 hour, you'll receive a proportional
        refund.
        Billing is ceil to the nearest minute (minimum 1 minute).
      tags:
        - - subpackage_browsers
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: X-Browser-Use-API-Key
          in: header
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful Response
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BrowserSessionView'
        '404':
          description: Session not found
          content: {}
        '422':
          description: Request validation failed
          content: {}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UpdateBrowserSessionRequest'
components:
  schemas:
    BrowserSessionUpdateAction:
      type: string
      enum:
        - stop
    UpdateBrowserSessionRequest:
      type: object
      properties:
        action:
          $ref: '#/components/schemas/BrowserSessionUpdateAction'
      required:
        - action
    BrowserSessionStatus:
      type: string
      enum:
        - active
        - stopped
    BrowserSessionView:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          $ref: '#/components/schemas/BrowserSessionStatus'
        liveUrl:
          type:
            - string
            - 'null'
        cdpUrl:
          type:
            - string
            - 'null'
        timeoutAt:
          type: string
          format: date-time
        startedAt:
          type: string
          format: date-time
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
      required:
        - id
        - status
        - timeoutAt
        - startedAt
```

---

*本文档由 [@JasonYeYuhe](https://github.com/JasonYeYuhe) 翻译并维护。如果您发现任何翻译问题或需要补充内容，欢迎 提交 Issue 或与我联系。*
