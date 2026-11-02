// relay/scripts/box-smoke.mjs
// Ablauf-Test der Box gegen einen laufenden `npx wrangler dev --var BOX_JURISDICTION:none` (echtes workerd, nicht die Fakes der
// Unit-Tests). Aufruf: `node scripts/box-smoke.mjs [baseUrl]`, Standard http://127.0.0.1:8787.
// Reines Node >= 22 (globales WebSocket), keine Abhängigkeiten. Exit 1, sobald eine Prüfung fehlschlägt.
import { randomBytes } from 'node:crypto';
import http from 'node:http';
import https from 'node:https';

const base = (process.argv[2] ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const wsBase = base.replace(/^http/, 'ws');
const MAX_FRAME = 1_048_576;   // = LIMITS.maxFrame in src/validate.js: eine ganze Nachricht samt Typ-Byte
const WAIT_MS = 8000;
// Vom Server ausgelöstes Schließen (DELETE) braucht rund 10 s, bis der Client es sieht (in `wrangler dev` und auf dem deployten Relay beobachtet).
const SERVER_CLOSE_WAIT_MS = 20_000;

let failed = 0;
const sockets = [];
const check = (ok, text) => {
  if (!ok) failed += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${text}`);
};
const newSecret = () => randomBytes(32).toString('base64url');

/** Ein Socket mit Warteschlange der Nachrichten; `opened` löst bei der 101-Antwort auf. */
function connect(secret, role, have) {
  const query = `role=${role}${have === undefined ? '' : `&have=${have}`}`;
  const ws = new WebSocket(`${wsBase}/v1/box/ws?${query}`, ['zeit.v1', secret]);
  ws.binaryType = 'arraybuffer';
  sockets.push(ws);
  const inbox = [];
  const waiting = [];
  let closed = null;
  const closeWaiters = [];
  ws.addEventListener('message', (event) => {
    const data = new Uint8Array(event.data);
    const next = waiting.shift();
    if (next) next(data);
    else inbox.push(data);
  });
  ws.addEventListener('close', (event) => {
    closed = { code: event.code, reason: event.reason };
    for (const resolve of closeWaiters.splice(0)) resolve(closed);
  });
  const opened = new Promise((resolve, reject) => {
    ws.addEventListener('open', () => resolve(ws));
    ws.addEventListener('error', () => reject(new Error('Verbindung fehlgeschlagen')));
  });
  const timeout = (ms, what) => new Promise((_, reject) => setTimeout(() => reject(new Error(`Zeit abgelaufen: ${what}`)), ms));
  return {
    ws,
    opened,
    next: (what = 'Nachricht') => (inbox.length
      ? Promise.resolve(inbox.shift())
      : Promise.race([new Promise((resolve) => waiting.push(resolve)), timeout(WAIT_MS, what)])),
    closedWith: (ms = WAIT_MS) => (closed
      ? Promise.resolve(closed)
      : Promise.race([new Promise((resolve) => closeWaiters.push(resolve)), timeout(ms, 'Schließen')])),
    idle: (ms) => new Promise((resolve) => setTimeout(() => resolve(inbox.length === 0), ms)),
  };
}

const put = (payload) => {
  const frame = new Uint8Array(1 + payload.length);
  frame[0] = 0x01;
  frame.set(payload, 1);
  return frame;
};
const verOf = (frame) => new DataView(frame.buffer, frame.byteOffset).getUint32(1, false);

async function run(name, body) {
  try {
    await body();
  } catch (error) {
    check(false, `${name}: ${error.message}`);
  }
}

await run('(a)-(c) Zustellung und Wiederaufnahme', async () => {
  const secret = newSecret();
  const phone = connect(secret, 'phone');
  const desktop = connect(secret, 'desktop');
  await Promise.all([phone.opened, desktop.opened]);
  check(phone.ws.protocol === 'zeit.v1' && desktop.ws.protocol === 'zeit.v1',
    `(a) Handy und Desktop verbunden, Subprotocol ${phone.ws.protocol}`);

  const payload = new Uint8Array(MAX_FRAME - 1).fill(0x5a);        // mit Typ-Byte genau maxFrame
  phone.ws.send(put(payload));
  const [slot, ok] = await Promise.all([desktop.next('slot an den Desktop'), phone.next('ok ans Handy')]);
  const ver1 = verOf(ok);
  check(ok[0] === 0x03 && ok.length === 5 && ver1 >= 1, `(b) Handy erhält ok, ver ${ver1}`);
  check(slot[0] === 0x02 && verOf(slot) === ver1 && slot.length === 5 + payload.length
    && slot[5] === 0x5a && slot[slot.length - 1] === 0x5a,
    `(b) Desktop erhält slot ver ${verOf(slot)} mit ${slot.length - 5} Nutzbytes (1 MiB Nachricht)`);

  desktop.ws.close(1000, 'bye');
  await desktop.closedWith();
  phone.ws.send(put(new Uint8Array([1, 2, 3])));
  const ok2 = await phone.next('zweites ok');
  const ver2 = verOf(ok2);
  check(ver2 > ver1, `(c) zweites put erhält größere ver (${ver1} -> ${ver2})`);

  const again = connect(secret, 'desktop', ver1);
  await again.opened;
  const resumed = await again.next('slot nach have');
  check(resumed[0] === 0x02 && verOf(resumed) === ver2 && resumed.length === 8 && resumed[7] === 3,
    `(c) Desktop mit have=${ver1} erhält ver ${verOf(resumed)}`);

  const known = connect(secret, 'desktop', ver2);
  await known.opened;
  check(await known.idle(500), '(c) Desktop mit have=aktuell erhält nichts');
});

await run('(d) falsches Subprotocol', async () => {
  const bad = new WebSocket(`${wsBase}/v1/box/ws?role=phone`, ['zeit.v1', 'zu-kurz']);
  sockets.push(bad);
  const outcome = await new Promise((resolve) => {
    bad.addEventListener('open', () => resolve('open'));
    bad.addEventListener('error', () => resolve('error'));
    bad.addEventListener('close', () => resolve('close'));
  });
  check(outcome !== 'open', `(d) Verbindung mit ungültigem Geheimnis abgelehnt (${outcome})`);
  // `fetch` darf `Upgrade` nicht setzen, deshalb der rohe Upgrade-Versuch über node:http.
  const status = await new Promise((resolve, reject) => {
    const req = (base.startsWith('https') ? https : http).request(`${base}/v1/box/ws?role=phone`, {
      headers: { connection: 'Upgrade', upgrade: 'websocket', 'sec-websocket-version': '13',
        'sec-websocket-key': randomBytes(16).toString('base64'), 'sec-websocket-protocol': 'zeit.v1, zu-kurz' },
    }, (res) => { res.resume(); resolve(res.statusCode); });
    req.on('upgrade', (res, socket) => { socket.destroy(); resolve(res.statusCode); });
    req.on('error', reject);
    req.end();
  });
  check(status === 401, `(d) HTTP-Antwort 401 (war ${status})`);
});

await run('(e) zu große Nachricht', async () => {
  const phone = connect(newSecret(), 'phone');
  await phone.opened;
  const frame = new Uint8Array(MAX_FRAME + 1);                     // maxFrame + 1 ganze Nachricht
  frame[0] = 0x01;
  phone.ws.send(frame);
  const result = await phone.closedWith();
  check(result.code === 1009, `(e) maxFrame + 1 schließt mit ${result.code}`);
});

await run('(f) DELETE /v1/box', async () => {
  const secret = newSecret();
  const phone = connect(secret, 'phone');
  const desktop = connect(secret, 'desktop');
  await Promise.all([phone.opened, desktop.opened]);
  const answer = await fetch(`${base}/v1/box`, { method: 'DELETE', headers: { authorization: `Bearer ${secret}` } });
  check(answer.status === 204, `(f) DELETE antwortet ${answer.status}`);
  const started = Date.now();
  const [a, b] = await Promise.all([phone.closedWith(SERVER_CLOSE_WAIT_MS), desktop.closedWith(SERVER_CLOSE_WAIT_MS)]);
  check(a.code === 1000 && b.code === 1000,
    `(f) beide Verbindungen geschlossen (${a.code}, ${b.code}) nach ${Math.round((Date.now() - started) / 1000)} s`);
});

for (const ws of sockets) {
  try {
    ws.close();
  } catch {
    // schon zu
  }
}
console.log(failed === 0 ? 'Alle Prüfungen bestanden.' : `${failed} Prüfung(en) fehlgeschlagen.`);
process.exit(failed === 0 ? 0 : 1);
