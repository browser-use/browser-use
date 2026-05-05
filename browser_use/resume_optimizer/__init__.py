"""
简历优化模块 - Resume Optimizer Module

根据目标岗位对简历进行定向修改，支持多种风格模板。

基本使用:
    from resume_optimizer import ResumeOptimizerAPI

    api = ResumeOptimizerAPI()

    # 解析简历
    result = api.parse_resume("/path/to/resume.pdf")

    # 优化简历
    request = OptimizeRequest(
        resume=result.data,
        job_requirements={...},
        style="big_tech"
    )
    response = await api.optimize_resume(request)
"""

from .views import (
    ResumeData,
    JobRequirement,
    Education,
    Experience,
    Project,
    Publication,
    Competition,
    OptimizationResult,
    OptimizationChange,
    OptimizeRequest,
    OptimizeResponse,
    ParseResult,
    RenderResult,
    StyleInfo,
)
from .optimizer import ResumeOptimizer, OptimizationStyle
from .api import ResumeOptimizerAPI

__version__ = "0.1.0"

__all__ = [
    # 核心类
    "ResumeOptimizer",
    "ResumeOptimizerAPI",
    "OptimizationStyle",
    # 数据模型
    "ResumeData",
    "JobRequirement",
    "Education",
    "Experience",
    "Project",
    "Publication",
    "Competition",
    "OptimizationResult",
    "OptimizationChange",
    # 请求/响应
    "OptimizeRequest",
    "OptimizeResponse",
    "ParseResult",
    "RenderResult",
    "StyleInfo",
]
