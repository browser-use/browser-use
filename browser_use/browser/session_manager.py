"""Event-driven CDP session management.

Manages CDP sessions by listening to Target.attachedToTarget and Target.detachedFromTarget
events, ensuring the session pool always reflects the current browser state.
"""

import asyncio
from typing import TYPE_CHECKING

from cdp_use.cdp.target import AttachedToTargetEvent, DetachedFromTargetEvent, SessionID, TargetID

from browser_use.utils import create_task_with_error_handling

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession, CDPSession, Target


class SessionManager:
	"""Event-driven CDP session manager.

	Automatically synchronizes the CDP session pool with browser state via CDP events.

	Key features:
	- Sessions added/removed automatically via Target attach/detach events
	- Multiple sessions can attach to the same target
	- Targets only removed when ALL sessions detach
	- No stale sessions - pool always reflects browser reality

	SessionManager is the SINGLE SOURCE OF TRUTH for all targets and sessions.
	"""

	def __init__(self, browser_session: 'BrowserSession'):
		self.browser_session = browser_session
		self.logger = browser_session.logger

		# All targets (entities: pages, iframes, workers)
		self._targets: dict[TargetID, 'Target'] = {}

		# All sessions (communication channels)
		self._sessions: dict[SessionID, 'CDPSession'] = {}

		# Mapping: target -> sessions attached to it
		self._target_sessions: dict[TargetID, set[SessionID]] = {}

		# Reverse mapping: session -> target it belongs to
		self._session_to_target: dict[SessionID, TargetID] = {}

		self._lock = asyncio.Lock()
		self._recovery_lock = asyncio.Lock()

		# Focus recovery coordination - event-driven instead of polling
		self._recovery_in_progress: bool = False
		self._recovery_complete_event: asyncio.Event | None = None
		self._recovery_task: asyncio.Task | None = None

	async def start_monitoring(self) -> None:
		"""Start monitoring Target attach/detach events.

		Registers CDP event handlers to keep the session pool synchronized with browser state.
		Also discovers and initializes all existing targets on startup.
		"""
		if not self.browser_session._cdp_client_root:
			raise RuntimeError('CDP client not initialized')

		# Capture cdp_client_root in closure to avoid type errors
		cdp_client = self.browser_session._cdp_client_root

		# Enable target discovery to receive targetInfoChanged events automatically
		# This eliminates the need for getTargetInfo() polling calls
		await cdp_client.send.Target.setDiscoverTargets(
			params={'discover': True, 'filter': [{'type': 'page'}, {'type': 'iframe'}]}
		)

		# Register synchronous event handlers (CDP requirement)
		def on_attached(event: AttachedToTargetEvent, session_id: SessionID | None = None):
			# _handle_target_attached() handles:
			# - setAutoAttach for children
			# - Create CDPSession
			# - Enable monitoring (for pages/tabs)
			# - Add to pool
			create_task_with_error_handling(
				self._handle_target_attached(event),
				name='handle_target_attached',
				logger_instance=self.logger,
				suppress_exceptions=True,
			)

		def on_detached(event: DetachedFromTargetEvent, session_id: SessionID | None = None):
			create_task_with_error_handling(
				self._handle_target_detached(event),
				name='handle_target_detached',
				logger_instance=self.logger,
				suppress_exceptions=True,
			)

		def on_target_info_changed(event, session_id: SessionID | None = None):
			# Update session info from targetInfoChanged events (no polling needed!)
			create_task_with_error_handling(
				self._handle_target_info_changed(event),
				name='handle_target_info_changed',
				logger_instance=self.logger,
				suppress_exceptions=True,
			)

		cdp_client.register.Target.attachedToTarget(on_attached)
		cdp_client.register.Target.detachedFromTarget(on_detached)
		cdp_client.register.Target.targetInfoChanged(on_target_info_changed)

		self.logger.debug('[SessionManager] Event monitoring started')

		# Discover and initialize ALL existing targets
		await self._initialize_existing_targets()

	def _get_session_for_target(self, target_id: TargetID) -> 'CDPSession | None':
		"""Internal: Get ANY valid session for a target (picks first available).

		⚠️ INTERNAL API - Use browser_session.get_or_create_cdp_session() instead!
		This method has no validation, no focus management, no recovery.

		Args:
			target_id: Target ID to get session for

		Returns:
			CDPSession if exists, None if target has detached
		"""
		session_ids = self._target_sessions.get(target_id, set())
		if not session_ids:
			# Check if this is the focused target - indicates stale focus that needs cleanup
			if self.browser_session.agent_focus_target_id == target_id:
				self.logger.warning(
					f'[SessionManager] ⚠️ Attempted to get session for stale focused target {target_id[:8]}... '
					f'Clearing stale focus and triggering recovery.'
				)

				# Clear stale focus immediately (defense in depth)
				self.browser_session.agent_focus_target_id = None

				# Trigger recovery if not already in progress
				if not self._recovery_in_progress:
					self.logger.warning('[SessionManager] Recovery was not in progress! Triggering now.')
					self._recovery_task = create_task_with_error_handling(
						self._recover_agent_focus(target_id),
						name='recover_agent_focus_from_stale_get',
						logger_instance=self.logger,
						suppress_exceptions=False,
					)
			return None
		return self._sessions.get(next(iter(session_ids)))

	def get_all_page_targets(self) -> list:
		"""Get all page/tab targets using owned data.

		Returns:
			List of Target objects for all page/tab targets
		"""
		page_targets = []
		for target in self._targets.values():
			if target.target_type in ('page', 'tab'):
				page_targets.append(target)
		return page_targets

	async def validate_session(self, target_id: TargetID) -> bool:
		"""Check if a target still has active sessions.

		Args:
			target_id: Target ID to validate

		Returns:
			True if target has active sessions, False if it should be removed
		"""
		if target_id not in self._target_sessions:
			return False
		return len(self._target_sessions[target_id]) > 0

	async def clear(self) -> None:
		"""Clear all owned data structures for cleanup."""
		async with self._lock:
			# Clear owned data (single source of truth)
			self._targets.clear()
			self._sessions.clear()
			self._target_sessions.clear()
			self._session_to_target.clear()

		self.logger.debug('[SessionManager] Cleared all owned data (targets, sessions, mappings)')

	async def is_target_valid(self, target_id: TargetID) -> bool:
		"""Check if a target is still valid and has active sessions.

		Args:
			target_id: Target ID to validate

		Returns:
			True if target is valid and has active sessions, False otherwise
		"""
		if target_id not in self._target_sessions:
			return False
		return len(self._target_sessions[target_id]) > 0

	def get_target_id_from_session_id(self, session_id: SessionID) -> TargetID | None:
		"""Look up which target a session belongs to.

		Args:
			session_id: The session ID to look up

		Returns:
			Target ID if found, None otherwise
		"""
		return self._session_to_target.get(session_id)

	def get_target(self, target_id: TargetID) -> 'Target | None':
		"""Get target from owned data.

		Args:
			target_id: Target ID to get

		Returns:
			Target object if found, None otherwise
		"""
		return self._targets.get(target_id)

	def get_all_targets(self) -> dict[TargetID, 'Target']:
		"""Get all targets (read-only access to owned data).

		Returns:
			Dict mapping target_id to Target objects
		"""
		return self._targets

	def get_all_target_ids(self) -> list[TargetID]:
		"""Get all target IDs from owned data.

		Returns:
			List of all target IDs
		"""
		return list(self._targets.keys())

	def get_all_sessions(self) -> dict[SessionID, 'CDPSession']:
		"""Get all sessions (read-only access to owned data).

		Returns:
			Dict mapping session_id to CDPSession objects
		"""
		return self._sessions

	def get_session(self, session_id: SessionID) -> 'CDPSession | None':
		"""Get session from owned data.

		Args:
			session_id: Session ID to get

		Returns:
			CDPSession object if found, None otherwise
		"""
		return self._sessions.get(session_id)

	def get_all_sessions_for_target(self, target_id: TargetID) -> list['CDPSession']:
		"""Get ALL sessions attached to a target from owned data.

		Args:
			target_id: Target ID to get sessions for

		Returns:
			List of all CDPSession objects for this target
		"""
		session_ids = self._target_sessions.get(target_id, set())
		return [self._sessions[sid] for sid in session_ids if sid in self._sessions]

	def get_target_sessions_mapping(self) -> dict[TargetID, set[SessionID]]:
		"""Get target->sessions mapping (read-only access).

		Returns:
			Dict mapping target_id to set of session_ids
		"""
		return self._target_sessions

	def get_focused_target(self) -> 'Target | None':
		"""Get the target that currently has agent focus.

		Convenience method that uses browser_session.agent_focus_target_id.

		Returns:
			Target object if agent has focus, None otherwise
		"""
		if not self.browser_session.agent_focus_target_id:
			return None
		return self.get_target(self.browser_session.agent_focus_target_id)

	async def ensure_valid_focus(self, timeout: float = 3.0) -> bool:
		"""Ensure agent_focus_target_id points to a valid, attached CDP session.

		If the focus target is stale (detached), this method waits for automatic recovery.
		Uses event-driven coordination instead of polling for efficiency.

		Args:
			timeout: Maximum time to wait for recovery in seconds (default: 3.0)

		Returns:
			True if focus is valid or successfully recovered, False if no focus or recovery failed
		"""
		if not self.browser_session.agent_focus_target_id:
			# No focus at all - might be initial state or complete failure
			if self._recovery_in_progress and self._recovery_complete_event:
				# Recovery is happening, wait for it
				try:
					await asyncio.wait_for(self._recovery_complete_event.wait(), timeout=timeout)
					# Check again after recovery - simple existence check
					focus_id = self.browser_session.agent_focus_target_id
					return bool(focus_id and self._get_session_for_target(focus_id))
				except TimeoutError:
					self.logger.error(f'[SessionManager] ❌ Timed out waiting for recovery after {timeout}s')
					return False
			return False

		# Simple existence check - does the focused target have a session?
		cdp_session = self._get_session_for_target(self.browser_session.agent_focus_target_id)
		if cdp_session:
			# Session exists - validate it's still active
			is_valid = await self.validate_session(self.browser_session.agent_focus_target_id)
			if is_valid:
				return True

		# Focus is stale - wait for recovery using event instead of polling
		stale_target_id = self.browser_session.agent_focus_target_id
		self.logger.warning(
			f'[SessionManager] ⚠️ Stale agent_focus detected (target {stale_target_id[:8] if stale_target_id else "None"}... detached), '
			f'waiting for recovery...'
		)

		# Check if recovery is already in progress
		if not self._recovery_in_progress:
			self.logger.warning(
				'[SessionManager] ⚠️ Recovery not in progress for stale focus! '
				'This indicates a bug - recovery should have been triggered.'
			)
			return False

		# Wait for recovery complete event (event-driven, not polling!)
		if self._recovery_complete_event:
			try:
				start_time = asyncio.get_event_loop().time()
				await asyncio.wait_for(self._recovery_complete_event.wait(), timeout=timeout)
				elapsed = asyncio.get_event_loop().time() - start_time

				# Verify recovery succeeded - simple existence check
				focus_id = self.browser_session.agent_focus_target_id
				if focus_id and self._get_session_for_target(focus_id):
					self.logger.info(
						f'[SessionManager] ✅ Agent focus recovered to {self.browser_session.agent_focus_target_id[:8]}... '
						f'after {elapsed * 1000:.0f}ms'
					)
					return True
				else:
					self.logger.error(
						f'[SessionManager] ❌ Recovery completed but focus still invalid after {elapsed * 1000:.0f}ms'
					)
					return False

			except TimeoutError:
				self.logger.error(
					f'[SessionManager] ❌ Recovery timed out after {timeout}s '
					f'(was: {stale_target_id[:8] if stale_target_id else "None"}..., '
					f'now: {self.browser_session.agent_focus_target_id[:8] if self.browser_session.agent_focus_target_id else "None"})'
				)
				return False
		else:
			self.logger.error('[SessionManager] ❌ Recovery event not initialized')
			return False

	async def _handle_target_attached(self, event: AttachedToTargetEvent) -> None:
		"""Handle Target.attachedToTarget event.

		Called automatically by Chrome when a new target/session is created.
		This is the ONLY place where sessions are added to the pool.
		"""
		target_id = event['targetInfo']['targetId']
		session_id = event['sessionId']
		target_type = event['targetInfo']['type']
		target_info = event['targetInfo']
		waiting_for_debugger = event.get('waitingForDebugger', False)

		self.logger.debug(
			f'[SessionManager] Target attached: {target_id[:8]}... (session={session_id[:8]}..., '
			f'type={target_type}, waitingForDebugger={waiting_for_debugger})'
		)

		# Defensive check: browser may be shutting down and _cdp_client_root could be None
		if self.browser_session._cdp_client_root is None:
			self.logger.debug(
				f'[SessionManager] Skipping target attach for {target_id[:8]}... - browser shutting down (no CDP client)'
			)
			return

		# Enable auto-attach for this session's children (do this FIRST, outside lock)
		try:
			await self.browser_session._cdp_client_root.send.Target.setAutoAttach(
				params={'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True}, session_id=session_id
			)
		except Exception as e:
			error_str = str(e)
			# Expected for short-lived targets (workers, temp iframes) that detach before this executes
			if '-32001' not in error_str and 'Session with given id not found' not in error_str:
				self.logger.debug(f'[SessionManager] Auto-attach failed for {target_type}: {e}')

		async with self._lock:
			# Track this session for the target
			if target_id not in self._target_sessions:
				self._target_sessions[target_id] = set()

			self._target_sessions[target_id].add(session_id)
			self._session_to_target[session_id] = target_id

		# Create or update Target (source of truth for url/title)
		if target_id not in self._targets:
			from browser_use.browser.session import Target

			target = Target(
				target_id=target_id,
				target_type=target_type,
				url=target_info.get('url', 'about:blank'),
				title=target_info.get('title', 'Unknown title'),
			)
			self._targets[target_id] = target
			self.logger.debug(f'[SessionManager] Created target {target_id[:8]}... (type={target_type})')
		else:
			# Update existing target info
			existing_target = self._targets[target_id]
			existing_target.url = target_info.get('url', existing_target.url)
			existing_target.title = target_info.get('title', existing_target.title)

		# Create CDPSession (communication channel)
		from browser_use.browser.session import CDPSession

		assert self.browser_session._cdp_client_root is not None, 'Root CDP client required'

		cdp_session = CDPSession(
			cdp_client=self.browser_session._cdp_client_root,
			target_id=target_id,
			session_id=session_id,
		)

		# Add to sessions dict
		self._sessions[session_id] = cdp_session

		self.logger.debug(
			f'[SessionManager] Created session {session_id[:8]}... for target {target_id[:8]}... '
			f'(total sessions: {len(self._sessions)})'
		)

		# Enable lifecycle events and network monitoring for page targets
		if target_type in ('page', 'tab'):
			await self._enable_page_monitoring(cdp_session)

		# Resume execution if waiting for debugger
		if waiting_for_debugger:
			try:
				assert self.browser_session._cdp_client_root is not None
				await self.browser_session._cdp_client_root.send.Runtime.runIfWaitingForDebugger(session_id=session_id)
			except Exception as e:
				self.logger.warning(f'[SessionManager] Failed to resume execution: {e}')

		if target_type in ('page', 'tab') and self.browser_session.browser_profile.demo_mode:
			demo = self.browser_session.demo_mode
			if demo:
				try:
					await demo.register_new_target(target_id)
				except Exception as exc:
					self.logger.debug(f'[SessionManager] Failed to register demo overlay for {target_id[:8]}...: {exc}')

	async def _handle_target_info_changed(self, event: dict) -> None:
		"""Handle Target.targetInfoChanged event.

		Updates target title/URL without polling getTargetInfo().
		Chrome fires this automatically when title or URL changes.
		"""
		target_info = event.get('targetInfo', {})
		target_id = target_info.get('targetId')

		if not target_id:
			return

		url_changed = False
		target_type = None

		async with self._lock:
			# Update target if it exists (source of truth for url/title)
			if target_id in self._targets:
				target = self._targets[target_id]
				target_type = target.target_type
				previous_url = target.url
				new_url = target_info.get('url', previous_url)

				target.title = target_info.get('title', target.title)
				target.url = new_url
				url_changed = previous_url != new_url

		if url_changed and target_type in ('page', 'tab') and self.browser_session.browser_profile.demo_mode:
			demo = self.browser_session.demo_mode
			if demo:
				try:
					await demo.refresh_target(target_id)
				except Exception as exc:
					self.logger.debug(
						f'[SessionManager] Failed to refresh demo overlay after URL change for {target_id[:8]}...: {exc}'
					)

	async def _handle_target_detached(self, event: DetachedFromTargetEvent) -> None:
		"""Handle Target.detachedFromTarget event.

		Called automatically by Chrome when a target/session is destroyed.
		This is the ONLY place where sessions are removed from the pool.
		"""
		session_id = event['sessionId']
		target_id = event.get('targetId')  # May be empty

		# If targetId not in event, look it up via session mapping
		if not target_id:
			async with self._lock:
				target_id = self._session_to_target.get(session_id)

		if not target_id:
			self.logger.warning(f'[SessionManager] Session detached but target unknown (session={session_id[:8]}...)')
			return

		agent_focus_lost = False
		target_fully_removed = False
		target_type = None

		async with self._lock:
			# Remove this session from target's session set
			if target_id in self._target_sessions:
				self._target_sessions[target_id].discard(session_id)

				remaining_sessions = len(self._target_sessions[target_id])

				self.logger.debug(
					f'[SessionManager] Session detached: target={target_id[:8]}... '
					f'session={session_id[:8]}... (remaining={remaining_sessions})'
				)

				# Only remove target when NO sessions remain
				if remaining_sessions == 0:
					self.logger.debug(f'[SessionManager] No sessions remain for target {target_id[:8]}..., removing target')

					target_fully_removed = True

					# Check if agent_focus points to this target
					agent_focus_lost = self.browser_session.agent_focus_target_id == target_id

					# Immediately clear stale focus to prevent operations on detached target
					if agent_focus_lost:
						self.logger.debug(
							f'[SessionManager] Clearing stale agent_focus_target_id {target_id[:8]}... '
							f'to prevent operations on detached target'
						)
						self.browser_session.agent_focus_target_id = None

					# Get target type before removing (needed for TabClosedEvent dispatch)
					target = self._targets.get(target_id)
					target_type = target.target_type if target else None

					# Remove target (entity) from owned data
					if target_id in self._targets:
						self._targets.pop(target_id)
						self.logger.debug(
							f'[SessionManager] Removed target {target_id[:8]}... (remaining targets: {len(self._targets)})'
						)

					# Clean up tracking
					del self._target_sessions[target_id]
			else:
				# Target not tracked - already removed or never attached
				self.logger.debug(
					f'[SessionManager] Session detached from untracked target: target={target_id[:8]}... '
					f'session={session_id[:8]}... (target was already removed or attach event was missed)'
				)

			# Remove session from owned sessions dict
			if session_id in self._sessions:
				self._sessions.pop(session_id)
				self.logger.debug(
					f'[SessionManager] Removed session {session_id[:8]}... (remaining sessions: {len(self._sessions)})'
				)

			# Remove from reverse mapping
			if session_id in self._session_to_target:
				del self._session_to_target[session_id]

		# Dispatch TabClosedEvent only for page/tab targets that are fully removed (not iframes/workers or partial detaches)
		if target_fully_removed:
			if target_type in ('page', 'tab'):
				from browser_use.browser.events import TabClosedEvent

				self.browser_session.event_bus.dispatch(TabClosedEvent(target_id=target_id))
				self.logger.debug(f'[SessionManager] Dispatched TabClosedEvent for page target {target_id[:8]}...')
				demo = self.browser_session.demo_mode
				if demo:
					demo.unregister_target(target_id)
			elif target_type:
				self.logger.debug(
					f'[SessionManager] Target {target_id[:8]}... fully removed (type={target_type}) - not dispatching TabClosedEvent'
				)

		# Auto-recover agent_focus outside the lock to avoid blocking other operations
		if agent_focus_lost:
			# Create recovery task instead of awaiting directly - allows concurrent operations to wait on same recovery
			if not self._recovery_in_progress:
				self._recovery_task = create_task_with_error_handling(
					self._recover_agent_focus(target_id),
					name='recover_agent_focus',
					logger_instance=self.logger,
					suppress_exceptions=False,
				)

	async def _recover_agent_focus(self, crashed_target_id: TargetID) -> None:
		"""Auto-recover agent_focus when the focused target crashes/detaches.

		Uses recovery lock to prevent concurrent recovery attempts from creating multiple emergency tabs.
		Coordinates with ensure_valid_focus() via events for efficient waiting.

		Args:
			crashed_target_id: The target ID that was lost
		"""
		try:
			# Prevent concurrent recovery attempts
			async with self._recovery_lock:
				# Set recovery state INSIDE lock to prevent race conditions
				if self._recovery_in_progress:
					self.logger.debug('[SessionManager] Recovery already in progress, waiting for it to complete')
					# Wait for ongoing recovery instead of starting a new one
					if self._recovery_complete_event:
						try:
							await asyncio.wait_for(self._recovery_complete_event.wait(), timeout=5.0)
						except TimeoutError:
							self.logger.error('[SessionManager] Timed out waiting for ongoing recovery')
					return

				# Set recovery state
				self._recovery_in_progress = True
				self._recovery_complete_event = asyncio.Event()

				if self.browser_session._cdp_client_root is None:
					self.logger.debug('[SessionManager] Skipping focus recovery - browser shutting down (no CDP client)')
					return

				# Check if another recovery already fixed agent_focus
				if self.browser_session.agent_focus_target_id and self.browser_session.agent_focus_target_id != crashed_target_id:
					self.logger.debug(
						f'[SessionManager] Agent focus already recovered by concurrent operation '
						f'(now: {self.browser_session.agent_focus_target_id[:8]}...), skipping recovery'
					)
					return

				# Note: agent_focus_target_id may already be None (cleared in _handle_target_detached)
				current_focus_desc = (
					f'{self.browser_session.agent_focus_target_id[:8]}...'
					if self.browser_session.agent_focus_target_id
					else 'None (already cleared)'
				)

				self.logger.warning(
					f'[SessionManager] Agent focus target {crashed_target_id[:8]}... detached! '
					f'Current focus: {current_focus_desc}. Auto-recovering by switching to another target...'
				)

			# Perform recovery (outside lock to allow concurrent operations)
			# Try to find another valid page target
			page_targets = self.get_all_page_targets()

			new_target_id = None
			is_existing_tab = False

			if page_targets:
				# Switch to most recent page that's not the crashed one
				new_target_id = page_targets[-1].target_id
				is_existing_tab = True
				self.logger.info(f'[SessionManager] Switching agent_focus to existing tab {new_target_id[:8]}...')
			else:
				# No pages exist - create a new one
				self.logger.warning('[SessionManager] No tabs remain! Creating new tab for agent...')
				new_target_id = await self.browser_session._cdp_create_new_page('about:blank')
				self.logger.info(f'[SessionManager] Created new tab {new_target_id[:8]}... for agent')

				# Dispatch TabCreatedEvent so watchdogs can initialize
				from browser_use.browser.events import TabCreatedEvent

				self.browser_session.event_bus.dispatch(TabCreatedEvent(url='about:blank', target_id=new_target_id))

			# Wait for CDP attach event to create session
			# Note: This polling is necessary - waiting for external Chrome CDP event
			# _handle_target_attached will add session to pool when Chrome fires attachedToTarget
			new_session = None
			for attempt in range(20):  # Wait up to 2 seconds
				await asyncio.sleep(0.1)
				new_session = self._get_session_for_target(new_target_id)
				if new_session:
					break

			if new_session:
				self.browser_session.agent_focus_target_id = new_target_id
				self.logger.info(f'[SessionManager] ✅ Agent focus recovered: {new_target_id[:8]}...')

				# Visually activate the tab in browser (only for existing tabs)
				if is_existing_tab:
					try:
						assert self.browser_session._cdp_client_root is not None
						await self.browser_session._cdp_client_root.send.Target.activateTarget(params={'targetId': new_target_id})
						self.logger.debug(f'[SessionManager] Activated tab {new_target_id[:8]}... in browser UI')
					except Exception as e:
						self.logger.debug(f'[SessionManager] Failed to activate tab visually: {e}')

				# Get target to access url (from owned data)
				target = self.get_target(new_target_id)
				target_url = target.url if target else 'about:blank'

				# Dispatch focus changed event
				from browser_use.browser.events import AgentFocusChangedEvent

				self.browser_session.event_bus.dispatch(AgentFocusChangedEvent(target_id=new_target_id, url=target_url))
				return

			# Recovery failed - create emergency fallback tab
			self.logger.error(
				f'[SessionManager] ❌ Failed to get session for {new_target_id[:8]}... after 2s, creating emergency fallback tab'
			)

			fallback_target_id = await self.browser_session._cdp_create_new_page('about:blank')
			self.logger.warning(f'[SessionManager] Created emergency fallback tab {fallback_target_id[:8]}...')

			# Try one more time with fallback
			# Note: This polling is necessary - waiting for external Chrome CDP event
			for _ in range(20):
				await asyncio.sleep(0.1)
				fallback_session = self._get_session_for_target(fallback_target_id)
				if fallback_session:
					self.browser_session.agent_focus_target_id = fallback_target_id
					self.logger.warning(f'[SessionManager] ⚠️ Agent focus set to emergency fallback: {fallback_target_id[:8]}...')

					from browser_use.browser.events import AgentFocusChangedEvent, TabCreatedEvent

					self.browser_session.event_bus.dispatch(TabCreatedEvent(url='about:blank', target_id=fallback_target_id))
					self.browser_session.event_bus.dispatch(
						AgentFocusChangedEvent(target_id=fallback_target_id, url='about:blank')
					)
					return

			# Complete failure - this should never happen
			self.logger.critical(
				'[SessionManager] 🚨 CRITICAL: Failed to recover agent_focus even with fallback! Agent may be in broken state.'
			)

		except Exception as e:
			self.logger.error(f'[SessionManager] ❌ Error during agent_focus recovery: {type(e).__name__}: {e}')
		finally:
			# Always signal completion and reset recovery state
			# This allows all waiting operations to proceed (success or failure)
			if self._recovery_complete_event:
				self._recovery_complete_event.set()
			self._recovery_in_progress = False
			self._recovery_task = None
			self.logger.debug('[SessionManager] Recovery state reset')

	async def _initialize_existing_targets(self) -> None:
		"""Discover and initialize all existing targets at startup.

		Attaches to each target and initializes it SYNCHRONOUSLY.
		Chrome will also fire attachedToTarget events, but _handle_target_attached() is
		idempotent (checks if target already in pool), so duplicate handling is safe.

		This eliminates race conditions - monitoring is guaranteed ready before navigation.
		"""
		cdp_client = self.browser_session._cdp_client_root
		assert cdp_client is not None

		# Get all existing targets
		targets_result = await cdp_client.send.Target.getTargets()
		existing_targets = targets_result.get('targetInfos', [])

		self.logger.debug(f'[SessionManager] Discovered {len(existing_targets)} existing targets')

		# Track target IDs for verification
		target_ids_to_wait_for = []

		# Just attach to ALL existing targets - Chrome fires attachedToTarget events
		# The on_attached handler (via create_task) does ALL the work
		for target in existing_targets:
			target_id = target['targetId']
			target_type = target.get('type', 'unknown')

			try:
				# Just attach - event handler does everything
				await cdp_client.send.Target.attachToTarget(params={'targetId': target_id, 'flatten': True})
				target_ids_to_wait_for.append(target_id)
			except Exception as e:
				self.logger.debug(
					f'[SessionManager] Failed to attach to existing target {target_id[:8]}... (type={target_type}): {e}'
				)

		# Wait for event handlers to complete their work (they run via create_task)
		# Use event-driven approach instead of polling for better performance
		ready_event = asyncio.Event()

		async def check_all_ready():
			"""Check if all sessions are ready and signal completion."""
			while True:
				ready_count = 0
				for tid in target_ids_to_wait_for:
					session = self._get_session_for_target(tid)
					if session:
						target = self._targets.get(tid)
						target_type = target.target_type if target else 'unknown'
						# For pages, verify monitoring is enabled
						if target_type in ('page', 'tab'):
							if hasattr(session, '_lifecycle_events') and session._lifecycle_events is not None:
								ready_count += 1
						else:
							# Non-page targets don't need monitoring
							ready_count += 1

				if ready_count == len(target_ids_to_wait_for):
					ready_event.set()
					return

				await asyncio.sleep(0.05)

		# Start checking in background
		check_task = create_task_with_error_handling(
			check_all_ready(), name='check_all_targets_ready', logger_instance=self.logger
		)

		try:
			# Wait for completion with timeout
			await asyncio.wait_for(ready_event.wait(), timeout=2.0)
		except TimeoutError:
			# Timeout - count what's ready
			ready_count = 0
			for tid in target_ids_to_wait_for:
				session = self._get_session_for_target(tid)
				if session:
					target = self._targets.get(tid)
					target_type = target.target_type if target else 'unknown'
					# For pages, verify monitoring is enabled
					if target_type in ('page', 'tab'):
						if hasattr(session, '_lifecycle_events') and session._lifecycle_events is not None:
							ready_count += 1
					else:
						# Non-page targets don't need monitoring
						ready_count += 1
			self.logger.warning(
				f'[SessionManager] Initialization timeout after 2.0s: {ready_count}/{len(target_ids_to_wait_for)} sessions ready'
			)
		finally:
			check_task.cancel()
			try:
				await check_task
			except asyncio.CancelledError:
				pass

	async def _enable_page_monitoring(self, cdp_session: 'CDPSession') -> None:
		"""Enable lifecycle events and network monitoring for a page target.

		This is called once per page when it's created, avoiding handler accumulation.
		Registers a SINGLE lifecycle handler per session that stores events for navigations to consume.

		Args:
			cdp_session: The CDP session to enable monitoring on
		"""
		try:
			# Enable Page domain first (required for lifecycle events)
			await cdp_session.cdp_client.send.Page.enable(session_id=cdp_session.session_id)

			# Enable lifecycle events (load, DOMContentLoaded, networkIdle, etc.)
			await cdp_session.cdp_client.send.Page.setLifecycleEventsEnabled(
				params={'enabled': True}, session_id=cdp_session.session_id
			)

			# Enable network monitoring for networkIdle detection
			await cdp_session.cdp_client.send.Network.enable(session_id=cdp_session.session_id)

			# Initialize lifecycle event storage for this session (thread-safe)
			from collections import deque

			cdp_session._lifecycle_events = deque(maxlen=50)  # Keep last 50 events
			cdp_session._lifecycle_lock = asyncio.Lock()

			# Register ONE handler per session that stores events
			def on_lifecycle_event(event, session_id=None):
				event_name = event.get('name', 'unknown')
				event_loader_id = event.get('loaderId', 'none')

				# Find which target this session belongs to
				target_id_from_event = None
				if session_id:
					target_id_from_event = self.get_target_id_from_session_id(session_id)

				# Check if this event is for our target
				if target_id_from_event == cdp_session.target_id:
					# Store event for navigations to consume
					event_data = {
						'name': event_name,
						'loaderId': event_loader_id,
						'timestamp': asyncio.get_event_loop().time(),
					}
					# Append is atomic in CPython
					try:
						cdp_session._lifecycle_events.append(event_data)
					except Exception as e:
						# Only log errors, not every event
						self.logger.error(f'[SessionManager] Failed to store lifecycle event: {e}')

			# Register the handler ONCE (this is the only place we register)
			cdp_session.cdp_client.register.Page.lifecycleEvent(on_lifecycle_event)

		except Exception as e:
			# Don't fail - target might be short-lived or already detached
			error_str = str(e)
			if '-32001' in error_str or 'Session with given id not found' in error_str:
				self.logger.debug(
					f'[SessionManager] Target {cdp_session.target_id[:8]}... detached before monitoring could be enabled (normal for short-lived targets)'
				)
			else:
				self.logger.warning(
					f'[SessionManager] Failed to enable monitoring for target {cdp_session.target_id[:8]}...: {e}'
				)
