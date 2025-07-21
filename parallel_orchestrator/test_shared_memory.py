"""
Test script for SharedMemory class

This script tests all the functionality of the SharedMemory class to ensure
it works correctly in a multi-agent environment.
"""

import asyncio
import logging
from shared_memory import SharedMemory

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_shared_memory():
    """Test all SharedMemory functionality."""
    print("🧪 Testing SharedMemory class...")
    
    # Create shared memory instance
    shared_memory = SharedMemory()
    print(f"✅ Created SharedMemory instance: {shared_memory}")
    
    # Test 1: Write and read operations
    print("\n📝 Test 1: Write and read operations")
    await shared_memory.write("task_001", {"email": "contact@perplexity.ai", "status": "completed"})
    await shared_memory.write("task_002", {"email": "contact@anthropic.com", "status": "completed"})
    
    result1 = await shared_memory.read("task_001")
    result2 = await shared_memory.read("task_002")
    
    print(f"✅ Task 001 result: {result1}")
    print(f"✅ Task 002 result: {result2}")
    
    # Test 2: Get all results
    print("\n📋 Test 2: Get all results")
    all_results = await shared_memory.get_all()
    print(f"✅ All results: {all_results}")
    
    # Test 3: Check task existence
    print("\n🔍 Test 3: Check task existence")
    exists_001 = await shared_memory.has_task("task_001")
    exists_003 = await shared_memory.has_task("task_003")
    print(f"✅ Task 001 exists: {exists_001}")
    print(f"✅ Task 003 exists: {exists_003}")
    
    # Test 4: Get task count
    print("\n📊 Test 4: Get task count")
    count = await shared_memory.get_task_count()
    print(f"✅ Total tasks: {count}")
    
    # Test 5: Remove task
    print("\n🗑️ Test 5: Remove task")
    removed = await shared_memory.remove_task("task_001")
    print(f"✅ Task 001 removed: {removed}")
    
    # Verify removal
    exists_after_removal = await shared_memory.has_task("task_001")
    print(f"✅ Task 001 exists after removal: {exists_after_removal}")
    
    # Test 6: Clear all
    print("\n🧹 Test 6: Clear all")
    await shared_memory.clear()
    count_after_clear = await shared_memory.get_task_count()
    print(f"✅ Tasks after clear: {count_after_clear}")
    
    # Test 7: Concurrent access simulation
    print("\n⚡ Test 7: Concurrent access simulation")
    
    async def concurrent_writer(worker_id: int, shared_mem: SharedMemory):
        """Simulate concurrent writing from multiple workers."""
        for i in range(3):
            task_id = f"worker_{worker_id}_task_{i}"
            result = {"worker_id": worker_id, "task_num": i, "data": f"result_{i}"}
            await shared_mem.write(task_id, result)
            await asyncio.sleep(0.1)  # Simulate some work
            print(f"  Worker {worker_id} wrote task {task_id}")
    
    # Create multiple concurrent writers
    writers = [
        concurrent_writer(1, shared_memory),
        concurrent_writer(2, shared_memory),
        concurrent_writer(3, shared_memory)
    ]
    
    # Run all writers concurrently
    await asyncio.gather(*writers)
    
    # Check final state
    final_results = await shared_memory.get_all()
    final_count = await shared_memory.get_task_count()
    print(f"✅ Final results count: {final_count}")
    print(f"✅ Final results: {final_results}")
    
    print("\n🎉 All tests completed successfully!")
    print(f"Final SharedMemory state: {shared_memory}")

async def main():
    """Main test function."""
    try:
        await test_shared_memory()
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 