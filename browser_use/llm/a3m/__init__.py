"""
A3M Router integration for browser-use.

Usage:
    from browser_use import Agent
    from browser_use.llm.a3m import ChatA3M

    agent = Agent(
        task="Fill out this job application form",
        llm=ChatA3M(model="auto", stealth=True),
    )
"""

from browser_use.llm.a3m.chat import ChatA3M

__all__ = ['ChatA3M']
