#!/usr/bin/env node
'use strict';

/**
 * Regression gate for the locally vendored braces nesting-depth mitigation.
 *
 * Examples:
 *   node scripts/check-braces-fix.cjs
 *   node scripts/check-braces-fix.cjs --package /absolute/path/to/braces
 *   node scripts/check-braces-fix.cjs --expect-vulnerable-baseline --package /absolute/path/to/braces-3.0.3
 *   node scripts/check-braces-fix.cjs --package /absolute/path/to/braces --baseline-package /absolute/path/to/braces-3.0.3
 *
 * Hostile-depth and cyclic-AST cases run in disposable, memory-limited child
 * processes with a timeout. The script never accesses the network.
 */

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const MOBILE_ROOT = path.resolve(__dirname, '..');
const VENDOR_ROOT = path.join(MOBILE_ROOT, 'vendor/braces');
const TARBALL_RELATIVE = 'vendor/braces-3.0.4-cypher65.1.tgz';
const TARBALL_OVERRIDE = '$braces';
const EXPECTED_VERSION = '3.0.4-cypher65.1';
const EXPECTED_BASELINE_SHA = '74b2db2938fad48a2ea54a9c8bf27a37a62c350d';
const CHILD_TIMEOUT_MS = 4000;
const CHILD_MEMORY_MB = 128;
const DEPTH_REJECTION = /(?:nest(?:ing)?|depth).*(?:limit|maximum|exceed|too deep|too many)|(?:limit|maximum).*(?:nest(?:ing)?|depth)/i;

function argumentValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return undefined;
  assert.ok(process.argv[index + 1], `${name} requires a value`);
  return process.argv[index + 1];
}

function packageDirectory() {
  const supplied = argumentValue('--package');
  if (supplied === undefined) return undefined;
  assert.ok(path.isAbsolute(supplied), '--package must be an absolute package directory');
  return path.resolve(supplied);
}

function packageMetadata(directory) {
  return JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
}

function verifyInternalPatchMetadata(metadata, label) {
  assert.equal(metadata.name, 'braces', `${label} must retain the real package name`);
  assert.equal(metadata.version, EXPECTED_VERSION,
    `${label} must identify the internal CYPHER65 build`);
  assert.equal(metadata.license, 'MIT', `${label} must preserve MIT metadata`);
  assert.equal(metadata.cypher65SecurityPatch?.upstreamCommit, EXPECTED_BASELINE_SHA,
    `${label} must identify the exact upstream baseline SHA`);
  assert.equal(metadata.cypher65SecurityPatch?.upstreamVersion, '3.0.3');
  assert.equal(metadata.cypher65SecurityPatch?.advisory, 'GHSA-vfj7-8cjw-p6xm');
  assert.equal(metadata.cypher65SecurityPatch?.officialRelease, false,
    `${label} must not represent the internal mitigation as an official upstream release`);
}

function walkFiles(directory, prefix = '') {
  const results = [];
  for (const entry of fs.readdirSync(path.join(directory, prefix), { withFileTypes: true })) {
    const relative = path.posix.join(prefix, entry.name);
    if (entry.isDirectory()) results.push(...walkFiles(directory, relative));
    else if (entry.isFile()) results.push(relative);
    else assert.fail(`Unexpected non-file entry in package tree: ${relative}`);
  }
  return results.sort();
}

function assertTreesByteIdentical(expectedDirectory, installedDirectory) {
  const expectedFiles = walkFiles(expectedDirectory);
  const installedFiles = walkFiles(installedDirectory);
  assert.deepEqual(installedFiles, expectedFiles,
    'installed braces runtime file list must exactly match the vendored source tree');
  for (const relative of expectedFiles) {
    const expected = fs.readFileSync(path.join(expectedDirectory, relative));
    const installed = fs.readFileSync(path.join(installedDirectory, relative));
    assert.ok(expected.equals(installed),
      `installed braces file differs from vendored source: ${relative}`);
  }
}

function verifyDefaultInstallation() {
  const manifest = JSON.parse(fs.readFileSync(path.join(MOBILE_ROOT, 'package.json'), 'utf8'));
  const lock = JSON.parse(fs.readFileSync(path.join(MOBILE_ROOT, 'package-lock.json'), 'utf8'));
  const tarballPath = path.join(MOBILE_ROOT, TARBALL_RELATIVE);
  const braceEntries = Object.entries(lock.packages || {})
    .filter(([packagePath]) => /(?:^|\/)node_modules\/braces$/.test(packagePath));

  assert.equal(manifest.overrides?.braces, TARBALL_OVERRIDE,
    'root package.json must retain the override reference to its direct braces dependency');
  assert.equal(manifest.devDependencies?.braces, `file:${TARBALL_RELATIVE}`,
    'mobile must pin the reviewed tarball as an explicit development security-test dependency');
  assert.ok(fs.existsSync(tarballPath), `vendored braces tarball is missing: ${TARBALL_RELATIVE}`);
  assert.ok(braceEntries.length > 0, 'package-lock.json must contain at least one braces package');

  const actualIntegrity = `sha512-${crypto.createHash('sha512')
    .update(fs.readFileSync(tarballPath)).digest('base64')}`;
  for (const [packagePath, entry] of braceEntries) {
    assert.equal(entry.version, EXPECTED_VERSION,
      `lockfile ${packagePath} braces version must be the internal CYPHER65 build, not a vulnerable registry release`);
    assert.equal(entry.resolved, `file:${TARBALL_RELATIVE}`,
      `lockfile ${packagePath} braces resolution must point to the reviewed root-relative local tarball`);
    assert.equal(entry.integrity, actualIntegrity,
      `${packagePath} SHA-512 integrity must match the exact vendored tarball bytes`);
  }

  const vendorMetadata = packageMetadata(VENDOR_ROOT);
  verifyInternalPatchMetadata(vendorMetadata, 'vendored package metadata');
  assert.ok(fs.existsSync(path.join(VENDOR_ROOT, 'LICENSE')),
    'vendored source must retain the upstream MIT license text');
  for (const [packagePath] of braceEntries) {
    const installedDirectory = path.join(MOBILE_ROOT, packagePath);
    const installedMetadata = packageMetadata(installedDirectory);
    verifyInternalPatchMetadata(installedMetadata, `installed ${packagePath} metadata`);
    assertTreesByteIdentical(VENDOR_ROOT, installedDirectory);
  }
}

function makePattern(depth, open = '{', close = '}') {
  return `${open.repeat(depth)}a,b${close.repeat(depth)}`;
}

function makeAlternatingPattern(depth) {
  const opens = Array.from({ length: depth }, (_, index) => index % 2 ? '(' : '{').join('');
  const closes = Array.from({ length: depth }, (_, index) => index)
    .reverse().map(index => index % 2 ? ')' : '}').join('');
  return `${opens}a,b${closes}`;
}

function makeDeepAst(depth) {
  const root = { type: 'root', nodes: [] };
  let parent = root;
  for (let index = 0; index < depth; index += 1) {
    const child = {
      type: 'brace', open: true, close: true, commas: 1, ranges: 0, nodes: [], parent,
    };
    parent.nodes.push(child);
    parent = child;
  }
  parent.nodes.push({ type: 'text', value: 'x', parent });
  return root;
}

function makeCyclicAst() {
  const root = { type: 'root', nodes: [] };
  const child = { type: 'brace', open: true, close: true, commas: 1, ranges: 0, nodes: [], parent: root };
  root.nodes.push(child);
  child.nodes.push(root);
  return root;
}

function workerAction(braces, action) {
  const options = action.limitCase === undefined
    ? (action.options || {})
    : { maxDepth: parseLimitCase(action.limitCase) };
  let input = action.pattern;
  if (action.ast === 'deep') input = makeDeepAst(action.depth);
  if (action.ast === 'cycle') input = makeCyclicAst();
  if (action.parseFirst === true) input = braces.parse(input, options);

  switch (action.operation) {
    case 'parse': return braces.parse(input, options);
    case 'compile': return braces.compile(input, options);
    case 'expand': return braces.expand(input, options);
    case 'stringify': return braces.stringify(input, options);
    default: throw new Error(`Unknown worker operation: ${action.operation}`);
  }
}

function parseLimitCase(value) {
  if (value === 'NaN') return Number.NaN;
  if (value === 'Infinity') return Number.POSITIVE_INFINITY;
  if (value === '-Infinity') return Number.NEGATIVE_INFINITY;
  if (value === 'string') return '1';
  return Number(value);
}

function runWorker(action, directory) {
  const encoded = Buffer.from(JSON.stringify({ action, directory })).toString('base64');
  const result = spawnSync(process.execPath, [
    `--max-old-space-size=${CHILD_MEMORY_MB}`,
    __filename,
    '--worker', encoded,
  ], {
    encoding: 'utf8',
    timeout: CHILD_TIMEOUT_MS,
    maxBuffer: 1024 * 1024,
    windowsHide: true,
  });

  assert.notEqual(result.error?.code, 'ETIMEDOUT',
    `child process did not complete within ${CHILD_TIMEOUT_MS}ms`);
  assert.equal(result.signal, null, `child process terminated by signal ${result.signal}`);
  assert.equal(result.status, 0,
    `child process exited ${result.status}: ${(result.stderr || result.stdout || '').trim()}`);
  const lines = result.stdout.trim().split(/\r?\n/);
  assert.equal(lines.length, 1, `child must emit one JSON result, got: ${result.stdout}`);
  return JSON.parse(lines[0]);
}

function loadWorkerPackage(directory) {
  return require(directory);
}

function runWorkerMode(encoded) {
  const { action, directory } = JSON.parse(Buffer.from(encoded, 'base64').toString('utf8'));
  const braces = loadWorkerPackage(directory);
  try {
    const value = workerAction(braces, action);
    const safeValue = action.operation === 'parse'
      ? { type: value.type, input: value.input }
      : value;
    process.stdout.write(`${JSON.stringify({ ok: true, value: safeValue })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({
      ok: false,
      errorName: error?.name || 'Error',
      errorMessage: String(error?.message || error),
    })}\n`);
  }
}

function assertControlledDepthRejection(result, label, expectedName = 'SyntaxError') {
  assert.equal(result.ok, false, `${label} must reject over-limit nesting`);
  assert.equal(result.errorName, expectedName,
    `${label} must reject with ${expectedName}, got ${result.errorName}: ${result.errorMessage}`);
  assert.notEqual(result.errorMessage, 'Maximum call stack size exceeded',
    `${label} must not rely on JavaScript stack exhaustion`);
  assert.ok(DEPTH_REJECTION.test(result.errorMessage),
    `${label} must return a controlled nesting/depth error, got ${result.errorName}: ${result.errorMessage}`);
}

function assertControlledCycleRejection(result, label) {
  assert.equal(result.ok, false, `${label} must reject a cyclic AST`);
  assert.equal(result.errorName, 'RangeError',
    `${label} must reject with RangeError, got ${result.errorName}: ${result.errorMessage}`);
  assert.notEqual(result.errorMessage, 'Maximum call stack size exceeded',
    `${label} must not rely on JavaScript stack exhaustion`);
  assert.ok(DEPTH_REJECTION.test(result.errorMessage) || /cycl(?:e|ic)/i.test(result.errorMessage),
    `${label} must return a controlled cycle/depth error, got ${result.errorName}: ${result.errorMessage}`);
}

function assertPass(result, label) {
  assert.equal(result.ok, true,
    `${label} unexpectedly failed: ${result.errorName || ''} ${result.errorMessage || ''}`);
}

function runDepthRegression(directory) {
  const operations = ['parse', 'compile', 'expand', 'stringify'];
  const depth100 = makePattern(100);
  for (const operation of operations) {
    assertPass(runWorker({ operation, pattern: depth100 }, directory), `${operation} depth 100`);
    assertPass(runWorker({ operation, pattern: makePattern(100, '(', ')') }, directory),
      `${operation} parenthesis depth 100`);
  }

  for (const operation of operations) {
    assertControlledDepthRejection(
      runWorker({ operation, pattern: makePattern(101) }, directory),
      `${operation} depth 101`
    );
    assertControlledDepthRejection(
      runWorker({ operation, pattern: makePattern(101, '(', ')') }, directory),
      `${operation} parenthesis depth 101`
    );
  }
  for (const depth of [1000, 4000]) {
    assertControlledDepthRejection(
      runWorker({ operation: 'compile', pattern: makePattern(depth) }, directory),
      `compile depth ${depth}`
    );
  }
  assertControlledDepthRejection(
    runWorker({ operation: 'parse', pattern: makeAlternatingPattern(101) }, directory),
    'parse mixed brace/parenthesis depth 101'
  );
}

function runLimitRegression(directory) {
  for (const limitCase of ['1', '1.5']) {
    assertPass(runWorker({ operation: 'parse', pattern: makePattern(1), limitCase }, directory),
      `maxDepth ${limitCase} at depth 1`);
    assertControlledDepthRejection(
      runWorker({ operation: 'parse', pattern: makePattern(2), limitCase }, directory),
      `maxDepth ${limitCase} at depth 2`
    );
  }
  for (const limitCase of ['0', '-1']) {
    assertPass(runWorker({ operation: 'parse', pattern: 'plain', limitCase }, directory),
      `maxDepth ${limitCase} at depth 0`);
    assertControlledDepthRejection(
      runWorker({ operation: 'parse', pattern: makePattern(1), limitCase }, directory),
      `maxDepth ${limitCase} at depth 1`
    );
  }
  for (const limitCase of ['NaN', 'Infinity', '-Infinity', 'string']) {
    assertPass(runWorker({ operation: 'parse', pattern: makePattern(100), limitCase }, directory),
      `fallback maxDepth ${limitCase} at depth 100`);
    assertControlledDepthRejection(
      runWorker({ operation: 'parse', pattern: makePattern(101), limitCase }, directory),
      `fallback maxDepth ${limitCase} at depth 101`
    );
  }

  for (const operation of ['compile', 'expand', 'stringify']) {
    for (const limitCase of ['1', '1.5']) {
      assertPass(runWorker({ operation, ast: 'deep', depth: 1, limitCase }, directory),
        `${operation} walker maxDepth ${limitCase} direct AST depth 1`);
      assertControlledDepthRejection(
        runWorker({ operation, ast: 'deep', depth: 2, limitCase }, directory),
        `${operation} walker maxDepth ${limitCase} direct AST depth 2`,
        'RangeError'
      );
    }
    for (const limitCase of ['0', '-1']) {
      assertPass(runWorker({ operation, ast: 'deep', depth: 0, limitCase }, directory),
        `${operation} walker maxDepth ${limitCase} direct AST depth 0`);
      assertControlledDepthRejection(
        runWorker({ operation, ast: 'deep', depth: 1, limitCase }, directory),
        `${operation} walker maxDepth ${limitCase} direct AST depth 1`,
        'RangeError'
      );
    }
  }
}

function runAstRegression(directory) {
  for (const operation of ['compile', 'expand', 'stringify']) {
    assertPass(runWorker({ operation, ast: 'deep', depth: 100 }, directory),
      `${operation} direct AST depth 100`);
    assertControlledDepthRejection(
      runWorker({ operation, ast: 'deep', depth: 101 }, directory),
      `${operation} direct AST depth 101`,
      'RangeError'
    );
    assertControlledCycleRejection(
      runWorker({ operation, ast: 'cycle' }, directory),
      `${operation} cyclic direct AST`
    );
  }
}

function runShallowContract(braces) {
  assert.deepEqual(braces('{a,b}'), ['(a|b)']);
  assert.deepEqual(braces('{a,b}', { expand: true }), ['a', 'b']);
  assert.deepEqual(braces('x{a,b}y', { expand: true }), ['xay', 'xby']);
  assert.deepEqual(braces('{1..3}'), ['([1-3])']);
  assert.deepEqual(braces('{a,{b,c}}', { expand: true }), ['a', 'b', 'c']);
  assert.deepEqual(braces('"{a,b}"'), ['{a,b}']);
  assert.deepEqual(braces("'{a,b}'"), ['{a,b}']);
  assert.deepEqual(braces('\\{a,b\\}'), ['{a,b}']);
  assert.deepEqual(braces('a{b,c', { escapeInvalid: true }), ['a\\{b,c']);
  assert.deepEqual(braces('{a,,b}', { expand: true }), ['a', '', 'b']);
  assert.deepEqual(braces('{a..c}', { expand: true }), ['a', 'b', 'c']);
  assert.equal(braces.stringify(braces.parse('"{a,b}"', { keepQuotes: true })), '"{a,b}"');
}

function runBaselineComparison(candidateDirectory, baselineDirectory) {
  assert.ok(path.isAbsolute(baselineDirectory), '--baseline-package must be absolute');
  const candidate = require(candidateDirectory);
  const baseline = require(baselineDirectory);
  const corpus = [
    '{}', '{a,b}', 'x{a,b}y', '{1..3}', '{01..03}', '{a,{b,c}}',
    'a{b,c}{d,e}', '"{a,b}"', "'{a,b}'", '\\{a,b\\}',
    'a{b,c', 'a}', '{a,,b}', '{a..c}', 'foo', 'x(y|z)',
  ];
  for (const pattern of corpus) {
    for (const options of [{}, { expand: true }, { escapeInvalid: true }]) {
      assert.deepEqual(candidate(pattern, options), baseline(pattern, options),
        `shallow package behavior changed for ${JSON.stringify(pattern)} ${JSON.stringify(options)}`);
    }
    assert.deepEqual(candidate.parse(pattern), baseline.parse(pattern),
      `shallow parser AST changed for ${JSON.stringify(pattern)}`);
    assert.equal(candidate.stringify(candidate.parse(pattern, { keepQuotes: true })),
      baseline.stringify(baseline.parse(pattern, { keepQuotes: true })),
      `shallow stringify behavior changed for ${JSON.stringify(pattern)}`);
    assert.deepEqual(candidate.compile(candidate.parse(pattern, { keepQuotes: true }), { escapeInvalid: true }),
      baseline.compile(baseline.parse(pattern, { keepQuotes: true }), { escapeInvalid: true }),
      `shallow escapeInvalid compile changed for ${JSON.stringify(pattern)}`);
  }
}

function reproduceVulnerableCompile(directory) {
  const result = runWorker({ operation: 'compile', pattern: makePattern(4000) }, directory);
  assert.equal(result.ok, false, 'official vulnerable baseline must fail during deep compile');
  assert.equal(result.errorName, 'RangeError',
    `expected baseline compiler stack exhaustion, got ${result.errorName}: ${result.errorMessage}`);
  assert.equal(result.errorMessage, 'Maximum call stack size exceeded',
    `expected the known compiler stack exhaustion, got: ${result.errorMessage}`);
}

function verifyBaselineSourceCommit(directory) {
  const commit = spawnSync('git', ['-C', directory, 'rev-parse', 'HEAD'], {
    encoding: 'utf8', timeout: 2000, maxBuffer: 4096, windowsHide: true,
  });
  assert.ifError(commit.error);
  assert.equal(commit.status, 0, `could not read official braces baseline commit: ${commit.stderr}`);
  assert.equal(commit.stdout.trim(), EXPECTED_BASELINE_SHA,
    'vulnerable baseline must be the recorded official upstream source commit');

  const status = spawnSync('git', ['-C', directory, 'status', '--porcelain'], {
    encoding: 'utf8', timeout: 2000, maxBuffer: 4096, windowsHide: true,
  });
  assert.ifError(status.error);
  assert.equal(status.status, 0, `could not verify clean baseline source: ${status.stderr}`);
  assert.equal(status.stdout, '', 'vulnerable baseline source tree must be clean');
}

function main() {
  const suppliedDirectory = packageDirectory();
  const baselineMode = process.argv.includes('--expect-vulnerable-baseline');
  const codeOnly = suppliedDirectory !== undefined;
  const directory = suppliedDirectory || path.join(MOBILE_ROOT, 'node_modules/braces');

  assert.ok(fs.existsSync(path.join(directory, 'package.json')),
    `braces package directory is missing: ${directory}`);
  const metadata = packageMetadata(directory);
  assert.equal(metadata.name, 'braces', 'the package must not be renamed or aliased');

  if (baselineMode) {
    assert.ok(codeOnly, '--expect-vulnerable-baseline requires --package with the official baseline');
    assert.equal(metadata.version, '3.0.3', 'vulnerable baseline must be official braces 3.0.3');
    verifyBaselineSourceCommit(directory);
    reproduceVulnerableCompile(directory);
    console.log('Confirmed official braces 3.0.3 reproduces compile stack exhaustion at nesting depth 4000.');
    return;
  }

  if (!codeOnly) verifyDefaultInstallation();
  else {
    verifyInternalPatchMetadata(metadata, '--package metadata');
    assert.ok(fs.existsSync(path.join(directory, 'LICENSE')),
      'vendored package must retain its MIT license file');
  }

  runShallowContract(require(directory));
  runDepthRegression(directory);
  runLimitRegression(directory);
  runAstRegression(directory);

  const baselineDirectory = argumentValue('--baseline-package');
  if (baselineDirectory !== undefined) runBaselineComparison(directory, baselineDirectory);

  console.log(`Verified braces ${metadata.version}: lock/tar/runtime provenance ${codeOnly ? 'not requested (code-only mode)' : 'passed'}; shallow compatibility and depth/AST regressions passed.`);
}

const workerIndex = process.argv.indexOf('--worker');
if (workerIndex !== -1) {
  runWorkerMode(process.argv[workerIndex + 1]);
} else {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message || error);
    process.exitCode = 1;
  }
}
