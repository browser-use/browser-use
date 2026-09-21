"""
GIF generation utilities for browser agent sessions.

This module provides functionality to create animated GIFs from a sequence of
screenshots captured during a browser agent's execution. This is useful for
visualizing the agent's actions and debugging.
"""

import os
import logging
from typing import List, Optional, Union
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None
    logging.warning("Pillow (PIL) is not installed. GIF generation will not be available. Install it with: pip install Pillow")

logger = logging.getLogger(__name__)


def create_gif(
    image_paths: List[Union[str, Path]],
    output_path: Union[str, Path],
    duration: int = 500,
    loop: int = 0,
    resize: Optional[tuple] = None,
    quality: int = 80,
) -> Optional[Path]:
    """
    Create an animated GIF from a list of image file paths.

    Args:
        image_paths: List of paths to image files (PNG, JPEG, etc.).
        output_path: Path where the GIF will be saved.
        duration: Duration of each frame in milliseconds.
        loop: Number of times to loop the GIF (0 = infinite).
        resize: Optional tuple (width, height) to resize frames to.
        quality: JPEG quality for intermediate processing (if applicable).

    Returns:
        Path to the created GIF file, or None if creation failed.
    """
    if Image is None:
        logger.error("Pillow is not installed. Cannot create GIF.")
        return None

    if not image_paths:
        logger.warning("No image paths provided. Cannot create GIF.")
        return None

    # Validate that all image files exist
    valid_paths = []
    for path in image_paths:
        p = Path(path)
        if p.exists():
            valid_paths.append(p)
        else:
            logger.warning(f"Image file not found: {p}. Skipping.")

    if not valid_paths:
        logger.error("No valid image files found. Cannot create GIF.")
        return None

    try:
        # Load all images
        images = []
        for path in valid_paths:
            try:
                img = Image.open(path)
                # Convert to RGB if necessary (GIF doesn't support alpha well)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                
                # Resize if specified
                if resize:
                    img = img.resize(resize, Image.Resampling.LANCZOS)
                
                images.append(img)
            except Exception as e:
                logger.warning(f"Failed to load image {path}: {e}. Skipping.")
                continue

        if not images:
            logger.error("No images could be loaded. Cannot create GIF.")
            return None

        # Ensure output directory exists
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save as GIF
        # Note: PIL's save method for GIF uses 'duration' in milliseconds
        # and 'loop' for infinite looping (0) or specific count
        images[0].save(
            output_path,
            save_all=True,
            append_images=images[1:],
            duration=duration,
            loop=loop,
            optimize=True,
        )

        logger.info(f"GIF created successfully: {output_path} ({len(images)} frames)")
        return output_path

    except Exception as e:
        logger.error(f"Failed to create GIF: {e}")
        return None


def create_gif_from_bytes(
    image_data_list: List[bytes],
    output_path: Union[str, Path],
    duration: int = 500,
    loop: int = 0,
    resize: Optional[tuple] = None,
) -> Optional[Path]:
    """
    Create an animated GIF from a list of image byte strings.

    Args:
        image_data_list: List of byte strings containing image data.
        output_path: Path where the GIF will be saved.
        duration: Duration of each frame in milliseconds.
        loop: Number of times to loop the GIF (0 = infinite).
        resize: Optional tuple (width, height) to resize frames to.

    Returns:
        Path to the created GIF file, or None if creation failed.
    """
    if Image is None:
        logger.error("Pillow is not installed. Cannot create GIF.")
        return None

    if not image_data_list:
        logger.warning("No image data provided. Cannot create GIF.")
        return None

    try:
        import io

        images = []
        for data in image_data_list:
            try:
                img = Image.open(io.BytesIO(data))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                
                if resize:
                    img = img.resize(resize, Image.Resampling.LANCZOS)
                
                images.append(img)
            except Exception as e:
                logger.warning(f"Failed to decode image data: {e}. Skipping.")
                continue

        if not images:
            logger.error("No images could be decoded. Cannot create GIF.")
            return None

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        images[0].save(
            output_path,
            save_all=True,
            append_images=images[1:],
            duration=duration,
            loop=loop,
            optimize=True,
        )

        logger.info(f"GIF created successfully from bytes: {output_path} ({len(images)} frames)")
        return output_path

    except Exception as e:
        logger.error(f"Failed to create GIF from bytes: {e}")
        return None
