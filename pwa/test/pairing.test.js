// pwa/test/pairing.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  CODE_ALPHABET, CODE_LENGTH, DEFAULT_PORT, PROTOCOL, baseUrl, deviceNameFromUserAgent, isLanAddress,
  isValidDeviceId, newDeviceId, normalizeCode, pairRequestBody, parseHostPort, parsePairFragment, parsePairLink, parseQrText,
} from '../pairing.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/pairing-cases.json', import.meta.url)));

test('the code alphabet has 31 unambiguous characters', () => {
  assert.equal(CODE_ALPHABET.length, 31);
  assert.equal(new Set(CODE_ALPHABET).size, 31);
  for (const ch of '01ILO') assert.equal(CODE_ALPHABET.includes(ch), false, ch);
  assert.equal(PROTOCOL, 2);
  assert.equal(CODE_LENGTH, 28);
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

test('the pair request body has the protocol fields and never carries the code', () => {
  const body = pairRequestBody({ code: 'K7M29QXA'.repeat(3) + 'K7M2', deviceName: 'Pixel', deviceId: 'abcdefgh' });
  assert.deepEqual(body, { protocol: 2, device_name: 'Pixel', device_id: 'abcdefgh' });
  assert.equal(JSON.stringify(body).includes('K7M2'), false);
});

test('a scanned QR text is the full link; only its fragment counts', () => {
  const L = 'K7M29QXA'.repeat(3) + 'K7M2';
  const N = '23456789'.repeat(3) + '2345';
  assert.deepEqual(parseQrText(`https://xveyn.github.io/Zeiterfassung/#pair=192.168.178.20:17654:${L}`),
    { host: '192.168.178.20', port: 17654, code: L });
  assert.deepEqual(parseQrText(`http://localhost:8099/#pair=10.0.0.5:20000:${N}`),
    { host: '10.0.0.5', port: 20000, code: N });
  for (const bad of ['', 'kein link', `https://x.example/#pair=8.8.8.8:17654:${L}`,
    `https://x.example/#pair=192.168.1.20:80:${L}`, 'https://x.example/#pair=192.168.1.20:17654:K7M29QXA',
    'https://x.example/', 'https://x.example/#other=1',
    null, undefined, 5, 'http://[::1', 'a'.repeat(5000)]) {
    assert.equal(parseQrText(bad), null, String(bad).slice(0, 30));
  }
});

const relayFrames = JSON.parse(readFileSync(new URL('./fixtures/relay-frames.json', import.meta.url)));
const RELAY_SECRET = 'Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmE';
const RELAY_CODE = 'K7M29QXAK7M29QXAK7M29QXAK7M2';
const RELAY_BASE = 'https://xveyn.github.io/Zeiterfassung/';

test('parsePairLink matches every fixture link (lan, relay, null)', () => {
  assert.ok(relayFrames.links.length > 0);
  for (const row of relayFrames.links) {
    const result = parsePairLink(row.url);
    if (row.kind === 'lan') {
      assert.deepEqual(result, { kind: 'lan', host: row.host, port: row.port, code: row.code }, row.url);
    } else if (row.kind === 'relay') {
      assert.deepEqual(result, { kind: 'relay', secret: row.secret, code: row.code }, row.url);
    } else {
      assert.equal(result, null, row.url.slice(0, 80));
    }
  }
});

test('parsePairLink leaves parseQrText untouched: a relay link still yields null from parseQrText', () => {
  const link = `${RELAY_BASE}#relay=${RELAY_SECRET}:${RELAY_CODE}`;
  assert.equal(parseQrText(link), null);
  assert.equal(parsePairFragment(`#relay=${RELAY_SECRET}:${RELAY_CODE}`), null);
  assert.deepEqual(parsePairLink(link), { kind: 'relay', secret: RELAY_SECRET, code: RELAY_CODE });
});

test('parsePairLink rejects longer than 512 characters', () => {
  const tail = `#relay=${RELAY_SECRET}:${RELAY_CODE}`;
  const fits = RELAY_BASE + 'x'.repeat(512 - RELAY_BASE.length - tail.length) + tail;
  assert.equal(fits.length, 512);
  assert.deepEqual(parsePairLink(fits), { kind: 'relay', secret: RELAY_SECRET, code: RELAY_CODE });
  const tooLong = RELAY_BASE + 'x'.repeat(513 - RELAY_BASE.length - tail.length) + tail;
  assert.equal(tooLong.length, 513);
  assert.equal(parsePairLink(tooLong), null);
  for (const junk of [null, undefined, 5, {}, '']) assert.equal(parsePairLink(junk), null);
});

test('parsePairLink rejects whitespace inside the relay fragment', () => {
  const head = `${RELAY_BASE}#relay=${RELAY_SECRET}:`;
  assert.equal(parsePairLink(`${head}${RELAY_CODE.slice(0, 10)} ${RELAY_CODE.slice(10)}`), null);
  assert.equal(parsePairLink(`${head}${RELAY_CODE}\n`), null);
  assert.equal(parsePairLink(`${head}${RELAY_CODE.toLowerCase()}`), null);
});

test('an LAN link keeps parsing as lan with the same host, port and code as before', () => {
  const link = `${RELAY_BASE}#pair=192.168.178.20:17654:${RELAY_CODE}`;
  const before = parseQrText(link);
  assert.deepEqual(parsePairLink(link), { kind: 'lan', ...before });
  assert.equal(parsePairLink(`${RELAY_BASE}#pair=8.8.8.8:17654:${RELAY_CODE}`), null);
});
