# UI fixtures

Real `versionbar list --json` output from the development machine (Windows 11), with the
user profile folder replaced by `%USERPROFILE%`. Nothing else is edited.

| File                              | How it was captured                                                                                                                                                                                                                         |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list-windows.json`               | `npm run cli -- list --json` (ticket 21).                                                                                                                                                                                                   |
| `list-windows-installs.json`      | `npm run cli -- list --json` (ticket 25): Git twice on PATH, Node.js active from nvm's install folder plus nvm's shim.                                                                                                                      |
| `list-windows-problems.json`      | The real CLI over the real machine with only the config folder redirected to a config holding `timeouts.git = 0.001` and a custom `uv` definition whose `version_args` is `["--no-such-flag"]`, so Git times out and uv errors (ticket 25). |
| `list-windows-provider-only.json` | `uv run --project core versionbar list --json` with every nvm folder removed from PATH but `NVM_HOME` kept, so Node.js is missing while the nvm provider still reports its version (ticket 25).                                             |

Python is a Microsoft Store placeholder on this machine, so it is missing in all of them.

## Preferences query

Real `versionbar config --json` output from the same machine (ticket 41), redacted the same way. The two cases with a config file ran the real CLI with only the config folder redirected (platformdirs' `user_config_dir` patched to a scratch folder holding the file), which is why their `config_path` is not the usual `AppData\Roaming` one.

| File                             | Config file                                                                                                                                   | Exit code |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| `config-windows-defaults.json`   | None, so every default applies (`uv run --project core versionbar config --json`).                                                            | 0         |
| `config-windows-update-off.json` | `pinned = ["node"]` and `[app] update_check = false`.                                                                                         | 0         |
| `config-windows-invalid.json`    | `pinned = ["node", "nod"]` and `[app] update_check = 1`; only the type error is reported, since unknown ids are checked once types are valid. | 3         |
