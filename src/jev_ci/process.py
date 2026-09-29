"""Run fixed argument vectors with hard time and output bounds."""

from __future__ import annotations

import os
import selectors
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    output_exceeded: bool


def run_bounded(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    max_output_bytes: int,
    timeout_seconds: float,
    max_stderr_bytes: int = 4096,
    input_bytes: bytes | None = None,
) -> ProcessResult:
    deadline = time.monotonic() + timeout_seconds
    input_stream = None
    if input_bytes is not None:
        input_stream = tempfile.TemporaryFile()
        input_stream.write(input_bytes)
        input_stream.seek(0)
    try:
        if deadline <= time.monotonic():
            raise TimeoutError("subprocess deadline expired")
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdin=input_stream,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except BaseException:
        if input_stream:
            input_stream.close()
        raise
    try:
        assert process.stdout is not None and process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        exceeded = False
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("subprocess deadline expired")
                for key, _ in selector.select(remaining):
                    piece = os.read(key.fd, 65536)
                    if not piece:
                        selector.unregister(key.fileobj)
                    elif key.data == "stdout":
                        stdout.extend(
                            piece[: max(0, max_output_bytes + 1 - len(stdout))]
                        )
                        if len(stdout) > max_output_bytes:
                            exceeded = True
                            break
                    else:
                        stderr.extend(piece[: max(0, max_stderr_bytes - len(stderr))])
                if exceeded:
                    break
        if exceeded:
            process.kill()
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return ProcessResult(process.returncode, bytes(stdout), bytes(stderr), exceeded)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        if input_stream:
            input_stream.close()
