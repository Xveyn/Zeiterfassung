// relay/src/box.js
// Das Durable Object einer Kopplung (Handy ↔ Desktop über den Relay): zwei ersetzbare Slots, `req`
// (schreibt das Handy) und `res` (schreibt der Desktop), je `{ver, data}`. Beide Seiten halten eine
// WebSocket über die Hibernation API; die Rolle ist das Tag am Socket. Die Nutzbytes sind opak:
// kein JSON, keine Kryptografie, kein Logging (s. Design „Budget“).
// Je `put` genau ein Schreibvorgang für den Slot; `idle` und Alarm höchstens einmal am Tag dazu.
import { encodeOk, encodeSlot, decodePut } from './frames.js';
import { InvalidRequest, LIMITS, parseHave, parseRole } from './validate.js';
import { socketPlatform } from './ws-platform.js';

const DAY_MS = 86_400_000;
const PROTOCOL = 'zeit.v1';
const SLOT = { phone: 'req', desktop: 'res' };
const PEER = { phone: 'desktop', desktop: 'phone' };

// Untergrenze für `ver`: Sekunden seit diesem Zeitpunkt. Das Aufräumen (Leerlauf, `DELETE /v1/box`) löscht
// die Slots samt Zähler, das Objekt (sha256 des Geheimnisses) und das `have` der Clients bleiben aber.
// Finge `ver` danach wieder bei 1 an, hielte ein Client mit `have = 40` jeden neuen Slot für bekannt und
// der Abgleich stünde still. Mit der Uhr als Untergrenze bleibt `ver` monoton, ohne dass eine Zeile das
// Aufräumen überlebt oder ein weiterer Schreibvorgang anfällt. Bis ca. 2094 unter 2^31 (Grenze von `have`).
const VER_EPOCH = Date.UTC(2026, 0, 1);

const MINUTE_MS = 60_000;

const json = (status, body) => Response.json(body, { status });

/** Schließt einen Socket, ohne zu werfen: er kann schon zu sein (ersetzt, vom Gegenüber geschlossen). */
function closeQuietly(ws, code, reason) {
  try {
    ws.close(code, reason);
  } catch {
    // schon geschlossen oder im Schließen: nichts zu tun
  }
}

/** Sendet, ohne zu werfen: ein Socket im Schließen darf den Schreibvorgang nicht scheitern lassen. */
function sendQuietly(ws, data) {
  try {
    ws.send(data);
  } catch {
    // das Gegenüber ist gerade weg; der Slot liegt gespeichert und kommt beim nächsten Verbinden
  }
}

export class Box {
  constructor(ctx, env, { now = Date.now, platform = socketPlatform } = {}) {
    this.ctx = ctx;
    this.env = env;
    this.now = now;
    this.platform = platform;
    // Put-Drossel je Socket: Token-Eimer `{tokens, at}`, Schlüssel ist das Socket-Objekt. Bewusst nur im
    // Speicher (kein Schreibvorgang): verliert ein Ruhezustand den Stand, beginnt der Eimer voll, und das
    // ist harmlos — wer in Drossel-Tempo sendet, hält das Objekt ohnehin wach. Ping/Pong beantwortet die
    // Plattform selbst, sie erreichen `webSocketMessage` nie und zählen nicht.
    this.buckets = new Map();
    // Heartbeat ohne Aufwecken: die Plattform beantwortet „ping“ selbst. In Node gibt es beides nicht.
    if (typeof WebSocketRequestResponsePair !== 'undefined' && typeof ctx.setWebSocketAutoResponse === 'function') {
      ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
    }
  }

  async fetch(request) {
    const url = new URL(request.url);
    try {
      if (url.pathname === '/v1/box/ws' && request.method === 'GET') return await this.#connect(request, url);
      if (url.pathname === '/v1/box' && request.method === 'DELETE') {
        await this.#wipe();
        return new Response(null, { status: 204 });
      }
      return json(404, { error: 'not_found' });
    } catch (error) {
      if (error instanceof InvalidRequest) return json(400, { error: 'invalid_request', message: error.message });
      throw error;
    }
  }

  async #connect(request, url) {
    if ((request.headers.get('upgrade') ?? '').toLowerCase() !== 'websocket') {
      return json(426, { error: 'upgrade_required' });
    }
    const role = parseRole(url.searchParams.get('role'));
    const have = parseHave(url.searchParams.get('have'));
    // Je Rolle höchstens eine Verbindung: erst die alte schließen, dann die neue annehmen.
    for (const old of this.ctx.getWebSockets(role)) {
      this.buckets.delete(old);
      closeQuietly(old, 1000, 'replaced');
    }
    const { client, server } = this.platform.open();
    this.ctx.acceptWebSocket(server, [role]);
    const slot = await this.ctx.storage.get(SLOT[PEER[role]]);
    if (slot && slot.ver > have) sendQuietly(server, encodeSlot(slot.ver, slot.data));
    return this.platform.upgrade(client, PROTOCOL);
  }

  async webSocketMessage(ws, message) {
    if (typeof message === 'string') {
      closeQuietly(ws, 1003, 'binary only');
      return;
    }
    // Die Länge zuerst: eine zu große Nachricht soll keinen Speicherzugriff kosten.
    if (message.byteLength > LIMITS.maxFrame) {
      closeQuietly(ws, 1009, 'too large');
      return;
    }
    const data = decodePut(message);
    if (data === null) return;                         // unbekannter Typ: still übergehen
    const role = this.ctx.getTags(ws).find((tag) => Object.hasOwn(SLOT, tag));
    if (!role) return;
    // Auch die Drossel vor jedem Speicherzugriff: ein `put` über dem Budget wird weder geschrieben noch zugestellt.
    if (!this.#spend(ws)) {
      this.buckets.delete(ws);
      closeQuietly(ws, 1008, 'too many');
      return;
    }
    const { storage } = this.ctx;
    const key = SLOT[role];
    const floor = Math.max(1, Math.floor((this.now() - VER_EPOCH) / 1000));
    const ver = Math.max(((await storage.get(key))?.ver ?? 0) + 1, floor);
    await storage.put(key, { ver, data });
    await this.#touch();
    sendQuietly(ws, encodeOk(ver));
    const frame = encodeSlot(ver, data);
    for (const peer of this.ctx.getWebSockets(PEER[role])) sendQuietly(peer, frame);
  }

  /** Ein Token aus dem Eimer des Sockets; der Eimer füllt sich laufend auf (`putsPerMinute` je Minute). */
  #spend(ws) {
    const now = this.now();
    const rate = LIMITS.putsPerMinute;
    const bucket = this.buckets.get(ws) ?? { tokens: rate, at: now };
    const tokens = Math.min(rate, bucket.tokens + ((now - bucket.at) * rate) / MINUTE_MS);
    if (tokens < 1) {
      this.buckets.set(ws, { tokens, at: now });
      return false;
    }
    this.buckets.set(ws, { tokens: tokens - 1, at: now });
    return true;
  }

  /** Die Plattform beantwortet das Schließen selbst; hier bleibt nichts zu tun außer, es nicht zu stören. */
  async webSocketClose(ws) {
    this.buckets.delete(ws);
    closeQuietly(ws, 1000, '');
  }

  async webSocketError(ws) {
    this.buckets.delete(ws);
    closeQuietly(ws, 1011, '');
  }

  /** Leerlauf-Frist und Alarm verschieben, aber höchstens einmal am Tag (jeder `setAlarm` ist ein
   *  Schreibvorgang im Kontingent). */
  async #touch() {
    const { storage } = this.ctx;
    const target = this.now() + LIMITS.idleDays * DAY_MS;
    const idle = await storage.get('idle');
    if ((await storage.getAlarm()) !== null && idle !== undefined && target - idle <= DAY_MS) return;
    await storage.put('idle', target);
    await storage.setAlarm(target);
  }

  async alarm() {
    const idle = (await this.ctx.storage.get('idle')) ?? 0;
    if (this.now() >= idle) {
      await this.#wipe();
      return;
    }
    await this.ctx.storage.setAlarm(idle);
  }

  async #wipe() {
    await this.ctx.storage.deleteAll();
    await this.ctx.storage.deleteAlarm();              // `deleteAll` lässt den Alarm stehen
    for (const ws of this.ctx.getWebSockets()) closeQuietly(ws, 1000, 'wiped');
    this.buckets.clear();
  }
}
