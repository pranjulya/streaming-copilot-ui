"""Boot both processes and check the real development rewrite, then clean up."""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-db", action="store_true")
    args = parser.parse_args()
    processes = []
    # Refuse occupied ports to avoid checking an unrelated app.
    import socket

    for port in (8000, 3000):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    with tempfile.TemporaryDirectory(prefix="copilot-smoke-") as directory:
        logfiles = []
        try:
            for name, command in [
                (
                    "api",
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:create_app",
                        "--factory",
                        "--app-dir",
                        "services/api",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8000",
                    ],
                ),
                ("web", ["pnpm", "--dir", "apps/web", "dev"]),
            ]:
                log = open(Path(directory) / f"{name}.log", "w+")
                logfiles.append(log)
                processes.append(
                    subprocess.Popen(
                        command,
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                )
            deadline = time.monotonic() + 60
            while True:
                if any(process.poll() is not None for process in processes):
                    raise RuntimeError(
                        "A smoke-test process exited before becoming ready"
                    )
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:3000/health/live", timeout=3
                    ) as response:
                        assert json.load(response) == {"status": "live"}
                    break
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Development proxy did not become ready within 60 seconds"
                        ) from None
                    time.sleep(0.5)
            with urllib.request.urlopen(
                "http://127.0.0.1:3000", timeout=30
            ) as response:
                # The real chat shell replaced the Phase 00 placeholder heading;
                # assert the list region the app actually renders.
                assert 'aria-label="Conversations"' in response.read().decode()
            try:
                response = urllib.request.urlopen(
                    "http://127.0.0.1:3000/health/ready", timeout=5
                )
            except urllib.error.HTTPError as error:
                response = error
            with response:
                body = json.load(response)
                if args.require_db:
                    assert response.status == 200, body
                    assert body == {"status": "ready", "database": "ok"}
                else:
                    assert response.status in (200, 503), body
                    if response.status == 503:
                        assert body["code"] == "service_unavailable"
                        assert response.headers["Content-Type"].startswith(
                            "application/problem+json"
                        )
            print(f"PASS: shell, live proxy, readiness proxy (HTTP {response.status})")
        except BaseException:
            for log in logfiles:
                log.flush()
                log.seek(0)
                print(log.read(), file=sys.stderr)
            raise
        finally:
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            for log in logfiles:
                log.close()


if __name__ == "__main__":
    main()
