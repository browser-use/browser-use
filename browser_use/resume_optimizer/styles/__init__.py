"""
简历风格优化策略

提供不同风格的简历优化实现：
- BigTechStyle: 大厂风格
- ResearchStyle: 科研风格
- ProductStyle: 产品风格
- AlgorithmStyle: 算法岗风格
- BackendStyle: 后端岗风格
"""

from .big_tech import BigTechStyle
from .research import ResearchStyle
from .product import ProductStyle
from .algorithm import AlgorithmStyle
from .backend import BackendStyle

__all__ = [
    'BigTechStyle',
    'ResearchStyle',
    'ProductStyle',
    'AlgorithmStyle',
    'BackendStyle',
]
