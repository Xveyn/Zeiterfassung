// relay/scripts/gen-vapid.mjs
// Erzeugt das VAPID-Schlüsselpaar des Relays im Format, das `@block65/webcrypto-web-push` liest:
// öffentlich = Base64url der 65 Roh-Bytes, privat = Base64url von `d`. Direkt aufgerufen druckt es
// beide Werte; der private gehört nur als Secret in den Worker, nie ins Repository.
import { fileURLToPath } from 'node:url';

export async function generateVapid() {
  const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const jwk = await crypto.subtle.exportKey('jwk', pair.privateKey);
  const raw = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey));
  return { publicKey: Buffer.from(raw).toString('base64url'), privateKey: jwk.d };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { publicKey, privateKey } = await generateVapid();
  console.log(`VAPID_PUBLIC=${publicKey}\nVAPID_PRIVATE=${privateKey}`);
}
