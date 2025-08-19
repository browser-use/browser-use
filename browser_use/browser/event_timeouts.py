"""Typed configuration for overriding per-event timeouts.

This module exposes a single Pydantic model, EventTimeouts, that lets callers
override the `event_timeout` on events defined in `browser_use.browser.events`.

Usage:
    from browser_use.browser.event_timeouts import EventTimeouts

    timeouts = EventTimeouts(type_text_timeout=30.0)
    session = BrowserSession(cdp_url=..., event_timeouts=timeouts)
"""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field

# Import event classes to get their defaults and map names
from . import events as evt


class EventTimeouts(BaseModel):
    """Typed set of optional timeout overrides for all known events.

    None means "use the event's built-in default". A float overrides it.
    """

    # High-level browser actions
    navigate_to_url_timeout: Optional[float] = Field(default=None)
    click_element_timeout: Optional[float] = Field(default=None)
    type_text_timeout: Optional[float] = Field(default=None)
    scroll_timeout: Optional[float] = Field(default=None)
    switch_tab_timeout: Optional[float] = Field(default=None)
    close_tab_timeout: Optional[float] = Field(default=None)
    screenshot_timeout: Optional[float] = Field(default=None)
    browser_state_request_timeout: Optional[float] = Field(default=None)
    go_back_timeout: Optional[float] = Field(default=None)
    go_forward_timeout: Optional[float] = Field(default=None)
    refresh_timeout: Optional[float] = Field(default=None)
    wait_timeout: Optional[float] = Field(default=None)
    send_keys_timeout: Optional[float] = Field(default=None)
    upload_file_timeout: Optional[float] = Field(default=None)
    get_dropdown_options_timeout: Optional[float] = Field(default=None)
    select_dropdown_option_timeout: Optional[float] = Field(default=None)
    scroll_to_text_timeout: Optional[float] = Field(default=None)

    # Browser lifecycle
    browser_start_timeout: Optional[float] = Field(default=None)
    browser_stop_timeout: Optional[float] = Field(default=None)
    browser_launch_timeout: Optional[float] = Field(default=None)
    browser_kill_timeout: Optional[float] = Field(default=None)

    # DOM / Navigation / Tabs
    browser_connected_timeout: Optional[float] = Field(default=None)
    browser_stopped_timeout: Optional[float] = Field(default=None)
    browser_error_timeout: Optional[float] = Field(default=None)
    tab_created_timeout: Optional[float] = Field(default=None)
    tab_closed_timeout: Optional[float] = Field(default=None)
    agent_focus_changed_timeout: Optional[float] = Field(default=None)
    target_crashed_timeout: Optional[float] = Field(default=None)
    navigation_started_timeout: Optional[float] = Field(default=None)
    navigation_complete_timeout: Optional[float] = Field(default=None)

    # Storage state
    save_storage_state_timeout: Optional[float] = Field(default=None)
    storage_state_saved_timeout: Optional[float] = Field(default=None)
    load_storage_state_timeout: Optional[float] = Field(default=None)
    storage_state_loaded_timeout: Optional[float] = Field(default=None)

    # File downloads
    file_downloaded_timeout: Optional[float] = Field(default=None)

    def as_overrides_by_event_class(self) -> Dict[str, float]:
        """Return only the non-None overrides keyed by event class name.

        Example: { 'TypeTextEvent': 30.0 }
        """
        result: Dict[str, float] = {}
        for field_name, value in self.model_dump().items():
            if value is None:
                continue
            event_class = _FIELD_TO_EVENT_CLASS.get(field_name)
            if event_class is not None:
                result[event_class] = float(value)
        return result

    @classmethod
    def defaults(cls) -> "EventTimeouts":
        """Build an EventTimeouts with all fields set to the event defaults.

        This is useful to present current effective values to callers.
        """
        return cls(
            navigate_to_url_timeout=_get_default(evt.NavigateToUrlEvent),
            click_element_timeout=_get_default(evt.ClickElementEvent),
            type_text_timeout=_get_default(evt.TypeTextEvent),
            scroll_timeout=_get_default(evt.ScrollEvent),
            switch_tab_timeout=_get_default(evt.SwitchTabEvent),
            close_tab_timeout=_get_default(evt.CloseTabEvent),
            screenshot_timeout=_get_default(evt.ScreenshotEvent),
            browser_state_request_timeout=_get_default(evt.BrowserStateRequestEvent),
            go_back_timeout=_get_default(evt.GoBackEvent),
            go_forward_timeout=_get_default(evt.GoForwardEvent),
            refresh_timeout=_get_default(evt.RefreshEvent),
            wait_timeout=_get_default(evt.WaitEvent),
            send_keys_timeout=_get_default(evt.SendKeysEvent),
            upload_file_timeout=_get_default(evt.UploadFileEvent),
            get_dropdown_options_timeout=_get_default(evt.GetDropdownOptionsEvent),
            select_dropdown_option_timeout=_get_default(evt.SelectDropdownOptionEvent),
            scroll_to_text_timeout=_get_default(evt.ScrollToTextEvent),
            browser_start_timeout=_get_default(evt.BrowserStartEvent),
            browser_stop_timeout=_get_default(evt.BrowserStopEvent),
            browser_launch_timeout=_get_default(evt.BrowserLaunchEvent),
            browser_kill_timeout=_get_default(evt.BrowserKillEvent),
            browser_connected_timeout=_get_default(evt.BrowserConnectedEvent),
            browser_stopped_timeout=_get_default(evt.BrowserStoppedEvent),
            browser_error_timeout=_get_default(evt.BrowserErrorEvent),
            tab_created_timeout=_get_default(evt.TabCreatedEvent),
            tab_closed_timeout=_get_default(evt.TabClosedEvent),
            agent_focus_changed_timeout=_get_default(evt.AgentFocusChangedEvent),
            target_crashed_timeout=_get_default(evt.TargetCrashedEvent),
            navigation_started_timeout=_get_default(evt.NavigationStartedEvent),
            navigation_complete_timeout=_get_default(evt.NavigationCompleteEvent),
            save_storage_state_timeout=_get_default(evt.SaveStorageStateEvent),
            storage_state_saved_timeout=_get_default(evt.StorageStateSavedEvent),
            load_storage_state_timeout=_get_default(evt.LoadStorageStateEvent),
            storage_state_loaded_timeout=_get_default(evt.StorageStateLoadedEvent),
            file_downloaded_timeout=_get_default(evt.FileDownloadedEvent),
        )

    def resolved_timeout_for_event_class(self, event_class_name: str) -> Optional[float]:
        """Return the override if set, else the event class default if known."""
        # First check overrides
        overrides = self.as_overrides_by_event_class()
        if event_class_name in overrides:
            return overrides[event_class_name]
        # Fall back to event defaults if we have a mapping
        event_cls = _EVENT_CLASS_BY_NAME.get(event_class_name)
        if event_cls is None:
            return None
        return _get_default(event_cls)

    def merged_with_defaults(self) -> "EventTimeouts":
        """Return a copy where each field is set to override or default value.

        This is handy for exposing the current effective configuration.
        """
        defaults = self.defaults()
        data = defaults.model_dump()
        for k, v in self.model_dump().items():
            if v is not None:
                data[k] = v
        return EventTimeouts(**data)


def _get_default(event_cls: type) -> Optional[float]:
    return getattr(event_cls, 'event_timeout', None)


_FIELD_TO_EVENT_CLASS: Dict[str, str] = {
    # High-level actions
    'navigate_to_url_timeout': 'NavigateToUrlEvent',
    'click_element_timeout': 'ClickElementEvent',
    'type_text_timeout': 'TypeTextEvent',
    'scroll_timeout': 'ScrollEvent',
    'switch_tab_timeout': 'SwitchTabEvent',
    'close_tab_timeout': 'CloseTabEvent',
    'screenshot_timeout': 'ScreenshotEvent',
    'browser_state_request_timeout': 'BrowserStateRequestEvent',
    'go_back_timeout': 'GoBackEvent',
    'go_forward_timeout': 'GoForwardEvent',
    'refresh_timeout': 'RefreshEvent',
    'wait_timeout': 'WaitEvent',
    'send_keys_timeout': 'SendKeysEvent',
    'upload_file_timeout': 'UploadFileEvent',
    'get_dropdown_options_timeout': 'GetDropdownOptionsEvent',
    'select_dropdown_option_timeout': 'SelectDropdownOptionEvent',
    'scroll_to_text_timeout': 'ScrollToTextEvent',
    # Lifecycle
    'browser_start_timeout': 'BrowserStartEvent',
    'browser_stop_timeout': 'BrowserStopEvent',
    'browser_launch_timeout': 'BrowserLaunchEvent',
    'browser_kill_timeout': 'BrowserKillEvent',
    # DOM / Tabs / Navigation
    'browser_connected_timeout': 'BrowserConnectedEvent',
    'browser_stopped_timeout': 'BrowserStoppedEvent',
    'browser_error_timeout': 'BrowserErrorEvent',
    'tab_created_timeout': 'TabCreatedEvent',
    'tab_closed_timeout': 'TabClosedEvent',
    'agent_focus_changed_timeout': 'AgentFocusChangedEvent',
    'target_crashed_timeout': 'TargetCrashedEvent',
    'navigation_started_timeout': 'NavigationStartedEvent',
    'navigation_complete_timeout': 'NavigationCompleteEvent',
    # Storage
    'save_storage_state_timeout': 'SaveStorageStateEvent',
    'storage_state_saved_timeout': 'StorageStateSavedEvent',
    'load_storage_state_timeout': 'LoadStorageStateEvent',
    'storage_state_loaded_timeout': 'StorageStateLoadedEvent',
    # Downloads
    'file_downloaded_timeout': 'FileDownloadedEvent',
}


_EVENT_CLASS_BY_NAME = {name: getattr(evt, name) for name in _FIELD_TO_EVENT_CLASS.values()}
