"""Bounded polling must never turn pending, late or failed reads into success."""
import asyncio
import unittest

from rpc_poll import poll


class PollTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_attempt_limit(self):
        calls = []
        async def read():
            calls.append(1)
            return {"status": "unspent"}
        r = await poll(read, timeout=1, interval=0, max_attempts=2)
        self.assertEqual((r["status"], r["reason"], len(calls)), ("timed-out", "attempt-limit", 2))
        self.assertEqual(r["last_observation"]["status"], "unspent")
        self.assertEqual(r["transactions_submitted"], 0)

    async def test_confirmation_after_pending(self):
        replies = [{"status": "confirming"}, {"status": "confirmed", "height": 10}]
        async def read():
            return replies.pop(0)
        r = await poll(read, timeout=1, interval=0, max_attempts=3)
        self.assertEqual((r["status"], r["attempts"]), ("confirmed", 2))
        self.assertEqual(r["last_observation"]["height"], 10)

    async def test_reorg_and_conflict_stop(self):
        for status in ("reorged", "conflicting-spend"):
            async def read():
                return {"status": status}
            r = await poll(read, timeout=1, interval=0, max_attempts=3)
            self.assertEqual((r["status"], r["attempts"]), (status, 1))

    async def test_invalid_bounds_do_not_read(self):
        async def read():
            self.fail("Invalid bounds reached observer")
        for key, value in [("timeout", 0), ("timeout", float("nan")), ("timeout", True), ("timeout", 601),
                           ("interval", -1), ("interval", 2), ("max_attempts", 0), ("max_attempts", True), ("max_attempts", 1001)]:
            args = {"timeout": 1, "interval": 0, "max_attempts": 2, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                await poll(read, **args)

    async def test_deadline_and_late_cancelled_confirmation(self):
        async def blocked():
            await asyncio.sleep(1)
            return {"status": "confirmed"}
        r = await poll(blocked, timeout=0.01, interval=0, max_attempts=2)
        self.assertEqual(r["status"], "timed-out")
        self.assertIsNone(r["last_observation"])
        async def ignores_cancellation():
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return {"status": "confirmed"}
        r = await poll(ignores_cancellation, timeout=0.01, interval=0, max_attempts=2)
        self.assertEqual((r["status"], r["reason"]), ("timed-out", "deadline"))
        self.assertIsNone(r["last_observation"])

    async def test_malformed_and_transport_failure_propagate(self):
        async def malformed():
            return {"status": "SUCCESS"}
        with self.assertRaises(RuntimeError):
            await poll(malformed, timeout=1, interval=0, max_attempts=2)
        async def failed():
            raise OSError("fixture failure")
        with self.assertRaises(OSError):
            await poll(failed, timeout=1, interval=0, max_attempts=2)

    async def test_caller_cancellation_propagates(self):
        async def cancelled():
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await poll(cancelled, timeout=1, interval=0, max_attempts=2)


if __name__ == "__main__":
    unittest.main()
