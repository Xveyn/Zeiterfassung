// pwa/push-scheduler.js
// Wann der Zeitplan der Erinnerungen an den Relay geht (#507), ohne Browser-API: sofort bei jedem Auslöser, nie zwei
// Sendungen zugleich, und kein Auslöser geht verloren. Eine eingetragene Zeit muss den Relay erreichen, bevor die
// Erinnerung fällig wird, auch wenn die App gleich danach geschlossen wird; deshalb gibt es keine Wartezeit vor dem Senden.

/** Abstände der Wiederholungen nach einem gescheiterten Senden; danach wartet der Planer auf den nächsten Auslöser. */
export const RETRY_DELAYS_MS = [5000, 30000, 120000];

/** `run()` sendet den aktuellen Stand und liefert `'retry'`, wenn es scheiterte (ein Wurf zählt genauso).
 *  - `request()`: jetzt senden. Läuft schon ein Senden, folgt danach genau eines mit dem dann aktuellen Stand.
 *  - `idle()`: erfüllt sich, sobald nichts mehr läuft oder ansteht; wirft nie.
 *  - `stop()`: endgültig (Trennen): nichts Anstehendes, keine Wiederholung, kein neuer Auslöser mehr. */
export function createPushScheduler({ run, setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = (timer) => clearTimeout(timer) }) {
  let running = null;
  let queued = false;
  let stopped = false;
  let timer = null;
  let failures = 0;

  const dropTimer = () => {
    if (timer === null) return;
    clearTimer(timer);
    timer = null;
  };

  const retryLater = () => {
    const delay = RETRY_DELAYS_MS[failures];
    failures += 1;
    if (delay === undefined) return;
    const handle = setTimer(() => {
      if (timer !== handle) return;                // inzwischen verworfen: ein alter Timer löst nichts mehr aus
      timer = null;
      kick();
    }, delay);
    timer = handle;
  };

  const loop = async () => {
    do {
      queued = false;
      let outcome;
      try {
        outcome = await run();
      } catch {
        outcome = 'retry';                         // der Aufrufer meldet seine Fehler selbst; hier zählt nur: nicht angekommen
      }
      if (stopped) return;
      if (outcome !== 'retry') failures = 0;
      else if (!queued) retryLater();
    } while (queued && !stopped);
  };

  function kick() {
    if (stopped) return;
    if (running !== null) { queued = true; return; }
    running = loop().finally(() => { running = null; });
  }

  return {
    request() {
      if (stopped) return;
      failures = 0;
      dropTimer();
      kick();
    },
    idle() {
      return running ?? Promise.resolve();
    },
    stop() {
      stopped = true;
      queued = false;
      dropTimer();
    },
  };
}
