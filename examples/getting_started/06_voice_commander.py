"""
Perfect Voice Commander for Browser-Use
- Sequential execution: Completes current task before listening to next
- Fast execution with flash mode
- Clean and simple
- Production ready

Usage:
    uv run examples/integrations/voice_commander.py
"""

import asyncio
import time

import speech_recognition as sr  # type: ignore

from browser_use import Agent, Browser, ChatBrowserUse


class VoiceCommander:
	"""Sequential voice commander - one command at a time"""

	def __init__(self, use_cloud: bool = True, flash_mode: bool = True):
		self.recognizer = sr.Recognizer()
		self.microphone = sr.Microphone()
		self.is_running = True
		self.flash_mode = flash_mode

		# Initialize browser with fallback
		print('\nInitializing browser...')
		self.browser = self._init_browser(use_cloud)

		# Calibrate microphone
		print('Calibrating microphone...')
		with self.microphone as source:
			self.recognizer.adjust_for_ambient_noise(source, duration=1)

		print('Ready\n')

	def _init_browser(self, use_cloud: bool) -> Browser:
		"""Initialize browser with fallback to local if cloud fails"""
		try:
			if use_cloud:
				print('Attempting cloud browser...')
				browser = Browser(  # type: ignore
					use_cloud=True,
					headless=False,
					keep_alive=True,
				)
				print('Cloud browser connected')
				return browser
		except Exception as e:
			print(f'Cloud browser failed: {str(e)[:50]}')
			print('Falling back to local browser...')

		# Fallback to local browser
		browser = Browser(  # type: ignore
			use_cloud=False,
			headless=False,
			keep_alive=True,
		)
		print('Local browser initialized')
		return browser

	def listen_for_command(self) -> str | None:
		"""Listen for a single voice command"""
		try:
			print('Listening... (speak your command)')

			with self.microphone as source:
				audio = self.recognizer.listen(
					source,
					timeout=10,  # Wait up to 10s for speech
					phrase_time_limit=10,  # Max 10s per command
				)

			print('Processing speech...')

			# Transcribe using Google Speech Recognition (free)
			text = self.recognizer.recognize_google(audio)  # type: ignore

			print(f"Heard: '{text}'\n")
			return text

		except sr.WaitTimeoutError:
			print('No speech detected\n')
			return None
		except sr.UnknownValueError:
			print('Could not understand audio\n')
			return None
		except sr.RequestError as e:
			print(f'Speech recognition error: {e}\n')
			return None
		except Exception as e:
			print(f'Error: {e}\n')
			return None

	async def execute_command(self, command: str):
		"""Execute command and wait for completion"""
		print(f'{"=" * 60}')
		print(f"Executing: '{command}'")
		print(f'{"=" * 60}\n')

		start_time = time.time()

		# Retry logic
		max_retries = 2
		retry_count = 0

		while retry_count <= max_retries:
			try:
				# Create agent with optimizations
				agent = Agent(
					task=command,
					llm=ChatBrowserUse(),
					browser=self.browser,
					flash_mode=self.flash_mode,  # Fast execution
					max_actions_per_step=5,  # More actions at once
				)

				# Execute and WAIT for completion
				result = await agent.run(max_steps=10)

				elapsed = time.time() - start_time

				# Show result
				if result.is_done():
					result_text = result.final_result() or 'Task completed'
					print(f'\nDone in {elapsed:.1f}s')
					print(f'Result: {result_text}\n')
				else:
					print(f'\nTask incomplete after {elapsed:.1f}s\n')

				break  # Success, exit retry loop

			except Exception as e:
				elapsed = time.time() - start_time
				error_msg = str(e)

				# Check if it's a network error
				if 'nodename nor servname' in error_msg or 'ConnectError' in error_msg:
					if retry_count < max_retries:
						retry_count += 1
						print(f'\nNetwork error, retrying ({retry_count}/{max_retries})...\n')
						await asyncio.sleep(2)  # Wait before retry
						continue
					else:
						print(f'\nNetwork error after {elapsed:.1f}s')
						print('Tip: Check your internet connection or try local browser\n')
						break
				else:
					# Other errors
					print(f'\nError after {elapsed:.1f}s: {error_msg[:100]}\n')
					break

	async def run(self):
		"""Main loop - sequential command execution"""
		print('\n' + '=' * 60)
		print('VOICE COMMANDER')
		print('=' * 60)
		print('Sequential mode: Completes task before next command')
		if self.flash_mode:
			print('Flash mode: Enabled (3-5x faster)')
		else:
			print('Normal mode: Enabled (more accurate)')

		print('\nExample commands:')
		print("  - 'Search for Python tutorials'")
		print("  - 'Go to GitHub'")
		print("  - 'Open YouTube and play relaxing music'")
		print("  - 'Find weather in Tokyo'")
		print("\nSay 'exit' or 'quit' to stop")
		print('=' * 60 + '\n')

		while self.is_running:
			# Step 1: Listen for command
			command = self.listen_for_command()

			if not command:
				continue  # Try listening again

			# Check for exit commands
			if any(word in command.lower() for word in ['exit', 'quit', 'stop']):
				print('Goodbye!')
				break

			# Step 2: Execute command and WAIT for completion
			await self.execute_command(command)

			# Step 3: Ready for next command
			print('Ready for next command...\n')

		print('\nVoice commander stopped\n')


async def main():
	"""Run the voice commander"""

	# Configuration
	USE_CLOUD = False  # True for cloud browser (faster but needs network)
	FLASH_MODE = True  # False for more accurate but slower execution

	commander = VoiceCommander(use_cloud=USE_CLOUD, flash_mode=FLASH_MODE)

	try:
		await commander.run()
	except KeyboardInterrupt:
		print('\n\nStopped by user\n')
	finally:
		# Cleanup
		if commander.browser:
			print('Cleaning up...')
			await commander.browser.close()


if __name__ == '__main__':
	asyncio.run(main())