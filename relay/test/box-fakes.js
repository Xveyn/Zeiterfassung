// relay/test/box-fakes.js
// Ersatz für WebSocket, DO-Kontext (Hibernation API) und `ws-platform.js` der Box. Node kennt weder
// `WebSocketPair` noch eine `Response` mit Status 101; die Fakes bilden nur ab, was `box.js` benutzt.
import { fakeStorage } from './fake-storage.js';

/** Ein Socket, der Gesendetes sammelt und sein Schließen festhält. Gesendet wird als Kopie. */
export function fakeSocket() {
  return {
    sent: [],
    closed: null,
    send(data) {
      if (this.closed) throw new Error('socket closed');
      this.sent.push(new Uint8Array(data));
    },
    close(code, reason) {
      if (this.closed) throw new Error('socket already closed');
      this.closed = [code, reason];
    },
  };
}

/** `ctx` mit Speicher und den WebSocket-Methoden der Hibernation API. Geschlossene Sockets liefert
 *  `getWebSockets` nicht mehr (die Plattform räumt sie aus der Liste). */
export function fakeContext() {
  const storage = fakeStorage();
  const sockets = [];
  return {
    storage,
    sockets,
    acceptWebSocket(ws, tags) { sockets.push({ ws, tags: [...tags] }); },
    getWebSockets(tag) {
      return sockets
        .filter((entry) => !entry.ws.closed && (tag === undefined || entry.tags.includes(tag)))
        .map((entry) => entry.ws);
    },
    getTags(ws) { return sockets.find((entry) => entry.ws === ws)?.tags ?? []; },
  };
}

export function fakePlatform() {
  return {
    open() { return { client: fakeSocket(), server: fakeSocket() }; },
    upgrade(client, protocol) { return { status: 101, protocol, client }; },
  };
}
