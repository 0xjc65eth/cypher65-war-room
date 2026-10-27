# Issue #867 — Fail-closed JS child-suite execution

## Confirmed defect and scope

Base: `f479382750f608b44d3a8dfd6a163ab87ae97d6a` (`master`).

The CI command `node --test tests/test_app_js_core.js` supplies Node's internal
`NODE_TEST_CONTEXT` to the core process. The old Mini War Room and Energy Advisor
`spawnSync(node, ['--test', file])` calls inherited it. Node could refuse the
recursive runner, skip the files and still exit zero. The old status-only gate
accepted that as success. Direct core execution exposed the known Mini worker
regression (#863), while the same source under the CI command returned a false
green. These are local reproductions, not claims that a historical CI green
proved execution of the suppressed suites.

This change is test infrastructure only. It preserves both feature suites and
their assertions, the existing core command and Node major version, production
source, dependencies and coverage settings. It does **not** include the #863
Service Worker fix or claim provider, hardware, TLS or deployed validation.

## Shared runner and machine receipt

`tests/helpers/node-child-runner.js` runs an awaited bounded child, copies the
caller environment, and removes only `NODE_TEST_CONTEXT`. Legitimate variables,
including `NODE_OPTIONS` and `NODE_V8_COVERAGE`, are preserved. It resolves source
path aliases before comparing execution evidence, because Node reports canonical
paths (notably `/var` versus `/private/var` on macOS). Missing source files still
fail in the child. Timeout, signal, spawn error, nonzero exit, absent/malformed
receipt, incomplete stream or zero executed declared tests all fail closed.

The custom reporter consumes documented structured `TestsStream` events and
emits one JSON receipt only after the stream drains. The receipt includes the
root plan, source paths, individual pass/fail/skip/todo outcomes, executed count,
failures and captured diagnostics. The parent validates the protocol/schema,
expected source identity, counts and outcomes as well as process status. An empty
file or early `exit(0)` produces a synthetic file wrapper at source location 1:1
with its name equal to its file; that wrapper is excluded from execution proof.
Suite containers and skip/todo-only files cannot supply proof either. A declared
test deliberately named exactly its absolute file path at 1:1 is conservatively
reserved as a wrapper and rejected, rather than risking a false green.

Node 20 does not expose the newer `test:summary` event, so this implementation
uses pass/fail/plan events available in both supported test runtimes. It does not
parse TAP strings or accept a stdout substring. Node's documentation explicitly
directs programmatic consumers to structured events instead of built-in reporter
text: [Node 20 custom reporters](https://nodejs.org/download/release/v20.20.1/docs/api/test.html#custom-reporters).

Both existing core child sites use this helper. Successful children print their
actual declared-test count; failures retain their structured evidence and exit
failure. The Energy result is collected before printing the final core summary.
PR #865's separate Thermal/combined-worker child sites must use the same helper
when the branches are composed; this branch does not silently modify that PR or
pull in its production worker patch.

## Regression evidence

The hermetic regression creates disposable local test fixtures and drivers. For
both direct Node and a parent launched using `node --test`, it verifies:

- A passing declared callback really writes an execution sentinel and supplies a
  positive structured executed count for the expected source file.
- An injected assertion failure really executes, writes the sentinel, appears
  in the receipt and propagates to a failing parent status.
- Empty, all-skipped, TODO-only, early-exiting and missing files are rejected,
  including a fake human-readable `ok` line in an empty fixture.
- A hanging child is bounded and cannot be treated as success.
- Caller environment is not mutated, legitimate values survive, and actual child
  source with positive execution counts appears in emitted V8 coverage files.
- Reporter receipt generation distinguishes source wrappers/suite containers,
  pass/fail/skip/todo, diagnostics and missing root-plan completion.

CI runs this regression directly and with `--test`, before the unchanged core
gate. The fixtures make no external request and run no production bootstrap,
provider, device or financial operation.

```bash
node tests/test_node_child_runner.js
node --test tests/test_node_child_runner.js
node --test --experimental-test-coverage \
  --test-coverage-include='**/tests/helpers/node-child-*.js' \
  tests/test_node_child_runner.js
node tests/test_app_js_core.js
node --test tests/test_app_js_core.js
git diff --check
```

Measured local results:

- RED before implementation: new runner regressions fail because the safe helper
  does not yet exist; the old core direct/CI discrepancy is separately preserved.
- GREEN: 17 runner regressions in each direct/`--test` mode on Node 20.18.0 and
  Node 22.22.0. These are four executions of the same tests, not 68 unique cases.
- Named helper coverage on Node 22: 100% lines/functions; runner 91.67% branches,
  reporter 100% branches, combined 95.65% branches. This is helper coverage, not
  repository-wide coverage or a claim about other test infrastructure.
- EXPECTED FAIL: current-master core in all four runtime/mode combinations now
  exposes the unchanged #863 Mini Service Worker regression. Energy's ten tests
  execute and pass; the failed core is not relabeled green. Production worker
  fixes and runner fixes must compose and pass normally before merge.

The first implementation's positive probes failed on a macOS canonical-path
alias mismatch (13/16 passing); those intermediate logs were retained and the
path comparison was corrected. Final syntax and whitespace checks pass. Local
regressions, source review and named coverage do not replace exact-head GitHub
CI, independent GitHub approval, merge or deployment gates.
