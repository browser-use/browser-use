"""Video Recording Service for Browser Use Sessions."""

import base64
import io
import logging
import math
from pathlib import Path
from typing import Optional

from browser_use.browser.profile import ViewportSize

try:
	import imageio.v2 as iio  # type: ignore[import-not-found]
	import numpy as np  # type: ignore[import-not-found]
	from imageio.core.format import Format  # type: ignore[import-not-found]
	from PIL import Image

	IMAGEIO_AVAILABLE = True
except ImportError:
	IMAGEIO_AVAILABLE = False

logger = logging.getLogger(__name__)


def _get_padded_size(size: ViewportSize, macro_block_size: int = 16) -> ViewportSize:
	"""Calculates the dimensions padded to the nearest multiple of macro_block_size."""
	width = int(math.ceil(size['width'] / macro_block_size)) * macro_block_size
	height = int(math.ceil(size['height'] / macro_block_size)) * macro_block_size
	return ViewportSize(width=width, height=height)


class VideoRecorderService:
	"""
	Handles the video encoding process for a browser session using imageio.

	This service captures individual frames from the CDP screencast, decodes them,
	and appends them to a video file using a pip-installable ffmpeg backend.
	It automatically resizes frames to match the target video dimensions.
	"""

	def __init__(self, output_path: Path, size: ViewportSize, framerate: int):
		"""
		Initializes the video recorder.

		Args:
		    output_path: The full path where the video will be saved.
		    size: A ViewportSize object specifying the width and height of the video.
		    framerate: The desired framerate for the output video.
		"""
		self.output_path = output_path
		self.size = size
		self.framerate = framerate
		self._writer: Optional['Format.Writer'] = None
		self._is_active = False
		self.padded_size = _get_padded_size(self.size)

	def start(self) -> None:
		"""
		Prepares and starts the video writer.

		If the required optional dependencies are not installed, this method will
		log an error and do nothing.
		"""
		if not IMAGEIO_AVAILABLE:
			logger.error(
				'MP4 recording requires optional dependencies. Please install them with: pip install "browser-use[video]"'
			)
			return

		try:
			self.output_path.parent.mkdir(parents=True, exist_ok=True)
			# The macro_block_size is set to None because we handle padding ourselves
			self._writer = iio.get_writer(
				str(self.output_path),
				fps=self.framerate,
				codec='libx264',
				quality=8,  # A good balance of quality and file size (1-10 scale)
				pixelformat='yuv420p',  # Ensures compatibility with most players
				macro_block_size=None,
			)
			self._is_active = True
			logger.debug(f'Video recorder started. Output will be saved to {self.output_path}')
		except Exception as e:
			logger.error(f'Failed to initialize video writer: {e}')
			self._is_active = False

	def add_frame(self, frame_data_b64: str) -> None:
		"""
		Decodes a base64-encoded PNG frame, resizes it, pads it to be codec-compatible,
		and appends it to the video.

		Args:
		    frame_data_b64: A base64-encoded string of the PNG frame data.
		"""
		if not self._is_active or not self._writer:
			return

		try:
			frame_bytes = base64.b64decode(frame_data_b64)

			# Use PIL to handle image processing in memory - much faster than spawning ffmpeg subprocess per frame
			with Image.open(io.BytesIO(frame_bytes)) as img:
				# 1. Resize if needed to target viewport size
				if img.size != (self.size['width'], self.size['height']):
					# Use BICUBIC as it's faster than LANCZOS and good enough for screen recordings
					img = img.resize((self.size['width'], self.size['height']), Image.Resampling.BICUBIC)

				# 2. Handle Padding (Macro block alignment for codecs)
				# Check if padding is actually needed
				if self.padded_size['width'] != self.size['width'] or self.padded_size['height'] != self.size['height']:
					new_img = Image.new('RGB', (self.padded_size['width'], self.padded_size['height']), (0, 0, 0))
					# Center the image
					x_offset = (self.padded_size['width'] - self.size['width']) // 2
					y_offset = (self.padded_size['height'] - self.size['height']) // 2
					new_img.paste(img, (x_offset, y_offset))
					img = new_img

				# 3. Convert to numpy array for imageio
				img_array = np.array(img)

			self._writer.append_data(img_array)
		except Exception as e:
			logger.warning(f'Could not process and add video frame: {e}')

	def stop_and_save(self) -> None:
		"""
		Finalizes the video file by closing the writer.

		This method should be called when the recording session is complete.
		"""
		if not self._is_active or not self._writer:
			return

		try:
			self._writer.close()
			logger.info(f'📹 Video recording saved successfully to: {self.output_path}')
		except Exception as e:
			logger.error(f'Failed to finalize and save video: {e}')
		finally:
			self._is_active = False
			self._writer = None
