import time
from enum import Enum
import structlog
from typing import Dict, Any

logger = structlog.get_logger(__name__)

class CircuitState(Enum):
    CLOSED = "CLOSED"       # Healthy, requests pass through
    OPEN = "OPEN"           # Failing, requests blocked
    HALF_OPEN = "HALF_OPEN" # Testing recovery, 1 request passes through

class ModelCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._states: Dict[str, CircuitState] = {}
        self._failure_counts: Dict[str, int] = {}
        self._last_failure_times: Dict[str, float] = {}

    def get_state(self, model_id: str) -> CircuitState:
        """Determines the current state of the circuit for a given model."""
        state = self._states.get(model_id, CircuitState.CLOSED)
        
        if state == CircuitState.OPEN:
            last_failure = self._last_failure_times.get(model_id, 0)
            if time.time() - last_failure > self.recovery_timeout:
                logger.info(f"Circuit for {model_id} entering HALF_OPEN state.")
                self._states[model_id] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN
                
        return state

    def is_open(self, model_id: str) -> bool:
        """Returns True if requests should be blocked."""
        return self.get_state(model_id) == CircuitState.OPEN

    def get_remaining_recovery_time(self, model_id: str) -> int:
        """Returns the number of seconds remaining until circuit attempts recovery, or 0."""
        state = self._states.get(model_id, CircuitState.CLOSED)
        if state != CircuitState.OPEN:
            return 0
        last_failure = self._last_failure_times.get(model_id, 0)
        elapsed = time.time() - last_failure
        remaining = int(self.recovery_timeout - elapsed)
        return max(0, remaining)


    def record_success(self, model_id: str):
        """Records a successful request, resetting the circuit if needed."""
        state = self.get_state(model_id)
        if state == CircuitState.HALF_OPEN:
            logger.info(f"Circuit for {model_id} recovered. Entering CLOSED state.")
        self._states[model_id] = CircuitState.CLOSED
        self._failure_counts[model_id] = 0

    def record_failure(self, model_id: str):
        """Records a failed request, potentially opening the circuit."""
        state = self.get_state(model_id)
        if state == CircuitState.HALF_OPEN:
            # Failed during test, go straight back to OPEN
            logger.warning(f"Circuit for {model_id} failed recovery test. Entering OPEN state.")
            self._states[model_id] = CircuitState.OPEN
            self._last_failure_times[model_id] = time.time()
        elif state == CircuitState.CLOSED:
            # Increment failure count
            count = self._failure_counts.get(model_id, 0) + 1
            self._failure_counts[model_id] = count
            self._last_failure_times[model_id] = time.time()
            
            if count >= self.failure_threshold:
                logger.warning(f"Circuit for {model_id} exceeded failure threshold ({self.failure_threshold}). Entering OPEN state.")
                self._states[model_id] = CircuitState.OPEN
