"""
简历优化 API 接口

为后端编排层提供统一的 API 接口。
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import json

from .optimizer import ResumeOptimizer, ResumeData, JobRequirement, OptimizationStyle, OptimizationResult
from .utils import ResumeParser, TemplateRenderer


@dataclass
class OptimizeRequest:
    """优化请求"""
    resume: Dict[str, Any]
    job_requirements: Dict[str, Any]
    style: str = "big_tech"  # big_tech, research, product, algorithm, backend
    output_format: str = "html"  # html, markdown, pdf, json


@dataclass
class OptimizeResponse:
    """优化响应"""
    success: bool
    optimized_resume: Optional[Dict[str, Any]] = None
    changes: Optional[List[Dict[str, Any]]] = None
    match_score: Optional[float] = None
    suggestions: Optional[List[str]] = None
    html_preview: Optional[str] = None
    error_message: Optional[str] = None


class ResumeOptimizerAPI:
    """
    简历优化 API

    提供与后端编排层对接的接口。
    """

    def __init__(self):
        self.optimizer = ResumeOptimizer()
        self.parser = ResumeParser()
        self.renderer = TemplateRenderer()

    def optimize_resume(self, request: OptimizeRequest) -> OptimizeResponse:
        """
        优化简历

        Args:
            request: 优化请求

        Returns:
            OptimizeResponse: 优化响应
        """
        try:
            # 解析风格
            style_map = {
                'big_tech': OptimizationStyle.BIG_TECH,
                'research': OptimizationStyle.RESEARCH,
                'product': OptimizationStyle.PRODUCT,
                'algorithm': OptimizationStyle.ALGORITHM,
                'backend': OptimizationStyle.BACKEND,
            }
            style = style_map.get(request.style, OptimizationStyle.BIG_TECH)

            # 构建简历数据
            resume_data = self._dict_to_resume_data(request.resume)

            # 构建岗位需求
            job_requirement = self._dict_to_job_requirement(request.job_requirements)

            # 执行优化
            result = self.optimizer.optimize(resume_data, job_requirement, style)

            # 生成预览
            optimized_dict = self._resume_data_to_dict(result.optimized_resume)
            html_preview = self.renderer.render_to_html(optimized_dict)

            return OptimizeResponse(
                success=True,
                optimized_resume=optimized_dict,
                changes=result.changes,
                match_score=result.match_score,
                suggestions=result.suggestions,
                html_preview=html_preview
            )

        except Exception as e:
            return OptimizeResponse(
                success=False,
                error_message=str(e)
            )

    def parse_resume(self, file_path: str) -> Dict[str, Any]:
        """
        解析简历文件

        Args:
            file_path: 文件路径

        Returns:
            Dict: 解析结果
        """
        try:
            parsed = self.parser.parse(file_path)
            return {
                'success': True,
                'data': self.parser.to_json(parsed)
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def render_resume(
        self,
        resume_data: Dict[str, Any],
        output_format: str = 'html',
        output_path: Optional[str] = None,
        style: str = 'modern'
    ) -> Dict[str, Any]:
        """
        渲染简历

        Args:
            resume_data: 简历数据
            output_format: 输出格式 (html, markdown, pdf)
            output_path: 输出路径
            style: 模板风格

        Returns:
            Dict: 渲染结果
        """
        try:
            if output_format == 'html':
                content = self.renderer.render_to_html(resume_data, style, output_path)
                return {'success': True, 'content': content, 'format': 'html'}

            elif output_format == 'markdown':
                content = self.renderer.render_to_markdown(resume_data, output_path)
                return {'success': True, 'content': content, 'format': 'markdown'}

            elif output_format == 'pdf':
                content = self.renderer.render_to_pdf(resume_data, style, output_path)
                return {'success': True, 'content': content, 'format': 'pdf'}

            else:
                return {'success': False, 'error': f'不支持的格式: {output_format}'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def preview_changes(
        self,
        original: Dict[str, Any],
        optimized: Dict[str, Any],
        changes: List[Dict[str, Any]]
    ) -> str:
        """
        预览变更

        Args:
            original: 原始简历
            optimized: 优化后的简历
            changes: 变更记录

        Returns:
            str: HTML预览
        """
        return self.renderer.preview_changes(original, optimized, changes)

    def get_available_styles(self) -> List[Dict[str, str]]:
        """
        获取可用的优化风格

        Returns:
            List[Dict]: 风格列表
        """
        return [
            {
                'id': 'big_tech',
                'name': '大厂风格',
                'description': '强调技术深度、系统设计和量化成果，适合申请大型科技公司',
                'keywords': ['系统设计', '分布式', '高并发', '性能优化']
            },
            {
                'id': 'research',
                'name': '科研风格',
                'description': '强调论文发表、研究成果和创新性，适合申请研究型岗位',
                'keywords': ['论文', '研究', '算法', '创新']
            },
            {
                'id': 'product',
                'name': '产品风格',
                'description': '强调用户思维和数据驱动，适合申请产品相关岗位',
                'keywords': ['用户', '数据', '产品', '迭代']
            },
            {
                'id': 'algorithm',
                'name': '算法岗风格',
                'description': '强调算法能力和模型优化，适合申请算法工程师岗位',
                'keywords': ['机器学习', '深度学习', '竞赛', '模型']
            },
            {
                'id': 'backend',
                'name': '后端岗风格',
                'description': '强调系统架构和高可用，适合申请后端工程师岗位',
                'keywords': ['微服务', '数据库', '缓存', '架构']
            }
        ]

    def _dict_to_resume_data(self, data: Dict[str, Any]) -> ResumeData:
        """字典转 ResumeData"""
        return ResumeData(
            name=data.get('name', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            education=data.get('education', []),
            skills=data.get('skills', []),
            projects=data.get('projects', []),
            experience=data.get('experience', []),
            summary=data.get('summary')
        )

    def _dict_to_job_requirement(self, data: Dict[str, Any]) -> JobRequirement:
        """字典转 JobRequirement"""
        return JobRequirement(
            title=data.get('title', ''),
            company=data.get('company', ''),
            required_skills=data.get('required_skills', []),
            preferred_skills=data.get('preferred_skills', []),
            responsibilities=data.get('responsibilities', []),
            qualifications=data.get('qualifications', []),
            salary_range=data.get('salary_range'),
            location=data.get('location')
        )

    def _resume_data_to_dict(self, resume_data: ResumeData) -> Dict[str, Any]:
        """ResumeData 转字典"""
        return {
            'name': resume_data.name,
            'email': resume_data.email,
            'phone': resume_data.phone,
            'education': resume_data.education,
            'skills': resume_data.skills,
            'projects': resume_data.projects,
            'experience': resume_data.experience,
            'summary': resume_data.summary
        }


# 创建全局 API 实例
api = ResumeOptimizerAPI()


def optimize_resume_endpoint(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    优化简历端点 (供后端调用)

    Args:
        request_data: {
            'resume': {...},  # 简历数据
            'job_requirements': {...},  # 岗位需求
            'style': 'big_tech',  # 可选
            'output_format': 'html'  # 可选
        }

    Returns:
        Dict: 优化结果
    """
    request = OptimizeRequest(
        resume=request_data.get('resume', {}),
        job_requirements=request_data.get('job_requirements', {}),
        style=request_data.get('style', 'big_tech'),
        output_format=request_data.get('output_format', 'html')
    )

    response = api.optimize_resume(request)
    return asdict(response)


def get_styles_endpoint() -> List[Dict[str, str]]:
    """获取可用风格端点"""
    return api.get_available_styles()


def parse_resume_endpoint(file_path: str) -> Dict[str, Any]:
    """解析简历端点"""
    return api.parse_resume(file_path)


def render_resume_endpoint(
    resume_data: Dict[str, Any],
    output_format: str = 'html',
    output_path: Optional[str] = None,
    style: str = 'modern'
) -> Dict[str, Any]:
    """渲染简历端点"""
    return api.render_resume(resume_data, output_format, output_path, style)
