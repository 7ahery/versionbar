"""The real system's process runner, against real processes (outside the CLI seam,
like the install smoke test): the fake can only replay what this produces, so the
timeout and capture behaviour behind it is checked here."""

import sys
import time

from versionbar.system.real import local_system

# The child starts a grandchild that inherits its stdout and outlives it, as a
# `.cmd` shim's hung program would, then hangs itself.
HANGS_WITH_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print('partial', flush=True)\n"
    "time.sleep(60)\n"
)

LARGE_OUTPUT_THEN_EXIT_3 = (
    "import sys\n"
    "sys.stdout.buffer.write(bytes(range(256)) * 800)\n"
    "sys.stdout.flush()\n"
    "sys.exit(3)\n"
)


def test_a_timeout_kills_the_whole_tree_and_keeps_partial_output() -> None:
    start = time.monotonic()

    result = local_system().run([sys.executable, "-c", HANGS_WITH_GRANDCHILD], 0.5)

    elapsed = time.monotonic() - start
    assert result.timed_out
    assert result.exit_code is None
    assert result.stdout.replace(b"\r\n", b"\n") == b"partial\n"
    # Not a performance threshold: waiting for the grandchild instead of
    # killing it would take the full 60 s, so anything far below that tells
    # the two apart even on a slow CI runner.
    assert elapsed < 20, f"run returned after {elapsed:.1f} s"


def test_large_output_and_exit_code_are_captured_whole() -> None:
    result = local_system().run([sys.executable, "-c", LARGE_OUTPUT_THEN_EXIT_3], 30)

    assert (result.exit_code, result.timed_out, result.launch_error) == (3, False, None)
    # 200 KiB, every byte value: well beyond a pipe buffer, and binary-exact.
    assert result.stdout == bytes(range(256)) * 800
    assert result.stderr == b""
