// pwa/scanner.js
// QR-Scan über die Kamera. Bevorzugt den `BarcodeDetector` des Browsers (Chrome auf Android); wo er
// fehlt oder keine QR-Codes liest (Firefox, Safari/iOS), liest der eigene Decoder (`qr-decode.js`)
// Bilder aus dem Video. Das Ergebnis läuft in beiden Fällen durch `parseQrText`: nur ein Koppel-Link
// mit privater IPv4-Adresse zählt.
import { parseQrText } from './pairing.js';
import { decodeQr } from './qr-decode.js';

/** Längste Kante eines Bildes für den eigenen Decoder: größer bringt nichts, kostet nur Zeit. */
export const MAX_FRAME_SIDE = 640;
/** Pause zwischen zwei Bildern (nach dem Dekodieren, nicht im festen Takt): etwa fünf Bilder je
 *  Sekunde, und die Oberfläche bleibt bedienbar, weil der Decoder auf dem Hauptthread läuft. */
export const FRAME_INTERVAL_MS = 200;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Die Umgebung, gegen die gescannt wird; Tests reichen eine eigene herein. */
const liveEnv = () => ({
  navigator: globalThis.navigator,
  document: globalThis.document,
  BarcodeDetector: globalThis.BarcodeDetector,
  wait: delay,
});

/** Welcher Weg gilt: `'detector'`, `'canvas'` (eigener Decoder) oder `null` (keine Kamera oder kein
 *  Canvas). Ob der Detector wirklich QR-Codes liest, weiß erst `scanForPairLink`; hier genügt, dass es
 *  mindestens einen Weg gibt. */
export function scanMethod(env = liveEnv()) {
  if (!env.navigator?.mediaDevices?.getUserMedia) return null;
  if (env.BarcodeDetector) return 'detector';
  return typeof env.document?.createElement === 'function' ? 'canvas' : null;
}

export const canScan = () => scanMethod() !== null;

/** Zielgröße für das Bild, das der Decoder bekommt: höchstens `max` Pixel an der langen Kante, nie
 *  vergrößert. `null`, solange das Video noch kein Bild hat. */
export function scaledSize(width, height, max = MAX_FRAME_SIDE) {
  if (!(width > 0) || !(height > 0)) return null;
  const factor = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * factor)), height: Math.max(1, Math.round(height * factor)) };
}

/** RGBA → Grauwerte (Rec. 601, ganzzahlig): `count` Pixel. */
export function toLuminance(rgba, count) {
  const out = new Uint8ClampedArray(count);
  for (let i = 0; i < count; i += 1) {
    out[i] = (77 * rgba[4 * i] + 150 * rgba[4 * i + 1] + 29 * rgba[4 * i + 2]) >> 8;
  }
  return out;
}

async function detectorReadsQr(env) {
  try {
    if (typeof env.BarcodeDetector.getSupportedFormats !== 'function') return true;   // ältere Chrome-Versionen
    return (await env.BarcodeDetector.getSupportedFormats()).includes('qr_code');
  } catch {
    return false;
  }
}

/** Liest Bilder aus `video`, bis ein Koppel-Link erkannt wird oder `signal` abbricht.
 *  Löst mit `{host, port, code}` auf, wirft bei fehlender Kamera oder Berechtigung. */
export async function scanForPairLink(video, signal, onStatus = () => {}, env = liveEnv()) {
  if (scanMethod(env) === null) throw new Error('no_scanner');
  const stream = await env.navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  });
  try {
    // Das Attribut `muted` setzt den Zustand nur beim Parsen; Safari spielt ein Video, das nicht
    // stumm und `playsinline` ist, nur im Vollbild oder gar nicht.
    video.muted = true;
    video.setAttribute('playsinline', '');
    video.srcObject = stream;
    await video.play();
    onStatus('Den QR-Code vom Desktop in das Bild halten.');
    const readFrame = await frameReader(video, env);
    while (!signal.aborted) {
      const text = await readFrame();
      if (text !== null) {
        const link = parseQrText(text);
        if (link) return link;
        onStatus('Das ist kein Koppel-Code dieser App.');
      }
      await env.wait(FRAME_INTERVAL_MS);
    }
    return null;
  } finally {
    for (const track of stream.getTracks()) track.stop();
    video.srcObject = null;
  }
}

/** Ein Leser, der bei jedem Aufruf den Text des ersten QR-Codes im aktuellen Bild liefert oder
 *  `null`. Der Detector, wenn er QR-Codes liest und sich bauen lässt, sonst der eigene Decoder. */
async function frameReader(video, env) {
  if (env.BarcodeDetector && await detectorReadsQr(env)) {
    try {
      const detector = new env.BarcodeDetector({ formats: ['qr_code'] });
      return async () => {
        const codes = await detector.detect(video);
        return codes.length > 0 ? codes[0].rawValue : null;
      };
    } catch {
      // Der Konstruktor kann auf Plattformen scheitern, die die Klasse nur vortäuschen.
    }
  }
  if (typeof env.document?.createElement !== 'function') throw new Error('no_scanner');
  const canvas = env.document.createElement('canvas');
  const context = canvas.getContext('2d', { willReadFrequently: true });
  return async () => {
    const size = scaledSize(video.videoWidth, video.videoHeight);
    if (size === null || video.readyState < 2) return null;
    canvas.width = size.width;
    canvas.height = size.height;
    context.drawImage(video, 0, 0, size.width, size.height);
    const { data } = context.getImageData(0, 0, size.width, size.height);
    return decodeQr(toLuminance(data, size.width * size.height), size.width, size.height);
  };
}
