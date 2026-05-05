"""
辅助函数
"""

import re
from typing import List, Set
from datetime import datetime


def format_date(date_str: str, input_format: str = None, output_format: str = '%Y-%m') -> str:
    """
    格式化日期字符串

    Args:
        date_str: 原始日期字符串
        input_format: 输入格式
        output_format: 输出格式

    Returns:
        str: 格式化后的日期
    """
    if not date_str:
        return ''

    # 常见日期格式
    formats = [
        '%Y-%m-%d',
        '%Y/%m/%d',
        '%d-%m-%Y',
        '%d/%m/%Y',
        '%m-%Y',
        '%m/%Y',
        '%Y-%m',
        '%Y/%m',
        '%Y',
        '%b %Y',
        '%B %Y',
    ]

    if input_format:
        formats = [input_format] + formats

    for fmt in formats:
        try:
            date_obj = datetime.strptime(date_str.strip(), fmt)
            return date_obj.strftime(output_format)
        except ValueError:
            continue

    return date_str


def sanitize_text(text: str) -> str:
    """
    清理文本内容

    Args:
        text: 原始文本

    Returns:
        str: 清理后的文本
    """
    if not text:
        return ''

    # 移除多余空白
    text = ' '.join(text.split())

    # 移除特殊字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

    return text.strip()


def extract_keywords(text: str, min_length: int = 3) -> Set[str]:
    """
    从文本中提取关键词

    Args:
        text: 文本内容
        min_length: 最小词长

    Returns:
        Set[str]: 关键词集合
    """
    if not text:
        return set()

    # 转换为小写并分割
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())

    # 过滤短词和常见停用词
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
        'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are',
        'were', 'been', 'be', 'have', 'has', 'had', 'do', 'does', 'did',
        'will', 'would', 'could', 'should', 'may', 'might', 'must',
        'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
        'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them'
    }

    keywords = {
        word for word in words
        if len(word) >= min_length and word not in stopwords
    }

    return keywords


def calculate_similarity(text1: str, text2: str) -> float:
    """
    计算两段文本的相似度

    Args:
        text1: 文本1
        text2: 文本2

    Returns:
        float: 相似度分数 (0-1)
    """
    keywords1 = extract_keywords(text1)
    keywords2 = extract_keywords(text2)

    if not keywords1 or not keywords2:
        return 0.0

    intersection = keywords1 & keywords2
    union = keywords1 | keywords2

    return len(intersection) / len(union) if union else 0.0


def truncate_text(text: str, max_length: int, suffix: str = '...') -> str:
    """
    截断文本

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 后缀

    Returns:
        str: 截断后的文本
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def highlight_keywords(text: str, keywords: List[str], tag: str = 'strong') -> str:
    """
    高亮关键词

    Args:
        text: 原始文本
        keywords: 关键词列表
        tag: HTML标签

    Returns:
        str: 高亮后的文本
    """
    for keyword in sorted(keywords, key=len, reverse=True):
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        text = pattern.sub(f'<{tag}>\\g<0></{tag}>', text)

    return text


def parse_duration(duration_str: str) -> dict:
    """
    解析时间段字符串

    Args:
        duration_str: 如 "2020-2022" 或 "2 years"

    Returns:
        dict: 包含 start, end, years 的字典
    """
    result = {'start': None, 'end': None, 'years': None}

    if not duration_str:
        return result

    # 尝试解析 "2020-2022" 格式
    year_range = re.findall(r'(\d{4})\s*[-~至]\s*(\d{4}|present|至今)', duration_str, re.IGNORECASE)
    if year_range:
        result['start'] = year_range[0][0]
        end = year_range[0][1]
        result['end'] = 'Present' if end.lower() in ['present', '至今'] else end
        result['years'] = int(result['end']) - int(result['start']) if result['end'] != 'Present' else None
        return result

    # 尝试解析 "2 years" 格式
    year_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:year|年)', duration_str, re.IGNORECASE)
    if year_match:
        result['years'] = float(year_match.group(1))

    return result


def validate_email(email: str) -> bool:
    """验证邮箱格式"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """验证电话格式"""
    # 支持多种格式
    patterns = [
        r'^\+?1?\d{10,12}$',
        r'^\d{3}-\d{3}-\d{4}$',
        r'^\(\d{3}\)\s?\d{3}-\d{4}$',
        r'^1[3-9]\d{9}$',  # 中国大陆手机
    ]
    return any(re.match(p, phone.replace(' ', '')) for p in patterns)
