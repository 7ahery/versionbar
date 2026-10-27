"""The py launcher provider, through the CLI seam.

`py -0p` answers with a real capture from a GitHub Windows runner (five
registered Pythons plus the active virtual environment's untagged `*` line).
Where a test needs the launcher to name a path the machine's other sources
also know, the path in that real line is replaced; machine state is synthetic.
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
REAL_313 = r"C:\hostedtoolcache\windows\Python\3.13.16\x64\python.exe"
OTHERS = [
    rf"C:\hostedtoolcache\windows\Python\{v}\x64\python.exe"
    for v in ("3.15.1", "3.14.9", "3.12.10", "3.11.9")
]
UV_BIN = r"C:\Users\dev\.local\bin"
UV = rf"{UV_BIN}\uv.exe"
UV_DIR = r"C:\Users\dev\AppData\Roaming\uv\python"
UV_313 = rf"{UV_DIR}\cpython-3.13.16-windows-x86_64-none\python.exe"
UV_314 = rf"{UV_DIR}\cpython-3.14.8-windows-x86_64-none\python.exe"
NOT_FOUND = "not found on PATH (looked for: python, python3)"


def machine(
    listing: Capture | None = None, *, py_on_path: bool = True, path: list[str] | None = None
) -> FakeSystem:
    """Only the 3.13.16 the launcher names answers its version from a capture;
    the rest of the real listing's Pythons have none, so they fail to run."""
    folders = [r"C:\WINDOWS\system32"] + ([r"C:\WINDOWS"] if py_on_path else []) + (path or [])
    system = FakeSystem(os="windows", env={"PATH": ";".join(folders), "PATHEXT": WINDOWS_PATHEXT})
    if py_on_path:
        system.add_executable(PY_EXE, listing or load_capture(PY_LISTING_WINDOWS))
    system.add_executable(REAL_313, load_capture(PYTHON_313_WINDOWS))
    for other in OTHERS:
        system.add_executable(other, Capture(("--version",), ProcessResult(1, b"", b"")))
    return system


def python_of(system: FakeSystem) -> dict:
    result = run_cli(system, "show", "python", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def answer(out: bytes = b"", code: int = 0) -> Capture:
    return Capture(("-0p",), ProcessResult(exit_code=code, stdout=out, stderr=b""))


def paths(tool: dict) -> list[tuple[str, str]]:
    return [(i["path"], i["source"]) for i in tool["installs"]]


def test_a_registered_python_is_listed_with_source_py_and_never_active() -> None:
    system = machine()

    python = python_of(system)

    assert python["status"] == "missing"
    assert python["active"] is None
    assert (REAL_313, "py") in paths(python)
    assert ("3.13.16", REAL_313) in [(i["version"], i["path"]) for i in python["installs"]]
    # The untagged `*` line is the active virtual environment: PATH's, not the launcher's.
    assert not any("venv" in run[0] for run in system.runs)


def test_the_launcher_listing_is_declared_for_capture() -> None:
    assert PyLauncher().listing(machine(), "python") == [PY_EXE, "-0p"]
    assert PyLauncher().listing(machine(py_on_path=False), "python") is None


def test_a_path_with_spaces_is_one_install() -> None:
    spaced = r"C:\Program Files\Python 313\python.exe"
    system = machine(answer(f" -V:3.13          {spaced}\r\n".encode()))
    system.add_executable(spaced, load_capture(PYTHON_313_WINDOWS))

    assert paths(python_of(system)) == [(spaced, "py")]


def test_a_launcher_default_star_after_the_tag_is_still_the_path() -> None:
    python = python_of(machine(answer(f" -V:3.13        * {REAL_313}\r\n".encode())))

    assert paths(python) == [(REAL_313, "py")]


def test_without_the_launcher_nothing_is_added_and_nothing_is_said() -> None:
    python = python_of(machine(py_on_path=False))

    assert python["installs"] == []
    assert python["notes"] == [NOT_FOUND]


def test_an_empty_listing_adds_nothing() -> None:
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
    assert paths(python) == [(REAL_313, "path")]
    assert system.runs.count((REAL_313, "--version")) == 1


def test_one_python_seen_by_uv_the_launcher_and_path_is_one_install() -> None:
    # The real launcher listing, with the path of the uv-managed 3.13.16 in it.
    real = load_capture(PY_LISTING_WINDOWS).result.stdout
    text = real.replace(REAL_313.encode(), UV_313.encode())
    system = machine(answer(text), path=[UV_BIN, UV_313.rpartition("\\")[0]])
    system.add_executable(UV, load_capture(UV_WINDOWS), load_capture(UV_PYTHON_LIST_WINDOWS))
    system.add_executable(UV_313, load_capture(PYTHON_313_WINDOWS))
    system.add_executable(UV_314, load_capture(PYTHON_314_WINDOWS))

    python = python_of(system)

    assert python["active"]["path"] == UV_313
    assert [p for p in paths(python) if p[0] == UV_313] == [(UV_313, "path")]
    assert (UV_314, "uv") in paths(python)


def test_the_launcher_is_listed_as_a_windows_provider_of_python() -> None:
    result = run_cli(machine(), "tools", "--json")

    [py] = [p for p in json.loads(result.stdout)["providers"] if p["id"] == "py"]
    assert (py["name"], py["os"], py["tools"]) == ("py launcher", ["windows"], ["python"])
