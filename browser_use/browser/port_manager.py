"""
Thread-safe port management for CDP debugging ports.

Fixes race conditions when multiple browser sessions try to allocate ports simultaneously.
"""

import json
import os
import random
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Set

try:
	import psutil
except ImportError:
	psutil = None  # graceful fallback if psutil not available


class PortManager:
	"""Thread-safe port allocation manager to prevent CDP port conflicts."""
	
	_instance = None
	_lock = threading.Lock()
	
	def __new__(cls):
		if cls._instance is None:
			with cls._lock:
				if cls._instance is None:
					cls._instance = super().__new__(cls)
		return cls._instance
	
	def __init__(self):
		if not hasattr(self, '_initialized'):
			self._allocation_lock = threading.Lock()
			self._start_port = 9000
			self._end_port = 10000
			
			# Set up lock directory
			self._lock_dir = Path(tempfile.gettempdir()) / "browser-use-ports"
			self._lock_dir.mkdir(exist_ok=True)
			
			self._initialized = True
			print(f"[PYTHON] PortManager initialized: port range {self._start_port}-{self._end_port} ({self._end_port - self._start_port + 1} ports available)")
			print(f"[PYTHON] PortManager: Using lock directory {self._lock_dir}")
			
			# Clean up stale lock files on initialization
			self._cleanup_stale_locks()
	
	def allocate_port(self, max_retries: int = 50) -> int:
		"""
		Allocate an available port in a thread-safe manner using lock files.
		
		Args:
			max_retries: Maximum number of attempts to find a free port
			
		Returns:
			Available port number
			
		Raises:
			RuntimeError: If no available port could be found
		"""
		start_time = time.time()
		with self._allocation_lock:
			# Count current lock files for debugging
			try:
				current_locks = list(self._lock_dir.glob("*.lock"))
				lock_ports = [int(f.stem) for f in current_locks if f.stem.isdigit()]
				print(f"[PYTHON] PortManager: Starting port allocation (current lock files: {len(current_locks)}, ports: {sorted(lock_ports) if lock_ports else 'none'})")
			except Exception:
				print(f"[PYTHON] PortManager: Starting port allocation (could not enumerate current locks)")
			
			for attempt in range(max_retries):
				# Use random selection to reduce collisions
				port = random.randint(self._start_port, self._end_port)
				
				# Check if port is available (handles lock file + socket binding)
				if self._is_port_available(port):
					# Try to create lock file atomically
					if self._create_lock_file(port):
						elapsed = time.time() - start_time
						print(f"[PYTHON] PortManager: Successfully allocated port {port} after {attempt + 1} attempts in {elapsed:.3f}s")
						return port
					else:
						print(f"[PYTHON] PortManager: Attempt {attempt + 1}/{max_retries} - Port {port} available but failed to create lock file, retrying...")
				else:
					print(f"[PYTHON] PortManager: Attempt {attempt + 1}/{max_retries} - Port {port} not available (locked or in use), retrying...")
			
			# Log final failure state
			elapsed = time.time() - start_time
			print(f"[PYTHON] PortManager: FAILED to allocate port after {max_retries} attempts in {elapsed:.3f}s")
			try:
				current_locks = list(self._lock_dir.glob("*.lock"))
				lock_ports = [int(f.stem) for f in current_locks if f.stem.isdigit()]
				print(f"[PYTHON] PortManager: Current lock files ({len(current_locks)}): {sorted(lock_ports) if lock_ports else 'none'}")
			except Exception:
				print(f"[PYTHON] PortManager: Could not enumerate lock files for debugging")
			raise RuntimeError(f"Could not find available port after {max_retries} attempts")
	
	def release_port(self, port: int) -> None:
		"""Release a previously allocated port by removing its lock file."""
		with self._allocation_lock:
			success = self._remove_lock_file(port)
			if success:
				# Count remaining locks for debugging
				try:
					current_locks = list(self._lock_dir.glob("*.lock"))
					print(f"[PYTHON] PortManager: Released port {port} (remaining lock files: {len(current_locks)})")
				except Exception:
					print(f"[PYTHON] PortManager: Released port {port}")
			else:
				print(f"[PYTHON] PortManager: Warning - attempted to release port {port} but lock file was not found")
	
	def _get_lock_file_path(self, port: int) -> Path:
		"""Get the path to the lock file for a given port."""
		return self._lock_dir / f"{port}.lock"
	
	def _is_process_running(self, pid: int) -> bool:
		"""Check if a process with the given PID is still running."""
		if psutil is None:
			# Fallback: assume process might be running
			return True
		try:
			return psutil.pid_exists(pid)
		except Exception:
			# If we can't check, assume it might be running
			return True
	
	def _is_lock_stale(self, lock_path: Path, max_age_seconds: int = 1800) -> bool:
		"""Check if a lock file is stale (process dead or too old)."""
		try:
			if not lock_path.exists():
				return False
				
			with open(lock_path, 'r') as f:
				lock_data = json.load(f)
			
			# Check age (30 minutes default)
			lock_age = time.time() - lock_data.get('timestamp', 0)
			if lock_age > max_age_seconds:
				print(f"[PYTHON] PortManager: Lock file {lock_path.name} is stale (age: {lock_age:.1f}s)")
				return True
			
			# Check if process is still running
			pid = lock_data.get('pid', 0)
			if not self._is_process_running(pid):
				print(f"[PYTHON] PortManager: Lock file {lock_path.name} has dead process (pid: {pid})")
				return True
				
			return False
		except Exception as e:
			print(f"[PYTHON] PortManager: Error checking lock file {lock_path.name}: {e}")
			return True  # If we can't read it, consider it stale
	
	def _cleanup_stale_locks(self) -> None:
		"""Clean up stale lock files from dead processes."""
		try:
			cleaned = 0
			for lock_file in self._lock_dir.glob("*.lock"):
				if self._is_lock_stale(lock_file):
					try:
						lock_file.unlink()
						cleaned += 1
						print(f"[PYTHON] PortManager: Cleaned up stale lock file {lock_file.name}")
					except Exception as e:
						print(f"[PYTHON] PortManager: Failed to clean up {lock_file.name}: {e}")
			
			if cleaned > 0:
				print(f"[PYTHON] PortManager: Cleaned up {cleaned} stale lock files")
		except Exception as e:
			print(f"[PYTHON] PortManager: Error during lock cleanup: {e}")
	
	def _create_lock_file(self, port: int) -> bool:
		"""Atomically create a lock file for the given port."""
		lock_path = self._get_lock_file_path(port)
		
		# Check if lock already exists and is not stale
		if lock_path.exists() and not self._is_lock_stale(lock_path):
			return False
		
		# Clean up stale lock if it exists
		if lock_path.exists():
			try:
				lock_path.unlink()
			except Exception as e:
				print(f"[PYTHON] PortManager: Failed to remove stale lock {lock_path.name}: {e}")
				return False
		
		# Create new lock file
		try:
			lock_data = {
				"pid": os.getpid(),
				"timestamp": time.time(),
				"port": port
			}
			
			with open(lock_path, 'w') as f:
				json.dump(lock_data, f)
			
			print(f"[PYTHON] PortManager: Created lock file for port {port}")
			return True
		except Exception as e:
			print(f"[PYTHON] PortManager: Failed to create lock file for port {port}: {e}")
			return False
	
	def _remove_lock_file(self, port: int) -> bool:
		"""Remove the lock file for the given port."""
		lock_path = self._get_lock_file_path(port)
		
		try:
			if lock_path.exists():
				lock_path.unlink()
				print(f"[PYTHON] PortManager: Removed lock file for port {port}")
				return True
			else:
				print(f"[PYTHON] PortManager: Lock file for port {port} does not exist")
				return False
		except Exception as e:
			print(f"[PYTHON] PortManager: Failed to remove lock file for port {port}: {e}")
			return False
	
	def _is_port_available(self, port: int) -> bool:
		"""Check if a port is available for allocation (no lock file + socket binding works)."""
		# First check lock file
		lock_path = self._get_lock_file_path(port)
		if lock_path.exists() and not self._is_lock_stale(lock_path):
			return False
		
		# Then check socket binding
		try:
			with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
				sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
				sock.bind(('127.0.0.1', port))
				return True
		except OSError:
			return False


# Global singleton instance
_port_manager = PortManager()

def allocate_port() -> int:
	"""Allocate an available CDP debugging port."""
	return _port_manager.allocate_port()

def release_port(port: int) -> None:
	"""Release a previously allocated CDP debugging port."""
	_port_manager.release_port(port)