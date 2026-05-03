from typing import Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class InvalidTransitionError(Exception):
    pass

class RCAIncompleteError(Exception):
    def __init__(self, message: str, fields: list = None):
        super().__init__(message)
        self.fields = fields or []

class WorkItemState:
    name = "UNKNOWN"

    def can_transition_to(self, new_state: str) -> bool:
        return False

    async def on_enter(self, work_item: dict, db_conn, rca_record: dict = None) -> None:
        pass

    async def on_exit(self, work_item: dict, db_conn) -> None:
        pass

class OpenState(WorkItemState):
    name = "OPEN"

    def can_transition_to(self, new_state: str) -> bool:
        return new_state in ("INVESTIGATING",)

class InvestigatingState(WorkItemState):
    name = "INVESTIGATING"

    def can_transition_to(self, new_state: str) -> bool:
        return new_state in ("RESOLVED",)

class ResolvedState(WorkItemState):
    name = "RESOLVED"

    def can_transition_to(self, new_state: str) -> bool:
        return new_state in ("CLOSED", "INVESTIGATING")

    async def on_enter(self, work_item: dict, db_conn, rca_record: dict = None) -> None:
        # Set end_time
        await db_conn.execute(
            "UPDATE work_items SET end_time = $1 WHERE id = $2",
            datetime.now(timezone.utc), work_item["id"]
        )

class ClosedState(WorkItemState):
    name = "CLOSED"

    def can_transition_to(self, new_state: str) -> bool:
        return False # Terminal state

    async def on_enter(self, work_item: dict, db_conn, rca_record: dict = None) -> None:
        if not rca_record:
            raise RCAIncompleteError("Cannot close incident without RCA record.")
        
        # Validation is already done at insertion time of RCA, but we can double check
        # Business rules: fix_applied >= 20 chars, prevention_steps >= 20 chars, start < end
        if len(rca_record["fix_applied"]) < 20:
            raise RCAIncompleteError("fix_applied must be at least 20 chars.", ["fix_applied"])
        if len(rca_record["prevention_steps"]) < 20:
            raise RCAIncompleteError("prevention_steps must be at least 20 chars.", ["prevention_steps"])
        if rca_record["incident_start"] >= rca_record["incident_end"]:
            raise RCAIncompleteError("incident_end must be after incident_start.", ["incident_end"])

        # Calculate MTTR
        mttr_seconds = int((rca_record["incident_end"] - work_item["start_time"]).total_seconds())
        await db_conn.execute(
            "UPDATE work_items SET mttr_seconds = $1 WHERE id = $2",
            mttr_seconds, work_item["id"]
        )

STATE_MAP = {
    "OPEN": OpenState(),
    "INVESTIGATING": InvestigatingState(),
    "RESOLVED": ResolvedState(),
    "CLOSED": ClosedState()
}

class WorkItemStateMachine:
    @staticmethod
    async def transition(work_item: dict, new_state_name: str, db_conn, rca_record: dict = None):
        current_state_name = work_item["status"]
        if current_state_name == new_state_name:
            raise InvalidTransitionError("Already in this state")

        current_state = STATE_MAP.get(current_state_name)
        if not current_state:
            raise InvalidTransitionError(f"Unknown current state: {current_state_name}")

        if not current_state.can_transition_to(new_state_name):
            if current_state_name == "CLOSED":
                raise InvalidTransitionError("Work item is closed and immutable")
            raise InvalidTransitionError(f"Invalid transition from {current_state_name} to {new_state_name}")

        new_state = STATE_MAP.get(new_state_name)
        if not new_state:
            raise InvalidTransitionError(f"Unknown new state: {new_state_name}")

        await current_state.on_exit(work_item, db_conn)
        
        # We perform on_enter which might raise RCAIncompleteError
        await new_state.on_enter(work_item, db_conn, rca_record)
        
        # If we reach here, it's valid to update status
        await db_conn.execute(
            "UPDATE work_items SET status = $1, updated_at = $2 WHERE id = $3",
            new_state_name, datetime.now(timezone.utc), work_item["id"]
        )
