#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const EXPECTED_COMMIT = 'ceba34402e329f0365134f23fe19898756527d65';
const EXPECTED_OVERRIDE = `git+https://github.com/digitalbazaar/forge.git#${EXPECTED_COMMIT}`;
const ROOT = path.resolve(__dirname, '..');

function verifyPin() {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
  const lock = JSON.parse(fs.readFileSync(path.join(ROOT, 'package-lock.json'), 'utf8'));
  const lockEntry = lock.packages?.['node_modules/node-forge'];

  assert.equal(manifest.overrides?.['node-forge'], EXPECTED_OVERRIDE,
    'package.json must retain the reviewed HTTPS URL and full upstream commit SHA');
  assert.equal(lockEntry?.version, '1.4.1-0',
    'lockfile must retain the tested upstream prerelease version');
  assert.equal(lockEntry?.resolved, EXPECTED_OVERRIDE,
    'lockfile must resolve node-forge from the exact reviewed commit');
  assert.ok(lockEntry.integrity, 'lockfile must include npm integrity for the fetched archive');

  const installed = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'node_modules/node-forge/package.json'), 'utf8'
  ));
  assert.equal(installed.version, lockEntry.version,
    'installed node-forge version must match the pinned lock entry');
}

function loadForge() {
  const externalPackage = process.argv.indexOf('--forge-package');
  if (externalPackage !== -1) {
    assert.ok(process.argv[externalPackage + 1], '--forge-package requires a package directory');
    return require(path.resolve(process.argv[externalPackage + 1]));
  }
  return require('node-forge');
}

// Regression vector adapted from digitalbazaar/forge PR #1152, tests/unit/rsa.js.
// The upstream project is BSD-3-Clause OR GPL-2.0; see the documentation for attribution.
function reproduceExploit(forge) {
  const modulus = new forge.jsbn.BigInteger(
    'E932AC92252F585B3A80A4DD76A897C8B7652952FE788F6EC8DD640587A1EE56' +
    '47670A8AD4C2BE0F9FA6E49C605ADF77B5174230AF7BD50E5D6D6D6D28CCF0A8' +
    '86A514CC72E51D209CC772A52EF419F6A953F3135929588EBE9B351FCA61CED7' +
    '8F346FE00DBB6306E5C2A4C6DFC3779AF85AB417371CF34D8387B9B30AE46D7A' +
    '5FF5A655B8D8455F1B94AE736989D60A6F2FD5CADBFFBD504C5A756A2E6BB5CE' +
    'CC13BCA7503F6DF8B52ACE5C410997E98809DB4DC30D943DE4E812A47553DCE5' +
    '4844A78E36401D13F77DC650619FED88D8B3926E3D8E319C80C744779AC5D6AB' +
    'E252896950917476ECE5E8FC27D5F053D6018D91B502C4787558A002B9283DA7', 16
  );
  const publicKey = forge.pki.rsa.setPublicKey(modulus, new forge.jsbn.BigInteger('3'));
  const signature = Buffer.from(
    'a4ae63dd5e7712b78f4870d0f51e294df5503d4f16c5d27ae33370981fb57f0de49f' +
    '50f3d6a04666774cd984cd13972db9bf8e12bd294ef0ddc916c7c86cbae63efd7b6b' +
    '97885e69760c208a40f1aecc76a90d7af5145177efce1bb55807a8d05c20b1596753' +
    'ba710642fc9acdde6c160232654662c77cc4466c8257a38edb49f894e8845d0fd987' +
    'b857ced88f4b62505a080bd87ef700d35d392a6e8f6fde34250c50b86fae606cb551' +
    '215e8f4813239b77651d5565ad453698c071d48c31e8e526fb4a37610f64b3e1fb8e' +
    '5be5898e408ad08197a0947794a530b54f84485377ce4a7488ed485ce4e5e105dd89' +
    '698a472f390c3b1b76bc16b73276c4d1c81d', 'hex'
  ).toString('binary');
  const digest = forge.md.sha256.create();
  digest.update('hello world!');

  try {
    return publicKey.verify(digest.digest().getBytes(), signature, undefined, {
      _parseAllDigestBytes: true,
      _skipPaddingChecks: true,
    });
  } catch (error) {
    if (error.message.includes('valid RSASSA-PKCS1-v1_5 DigestInfo')) return false;
    throw error;
  }
}

function verifyValidRsaCompatibility(forge) {
  const keyPair = forge.pki.rsa.generateKeyPair({ bits: 1024, e: 0x10001 });
  const message = 'CYPHER65 node-forge RSA compatibility check';
  const signer = forge.md.sha256.create();
  signer.update(message, 'utf8');
  const signature = keyPair.privateKey.sign(signer);
  const verifier = forge.md.sha256.create();
  verifier.update(message, 'utf8');
  assert.equal(keyPair.publicKey.verify(verifier.digest().getBytes(), signature), true,
    'a valid RSA/SHA-256 signature must continue to verify');

  const tampered = forge.md.sha256.create();
  tampered.update(`${message}!`, 'utf8');
  assert.equal(keyPair.publicKey.verify(tampered.digest().getBytes(), signature), false,
    'a modified message must not verify against the original signature');
}

const baselineMode = process.argv.includes('--expect-vulnerable-baseline');
if (!baselineMode) verifyPin();

const forge = loadForge();
const forgeVersion = require(
  process.argv.includes('--forge-package')
    ? path.join(path.resolve(process.argv[process.argv.indexOf('--forge-package') + 1]), 'package.json')
    : path.join(ROOT, 'node_modules/node-forge/package.json')
).version;
const exploitAccepted = reproduceExploit(forge);
if (baselineMode) {
  assert.equal(exploitAccepted, true,
    'the vulnerable baseline is expected to accept the upstream forgery vector');
  console.log(`Confirmed vulnerable baseline: node-forge ${forgeVersion} accepted exploit vector.`);
} else {
  assert.equal(exploitAccepted, false,
    'the pinned candidate must reject the upstream forgery vector');
  verifyValidRsaCompatibility(forge);
  console.log(`Verified pinned node-forge ${forgeVersion}: exploit rejected; valid RSA compatibility passed.`);
}
