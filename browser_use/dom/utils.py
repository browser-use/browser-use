def cap_text_length(text: str, max_length: int) -> str:
	if len(text) > max_length:
		return text[:max_length] + '...'
	return text
