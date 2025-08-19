"""
Thread-safe port management for CDP debugging ports.

Fixes race conditions when multiple browser sessions try to allocate ports simultaneously.
"""

import random
import socket
import threading
from typing import Set


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
			self._allocated_ports: Set[int] = set()
			self._start_port = 9000
			self._end_port = 10000
			self._initialized = True
	
	def allocate_port(self, max_retries: int = 50) -> int:
		"""
		Allocate an available port in a thread-safe manner.
		
		Args:
			max_retries: Maximum number of attempts to find a free port
			
		Returns:
			Available port number
			
		Raises:
			RuntimeError: If no available port could be found
		"""
		with self._allocation_lock:
			for _ in range(max_retries):
				# Use random selection to reduce collisions
				port = random.randint(self._start_port, self._end_port)
				
				# Skip already allocated ports
				if port in self._allocated_ports:
					continue
					
				# Verify port is actually available
				if self._is_port_available(port):
					self._allocated_ports.add(port)
					return port
			
			raise RuntimeError(f"Could not find available port after {max_retries} attempts")
	
	def release_port(self, port: int) -> None:
		"""Release a previously allocated port."""
		with self._allocation_lock:
			self._allocated_ports.discard(port)
	
	def _is_port_available(self, port: int) -> bool:
		"""Check if a port is available for binding."""
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