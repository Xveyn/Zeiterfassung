// relay/src/device.js
// Das Durable Object eines Handys: Abo und Zeitplan liegen im Speicher, der Alarm steht immer auf dem
// nächsten fälligen Eintrag (sonst auf dem Leerlauf-Ablauf). Die Entscheidungen stecken in `validate.js`
// und `schedule.js`; hier wird nur gespeichert, gesendet und der Alarm gesetzt.
// Kein Logging: Abo, Blob und Zeitplan gehören nicht in ein Log.
import { TEST_PAYLOAD, sendPush } from './push.js';
import { afterFailure, idleAt, planAlarm } from './schedule.js';
import { InvalidRequest, LIMITS, parseSchedule, parseSubscription } from './validate.js';

const RETRY_AFTER_CRASH_MS = 30_000;
const MAX_CRASH_RETRIES = 5;

const json = (status, body) => Response.json(body, { status });
const empty = () => new Response(null, { status: 204 });

/** Nur HTTP-Status 100–599, `network` und `build` verlassen den Relay; alles andere (auch ein Ersatz-`send`)
 *  wird weggelassen, damit nie ein Endpoint oder Text in der Antwort landet. */
function publicCause(cause) {
  if (Number.isInteger(cause) && cause >= 100 && cause <= 599) return cause;
  return cause === 'network' || cause === 'build' ? cause : undefined;
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    throw new InvalidRequest('Der Body ist kein gültiges JSON.');
  }
}

/** Gespeicherter Wert. Der Speicher kennt die Form nicht (`unknown`), sie legt der Schreiber fest: `any` an
 *  dieser einen Stelle statt Zusicherungen an jedem Lesen. */
const read = (/** @type {DurableObjectStorage} */ storage, /** @type {string} */ key) =>
  /** @type {Promise<any>} */ (storage.get(key));

export class Device {
  /** @param {DurableObjectState} ctx @param {Env} env */
  constructor(ctx, env, { now = Date.now, send = (sub, blob, vars, report) => sendPush(sub, blob, vars, fetch, report) } = {}) {
    this.ctx = ctx;
    this.env = env;
    this.now = now;
    this.send = send;
    this.crashes = 0;
  }

  async fetch(request) {
    const { pathname } = new URL(request.url);
    try {
      if (pathname === '/v1/device' && request.method === 'PUT') return await this.#register(request);
      if (pathname === '/v1/schedule' && request.method === 'PUT') return await this.#replaceSchedule(request);
      if (pathname === '/v1/test' && request.method === 'POST') return await this.#test(request);
      if (pathname === '/v1/device' && request.method === 'DELETE') {
        await this.#wipe();
        return empty();
      }
      return json(404, { error: 'not_found' });
    } catch (error) {
      if (error instanceof InvalidRequest) return json(400, { error: 'invalid_request', message: error.message });
      throw error;
    }
  }

  async #register(request) {
    const subscription = parseSubscription(await readJson(request));
    const { storage } = this.ctx;
    await storage.put('sub', subscription);
    await storage.put('idle', idleAt(this.now()));
    await this.#arm((await read(storage, 'items')) ?? []);
    return empty();
  }

  async #replaceSchedule(request) {
    // Erst den Body lesen (auch für die 409-Antwort: ein ungelesener Body löst in workerd einen Fehler aus),
    // dann ohne weiteres Warten auf Netz oder Body prüfen und schreiben: nur Speicherzugriffe sind atomar.
    const items = parseSchedule(await readJson(request), this.now());
    const { storage } = this.ctx;
    if (!(await read(storage, 'sub'))) return json(409, { error: 'no_subscription' });
    await storage.put('items', items);
    await storage.put('idle', idleAt(this.now()));
    await this.#arm(items);
    return empty();
  }

  /** Sendet sofort die feste Test-Nutzlast, ohne Zeitplan und Alarm anzufassen. Je Gerät höchstens alle
   *  `testCooldownSeconds`: `lastTest` wird vor dem Senden gesetzt (während des Netzaufrufs laufen andere
   *  Anfragen weiter) und bei einem Fehlschlag zurückgenommen, damit ein misslungener Versuch nicht sperrt. */
  async #test(request) {
    await request.text().catch(() => '');           // ein Body ist unnötig; lesen, damit workerd nicht klagt
    const { storage } = this.ctx;
    const subscription = await read(storage, 'sub');
    if (!subscription) return json(409, { error: 'no_subscription' });
    const now = this.now();
    const previous = await read(storage, 'lastTest');
    if (previous !== undefined && now - previous < LIMITS.testCooldownSeconds * 1000) {
      return json(429, { error: 'too_soon' });
    }
    await storage.put('lastTest', now);
    let result;
    let cause;
    try {
      result = await this.send(subscription, TEST_PAYLOAD, this.env, (value) => { cause = value; });
    } catch {
      result = 'retry';
    }
    if (result === 'ok') return empty();
    const current = await read(storage, 'sub');
    if (result === 'gone' && current && current.endpoint === subscription.endpoint) {
      await this.#wipe();
      return json(410, { error: 'gone' });
    }
    if (previous === undefined) await storage.delete('lastTest'); else await storage.put('lastTest', previous);
    return result === 'gone' ? json(410, { error: 'gone' }) : json(502, publicCause(cause) === undefined ? { error: 'push_failed' } : { error: 'push_failed', cause });
  }

  /** Der Alarm steht auf „jetzt“, wenn schon etwas fällig ist, sonst auf dem nächsten Eintrag. */
  async #arm(items) {
    const { storage } = this.ctx;
    const now = this.now();
    const plan = planAlarm(items, now, await read(storage, 'idle'));
    await storage.setAlarm(plan.due.length > 0 ? now : plan.alarmAt);
  }

  async #wipe() {
    await this.ctx.storage.deleteAll();
    await this.ctx.storage.deleteAlarm();   // `deleteAll` lässt den Alarm stehen
  }

  /** Wirft nie: bei einer nicht abgefangenen Ausnahme begrenzt die Plattform die Wiederholungen auf 6. */
  async alarm() {
    try {
      await this.#run();
      this.crashes = 0;
    } catch {
      // Ein Speicherfehler darf die Erinnerungen nicht lautlos beenden: ein paar Mal neu anstoßen,
      // dann aufgeben (das Handy setzt beim nächsten Abgleich den Zeitplan ohnehin neu).
      this.crashes += 1;
      if (this.crashes > MAX_CRASH_RETRIES) return;
      try {
        await this.ctx.storage.setAlarm(this.now() + RETRY_AFTER_CRASH_MS);
      } catch {
        // auch das Setzen des Alarms scheitert: nichts mehr zu retten, die Plattform räumt später auf
      }
    }
  }

  async #run() {
    const { storage } = this.ctx;
    const start = this.now();
    const idle = (await read(storage, 'idle')) ?? 0;
    const subscription = await read(storage, 'sub');
    if (!subscription || start >= idle) {
      await this.#wipe();
      return;
    }
    const plan = planAlarm((await read(storage, 'items')) ?? [], start, idle);

    // Während des Sendens warten wir auf das Netz, und andere Anfragen (neuer Zeitplan, neues Abo, Löschen)
    // laufen dazwischen. Deshalb nur merken, was geschah, und danach gegen den aktuellen Stand anwenden.
    const sent = new Set();
    const retries = [];
    let gone = false;
    for (const item of plan.due) {
      let result;
      try {
        result = await this.send(subscription, item.blob, this.env);
      } catch {
        result = 'retry';      // `sendPush` wirft nie; ein Ersatz, der es tut, soll die übrigen nicht stoppen
      }
      sent.add(`${item.id}@${item.fireAt}`);
      if (result === 'gone') {
        gone = true;
        break;
      }
      if (result === 'retry') {
        const again = afterFailure(item, start);
        if (again) retries.push(again);
      }
    }

    const current = await read(storage, 'sub');
    if (!current) return;                       // zwischenzeitlich gelöscht: nichts wieder anlegen
    if (gone && current.endpoint === subscription.endpoint) {
      await this.#wipe();
      return;
    }
    if (gone) return;                           // das Abo wurde inzwischen erneuert; der alte Endpoint ist egal
    const stored = (await read(storage, 'items')) ?? [];
    const items = stored.filter((item) => !sent.has(`${item.id}@${item.fireAt}`));
    for (const again of retries) {
      if (!items.some((item) => item.id === again.id)) items.push(again);
    }
    const now = this.now();
    // Abgelaufene Einträge entfallen hier; was inzwischen fällig wurde (neuer Zeitplan), bleibt und klingelt gleich.
    const next = planAlarm(items, now, (await read(storage, 'idle')) ?? idle);
    await storage.put('items', [...next.due, ...next.keep]);
    await storage.setAlarm(next.due.length > 0 ? now : next.alarmAt);
  }
}
