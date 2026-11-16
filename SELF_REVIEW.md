# Self-review 2026-11-16 (2): teaching the domain-check gap

Gap: *[browser] "Search for the domain 'aureusdetailing.com.au' to check its availability and ownership
details."* Run #237 failed at 21:13 with `browser_type ... expected string, received undefined → at target`
three times.

The bug behind that log line (Playwright MCP 0.0.85 wants `target`, not `ref`) was already fixed in
commit 968fe53 (21:17, after the failed run). I left that fix as it is and made the three changes below.

## 1. New tool `open.domain`: domain lookups without the browser
- **What:** `jarvis/tools/opendata.py` gets `open.domain`. It finds the domain's registry through IANA's
  RDAP list (`data.iana.org/rdap/dns.json`; for `.au` that's auDA), then reads the registry's record.
  It returns whether the name is registered, the registrar, the holder if the registry shows it,
  registration and expiry dates, status and nameservers. If the registry answers 404, it reports the
  name as looking available, and for `.au` names it adds auDA's rule that you need an ABN/ACN.
  It's free, needs no key, is read-only (`web_read`), and is registered with the other open-data tools.
- **Why:** the owner's question can be answered with one request to the official registry. Before,
  the 9b model had to drive a WHOIS website step by step, and that is how run #237 got stuck.
- **How to ask:** "Is aureusdetailing.com.au available?", "Who owns monsoormotors.com.au?",
  "whois example.com", "When does my domain expire?"
- **Checked:** unit tests cover parsing a registered record (registrar from a nested vCard, dates,
  nameservers, `https://www.` and path removed), the 404 "available" case with the auDA note, and
  rejecting input that isn't a domain. **I could not reach the live service:** network calls were
  blocked in this session. After merging, please check it once by asking about aureusdetailing.com.au.

## 2. Domain questions go to `open.domain` before the router
- **What:** a new `DOMAIN_CHECK` pattern in `jarvis/engine/conversation.py` matches a domain name or the
  word "domain" near words like available, owner, registered or expiry, or the words "whois"/"rdap".
  Messages that match go through the existing one-pick `_quick_tool` path: the fast model picks
  `open.domain`, JARVIS runs it, and the local model answers from the data. The pattern skips file
  names (`report.pdf`), attachments and messages that ask JARVIS to do something (send, buy, ...).
  If nothing fits, the message falls through to normal routing as before.
- **Why:** the router had sent the gap's message to `browse` mode, which became "Use the browser.use
  tool ...". That path skips the open-data tools completely (see the `startswith` check in `reply`).
- **Checked:** test with the exact gap sentence, "who owns …", "whois …", plus negative cases
  (a PDF, a weather question).

## 3. The browser agent accepts refs however the model writes them
- **What:** `_ref()` in `jarvis/tools/browser.py` turns `"e5"`, `"[ref=e5]"`, `"ref=e5"` and a
  `"target"` key all into `e5` before click and type.
- **Why:** the snapshot shows elements as `[ref=e5]`, and a small local model often copies that text
  as-is, or uses Playwright's own word `target`. Before this, such a step failed with "no such element"
  until the agent gave up after three repeats, which is the same kind of loop as run #237.
- **Checked:** a unit test for the formats, and a mocked `_browser_use` run where the model writes
  `"target": "[ref=e5]"`. The test checks that `browser_type` receives `target: "e5"` and the text.

Full suite: `python3 -m unittest discover -s tests`: 353 tests, OK (1 skipped).

## Needs the owner
- Nothing to install. Please do the live check from change 1 after merging.
