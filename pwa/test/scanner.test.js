// pwa/test/scanner.test.js
// Der QR-Scan der Koppel-Seite: wann er angeboten wird, welcher Weg gilt (BarcodeDetector oder der
// eigene Decoder) und der Ablauf gegen eine gespielte Kamera.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { canScan, scaledSize, scanForPairLink, scanMethod, toLuminance } from '../scanner.js';
import { render } from './qr-render.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/qr-matrices.json', import.meta.url)));
const link = fixture.link.rows.map((row) => Array.from(row, (ch) => ch === '1'));
const PAIR = { host: '192.168.178.20', port: 17654, code: 'K7M29QXAK7M29QXAK7M29QXAK7M2' };

// --- Hilfsfunktionen ------------------------------------------------------------------------------

test('scaledSize shrinks to at most 640 px on the long side and never enlarges', () => {
  assert.deepEqual(scaledSize(1920, 1080), { width: 640, height: 360 });
  assert.deepEqual(scaledSize(1080, 1920), { width: 360, height: 640 });
  assert.deepEqual(scaledSize(640, 480), { width: 640, height: 480 });
  assert.deepEqual(scaledSize(320, 240), { width: 320, height: 240 });
  assert.deepEqual(scaledSize(100, 5000), { width: 13, height: 640 });
});

test('scaledSize refuses a video that has no picture yet', () => {
  for (const [w, h] of [[0, 0], [640, 0], [0, 480], [-1, 5], [NaN, 10], [undefined, undefined]]) {
    assert.equal(scaledSize(w, h), null, `${w}x${h}`);
  }
});

test('toLuminance turns RGBA pixels into grey values (Rec. 601, integers)', () => {
  const rgba = Uint8ClampedArray.from([255, 0, 0, 255, 0, 255, 0, 255, 255, 255, 255, 255, 0, 0, 0, 255]);
  assert.deepEqual([...toLuminance(rgba, 4)], [76, 149, 255, 0]);
});

// --- Wann der Scan angeboten wird -----------------------------------------------------------------

const camera = { mediaDevices: { getUserMedia: async () => ({}) } };
const documentWithCanvas = { createElement: () => ({}) };

test('scanMethod prefers the BarcodeDetector, falls back to the canvas decoder, and needs a camera', () => {
  assert.equal(scanMethod({ navigator: camera, document: documentWithCanvas, BarcodeDetector: class {} }), 'detector');
  assert.equal(scanMethod({ navigator: camera, document: documentWithCanvas }), 'canvas');
  assert.equal(scanMethod({ navigator: {}, document: documentWithCanvas, BarcodeDetector: class {} }), null);
  assert.equal(scanMethod({ navigator: camera }), null);
  assert.equal(scanMethod({}), null);
});

test('canScan is false here: no camera in Node', () => {
  assert.equal(canScan(), false);
});

// --- Ablauf gegen eine gespielte Kamera -----------------------------------------------------------

function grey(options) {
  const { luminance, width, height } = render(link, options);
  const data = new Uint8ClampedArray(width * height * 4);
  luminance.forEach((value, i) => { data[4 * i] = value; data[4 * i + 1] = value; data[4 * i + 2] = value; data[4 * i + 3] = 255; });
  return { data, width, height };
}

/** Eine Kamera, deren Bild `frames[n]` ist (das letzte bleibt stehen); `abort` bricht nach `frames` Bildern ab. */
function fakeCamera(frames, extra = {}) {
  const log = { stopped: 0, drawn: 0, constraints: null, played: 0 };
  const controller = new AbortController();
  const video = {
    srcObject: null, muted: false, readyState: 4, videoWidth: frames[0].width, videoHeight: frames[0].height,
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    async play() { log.played += 1; },
  };
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({
      drawImage: () => { log.drawn += 1; },
      getImageData: (_x, _y, w, h) => {
        const frame = frames[Math.min(log.drawn - 1, frames.length - 1)];
        // Der Canvas hat die Größe des skalierten Bilds; die Bilder der Tests sind schon klein genug.
        assert.equal(w, frame.width);
        assert.equal(h, frame.height);
        return { data: frame.data, width: w, height: h };
      },
    }),
  };
  const env = {
    navigator: { mediaDevices: { async getUserMedia(constraints) {
      log.constraints = constraints;
      return { getTracks: () => [{ stop: () => { log.stopped += 1; } }] };
    } } },
    document: { createElement: () => canvas },
    wait: async () => { if (log.drawn >= frames.length + (extra.extraFrames ?? 3)) controller.abort(); },
    ...extra.env,
  };
  return { video, env, log, signal: controller.signal };
}

test('scanForPairLink reads the link from camera frames with the own decoder', async () => {
  const frame = grey({ px: 5 });
  const { video, env, log, signal } = fakeCamera([frame]);
  const statuses = [];
  const result = await scanForPairLink(video, signal, (text) => statuses.push(text), env);
  assert.deepEqual(result, PAIR);
  assert.equal(log.stopped, 1, 'the camera is released');
  assert.equal(video.srcObject, null);
  assert.ok(statuses.length > 0);
});

test('scanForPairLink keeps looking through frames without a code, then finds it', async () => {
  const empty = { data: new Uint8ClampedArray(frameSize(grey({ px: 5 })) * 4).fill(200), ...sizeOf(grey({ px: 5 })) };
  const { video, env, log, signal } = fakeCamera([empty, empty, grey({ px: 5 })]);
  const result = await scanForPairLink(video, signal, () => {}, env);
  assert.deepEqual(result, PAIR);
  assert.ok(log.drawn >= 3);
});

function sizeOf({ width, height }) { return { width, height }; }
function frameSize({ width, height }) { return width * height; }

test('scanForPairLink makes the video muted and inline before it plays (iOS Safari)', async () => {
  const { video, env, signal } = fakeCamera([grey({ px: 5 })]);
  await scanForPairLink(video, signal, () => {}, env);
  assert.equal(video.muted, true);
  assert.equal(video.attributes.playsinline, '');
});

test('scanForPairLink asks for the rear camera', async () => {
  const { video, env, log, signal } = fakeCamera([grey({ px: 5 })]);
  await scanForPairLink(video, signal, () => {}, env);
  assert.equal(log.constraints.audio, false);
  assert.equal(log.constraints.video.facingMode, 'environment');
});

test('scanForPairLink reports a foreign QR code and goes on', async () => {
  const foreign = fixture.cases.find((item) => item.name === 'v2-M');
  const { luminance, width, height } = render(foreign.rows.map((row) => Array.from(row, (ch) => ch === '1')), { px: 5 });
  const data = new Uint8ClampedArray(width * height * 4);
  luminance.forEach((value, i) => { data[4 * i] = value; data[4 * i + 1] = value; data[4 * i + 2] = value; data[4 * i + 3] = 255; });
  const { video, env, signal } = fakeCamera([{ data, width, height }], { extraFrames: 2 });
  const statuses = [];
  const result = await scanForPairLink(video, signal, (text) => statuses.push(text), env);
  assert.equal(result, null);
  assert.ok(statuses.includes('Das ist kein Koppel-Code dieser App.'));
});

test('scanForPairLink returns null when aborted, and still releases the camera', async () => {
  const empty = { data: new Uint8ClampedArray(64 * 64 * 4).fill(255), width: 64, height: 64 };
  const { video, env, log, signal } = fakeCamera([empty]);
  assert.equal(await scanForPairLink(video, signal, () => {}, env), null);
  assert.equal(log.stopped, 1);
});

test('scanForPairLink uses the BarcodeDetector when it supports QR codes', async () => {
  const seen = [];
  class Detector {
    static async getSupportedFormats() { return ['qr_code', 'ean_13']; }
    async detect(source) { seen.push(source); return [{ rawValue: fixture.link.text }]; }
  }
  const { video, env, log, signal } = fakeCamera([grey({ px: 5 })], { env: { BarcodeDetector: Detector } });
  assert.deepEqual(await scanForPairLink(video, signal, () => {}, env), PAIR);
  assert.equal(seen[0], video);
  assert.equal(log.drawn, 0, 'the canvas path is not used');
});

test('scanForPairLink falls back to the own decoder when the BarcodeDetector cannot read QR codes', async () => {
  class Detector {
    static async getSupportedFormats() { return ['ean_13']; }
    async detect() { throw new Error('must not be called'); }
  }
  const { video, env, signal } = fakeCamera([grey({ px: 5 })], { env: { BarcodeDetector: Detector } });
  assert.deepEqual(await scanForPairLink(video, signal, () => {}, env), PAIR);
});

test('scanForPairLink falls back to the own decoder when the detector cannot be built', async () => {
  class Detector {
    constructor() { throw new Error('unsupported'); }
  }
  const { video, env, signal } = fakeCamera([grey({ px: 5 })], { env: { BarcodeDetector: Detector } });
  assert.deepEqual(await scanForPairLink(video, signal, () => {}, env), PAIR);
});

test('scanForPairLink throws without a camera and releases nothing', async () => {
  const { video, signal } = fakeCamera([grey({ px: 5 })]);
  const env = { navigator: {}, document: documentWithCanvas, wait: async () => {} };
  await assert.rejects(() => scanForPairLink(video, signal, () => {}, env));
});

test('scanForPairLink skips frames while the video has no picture yet', async () => {
  const { video, env, log, signal } = fakeCamera([grey({ px: 5 })]);
  let calls = 0;
  Object.defineProperty(video, 'videoWidth', { get() { calls += 1; return calls < 3 ? 0 : grey({ px: 5 }).width; } });
  assert.deepEqual(await scanForPairLink(video, signal, () => {}, env), PAIR);
  assert.ok(log.drawn >= 1);
});
