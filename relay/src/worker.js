// relay/src/worker.js
// Die Haustür: Routen, Auth und CORS. Das Geheimnis des Handys wählt das Durable Object (benannt nach
// seinem SHA-256), es gibt keine getrennte Geräte-ID. Alles Fachliche steckt in `device.js`.
// Kein Logging: weder Geheimnis noch Abo oder Zeitplan gehören in ein Log.
import { InvalidRequest, LIMITS, parseHave, parseRole, parseSecret, parseSubprotocol } from './validate.js';

export { Box } from './box.js';
export { Device } from './device.js';

const PAGES_ORIGIN = 'https://xveyn.github.io';
const ROUTES = { '/v1/device': ['PUT', 'DELETE'], '/v1/schedule': ['PUT'], '/v1/test': ['POST'],
  '/v1/box/ws': ['GET'], '/v1/box': ['DELETE'] };

/** SHA-256 des Geheimnisses als Hex: so wählt nie der Rohwert das Objekt. */
export async function objectName(secret) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(secret));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Liest den Body höchstens bis `LIMITS.maxBody` Bytes; `null`, wenn er größer ist. Ohne diese Grenze
 *  puffert `request.json()` im Durable Object beliebig viel. */
async function readBody(request) {
  const declared = Number(request.headers.get('content-length'));
  if (declared > LIMITS.maxBody) return null;
  if (!request.body) return '';
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > LIMITS.maxBody) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  return new TextDecoder().decode(await new Blob(chunks).arrayBuffer());
}

/** @param {Request} request @param {Env} env */
function corsHeaders(request, env) {
  const origin = request.headers.get('origin');
  const allowed = origin && (origin === PAGES_ORIGIN || (env.DEV_ORIGIN && origin === env.DEV_ORIGIN));
  return allowed ? { 'access-control-allow-origin': origin, vary: 'Origin' } : {};
}

/** @param {Request} request @param {Env} env */
function reply(request, env, status, body, extra = {}) {
  const headers = { ...corsHeaders(request, env), ...extra };
  return body === null ? new Response(null, { status, headers }) : Response.json(body, { status, headers });
}

/** Schlüssel des Limits: IPv4 ganz, IPv6 nur als /64 (so viel bekommt ein Anschluss meist, sonst
 *  umginge man das Limit mit wechselnden Adressen), IPv4-in-IPv6 als die IPv4-Adresse. */
export function limitKey(ip) {
  if (!ip) return 'unknown';
  const address = ip.toLowerCase();
  const mapped = address.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  if (mapped) return mapped[1];
  if (!address.includes(':')) return address;
  const [head, tail = ''] = address.split('::');
  const groups = (text) => (text ? text.split(':') : []);
  const front = groups(head);
  const back = address.includes('::') ? groups(tail) : [];
  const all = [...front, ...Array(Math.max(0, 8 - front.length - back.length)).fill('0'), ...back];
  return `${all.slice(0, 4).map((group) => group.replace(/^0+(?=.)/, '')).join(':')}::/64`;
}

/** Pro Absender-Adresse, nicht pro Geheimnis: wer beliebig viele Geheimnisse erfindet, soll nicht
 *  beliebig viele Objekte anlegen. Fehlt das Binding (lokale Entwicklung) oder wirft es, geht die
 *  Anfrage durch — ein ausgefallener Zähler darf den Relay nicht abschalten.
 *  @param {Request} request @param {Env} env */
async function withinLimit(request, env) {
  if (!env.LIMITER) return true;
  try {
    const { success } = await env.LIMITER.limit({ key: limitKey(request.headers.get('cf-connecting-ip')) });
    return success;
  } catch {
    return true;
  }
}

/** Das Objekt der Box: in Produktion nur über die EU-Jurisdiktion gewählt, nie direkt über
 *  `env.BOX.idFromName`. `BOX_JURISDICTION` = `none` gibt es nur für `wrangler dev` (lokales workerd kennt keine
 *  Jurisdiktionen); jeder andere Wert wirft und endet im 500 `internal`.
 *  @param {Env} env */
async function boxStub(env, secret) {
  const mode = env.BOX_JURISDICTION ?? 'eu';
  if (mode !== 'eu' && mode !== 'none') throw new Error('BOX_JURISDICTION ist ungültig.');
  const box = mode === 'eu' ? env.BOX.jurisdiction('eu') : env.BOX;
  return box.get(box.idFromName(await objectName(secret)));
}

/** Die Anfrage an die Box: kein Geheimnis, kein Body; nur Pfad, `upgrade` und die geprüfte Query. */
function boxRequest(request, path, role, have) {
  const url = new URL(path, request.url);
  if (role) url.searchParams.set('role', role);
  if (have) url.searchParams.set('have', String(have));
  const headers = path === '/v1/box/ws' ? { upgrade: 'websocket' } : {};
  return new Request(url, { method: request.method, headers });
}

/** `GET /v1/box/ws` (Upgrade) und `DELETE /v1/box`. Die 101-Antwort geht unverändert zurück: ein neu
 *  gebautes Response verlöre die WebSocket.
 *  @param {Request} request @param {Env} env */
async function boxRoute(request, env, pathname) {
  const socket = pathname === '/v1/box/ws';
  if (socket) {
    const origin = request.headers.get('origin');
    if (origin && !corsHeaders(request, env)['access-control-allow-origin']) {
      return reply(request, env, 403, { error: 'forbidden_origin' });
    }
  }
  let secret;
  try {
    secret = socket ? parseSubprotocol(request.headers.get('sec-websocket-protocol')) : parseSecret(request.headers.get('authorization'));
  } catch (error) {
    if (!(error instanceof InvalidRequest)) throw error;
    return reply(request, env, 401, { error: 'unauthorized' });
  }
  let role = null;
  let have = 0;
  if (socket) {
    if ((request.headers.get('upgrade') ?? '').toLowerCase() !== 'websocket') {
      return reply(request, env, 426, { error: 'upgrade_required' });
    }
    try {
      const query = new URL(request.url).searchParams;
      role = parseRole(query.get('role'));
      have = parseHave(query.get('have'));
    } catch (error) {
      if (!(error instanceof InvalidRequest)) throw error;
      return reply(request, env, 400, { error: 'invalid_request' });
    }
  }
  try {
    const answer = await (await boxStub(env, secret)).fetch(boxRequest(request, pathname, role, have));
    if (socket) return answer;
    const headers = new Headers(answer.headers);
    for (const [name, value] of Object.entries(corsHeaders(request, env))) headers.set(name, value);
    return new Response(answer.body, { status: answer.status, headers });
  } catch {
    // Bewusst ohne Details und ohne Log: die Ausnahme könnte das Geheimnis enthalten.
    return reply(request, env, 500, { error: 'internal' });
  }
}

export default {
  /** @param {Request} request @param {Env} env */
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    const methods = ROUTES[pathname];
    if (!methods) return reply(request, env, 404, { error: 'not_found' });

    if (request.method === 'OPTIONS') {
      const headers = corsHeaders(request, env);
      if (headers['access-control-allow-origin']) {
        Object.assign(headers, {
          'access-control-allow-methods': [...methods, 'OPTIONS'].join(', '),
          'access-control-allow-headers': 'authorization, content-type',
          'access-control-max-age': '86400',
        });
      }
      return new Response(null, { status: 204, headers });
    }
    if (!methods.includes(request.method)) {
      return reply(request, env, 405, { error: 'method_not_allowed' }, { allow: methods.join(', ') });
    }

    if (!(await withinLimit(request, env))) return reply(request, env, 429, { error: 'rate_limited' });

    if (pathname.startsWith('/v1/box')) return boxRoute(request, env, pathname);

    let secret;
    try {
      secret = parseSecret(request.headers.get('authorization'));
    } catch (error) {
      if (!(error instanceof InvalidRequest)) throw error;
      return reply(request, env, 401, { error: 'unauthorized' });
    }

    try {
      const text = await readBody(request);
      if (text === null) return reply(request, env, 413, { error: 'too_large' });
      const stub = env.DEVICE.get(env.DEVICE.idFromName(await objectName(secret)));
      // Das Geheimnis wählt nur das Objekt; es geht nicht weiter, auch nicht als Header.
      const forwarded = new Request(request.url, {
        method: request.method, headers: { 'content-type': 'application/json' },
        body: request.method === 'DELETE' ? undefined : text,
      });
      const answer = await stub.fetch(forwarded);
      const headers = new Headers(answer.headers);
      for (const [name, value] of Object.entries(corsHeaders(request, env))) headers.set(name, value);
      return new Response(answer.body, { status: answer.status, headers });
    } catch {
      // Bewusst ohne Details und ohne Log: die Ausnahme könnte das Geheimnis oder das Abo enthalten.
      return reply(request, env, 500, { error: 'internal' });
    }
  },
};
