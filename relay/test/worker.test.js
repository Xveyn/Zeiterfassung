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

// --- Testroute (#340) ---------------------------------------------------------------------------

test('POST /v1/test is routed to the device named after the secret hash', async () => {
  const { call, touched } = setup();
  const auth = `Bearer ${secret(1)}`;
  assert.equal((await call('POST', '/v1/test', { auth })).status, 204);
  assert.deepEqual(touched.map((t) => [t.id, t.method, t.path]),
    [[await objectName(secret(1)), 'POST', '/v1/test']]);
});

test('the test route needs the bearer like the others and allows POST only', async () => {
  const { call, touched } = setup();
  assert.equal((await call('POST', '/v1/test', {})).status, 401);
  const wrong = await call('PUT', '/v1/test', { auth: `Bearer ${secret(1)}`, body: '{}' });
  assert.equal(wrong.status, 405);
  assert.equal(wrong.headers.get('allow'), 'POST');
  assert.deepEqual(touched, []);
});

test('the preflight for the test route allows POST', async () => {
  const { call } = setup();
  const ok = await call('OPTIONS', '/v1/test', { origin: PAGES });
  assert.equal(ok.status, 204);
  assert.match(ok.headers.get('access-control-allow-methods'), /POST/);
});

// --- Box (#358) ---------------------------------------------------------------------------------

function boxSetup(env = {}, answer = () => new Response(null, { status: 204 })) {
  const seen = [];
  const jurisdictions = [];
  let direct = 0;
  const BOX = {
    idFromName: () => { direct += 1; return 'direct'; },
    jurisdiction: (name) => {
      jurisdictions.push(name);
      return { idFromName: (n) => n, get: (id) => ({ fetch: async (request) => {
        seen.push({ id, request, body: await request.text() });
        return answer(request);
      } }) };
    },
  };
  const call = (method, path, { headers = {}, origin } = {}) => worker.fetch(new Request(`https://relay.example${path}`, {
    method, headers: { ...headers, ...(origin ? { origin } : {}) },
  }), { BOX, DEVICE: { idFromName: (n) => n, get: () => { throw new Error('device'); } }, ...env });
  const ws = (query = '?role=phone', extra = {}, o = {}) => call('GET', `/v1/box/ws${query}`, {
    headers: { upgrade: 'websocket', 'sec-websocket-protocol': `zeit.v1, ${secret(1)}`, ...extra }, ...o });
  return { call, ws, seen, jurisdictions, direct: () => direct };
}

test('ws route with valid subprotocol reaches the box named after sha256(secret); the 101 answer is returned as is (same object)', async () => {
  const answer = new Response(null, { status: 204 });
  const { ws, seen } = boxSetup({}, () => answer);
  const response = await ws('?role=desktop&have=7');
  assert.equal(response, answer);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].id, await objectName(secret(1)));
  const url = new URL(seen[0].request.url);
  assert.equal(url.pathname, '/v1/box/ws');
  assert.equal(url.searchParams.get('role'), 'desktop');
  assert.equal(url.searchParams.get('have'), '7');
  assert.equal(seen[0].request.headers.get('upgrade'), 'websocket');
});

test('have is omitted when absent and the raw query is not forwarded', async () => {
  const { ws, seen } = boxSetup();
  await ws('?role=phone&junk=1');
  assert.equal(new URL(seen[0].request.url).search, '?role=phone');
});

test('response protocol is exactly "zeit.v1" and the secret appears in no response header', async () => {
  const answer = new Response(null, { status: 204, headers: { 'sec-websocket-protocol': 'zeit.v1' } });
  const { ws } = boxSetup({}, () => answer);
  const response = await ws();
  assert.equal(response.headers.get('sec-websocket-protocol'), 'zeit.v1');
  for (const [, value] of response.headers) assert.ok(!value.includes(secret(1)));
});

test('the request forwarded to the box has no authorization/protocol header containing the secret and no body', async () => {
  const { ws, call, seen } = boxSetup();
  await ws();
  await call('DELETE', '/v1/box', { headers: { authorization: `Bearer ${secret(1)}` } });
  assert.equal(seen.length, 2);
  for (const { request, body } of seen) {
    assert.equal(request.headers.get('authorization'), null);
    assert.equal(request.headers.get('sec-websocket-protocol'), null);
    for (const [, value] of request.headers) assert.ok(!value.includes(secret(1)));
    assert.ok(!request.url.includes(secret(1)));
    assert.equal(body, '');
  }
});

test('ws without upgrade header is 426; missing/invalid subprotocol is 401; invalid role/have is 400', async () => {
  const { call, ws, seen } = boxSetup();
  const noUpgrade = await call('GET', '/v1/box/ws?role=phone', { headers: { 'sec-websocket-protocol': `zeit.v1, ${secret(1)}` } });
  assert.equal(noUpgrade.status, 426);
  assert.deepEqual(await noUpgrade.json(), { error: 'upgrade_required' });
  for (const protocol of [undefined, `${secret(1)}`, 'zeit.v1', `zeit.v1, ${'a'.repeat(42)}`]) {
    const headers = { upgrade: 'websocket', ...(protocol === undefined ? {} : { 'sec-websocket-protocol': protocol }) };
    const response = await call('GET', '/v1/box/ws?role=phone', { headers });
    assert.equal(response.status, 401, String(protocol));
    assert.deepEqual(await response.json(), { error: 'unauthorized' });
  }
  for (const query of ['', '?role=x', '?role=phone&have=-1', '?role=phone&have=abc']) {
    const response = await ws(query);
    assert.equal(response.status, 400, query);
    assert.deepEqual(await response.json(), { error: 'invalid_request' });
  }
  assert.deepEqual(seen, []);
});

test('foreign Origin is 403; no Origin is allowed; PAGES_ORIGIN is allowed', async () => {
  const { ws, seen } = boxSetup({ DEV_ORIGIN: 'http://localhost:8099' });
  const foreign = await ws('?role=phone', {}, { origin: 'https://evil.example' });
  assert.equal(foreign.status, 403);
  assert.deepEqual(await foreign.json(), { error: 'forbidden_origin' });
  assert.equal(seen.length, 0);
  assert.equal((await ws()).status, 204);
  assert.equal((await ws('?role=phone', {}, { origin: PAGES })).status, 204);
  assert.equal((await ws('?role=phone', {}, { origin: 'http://localhost:8099' })).status, 204);
});

test('rate limit applies: LIMITER failing -> 429 before any box access', async () => {
  const { binding } = limiter(() => false);
  const { ws, call, seen, jurisdictions } = boxSetup({ LIMITER: binding });
  assert.equal((await ws()).status, 429);
  assert.equal((await call('DELETE', '/v1/box', { headers: { authorization: `Bearer ${secret(1)}` } })).status, 429);
  assert.deepEqual(seen, []);
  assert.deepEqual(jurisdictions, []);
});

test('DELETE /v1/box with bearer secret is forwarded; without it 401', async () => {
  const { call, seen } = boxSetup();
  const ok = await call('DELETE', '/v1/box', { headers: { authorization: `Bearer ${secret(1)}` }, origin: PAGES });
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get('access-control-allow-origin'), PAGES);
  assert.equal(seen[0].request.method, 'DELETE');
  assert.equal(new URL(seen[0].request.url).pathname, '/v1/box');
  assert.equal(seen[0].id, await objectName(secret(1)));
  const denied = await call('DELETE', '/v1/box');
  assert.equal(denied.status, 401);
  assert.equal(seen.length, 1);
});

test('wrong method on /v1/box/ws is 405 with Allow: GET', async () => {
  const { call, seen } = boxSetup();
  const response = await call('POST', '/v1/box/ws', { headers: { authorization: `Bearer ${secret(1)}` } });
  assert.equal(response.status, 405);
  assert.equal(response.headers.get('allow'), 'GET');
  assert.equal((await call('GET', '/v1/box')).status, 405);
  assert.deepEqual(seen, []);
});

test('box objects are chosen through jurisdiction("eu") only', async () => {
  const { ws, call, jurisdictions, direct } = boxSetup();
  await ws();
  await call('DELETE', '/v1/box', { headers: { authorization: `Bearer ${secret(2)}` } });
  assert.deepEqual(jurisdictions, ['eu', 'eu']);
  assert.equal(direct(), 0);
});

test('a throwing box is 500 without details and the box routes do not log', async () => {
  const logged = [];
  const originals = {};
  for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
    originals[level] = console[level];
    console[level] = (...args) => logged.push(args.join(' '));
  }
  try {
    const { ws } = boxSetup({}, () => { throw new Error(`kaputt ${secret(1)}`); });
    const response = await ws();
    assert.equal(response.status, 500);
    assert.deepEqual(await response.json(), { error: 'internal' });
  } finally {
    Object.assign(console, originals);
  }
  assert.deepEqual(logged, []);
});

test('wrangler.toml disables observability', async () => {
  const { readFile } = await import('node:fs/promises');
  const toml = await readFile(new URL('../wrangler.toml', import.meta.url), 'utf8');
  assert.match(toml, /\[observability\]\s*\nenabled = false/);
  assert.match(toml, /name = "BOX"\s*\nclass_name = "Box"/);
  assert.match(toml, /tag = "v2"\s*\nnew_sqlite_classes = \["Box"\]/);
});
