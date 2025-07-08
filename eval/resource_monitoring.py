import asyncio
import gc
import logging
import signal
import sys
import threading
import time
from typing import Any

import psutil

# Module logger
logger = logging.getLogger(__name__)

# Global variables for resource monitoring
_resource_monitor_task = None
_resource_monitor_stop_event = None
_graceful_shutdown_initiated = False


def get_system_resources() -> dict[str, Any]:
	"""Get current system resource usage"""
	try:
		# Memory usage
		memory = psutil.virtual_memory()
		memory_percent = memory.percent
		memory_available_gb = memory.available / (1024**3)

		# CPU usage
		cpu_percent = psutil.cpu_percent(interval=None)

		# Load average (Unix only)
		try:
			load_avg = psutil.getloadavg()
			load_1min = load_avg[0]
		except (AttributeError, OSError):
			load_1min = 0.0

		# Process count
		process_count = len(psutil.pids())

		# Chrome/Browser processes
		chrome_processes = []
		python_processes = []
		for proc in psutil.process_iter(['pid', 'name', 'memory_percent', 'cpu_percent']):
			try:
				name = proc.info['name'].lower()
				if 'chrome' in name or 'chromium' in name:
					chrome_processes.append(proc.info)
				elif 'python' in name:
					python_processes.append(proc.info)
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				continue

		return {
			'memory_percent': memory_percent,
			'memory_available_gb': memory_available_gb,
			'cpu_percent': cpu_percent,
			'load_1min': load_1min,
			'process_count': process_count,
			'chrome_process_count': len(chrome_processes),
			'python_process_count': len(python_processes),
			'chrome_processes': chrome_processes[:5],  # Top 5 chrome processes
			'python_processes': python_processes[:5],  # Top 5 python processes
		}
	except Exception as e:
		logger.warning(f'Failed to get system resources: {type(e).__name__}: {e}')
		return {
			'memory_percent': 0,
			'memory_available_gb': 0,
			'cpu_percent': 0,
			'load_1min': 0,
			'process_count': 0,
			'chrome_process_count': 0,
			'python_process_count': 0,
			'chrome_processes': [],
			'python_processes': [],
		}


def log_system_resources(context: str = ''):
	"""Log current system resource usage"""
	resources = get_system_resources()
	logger.info(f'=== SYSTEM RESOURCES {context} ===')
	logger.info(f'Memory: {resources["memory_percent"]:.1f}% used, {resources["memory_available_gb"]:.2f}GB available')
	logger.info(f'CPU: {resources["cpu_percent"]:.1f}%, Load: {resources["load_1min"]:.2f}')
	logger.info(
		f'Processes: {resources["process_count"]} total, {resources["chrome_process_count"]} Chrome, {resources["python_process_count"]} Python'
	)

	if resources['chrome_processes']:
		logger.info('Top Chrome processes:')
		for proc in resources['chrome_processes']:
			logger.info(
				f'  PID {proc["pid"]}: {proc["name"]} - CPU: {proc["cpu_percent"]:.1f}%, Memory: {proc["memory_percent"]:.1f}%'
			)

	logger.info('=' * (20 + len(context)))


async def start_resource_monitoring(interval: int = 30):
	"""Start background resource monitoring"""
	global _resource_monitor_task, _resource_monitor_stop_event

	if _resource_monitor_task is not None:
		logger.warning('Resource monitoring is already running')
		return

	_resource_monitor_stop_event = asyncio.Event()

	async def monitor_loop():
		"""Background monitoring loop"""
		logger.info(f'Starting resource monitoring (interval: {interval}s)')
		try:
			while _resource_monitor_stop_event is not None and not _resource_monitor_stop_event.is_set():
				try:
					log_system_resources('MONITOR')

					# Check for concerning resource levels
					resources = get_system_resources()
					if resources['memory_percent'] > 85:
						logger.warning(f'⚠️ HIGH MEMORY USAGE: {resources["memory_percent"]:.1f}%')
					if resources['cpu_percent'] > 90:
						logger.warning(f'⚠️ HIGH CPU USAGE: {resources["cpu_percent"]:.1f}%')
					if resources['chrome_process_count'] > 20:
						logger.warning(f'⚠️ HIGH CHROME PROCESS COUNT: {resources["chrome_process_count"]}')

					# Force garbage collection periodically
					if resources['memory_percent'] > 70:
						logger.info('Running garbage collection due to high memory usage')
						gc.collect()

				except Exception as e:
					logger.error(f'Error in resource monitoring: {type(e).__name__}: {e}')

				try:
					if _resource_monitor_stop_event is not None:
						await asyncio.wait_for(_resource_monitor_stop_event.wait(), timeout=interval)
					else:
						await asyncio.sleep(interval)
					break  # Event was set, exit loop
				except TimeoutError:
					continue  # Timeout reached, continue monitoring
		except Exception as e:
			logger.error(f'Resource monitoring loop crashed: {type(e).__name__}: {e}')
		finally:
			logger.info('Resource monitoring stopped')

	_resource_monitor_task = asyncio.create_task(monitor_loop())


async def stop_resource_monitoring():
	"""Stop background resource monitoring"""
	global _resource_monitor_task, _resource_monitor_stop_event

	if _resource_monitor_stop_event is not None:
		_resource_monitor_stop_event.set()

	if _resource_monitor_task is not None:
		try:
			await asyncio.wait_for(_resource_monitor_task, timeout=5.0)
		except TimeoutError:
			logger.warning('Resource monitoring task did not stop gracefully')
			_resource_monitor_task.cancel()
			try:
				await _resource_monitor_task
			except asyncio.CancelledError:
				pass

		_resource_monitor_task = None
		_resource_monitor_stop_event = None


def setup_signal_handlers():
	"""Setup signal handlers for graceful shutdown"""
	global _graceful_shutdown_initiated

	def signal_handler(signum, frame):
		global _graceful_shutdown_initiated
		if _graceful_shutdown_initiated:
			logger.critical('🔥 FORCE EXIT: Second signal received, terminating immediately')
			sys.exit(1)

		_graceful_shutdown_initiated = True
		logger.warning(f'⚠️ GRACEFUL SHUTDOWN: Received signal {signum}, initiating graceful shutdown...')
		log_system_resources('SHUTDOWN')

		# Try to stop resource monitoring
		try:
			loop = asyncio.get_event_loop()
			if loop.is_running():
				loop.create_task(stop_resource_monitoring())
		except Exception as e:
			logger.error(f'Failed to stop resource monitoring during shutdown: {e}')

		# Give some time for cleanup, then force exit
		def force_exit():
			time.sleep(10)
			if _graceful_shutdown_initiated:
				logger.critical('🔥 FORCE EXIT: Graceful shutdown timeout, terminating')
				sys.exit(1)

		threading.Thread(target=force_exit, daemon=True).start()

	# Register signal handlers
	signal.signal(signal.SIGINT, signal_handler)
	signal.signal(signal.SIGTERM, signal_handler)


def is_shutdown_initiated() -> bool:
	"""Check if graceful shutdown has been initiated"""
	return _graceful_shutdown_initiated


def is_monitoring_active() -> bool:
	"""Check if resource monitoring is currently active"""
	return _resource_monitor_task is not None and not _resource_monitor_task.done()
