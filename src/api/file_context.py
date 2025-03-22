from typing import Any


def convert_file_context(file_meta: list[dict[str, Any]], content: str) -> str | None:
    file_context = ""
    for fl in file_meta:
        file_context += f"url: {fl['source_url']}\n"
        # todo this content is temporary, need to be replaced by the real content by fetch from the file_url or by file_id
        file_context += f"content: {fl['content'][:5000]}\n"
    return file_context
