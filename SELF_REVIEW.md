# Self-review 2026-11-16 (2, second pass): learning passes wasted on repeats

## 1. The learner sees every query it refuses, and gets one retry
- **What:** in `Learner.pick()` (`jarvis/learner.py`), the "Recently read (do not repeat)" list in the
  prompt now shows every stored recent query, not only the last 25. If the model still repeats one, JARVIS
  tells it "“…” was already read. Choose a different topic." and asks once more. The error messages now say
  which case happened: "no query in the reply (...)" or "no new query chosen: “…” was already read".
- **Why:** the log line `21:37:19 Learning pass skipped: no new query chosen ('{\n"query": "Aureus
  Detailing Perth Google Ads cost per lead November 2026", ...` shows a whole pass lost. The cause is in the
  code: `once()` stores up to 50 recent queries (`[-50:]`), and `pick()` refuses a repeat of any of the 50,
  but the prompt only listed the last 25. Queries 26 to 50 were refused without the model ever being told
  about them. The old message also cut the reply at 120 characters, so you could not tell from the log
  whether the reply was unreadable or a repeat.
- **Checked:** two new tests in `tests/test_learner.py`. One stores 40 recent queries, has the model
  repeat the oldest one, and checks that it was listed in the prompt, that the retry names it, and that the
  second answer is used. The other has the model repeat itself twice and checks the pass is skipped with
  "was already read". The existing test `test_a_repeated_query_is_refused` still passes.
  Full suite: `python3 -m unittest discover -s tests`: 356 tests, OK (1 skipped).

## Looked at, not changed
- Run #237 (`browser_type ... at target`), run #154 (weather "tomorrow") and run #45 (`'query' is
  required`) are already fixed in the code: browser refs are normalised, `open.weather` always fetches
  at least 3 days, and the engine moves inputs written beside `"inputs"` into it.

## Needs the owner
- Nothing.
