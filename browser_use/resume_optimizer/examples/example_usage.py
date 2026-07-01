"""
简历优化模块使用示例

展示如何使用 resume_optimizer 模块进行简历优化。
"""

import sys
from pathlib import Path

# 添加上级目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from resume_optimizer import ResumeOptimizer, BigTechStyle, AlgorithmStyle
from resume_optimizer.optimizer import ResumeData, JobRequirement, OptimizationStyle
from resume_optimizer.api import ResumeOptimizerAPI, OptimizeRequest


def example_basic_usage():
    """基础使用示例"""
    print("=" * 50)
    print("示例 1: 基础使用")
    print("=" * 50)

    # 创建简历数据
    resume = ResumeData(
        name="张三",
        email="zhangsan@example.com",
        phone="13800138000",
        education=[
            {
                "institution": "清华大学",
                "degree": "本科",
                "field": "计算机科学"
            }
        ],
        skills=[
            "Python", "Java", "Machine Learning", "Deep Learning",
            "TensorFlow", "PyTorch", "Docker", "Kubernetes"
        ],
        projects=[
            {
                "name": "智能推荐系统",
                "description": "使用深度学习构建的推荐系统，提升了用户点击率"
            }
        ],
        experience=[
            {
                "company": "某互联网公司",
                "position": "后端工程师",
                "duration": "2021-2023",
                "description": "负责微服务架构设计和开发"
            }
        ],
        summary="热爱技术的全栈工程师"
    )

    # 创建岗位需求
    job = JobRequirement(
        title="高级算法工程师",
        company="字节跳动",
        required_skills=["Machine Learning", "Deep Learning", "Python"],
        preferred_skills=["TensorFlow", "PyTorch", "推荐系统"],
        responsibilities=["构建推荐算法", "优化模型性能"],
        qualifications=["3年以上经验", "计算机相关专业"],
        salary_range="40k-70k",
        location="北京"
    )

    # 创建优化器并执行优化
    optimizer = ResumeOptimizer()
    result = optimizer.optimize(resume, job, OptimizationStyle.ALGORITHM)

    print(f"原始匹配分数: {optimizer._calculate_match_score(resume, job):.1f}%")
    print(f"优化后匹配分数: {result.match_score:.1f}%")
    print(f"优化风格: {result.style.value}")
    print(f"变更数量: {len(result.changes)}")
    print("\n优化建议:")
    for suggestion in result.suggestions:
        print(f"  - {suggestion}")


def example_api_usage():
    """API 使用示例"""
    print("\n" + "=" * 50)
    print("示例 2: API 接口使用")
    print("=" * 50)

    api = ResumeOptimizerAPI()

    # 查看可用的优化风格
    print("\n可用风格:")
    for style in api.get_available_styles():
        print(f"  - {style['name']}: {style['description']}")

    # 构建优化请求
    request = OptimizeRequest(
        resume={
            "name": "李四",
            "email": "lisi@example.com",
            "phone": "13900139000",
            "skills": ["Java", "Spring", "MySQL", "Redis", "Microservices"],
            "experience": [
                {
                    "company": "阿里巴巴",
                    "position": "Java工程师",
                    "duration": "2020-2023",
                    "description": "负责电商系统开发"
                }
            ],
            "projects": [
                {
                    "name": "订单系统",
                    "description": "高并发订单处理系统"
                }
            ]
        },
        job_requirements={
            "title": "高级后端工程师",
            "company": "腾讯",
            "required_skills": ["Java", "Distributed Systems", "High Concurrency"],
            "preferred_skills": ["Spring Cloud", "Kafka", "Elasticsearch"]
        },
        style="backend",
        output_format="html"
    )

    # 执行优化
    response = api.optimize_resume(request)

    if response.success:
        print(f"\n优化成功!")
        print(f"匹配分数: {response.match_score:.1f}%")
        print(f"变更记录:")
        for change in response.changes:
            print(f"  - [{change['type']}] {change.get('description', '')}")

        # 保存 HTML 预览
        if response.html_preview:
            output_path = Path("optimized_resume_preview.html")
            output_path.write_text(response.html_preview, encoding='utf-8')
            print(f"\nHTML 预览已保存到: {output_path.absolute()}")
    else:
        print(f"优化失败: {response.error_message}")


def example_style_usage():
    """不同风格优化示例"""
    print("\n" + "=" * 50)
    print("示例 3: 不同风格优化对比")
    print("=" * 50)

    resume_data = {
        "name": "王五",
        "skills": ["Python", "Research", "Deep Learning", "NLP"],
        "projects": [
            {
                "name": "BERT改进模型",
                "description": "提出了新的预训练方法"
            }
        ]
    }

    job_requirements = {
        "title": "NLP研究员",
        "required_skills": ["NLP", "Deep Learning", "Python"],
        "preferred_skills": ["PyTorch", "Transformer", "Paper Writing"]
    }

    styles = ["big_tech", "research", "algorithm"]

    for style_name in styles:
        print(f"\n--- {style_name} 风格 ---")

        request = OptimizeRequest(
            resume=resume_data,
            job_requirements=job_requirements,
            style=style_name
        )

        api = ResumeOptimizerAPI()
        response = api.optimize_resume(request)

        if response.success:
            print(f"匹配分数: {response.match_score:.1f}%")
            print(f"建议: {response.suggestions}")


def example_render_usage():
    """渲染示例"""
    print("\n" + "=" * 50)
    print("示例 4: 简历渲染")
    print("=" * 50)

    resume_data = {
        "name": "赵六",
        "email": "zhaoliu@example.com",
        "phone": "13700137000",
        "summary": "资深全栈工程师，专注于高并发系统",
        "skills": ["Python", "Go", "Kubernetes", "Microservices"],
        "experience": [
            {
                "company": "美团",
                "position": "高级工程师",
                "duration": "2019-2023",
                "description": "负责外卖系统架构升级"
            }
        ],
        "education": [
            {
                "institution": "北京大学",
                "degree": "硕士",
                "field": "软件工程"
            }
        ]
    }

    api = ResumeOptimizerAPI()

    # 渲染为 Markdown
    result = api.render_resume(resume_data, output_format='markdown')
    if result['success']:
        print("\nMarkdown 输出:")
        print(result['content'][:500] + "...")


if __name__ == "__main__":
    example_basic_usage()
    example_api_usage()
    example_style_usage()
    example_render_usage()

    print("\n" + "=" * 50)
    print("所有示例运行完成!")
    print("=" * 50)
