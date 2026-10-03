#!/usr/bin/env node
'use strict';

/**
 * Verify the actual security gate rejects tampered package provenance.
 * Fixtures are disposable copies; the checkout and installed packages are not edited.
 * @example node --test scripts/check-braces-fix.test.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { test } = require('node:test');

const mobile = path.resolve(__dirname, '..');
const archive = 'vendor/braces-3.0.4-cypher65.1.tgz';
const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const writeJson = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');

function fixture(context) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'cypher65-braces-checker-test-'));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  fs.mkdirSync(path.join(directory, 'scripts'));
  fs.cpSync(path.join(mobile, 'vendor'), path.join(directory, 'vendor'), { recursive: true });
  for (const file of ['package.json', 'package-lock.json']) {
    fs.copyFileSync(path.join(mobile, file), path.join(directory, file));
  }
  fs.copyFileSync(path.join(__dirname, 'check-braces-fix.cjs'),
    path.join(directory, 'scripts/check-braces-fix.cjs'));
  const lock = readJson(path.join(directory, 'package-lock.json'));
  const entries = Object.keys(lock.packages).filter(key => /(?:^|\/)node_modules\/braces$/.test(key));
  assert.equal(entries.length, 1, 'self-test requires the single reviewed installed braces entry');
  const installed = path.join(directory, entries[0]);
  fs.mkdirSync(path.dirname(installed), { recursive: true });
  fs.cpSync(path.join(directory, 'vendor/braces'), installed, { recursive: true });
  return { directory, installed, lock, entry: entries[0] };
}

function runGate(directory) {
  const result = spawnSync(process.execPath, [path.join(directory, 'scripts/check-braces-fix.cjs')], {
    encoding: 'utf8', timeout: 60000, maxBuffer: 1024 * 1024,
    env: { ...process.env, NODE_PATH: path.join(mobile, 'node_modules') },
  });
  assert.equal(result.error, undefined, `security gate process error: ${result.error}`);
  assert.equal(result.signal, null, `security gate terminated by ${result.signal}`);
  return result;
}

test('copied valid source/archive/lock fixture passes the actual default gate', context => {
  const { directory } = fixture(context);
  const result = runGate(directory);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout, /lock\/tar\/runtime provenance passed/);
});

const cases = [
  ['floating override', target => {
    const file = path.join(target.directory, 'package.json');
    const metadata = readJson(file);
    metadata.overrides.braces = '*';
    writeJson(file, metadata);
  }, /override/],
  ['unpatched lock version', target => {
    target.lock.packages[target.entry].version = '3.0.3';
    writeJson(path.join(target.directory, 'package-lock.json'), target.lock);
  }, /lockfile.*version/],
  ['remote lock resolution', target => {
    target.lock.packages[target.entry].resolved = 'https://registry.npmjs.org/braces/-/braces-3.0.3.tgz';
    writeJson(path.join(target.directory, 'package-lock.json'), target.lock);
  }, /lockfile.*resolution/],
  ['archive byte tampering', target => {
    fs.appendFileSync(path.join(target.directory, archive), 'tampered');
  }, /integrity/],
  ['false official-release claim', target => {
    const file = path.join(target.installed, 'package.json');
    const metadata = readJson(file);
    metadata.cypher65SecurityPatch.officialRelease = true;
    writeJson(file, metadata);
  }, /official upstream release/],
  ['false baseline identity', target => {
    const file = path.join(target.installed, 'package.json');
    const metadata = readJson(file);
    metadata.cypher65SecurityPatch.upstreamCommit = '0'.repeat(40);
    writeJson(file, metadata);
  }, /baseline SHA/],
  ['changed runtime code', target => {
    fs.appendFileSync(path.join(target.installed, 'lib/parse.js'), '\n// tampered\n');
  }, /differs from vendored source/],
  ['missing license', target => {
    fs.unlinkSync(path.join(target.installed, 'LICENSE'));
  }, /file list/],
  ['additional installed file', target => {
    fs.writeFileSync(path.join(target.installed, 'unexpected.js'), 'module.exports = {};\n');
  }, /file list/],
];

for (const [name, mutate, expected] of cases) {
  test(`actual default gate rejects ${name}`, context => {
    const target = fixture(context);
    mutate(target);
    const result = runGate(target.directory);
    assert.equal(result.status, 1, `tampered fixture unexpectedly accepted: ${result.stdout}`);
    assert.match(result.stderr, expected);
  });
}
