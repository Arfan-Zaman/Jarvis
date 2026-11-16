# Self-review 2026-11-16 (3)

Two small fixes. Tests: `python3 -m unittest discover -s tests` passes all 343 tests (1 skipped).

## 1. Goal engine: accept tool inputs the model puts beside `"inputs"`

**What:** `jarvis/engine/engine.py`, the ACTION check in `Engine._step`. If the model's reply has
keys that are this tool's own input names but sit at the top level (`{"query": "..."}`, or
`{"inputs": {}, "query": "..."}`), they are moved into `inputs`. Only the tool's declared input
names are moved, and they still go through `ToolRegistry.validate`. A reply with no `inputs` and
none of the tool's input names is still rejected, and so is `{"inputs": "text"}`.

**Why:** Failed run 45 ("Find out what the tallest mountain in Australia is") ended with
`The model gave an unusable action twice: web.search: 'query' is required`. That error comes from
`validate` when the reply has an `inputs` object without `query` in it. The likeliest cause is that
qwen3.5:9b put the query next to `inputs` instead of inside it. I inferred this from the error text.
I did not read the run's stored replies, so I have not confirmed it. Either way, the old check
threw away an answer that could have been used, and the goal failed.

**Checked:** new tests `test_inputs_placed_beside_inputs_are_lifted` (both reply shapes create the
task) and `test_stray_keys_are_not_mistaken_for_inputs` (unrelated keys still fail and the tool
never runs). The existing `test_invalid_action_inputs_never_reach_the_tool` still passes.

## 2. `web.fetch`: no crash on unknown or quoted charsets

**What:** `jarvis/tools/web.py`, `web_fetch`. If a page names a charset Python does not know
(for example `charset=utf8mb4`, which some sites send), the page is now read as UTF-8. Before, it
crashed with `LookupError`. The charset pattern also accepts quotes now (`charset="iso-8859-1"`).
Before, a quoted charset was silently ignored and the page was decoded as UTF-8, which garbled
accented text.

**Why:** The code: `body.decode(charset, "replace")` raises `LookupError` for an unknown codec
name (`"replace"` only covers bad bytes). The registry caught it as a crash
(`LookupError: unknown encoding: ...`), so the page could not be read at all. This one is from
reading the code, not from a log line.

**Checked:** new test `test_unknown_and_quoted_charsets_are_read` covers a `utf8mb4` page and a
quoted Latin-1 page, and both give back the text `Café prices`.

## Looked at, not changed

- Run 154 (weather "tomorrow" fetched with days=1): already fixed in HEAD (`open_weather` asks for
  at least 3 days).
- Run 167 (`www.aph.gov.au answered HTTP 403`): the site blocks automated clients. `web.py` says on
  purpose that JARVIS does not get around bot detection, so I left it alone. `browser.read` is the
  way to read such pages.
- Run 2 (Claude OAuth expired): the owner needs to log in again. Nothing to fix in code.

## Needs the owner

Nothing.
