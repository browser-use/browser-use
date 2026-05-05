# 简历优化模块 (Resume Optimizer)

基于 browser-use 的简历优化模块，为求职 Agent 提供简历定向优化能力。

## 功能特性

- **多种优化风格**: 支持大厂风、科研风、产品风、算法岗风、后端岗风
- **智能匹配**: 根据岗位需求计算匹配分数
- **模板渲染**: 支持 HTML、Markdown、PDF 多种输出格式
- **API 接口**: 提供与后端编排层对接的统一接口
- **简历解析**: 支持 PDF、Word、Markdown、HTML 多种输入格式

## 项目结构

```
resume_optimizer/
├── __init__.py          # 模块初始化
├── optimizer.py         # 核心优化逻辑
├── api.py              # API 接口
├── styles/             # 风格优化器
│   ├── __init__.py
│   ├── base.py         # 风格基类
│   ├── big_tech.py     # 大厂风格
│   ├── research.py     # 科研风格
│   ├── product.py      # 产品风格
│   ├── algorithm.py    # 算法岗风格
│   └── backend.py      # 后端岗风格
├── utils/              # 工具函数
│   ├── __init__.py
│   ├── parser.py       # 简历解析器
│   ├── renderer.py     # 模板渲染器
│   └── helpers.py      # 辅助函数
├── templates/          # 简历模板
│   ├── modern.html     # 现代风格
│   └── classic.html    # 经典风格
└── examples/           # 使用示例
    └── example_usage.py
```

## 快速开始

### 基础使用

```python
from resume_optimizer import ResumeOptimizer
from resume_optimizer.optimizer import ResumeData, JobRequirement, OptimizationStyle

# 创建简历数据
resume = ResumeData(
    name="张三",
    email="zhangsan@example.com",
    phone="13800138000",
    education=[{"institution": "清华大学", "degree": "本科", "field": "CS"}],
    skills=["Python", "Machine Learning", "TensorFlow"],
    projects=[{"name": "推荐系统", "description": "深度学习推荐"}],
    experience=[]
)

# 创建岗位需求
job = JobRequirement(
    title="算法工程师",
    company="字节跳动",
    required_skills=["Machine Learning", "Python"],
    preferred_skills=["TensorFlow", "Deep Learning"],
    responsibilities=["构建推荐算法"],
    qualifications=["3年以上经验"]
)

# 优化简历
optimizer = ResumeOptimizer()
result = optimizer.optimize(resume, job, OptimizationStyle.ALGORITHM)

print(f"匹配分数: {result.match_score}%")
print(f"优化建议: {result.suggestions}")
```

### API 接口使用

```python
from resume_optimizer.api import ResumeOptimizerAPI, OptimizeRequest

api = ResumeOptimizerAPI()

# 构建请求
request = OptimizeRequest(
    resume={"name": "张三", "skills": ["Python", "Java"], ...},
    job_requirements={"title": "后端工程师", "required_skills": ["Java"], ...},
    style="backend",  # big_tech, research, product, algorithm, backend
    output_format="html"
)

# 执行优化
response = api.optimize_resume(request)

if response.success:
    print(response.optimized_resume)
    print(response.html_preview)  # HTML 预览
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
pip install PyPDF2 python-docx beautifulsoup4 weasyprint
```

## 测试

```bash
python examples/example_usage.py
```

## 贡献

本模块是 browser-use 项目的组成部分，用于求职 Agent 的简历优化功能。

## License

MIT License
