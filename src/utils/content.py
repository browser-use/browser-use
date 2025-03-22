import json
import logging


def list_dict_to_markdown(data: list[dict]) -> str:
    if not data or not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        return "No data or invalid format"
    
    # 使用第一个字典的键顺序作为基准，然后添加其他字典中的键
    headers = list(data[0].keys())
    for item in data[1:]:
        for key in item.keys():
            if key not in headers:
                headers.append(key)
    
    # 创建 Markdown 表格
    markdown = []
    
    # 添加表头
    markdown.append("| " + " | ".join(headers) + " |")
    # 添加分隔行
    markdown.append("| " + " | ".join(["---"] * len(headers)) + " |")
    
    # 添加数据行
    for item in data:
        row = []
        for header in headers:
            # 获取值，如果不存在则用空字符串替代
            value = str(item.get(header, "")).replace("|", "\\|")  # 转义管道符
            # 处理多行文本
            value = value.replace("\n", "<br>")
            row.append(value)
        markdown.append("| " + " | ".join(row) + " |")
    
    return "\n".join(markdown)

def check_valid_json(content: str) -> bool:
    try:
        json_data = json.loads(content)
        return True
    except json.decoder.JSONDecodeError as e:
        logging.info(f"Content {content} is invalid {str(e)}")
        return False