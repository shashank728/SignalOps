from abc import ABC, abstractmethod
import logging
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)

class Alert:
    def __init__(self, work_item_id: str, alert_type: str, message: str):
        self.alert_id = str(uuid.uuid4())
        self.work_item_id = work_item_id
        self.alert_type = alert_type
        self.message = message
        self.notified_at = datetime.now(timezone.utc).isoformat()
        self.channels = ["slack", "pagerduty"]

    def to_dict(self):
        return {
            "alert_id": self.alert_id,
            "work_item_id": self.work_item_id,
            "alert_type": self.alert_type,
            "message": self.message,
            "notified_at": self.notified_at,
            "channels": self.channels
        }

class AlertStrategy(ABC):
    @abstractmethod
    def build_alert(self, work_item: dict) -> Alert:
        pass

class P0DatabaseAlert(AlertStrategy):
    def build_alert(self, work_item: dict) -> Alert:
        return Alert(work_item["id"], "P0_DATABASE_CRITICAL", f"CRITICAL: RDBMS outage detected for {work_item['component_id']}")

class P1APIAlert(AlertStrategy):
    def build_alert(self, work_item: dict) -> Alert:
        return Alert(work_item["id"], "P1_API_DEGRADED", f"HIGH: API degradation detected for {work_item['component_id']}")

class P2CacheAlert(AlertStrategy):
    def build_alert(self, work_item: dict) -> Alert:
        return Alert(work_item["id"], "P2_CACHE_ISSUE", f"MEDIUM: Cache issue detected for {work_item['component_id']}")

class P3QueueAlert(AlertStrategy):
    def build_alert(self, work_item: dict) -> Alert:
        return Alert(work_item["id"], "P3_QUEUE_DELAY", f"LOW: Queue delays detected for {work_item['component_id']}")

class GenericAlert(AlertStrategy):
    def build_alert(self, work_item: dict) -> Alert:
        return Alert(work_item["id"], f"{work_item['severity']}_{work_item['component_type']}_ALERT", f"Alert for {work_item['component_id']}")

ALERT_STRATEGY_MAP = {
    ("RDBMS", "P0"): P0DatabaseAlert(),
    ("API", "P1"): P1APIAlert(),
    ("CACHE", "P2"): P2CacheAlert(),
    ("QUEUE", "P3"): P3QueueAlert(),
}

def generate_alert(work_item: dict) -> Alert:
    strategy = ALERT_STRATEGY_MAP.get((work_item["component_type"], work_item["severity"]), GenericAlert())
    alert = strategy.build_alert(work_item)
    # Log to console
    logger.error(f"[ALERT GENERATED] {alert.to_dict()}")
    # Simulate webhook
    try:
        with open("webhooks.log", "a") as f:
            import json
            f.write(json.dumps(alert.to_dict()) + "\n")
    except Exception as e:
        logger.error(f"Failed to write to webhooks.log: {e}")
    return alert
