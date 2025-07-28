# Browser-Use 强化学习系统设计文档

## 一、系统概述

### 1.1 项目背景
原Browser-Use项目是一个基于LLM的浏览器自动化框架，但存在一个关键问题：LLM每次做决策都是独立的，无法从过去的成功和失败中学习。这导致相同的错误可能重复出现，而有效的策略也无法被复用。为了解决这个问题，我们引入强化学习机制，通过记录、评分和检索历史执行经验，使agent能够在面对相似情况时参考过去的成功经验，从而提高任务完成率和执行效率。

### 1.2 核心思想
系统通过三个关键步骤实现经验学习：首先记录每次任务执行的完整过程（包括浏览器状态、可用工具、agent决策等），然后对每个动作的效果进行评分（-5到+5），最后在新的任务执行中通过状态相似度检索相关的历史经验，将高分经验作为参考信息提供给LLM，指导其做出更好的决策。这种方式不改变LLM的决策机制，而是通过提供更丰富的上下文信息来提升决策质量。

### 1.3 整体架构
- 数据收集层
- 数据处理层  
- 检索增强层
- 在线应用层

## 二、数据收集层

### 2.1 原始日志增强

#### 2.1.1 TXT日志格式增强
原项目的TXT日志记录了每个步骤的完整对话，但缺少了一个关键信息：**LLM在当前步骤可用的工具列表**。这个信息对于强化学习系统至关重要，因为它记录了LLM在特定状态下的决策空间，帮助我们理解：
- LLM从哪些工具中进行选择
- 某个决策是否合理（是否选择了最合适的工具）
- 在相似状态下，历史经验中哪些工具是可用的

**技术实现：**

1. **数据获取位置**：在`browser_use/agent/service.py`的`get_next_action`方法中
2. **获取逻辑**：从`self.ActionModel.model_fields`中提取工具名称和描述
3. **存储方式**：通过`self._last_tools_description`实例变量保存
4. **输出格式**：在`browser_use/agent/message_manager/utils.py`的`_format_conversation_full`方法中添加

**具体代码逻辑：**
```python
# 在get_next_action中获取工具描述
if hasattr(self, 'ActionModel') and hasattr(self.ActionModel, 'model_fields'):
    tools_desc = []
    for tool_name, tool_field in self.ActionModel.model_fields.items():
        if tool_field.description:
            tools_desc.append(f"{tool_name}: {tool_field.description}")
    self._last_tools_description = '\n'.join(tools_desc) if tools_desc else None
```

**日志格式增强效果：**
```
 AVAILABLE TOOLS/ACTIONS 
click_element: Click on an element
input_text: Input text into an element
scroll_page: Scroll the page
navigate_to_url: Navigate to a URL
done: Complete the task

 SystemMessage 
[系统提示词内容]

 HumanMessage 
[用户任务和浏览器状态]

 RAW LLM OUTPUT 
[LLM原始输出]

 RESPONSE
[解析后的agent输出]
```

#### 2.1.2 JSON日志结构化存储
原项目通过`AgentJSONLogger`类实现了结构化的JSON日志存储，将一次完整的agent任务执行过程保存为单个JSON文件。这种设计已经很完善，包含了强化学习所需的大部分关键信息。

**当前JSON结构示例：**
```json
{
  "session_info": {
    "session_id": "session_name_timestamp",
    "start_time": "2025-01-15T10:30:00.123456",
    "end_time": "2025-01-15T10:35:30.789012", 
    "total_steps": 12,
    "success": true,
    "task": "用户任务描述"
  },
  "steps": [
    {
      "step_number": 1,
      "timestamp": "2025-01-15T10:30:05.456789",
      "dom_state": {
        "url": "https://example.com",
        "title": "页面标题",
        "scroll_position": {"pixels_above": 0, "pixels_below": 800},
        "tabs": [{"page_id": "page_123", "url": "https://example.com", "title": "页面标题"}],
        "interactive_elements_text": "可交互元素的文本描述",
        "has_screenshot": true
      },
      "agent_response": {
        "thinking": "我需要点击登录按钮",
        "evaluation_previous_goal": "成功导航到了登录页面", 
        "memory": "已经到达登录页面",
        "next_goal": "点击登录按钮",
        "action": [{"action_type": "click_element", "parameters": {"index": 5}}]
      }
    }
  ]
}
```

**已包含的核心信息：**
- **任务上下文**：task描述、success状态、执行时间
- **决策过程**：thinking推理、next_goal目标、action动作
- **环境状态**：url、页面元素、滚动位置、标签页信息
- **执行轨迹**：step_number、timestamp、evaluation反馈


### 2.2 关键数据结构
- 会话(Session)数据模型
- 步骤(Step)数据模型
- 状态(State)表示方法

## 三、数据处理层

### 3.1 动作评分系统

动作评分系统通过`ActionScorer`类实现，负责对已完成任务的每个步骤进行质量评估，为强化学习提供训练信号。

#### 3.1.1 评分标准设计
采用**-5到+5**的整数评分体系，共11个分值级别：

**正向评分：**
- **+5**: 完美动作 - 直接解决核心问题或实现主要目标
- **+4**: 优秀动作 - 重大突破或关键进展
- **+3**: 良好动作 - 明确的正向进展
- **+2**: 有用动作 - 合理的常规步骤
- **+1**: 轻微帮助 - 小幅进展或准备动作

**中性评分：**
- **0**: 无影响 - 既不帮助也不阻碍

**负向评分：**
- **-1**: 轻微浪费 - 无害但不必要
- **-2**: 低效动作 - 浪费时间或资源
- **-3**: 错误动作 - 明显的错误选择
- **-4**: 有害动作 - 造成问题或倒退
- **-5**: 严重失败 - 重大阻碍

#### 3.1.2 评分实现特点
- **全局视角评分**：一次性评估整个任务流程，理解步骤间的依赖关系
- **批量处理**：单次API调用评分所有步骤，提高效率和一致性
- **结构化输出**：包含分数(score)、理由(reasoning)、情境描述(situation)
- **验证机制**：自动检查分数范围，处理异常情况

#### 3.1.3 评分数据结构
```json
{
  "task_analysis": "整体任务执行分析",
  "scored_steps": [
    {
      "step_number": 1,
      "scores": {
        "step_score": 3,
        "overall_reasoning": "该动作成功定位到目标页面",
        "situation": "在Google搜索页面，搜索框和按钮可见"
      }
    }
  ]
}
```

#### 3.1.4 技术实现
- 使用LangChain的ChatOpenAI接口
- 支持多种LLM模型（默认gpt-4o-mini）
- 详细的提示词工程确保评分一致性
- 完整的错误处理和日志记录

### 3.2 状态嵌入生成

状态嵌入系统通过`StateEmbedder`模块实现，将DOM状态转换为向量表示，为后续的相似经验检索提供基础。

#### 3.2.1 状态表示方案
从DOM状态中提取关键信息构建文本表示：
```
URL: {url}
Page Title: {title}
Interactive Elements: {interactive_elements}
Scroll Position: {pixels_above} pixels above, {pixels_below} pixels below
```

**选择这些特征的原因：**
- **URL**：标识页面位置和类型
- **标题**：页面内容的概括
- **交互元素**：可用的动作空间
- **滚动位置**：页面视图状态

#### 3.2.2 嵌入生成流程
1. **数据加载**：同时读取评分数据和原始会话数据
2. **状态提取**：从原始数据中提取DOM状态信息
3. **批量嵌入**：使用OpenAI的`text-embedding-3-large`模型
4. **数据整合**：将嵌入向量与动作、评分、情境描述等信息合并

#### 3.2.3 输出数据结构
```json
{
  "metadata": {
    "model": "text-embedding-3-large",
    "total_steps": 12,
    "source_files": {...}
  },
  "state_embeddings": [
    {
      "step_number": 1,
      "state_text": "URL: https://example.com\n...",
      "state_embedding": [3072维向量],
      "action": [{"action_type": "click_element", ...}],
      "score": 3,
      "reasoning": "该动作成功定位到目标页面",
      "situation": "在Google搜索页面，搜索框和按钮可见"
    }
  ]
}
```

#### 3.2.4 技术特点
- **高维向量**：使用3072维的text-embedding-3-large模型
- **批量处理**：一次API调用处理所有步骤，提高效率
- **信息完整**：保留评分、理由、情境等所有相关信息
- **灵活设计**：嵌入仅基于DOM状态，但输出包含完整上下文

### 3.3 向量存储系统

目前系统采用基于JSON文件的向量存储方案，为后续升级到专业向量数据库预留了接口。

#### 3.3.1 存储格式设计
嵌入数据以JSON格式存储在`state_embedder/`目录下，每个文件对应一个已评分的会话：

```json
{
  "metadata": {
    "model": "text-embedding-3-large",
    "total_steps": 15,
    "source_files": {
      "scored": "score_json/session_scored.json",
      "original": "json_logs/session.json"
    }
  },
  "state_embeddings": [
    {
      "step_number": 1,
      "state_text": "URL: https://example.com\n...",
      "state_embedding": [3072维浮点数组],
      "action": [{"action_type": "click_element", ...}],
      "score": 3,
      "reasoning": "该动作成功定位到目标页面",
      "situation": "在Google搜索页面，搜索框和按钮可见",
      "thinking": "我需要先搜索相关信息",
      "action_detail": "click_element: {'index': 5}"
    }
  ]
}
```

#### 3.3.2 数据完整性保证
系统在生成嵌入时整合多个数据源：
- **原始会话数据**：提取thinking字段，保留agent的原始推理过程
- **评分数据**：获取score、reasoning、situation等评估信息
- **DOM状态**：构建标准化的状态文本表示

这种设计确保了检索时能获得完整的历史经验上下文。

## 四、检索增强层

检索增强层通过`ExperienceRetriever`类实现，负责在agent执行时检索相似的历史经验，为决策提供参考。

### 4.1 相似性匹配

#### 4.1.1 状态相似度计算
采用余弦相似度作为相似性度量：
```python
def cosine_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
    norm1 = math.sqrt(sum(a * a for a in embedding1))
    norm2 = math.sqrt(sum(b * b for b in embedding2))
    return dot_product / (norm1 * norm2) if norm1 * norm2 != 0 else 0
```

#### 4.1.2 检索流程设计
1. **实时嵌入生成**：将当前DOM状态转换为嵌入向量
2. **多文件检索**：遍历所有历史嵌入文件计算相似度
3. **结果聚合**：收集所有相似状态并排序
4. **Top-K选择**：返回相似度最高的K个历史经验

#### 4.1.3 检索优化策略
- **相似度阈值**：只返回相似度高于阈值（默认0.7）的结果
- **评分过滤**：优先选择高分（score > 0）的历史经验
- **批量计算**：预加载所有嵌入文件，减少I/O开销

### 4.2 经验集成机制

#### 4.2.1 历史经验格式化
系统将检索到的历史经验格式化为结构化消息：

```
## 📚 Historical Experience Reference

Based on the current browser state, here are similar situations from past experiences:

**1. Similarity: 0.85**
- **Situation**: 在Google搜索页面，搜索框和按钮可见
- **Action and intention**: click_element - 我需要点击搜索框输入查询
- **Comment**: Score 3/5, 该动作成功定位到搜索框，为后续输入做好准备

**2. Similarity: 0.82**
- **Situation**: 搜索结果页面显示多个链接
- **Action and intention**: scroll_down - 需要向下滚动查看更多结果
- **Comment**: Score 2/5, 常规滚动操作，有效但效率一般
```

#### 4.2.2 系统提示词集成
在`system_prompt.md`中添加了历史经验指导：

```markdown
<historical_experience_guidance>
You may receive historical experience from similar past situations. These experiences include:
- **Situation**: The context/state when the action was taken
- **Action and intention**: What action was taken and why
- **Comment**: Score (-5 to +5) and reasoning for the action's effectiveness

Score interpretation:
- **+4 to +5**: Excellent actions that made breakthrough progress
- **+1 to +3**: Positive actions with varying degrees of usefulness
- **0**: Neutral actions with no significant impact
- **-1 to -3**: Inefficient or wrong actions to avoid
- **-4 to -5**: Harmful actions that caused significant problems

Use high-scoring experiences as positive examples and low-scoring ones as warnings.
</historical_experience_guidance>
```

### 4.3 实时检索集成

#### 4.3.1 检索触发时机
在agent主循环中，每个步骤开始前触发经验检索：

```python
# 在browser_use/agent/service.py的run方法中
if self.experience_retriever and browser_state_summary:
    # 创建当前状态的嵌入
    current_state_embedding = await self.experience_retriever.create_state_embedding(
        browser_state_summary
    )
    
    # 检索相似历史状态
    similar_states = self.experience_retriever.retrieve_similar_states(
        current_state_embedding,
        top_k=self.settings.experience_top_k,
        similarity_threshold=self.settings.experience_similarity_threshold
    )
    
    if similar_states:
        # 格式化并添加到消息历史
        experience_message = self.experience_retriever.format_experience_message(similar_states)
        self._message_manager._add_message_with_tokens(
            HumanMessage(content=experience_message)
        )
```

#### 4.3.2 性能考虑
- **异步处理**：嵌入生成使用异步API调用
- **缓存机制**：考虑对频繁访问的嵌入进行内存缓存
- **懒加载**：只在启用经验检索时加载历史数据

## 五、系统集成与优化

### 5.1 配置管理

#### 5.1.1 Agent配置扩展
在`AgentSettings`中添加了强化学习相关配置：

```python
class AgentSettings(BaseModel):
    # 历史经验检索设置
    enable_experience_retrieval: bool = False
    embeddings_file: str | None = None  # 指定特定的嵌入文件
    experience_similarity_threshold: float = 0.7
    experience_top_k: int = 5
```

#### 5.1.2 使用示例
```python
agent = Agent(
    browser=browser,
    task="完成某个任务",
    enable_experience_retrieval=True,
    experience_similarity_threshold=0.75,
    experience_top_k=3
)
```

### 5.2 模型优化与选择

#### 5.2.1 评分模型对比
通过实际测试，我们对比了多个LLM的评分效果：

| 模型 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| GPT-4o-mini | 响应快，成本低 | 评分相对宽松 | ★★★☆☆ |
| Claude-3 | 评分合理，解释详细 | 成本较高 | ★★★★☆ |
| Gemini-2.5-pro | 错误识别准确，评分严格 | 需处理JSON格式问题 | ★★★★★ |

**Gemini-2.5-pro的特殊处理：**
```python
# 处理Gemini返回的markdown包装JSON
content = response.content.strip()
if content.startswith('```json'):
    content = content[7:]  # 移除 ```json
    if content.endswith('```'):
        content = content[:-3]  # 移除结尾的 ```
```

#### 5.2.2 嵌入模型选择
使用OpenAI的`text-embedding-3-large`模型：
- **维度**：3072维，提供丰富的语义信息
- **性能**：在相似度匹配上表现优秀
- **成本**：相对合理，支持批量处理

### 5.3 已知问题与改进

#### 5.3.1 Conversation Log累积问题
**问题描述：**
原项目的conversation保存机制存在累积问题，每个步骤的日志文件包含了所有之前步骤的历史。

**问题根源：**
```python
# browser_use/agent/service.py 第1007行
input_messages = self._message_manager.get_messages()  # 获取所有累积消息

# 第1054行
await save_conversation(
    input_messages,  # 包含全部历史
    model_output, 
    target
)
```

**建议解决方案：**
1. 在`MessageManager`中添加`get_current_step_messages()`方法
2. 保存时只包含当前步骤的相关消息
3. 保持LLM调用时的完整上下文不变

#### 5.3.2 数据处理优化建议
1. **并行处理**：评分和嵌入生成可以并行化
2. **增量更新**：只处理新增的会话数据
3. **存储优化**：考虑压缩存储历史嵌入数据

## 六、技术实现总结

### 6.1 核心组件架构

#### 6.1.1 ActionScorer（动作评分器）
**职责**：对历史会话的每个动作进行质量评分
- **输入**：JSON格式的会话日志
- **输出**：包含评分和分析的增强JSON
- **特点**：批量评分、多模型支持、结构化输出

#### 6.1.2 StateEmbedder（状态嵌入器）
**职责**：将DOM状态转换为向量表示
- **输入**：评分后的会话数据 + 原始会话数据
- **输出**：包含嵌入向量的JSON文件
- **特点**：信息整合、批量处理、高维嵌入

#### 6.1.3 ExperienceRetriever（经验检索器）
**职责**：检索并格式化相似的历史经验
- **输入**：当前DOM状态
- **输出**：格式化的历史经验消息
- **特点**：实时检索、相似度计算、灵活过滤

### 6.2 数据流转管道

```
原始日志 → 动作评分 → 状态嵌入 → 经验检索 → Agent决策增强
   ↓           ↓           ↓           ↓              ↓
json_logs  score_json  state_embedder  runtime    improved actions
```

### 6.3 关键设计决策

1. **评分范围选择（-5到+5）**：
   - 11个离散级别提供足够的区分度
   - 避免过于细粒度的评分带来的不一致性
   - 便于LLM理解和应用

2. **JSON文件存储方案**：
   - 简单可靠，易于调试和人工检查
   - 无需额外的数据库依赖
   - 为未来升级到向量数据库预留接口

3. **批量处理策略**：
   - 减少API调用次数，降低成本
   - 保证同一会话的评分一致性
   - 提高整体处理效率

4. **信息完整性设计**：
   - 保留thinking、situation等关键上下文
   - 支持多维度的经验分析
   - 便于调试和效果评估

## 七、使用指南

### 7.1 快速开始

#### 7.1.1 处理历史数据
```bash
# 1. 对会话进行评分
python action_scorer.py json_logs/session_20250117.json --model gemini-2.5-pro

# 2. 生成状态嵌入
python state_embedder.py score_json/session_20250117_scored.json

# 3. 启用经验检索运行agent
agent = Agent(
    task="your task",
    enable_experience_retrieval=True
)
```

#### 7.1.2 配置文件示例
```python
# api_key.py
Openrouter_API_KEY = "your-api-key"
Openrouter_BASE_URL = "https://openrouter.ai/api/v1"
```

### 7.2 最佳实践

1. **数据收集阶段**：
   - 收集多样化的任务执行数据
   - 确保包含成功和失败的案例
   - 定期清理低质量数据

2. **评分阶段**：
   - 使用Gemini-2.5-pro获得最佳评分质量
   - 批量处理相关任务的会话
   - 人工抽查评分合理性

3. **应用阶段**：
   - 先在测试环境验证效果
   - 逐步调整相似度阈值
   - 监控检索的经验质量

## 八、总结与展望

### 8.1 系统成果

本强化学习增强系统成功实现了：

1. **完整的数据管道**：从日志收集到经验应用的全流程
2. **灵活的评分机制**：支持多模型、批量处理、结构化输出
3. **高效的检索系统**：基于语义相似度的历史经验检索
4. **无缝的集成方案**：最小化对原系统的改动

### 8.2 效果预期

- **任务成功率提升**：通过学习历史经验避免重复错误
- **执行效率优化**：参考高分动作选择更优路径
- **错误恢复能力**：从失败经验中学习恢复策略

### 8.3 未来发展方向

1. **向量数据库升级**：
   - 迁移到专业向量数据库（如Milvus、Pinecone）
   - 支持更大规模的历史数据
   - 提供更快的检索速度

2. **在线学习机制**：
   - 实时评分和更新
   - 自动识别新模式
   - 动态调整检索策略

3. **多任务知识迁移**：
   - 跨任务的经验共享
   - 通用动作模式提取
   - 领域特定知识库

4. **评估体系完善**：
   - A/B测试框架
   - 效果量化指标
   - 持续优化循环

通过这个强化学习系统，Browser-Use从一个"无记忆"的自动化工具进化为能够从经验中学习的智能agent，为复杂的Web自动化任务提供了更可靠和高效的解决方案。