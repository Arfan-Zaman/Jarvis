# Self-review 2026-11-16 (2)

Three small changes. `python3 -m unittest discover -s tests`: 333 tests pass (4 new or extended).

## 1. Goal steps: accept inputs placed beside `"inputs"`, and say what the tool takes on retry

- **What:** `jarvis/engine/engine.py`. When asked for an ACTION, the engine now also
  accepts a step tool's inputs written at the top level of the reply
  (`{"query": "..."}` or `{"inputs": {}, "query": "..."}`). Only names that are
  real inputs of that tool are picked up, and they still go through
  `ToolRegistry.validate`. If validation fails, the retry message now lists the
  tool's inputs, e.g. `web.search takes {"inputs": {...}} with: query (string, required), limit (integer)`.
- **Why:** Run #45 failed with `The model gave an unusable action twice: web.search: 'query' is required`.
  The local qwen3.5:9b sent no `query` inside `"inputs"` on both tries. The retry only
  repeated the error, without the input names, so the model had nothing to correct
  itself with. Putting arguments beside `"inputs"` is a common small-model mistake.
- **Checked:** `test_inputs_beside_the_inputs_key_are_accepted` (both shapes finish the
  goal) and `test_retry_after_missing_input_names_the_tool_inputs` (the retry prompt names
  `title (string, required)`). `test_invalid_action_inputs_never_reach_the_tool` still
  passes, so bad inputs are still refused.

## 2. `web.fetch` focus: keep repeated lines only once, skip lines that are too long

- **What:** `_focus` in `jarvis/tools/web.py`. A line that appears more than once is kept
  only once. A matching line too long for the space left is now skipped instead of
  ending the search.
- **Why:** Run #46 failed because "the fetch result was mostly repetitive text without the
  key data". Repeated menu, share and banner lines that contain a focus word filled the
  budget before the real answer got in. Also, the old `break` meant that when one long
  matching paragraph didn't fit, every later line was dropped. If nothing had been kept
  yet, the whole unfocused page came back, cut at `max_chars`.
- **Checked:** `test_focus_drops_repeated_lines_and_skips_lines_too_long`: an over-long
  line comes first, then 30 copies of a "share" line, then the answer. The output is the
  share line once plus the answer. Under the old code only the answer came back,
  because the loop stopped at the long line. The existing focus test still passes.

## 3. `jarvis.info` reports the running git commit

- **What:** `jarvis/tools/builtin.py`. `jarvis.info` now returns `"commit"`: the short
  `git rev-parse HEAD`, read once when the module loads, so it shows the build that is
  actually running and not whatever is checked out later. It is `None` outside a git
  checkout or if git fails. The command is fixed with no inputs and has a 5 s timeout.
- **Why:** Run #83 failed with "jarvis.info shows version '0.1.0' without a commit
  reference", so JARVIS could not answer "is the latest build (commit 43ec309) running?"
- **Checked:** `test_info_and_health` now checks the field: either `None` or an
  alphanumeric hash.
