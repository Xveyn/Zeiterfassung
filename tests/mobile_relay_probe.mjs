// Hilfsskript für tests/test_mobile_relay_e2e.py: ein Handy der echten PWA-Logik (Store, SyncClient,
// RelayTransport, Codec) über den Relay-Abgleich. Die WebSocket ist eine Attrappe, die jedes `put` an den
// Python-Test weiterreicht: dort antwortet der echte RelayAdapter, und eine kleine Box-Attrappe entscheidet,
// was das Handy zugestellt bekommt.
//
// Zeilenprotokoll wie mobile_session_probe.mjs (je Zeile ein JSON-Objekt), dazu Rückfragen mitten im Befehl:
//   Python → Node   {cmd, ...}                          ein Befehl; Antwort ist {ok} oder {error}
//   Node → Python   {event: 'connect', have}            eine WebSocket wurde geöffnet
//                   {event: 'put', hex}                 das Handy legt eine Anfrage in die Box
//   Python → Node   {deliver: [{type, ver, hex?}], close: null | {code, reason}}
//                   die Antwort auf genau eine Rückfrage: was die Box dem Handy zustellt
// Befehle:
//   setup {timeoutMs}              Store und Client anlegen
//   pair {secret, code}            über den Relay koppeln          -> {desktopName} | {failed: {kind, code}}
//   save {date, slots}             Tag speichern
//   sync {}                        abgleichen                      -> {sent, received, ...} | {failed: ...}
//   state {}                       -> {seq, box_have, token, transport, pending}
import { createInterface } from 'node:readline';
import { Store } from '../pwa/store.js';
import { createMemoryAdapter } from '../pwa/memory-adapter.js';
import { SyncClient, SyncError } from '../pwa/sync.js';

// Eigene Warteschlange statt `for await`: mitten in einem Befehl wird zusätzlich auf Antworten gewartet, und
// die Reihenfolge der Leser muss die der Zeilen sein.
const queue = [];
const waiters = [];
const rl = createInterface({ input: process.stdin });
rl.on('line', (line) => {
  if (!line.trim()) return;
  const value = JSON.parse(line);
  const waiter = waiters.shift();
  if (waiter) waiter(value); else queue.push(value);
});
rl.on('close', () => { while (waiters.length) waiters.shift()(null); });
const nextLine = () => new Promise((resolve) => (queue.length ? resolve(queue.shift()) : waiters.push(resolve)));
const emit = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);
const ask = (event) => { emit({ event }); return nextLine(); };

const toHex = (bytes) => Buffer.from(bytes).toString('hex');
const fromHex = (hex) => new Uint8Array(Buffer.from(hex, 'hex'));

function boxMessage({ type, ver, hex }) {
  const payload = hex ? fromHex(hex) : new Uint8Array(0);
  const out = new Uint8Array(5 + payload.length);
  out[0] = { slot: 2, ok: 3 }[type];
  new DataView(out.buffer).setUint32(1, ver, false);
  out.set(payload, 5);
  return out.buffer;
}

function webSocketFactory(url) {
  const have = Number(new URL(url).searchParams.get('have') ?? 0);
  const listeners = {};
  let closed = false;
  const ws = {
    binaryType: '',
    addEventListener(type, fn) { (listeners[type] ??= []).push(fn); },
    // Wie eine echte WebSocket: nach `close()` kommt nichts mehr an (sonst rückte `have` über eine
    // Zustellung vor, die das Handy nie erlebt hätte).
    close() { closed = true; },
    fire(type, event = {}) { if (!closed) for (const fn of listeners[type] ?? []) fn(event); },
    play(reply) {
      for (const message of reply.deliver) ws.fire('message', { data: boxMessage(message) });
      if (reply.close) ws.fire('close', reply.close);
    },
    async send(data) {
      ws.play(await ask({ type: 'put', hex: toHex(data.subarray(1)) }));
    },
  };
  queueMicrotask(async () => {
    const reply = await ask({ type: 'connect', have });
    ws.fire('open');
    ws.play(reply);
  });
  return ws;
}

let store;
let client;

const failed = (error) => {
  if (error instanceof SyncError) return { failed: { kind: error.kind, code: error.code } };
  throw error;
};

function state() {
  const meta = store.getMeta();
  return { seq: meta.seq, box_have: meta.box_have, token: meta.token || '', transport: meta.transport,
    pending: store.pendingCount() };
}

const handlers = {
  async setup({ timeoutMs }) {
    store = new Store(createMemoryAdapter(), () => new Date());
    await store.load();
    client = new SyncClient({ store, webSocketFactory, timeoutMs, locks: null });
    return {};
  },
  async pair({ secret, code }) {
    try { return await client.pairRelay({ secret, code, deviceName: 'Pixel' }); } catch (error) { return failed(error); }
  },
  async save({ date, slots }) { await store.saveDay(date, slots); return state(); },
  async sync() {
    try { return await client.sync(); } catch (error) { return failed(error); }
  },
  async state() { return state(); },
};

for (;;) {
  const message = await nextLine();
  if (message === null) break;
  const { cmd, ...args } = message;
  try { emit({ ok: await handlers[cmd](args) }); } catch (error) { emit({ error: String(error.stack || error) }); }
}
