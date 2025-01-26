import logging
import os
import pytest

from browser_use.logging_config import setup_logging

class TestLoggingConfig:
    """Test class for logging configuration."""

    def test_setup_logging_debug_level(self, monkeypatch):
        """
        Test that setup_logging correctly sets the debug level when
        BROWSER_USE_LOGGING_LEVEL is set to 'debug'.
        """
        # Mock the environment variable
        monkeypatch.setenv('BROWSER_USE_LOGGING_LEVEL', 'debug')

        # Clear any existing logging configuration
        logging.getLogger().handlers.clear()

        # Run the setup_logging function
        setup_logging()

        # Check that the root logger is set to DEBUG level
        assert logging.getLogger().level == logging.DEBUG

        # Check that the browser_use logger is set to DEBUG level
        browser_use_logger = logging.getLogger('browser_use')
        assert browser_use_logger.level == logging.DEBUG

        # Check that the formatter is correctly set
        handler = browser_use_logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.formatter._fmt == '%(levelname)-8s [%(name)s] %(message)s'

        # Check that third-party loggers are set to ERROR level
        for logger_name in ['WDM', 'httpx', 'selenium', 'playwright']:
            logger = logging.getLogger(logger_name)
            assert logger.level == logging.ERROR
            assert not logger.propagate