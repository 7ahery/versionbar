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
