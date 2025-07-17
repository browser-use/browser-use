def cap_text_length(text: str, max_length: int) -> str:
	"""Cap text length for display."""
	if len(text) <= max_length:
		return text
	return text[:max_length] + '...'
