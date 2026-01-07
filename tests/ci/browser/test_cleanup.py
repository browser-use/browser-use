
import asyncio
import os
import shutil
from pathlib import Path
import pytest
from browser_use.browser.session import BrowserSession
from browser_use.browser.profile import BrowserProfile

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
    
    assert Path(user_data_dir).exists()
    assert Path(downloads_path).exists()
    
    await session.stop()
    
    assert not Path(user_data_dir).exists()
    assert not Path(downloads_path).exists()

@pytest.mark.asyncio
async def test_cleanup_on_close_disabled():
    """Verify that temp files are preserved when cleanup_on_close is False (default)"""
    session = BrowserSession(headless=True, cleanup_on_close=False)
    
    user_data_dir = session.browser_profile.user_data_dir
    downloads_path = session.browser_profile.downloads_path
    
    assert user_data_dir is not None
    assert downloads_path is not None
    
    await session.start()
    
    assert Path(user_data_dir).exists()
    assert Path(downloads_path).exists()
    
    await session.stop()
    
    assert Path(user_data_dir).exists()
    assert Path(downloads_path).exists()
    
    # Cleanup manually
    shutil.rmtree(user_data_dir, ignore_errors=True)
    shutil.rmtree(downloads_path, ignore_errors=True)

@pytest.mark.asyncio
async def test_cleanup_default_behavior():
    """Verify default behavior (cleanup_on_close=False)"""
    session = BrowserSession(headless=True)
    
    user_data_dir = session.browser_profile.user_data_dir
    downloads_path = session.browser_profile.downloads_path
    
    assert not session.browser_profile.cleanup_on_close
    
    await session.start()
    await session.stop()
    
    assert Path(user_data_dir).exists()
    assert Path(downloads_path).exists()
    
    # Cleanup manually
    shutil.rmtree(user_data_dir, ignore_errors=True)
    shutil.rmtree(downloads_path, ignore_errors=True)

@pytest.mark.asyncio
async def test_cleanup_custom_paths_safe():
    """Verify that custom (non-auto-generated) paths are NOT deleted even if cleanup_on_close is True"""
    # Create custom user dir
    custom_dir = Path("./custom_user_data_test").resolve()
    custom_dir.mkdir(exist_ok=True)
    
    session = BrowserSession(
        headless=True, 
        cleanup_on_close=True,
        user_data_dir=custom_dir
    )
    
    # downloads_path will still be auto-generated since we didn't specify it
    downloads_path = session.browser_profile.downloads_path
    
    await session.start()
    await session.stop()
    
    # Custom dir should still exist (safety check)
    assert custom_dir.exists()
    
    # Auto-generated downloads should be gone
    assert not Path(downloads_path).exists()
    
    # Cleanup manually
    shutil.rmtree(custom_dir, ignore_errors=True)
