"""Bounded asynchronous read-only observation; never submits or replaces spends."""
import asyncio
import copy
import math

from smoke import require


async def poll(read, *, timeout, interval, max_attempts):
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 600, "Invalid observation timeout")
    require(type(interval) in (int, float) and math.isfinite(interval) and 0 <= interval <= timeout, "Invalid poll interval")
    require(type(max_attempts) is int and 1 <= max_attempts <= 1000, "Invalid attempt bound")
    loop = asyncio.get_running_loop()
    start = loop.time()
    deadline = start + timeout
    attempts, last = 0, None

    def result(status, reason):
        return {"status": status, "reason": reason, "attempts": attempts, "max_attempts": max_attempts,
                "timeout_seconds": timeout, "elapsed_seconds": loop.time() - start,
                "last_observation": copy.deepcopy(last), "transactions_submitted": 0}

    while attempts < max_attempts:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return result("timed-out", "deadline")
        attempts += 1
        try:
            observation = await asyncio.wait_for(read(), timeout=remaining)
        except TimeoutError:
            return result("timed-out", "observation-timeout")
        # A coroutine can delay cancellation: never accept a late confirmation.
        if loop.time() >= deadline:
            return result("timed-out", "deadline")
        require(type(observation) is dict and observation.get("status") in
                {"unspent", "confirming", "confirmed", "reorged", "conflicting-spend"}, "Invalid observation status")
        last = copy.deepcopy(observation)
        if last["status"] in {"confirmed", "reorged", "conflicting-spend"}:
            return result(last["status"], "terminal-observation")
        if attempts < max_attempts:
            await asyncio.sleep(min(interval, max(0, deadline - loop.time())))
    return result("timed-out", "attempt-limit")
