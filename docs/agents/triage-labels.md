# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker, and lists the extra labels this repo uses.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

## Additional labels

Apply one **type** label and one **priority** label to each triaged issue.

| Group    | Label               | Meaning                                   |
| -------- | ------------------- | ----------------------------------------- |
| Type     | `bug`               | Something is broken                       |
| Type     | `feature`           | New capability                            |
| Type     | `enhancement`       | Improvement to an existing capability     |
| Type     | `documentation`     | Docs-only change                          |
| Type     | `chore`             | Maintenance, tooling, dependencies        |
| Type     | `question`          | Needs an answer, not a change             |
| Priority | `priority:critical` | Drop everything                           |
| Priority | `priority:high`     | Next up                                   |
| Priority | `priority:medium`   | Normal backlog                            |
| Priority | `priority:low`      | Nice to have                              |
| Other    | `duplicate`         | Already tracked elsewhere                 |
| Other    | `good first issue`  | Small and well scoped                     |
