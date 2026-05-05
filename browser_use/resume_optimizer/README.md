# 简历优化模块 (Resume Optimizer)

基于 browser-use 的简历优化模块，为求职 Agent 提供简历定向优化能力。

## 功能特性

- **多种优化风格**: 支持大厂风、科研风、产品风、算法岗风、后端岗风
- **LLM 智能增强**: 使用大语言模型智能优化项目描述和个人总结
- **智能匹配**: 根据岗位需求计算匹配分数
- **Pydantic 验证**: 所有数据模型使用 Pydantic 进行验证
- **模板渲染**: 支持 HTML、Markdown、PDF 多种输出格式
- **API 接口**: 提供与后端编排层对接的统一接口
- **简历解析**: 支持 PDF、Word、Markdown、HTML、JSON 多种输入格式

## 项目结构

```
resume_optimizer/
├── __init__.py          # 模块初始化
├── views.py            # Pydantic 数据模型
├── optimizer.py        # 核心优化逻辑
├── llm_enhancer.py     # LLM 增强器
├── api.py              # API 接口
├── styles/             # 风格优化器
│   ├── __init__.py
│   ├── base.py
│   ├── big_tech.py
│   ├── research.py
│   ├── product.py
│   ├── algorithm.py
│   └── backend.py
├── utils/              # 工具函数
│   ├── __init__.py
│   ├── parser.py       # 简历解析器
│   ├── renderer.py     # 模板渲染器
│   └── helpers.py
├── templates/          # 简历模板
│   ├── modern.html
│   └── classic.html
├── tests/              # 单元测试
│   ├── __init__.py
│   ├── test_views.py
│   ├── test_optimizer.py
│   └── test_parser.py
└── examples/           # 使用示例
    └── example_usage.py
```

## 快速开始

### 基础使用

```python
import asyncio
from resume_optimizer import ResumeOptimizer, OptimizationStyle
from resume_optimizer.views import ResumeData, JobRequirement, Project

async def main():
    # 创建简历数据
    resume = ResumeData(
        name="张三",
        email="zhangsan@example.com",
        skills=["Python", "Machine Learning", "TensorFlow"],
        projects=[
            Project(
                name="推荐系统",
                description="使用深度学习构建的推荐系统"
            )
        ]
    )

    # 创建岗位需求
    job = JobRequirement(
        title="算法工程师",
        company="字节跳动",
        required_skills=["Machine Learning", "Python"],
        preferred_skills=["TensorFlow", "Deep Learning"]
    )

    # 优化简历（异步）
    optimizer = ResumeOptimizer()
    result = await optimizer.optimize(resume, job, OptimizationStyle.ALGORITHM)

    print(f"匹配分数: {result.match_score}%")
    print(f"优化建议: {result.suggestions}")

asyncio.run(main())
```

### API 接口使用

```python
import asyncio
from resume_optimizer.api import ResumeOptimizerAPI
from resume_optimizer.views import OptimizeRequest

async def main():
    api = ResumeOptimizerAPI()

    # 构建请求
    request = OptimizeRequest(
        resume={
            "name": "张三",
            "skills": ["Python", "Java"],
            ...
        },
        job_requirements={
            "title": "后端工程师",
            "required_skills": ["Java"],
            ...
        },
        style="backend",
        output_format="html"
    )

    # 执行优化
    response = await api.optimize_resume(request)

    if response.success:
        print(response.optimized_resume)
        print(response.html_preview)

asyncio.run(main())
```

### 使用 LLM 增强

```python
from resume_optimizer import ResumeOptimizer
from browser_use.llm.service import LLMService

# 传入 LLM 服务
llm_service = LLMService()  # 配置你的 LLM
optimizer = ResumeOptimizer(llm_service)

# 现在优化会使用 LLM 智能增强描述
result = await optimizer.optimize(resume, job, OptimizationStyle.BIG_TECH)
```

## 优化风格说明

| 风格 | 适用场景 | 特点 |
|------|---------|------|
| big_tech | 大型科技公司 | 强调系统设计和量化成果 |
| research | 研究型岗位 | 强调论文和研究成果 |
| product | 产品岗位 | 强调用户思维和数据驱动 |
| algorithm | 算法工程师 | 强调算法能力和竞赛成绩 |
| backend | 后端工程师 | 强调架构和高并发经验 |

## API 端点

### POST /optimize_resume

优化简历接口。

**请求参数**:
```json
{
    "resume": {
        "name": "姓名",
        "email": "邮箱",
        "phone": "电话",
        "skills": ["技能1", "技能2"],
        "experience": [...],
        "projects": [...],
        "education": [...]
    },
    "job_requirements": {
        "title": "岗位名称",
        "company": "公司名称",
        "required_skills": ["必需技能"],
        "preferred_skills": ["优先技能"],
        "responsibilities": ["职责"],
        "qualifications": ["要求"]
    },
    "style": "big_tech",
    "output_format": "html"
}
```

**响应**:
```json
{
    "success": true,
    "optimized_resume": {...},
    "changes": [...],
    "match_score": 85.5,
    "suggestions": [...],
    "html_preview": "<html>...</html>"
}
```

### GET /styles

获取可用的优化风格列表。

### POST /parse_resume

解析简历文件。

**请求参数**:
```json
{
    "file_path": "/path/to/resume.pdf"
}
```

### POST /render_resume

渲染简历为指定格式。

**请求参数**:
```json
{
    "resume_data": {...},
    "output_format": "html",
    "style": "modern"
}
```

## 依赖安装

```bash
# 基础依赖
pip install pydantic

# PDF 解析
pip install PyPDF2

# Word 解析
pip install python-docx

# HTML 解析
pip install beautifulsoup4

# PDF 渲染
pip install weasyprint

# 测试
pip install pytest pytest-asyncio
```

## 测试

```bash
# 运行所有测试
pytest browser_use/resume_optimizer/tests/ -v

# 运行特定测试
pytest browser_use/resume_optimizer/tests/test_optimizer.py -v

# 运行示例
python browser_use/resume_optimizer/examples/example_usage.py
```

## 代码规范

本模块遵循以下规范：

- **类型注解**: 使用现代 Python 3.12+ 语法 (`str | None` 而非 `Optional[str]`)
- **Pydantic 模型**: 所有数据模型使用 Pydantic 进行验证和序列化
- **异步支持**: 核心功能使用 async/await 实现
- **错误处理**: 细化的异常类型，安全的错误信息

## 贡献

本模块是 browser-use 项目的组成部分，用于求职 Agent 的简历优化功能。

## License

MIT License
