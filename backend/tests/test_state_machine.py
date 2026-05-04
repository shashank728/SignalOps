import pytest
from src.state_machine import WorkItemStateMachine, OpenState, InvestigatingState, ResolvedState, ClosedState, InvalidTransitionError, RCAIncompleteError
from datetime import datetime, timezone, timedelta

class MockDBConn:
    async def execute(self, *args, **kwargs):
        pass

@pytest.fixture
def mock_db():
    return MockDBConn()

@pytest.fixture
def base_work_item():
    return {
        "id": "123",
        "status": "OPEN",
        "start_time": datetime.now(timezone.utc) - timedelta(hours=1)
    }

@pytest.fixture
def valid_rca():
    return {
        "incident_start": datetime.now(timezone.utc) - timedelta(minutes=30),
        "incident_end": datetime.now(timezone.utc) - timedelta(minutes=10),
        "fix_applied": "We applied a hotfix to correct the connection pool limit and increased it to 200.",
        "prevention_steps": "Added auto-scaling policies to the connection pool and set up proactive alerts."
    }

@pytest.mark.asyncio
async def test_rca_rejected_if_fix_applied_too_short(base_work_item, valid_rca, mock_db):
    valid_rca["fix_applied"] = "short"
    base_work_item["status"] = "RESOLVED"
    
    with pytest.raises(RCAIncompleteError) as excinfo:
        await WorkItemStateMachine.transition(base_work_item, "CLOSED", mock_db, valid_rca)
    assert "fix_applied must be at least 20 chars" in str(excinfo.value)

@pytest.mark.asyncio
async def test_rca_rejected_if_prevention_steps_missing(base_work_item, valid_rca, mock_db):
    valid_rca["prevention_steps"] = ""
    base_work_item["status"] = "RESOLVED"
    
    with pytest.raises(RCAIncompleteError) as excinfo:
        await WorkItemStateMachine.transition(base_work_item, "CLOSED", mock_db, valid_rca)
    assert "prevention_steps must be at least 20 chars" in str(excinfo.value)

@pytest.mark.asyncio
async def test_rca_rejected_if_end_before_start(base_work_item, valid_rca, mock_db):
    valid_rca["incident_end"] = valid_rca["incident_start"] - timedelta(minutes=10)
    base_work_item["status"] = "RESOLVED"
    
    with pytest.raises(RCAIncompleteError) as excinfo:
        await WorkItemStateMachine.transition(base_work_item, "CLOSED", mock_db, valid_rca)
    assert "incident_end must be after incident_start" in str(excinfo.value)

@pytest.mark.asyncio
async def test_rca_accepted_with_valid_data(base_work_item, valid_rca, mock_db):
    base_work_item["status"] = "RESOLVED"
    # Should not raise any exception
    await WorkItemStateMachine.transition(base_work_item, "CLOSED", mock_db, valid_rca)

@pytest.mark.asyncio
async def test_closed_transition_rejected_without_rca(base_work_item, mock_db):
    base_work_item["status"] = "RESOLVED"
    with pytest.raises(RCAIncompleteError):
        await WorkItemStateMachine.transition(base_work_item, "CLOSED", mock_db, None)

@pytest.mark.asyncio
async def test_cannot_transition_from_closed(base_work_item, mock_db):
    base_work_item["status"] = "CLOSED"
    with pytest.raises(InvalidTransitionError) as excinfo:
        await WorkItemStateMachine.transition(base_work_item, "OPEN", mock_db)
    assert "Work item is closed and immutable" in str(excinfo.value)

@pytest.mark.asyncio
async def test_valid_transitions(base_work_item, valid_rca, mock_db):
    await WorkItemStateMachine.transition(base_work_item, "INVESTIGATING", mock_db)
    base_work_item["status"] = "INVESTIGATING"
    
    await WorkItemStateMachine.transition(base_work_item, "RESOLVED", mock_db)
    base_work_item["status"] = "RESOLVED"
    
    await WorkItemStateMachine.transition(base_work_item, "CLOSED", mock_db, valid_rca)

@pytest.mark.asyncio
async def test_regression_allowed(base_work_item, mock_db):
    base_work_item["status"] = "RESOLVED"
    # RESOLVED -> INVESTIGATING is allowed
    await WorkItemStateMachine.transition(base_work_item, "INVESTIGATING", mock_db)
