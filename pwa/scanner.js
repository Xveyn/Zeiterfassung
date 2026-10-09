// pwa/scanner.js
// QR-Scan über die Kamera (`BarcodeDetector`, nur wo vorhanden — Chrome auf Android). Wo er fehlt,
// bleibt die Kamera-App des Handys: sie öffnet den Link, dessen Fragment `app.js` ausliest.
import { parseQrText } from './pairing.js';

export const canScan = () => 'BarcodeDetector' in globalThis && Boolean(navigator.mediaDevices?.getUserMedia);

/** Liest Bilder aus `video`, bis ein Koppel-Link erkannt wird oder `signal` abbricht.
 *  Löst mit `{host, port, code}` auf, wirft bei fehlender Kamera-Berechtigung. */
export async function scanForPairLink(video, signal, onStatus = () => {}) {
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
  try {
    video.srcObject = stream;
    await video.play();
    onStatus('Den QR-Code vom Desktop in das Bild halten.');
    const detector = new globalThis.BarcodeDetector({ formats: ['qr_code'] });
    while (!signal.aborted) {
      const codes = await detector.detect(video);
      for (const code of codes) {
        const link = parseQrText(code.rawValue);
        if (link) return link;
        onStatus('Das ist kein Koppel-Code dieser App.');
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    return null;
  } finally {
    for (const track of stream.getTracks()) track.stop();
    video.srcObject = null;
  }
}
