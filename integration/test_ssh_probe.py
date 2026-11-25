"""SSH argument, request binding, deadline and remote worker regression checks."""
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import ssh_probe
import test_testnet_probe as fixtures
from testnet_probe import ProbeError


class SSHProbeTests(unittest.TestCase):
    def run_probe(self, **kwargs):
        return ssh_probe.probe("steve@LOBOT", "https://127.0.0.1:8555",
                               "/ca", "/cert", "/key", **kwargs)

    def test_arguments_and_validation_before_launch(self):
        argv = ssh_probe.command("steve@LOBOT", 30)
        for option in ("StrictHostKeyChecking=yes", "BatchMode=yes", "ForwardAgent=no",
                       "ClearAllForwardings=yes", "PermitLocalCommand=no", "ControlPath=none"):
            self.assertIn(option, argv)
        self.assertEqual(argv[-2], "steve@LOBOT")
        self.assertTrue(argv[-1].startswith("/usr/bin/python3 -I -B -c "))
        with patch.object(ssh_probe.subprocess, "Popen") as launch:
            for target in ("-option", "a;touch /tmp/x", "user@host extra", "a\nb", "a@b@c"):
                with self.assertRaises(ProbeError):
                    ssh_probe.command(target, 30)
            for duration in (0, -1, 121, float("nan"), float("inf")):
                with self.assertRaises(ProbeError):
                    self.run_probe(duration=duration)
            with self.assertRaises(ProbeError):
                self.run_probe(timeout=0)
            with self.assertRaises(ProbeError):
                ssh_probe.probe("LOBOT", "https://127.0.0.1:8555", "relative", "/cert", "/key")
            launch.assert_not_called()

    def test_reply_is_bound_to_sources_and_nonce(self):
        class Child:
            returncode = 0
            stdin = stdout = stderr = None

            def __init__(self, mutation):
                self.mutation = mutation

            def communicate(self, timeout=None):
                if timeout is None:
                    return b"", b""
                request = self.packet
                self.packet = request
                reply = {"nonce": request["nonce"], "sources": {
                    name: hashlib.sha256(source.encode()).hexdigest()
                    for name, source in request["modules"].items()}, "observation": {
                    "validation": "rpc-observation-only", "coin": None, "transactions_submitted": 0}}
                self.mutation(reply)
                return json.dumps(reply).encode(), b""

            def poll(self):
                return self.returncode

        good = Child(lambda reply: None)
        def launch_child(child):
            def launch(*args, **kwargs):
                child.packet = json.load(kwargs['stdin'])
                return child
            return launch
        with patch.object(ssh_probe.subprocess, "Popen", side_effect=launch_child(good)) as launch:
            self.assertEqual(self.run_probe()["validation"], "ssh-read-only-probe")
            self.assertEqual(set(good.packet["modules"]), set(ssh_probe.MODULES))
            self.assertNotIn("/key", launch.call_args.args[0][-1])
        for mutate in (lambda r: r.update(nonce="stale"), lambda r: r.update(sources={}),
                       lambda r: r.update(extra=True), lambda r: r.update(observation=None)):
            with patch.object(ssh_probe.subprocess, "Popen", side_effect=launch_child(Child(mutate))):
                with self.assertRaises(ProbeError):
                    self.run_probe()

    def test_coin_arguments_rejected_before_ssh(self):
        with patch.object(ssh_probe.subprocess, "Popen") as launch:
            for args in ({"requested_coin": fixtures.COIN_ID},
                         {"expected_amount": 1000},
                         {"requested_coin": "bad", "expected_puzzle_hash": fixtures.PUZZLE, "expected_amount": 1000},
                         *({"requested_coin": fixtures.COIN_ID, "expected_puzzle_hash": fixtures.PUZZLE,
                            "expected_amount": amount} for amount in (-1, True, 2**64))):
                with self.subTest(args=args), self.assertRaises(ProbeError):
                    self.run_probe(**args)
            launch.assert_not_called()

    def test_coin_worker_and_parent_with_synthetic_rpc(self):
        # Run the actual streamed observation and parent protocol in a subprocess.
        # Replace only RPC I/O with public fixture replies. POSIX uses the real alarm;
        # Windows disables that Linux-specific mechanism, covered by native tests.
        launch = subprocess.Popen
        read_text = ssh_probe.Path.read_text
        data = fixtures.replies()
        extra = ""

        def fixture_source(path, *args, **kwargs):
            source = read_text(path, *args, **kwargs)
            if path.name == "testnet_probe.py":
                source += ("\n_DATA = " + repr(data) + "\nclass Transport:\n"
                           " def __init__(self, *args): pass\n"
                           " def call(self, route, request):\n"
                           "  if route == 'get_coin_record_by_name':\n"
                           "   assert request == {'name': '0x" + fixtures.COIN_ID + "'}\n"
                           "  return _DATA[route]\n")
                source += extra
            return source

        def local_worker(*args, **kwargs):
            prelude = "DURATION = 5\n"
            if os.name != "posix":
                prelude += ("import signal\nsignal.SIGALRM = signal.SIGTERM\n"
                            "signal.ITIMER_REAL = 0\nsignal.setitimer = lambda *args: None\n")
            return launch([sys.executable, "-I", "-B", "-c", prelude + ssh_probe.REMOTE], **kwargs)

        args = {"requested_coin": fixtures.COIN_ID.upper(),
                "expected_puzzle_hash": "0x" + fixtures.PUZZLE, "expected_amount": 1000}
        with patch.object(ssh_probe.Path, "read_text", fixture_source), \
                patch.object(ssh_probe.subprocess, "Popen", side_effect=local_worker):
            result = self.run_probe(**args)
            self.assertEqual(result["observation"]["coin"]["name"], fixtures.COIN_ID)
            self.assertEqual(result["observation"]["coin"]["amount"], "1000")
            self.assertFalse(result["observation"]["spend_validated"])
            for key, value in (("spent", True), ("spent_block_index", 1)):
                data = fixtures.replies()
                data["get_coin_record_by_name"]["coin_record"][key] = value
                with self.subTest(key=key), self.assertRaises(ProbeError):
                    self.run_probe(**args)
            data = fixtures.replies()
            with self.assertRaises(ProbeError):
                self.run_probe(**dict(args, expected_amount=999))
            with self.assertRaises(ProbeError):
                self.run_probe(**dict(args, expected_puzzle_hash="ff" * 32))
            # Even a well-formed envelope must not substitute another observed coin.
            extra = ("\n_original = observe\ndef observe(*args):\n"
                     " result = _original(*args)\n result['coin']['name'] = '00' * 32\n return result\n")
            with self.assertRaises(ProbeError):
                self.run_probe(**args)

    def test_real_local_timeout_kills_reaps_and_closes_pipes(self):
        launch = subprocess.Popen
        children = []

        def sleeping_child(*args, **kwargs):
            child = launch([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            children.append(child)
            return child

        with patch.object(ssh_probe.subprocess, "Popen", side_effect=sleeping_child):
            started = time.monotonic()
            with self.assertRaises((subprocess.TimeoutExpired, ProbeError)):
                self.run_probe(duration=0.2)
            self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(len(children), 1)
        child = children[0]
        self.assertIsNotNone(child.poll())
        self.assertTrue(all(stream.closed for stream in (child.stdout, child.stderr)))

    @unittest.skipUnless(os.name == "posix", "Remote watchdog requires Linux/POSIX")
    def test_remote_watchdog_bounds_stdin_and_rpc(self):
        source = "DURATION = 0.2\n" + ssh_probe.REMOTE
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c", source],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # Keep stdin open: remote timeout must work even before request arrival.
            self.assertEqual(child.wait(timeout=5), 124)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate()
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        fixture = "import time\nclass Transport:\n def __init__(self, *args): pass\n def call(self): pass\ndef observe(call): time.sleep(60)\n"
        packet = {"nonce": "test", "modules": {"network_identity": "", "testnet_probe": fixture},
                  "request": {"endpoint": "unused", "ca_cert": "/ca", "client_cert": "/cert",
                              "client_key": "/key", "timeout": 1}}
        result = subprocess.run([sys.executable, "-I", "-B", "-c", source],
                                input=json.dumps(packet).encode(), capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, b"")

    @unittest.skipUnless(os.name == "posix", "Remote watchdog requires Linux/POSIX")
    def test_remote_worker_runs_fixed_probe_and_sanitizes_errors(self):
        source = "DURATION = 5\n" + ssh_probe.REMOTE
        fixture = "class Transport:\n def __init__(self, *args): pass\n def call(self): pass\ndef observe(call): return {'test': True}\n"
        packet = {"nonce": "test", "modules": {"network_identity": "", "testnet_probe": fixture},
                  "request": {"endpoint": "unused", "ca_cert": "/ca", "client_cert": "/cert",
                              "client_key": "/key", "timeout": 1}}
        result = subprocess.run([sys.executable, "-I", "-B", "-c", source],
                                input=json.dumps(packet).encode(), capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["observation"], {"test": True})
        packet["modules"]["testnet_probe"] = "raise ValueError('secret fixture')"
        result = subprocess.run([sys.executable, "-I", "-B", "-c", source],
                                input=json.dumps(packet).encode(), capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"secret fixture", result.stderr)


if __name__ == "__main__":
    unittest.main()
