// pwa/test/messages.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { describeError } from '../messages.js';
import { PROTOCOL } from '../pairing.js';
import { SyncError } from '../sync.js';

const errors = JSON.parse(readFileSync(new URL('./fixtures/errors.json', import.meta.url)));

test('every error kind the server can produce has its own text', () => {
  const kinds = new Set(errors.map((row) => row.kind));
  for (const extra of ['offline', 'not_paired', 'timeout']) kinds.add(extra);
  const fallback = describeError(new SyncError({ kind: 'völlig_neu' })).text;
  for (const kind of kinds) {
    const { text } = describeError(new SyncError({ kind, message: 'Text vom Server', code: '' }));
    assert.ok(text.length > 10, kind);
    assert.notEqual(text, fallback, `${kind} fällt auf den Standardtext zurück`);
  }
});

test('re-pairing is offered for every case where the token is no longer accepted', () => {
  for (const code of ['unauthorized', 'token_expired', 'token_revoked']) {
    const result = describeError(new SyncError({ kind: 'repair', code, needsRepair: true }));
    assert.equal(result.action, 'pair', code);
  }
});

test('the revoked, expired and replaced cases are told apart', () => {
  const text = (code) => describeError(new SyncError({ kind: 'repair', code })).text;
  assert.match(text('token_revoked'), /widerrufen/);
  assert.match(text('token_expired'), /abgelaufen/);
  assert.match(text('unauthorized'), /nicht mehr akzeptiert/);
});

test('an unreachable desktop offers a new scan', () => {
  assert.equal(describeError(new SyncError({ kind: 'offline' })).action, 'rescan');
  assert.equal(describeError(new SyncError({ kind: 'address' })).action, 'rescan');
});

test('server texts are passed through for invalid entries and client errors', () => {
  assert.match(describeError(new SyncError({ kind: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' })).text,
    /Endzeit muss nach Startzeit liegen/);
  assert.match(describeError(new SyncError({ kind: 'client_error', message: 'Body ist zu groß.' })).text, /Body ist zu groß/);
});

test('clock skew and an invalid code say what to do', () => {
  assert.match(describeError(new SyncError({ kind: 'clock_skew' })).text, /Uhr/);
  assert.match(describeError(new SyncError({ kind: 'invalid_code' })).text, /neuen Code/);
});

test('transient and server errors may be retried', () => {
  assert.equal(describeError(new SyncError({ kind: 'transient', code: 'busy' })).action, 'retry');
  assert.equal(describeError(new SyncError({ kind: 'server' })).action, 'retry');
});

test('anything that is not a SyncError still gets a text', () => {
  assert.ok(describeError(new Error('kaputt')).text.length > 10);
  assert.ok(describeError(null).text.length > 10);
  assert.ok(describeError(undefined).text.length > 10);
});

test('crypto and encryption errors say to pair again and keep the unsent entries', () => {
  for (const kind of ['crypto', 'encryption']) {
    const result = describeError(new SyncError({ kind, needsRepair: true }));
    assert.equal(result.action, 'pair', kind);
    assert.match(result.text, /neu koppeln/, kind);
    assert.match(result.text, /nicht übertragenen Einträge bleiben erhalten/, kind);
  }
  assert.notEqual(describeError(new SyncError({ kind: 'crypto' })).text,
    describeError(new SyncError({ kind: 'encryption' })).text);
});

test('a locked keyring on the desktop is told apart from a busy desktop and may be retried', () => {
  const locked = describeError(new SyncError({ kind: 'transient', code: 'key_unavailable' }));
  const busy = describeError(new SyncError({ kind: 'transient', code: 'busy' }));
  assert.match(locked.text, /Schlüsselbund/);
  assert.equal(locked.action, 'retry');
  assert.notEqual(locked.text, busy.text);
});

// --- Welche Seite ist älter? (#290) ---------------------------------------------------------------

test('a protocol mismatch says which side is older when the desktop names its protocol', () => {
  const older = describeError(new SyncError({ kind: 'protocol', code: 'invalid_protocol', supportedProtocol: PROTOCOL - 1 }));
  assert.match(older.text, /Desktop-App ist älter/);
  assert.equal(older.action, null);

  const newer = describeError(new SyncError({ kind: 'protocol', code: 'invalid_protocol', supportedProtocol: PROTOCOL + 1 }));
  assert.match(newer.text, /Desktop-App ist neuer/);
  assert.equal(newer.action, 'reload');
});

test('without a usable protocol number the generic mismatch text is kept', () => {
  const generic = describeError(new SyncError({ kind: 'protocol', code: 'invalid_protocol' })).text;
  assert.match(generic, /passen nicht zusammen/);
  for (const supportedProtocol of [null, undefined, PROTOCOL, 'x', 1.5, -1]) {
    assert.equal(describeError(new SyncError({ kind: 'protocol', code: 'invalid_protocol', supportedProtocol })).text, generic,
      String(supportedProtocol));
  }
});

test('a timeout names both likely causes and where the history can be reset (#292)', () => {
  const { text, action } = describeError(new SyncError({ kind: 'timeout', retryable: true }));
  assert.match(text, /Zeitüberschreitung/);
  assert.match(text, /Verbindung/);
  assert.match(text, /90 Tage/);
  assert.equal(action, 'retry');
});
