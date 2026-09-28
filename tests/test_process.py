import sys

import pytest

from jev_ci.process import run_bounded


def test_subprocess_output_cap_kills_large_output():
    result = run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"],
        max_output_bytes=100,
        timeout_seconds=5,
    )
    assert result.output_exceeded
    assert len(result.stdout) == 101


def test_subprocess_deadline_stops_hung_command():
    with pytest.raises(TimeoutError):
        run_bounded(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            max_output_bytes=100,
            timeout_seconds=0.1,
        )
