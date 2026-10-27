import { spawnSync } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const reporter = fileURLToPath(new URL('./node-child-reporter.js', import.meta.url));

/**
 * Run a nonempty node:test file in an isolated, awaited child.
 * Preserve coverage/options and all legitimate environment; never inherit Node's
 * internal recursive-runner context. Success requires structured execution proof.
 * @param {string} suite Absolute or relative test-file path.
 * @param {{env?: NodeJS.ProcessEnv, timeout?: number}} [options] Child environment and wall-time cap.
 * @returns {{ok: boolean, status: number|null, reason: string, report: object|null, stdout: string, stderr: string}}
 * @example runNodeTestFile('tests/test_energy_advisor_js.js').ok
 */
export function runNodeTestFile(suite, { env = process.env, timeout = 30000 } = {}) {
  let file = path.resolve(suite);
  // Node reports canonical source paths; accept aliases without trusting another file.
  try { file = fs.realpathSync(file); } catch { /* Missing files fail in the child. */ }
  const childEnv = { ...env };
  delete childEnv.NODE_TEST_CONTEXT;
  const child = spawnSync(process.execPath, ['--test', '--test-reporter=' + reporter, file], {
    env: childEnv, encoding: 'utf8', timeout, maxBuffer: 4 * 1024 * 1024,
  });
  let report = null, reason = '';
  try {
    report = JSON.parse(child.stdout || '');
    const valid = report?.protocol === 'cypher65-node-child-v1' && report.completed === true &&
      Number.isSafeInteger(report.rootPlan) && report.rootPlan > 0 && Array.isArray(report.tests) &&
      Array.isArray(report.failures) && Array.isArray(report.diagnostics) &&
      Number.isSafeInteger(report.failed) && report.failed === report.failures.length &&
      report.tests.every(test => test.file === file && typeof test.name === 'string' &&
        ['pass', 'fail'].includes(test.outcome) && typeof test.skipped === 'boolean' && typeof test.todo === 'boolean') &&
      report.executed === report.tests.filter(test => !test.skipped && !test.todo).length;
    if (!valid) reason = 'invalid or incomplete child execution receipt';
    else if (report.executed === 0) reason = 'child executed no declared tests';
    else if (report.failed || report.tests.some(test => test.outcome === 'fail')) reason = 'child reported failing tests';
  } catch {
    reason = 'missing or malformed child execution receipt';
  }
  if (child.error) reason = 'child execution error: ' + child.error.message;
  else if (child.signal) reason = 'child terminated by signal: ' + child.signal;
  else if (child.status !== 0) reason ||= 'child exited with status ' + child.status;
  return { ok: !reason && child.status === 0, status: child.status, reason, report,
    stdout: child.stdout || '', stderr: child.stderr || '' };
}
