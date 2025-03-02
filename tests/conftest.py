"""
Test configuration for browser-use.
"""

import logging
import os
import sys

import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

# Ensure the project root is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext


@pytest.fixture(scope='session')
def llm():
	"""
	Fixture to provide a ChatOpenAI instance or a mock for testing.
	Uses a mock if OPENAI_API_KEY is not set.
	"""
	api_key = os.getenv('OPENAI_API_KEY')
	logger.debug(f'API Key present: {bool(api_key)}')
	logger.debug('Using actual ChatOpenAI model')
	return ChatOpenAI(model='gpt-4o', api_key=SecretStr(api_key) if api_key else None)


@pytest.fixture(scope='session')
def browser():
	"""
	Fixture to provide a Browser instance for testing.
	"""
	logger.debug('Creating Browser instance for testing')
	return Browser(config=BrowserConfig(headless=True, disable_security=True))


@pytest.fixture(scope='function')
async def browser_context(browser):
	"""
	Fixture to provide a BrowserContext instance for testing.
	"""
	logger.debug('Creating BrowserContext instance for testing')
	context = BrowserContext(browser=browser)
	yield context
	await context.close()
