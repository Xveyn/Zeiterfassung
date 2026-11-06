import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scrubText } from '../log-scrub.js';

const CASES = [
  ['Failed to fetch https://updates.push.services.mozilla.com/wpush/v2/abc?x=1#f', 'Failed to fetch <url>'],
  ['ws://localhost:8099/x', '<url>'],
  ['connect 192.168.1.20:17654 refused', 'connect <ip> refused'],
  ['[fe80::1]:8080', '<ip>'],
  ['fe80::1ff:fe23:4567:890a', '<ip>'],
  ['an max@example.com', 'an <mail>'],
  ['xveyn.github.io', '<host>'],
  ['localhost:8099', '<host>'],
  ['a'.repeat(1) + 'B3x9Kq7Zr2LmN8vT4wY6uP1sD5fG0hJ3cE7aQ9bX2zR'.slice(1), '<schlüssel>'],
  ['0123456789abcdef0123456789abcdef', '<schlüssel>'],
  ['Tag 2026-11-04 08:00–16:30, 04.11.2026', 'Tag <datum> <zeit>–<zeit>, <datum>'],
  ['status 413 version 131.0.6778 port 8080 errno 109 in sw.js line 12', 'status 413 version 131.0.6778 port 8080 errno 109 in sw.js line 12'],
  ['Unexpected token \'S\', "Sende Max" is not valid JSON', 'Unexpected token \'S\', <text> is not valid JSON'],
  ['at 2026-11-04T08:00:00.000Z', 'at <datum>T<zeit>Z'],
  ['Tag 2026-11-04T08:00', 'Tag <datum>T<zeit>'],
  ['um 08:00Uhr und 16:30h', 'um <zeit>Uhr und <zeit>h'],
  ['::ffff:192.168.1.20', '<ip>'],
  ['[::ffff:192.168.1.20]:17654', '<ip>'],
  ['ServiceWorker cannot be started', 'ServiceWorker cannot be started'],
  ['Failed to update a ServiceWorker: An unknown error occurred when fetching the script.', 'Failed to update a ServiceWorker: An unknown error occurred when fetching the script.'],
  ['Registration failed - push service error', 'Registration failed - push service error'],
  ['The operation is insecure.', 'The operation is insecure.'],
  ['TypeError: Failed to fetch', 'TypeError: Failed to fetch'],
];

test('scrubText: Eingabe -> Ausgabe', () => {
  for (const [input, expected] of CASES) assert.equal(scrubText(input), expected, input);
});

test('der Schlüssel-Beispieltext ist 43 Zeichen lang', () => {
  assert.equal(CASES[8][0].length, 43);
});

test('scrubText: Nicht-Text ergibt leeren Text', () => {
  assert.equal(scrubText(undefined), '');
  assert.equal(scrubText({}), '');
});

test('scrubText: Whitespace wird ein Leerzeichen, Kürzung mit …', () => {
  assert.equal(scrubText('a \n\t b'), 'a b');
  const long = scrubText('x'.repeat(1000));
  assert.equal(long.length, 240);
  assert.ok(long.endsWith('…'));
  assert.equal(scrubText('abcdefgh', 5), 'abcd…');
});

test('scrubText ist idempotent', () => {
  for (const [input] of CASES) assert.equal(scrubText(scrubText(input)), scrubText(input), input);
  const long = scrubText('x'.repeat(1000));
  assert.equal(scrubText(long), long);
});

const PATH_CASES = [
  ['Cannot read /home/max/notes.txt', 'Cannot read <pfad>'],
  ['open /var/log/x failed', 'open <pfad> failed'],
  ['file C:\\Users\\Max\\a.txt failed', 'file <pfad> failed'],
  ['at C:/Users/Max/x', 'at <pfad>'],
  ['share \\\\server\\share\\x ok', 'share <pfad> ok'],
  ['und/oder a/b', 'und/oder a/b'],
  ['sw.js app.js /sw.js', 'sw.js app.js /sw.js'],
  ['Chrome 131.0.6778 port 8099 status 404', 'Chrome 131.0.6778 port 8099 status 404'],
  ['12/1.27.0 (a1b2c3d) 1/7/30', '12/1.27.0 (a1b2c3d) 1/7/30'],
  ['fetch https://x.example/a/b/c failed', 'fetch <url> failed'],
];

test('scrubText: Pfade werden Platzhalter, Dateinamen und Verhältnisse bleiben', () => {
  for (const [input, expected] of PATH_CASES) {
    assert.equal(scrubText(input), expected, input);
    assert.equal(scrubText(scrubText(input)), scrubText(input), input);
  }
});

test('ALL_CAPS error codes stay readable, real keys do not', () => {
  assert.equal(scrubText('net::ERR_HTTP2_PROTOCOL_ERROR'), 'net::ERR_HTTP2_PROTOCOL_ERROR');
  assert.equal(scrubText('ERR_CONNECTION_REFUSED'), 'ERR_CONNECTION_REFUSED');
  assert.equal(scrubText('0123456789ABCDEF0123456789ABCDEF'), '<schlüssel>');
});
