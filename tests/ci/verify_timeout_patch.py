
import asyncio
import pytest
from bubus import BaseEvent, EventBus

class SlowEvent(BaseEvent):
    """Test event that takes a long time to process."""
    pass

class TestTimeoutPatch:
    @pytest.mark.asyncio
    async def test_slow_handler_does_not_timeout(self):
        """Verify that a handler taking 40s does not timeout (default should be 60s with patch)."""
        bus = EventBus()
        
        async def on_SlowEvent(event: SlowEvent):
            print("Processing slow event...")
            await asyncio.sleep(40) # Sleep longer than default 30s but less than patched 60s
            print("Slow event done!")
            return "success"
            
        bus.on(SlowEvent, on_SlowEvent)
        
        print("Dispatching slow event...")
        # valid_result=True ensures we wait for completion
        result = await bus.dispatch(SlowEvent())
        final_result = await result.event_result()
        
        assert final_result == "success"
        print("Test passed: 40s handler completed successfully")

if __name__ == "__main__":
    import asyncio
    test = TestTimeoutPatch()
    asyncio.run(test.test_slow_handler_does_not_timeout())
