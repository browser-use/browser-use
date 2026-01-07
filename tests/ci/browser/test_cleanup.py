
import shutil
from pathlib import Path

import pytest

from browser_use.browser.session import BrowserSession


@pytest.mark.asyncio
async def test_cleanup_on_close_enabled():
    """Verify that temp files are cleaned up when cleanup_on_close is True"""
    session = BrowserSession(headless=True, cleanup_on_close=True)
    
    user_data_dir = session.browser_profile.user_data_dir
    downloads_path = session.browser_profile.downloads_path
    
    assert user_data_dir is not None
    assert downloads_path is not None
    
    # Start session to ensure dirs are created
    await session.start()
    
    if user_data_dir:
        assert Path(user_data_dir).exists()
    if downloads_path:
        assert Path(downloads_path).exists()
    
    await session.stop()
    
    if user_data_dir:
        assert not Path(user_data_dir).exists()
    if downloads_path:
        assert not Path(downloads_path).exists()

@pytest.mark.asyncio
async def test_cleanup_on_close_disabled():
    """Verify that temp files are preserved when cleanup_on_close is False (default)"""
    session = BrowserSession(headless=True, cleanup_on_close=False)
    
    user_data_dir = session.browser_profile.user_data_dir
    downloads_path = session.browser_profile.downloads_path
    
    try:
        await session.start()
        
        if user_data_dir:
            assert Path(user_data_dir).exists()
        if downloads_path:
            assert Path(downloads_path).exists()
        
        await session.stop()
        
        if user_data_dir:
            assert Path(user_data_dir).exists()
        if downloads_path:
            assert Path(downloads_path).exists()
    finally:
        # Cleanup manually
        if user_data_dir:
            shutil.rmtree(user_data_dir, ignore_errors=True)
        if downloads_path:
            shutil.rmtree(downloads_path, ignore_errors=True)

@pytest.mark.asyncio
async def test_cleanup_default_behavior():
    """Verify default behavior (cleanup_on_close=False)"""
    session = BrowserSession(headless=True)
    
    user_data_dir = session.browser_profile.user_data_dir
    downloads_path = session.browser_profile.downloads_path
    
    assert not session.browser_profile.cleanup_on_close
    
    try:
        await session.start()
        await session.stop()
        
        if user_data_dir:
            assert Path(user_data_dir).exists()
        if downloads_path:
            assert Path(downloads_path).exists()
    finally:
        # Cleanup manually
        if user_data_dir:
            shutil.rmtree(user_data_dir, ignore_errors=True)
        if downloads_path:
            shutil.rmtree(downloads_path, ignore_errors=True)

@pytest.mark.asyncio
async def test_cleanup_custom_paths_safe(tmp_path):
    """Verify that custom (non-auto-generated) paths are NOT deleted even if cleanup_on_close is True"""
    # Create custom user dir using tmp_path for isolation
    custom_dir = tmp_path / "custom_user_data_test"
    custom_dir.mkdir(parents=True, exist_ok=True)
    
    session = BrowserSession(
        headless=True, 
        cleanup_on_close=True,
        user_data_dir=custom_dir
    )
    
    # downloads_path will still be auto-generated
    downloads_path = session.browser_profile.downloads_path
    
    await session.start()
    await session.stop()
    
    # Custom dir should still exist (safety check)
    assert custom_dir.exists()
    
    # Auto-generated downloads should be gone
    if downloads_path:
        assert not Path(downloads_path).exists()
