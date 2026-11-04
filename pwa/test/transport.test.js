// pwa/test/transport.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { LanTransport, endpointOf, isPaired } from '../transport.js';
import { SyncError } from '../sync-errors.js';

const ENDPOINT = { kind: 'lan', host: '192.168.1.2', port: 17654 };

function fetchReturning(status, json) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    return { status, ok: status >= 200 && status < 300, json: async () => json };
  };
  fn.calls = calls;
  return fn;
}

test('LanTransport sends the request to host and port and returns status and json', async () => {
  const fetchFn = fetchReturning(200, { a: 1 });
  const transport = new LanTransport({ fetchFn, timeoutMs: 1000 });
  const result = await transport.exchange({
    method: 'POST', path: '/v1/sync', token: 'T'.repeat(20), body: { x: 1 }, endpoint: ENDPOINT });
  assert.deepEqual(result, { status: 200, json: { a: 1 } });
  const { url, init } = fetchFn.calls[0];
  assert.equal(url, 'http://192.168.1.2:17654/v1/sync');
  assert.equal(init.method, 'POST');
  assert.equal(init.headers.Authorization, `Bearer ${'T'.repeat(20)}`);
  assert.equal(init.headers['Content-Type'], 'application/json');
  assert.equal(init.body, JSON.stringify({ x: 1 }));
  assert.equal(init.credentials, 'omit');
  assert.ok(init.signal instanceof AbortSignal);
});

test('LanTransport returns an error status instead of throwing', async () => {
  const transport = new LanTransport({ fetchFn: fetchReturning(500, { error: { code: 'internal_error' } }) });
  const result = await transport.exchange({ method: 'GET', path: '/v1/ping', endpoint: ENDPOINT });
  assert.equal(result.status, 500);
});

test('LanTransport turns a network failure into an offline SyncError and a timeout into timeout', async () => {
  const failing = new LanTransport({ fetchFn: async () => { throw new TypeError('Failed to fetch'); } });
  await assert.rejects(() => failing.exchange({ method: 'GET', path: '/v1/ping', endpoint: ENDPOINT }),
    (error) => error instanceof SyncError && error.kind === 'offline');
  const slow = new LanTransport({
    fetchFn: async () => { throw Object.assign(new Error('t'), { name: 'TimeoutError' }); } });
  await assert.rejects(() => slow.exchange({ method: 'GET', path: '/v1/ping', endpoint: ENDPOINT }),
    (error) => error instanceof SyncError && error.kind === 'timeout');
});

test('a body-less response is json null', async () => {
  const fetchFn = async () => ({ status: 204, ok: true, json: async () => { throw new SyntaxError('leer'); } });
  const result = await new LanTransport({ fetchFn }).exchange({ method: 'GET', path: '/x', endpoint: ENDPOINT });
  assert.deepEqual(result, { status: 204, json: null });
});

test('endpointOf and isPaired for a LAN pairing', () => {
  const meta = { address: { host: '192.168.1.2', port: 17654 }, token: 'x' };
  assert.deepEqual(endpointOf(meta), { kind: 'lan', host: '192.168.1.2', port: 17654 });
  assert.equal(isPaired(meta), true);
  assert.equal(endpointOf({ address: null, token: 'x' }), null);
  assert.equal(endpointOf({ address: meta.address, token: '' }), null);
  assert.equal(isPaired({ address: null, token: '' }), false);
});
