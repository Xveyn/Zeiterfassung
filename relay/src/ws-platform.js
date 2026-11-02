// relay/src/ws-platform.js
// Die zwei Plattform-Aufrufe der Box, die Node nicht kennt (`WebSocketPair`, `Response` mit Status 101).
// Bewusst dünn: die Tests ersetzen sie durch `test/box-fakes.js`.
export const socketPlatform = {
  open() {
    const pair = new WebSocketPair();
    return { client: pair[0], server: pair[1] };
  },
  upgrade(client, protocol) {
    return new Response(null, { status: 101, webSocket: client, headers: { 'sec-websocket-protocol': protocol } });
  },
};
