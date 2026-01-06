# Cloud.md
Instructions for AI Agents to assist the user in using Browser Use Cloud

## What is Browser Use Cloud?
Browser Use is a framework for AI Agents that interact with web browsers.
Browser Use Cloud is the fully hosted product made by Browser Use made for users to automate web-based tasks. 
Users submit tasks in the form of prompts (text and optionally files and images) and through API requests, remote browsers and agents are spun up to complete these tasks on-demand. 
Pricing is usage based and adjudicated through an API key system.
Billing, API Key management, live session viewing, task results, account settings, and profile management is done through the Browser Use Cloud web app at https://cloud.browser-use.com/

## Core Concepts:
The key product of Browser Use Cloud is the completion of user tasks.
- A Session is the complete package of infrastructure Browser Use Cloud provides. Sessions are currently limited to 15 minutes of runtime. A session has a Browser running, and users can run Agents in a session to complete tasks. A Session is limited to one and only one Browser, which will be open the entire duration of the Session. Users can run a maximum of one Agent on a Session at a time, which will control the Browser. After one Agent is done, the user can run another within the same Session, limited only by the Session maximum duration.
- A Browser is simply a browser running on Browser Use Cloud infrastructure (a Session). Browsers (as a service) are controllable via CDP url. The user can use an Agent to control a Browser, or can request the CDP url and control the hosted browser with whatever scripts or external automations they desire. However we mainly encourage to control Browsers with Browser Use Agents, as they are optimized to work together. These official Browser Use browsers are forked from chromium, but have a lot of proprietary optimizations made to them so that they are extremely fast and lightweight, untraceable and not detectable as bots, and come preloaded with adblockers and other quality of life. Using Browser Use hosted browsers provides significant performance improvements. 
- An Agent is the collection of tools, prompts, and framework that enables a Large Language Model to interact with a Browser. The Agents goal is to complete a given user Task. The Agent goes through an iterative process of many steps to complete this. For each step, the Agent is given the page state (including a screenshot) of the Browser, and then it calls tools to interact with the Browser. After many steps, the Agent will mark the task as complete, either successfully or unsuccessfully and return a result, which is a block of text and optionally files. After completion, an independent strict judge will examine the Agent's trajectory and give a verdict of true or false on whether the Agent completed its task successfully. The Agent has a lot of settings which can be tuned to improve performance, most importantly the LLM Model used.
- A Model is a Large Language Model that powers an Agent. The smarter and more capable the Model, the better the Agent will perform. The best model to use is ChatBrowserUse, the Browser Use official chat completion API which always routes to the best frontier foundation model as determined by Browser Use internal evaluations. ChatBrowserUse has several speed and cost optimizations done through batching, caching, and other tricks, making it faster and more cost effective than any other option, with identical performance to the top frontier models.
- A Browser Profile is a folder of browser data that is saved on our Cloud. If a user creates a Session with a Browser that has no Browser Profile, no data will persist. However, if they use the same Browser Profile across multiple Sessions, then data such as authentication cookies, site local storage data, saved passwords and credentials, and user preferences will persist. A Browser Profile is essentially a cloud hosted Chrome Profile, in fact, through the Profile Upload feature, a user can upload a Chrome profile from their own machine to be used on the Cloud in Sessions. This is great for giving authentication to Agents. A user can create a Chrome profile on their own machine, log into all of the services they want, and then upload this profile to the Cloud for automations.
- A Task is the combination of user prompt with optionally files and images that is given to the Agents to complete. Browser Use Cloud primarily sells the completion of user Tasks. Writing Tasks with clarity is key to success. 
- Profile Sync is the best way to handle authentication for tasks. This feature allows users to upload their local browser cookies (where the user is already logged into the services they need authentication for) to a Browser Profile that can be used for tasks on the cloud. To initiate a Profile Sync, a user must run `export BROWSER_USE_API_KEY=<your_key> && curl -fsSL https://browser-use.com/profile.sh | sh` and follow the steps in the interactive terminal.

## Quickstart
To get started, direct the user to first must create an account, purchase credits (or simply claim the free starter credits given on account creation), and generate an API key on the Browser Use online platform: https://cloud.browser-use.com/. These are the only steps that can only be done on the platform.

Avoid giving the user all of the following steps at once as it may seem overwheling. Instead present one step at a time and only continue when asked. Do as much for the user as you are able to.

Next, direct the user to run their first task by making the following post request to Create Task from whatever system is available (cURL, python, JS, etc), but replace `<apiKey>` with the users actual API key.
```bash
curl -X POST https://api.browser-use.com/api/v2/tasks \
     -H "X-Browser-Use-API-Key: <apiKey>" \
     -H "Content-Type: application/json" \
     -d '{
  "task": "Search for the top Hacker News post and return the title and url."
}'
```
This will return a response of the format:
{"id": "string","sessionId": "string"}
The user will probably want to watch the live stream of the task being completed by the agent, so direct them to use the Get Session request using the `<sessionId>` returned by the prior request and their API key
```bash
curl https://api.browser-use.com/api/v2/sessions/<sessionId> \
     -H "X-Browser-Use-API-Key: <apiKey>"
```
And in the response object there will be a `"liveUrl": "string"`. Direct the user to visit that url or open it for them.
If the user wants to terminate the Session after the Agent has completed its task (by default the Session will remain open), direct them to use the Update Session request with the stop action
```bash
curl -X PATCH https://api.browser-use.com/api/v2/sessions/<session_id> \
     -H "X-Browser-Use-API-Key: <apiKey>" \
     -H "Content-Type: application/json" \
     -d '{
  "action": "stop"

}'
```

## API (v2) Docs
The best way to use Browser Use Cloud is with API v2. 
Other options exist, namely API v2 and the SDK, but give less comprehensive control.

### Billing
##### Get Account Billing
GET https://api.browser-use.com/api/v2/billing/account
Get authenticated account information including credit balances and account details.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/billing/get-account-billing-billing-account-get
OpenAPI Specification
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

### Tasks

#### List Tasks
GET https://api.browser-use.com/api/v2/tasks
Get paginated list of AI agent tasks with optional filtering by session and status.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/list-tasks-tasks-get
OpenAPI Specification
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
        - value: started
        - value: paused
        - value: finished
        - value: stopped
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

#### Create Task
POST https://api.browser-use.com/api/v2/tasks
Content-Type: application/json
You can either:
1. Start a new task (auto creates a new simple session)
2. Start a new task in an existing session (you can create a custom session before starting the task and reuse it for follow-up tasks)
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/create-task-tasks-post
OpenAPI Specification
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
        - value: browser-use-llm
        - value: gpt-4.1
        - value: gpt-4.1-mini
        - value: o4-mini
        - value: o3
        - value: gemini-2.5-flash
        - value: gemini-2.5-pro
        - value: gemini-flash-latest
        - value: gemini-flash-lite-latest
        - value: claude-sonnet-4-20250514
        - value: gpt-4o
        - value: gpt-4o-mini
        - value: llama-4-maverick-17b-128e-instruct
        - value: claude-3-7-sonnet-20250219
    CreateTaskRequestVision:
      oneOf:
        - type: boolean
        - type: string
          enum:
            - type: stringLiteral
              value: auto
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

#### Get Task
GET https://api.browser-use.com/api/v2/tasks/{task_id}
Get detailed task information including status, progress, steps, and file outputs.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/get-task-tasks-task-id-get
OpenAPI Specification
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
        - value: started
        - value: paused
        - value: finished
        - value: stopped
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

#### Update Task
PATCH https://api.browser-use.com/api/v2/tasks/{task_id}
Content-Type: application/json
Control task execution with stop, pause, resume, or stop task and session actions.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/update-task-tasks-task-id-patch
OpenAPI Specification
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
        - value: stop
        - value: pause
        - value: resume
        - value: stop_task_and_session
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
        - value: started
        - value: paused
        - value: finished
        - value: stopped
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

#### Get Task Logs
GET https://api.browser-use.com/api/v2/tasks/{task_id}/logs
Get secure download URL for task execution logs with step-by-step details.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/tasks/get-task-logs-tasks-task-id-logs-get
OpenAPI Specification
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

### Sessions

#### List Sessions
GET https://api.browser-use.com/api/v2/sessions
Get paginated list of AI agent sessions with optional status filtering.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/list-sessions-sessions-get
OpenAPI Specification
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
        - value: active
        - value: stopped
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

#### Create Session
POST https://api.browser-use.com/api/v2/sessions
Content-Type: application/json
Create a new session with a new task.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/create-session-sessions-post
OpenAPI Specification
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
        - value: us
        - value: uk
        - value: fr
        - value: it
        - value: jp
        - value: au
        - value: de
        - value: fi
        - value: ca
        - value: in
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
        - value: active
        - value: stopped
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

#### Get Session
GET https://api.browser-use.com/api/v2/sessions/{session_id}
Get detailed session information including status, URLs, and task details.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/get-session-sessions-session-id-get
OpenAPI Specification
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
        - value: active
        - value: stopped
    TaskStatus:
      type: string
      enum:
        - value: started
        - value: paused
        - value: finished
        - value: stopped
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

#### Update Session
PATCH https://api.browser-use.com/api/v2/sessions/{session_id}
Content-Type: application/json
Stop a session and all its running tasks.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/update-session-sessions-session-id-patch
OpenAPI Specification
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
        - value: stop
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
        - value: active
        - value: stopped
    TaskStatus:
      type: string
      enum:
        - value: started
        - value: paused
        - value: finished
        - value: stopped
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

#### Get Session Public Share
GET https://api.browser-use.com/api/v2/sessions/{session_id}/public-share
Get public share information including URL and usage statistics.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/get-session-public-share-sessions-session-id-public-share-get
OpenAPI Specification
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

#### Create Session Public Share
POST https://api.browser-use.com/api/v2/sessions/{session_id}/public-share
Create or return existing public share for a session.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/create-session-public-share-sessions-session-id-public-share-post
OpenAPI Specification
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

#### Delete Session Public Share
DELETE https://api.browser-use.com/api/v2/sessions/{session_id}/public-share
Remove public share for a session.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/sessions/delete-session-public-share-sessions-session-id-public-share-delete
OpenAPI Specification
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

### Files

#### User Upload File Presigned Url
POST https://api.browser-use.com/api/v2/files/sessions/{session_id}/presigned-url
Content-Type: application/json
Generate a secure presigned URL for uploading files that AI agents can use during tasks.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/files/user-upload-file-presigned-url-files-sessions-session-id-presigned-url-post
OpenAPI Specification
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
        - value: image/jpg
        - value: image/jpeg
        - value: image/png
        - value: image/gif
        - value: image/webp
        - value: image/svg+xml
        - value: application/pdf
        - value: application/msword
        - value: >-
            application/vnd.openxmlformats-officedocument.wordprocessingml.document
        - value: application/vnd.ms-excel
        - value: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
        - value: text/plain
        - value: text/csv
        - value: text/markdown
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
            - type: stringLiteral
              value: POST
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

#### User Upload File Presigned Url Browser
POST https://api.browser-use.com/api/v2/files/browsers/{session_id}/presigned-url
Content-Type: application/json
Generate a secure presigned URL for uploading files that AI agents can use during tasks.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/files/user-upload-file-presigned-url-browser-files-browsers-session-id-presigned-url-post
OpenAPI Specification
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
        - value: image/jpg
        - value: image/jpeg
        - value: image/png
        - value: image/gif
        - value: image/webp
        - value: image/svg+xml
        - value: application/pdf
        - value: application/msword
        - value: >-
            application/vnd.openxmlformats-officedocument.wordprocessingml.document
        - value: application/vnd.ms-excel
        - value: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
        - value: text/plain
        - value: text/csv
        - value: text/markdown
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
            - type: stringLiteral
              value: POST
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

#### Get Task Output File Presigned Url
GET https://api.browser-use.com/api/v2/files/tasks/{task_id}/output-files/{file_id}
Get secure download URL for an output file generated by the AI agent.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/files/get-task-output-file-presigned-url-files-tasks-task-id-output-files-file-id-get
OpenAPI Specification
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

### Profiles

#### List Profiles
GET https://api.browser-use.com/api/v2/profiles
Get paginated list of profiles.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/list-profiles-profiles-get
OpenAPI Specification
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

#### Create Profile
POST https://api.browser-use.com/api/v2/profiles
Content-Type: application/json
Profiles allow you to preserve the state of the browser between tasks.
They are most commonly used to allow users to preserve the log-in state in the agent between tasks.
You'd normally create one profile per user and then use it for all their tasks.
You can create a new profile by calling this endpoint.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/create-profile-profiles-post
OpenAPI Specification
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

#### Get Profile
GET https://api.browser-use.com/api/v2/profiles/{profile_id}
Get profile details.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/get-profile-profiles-profile-id-get
OpenAPI Specification
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

#### Delete Browser Profile
DELETE https://api.browser-use.com/api/v2/profiles/{profile_id}
Permanently delete a browser profile and its configuration.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/delete-browser-profile-profiles-profile-id-delete
OpenAPI Specification
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

#### Update Profile
PATCH https://api.browser-use.com/api/v2/profiles/{profile_id}
Content-Type: application/json
Update a browser profile's information.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/profiles/update-profile-profiles-profile-id-patch
OpenAPI Specification
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

### Browsers

#### List Browser Sessions
GET https://api.browser-use.com/api/v2/browsers
Get paginated list of browser sessions with optional status filtering.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/list-browser-sessions-browsers-get
OpenAPI Specification
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
        - value: active
        - value: stopped
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

#### Create Browser Session
POST https://api.browser-use.com/api/v2/browsers
Content-Type: application/json
Create a new browser session.
**Pricing:** Browser sessions are charged at $0.05 per hour.
The full hourly rate is charged upfront when the session starts.
When you stop the session, any unused time is automatically refunded proportionally.
Billing is rounded to the nearest minute (minimum 1 minute).
For example, if you stop a session after 30 minutes, you'll be refunded $0.025.
**Session Limits:**
- Free users (without active subscription): Maximum 15 minutes per session
- Paid subscribers: Up to 4 hours per session
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/create-browser-session-browsers-post
OpenAPI Specification
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
        - value: us
        - value: uk
        - value: fr
        - value: it
        - value: jp
        - value: au
        - value: de
        - value: fi
        - value: ca
        - value: in
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
        - value: active
        - value: stopped
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

#### Get Browser Session
GET https://api.browser-use.com/api/v2/browsers/{session_id}
Get detailed browser session information including status and URLs.
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/get-browser-session-browsers-session-id-get
OpenAPI Specification
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
        - value: active
        - value: stopped
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

#### Update Browser Session
PATCH https://api.browser-use.com/api/v2/browsers/{session_id}
Content-Type: application/json
Stop a browser session.
**Refund:** When you stop a session, unused time is automatically refunded.
If the session ran for less than 1 hour, you'll receive a proportional refund.
Billing is ceil to the nearest minute (minimum 1 minute).
Reference: https://docs.cloud.browser-use.com/api-reference/v-2-api-current/browsers/update-browser-session-browsers-session-id-patch
OpenAPI Specification
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
        - value: stop
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
        - value: active
        - value: stopped
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
