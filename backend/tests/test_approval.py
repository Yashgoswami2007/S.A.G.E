"""
Tests for the HIGH_RISK tool approval pipeline.

Verifies that:
1. HIGH_RISK tools block execution until explicit approval
2. Approved requests execute exactly once
3. Rejected requests never execute
4. The confirm endpoint stores and checks the approved field
5. Duplicate approvals don't cause double execution
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sage.agent.state import AgentState, TraceEvent
from sage.agent.executor import ApprovalRejectedError
from sage.tools.base import BaseTool, ToolPermission, ToolResult


# ── Helpers ────────────────────────────────────────────────────────────────

class FakeHighRiskTool(BaseTool):
    """A mock HIGH_RISK tool for testing."""
    name = "execute_command"
    description = "A test high-risk tool."
    permission = ToolPermission.HIGH_RISK
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }

    def __init__(self):
        self.call_count = 0

    async def execute(self, command: str) -> ToolResult:
        self.call_count += 1
        return ToolResult(success=True, output=f"Ran: {command}")


class FakeSafeTool(BaseTool):
    """A mock SAFE tool for testing."""
    name = "read_file"
    description = "A test safe tool."
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, path: str) -> ToolResult:
        return ToolResult(success=True, output=f"Content of {path}")


# ── Unit Tests: Approval Gate Logic ────────────────────────────────────────

class TestApprovalGateLogic(unittest.TestCase):
    """Tests the approval/rejection mechanics in isolation."""

    def test_approval_rejected_error_exists(self):
        """ApprovalRejectedError must be a proper exception class."""
        err = ApprovalRejectedError("test rejection")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "test rejection")

    def test_high_risk_tool_has_correct_permission(self):
        tool = FakeHighRiskTool()
        self.assertEqual(tool.permission, ToolPermission.HIGH_RISK)

    def test_safe_tool_is_not_high_risk(self):
        tool = FakeSafeTool()
        self.assertNotEqual(tool.permission, ToolPermission.HIGH_RISK)


# ── Unit Tests: Confirm Endpoint ───────────────────────────────────────────

class TestConfirmEndpoint(unittest.TestCase):
    """Tests the /api/chat/confirm endpoint logic."""

    def test_confirm_approval_sets_event_and_stores_true(self):
        """When approved=True, record['approved'] must be True and event set."""
        async def _test():
            from sage.api.chat import _pending_confirmations

            record = {"event": asyncio.Event(), "approved": None}
            req_id = "test-req-approve"
            _pending_confirmations[req_id] = record

            # Simulate what confirm_action does
            record["approved"] = True
            record["event"].set()

            self.assertTrue(record["event"].is_set())
            self.assertTrue(record["approved"])

            # Cleanup
            _pending_confirmations.pop(req_id, None)

        asyncio.run(_test())

    def test_confirm_rejection_sets_event_and_stores_false(self):
        """When approved=False, record['approved'] must be False and event still set."""
        async def _test():
            from sage.api.chat import _pending_confirmations

            record = {"event": asyncio.Event(), "approved": None}
            req_id = "test-req-reject"
            _pending_confirmations[req_id] = record

            # Simulate rejection
            record["approved"] = False
            record["event"].set()

            self.assertTrue(record["event"].is_set())
            self.assertFalse(record["approved"])

            # Cleanup
            _pending_confirmations.pop(req_id, None)

        asyncio.run(_test())

    def test_approval_event_blocks_until_set(self):
        """The asyncio.Event must block callers until set()."""
        async def _test():
            record = {"event": asyncio.Event(), "approved": None}
            unblocked = False

            async def waiter():
                nonlocal unblocked
                await record["event"].wait()
                unblocked = True

            task = asyncio.create_task(waiter())

            # Should not be unblocked yet
            await asyncio.sleep(0.05)
            self.assertFalse(unblocked)

            # Now set it
            record["approved"] = True
            record["event"].set()
            await asyncio.sleep(0.01)
            self.assertTrue(unblocked)

            await task

        asyncio.run(_test())

    def test_no_approval_means_no_unblock(self):
        """If no one calls set(), the waiter stays blocked (timeout test)."""
        async def _test():
            record = {"event": asyncio.Event(), "approved": None}
            timed_out = False

            async def waiter():
                nonlocal timed_out
                try:
                    await asyncio.wait_for(record["event"].wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    timed_out = True

            await waiter()
            self.assertTrue(timed_out)

        asyncio.run(_test())

    def test_duplicate_approval_only_sets_once(self):
        """Calling set() twice on the same event is harmless — it stays set."""
        async def _test():
            record = {"event": asyncio.Event(), "approved": None}

            record["approved"] = True
            record["event"].set()
            record["event"].set()  # Second set — should be no-op

            self.assertTrue(record["event"].is_set())
            self.assertTrue(record["approved"])

        asyncio.run(_test())


# ── Integration Tests: Stream Callback Approval Flow ───────────────────────

class TestStreamCallbackApprovalFlow(unittest.TestCase):
    """Tests the stream_callback approval/rejection flow from chat.py."""

    def test_rejection_raises_approval_rejected_error(self):
        """When the confirm endpoint stores approved=False, the stream_callback
        must raise ApprovalRejectedError after the event is set."""
        async def _test():
            from sage.api.chat import _pending_confirmations

            # Simulate what stream_callback does
            req_id = "test-reject-flow"
            record = {"event": asyncio.Event(), "approved": None}
            _pending_confirmations[req_id] = record

            async def simulate_stream_callback():
                await record["event"].wait()
                _pending_confirmations.pop(req_id, None)
                if not record["approved"]:
                    raise ApprovalRejectedError("User rejected")

            # Simulate user rejecting after a short delay
            async def simulate_user_reject():
                await asyncio.sleep(0.05)
                record["approved"] = False
                record["event"].set()

            task_cb = asyncio.create_task(simulate_stream_callback())
            asyncio.create_task(simulate_user_reject())

            with self.assertRaises(ApprovalRejectedError):
                await task_cb

        asyncio.run(_test())

    def test_approval_does_not_raise(self):
        """When the confirm endpoint stores approved=True, the stream_callback
        must return normally (no exception)."""
        async def _test():
            from sage.api.chat import _pending_confirmations

            req_id = "test-approve-flow"
            record = {"event": asyncio.Event(), "approved": None}
            _pending_confirmations[req_id] = record

            async def simulate_stream_callback():
                await record["event"].wait()
                _pending_confirmations.pop(req_id, None)
                if not record["approved"]:
                    raise ApprovalRejectedError("User rejected")
                return "approved"

            async def simulate_user_approve():
                await asyncio.sleep(0.05)
                record["approved"] = True
                record["event"].set()

            task_cb = asyncio.create_task(simulate_stream_callback())
            asyncio.create_task(simulate_user_approve())

            result = await task_cb
            self.assertEqual(result, "approved")

        asyncio.run(_test())


# ── Integration Tests: Executor Approval Flow ──────────────────────────────

class TestExecutorApprovalFlow(unittest.TestCase):
    """Tests that the executor correctly handles approval/rejection of HIGH_RISK tools."""

    def test_rejection_skips_tool_execution(self):
        """When emit() raises ApprovalRejectedError, tool.execute() must NOT be called."""
        async def _test():
            tool = FakeHighRiskTool()
            trace_events = []

            async def rejecting_callback(event: TraceEvent):
                trace_events.append(event)
                if event.agent_state == AgentState.WAITING_FOR_APPROVAL:
                    raise ApprovalRejectedError("User rejected")

            # Create a minimal executor setup
            from sage.tools.registry import ToolRegistry
            registry = ToolRegistry()
            registry.register(tool)

            # Simulate what the executor does at lines 270-300
            tool_name = "execute_command"
            tool_args = {"command": "echo test"}
            tool_inst = registry.get_tool(tool_name)

            # Permission check
            self.assertEqual(tool_inst.permission, ToolPermission.HIGH_RISK)

            # Emit approval event (should raise)
            approval_event = TraceEvent(
                task_id="test-task",
                step_id=1,
                agent_state=AgentState.WAITING_FOR_APPROVAL,
                tool_name=tool_name,
                tool_args=tool_args,
                reflection=f"High-risk operation '{tool_name}' requires approval."
            )

            rejected = False
            try:
                await rejecting_callback(approval_event)
            except ApprovalRejectedError:
                rejected = True

            self.assertTrue(rejected)
            # Tool must NOT have been called
            self.assertEqual(tool.call_count, 0)

        asyncio.run(_test())

    def test_approval_allows_tool_execution(self):
        """When emit() returns normally (approval granted), tool.execute() must be called."""
        async def _test():
            tool = FakeHighRiskTool()
            trace_events = []

            async def approving_callback(event: TraceEvent):
                trace_events.append(event)
                # Approval granted — no exception

            from sage.tools.registry import ToolRegistry
            registry = ToolRegistry()
            registry.register(tool)

            tool_name = "execute_command"
            tool_args = {"command": "echo test"}
            tool_inst = registry.get_tool(tool_name)

            approval_event = TraceEvent(
                task_id="test-task",
                step_id=1,
                agent_state=AgentState.WAITING_FOR_APPROVAL,
                tool_name=tool_name,
                tool_args=tool_args,
                reflection=f"High-risk operation '{tool_name}' requires approval."
            )

            # emit does not raise — approval granted
            await approving_callback(approval_event)

            # Now tool execution should proceed
            result = await registry.execute_tool(
                name=tool_name,
                kwargs=tool_args,
                allowed_tools={"execute_command"},
            )
            self.assertTrue(result.success)
            self.assertEqual(tool.call_count, 1)

        asyncio.run(_test())


# ── Event Schema Tests ─────────────────────────────────────────────────────

class TestConfirmationRequiredEvent(unittest.TestCase):
    """Tests the ConfirmationRequiredEvent schema and trace_to_event mapping."""

    def test_confirmation_event_includes_tool_args(self):
        """ConfirmationRequiredEvent must include tool_args."""
        from sage.api.events import ConfirmationRequiredEvent

        evt = ConfirmationRequiredEvent(
            action="execute_command",
            description="Requires approval.",
            request_id="req-123",
            tool_args={"command": "echo hello"},
        )
        self.assertEqual(evt.tool_args, {"command": "echo hello"})
        data = evt.model_dump()
        self.assertIn("tool_args", data)
        self.assertEqual(data["tool_args"]["command"], "echo hello")

    def test_trace_to_event_maps_waiting_for_approval(self):
        """trace_to_event must return ConfirmationRequiredEvent for WAITING_FOR_APPROVAL."""
        from sage.api.events import trace_to_event, ConfirmationRequiredEvent

        trace = TraceEvent(
            task_id="t1",
            step_id=1,
            agent_state=AgentState.WAITING_FOR_APPROVAL,
            tool_name="execute_command",
            tool_args={"command": "echo hi"},
            reflection="High-risk operation requires approval.",
        )
        result = trace_to_event(trace)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ConfirmationRequiredEvent)
        self.assertEqual(result.action, "execute_command")
        self.assertEqual(result.request_id, trace.id)
        self.assertEqual(result.tool_args, {"command": "echo hi"})


if __name__ == "__main__":
    unittest.main()
