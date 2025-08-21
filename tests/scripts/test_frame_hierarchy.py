#!/usr/bin/env python3
"""Test frame hierarchy for any URL passed as argument."""

import asyncio
import sys

from browser_use.browser import BrowserSession
from browser_use.browser.events import BrowserStartEvent
from browser_use.browser.profile import BrowserProfile


async def analyze_frame_hierarchy(url):
	"""Analyze and display complete frame hierarchy for a URL."""

	profile = BrowserProfile(headless=True, user_data_dir=None)
	session = BrowserSession(browser_profile=profile)

	try:
		print('🚀 Starting browser...')
		await session.on_BrowserStartEvent(BrowserStartEvent())

		print(f'📍 Navigating to: {url}')
		await session._cdp_navigate(url)
		await asyncio.sleep(3)

		print('\n' + '=' * 80)
		print('FRAME HIERARCHY ANALYSIS')
		print('=' * 80)

		# Get all targets
		targets = await session.cdp_client.send.Target.getTargets()
		all_targets = targets.get('targetInfos', [])

		# Separate by type
		page_targets = [t for t in all_targets if t.get('type') == 'page']
		iframe_targets = [t for t in all_targets if t.get('type') == 'iframe']

		print('\n📊 Target Summary:')
		print(f'  Total targets: {len(all_targets)}')
		print(f'  Page targets: {len(page_targets)}')
		print(f'  Iframe targets (OOPIFs): {len(iframe_targets)}')

		# Show all targets
		print('\n📋 All Targets:')
		for i, target in enumerate(all_targets):
			t_type = target.get('type')
			t_url = target.get('url', 'none')
			t_id = target.get('targetId', 'unknown')

			if t_type in ['page', 'iframe']:
				print(f'\n  [{i + 1}] Type: {t_type}')
				print(f'      URL: {t_url}')
				print(f'      Target ID: {t_id[:30]}...')
				print(f'      Attached: {target.get("attached", False)}')

		# Get main page frame tree
		main_target = next((t for t in page_targets if url in t.get('url', '')), page_targets[0] if page_targets else None)

		if main_target:
			print('\n📐 Main Page Frame Tree:')
			print(f'  Target: {main_target["url"]}')
			print(f'  Target ID: {main_target["targetId"][:30]}...')

			s = await session.cdp_client.send.Target.attachToTarget(params={'targetId': main_target['targetId'], 'flatten': True})
			sid = s['sessionId']

			try:
				await session.cdp_client.send.Page.enable(session_id=sid)
				tree = await session.cdp_client.send.Page.getFrameTree(session_id=sid)

				print('\n  Frame Tree Structure:')

				def print_tree(node, indent=0, parent_id=None):
					frame = node['frame']
					frame_id = frame.get('id', 'unknown')
					frame_url = frame.get('url', 'none')

					prefix = '  ' * indent + ('└─ ' if indent > 0 else '')
					print(f'{prefix}Frame: {frame_url}')
					print(f'{"  " * (indent + 1)}ID: {frame_id[:30]}...')

					if parent_id:
						print(f'{"  " * (indent + 1)}Parent: {parent_id[:30]}...')

					# Check cross-origin status
					cross_origin = frame.get('crossOriginIsolatedContextType', 'unknown')
					if cross_origin != 'NotIsolated':
						print(f'{"  " * (indent + 1)}⚠️  Cross-Origin: {cross_origin}')

					# Process children
					for child in node.get('childFrames', []):
						print_tree(child, indent + 1, frame_id)

				print_tree(tree['frameTree'])

			finally:
				await session.cdp_client.send.Target.detachFromTarget(params={'sessionId': sid})

		# Show iframe target trees
		if iframe_targets:
			print('\n🔸 OOPIF Target Frame Trees:')

			for iframe_target in iframe_targets:
				print(f'\n  OOPIF Target: {iframe_target["url"]}')
				print(f'  Target ID: {iframe_target["targetId"][:30]}...')

				s = await session.cdp_client.send.Target.attachToTarget(
					params={'targetId': iframe_target['targetId'], 'flatten': True}
				)
				sid = s['sessionId']

				try:
					await session.cdp_client.send.Page.enable(session_id=sid)
					tree = await session.cdp_client.send.Page.getFrameTree(session_id=sid)

					frame = tree['frameTree']['frame']
					print(f'  Frame ID: {frame.get("id", "unknown")[:30]}...')
					print(f'  Frame URL: {frame.get("url", "none")}')
					print('  ⚠️  This frame runs in a separate process (OOPIF)')

				except Exception as e:
					print(f'  Error: {e}')
				finally:
					await session.cdp_client.send.Target.detachFromTarget(params={'sessionId': sid})

		# Now show unified view from get_all_frames
		print('\n' + '=' * 80)
		print('UNIFIED FRAME HIERARCHY (get_all_frames method)')
		print('=' * 80)

		all_frames, target_sessions = await session.get_all_frames()

		# Clean up sessions
		for tid, sess_id in target_sessions.items():
			try:
				await session.cdp_client.send.Target.detachFromTarget(params={'sessionId': sess_id})
			except:
				pass

		print('\n📊 Frame Statistics:')
		print(f'  Total frames discovered: {len(all_frames)}')

		# Separate root and child frames
		root_frames = []
		child_frames = []

		for frame_id, frame_info in all_frames.items():
			if not frame_info.get('parentFrameId'):
				root_frames.append((frame_id, frame_info))
			else:
				child_frames.append((frame_id, frame_info))

		print(f'  Root frames: {len(root_frames)}')
		print(f'  Child frames: {len(child_frames)}')

		# Display all frames with details
		print('\n📋 All Frames:')

		for i, (frame_id, frame_info) in enumerate(all_frames.items()):
			url = frame_info.get('url', 'none')
			parent = frame_info.get('parentFrameId')
			target_id = frame_info.get('frameTargetId', 'unknown')
			is_cross = frame_info.get('isCrossOrigin', False)

			print(f'\n  [{i + 1}] Frame URL: {url}')
			print(f'      Frame ID: {frame_id[:30]}...')
			print(f'      Parent Frame ID: {parent[:30] + "..." if parent else "None (ROOT)"}')
			print(f'      Target ID: {target_id[:30]}...')
			print(f'      Cross-Origin: {is_cross}')

			# Highlight problems
			if not parent and 'v0-simple-landing' in url:
				print('      ❌ PROBLEM: Cross-origin frame incorrectly marked as root!')
			elif not parent and url != 'about:blank' and url not in ['chrome://newtab/', 'about:blank']:
				# Check if this should be the main frame
				if any(url in t.get('url', '') for t in page_targets):
					print('      ✅ Correctly identified as root frame')

			if is_cross:
				print('      🔸 This is a cross-origin frame (OOPIF)')

		# Show parent-child relationships
		print('\n🌳 Frame Relationships:')

		# Build a tree structure
		def print_frame_tree(frame_id, frame_info, indent=0, visited=None):
			if visited is None:
				visited = set()

			if frame_id in visited:
				return
			visited.add(frame_id)

			url = frame_info.get('url', 'none')
			prefix = '  ' * indent + ('└─ ' if indent > 0 else '')

			print(f'{prefix}{url[:60]}...')
			print(f'{"  " * (indent + 1)}[{frame_id[:20]}...]')

			# Find children
			for child_id, child_info in all_frames.items():
				if child_info.get('parentFrameId') == frame_id:
					print_frame_tree(child_id, child_info, indent + 1, visited)

		# Print trees starting from roots
		for frame_id, frame_info in root_frames:
			print('\n  Tree starting from root:')
			print_frame_tree(frame_id, frame_info)

		print('\n' + '=' * 80)
		print('✅ Analysis complete!')
		print('=' * 80)

	except Exception as e:
		print(f'❌ Error: {e}')
		import traceback

		traceback.print_exc()
	finally:
		# Stop the CDP client first before killing the browser
		print('\n🛑 Shutting down...')

		# Close CDP connection first while browser is still alive
		if session._cdp_client_root:
			try:
				await session._cdp_client_root.stop()
			except Exception:
				pass  # Ignore errors if already disconnected

		# Then stop the browser process
		from browser_use.browser.events import BrowserStopEvent

		stop_event = session.event_bus.dispatch(BrowserStopEvent())
		try:
			await asyncio.wait_for(stop_event, timeout=2.0)
		except TimeoutError:
			print('⚠️ Browser stop timed out')


def main():
	if len(sys.argv) != 2:
		print('Usage: python test_frame_hierarchy.py <URL>')
		print('\nExample URLs to test:')
		print('  https://v0-website-with-clickable-elements.vercel.app/nested-iframe')
		print('  https://v0-website-with-clickable-elements.vercel.app/cross-origin')
		print('  https://v0-website-with-clickable-elements.vercel.app/shadow-dom')
		sys.exit(1)

	url = sys.argv[1]
	asyncio.run(analyze_frame_hierarchy(url))

	# Ensure clean exit
	print('✅ Script completed')
	sys.exit(0)


if __name__ == '__main__':
	main()
