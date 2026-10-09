// pwa/test/pairing.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  CODE_ALPHABET, DEFAULT_PORT, PROTOCOL, baseUrl, deviceNameFromUserAgent, isLanAddress,
  isValidDeviceId, newDeviceId, normalizeCode, pairRequestBody, parseHostPort, parsePairFragment,
} from '../pairing.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/pairing-cases.json', import.meta.url)));

test('the code alphabet has 31 unambiguous characters', () => {
  assert.equal(CODE_ALPHABET.length, 31);
  assert.equal(new Set(CODE_ALPHABET).size, 31);
  for (const ch of '01ILO') assert.equal(CODE_ALPHABET.includes(ch), false, ch);
  assert.equal(PROTOCOL, 1);
  assert.equal(DEFAULT_PORT, 17654);
});

for (const row of cases.codes) {
  test(`normalizeCode ${JSON.stringify(row.raw)}`, () => {
    assert.equal(normalizeCode(row.raw), row.code);
  });
}

test('normalizeCode refuses non-text and very long input', () => {
  for (const junk of [null, undefined, 5, {}, [], 'A'.repeat(5000)]) assert.equal(normalizeCode(junk), null);
});

for (const row of cases.lan_addresses) {
  test(`isLanAddress ${JSON.stringify(row.address)}`, () => {
    assert.equal(isLanAddress(row.address), row.lan);
  });
}

test('isLanAddress refuses non-text', () => {
  for (const junk of [null, undefined, 5, 192168120, [], {}]) assert.equal(isLanAddress(junk), false);
});

for (const row of cases.fragments) {
  test(`parsePairFragment ${JSON.stringify(row.hash)}`, () => {
    const result = parsePairFragment(row.hash);
    if (row.host === null) {
      assert.equal(result, null);
    } else {
      assert.deepEqual(result, { host: row.host, port: row.port, code: row.code });
    }
  });
}

test('parsePairFragment refuses non-text', () => {
  for (const junk of [null, undefined, 5, {}]) assert.equal(parsePairFragment(junk), null);
});

test('a manual address may omit the port', () => {
  assert.deepEqual(parseHostPort('192.168.1.20'), { host: '192.168.1.20', port: 17654 });
  assert.deepEqual(parseHostPort('192.168.1.20:20000'), { host: '192.168.1.20', port: 20000 });
  assert.deepEqual(parseHostPort(' 192.168.1.20:20000 '), { host: '192.168.1.20', port: 20000 });
  for (const bad of ['', 'evil.example', '8.8.8.8:17654', '192.168.1.20:', '192.168.1.20:80',
    '192.168.1.20:17654:1', 'http://192.168.1.20:17654', null]) {
    assert.equal(parseHostPort(bad), null, String(bad));
  }
});

test('baseUrl is plain http to host and port', () => {
  assert.equal(baseUrl({ host: '192.168.1.20', port: 17654 }), 'http://192.168.1.20:17654');
});

test('a device id is a UUID and valid for the server', () => {
  const id = newDeviceId();
  assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(isValidDeviceId(id), true);
  assert.notEqual(newDeviceId(), newDeviceId());
});

test('a device id also works without crypto.randomUUID', () => {
  const noUuid = { getRandomValues: (array) => { array.fill(0xab); return array; } };
  const id = newDeviceId(noUuid);
  assert.equal(isValidDeviceId(id), true);
  assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test('isValidDeviceId matches the server rule', () => {
  for (const ok of ['6f1c2b9e-3d4a-4b5c-8d7e-9f0a1b2c3d4e', 'ABCDEFGH', 'a'.repeat(64)]) {
    assert.equal(isValidDeviceId(ok), true, ok);
  }
  for (const bad of ['', 'kurz', 'a'.repeat(65), 'mit leerzeichen!', 'ä'.repeat(10), null, 5]) {
    assert.equal(isValidDeviceId(bad), false, String(bad));
  }
});

test('the device name comes from the user agent and falls back to a default', () => {
  assert.equal(deviceNameFromUserAgent(
    'Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UP1A) AppleWebKit/537.36'), 'Pixel 7');
  assert.equal(deviceNameFromUserAgent(
    'Mozilla/5.0 (Linux; Android 10; SM-G991B) AppleWebKit/537.36'), 'SM-G991B');
  // Chromes reduzierter User-Agent ersetzt das Modell durch „K“: unbrauchbar.
  assert.equal(deviceNameFromUserAgent('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'), 'Android-Handy');
  assert.equal(deviceNameFromUserAgent(''), 'Android-Handy');
  assert.equal(deviceNameFromUserAgent(null), 'Android-Handy');
  assert.equal(deviceNameFromUserAgent('Mozilla/5.0 (X11; Linux x86_64)'), 'Android-Handy');
  assert.ok(deviceNameFromUserAgent(`(Linux; Android 14; ${'x'.repeat(200)})`).length <= 60);
});

test('the pair request body has the protocol fields', () => {
  assert.deepEqual(pairRequestBody({ code: 'K7M2-9QXA', deviceName: 'Pixel', deviceId: 'abcdefgh' }), {
    protocol: 1, code: 'K7M2-9QXA', device_name: 'Pixel', device_id: 'abcdefgh',
  });
});
