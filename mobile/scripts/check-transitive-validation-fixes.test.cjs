#!/usr/bin/env node
'use strict';

/** Exercise actual installed validation/URI libraries with bounded fixtures only.
 * No network, credentials, OOM attempt, global override or Zod-v3 patch claim.
 * @example node --max-old-space-size=128 --test scripts/check-transitive-validation-fixes.test.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { test } = require('node:test');
const root = path.resolve(__dirname, '..');
const libraryRoot = process.env.CYPHER65_SECURITY_PACKAGE_ROOT || root;
const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8'));
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const semver = require(path.join(libraryRoot, 'node_modules/semver'));
const cap = 2;
const size = 256; // Intentionally small: observable visits/issues, not memory exhaustion.
const fixedZod = '4.6.7';
const fixedZodIntegrity = 'sha512-g8W2D2kU6a8untc053fX1uVBKzM7yqAxW/3zwk83+6RyF2+SKOuV+c0wBDhUwzV1PaGapmZH+rmcUzPf+3CGwg==';
const fixedURI = '3.1.9';
const fixedURIIntegrity = 'sha512-hS/0Wt3Ya043oKXs0sIxrMpKQITXhMLIrVAKKXi4gozGC9v7YRWVnXIZzjNPTO02M9BdxLCWqK1yRXgNziVyJQ==';

test('only compatible patched nodes are pinned, while Expo and v3 contracts remain intact', () => {
  const cli = lock.packages['node_modules/@expo/cli'];
  const v3 = lock.packages['node_modules/zod'];
  assert.equal(cli.version, '57.0.32');
  assert.equal(cli.dependencies.zod, '^3.25.76');
  assert.equal(semver.major(v3.version), 3);
  assert.ok(semver.satisfies(v3.version, cli.dependencies.zod));
  assert.equal(require(path.join(libraryRoot, 'node_modules/zod/package.json')).version, v3.version);
  assert.equal(lock.packages['node_modules/expo'].version, '57.0.31');
  assert.equal(manifest.devDependencies['@stryker-mutator/core'], '9.6.1');
  assert.equal(manifest.devDependencies['@stryker-mutator/jest-runner'], '9.6.1');
  assert.equal(manifest.overrides.zod, undefined);
  assert.equal(manifest.overrides['fast-uri'], undefined);
  for (const consumer of ['knip', 'mutation-server-protocol']) {
    const entry = lock.packages[`node_modules/${consumer}/node_modules/zod`];
    assert.equal(entry.version, fixedZod);
    assert.ok(semver.satisfies(entry.version, lock.packages[`node_modules/${consumer}`].dependencies.zod));
    assert.equal(entry.resolved, `https://registry.npmjs.org/zod/-/zod-${fixedZod}.tgz`);
    assert.equal(entry.integrity, fixedZodIntegrity);
    assert.equal(require(path.join(libraryRoot, `node_modules/${consumer}/node_modules/zod/package.json`)).version, entry.version);
  }
  const uri = lock.packages['node_modules/fast-uri'];
  assert.equal(uri.version, fixedURI);
  assert.ok(semver.satisfies(uri.version, lock.packages['node_modules/ajv'].dependencies['fast-uri']));
  assert.equal(uri.resolved, `https://registry.npmjs.org/fast-uri/-/fast-uri-${fixedURI}.tgz`);
  assert.equal(uri.integrity, fixedURIIntegrity);
  assert.equal(require(path.join(libraryRoot, 'node_modules/fast-uri/package.json')).version, uri.version);
});

test('the actual Expo CLI v3 plugin schemas retain supported good/bad contracts', () => {
  const schemas = require(path.join(libraryRoot, 'node_modules/@expo/cli/build/src/start/server/DevToolsPlugin.schema.js'));
  assert.equal(schemas.PluginSchema.safeParse({ packageName: 'synthetic-plugin', packageRoot: '/synthetic' }).success, true);
  assert.equal(schemas.PluginSchema.safeParse({ packageName: '', packageRoot: '/synthetic' }).success, false);
  assert.equal(schemas.DevToolsPluginOutputSchema.safeParse([{ type: 'text', text: 'synthetic output', level: 'info' }]).success, true);
  assert.equal(schemas.DevToolsPluginOutputSchema.safeParse([{ type: 'unknown' }]).success, false);
});

for (const consumer of ['knip', 'mutation-server-protocol']) {
  // Intentionally exercise the locked transitive node, not a new direct dependency.
  const { z } = require(path.join(libraryRoot, 'node_modules', consumer, 'node_modules/zod'));

  for (const kind of ['array', 'set', 'map']) {
    test(`${consumer}: oversized constrained ${kind} rejects before element visits/issues`, () => {
      let visits = 0;
      const element = z.string().superRefine((_value, context) => {
        visits++;
        context.addIssue({ code: 'custom', message: 'bounded synthetic rejection' });
      });
      const schema = kind === 'array' ? z.array(element).max(cap) :
        kind === 'set' ? z.set(element).max(cap) : z.map(element, element).max(cap);
      const values = Array.from({ length: size }, (_, index) => 'fixture-' + index);
      const input = kind === 'array' ? values : kind === 'set' ? new Set(values) : new Map(values.map(value => [value, value]));
      const result = schema.safeParse(input);
      assert.equal(result.success, false);
      assert.equal(visits, 0);
      assert.equal(result.error.issues.length, 1);
      assert.equal(result.error.issues[0].code, 'too_big');
    });
  }

  test(`${consumer}: async upper-bound rejection also avoids element callbacks`, async () => {
    let visits = 0;
    const schema = z.array(z.string().superRefine(async (_value, context) => {
      visits++; context.addIssue({ code: 'custom', message: 'bounded async fixture' });
    })).max(cap);
    const result = await schema.safeParseAsync(Array(size).fill('fixture'));
    assert.equal(result.success, false); assert.equal(visits, 0); assert.equal(result.error.issues.length, 1);
  });

  test(`${consumer}: valid and ordinary-invalid array/set/map contracts remain supported`, () => {
    assert.deepEqual(z.array(z.string()).max(cap).parse(['ok']), ['ok']);
    assert.deepEqual([...z.set(z.string()).max(cap).parse(new Set(['ok']))], ['ok']);
    assert.deepEqual([...z.map(z.string(), z.string()).max(cap).parse(new Map([['a', 'ok']]))], [['a', 'ok']]);
    assert.equal(z.array(z.string()).max(cap).safeParse([1]).success, false);
  });
}

test('the actual mutation protocol still accepts valid structures and rejects malformed data', async () => {
  const entry = path.join(libraryRoot, 'node_modules/mutation-server-protocol/dist/schema.js');
  const protocol = await import(pathToFileURL(entry).href);
  assert.equal(protocol.ConfigureParams.safeParse({ configFilePath: '/synthetic/config' }).success, true);
  assert.equal(protocol.DiscoverParams.safeParse({ files: [{ path: '/synthetic/source.ts' }] }).success, true);
  assert.equal(protocol.DiscoverParams.safeParse({ files: [{ path: 42 }] }).success, false);
  assert.equal(protocol.ConfigureResult.safeParse({ version: '1' }).success, true);
  assert.equal(protocol.ConfigureResult.safeParse({ version: 1 }).success, false);
});

const uri = require(path.join(libraryRoot, 'node_modules/fast-uri'));
test('fast-uri rejects encoded schemes without turning them into active schemes', () => {
  for (const input of ['%6Aavascript:fixture', '%u006Aavascript:fixture']) {
    assert.ok(uri.parse(input).error);
    assert.equal(uri.normalize(input), input);
    assert.equal(uri.equal(input, 'javascript:fixture'), false);
  }
});
test('fast-uri rejects ambiguous delimiters and stripped control characters in hosts', () => {
  for (const input of ['http://a@b@evil.invalid/', 'http://ex\tample.invalid/', 'http://ex\nample.invalid/']) {
    assert.ok(uri.parse(input).error);
  }
});
test('fast-uri relative normalization preserves resource resolution and suffixes cannot inject schemes', () => {
  for (const relative of ['a/../b', '../x']) {
    assert.equal(uri.resolve('https://fixture.invalid/a/', uri.normalize(relative)), uri.resolve('https://fixture.invalid/a/', relative));
  }
  assert.equal(uri.serialize({ path: 'javascript:fixture' }, { reference: 'suffix' }), 'javascript%3Afixture');
  assert.equal(uri.parse('https://fixture.invalid/path').error, undefined);
  assert.equal(uri.equal('https://fixture.invalid/a', 'https://fixture.invalid/a'), true);
});
