"""
Taskmarket integration for browser-use.

Usage:
    from browser_use import Tools
    from browser_use.integrations.taskmarket import register_taskmarket_actions

    tools = Tools()
    register_taskmarket_actions(tools)

The create action uses the first-party ``taskmarket`` CLI and requires a previously
prepared preview plus host-side user authorization via ``TaskMarketService.authorize_preview``
or an authorization callback. Status and submission actions are read-only and no
accept/reject/payment review actions are registered.
"""

from .actions import register_taskmarket_actions
from .service import TaskMarketPreview, TaskMarketService, TaskMarketTaskDraft

__all__ = ['TaskMarketPreview', 'TaskMarketService', 'TaskMarketTaskDraft', 'register_taskmarket_actions']
