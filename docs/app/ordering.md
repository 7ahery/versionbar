# Change highlighting and ordering in the popup

All of this lives in the React UI (`app/src/tools.ts`, `ToolList.tsx`). Rust never diffs or
sorts tool data (hard rule 2); it supplies the saved `current` and `previous` scans
([state.md](state.md)) and the config's `pinned` and `order` lists
([preferences.md](preferences.md)).

## Change highlighting

The popup compares the `current` scan with `previous`, the last successful scan before it.
That pair is all the history there is: nothing says "since the update" or shows a version
older than `previous` holds. With no `previous` (first run, or nothing saved) nothing is
highlighted. The saved pair survives a restart, so highlighting does too.

Per tool, matched by id:

| Previous scan | Current scan | Shown |
|---|---|---|
| found, active version `a` | found, active version `b` ≠ `a` | `a → b` in place of the version |
| missing, or tool not listed | found | badge "Newly found" |
| error or timeout | found | badge "Recovered" (not an upgrade; no earlier version is shown) |
| found, version `a` | missing | badge "Newly missing (was a)", in the missing section |
| found, version `a` | error or timeout | badge "Newly failing (was a)", in the main list |
| missing, or tool not listed | error or timeout | badge "Newly failing" |
| anything else (same version, still missing, still failing) | | nothing |

Only the active version counts: a different path or install list with the same active
version is not a change. A tool that is not in `current` is not shown.

## Order

Missing tools keep their own section at the bottom behind the toggle (shown directly while
searching). The rule below applies to each section on its own, so no missing tool moves above
the main list because it is pinned or changed.

Within a section:

1. Pinned ids, in `pinned` order.
2. Ids in `order` that are not pinned, in `order` order.
3. Everything else: tools with any highlighted change first (every badge and `a → b` counts), then by name ignoring case, then by id.

The order is total, so it never depends on the order the core printed. Search filters first;
the matches keep this order. Ids in the lists that match no tool are ignored.

Without usable preferences (not answered yet, or an invalid config, where `preferences` is
null) nothing is pinned or ordered.

### Duplicate ids

The core rejects them: an id may appear at most once across `pinned`, `order` and `hidden`
([config.md](../config.md#tool-ids)), so an invalid file gives `problems` and no
`preferences`. The UI therefore never sees duplicates from a real config; if it did, it would
use each id's first position.

### Why this differs from `versionbar list`

`list` orders pinned, then ordered, then registry order. The popup replaces the last step
with changed-first, name and id, because it has a previous scan to compare with and shows a
single section order. The pin and order lists are the same.
