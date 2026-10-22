// relay/src/worker.js
// Die Haustür: Routen, Auth und CORS. Das Geheimnis des Handys wählt das Durable Object (benannt nach
// seinem SHA-256), es gibt keine getrennte Geräte-ID. Alles Fachliche steckt in `device.js`.
// Kein Logging: weder Geheimnis noch Abo oder Zeitplan gehören in ein Log.
import { InvalidRequest, LIMITS, parseSecret } from './validate.js';

export { Device } from './device.js';

const PAGES_ORIGIN = 'https://xveyn.github.io';
const ROUTES = { '/v1/device': ['PUT', 'DELETE'], '/v1/schedule': ['PUT'] };

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

function corsHeaders(request, env) {
  const origin = request.headers.get('origin');
  const allowed = origin && (origin === PAGES_ORIGIN || (env.DEV_ORIGIN && origin === env.DEV_ORIGIN));
  return allowed ? { 'access-control-allow-origin': origin, vary: 'Origin' } : {};
}

function reply(request, env, status, body, extra = {}) {
  const headers = { ...corsHeaders(request, env), ...extra };
  return body === null ? new Response(null, { status, headers }) : Response.json(body, { status, headers });
}

/** Pro Absender-Adresse, nicht pro Geheimnis: wer beliebig viele Geheimnisse erfindet, soll nicht
 *  beliebig viele Objekte anlegen. Fehlt das Binding (lokale Entwicklung) oder wirft es, geht die
 *  Anfrage durch — ein ausgefallener Zähler darf den Relay nicht abschalten. */
async function withinLimit(request, env) {
  if (!env.LIMITER) return true;
  try {
    const { success } = await env.LIMITER.limit({ key: request.headers.get('cf-connecting-ip') ?? 'unknown' });
    return success;
  } catch {
    return true;
  }
}

export default {
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
