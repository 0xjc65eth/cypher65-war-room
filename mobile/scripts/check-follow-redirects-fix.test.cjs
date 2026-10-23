#!/usr/bin/env node
'use strict';

/**
 * Exercise the installed redirect state machine with in-memory native protocols.
 * No sockets, DNS, credentials, or external services are used.
 * @example node --test scripts/check-follow-redirects-fix.test.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { test } = require('node:test');
const redirects = require('follow-redirects');

const root = path.resolve(__dirname, '..');
const fixedVersion = '1.16.1';
const fixedResolution = `https://registry.npmjs.org/follow-redirects/-/follow-redirects-${fixedVersion}.tgz`;
const fixedIntegrity = 'sha512-FNvFGzoMLWmE6Yj9spb/zjd7yiNCHiAW9/Tg9CXrQ8wuu32HtlJOwWO11OJafl5FfY3DxTdQ0vj42zU1kvv5jg==';

function wireHeaders(headers) {
  const entries = Array.isArray(headers)
    ? Array.from({ length: headers.length / 2 }, (_, index) => headers.slice(index * 2, index * 2 + 2))
    : Object.entries(headers);
  return Object.fromEntries(entries.map(([name, value]) => [name.toLowerCase(), value]));
}

/**
 * Run the real library with a deterministic, socket-free HTTP(S) transport.
 * The first fixture response redirects; the second completes successfully.
 * @example await followFixture({ headers: { 'X-Public': 'fixture' } });
 */
function followFixture({
  headers,
  sensitiveHeaders = [],
  origin = 'http://origin.invalid/start',
  location = 'http://destination.invalid/finish',
  method = 'GET',
  redirectCode = 302,
}) {
  const requests = [];
  const native = {
    request(options, onResponse) {
      const request = new EventEmitter();
      const entry = {
        protocol: options.protocol,
        host: options.hostname,
        method: options.method || 'GET',
        headers: wireHeaders(options.headers),
      };
      requests.push(entry);
      const first = requests.length === 1;
      request.destroy = () => { request.destroyed = true; return request; };
      request.getHeader = name => entry.headers[name.toLowerCase()];
      request.write = (_data, _encoding, callback) => {
        if (typeof _encoding === 'function') _encoding();
        else if (callback) callback();
        return true;
      };
      request.end = (_data, _encoding, callback) => {
        queueMicrotask(() => {
          const response = new EventEmitter();
          response.statusCode = first ? redirectCode : 200;
          response.headers = first ? { location } : {};
          response.req = request;
          response.destroy = () => { response.destroyed = true; };
          onResponse(response);
          if (typeof _data === 'function') _data();
          else if (typeof _encoding === 'function') _encoding();
          else if (callback) callback();
        });
        return request;
      };
      return request;
    },
  };
  const wrapped = redirects.wrap({ http: native, https: native });
  const scheme = new URL(origin).protocol.slice(0, -1);
  return new Promise((resolve, reject) => {
    const request = wrapped[scheme].request(origin, {
      headers: structuredClone(headers), sensitiveHeaders, method,
    }, response => {
      assert.equal(response.statusCode, 200);
      resolve(requests);
    });
    request.on('error', reject);
    request.end();
  });
}

test('manifest, every lock resolution, and installed package use the reviewed release', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8'));
  assert.equal(manifest.overrides['follow-redirects'], fixedVersion);
  const entries = Object.entries(lock.packages)
    .filter(([name]) => /(?:^|\/)node_modules\/follow-redirects$/.test(name));
  assert.ok(entries.length > 0, 'a reviewed follow-redirects resolution must exist');
  for (const [name, entry] of entries) {
    assert.equal(entry.version, fixedVersion, name);
    assert.equal(entry.resolved, fixedResolution, name);
    assert.equal(entry.integrity, fixedIntegrity, name);
    assert.equal(require(path.join(root, name, 'package.json')).version, fixedVersion, name);
  }
});

const credentials = {
  Authorization: 'fixture-authorization',
  Cookie: 'fixture-cookie',
  'Proxy-Authorization': 'fixture-proxy-authorization',
};

for (const form of ['object', 'array']) {
  const headers = { ...credentials, 'X-Public': 'public-fixture' };
  const input = form === 'array' ? Object.entries(headers).flat() : headers;

  test(`${form} headers drop built-in credentials across domains`, { timeout: 2000 }, async () => {
    const sent = await followFixture({ headers: input });
    assert.equal(sent.length, 2);
    for (const name of Object.keys(credentials)) {
      assert.ok(sent[0].headers[name.toLowerCase()]);
      assert.equal(sent[1].headers[name.toLowerCase()], undefined, `${name} leaked`);
    }
    assert.equal(sent[1].headers['x-public'], 'public-fixture');
  });

  test(`${form} headers retain credentials for a same-origin redirect`, { timeout: 2000 }, async () => {
    const sent = await followFixture({ headers: input, location: '/finish' });
    assert.equal(sent.length, 2);
    for (const [name, value] of Object.entries(credentials)) {
      assert.equal(sent[1].headers[name.toLowerCase()], value);
    }
  });
}

for (const name of ['X-Api^Key', 'X-Token|Secret', 'X-Control-Key']) {
  test(`declared sensitive header ${name} is stripped literally`, { timeout: 2000 }, async () => {
    const sent = await followFixture({
      headers: { [name]: 'fixture-private-value', 'X-Public': 'public-fixture' },
      sensitiveHeaders: [name],
    });
    assert.equal(sent.length, 2);
    assert.equal(sent[0].headers[name.toLowerCase()], 'fixture-private-value');
    assert.equal(sent[1].headers[name.toLowerCase()], undefined);
    assert.equal(sent[1].headers['x-public'], 'public-fixture');
  });
}

test('array headers drop custom credentials on HTTPS downgrade', { timeout: 2000 }, async () => {
  const sent = await followFixture({
    origin: 'https://origin.invalid/start',
    location: 'http://origin.invalid/finish',
    headers: ['Authorization', 'fixture-private', 'X-Api^Key', 'fixture-custom'],
    sensitiveHeaders: ['X-Api^Key'],
  });
  assert.equal(sent.length, 2);
  assert.equal(sent[1].headers.authorization, undefined);
  assert.equal(sent[1].headers['x-api^key'], undefined);
});

test('array content headers are removed when 303 changes POST to GET', { timeout: 2000 }, async () => {
  const sent = await followFixture({
    method: 'POST', redirectCode: 303,
    headers: ['Content-Type', 'text/plain', 'Content-Length', '0', 'X-Public', 'fixture'],
  });
  assert.equal(sent[1].method, 'GET');
  assert.equal(sent[1].headers['content-type'], undefined);
  assert.equal(sent[1].headers['content-length'], undefined);
  assert.equal(sent[1].headers['x-public'], 'fixture');
});
