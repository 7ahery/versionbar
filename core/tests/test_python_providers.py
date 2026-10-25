"""The uv Python provider, through the CLI seam.

`uv python list --only-installed --output-format json` answers with a real
capture (uv 0.12.23, holding managed 3.14.8 and 3.13.16, also listing uv's
`python3.14.exe` shim and a minor-version link folder for the same 3.14.8).
Machine state (PATH, environment) is synthetic; version output is the real
python captures.
"""

import json

from versionbar.system import ProcessResult

from fakes import (
    PYTHON_313_WINDOWS,
    PYTHON_314_WINDOWS,
    STORE_PYTHON_PLACEHOLDER,
    UV_PYTHON_LIST_WINDOWS,
    UV_WINDOWS,
    WINDOWS_PATHEXT,
    Capture,
    FakeSystem,
    load_capture,
    run_cli,
)

UV_BIN = r"C:\Users\dev\.local\bin"
UV = rf"{UV_BIN}\uv.exe"
UV_PYTHONS = r"C:\Users\dev\AppData\Roaming\uv\python"
PY_314 = rf"{UV_PYTHONS}\cpython-3.14.8-windows-x86_64-none\python.exe"
PY_313 = rf"{UV_PYTHONS}\cpython-3.13.16-windows-x86_64-none\python.exe"
LIST_ARGS = ("python", "list", "--only-installed", "--output-format", "json")
WINDOWS_APPS = r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps"


def machine(*, uv_on_path: bool = True, uv_list: Capture | None = None) -> FakeSystem:
    """uv-managed Pythons that are not on PATH."""
    path = [r"C:\WINDOWS\system32"] + ([UV_BIN] if uv_on_path else [])
    system = FakeSystem(os="windows", env={"PATH": ";".join(path), "PATHEXT": WINDOWS_PATHEXT})
    system.add_executable(
        UV, load_capture(UV_WINDOWS), uv_list or load_capture(UV_PYTHON_LIST_WINDOWS)
    )
    system.add_executable(PY_314, load_capture(PYTHON_314_WINDOWS))
    system.add_executable(PY_313, load_capture(PYTHON_313_WINDOWS))
    return system


def python_of(system: FakeSystem) -> dict:
    result = run_cli(system, "show", "python", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def installs(tool: dict) -> list[tuple[str, str, str]]:
    return [(i["version"], i["path"], i["source"]) for i in tool["installs"]]


def test_uv_managed_pythons_off_path_are_listed_once_each_with_source_uv() -> None:
    python = python_of(machine())

    # uv names the same 3.14.8 three times (the install, its shim in the bin
    # folder, the minor-version link); only the install folder is the install.
    assert python["status"] == "missing"
    assert python["active"] is None
    assert installs(python) == [("3.14.8", PY_314, "uv"), ("3.13.16", PY_313, "uv")]


def test_a_python_on_path_stays_active_and_is_not_listed_twice() -> None:
    system = machine()
    system.env["PATH"] += rf";{UV_PYTHONS}\cpython-3.13.16-windows-x86_64-none"
    system.add_executable(
        rf"{UV_PYTHONS}\cpython-3.13.16-windows-x86_64-none\python.exe",
        load_capture(PYTHON_313_WINDOWS),
    )

    python = python_of(system)

    # uv's newer 3.14.8 does not take over: typing `python` runs the PATH hit.
    assert python["active"]["path"] == PY_313
    assert installs(python) == [("3.13.16", PY_313, "path"), ("3.14.8", PY_314, "uv")]
    assert system.runs.count((PY_313, "--version")) == 1


def test_uv_found_through_uv_install_dir_when_not_on_path() -> None:
    system = machine(uv_on_path=False)
    system.env["UV_INSTALL_DIR"] = f'"{UV_BIN}"'

    assert [i[2] for i in installs(python_of(system))] == ["uv", "uv"]


def test_without_uv_nothing_is_added_and_nothing_is_said() -> None:
    system = machine(uv_on_path=False)

    python = python_of(system)

    assert python["installs"] == []
    assert python["notes"] == ["not found on PATH (looked for: python, python3)"]
    assert all(run[1:2] != ("python",) for run in system.runs)


def test_uv_with_no_pythons_adds_nothing() -> None:
    empty = ProcessResult(exit_code=0, stdout=b"[]", stderr=b"")

    python = python_of(machine(uv_list=Capture(LIST_ARGS, empty)))

    assert python["installs"] == []
    assert python["notes"] == ["not found on PATH (looked for: python, python3)"]


def test_a_failing_uv_listing_is_a_note_and_loses_nothing_else() -> None:
    for result in (
        ProcessResult(exit_code=2, stdout=b"", stderr=b""),
        ProcessResult(exit_code=0, stdout=b"not json", stderr=b""),
        ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error="access denied"),
        ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True),
    ):
        system = machine(uv_list=Capture(LIST_ARGS, result))

        python = python_of(system)

        assert python["installs"] == []
        [first, *_, last] = python["notes"]
        assert first == "not found on PATH (looked for: python, python3)"
        assert last.startswith("uv: could not list installs: ")


def test_a_hanging_uv_listing_gives_up_after_the_tools_timeout() -> None:
    system = machine(uv_list=Capture(LIST_ARGS, ProcessResult(0, b"[]", b""), seconds=60))

    python = python_of(system)

    assert (
        python["notes"][-1]
        == "uv: could not list installs: uv python list did not answer within 5 s"
    )


def test_a_broken_managed_python_is_a_note_and_the_other_still_counts() -> None:
    system = machine()
    system.add_executable(PY_314, Capture(("--version",), ProcessResult(1, b"", b"")))

    python = python_of(system)

    assert installs(python) == [("3.13.16", PY_313, "uv")]
    assert python["notes"][-1].startswith(f"uv: {PY_314} exited with code 1")


def test_a_store_placeholder_is_still_missing_while_uv_pythons_are_listed() -> None:
    system = machine()
    system.env["PATH"] += f";{WINDOWS_APPS}"
    system.add_app_execution_alias(rf"{WINDOWS_APPS}\python.exe", STORE_PYTHON_PLACEHOLDER)

    python = python_of(system)

    assert python["status"] == "missing"
    assert python["active"] is None
    assert [i[2] for i in installs(python)] == ["uv", "uv"]


def test_uv_is_listed_as_a_windows_provider_of_python() -> None:
    result = run_cli(machine(), "tools", "--json")

    [uv] = [p for p in json.loads(result.stdout)["providers"] if p["id"] == "uv"]
    assert (uv["name"], uv["os"], uv["tools"]) == ("uv", ["windows"], ["python"])


def test_check_says_a_held_python_is_not_on_path_rather_than_not_installed() -> None:
    result = run_cli(machine(), "check", "python@>=3.13", "--json")

    [requirement] = json.loads(result.stdout)["requirements"]
    assert requirement["outcome"] == "missing"
    assert "not installed" not in requirement["message"]
    assert requirement["message"].startswith("python is not active: not found on PATH")
    assert "2 installs found off PATH" in requirement["message"]
