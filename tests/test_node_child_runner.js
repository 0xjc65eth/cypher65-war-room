/** Issue #867: execution proof, not a status-only child-suite smoke test. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const helper = new URL('./helpers/node-child-runner.js', import.meta.url);
const fixtures = {
  pass: `import test from 'node:test'; import assert from 'node:assert/strict'; import fs from 'node:fs';
    test('real execution', () => { fs.appendFileSync(process.env.CHILD_PROBE, 'ran\\n'); assert.equal(process.env.CHILD_LEGITIMATE, 'preserved'); });`,
  fail: `import test from 'node:test'; import assert from 'node:assert/strict'; import fs from 'node:fs';
    test('injected failure', () => { fs.appendFileSync(process.env.CHILD_PROBE, 'ran\\n'); assert.fail('injected-child-failure'); });`,
  empty: `console.log('ok 1 - this human text is NOT test execution proof');`,
  skipped: `import test from 'node:test'; test.skip('not executed', () => {});`,
  todo: `import test from 'node:test'; test.todo('not implemented');`,
  early: `process.exit(0);`,
  hang: `import test from 'node:test'; test('never finishes', () => new Promise(() => {})); setInterval(() => {}, 1000);`,
};

function fixture(t, name) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cypher65-child-runner-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const suite = path.join(dir, 'suite.mjs'), probe = path.join(dir, 'execution.txt');
  if (name !== 'missing') fs.writeFileSync(suite, fixtures[name]);
  return { dir, suite, probe };
}

for (const mode of ['direct', 'test']) {
  for (const name of ['pass', 'fail', 'empty', 'skipped', 'todo', 'early', 'missing']) {
    test(`${mode} parent executes/rejects ${name} child with structured proof`, t => {
      const { dir, suite, probe } = fixture(t, name);
      const output = path.join(dir, 'result.json'), driver = path.join(dir, 'driver.mjs');
      fs.writeFileSync(driver, `import fs from 'node:fs';
        import { runNodeTestFile } from ${JSON.stringify(helper.href)};
        const result = runNodeTestFile(${JSON.stringify(suite)}, { env: { ...process.env,
          NODE_TEST_CONTEXT: 'child-v8', CHILD_PROBE: ${JSON.stringify(probe)}, CHILD_LEGITIMATE: 'preserved' } });
        fs.writeFileSync(${JSON.stringify(output)}, JSON.stringify(result));
        process.exitCode = result.ok ? 0 : 1;`);
      const env = { ...process.env }; delete env.NODE_TEST_CONTEXT;
      const parent = spawnSync(process.execPath, [...(mode === 'test' ? ['--test'] : []), driver], { env, encoding: 'utf8', timeout: 15000 });
      assert.equal(parent.status, name === 'pass' ? 0 : 1, parent.stdout + parent.stderr);
      assert.equal(parent.error, undefined);
      const result = JSON.parse(fs.readFileSync(output, 'utf8'));
      assert.equal(result.ok, name === 'pass');
      assert.equal(fs.existsSync(probe), ['pass', 'fail'].includes(name));
      if (fs.existsSync(probe)) assert.equal(fs.readFileSync(probe, 'utf8'), 'ran\n');
      if (name === 'pass') {
        assert.equal(result.report.completed, true);
        assert.equal(result.report.executed, 1);
        assert.equal(result.report.failed, 0);
        assert.equal(result.report.tests[0].file, suite);
      }
      if (name === 'fail') {
        assert.equal(result.report.executed, 1);
        assert.equal(result.report.failed, 1);
        assert.equal(result.report.tests[0].error.message, 'injected-child-failure');
      }
    });
  }
}

test('coverage and legitimate environment survive while caller environment is untouched', async t => {
  const { runNodeTestFile } = await import(helper);
  const { dir, suite, probe } = fixture(t, 'pass');
  const coverage = path.join(dir, 'coverage');
  const env = { ...process.env, NODE_TEST_CONTEXT: 'child-v8', NODE_V8_COVERAGE: coverage,
    NODE_OPTIONS: '--no-warnings', CHILD_PROBE: probe, CHILD_LEGITIMATE: 'preserved' };
  const result = runNodeTestFile(suite, { env });
  assert.equal(result.ok, true, result.reason);
  assert.equal(env.NODE_TEST_CONTEXT, 'child-v8');
  assert.equal(env.NODE_V8_COVERAGE, coverage);
  const scripts = fs.readdirSync(coverage).flatMap(file => JSON.parse(fs.readFileSync(path.join(coverage, file), 'utf8')).result);
  const measured = scripts.find(script => script.url === new URL('file://' + suite).href);
  assert.ok(measured, 'actual child suite source must appear in V8 coverage');
  assert.ok(measured.functions.some(fn => fn.ranges.some(range => range.count > 0)));
});

test('bounded child timeout cannot be interpreted as a successful suite', async t => {
  const { runNodeTestFile } = await import(helper);
  const { suite } = fixture(t, 'hang');
  const result = runNodeTestFile(suite, { timeout: 300 });
  assert.equal(result.ok, false);
  assert.notEqual(result.status, 0);
  assert.match(result.reason, /timed out|ETIMEDOUT/);
});

test('reporter uses structured outcomes, rejects file wrappers and waits for root plan', async () => {
  const { default: reporter } = await import('./helpers/node-child-reporter.js');
  async function* events() {
    yield { type: 'test:start', data: {} };
    yield { type: 'test:plan', data: { nesting: 1, count: 2 } };
    yield { type: 'test:stdout', data: { message: 'fixture stdout' } };
    yield { type: 'test:stderr', data: { message: 'fixture stderr' } };
    yield { type: 'test:pass', data: { name: '/fixture.mjs', file: '/fixture.mjs', line: 1, column: 1 } };
    yield { type: 'test:pass', data: { name: 'empty suite', details: { type: 'suite' } } };
    yield { type: 'test:pass', data: { name: 'executed', file: '/fixture.mjs' } };
    yield { type: 'test:pass', data: { name: 'skipped', file: '/fixture.mjs', skip: 'fixture' } };
    yield { type: 'test:pass', data: { name: 'todo', file: '/fixture.mjs', todo: true } };
    yield { type: 'test:fail', data: { name: 'failed', file: '/fixture.mjs', details: { error: { message: 'fixture failure' } } } };
    yield { type: 'test:plan', data: { nesting: 0, count: 5 } };
  }
  const chunks = [];
  for await (const chunk of reporter(events())) chunks.push(chunk);
  assert.equal(chunks.length, 1);
  const result = JSON.parse(chunks[0]);
  assert.equal(result.completed, true); assert.equal(result.rootPlan, 5);
  assert.equal(result.tests.length, 4); assert.equal(result.executed, 2); assert.equal(result.failed, 1);
  assert.deepEqual(result.diagnostics, ['fixture stdout', 'fixture stderr']);
  async function* incomplete() { yield { type: 'test:start', data: {} }; }
  for await (const chunk of reporter(incomplete())) {
    assert.equal(JSON.parse(chunk).completed, false);
    assert.equal(JSON.parse(chunk).executed, 0);
  }
});
