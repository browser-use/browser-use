"""
OCI Raw API integration for browser-use.

This module provides direct integration with Oracle Cloud Infrastructure's
Generative AI service using the raw API endpoints, without Langchain dependencies.
"""

from .chat import ChatOCIRaw

__all__ = ['ChatOCIRaw']
