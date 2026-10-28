"""`npm run doctor`: the contributor toolchain check, through the CLI seam.

scripts/doctor.mjs derives its requirements from the repo's own pins. The tests take
that requirement list from the script (`--requirements`), run it through the real
`versionbar check` over a fake machine built from captures, and feed the JSON result
back to the script (`--report`) to see what a contributor would read.
"""

import json
import subprocess
from pathlib import Path

from fakes import WINDOWS_PATHEXT, FakeSystem, load_capture, run_cli

ROOT = Path(__file__).resolve().parents[2]
DOCTOR = str(ROOT / "scripts" / "doctor.mjs")
BIN = r"C:\dev\bin"

CAPTURES = {
    "node": "node/windows-node-24.21.0.json",
    "npm": "npm/windows-npm-11.19.0.json",
    "uv": "uv/windows-uv-0.12.23.json",
    "rustc": "rustc/windows-rustc-1.99.1.json",
    "cargo": "cargo/windows-cargo-1.99.1.json",
}


def machine(**without: None) -> FakeSystem:
    """A machine with every contributor tool except those passed as `tool=None`."""
    system = FakeSystem(
        os="windows", env={"PATH": rf"C:\WINDOWS\system32;{BIN}", "PATHEXT": WINDOWS_PATHEXT}
    )
    for tool, capture in CAPTURES.items():
        if tool not in without:
            system.add_executable(rf"{BIN}\{tool}.exe", load_capture(capture))
    return system


def doctor_script(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", DOCTOR, *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )


def requirements() -> list[str]:
    return json.loads(doctor_script("--requirements").stdout)


def run_doctor(
    system: FakeSystem, reqs: list[str] | None = None
) -> tuple[int, subprocess.CompletedProcess[str]]:
    checked = run_cli(system, "check", *(reqs or requirements()), "--json")
    return checked.exit_code, doctor_script("--report", stdin=checked.stdout)


def test_the_requirements_are_the_five_tools_at_the_repo_pins() -> None:
    assert requirements() == [
        "node@>=24",
        "npm@>=11",
        "uv@>=0.8",
        "rustc@==1.99.1",
        "cargo@==1.99.1",
    ]


def test_a_correctly_prepared_machine_passes() -> None:
    check_exit, report = run_doctor(machine())

    assert check_exit == 0
    assert report.returncode == 0, report.stdout + report.stderr


def test_a_too_old_tool_fails_naming_the_tool_and_how_to_fix_it() -> None:
    check_exit, report = run_doctor(machine(), ["node@>=99", "npm@>=11"])

    assert check_exit == 1
    assert report.returncode == 1
    assert "node" in report.stdout and "24.21.0" in report.stdout
    assert "winget install --id OpenJS.NodeJS.LTS" in report.stdout


def test_a_missing_tool_fails_with_its_remediation() -> None:
    check_exit, report = run_doctor(machine(rustc=None, cargo=None))

    assert check_exit == 1
    assert report.returncode == 1
    assert "rustc" in report.stdout and "cargo" in report.stdout
    assert "winget install --id Rustlang.Rustup" in report.stdout


def test_a_missing_uv_points_at_the_uv_install() -> None:
    _, report = run_doctor(machine(uv=None))

    assert report.returncode == 1
    assert "winget install --id astral-sh.uv" in report.stdout


def test_an_invalid_config_is_reported_as_such_not_as_a_missing_result() -> None:
    system = machine()
    system.add_config("colour = true\n")
    checked = run_cli(system, "check", *requirements(), "--json")
    assert checked.exit_code == 3

    report = doctor_script("--report", "--exit-code", "3", stdin=checked.stderr)

    assert report.returncode == 1
    assert "config file cannot be used" in report.stdout
    assert "colour" in report.stdout
    assert "npm run cli -- config" in report.stdout
