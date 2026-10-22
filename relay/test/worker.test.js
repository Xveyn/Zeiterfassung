// relay/test/worker.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import worker, { objectName } from '../src/worker.js';

const PAGES = 'https://xveyn.github.io';
const secret = (byte) => Buffer.alloc(32, byte).toString('base64url');

function setup(env = {}, deviceResponse = () => new Response(null, { status: 204 })) {
  const touched = [];
  const DEVICE = {
    idFromName: (name) => name,
    get: (id) => ({ fetch: async (request) => {
      touched.push({ id, method: request.method, path: new URL(request.url).pathname, body: await request.text() });
      return deviceResponse(request);
    } }),
  };
  const call = (method, path, { auth, origin, body } = {}) => worker.fetch(new Request(`https://relay.example${path}`, {
    method,
    headers: { ...(auth === undefined ? {} : { authorization: auth }), ...(origin ? { origin } : {}) },
    body,
  }), { DEVICE, ...env });
  return { call, touched };
}

test('routes the three endpoints to the device named after the secret hash', async () => {
  const { call, touched } = setup();
  const auth = `Bearer ${secret(1)}`;
  assert.equal((await call('PUT', '/v1/device', { auth, body: '{"a":1}' })).status, 204);
  await call('PUT', '/v1/schedule', { auth, body: '{"items":[]}' });
  await call('DELETE', '/v1/device', { auth });
  const name = await objectName(secret(1));
  assert.match(name, /^[0-9a-f]{64}$/);
  assert.notEqual(name, secret(1));
  assert.deepEqual(touched.map((t) => [t.id, t.method, t.path]), [
    [name, 'PUT', '/v1/device'], [name, 'PUT', '/v1/schedule'], [name, 'DELETE', '/v1/device']]);
  assert.equal(touched[0].body, '{"a":1}');
});

test('two different secrets reach two different objects', async () => {
  const { call, touched } = setup();
  await call('PUT', '/v1/schedule', { auth: `Bearer ${secret(1)}`, body: '{}' });
  await call('PUT', '/v1/schedule', { auth: `Bearer ${secret(2)}`, body: '{}' });
  assert.notEqual(touched[0].id, touched[1].id);
});

test('a missing or malformed Authorization header is 401 without touching a device', async () => {
  const { call, touched } = setup();
  for (const auth of [undefined, '', 'Bearer', `Bearer ${'a'.repeat(42)}`, `Basic ${secret(1)}`]) {
    const response = await call('PUT', '/v1/device', { auth, body: '{}' });
    assert.equal(response.status, 401, String(auth));
    assert.deepEqual(await response.json(), { error: 'unauthorized' });
  }
  assert.deepEqual(touched, []);
});

test('unknown routes are 404 and a wrong method is 405', async () => {
  const { call, touched } = setup();
  const auth = `Bearer ${secret(1)}`;
  assert.equal((await call('GET', '/', { auth })).status, 404);
  assert.equal((await call('PUT', '/v1/other', { auth, body: '{}' })).status, 404);
  const wrong = await call('GET', '/v1/device', { auth });
  assert.equal(wrong.status, 405);
  assert.match(wrong.headers.get('allow'), /PUT/);
  assert.equal((await call('POST', '/v1/schedule', { auth, body: '{}' })).status, 405);
  assert.deepEqual(touched, []);
});

test('preflight from the Pages origin gets CORS headers, other origins none', async () => {
  const { call, touched } = setup();
  const ok = await call('OPTIONS', '/v1/schedule', { origin: PAGES });
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get('access-control-allow-origin'), PAGES);
  assert.match(ok.headers.get('access-control-allow-methods'), /PUT/);
  assert.match(ok.headers.get('access-control-allow-headers').toLowerCase(), /authorization/);
  const other = await call('OPTIONS', '/v1/schedule', { origin: 'https://evil.example' });
  assert.equal(other.headers.get('access-control-allow-origin'), null);
  assert.deepEqual(touched, []);
});

test('responses carry Access-Control-Allow-Origin only for the allowed origin', async () => {
  const { call } = setup();
  const auth = `Bearer ${secret(1)}`;
  assert.equal((await call('PUT', '/v1/device', { auth, origin: PAGES, body: '{}' })).headers.get('access-control-allow-origin'), PAGES);
  assert.equal((await call('PUT', '/v1/device', { auth, origin: 'https://evil.example', body: '{}' })).headers.get('access-control-allow-origin'), null);
  assert.equal((await call('PUT', '/v1/device', { origin: PAGES, body: '{}' })).headers.get('access-control-allow-origin'), PAGES);
  const dev = setup({ DEV_ORIGIN: 'http://localhost:8099' });
  assert.equal((await dev.call('PUT', '/v1/device', { auth, origin: 'http://localhost:8099', body: '{}' })).headers.get('access-control-allow-origin'), 'http://localhost:8099');
  assert.equal((await call('PUT', '/v1/device', { auth, origin: 'http://localhost:8099', body: '{}' })).headers.get('access-control-allow-origin'), null);
});

test('a thrown error inside the device is 500 without echoing details or the secret', async () => {
  const { call } = setup({}, () => { throw new Error(`kaputt ${secret(1)}`); });
  const response = await call('PUT', '/v1/device', { auth: `Bearer ${secret(1)}`, origin: PAGES, body: '{}' });
  assert.equal(response.status, 500);
  const text = await response.text();
  assert.deepEqual(JSON.parse(text), { error: 'internal' });
  assert.ok(!text.includes(secret(1)));
  assert.equal(response.headers.get('access-control-allow-origin'), PAGES);
});

test('no request path logs the secret', async () => {
  const seen = [];
  const originals = {};
  for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
    originals[level] = console[level];
    console[level] = (...args) => seen.push(args.join(' '));
  }
  try {
    const failing = setup({}, () => { throw new Error('boom'); });
    const fine = setup();
    const auth = `Bearer ${secret(3)}`;
    await failing.call('PUT', '/v1/device', { auth, body: '{}' });
    await fine.call('PUT', '/v1/device', { auth, body: '{}' });
    await fine.call('PUT', '/v1/device', { auth: 'Bearer short', body: '{}' });
  } finally {
    Object.assign(console, originals);
  }
  assert.ok(seen.every((line) => !line.includes(secret(3))), seen.join('\n'));
});

test('a body over 300 KB is 413 without touching a device, with or without Content-Length (I4)', async () => {
  const { call, touched } = setup();
  const auth = `Bearer ${secret(1)}`;
  const big = 'x'.repeat(300_001);
  const declared = await call('PUT', '/v1/schedule', { auth, body: big });
  assert.equal(declared.status, 413);
  assert.deepEqual(await declared.json(), { error: 'too_large' });
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(big)); controller.close(); } });
  const streamed = await worker.fetch(new Request('https://relay.example/v1/schedule', {
    method: 'PUT', headers: { authorization: auth }, body: stream, duplex: 'half' }), { DEVICE: { idFromName: (n) => n, get: () => { throw new Error('touched'); } } });
  assert.equal(streamed.status, 413);
  assert.deepEqual(touched, []);
  assert.equal((await call('PUT', '/v1/schedule', { auth, body: 'x'.repeat(300_000) })).status, 204);
});

test('the Authorization header is not forwarded to the device', async () => {
  let forwarded;
  const { call } = setup({}, (request) => { forwarded = request.headers.get('authorization'); return new Response(null, { status: 204 }); });
  await call('PUT', '/v1/device', { auth: `Bearer ${secret(1)}`, body: '{}' });
  assert.equal(forwarded, null);
});

function limiter(allow) {
  const keys = [];
  return { keys, binding: { limit: async ({ key }) => { keys.push(key); return { success: allow(key) }; } } };
}

function callFrom(ip, env) {
  const { call, touched } = setup(env);
  const send = (auth) => worker.fetch(new Request('https://relay.example/v1/device', {
    method: 'PUT', headers: { ...(auth ? { authorization: auth } : {}), ...(ip ? { 'cf-connecting-ip': ip } : {}) }, body: '{}',
  }), { DEVICE: { idFromName: (n) => n, get: () => ({ fetch: async () => new Response(null, { status: 204 }) }) }, ...env });
  return { send, call, touched };
}

test('a blocked client gets 429 before auth and before any device is touched', async () => {
  const { binding } = limiter(() => false);
  const { call, touched } = setup({ LIMITER: binding });
  const response = await call('PUT', '/v1/device', { auth: `Bearer ${secret(1)}`, body: '{}' });
  assert.equal(response.status, 429);
  assert.deepEqual(await response.json(), { error: 'rate_limited' });
  assert.equal((await call('PUT', '/v1/device', { body: '{}' })).status, 429);
  assert.deepEqual(touched, []);
});

test('the limit is keyed by the client address, not by the secret', async () => {
  const { keys, binding } = limiter(() => true);
  const env = { LIMITER: binding };
  await callFrom('203.0.113.7', env).send(`Bearer ${secret(1)}`);
  await callFrom('203.0.113.7', env).send(`Bearer ${secret(2)}`);
  assert.deepEqual(keys, ['203.0.113.7', '203.0.113.7']);
});

test('only the blocked address is refused', async () => {
  const { binding } = limiter((key) => key !== '198.51.100.9');
  const env = { LIMITER: binding };
  assert.equal((await callFrom('198.51.100.9', env).send(`Bearer ${secret(1)}`)).status, 429);
  assert.equal((await callFrom('203.0.113.7', env).send(`Bearer ${secret(1)}`)).status, 204);
});

test('a preflight does not use up the limit', async () => {
  const { keys, binding } = limiter(() => false);
  const { call } = setup({ LIMITER: binding });
  assert.equal((await call('OPTIONS', '/v1/device', { origin: PAGES })).status, 204);
  assert.deepEqual(keys, []);
});

test('a broken limiter does not take the relay down', async () => {
  const binding = { limit: async () => { throw new Error('limiter down'); } };
  const { send } = callFrom('203.0.113.7', { LIMITER: binding });
  assert.equal((await send(`Bearer ${secret(1)}`)).status, 204);
});

test('without a limiter binding (local dev) requests pass', async () => {
  const { send } = callFrom('203.0.113.7', {});
  assert.equal((await send(`Bearer ${secret(1)}`)).status, 204);
});

test('IPv6 addresses of one /64 share one limit key, other networks and IPv4 keep their own', async () => {
  const { keys, binding } = limiter(() => true);
  const env = { LIMITER: binding };
  for (const ip of ['2001:db8:1:2:aaaa:bbbb:cccc:dddd', '2001:DB8:1:2::1', '2001:db8:1:2:0:0:0:0', '2001:db8:1:3::1',
    '::1', '203.0.113.7', '::ffff:203.0.113.7']) {
    await callFrom(ip, env).send(`Bearer ${secret(1)}`);
  }
  assert.equal(keys[0], keys[1]);
  assert.equal(keys[1], keys[2]);
  assert.notEqual(keys[2], keys[3]);
  assert.equal(keys[5], '203.0.113.7');
  assert.equal(keys[6], '203.0.113.7');
  assert.equal(new Set(keys).size, 4);
});
