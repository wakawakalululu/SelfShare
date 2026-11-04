"""External-server helper for the test suite.

When ``SELFSHARE_SERVER_BIN`` points at a server executable (e.g. the Go
implementation), the fixtures start that process instead of the in-process
Python server. The vault is still created with the Python CLI, so a green run
proves the on-disk registry and the HTTP protocol are shared by both
implementations.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

LISTEN_RE = re.compile(r"listening on http://127\.0\.0\.1:(\d+)")


class ExternalServer:
    def __init__(self, vault_id: str, token: str) -> None:
        binary = os.environ["SELFSHARE_SERVER_BIN"]
        self.root = tempfile.mkdtemp(prefix="selfshare-ext-server-")
        self.log_path = os.path.join(self.root, "server.log")
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [binary, "--root", self.root, "--host", "127.0.0.1", "--port", "0", "--quiet"],
            stdout=self._log, stderr=subprocess.STDOUT,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(binary))),
        )
        self.port = self._wait_port()
        self.url = "http://127.0.0.1:%d" % self.port
        self.vault_id = vault_id
        self.token = token

    def _wait_port(self) -> int:
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                with open(self.log_path, "r", encoding="utf-8", errors="replace") as fh:
                    match = LISTEN_RE.search(fh.read())
                if match:
                    return int(match.group(1))
            except OSError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError("external server exited early; see %s" % self.log_path)
            time.sleep(0.2)
        raise RuntimeError("external server did not report a port; see %s" % self.log_path)

    def create_vault(self) -> None:
        """Create the vault with the Python registry so the Go server reads it from disk."""
        from selfshare.store import Registry

        Registry(self.root).create_vault(self.vault_id, token=self.token)

    def ping(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/ping", timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self._log.close()
        shutil.rmtree(self.root, ignore_errors=True)
