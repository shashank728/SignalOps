from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid

class SignalPayload(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    component_id: str
    component_type: str
    severity: str
    error_code: str = Field(max_length=64)
    message: str = Field(min_length=1, max_length=512)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    @field_validator('component_type')
    @classmethod
    def check_component_type(cls, v: str) -> str:
        allowed = {"CACHE", "RDBMS", "API", "MCP_HOST", "QUEUE", "NOSQL"}
        if v not in allowed:
            raise ValueError(f"component_type must be one of {allowed}")
        return v

    @field_validator('severity')
    @classmethod
    def check_severity(cls, v: str) -> str:
        allowed = {"P0", "P1", "P2", "P3"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v

    @field_validator('timestamp')
    @classmethod
    def check_timestamp(cls, v: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        if v > now and (v - now).total_seconds() > 60:
            raise ValueError("timestamp cannot be more than 60s in the future")
        return v

class WorkItemStatusUpdate(BaseModel):
    status: str

class RCAPayload(BaseModel):
    incident_start: datetime
    incident_end: datetime
    root_cause_category: str
    fix_applied: str = Field(min_length=20)
    prevention_steps: str = Field(min_length=20)

    @field_validator('incident_end')
    @classmethod
    def check_dates(cls, v: datetime, info) -> datetime:
        if 'incident_start' in info.data and v <= info.data['incident_start']:
            raise ValueError("incident_end must be after incident_start")
        return v

    @field_validator('root_cause_category')
    @classmethod
    def check_category(cls, v: str) -> str:
        allowed = {
            "Infrastructure Failure", "Software Bug", "Configuration Error", 
            "Human Error", "Third-Party Dependency", "Capacity Exhaustion", 
            "Security Incident", "Unknown"
        }
        if v not in allowed:
            raise ValueError(f"root_cause_category must be one of {allowed}")
        return v
