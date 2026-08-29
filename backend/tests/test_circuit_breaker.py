import unittest
import time
from sage.models.circuit_breaker import ModelCircuitBreaker, CircuitState

class TestCircuitBreaker(unittest.TestCase):
    def test_circuit_starts_closed(self):
        cb = ModelCircuitBreaker()
        self.assertEqual(cb.get_state("test-model"), CircuitState.CLOSED)
        self.assertFalse(cb.is_open("test-model"))

    def test_circuit_opens_after_failures(self):
        cb = ModelCircuitBreaker(failure_threshold=3)
        cb.record_failure("test-model")
        cb.record_failure("test-model")
        self.assertEqual(cb.get_state("test-model"), CircuitState.CLOSED)
        
        cb.record_failure("test-model") # 3rd failure
        self.assertEqual(cb.get_state("test-model"), CircuitState.OPEN)
        self.assertTrue(cb.is_open("test-model"))

    def test_circuit_recovers_to_half_open(self):
        # Set a very short recovery timeout
        cb = ModelCircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure("test-model")
        cb.record_failure("test-model")
        self.assertEqual(cb.get_state("test-model"), CircuitState.OPEN)
        
        time.sleep(0.15)
        self.assertEqual(cb.get_state("test-model"), CircuitState.HALF_OPEN)
        
    def test_circuit_closes_on_success_from_half_open(self):
        cb = ModelCircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure("test-model")
        time.sleep(0.15)
        self.assertEqual(cb.get_state("test-model"), CircuitState.HALF_OPEN)
        
        cb.record_success("test-model")
        self.assertEqual(cb.get_state("test-model"), CircuitState.CLOSED)

    def test_circuit_reopens_on_failure_from_half_open(self):
        cb = ModelCircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure("test-model")
        time.sleep(0.15)
        self.assertEqual(cb.get_state("test-model"), CircuitState.HALF_OPEN)
        
        cb.record_failure("test-model")
        self.assertEqual(cb.get_state("test-model"), CircuitState.OPEN)

if __name__ == "__main__":
    unittest.main()
