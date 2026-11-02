// relay/test/frames-contract.test.js
// Kreuzprobe: die gemeinsame Vertrags-Fixture (pwa/test/fixtures/relay-frames.json) gegen die
// Referenzimplementierung des Relays. Die Hex-Werte der Fixture sind unabhaengig berechnet.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { FRAME, decodePut, encodeOk, encodeSlot } from '../src/frames.js';
import { LIMITS } from '../src/validate.js';

const fixture = JSON.parse(
  readFileSync(new URL('../../pwa/test/fixtures/relay-frames.json', import.meta.url), 'utf8'),
);

const toHex = (bytes) => Buffer.from(bytes).toString('hex');
const fromHex = (hex) => Uint8Array.from(Buffer.from(hex, 'hex'));

test('the fixture constants match the relay', () => {
  const c = fixture.constants;
  // Das Subprotocol ist in box.js nicht exportiert: aus dem Quelltext lesen. Findet die Regex
  // nichts, schlägt der Test fehl (kein stilles Überspringen).
  const box = readFileSync(new URL('../src/box.js', import.meta.url), 'utf8');
  const protocol = /const PROTOCOL = '([^']+)'/.exec(box);
  assert.ok(protocol, 'const PROTOCOL in relay/src/box.js nicht gefunden');
  assert.equal(c.subprotocol, protocol[1]);
  assert.equal(c.max_frame, LIMITS.maxFrame);
  assert.equal(c.max_payload, LIMITS.maxFrame - 1);
  assert.equal(c.puts_per_minute, LIMITS.putsPerMinute);
  assert.deepEqual(c.types, FRAME);
});

test('encodeSlot and encodeOk produce the fixture bytes', () => {
  let checked = 0;
  for (const m of fixture.messages) {
    if (m.decoded === null) continue;
    const { kind, ver, data_hex: dataHex } = m.decoded;
    const out =
      kind === 'slot' ? encodeSlot(ver, fromHex(dataHex ?? '')) : encodeOk(ver);
    assert.equal(toHex(out), m.hex, m.name);
    checked += 1;
  }
  assert.ok(checked >= 3);
});

test('decodePut returns the fixture payload', () => {
  assert.ok(fixture.puts.length >= 2);
  for (const p of fixture.puts) {
    assert.equal(p.hex, '01' + p.payload_hex, p.name);
    const out = decodePut(fromHex(p.hex));
    assert.equal(toHex(out), p.payload_hex, p.name);
  }
});
