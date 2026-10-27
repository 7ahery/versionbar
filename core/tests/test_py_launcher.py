"""The py launcher provider, through the CLI seam.

`py -0p` answers with a real capture from a GitHub Windows runner (five
registered Pythons plus the active virtual environment's untagged `*` line).
Version output is only ever a real `python --version` capture. The repo holds
those for 3.13.16 and 3.14.8, so the listing a test feeds the launcher is the
real one with the lines of Pythons that have no capture dropped, and the
3.14.9 line's path swapped to a folder where the real 3.14.8 capture replays
(the tag and layout bytes stay real). Only machine state changes, never output
formats. The runner's 3.15.1, 3.12.10 and 3.11.9 have no capture here, so they
stay out of every assertion.
"""

import json

from versionbar.providers.py import PyLauncher
from versionbar.system import ProcessResult

from fakes import (
    PY_LISTING_WINDOWS,
    PYTHON_313_WINDOWS,
    PYTHON_314_WINDOWS,
    UV_PYTHON_LIST_WINDOWS,
    UV_WINDOWS,
    WINDOWS_PATHEXT,
    Capture,
    FakeSystem,
    load_capture,
    run_cli,
)

PY_EXE = r"C:\WINDOWS\py.exe"
TOOLCACHE = r"C:\hostedtoolcache\windows\Python"
REAL_313 = rf"{TOOLCACHE}\3.13.16\x64\python.exe"
REAL_314_9 = rf"{TOOLCACHE}\3.14.9\x64\python.exe"
# Where the real 3.14.8 capture replays in place of the listing's 3.14.9.
PY_314 = rf"{TOOLCACHE}\3.14.8\x64\python.exe"
NO_CAPTURE = (b"3.15.1", b"3.12.10", b"3.11.9")
UV_BIN = r"C:\Users\dev\.local\bin"
UV = rf"{UV_BIN}\uv.exe"
UV_DIR = r"C:\Users\dev\AppData\Roaming\uv\python"
UV_313 = rf"{UV_DIR}\cpython-3.13.16-windows-x86_64-none\python.exe"
UV_314 = rf"{UV_DIR}\cpython-3.14.8-windows-x86_64-none\python.exe"
NOT_FOUND = "not found on PATH (looked for: python, python3)"


def real_listing(swaps: dict[str, str] | None = None) -> bytes:
    """The real `py -0p` bytes: Pythons without a version capture dropped,
    then each `swaps` path replaced (CRLF and padding untouched)."""
    stdout = load_capture(PY_LISTING_WINDOWS).result.stdout
    lines = [ln for ln in stdout.splitlines(keepends=True) if not any(v in ln for v in NO_CAPTURE)]
    text = b"".join(lines)
    for old, new in {REAL_314_9: PY_314, **(swaps or {})}.items():
        text = text.replace(old.encode(), new.encode())
    return text


def answer(out: bytes = b"", code: int = 0) -> Capture:
    return Capture(("-0p",), ProcessResult(exit_code=code, stdout=out, stderr=b""))


def machine(
    listing: Capture | None = None, *, py_on_path: bool = True, path: list[str] | None = None
) -> FakeSystem:
    folders = [r"C:\WINDOWS\system32"] + ([r"C:\WINDOWS"] if py_on_path else []) + (path or [])
    system = FakeSystem(os="windows", env={"PATH": ";".join(folders), "PATHEXT": WINDOWS_PATHEXT})
    if py_on_path:
        system.add_executable(PY_EXE, listing or answer(real_listing()))
    system.add_executable(REAL_313, load_capture(PYTHON_313_WINDOWS))
    system.add_executable(PY_314, load_capture(PYTHON_314_WINDOWS))
    return system


def python_of(system: FakeSystem) -> dict:
    result = run_cli(system, "show", "python", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def paths(tool: dict) -> list[tuple[str, str]]:
    return [(i["path"], i["source"]) for i in tool["installs"]]


def test_registered_pythons_are_listed_with_source_py_and_never_active() -> None:
    system = machine()

    python = python_of(system)

    assert python["status"] == "missing"
    assert python["active"] is None
    assert [(i["version"], i["path"], i["source"]) for i in python["installs"]] == [
        ("3.14.8", PY_314, "py"),
        ("3.13.16", REAL_313, "py"),
    ]
    # The untagged `*` line is the active virtual environment: PATH's, not the launcher's.
    assert not any("venv" in run[0] for run in system.runs)


def test_the_launcher_listing_is_declared_for_capture() -> None:
    assert PyLauncher().listing(machine(), "python") == [PY_EXE, "-0p"]
    assert PyLauncher().listing(machine(py_on_path=False), "python") is None


def test_a_path_with_spaces_is_one_install() -> None:
    spaced = r"C:\Program Files\Python 313\python.exe"
    system = machine(answer(real_listing({REAL_313: spaced})))
    system.add_executable(spaced, load_capture(PYTHON_313_WINDOWS))

    assert (spaced, "py") in paths(python_of(system))


def test_without_the_launcher_nothing_is_added_and_nothing_is_said() -> None:
    python = python_of(machine(py_on_path=False))

    assert python["installs"] == []
    assert python["notes"] == [NOT_FOUND]


def test_an_empty_listing_adds_nothing() -> None:
    # Unverified assumption: a launcher with no Pythons registered prints
    # nothing and exits 0 (never captured). A transport-style case only.
    python = python_of(machine(answer()))

    assert python["installs"] == []
    assert python["notes"] == [NOT_FOUND]


def test_a_failing_launcher_is_a_note_and_loses_nothing_else() -> None:
    for result in (
        ProcessResult(exit_code=1, stdout=b"", stderr=b""),
        ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error="access denied"),
        ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True),
    ):
        python = python_of(machine(Capture(("-0p",), result)))

        assert python["installs"] == []
        assert python["notes"][0] == NOT_FOUND
        assert python["notes"][-1].startswith("py launcher: could not list installs: ")


def test_a_python_on_path_stays_active_and_is_listed_once() -> None:
    system = machine(path=[REAL_313.rpartition("\\")[0]])

    python = python_of(system)

    assert python["active"]["path"] == REAL_313
    assert paths(python) == [(REAL_313, "path"), (PY_314, "py")]
    assert system.runs.count((REAL_313, "--version")) == 1


def test_one_python_seen_by_uv_the_launcher_and_path_is_one_install() -> None:
    system = machine(
        answer(real_listing({REAL_313: UV_313})), path=[UV_BIN, UV_313.rpartition("\\")[0]]
    )
    system.add_executable(UV, load_capture(UV_WINDOWS), load_capture(UV_PYTHON_LIST_WINDOWS))
    system.add_executable(UV_313, load_capture(PYTHON_313_WINDOWS))
    system.add_executable(UV_314, load_capture(PYTHON_314_WINDOWS))

    python = python_of(system)

    assert python["active"]["path"] == UV_313
    assert [p for p in paths(python) if p[0] == UV_313] == [(UV_313, "path")]
    assert (PY_314, "py") in paths(python)
    assert (UV_314, "uv") in paths(python)
    assert system.runs.count((UV_313, "--version")) == 1


def test_the_launcher_is_listed_as_a_windows_provider_of_python() -> None:
    result = run_cli(machine(), "tools", "--json")

    [py] = [p for p in json.loads(result.stdout)["providers"] if p["id"] == "py"]
    assert (py["name"], py["os"], py["tools"]) == ("py launcher", ["windows"], ["python"])
