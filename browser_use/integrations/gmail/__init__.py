"""
Gmail Integration for Browser Use
Provides Gmail API integration for email reading and verification code extraction.
This integration enables agents to read email content and extract verification codes themselves.
Usage:
    from browser_use.integrations.gmail import GmailService, register_gmail_actions
    # Option 1: Register Gmail actions with file-based authentication
    controller = Controller()
    register_gmail_actions(controller)
    # Option 2: Register Gmail actions with direct access token (recommended for production)
    controller = Controller()
    register_gmail_actions(controller, access_token="your_access_token_here")
    # Option 3: Use the service directly
    gmail = GmailService(access_token="your_access_token_here")
    await gmail.authenticate()
    emails = await gmail.get_recent_emails()
"""

# @file purpose: Gmail integration for 2FA email authentication and email reading

from .actions import register_gmail_actions
from .service import GmailService

__all__ = ['GmailService', 'register_gmail_actions']
