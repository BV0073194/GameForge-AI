# GameForge UI: non-disruptive live updates

The desktop dashboard still updates while the agent builds, edits, tests, or asks
for input, but **refreshing no longer destroys what the user is doing**.

## What changed

- **Single-flight state polling:** the dashboard allows only one project-state
  request at once. It schedules the next refresh after the previous one finishes
  (approximately every two seconds when visible, eight seconds when hidden).
  Late responses from an older selected project are discarded. The desktop
  backend/session heartbeat is independent from these UI paint updates.
- **Incremental rendering:** dynamic panels replace their DOM **only when their
  content has actually changed**. Changing a status or updating a log does not
  rebuild the rest of the page.
- **Copy/select text without losing it:** when the user is selecting text,
  updates to that selected region are temporarily deferred. New data appears
  after selection ends and the next poll runs. Activity, queue, acceptance,
  review, runtime summaries, and visual metrics use this behavior.
- **Persistent expanded details:** work-order and log `<details>` retain their
  open/closed state, and scrollable detail positions are restored when actual
  content changes. Work orders have stable IDs.
- **Form edits win over server snapshots:** changing a native select, text box,
  JSON editor, or checkbox marks it locally dirty. Automatic refreshes never
  overwrite these edits, even after the control loses focus. The Save settings
  action clears only edits that **actually match the submitted values**, so a
  second change made while an API request is in flight stays protected.
  Project switches clear the old project's editor state and stale question UI.
- **Agent questions are keyed:** the question editor (including native
  dropdowns, file inputs, JSON forms and text answers) is created once per
  request identity/schema and stays mounted between polls. Only a new or
  resolved question changes its controls.
- **Capture optimization:** the latest image URL changes only when the capture
  timestamp changes, avoiding repeated image downloads and flicker.
- **Copy buttons:** activity details, live work queue, logs, and build/test
  output can be copied directly. The browser Clipboard API is used on
  supported localhost/secure contexts, with a simple legacy fallback.
- **Explicit text selection styling:** selectable evidence/logs remain
  selectable even inside cards and expandable sections.

## Behavior during selection and editing

If the agent generates a new update while you are reading or highlighting
evidence, the UI retains the existing visible text until you finish selecting
it. Meanwhile the underlying autonomous agent keeps running normally.

Changes in an unsaved Settings field are not silently replaced by current
server configuration. Choose **Save settings** when you want to persist them.
The dashboard reports how many fields are unsaved.

## Tests and deployment

`node --test GameForgeAI/tests/test_ui_refresh.cjs` executes offline
interaction tests without npm packages. The normal source smoke workflow runs
this test and Node syntax checks on Windows and Ubuntu. It exercises:

- unchanged DOM, details-open state and scroll preservation;
- copying and selection during live text changes;
- native dropdown and text-field edits through server polling;
- edits made while a settings save is outstanding;
- stable agent-question controls and correct dismissal;
- stable capture URLs, concurrent request prevention, and resumed display.

The PyInstaller spec already packages the entire `web/` directory, including
`ui_refresh.js`. An already-installed executable must still be **replaced with
a newly built version** for these changes to appear. Passing offline tests
does not guarantee behavior on every Windows browser or Codex installation;
a live interaction test remains advisable.
