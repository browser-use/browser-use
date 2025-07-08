def normalize_url(url: str) -> str:
	"""
	Normalize a URL by adding https:// protocol if needed, while preserving special URLs.

	This function safely adds https:// to URLs that lack a protocol, but preserves
	special URLs like "about:blank", "chrome://new-tab-page", "mailto:...", "tel:...", etc.
	that should not be prefixed with https://.

	Args:
	    url: The URL string to normalize

	Returns:
	    str: The normalized URL with protocol if needed

	Examples:
	    >>> normalize_url('example.com')
	    'https://example.com'
	    >>> normalize_url('about:blank')
	    'about:blank'
	    >>> normalize_url('mailto:test@example.com')
	    'mailto:test@example.com'
	    >>> normalize_url('https://example.com')
	    'https://example.com'
	"""
	normalized_url = url.strip()

	# If URL already has a protocol, return as-is
	if '://' in normalized_url:
		return normalized_url

	# Check for special protocols that should not be prefixed with https://
	special_protocols = ['about:', 'mailto:', 'tel:', 'ftp:', 'file:', 'data:', 'javascript:']
	for protocol in special_protocols:
		if normalized_url.startswith(protocol):
			return normalized_url

	# For everything else, add https://
	return f'https://{normalized_url}'
