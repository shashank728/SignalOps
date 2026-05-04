import pytest
import asyncio
import time
from src.ingestion import process_signals_batch, signal_queue, debounce_store
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def clear_state():
    # Clear the queue and debounce store before each test
    while not signal_queue.empty():
        signal_queue.get_nowait()
    debounce_store.clear()

@pytest.fixture
def dummy_signal():
    return {
        "component_id": "TEST_COMP_1",
        "component_type": "API",
        "severity": "P1",
        "timestamp": "2023-01-01T00:00:00Z"
    }

@pytest.mark.asyncio
@patch('src.ingestion.create_work_item')
async def test_100_signals_create_one_work_item(mock_create):
    mock_create.return_value = asyncio.Future()
    mock_create.return_value.set_result(None)

    worker_task = asyncio.create_task(process_signals_batch())

    # Send 100 signals
    for _ in range(100):
        await signal_queue.put({
            "component_id": "TEST_COMP_1",
            "component_type": "API",
            "severity": "P1",
            "timestamp": "2023-01-01T00:00:00Z"
        })

    # Wait for queue to process
    await asyncio.sleep(0.1)

    # Should have called create_work_item exactly once
    assert mock_create.call_count == 1
    
    # Store should be empty for this component after creation
    assert "TEST_COMP_1" not in debounce_store

    worker_task.cancel()

@pytest.mark.asyncio
@patch('src.ingestion.create_work_item')
async def test_signals_in_different_windows_create_separate_work_items(mock_create):
    mock_create.return_value = asyncio.Future()
    mock_create.return_value.set_result(None)

    worker_task = asyncio.create_task(process_signals_batch())

    # We can mock time.time to simulate window passing
    with patch('time.time') as mock_time:
        mock_time.return_value = 1000.0
        
        # Send 99 signals (no work item created)
        for _ in range(99):
            await signal_queue.put({
                "component_id": "TEST_COMP_1",
                "component_type": "API",
                "severity": "P1",
                "timestamp": "2023-01-01T00:00:00Z"
            })
            
        await asyncio.sleep(0.1)
        assert mock_create.call_count == 0

        # Advance time by 11 seconds (window expires)
        mock_time.return_value = 1011.0
        
        # Send 1 more signal. Previous window expired, so it starts a new window
        await signal_queue.put({
            "component_id": "TEST_COMP_1",
            "component_type": "API",
            "severity": "P1",
            "timestamp": "2023-01-01T00:00:00Z"
        })
        
        await asyncio.sleep(0.1)
        assert mock_create.call_count == 0
        
        # Now send 99 more signals in this new window -> hits 100
        for _ in range(99):
            await signal_queue.put({
                "component_id": "TEST_COMP_1",
                "component_type": "API",
                "severity": "P1",
                "timestamp": "2023-01-01T00:00:00Z"
            })

        await asyncio.sleep(0.1)
        assert mock_create.call_count == 1

    worker_task.cancel()
