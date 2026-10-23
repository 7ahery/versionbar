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

npm 11 is required (it matches the `packageManager` pin in `package.json`, see Pins).

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
| Date | 2026-10-24 |
| Machine (OS build, CPU arch) | Windows 11 Pro 10.0.26200, x64 |
| `rustc --version` | rustc 1.99.1 (58cf8f9c3 2026-10-13) |
| `cargo --version` | cargo 1.99.1 (5f94df478 2026-08-27) |
| `cargo run` output of `hello` | Compiled, linked and printed `Hello, world!` |
| `npm --version` | 11.19.0 (Node v24.21.0) |
| `uv --version` | uv 0.12.23 (x86_64-pc-windows-msvc) |
| Notes (UAC, errors, workarounds) | No UAC prompts, no errors, no workarounds. |

## Pins

Pins now in the repo, and how this page matches them:

| Pin | Value | Where |
| --- | --- | --- |
| npm | 11.19.0 | `packageManager` in `package.json`; step 3 installs npm 11 |
| Node.js | `>=24` | `engines.node` in `package.json`; the LTS in step 3 satisfies this |
| Python | 3.14 | `core/.python-version`; uv downloads it, so step 4 installs no Python |
| Rust | 1.99.1 stable, `x86_64-pc-windows-msvc`, with rustfmt and clippy | `rust-toolchain.toml`; rustup (step 1) downloads it on the first `cargo` command in the repo |

Step 1's `rustup default` only sets the machine-wide fallback; inside the repo
`rust-toolchain.toml` wins. The pin is an exact stable release so that a new Rust release
cannot fail `clippy -D warnings` without a code change.

## After cloning

Once per checkout:

```powershell
npm install                         # UI and Tauri CLI (npm workspace app/)
cargo install cargo-deny --locked   # dependency licence and advisory checks in `npm run lint`
```

Then `npm run dev` launches the tray app with hot reload (see README).
