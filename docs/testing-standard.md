# The testing standard

**A test is not trusted until it has been shown to fail against the code it is
meant to catch.**

Our suites are behavior-first — Python `unittest`, the Node model tests, and a
hermetic integration suite. A green run only means something if each test has
been *seen* to go red when the behavior it pins is broken. That is the house
rule, and it is the one that keeps "the tests pass" honest.

## Break the rule, watch the test fail

Change the source so the behavior is wrong, run the suite, and watch the test
you are relying on go red. Restore, run again, watch it pass. Say so in the
commit body — *"proven red against X"*. A test that has not earned its green
this way is a comment with extra steps.

Rules, each learned the hard way (adapted from OmaCal's standard):

1. **Delete the branch, don't perturb it.** A perturbed condition can leave the
   behavior observably identical, and then a green suite proves nothing. If the
   branch is `if quotaKnown && quota > 0`, delete the guard outright; making it
   `>= 0` may look the same under the fixture.

2. **Check the mutation actually applied — with a count.** A string occurs more
   than once in real code. Grep for the mutation (with a count or a line match)
   *before* running, so "the suite went green" cannot mean "the edit missed".

3. **Run the whole suite.** `python3 -m unittest discover -s tests` runs unit
   *and* integration; a mutation caught by one test is often caught by several.
   Stopping at the first failure misreports the net as narrower than it is.

4. **Restore from a copy, never an inverse edit.** `cp` the file aside first,
   move it back, then `git diff --quiet` to confirm the tree is clean — a revert
   that is itself a string operation can fail in ways the mutation never could.

5. **On disk is not the same as reachable.** A mutation that reddens nothing is
   either a survivor (the net is thin — add a test) or inert (nothing reads the
   value — the test was fine). The two look identical until you read what
   consumes what you changed.

## What this looks like here

- **`tests/model.test.js`** — pure functions in `Model.js` (formatters, the
  state machine, `filesVisible`). Mutate a return value, run
  `node tests/model.test.js`, and expect exactly the assertions that cover it to
  fail.
- **`tests/test_status.py`** — `bin/status` is loaded in-process; mutate a probe
  or the fragment merge and watch the specific test go red.
- **`tests/test_setup.py` / `tests/integration/`** — `bin/setup` is bash driven
  as a subprocess with fake tooling; break a unit-file line or the ownership
  marker and watch the integration test catch it.
- `bin/status` and `bin/setup` are shellcheck-clean; a behavior change there
  needs a test as much as a QML property does. QML itself is covered only by the
  live pass — see [verification.md](verification.md).

## Why it is here

A suite that has never been seen to fail is indistinguishable from one that
asserts nothing. This document exists so "the tests pass" can be trusted after a
change as much as before it.
