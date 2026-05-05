"""
简历优化模块 - Resume Optimizer Module

根据目标岗位对简历进行定向修改，支持多种风格模板。
"""

from .optimizer import ResumeOptimizer
from .styles import (
    BigTechStyle,
    ResearchStyle,
    ProductStyle,
    AlgorithmStyle,
    BackendStyle,
)
from .utils import ResumeParser, TemplateRenderer

__all__ = [
    'ResumeOptimizer',
    'BigTechStyle',
    'ResearchStyle',
    'ProductStyle',
    'AlgorithmStyle',
    'BackendStyle',
    'ResumeParser',
    'TemplateRenderer',
]
