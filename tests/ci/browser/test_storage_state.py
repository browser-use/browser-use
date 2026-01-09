import json
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog
from browser_use.browser.events import LoadStorageStateEvent

@pytest.mark.asyncio
async def test_storage_state_origin_scoping():
    """Verify that localStorage and sessionStorage scripts are scoped to their specific origins."""
    
    # Mock browser session
    mock_session = MagicMock()
    mock_session.browser_profile.storage_state = "dummy_path.json"
    mock_session._cdp_add_init_script = AsyncMock() 
    mock_session._cdp_set_cookies = AsyncMock()
    mock_session.cdp_client = True

    # Create watchdog using construct to bypass pydantic validation of mock
    watchdog = StorageStateWatchdog.model_construct(
        browser_session=mock_session, 
        event_bus=MagicMock(),
        _logger=MagicMock()
    )
    
    # Test data with BOTH cookies and localStorage
    test_storage_data = {
        "cookies": [
             {"name": "session", "value": "val", "domain": ".example.com", "path": "/"}
        ],
        "origins": [
             {
                "origin": "https://target-origin.com",
                "localStorage": [{"name": "key1", "value": "val1"}],
                "sessionStorage": [{"name": "key2", "value": "val2"}]
            }
        ]
    }
    
    with patch('anyio.Path.read_text', new_callable=AsyncMock) as mock_read, \
         patch('os.path.exists', return_value=True):
        
        mock_read.return_value = json.dumps(test_storage_data)
        
        # Trigger the load event
        await watchdog.on_LoadStorageStateEvent(LoadStorageStateEvent(path="dummy.json"))
        
        # Verify Cookies
        assert mock_session._cdp_set_cookies.call_count == 1
        
        # Verify Scripts
        assert mock_session._cdp_add_init_script.call_count == 2 # 1 for local, 1 for session
        
        call_args = mock_session._cdp_add_init_script.call_args_list
        scripts = [c[0][0] for c in call_args]
        
        # Check strict origin scoping
        for script in scripts:
            assert 'if (window.location.origin === "https://target-origin.com")' in script
            assert 'window.location.origin ===' in script

        # Verify correct storage type
        assert any('window.localStorage.setItem("key1", "val1")' in s for s in scripts)
        assert any('window.sessionStorage.setItem("key2", "val2")' in s for s in scripts)

