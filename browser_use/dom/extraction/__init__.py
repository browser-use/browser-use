# @file purpose: Content extraction module exports
"""
Content extraction utilities for browser-use.

This module provides SOTA content extraction that preserves structure
and element indices for correlation with browser_state.
"""

from browser_use.dom.extraction.content_extractor import (
	ContentExtractor,
	ExtractedSection,
	ExtractionResult,
	extract_structured_content,
)

__all__ = [
	'ContentExtractor',
	'ExtractedSection',
	'ExtractionResult',
	'extract_structured_content',
]
