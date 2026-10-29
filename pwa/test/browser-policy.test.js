// pwa/test/browser-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { blocksLan, browserKind } from '../browser-policy.js';

const UA = {
  chromeAndroid: 'Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36',
  samsung: 'Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36',
  edgeAndroid: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36 EdgA/130.0.0.0',
  firefoxAndroid: 'Mozilla/5.0 (Android 14; Mobile; rv:131.0) Gecko/131.0 Firefox/131.0',
  firefoxDesktop: 'Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0',
  safariIphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
  chromeIphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0.6723.90 Mobile/15E148 Safari/604.1',
  firefoxIphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/131.0 Mobile/15E148 Safari/605.1.15',
  safariMac: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15',
};

test('Chromium browsers are told apart from Firefox and from everything on iOS', () => {
  assert.equal(browserKind(UA.chromeAndroid), 'chromium');
  assert.equal(browserKind(UA.samsung), 'chromium');
  assert.equal(browserKind(UA.edgeAndroid), 'chromium');
  assert.equal(browserKind(UA.firefoxAndroid), 'firefox');
  assert.equal(browserKind(UA.firefoxDesktop), 'firefox');
  assert.equal(browserKind(UA.safariMac), 'safari');
});

test('every browser on an iPhone is WebKit, whatever its name says', () => {
  assert.equal(browserKind(UA.safariIphone), 'ios');
  assert.equal(browserKind(UA.chromeIphone), 'ios');
  assert.equal(browserKind(UA.firefoxIphone), 'ios');
});

test('userAgentData marks Chromium even when the user agent string is reduced', () => {
  const data = { brands: [{ brand: 'Not A;Brand', version: '99' }, { brand: 'Chromium', version: '130' }] };
  assert.equal(browserKind('Mozilla/5.0 (X11; Linux x86_64)', data), 'chromium');
  assert.equal(browserKind('', { brands: [] }), 'unknown');
});

test('nothing recognizable is unknown, never an error', () => {
  for (const input of ['', undefined, null, 42, 'curl/8.0']) assert.equal(browserKind(input), 'unknown', String(input));
  assert.equal(browserKind('x', 'kaputt'), 'unknown');
});

test('only the engines known to block http in the local network count as blocking', () => {
  for (const kind of ['firefox', 'ios', 'safari']) assert.equal(blocksLan(kind), true, kind);
  for (const kind of ['chromium', 'unknown', undefined]) assert.equal(blocksLan(kind), false, String(kind));
});
