# Windows development setup

One-time machine setup for contributing to VersionBar on Windows 11. Run these
yourself; **the app never performs these installs** (setup is kept separate from
product behavior). The commands install system-wide software and may show UAC prompts.

Package IDs were checked against `winget show` on 2026-10-23.

## 1. Rust (rustup, stable MSVC toolchain)

```powershell
winget install --id Rustlang.Rustup --exact
rustup default stable-x86_64-pc-windows-msvc
```

The MSVC host triple is required: Tauri on Windows links with the MSVC linker, not GNU.

## 2. Visual Studio 2022 Build Tools (C++ workload)

Rust's MSVC target needs `link.exe` and the Windows SDK from this workload.

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

`--includeRecommended` pulls in the Windows 11 SDK and CMake tools. Approve the UAC
prompt. The install is large (several GB) and can take a while.

## 3. Node.js and npm

npm 11 is required (it must match the `packageManager` pin once it lands, see below).

```powershell
winget install --id OpenJS.NodeJS.LTS --exact
npm --version   # in a new terminal; expect 11.x
```

If the LTS bundles an older npm, upgrade with `npm install -g npm@11`.

## 4. uv

uv is the one hard prerequisite for the Python core; it manages Python itself, so do
not install a system Python.

```powershell
winget install --id astral-sh.uv --exact
```

## 5. WebView2 (Windows 11)

The tray app's flyout uses the WebView2 runtime. Windows 11 ships it preinstalled and
keeps it updated, so no action is normally needed. Only if it is missing:

```powershell
winget install --id Microsoft.EdgeWebView2Runtime --exact
```

## 6. Verify (prove the linker works)

Tool presence is not proof. Open a **new** terminal (so PATH is refreshed), then:

```powershell
rustc --version
cargo --version
cd $env:TEMP
cargo new --bin hello
cd hello
cargo run
```

Success is `cargo run` compiling, linking and printing `Hello, world!`. A
`linker 'link.exe' not found` error means the C++ workload is missing or incomplete:
re-run the Build Tools installer, confirm "Desktop development with C++", and retry in
a new terminal. Delete `%TEMP%\hello` afterwards.

## Verification record

To be filled in by the human who performs the setup (ticket 02 / issue #3).

| Item | Result |
| --- | --- |
| Date | TODO |
| Machine (OS build, CPU arch) | TODO |
| `rustc --version` | TODO |
| `cargo --version` | TODO |
| `cargo run` output of `hello` | TODO |
| `npm --version` | TODO |
| `uv --version` | TODO |
| Notes (UAC, errors, workarounds) | TODO |

## Pins to reconcile

The repo does not yet pin tool versions. `rust-toolchain.toml`, `.python-version`
and `packageManager`/`engines` in `package.json` arrive with tickets 03 and 20. When
they land, update this page so the versions above match the pins (notably npm 11 and
the stable Rust channel).
