// pwa/test/qr-image.test.js
// Bild → Text: der Decoder gegen gerenderte und verschlechterte Matrizen aus `segno`.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { decodeQr } from '../qr-decode.js';
import { lcg, render } from './qr-render.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/qr-matrices.json', import.meta.url)));
const toMatrix = (rows) => rows.map((row) => Array.from(row, (ch) => ch === '1'));
const link = toMatrix(fixture.link.rows);
const LINK = fixture.link.text;

function decodeRendered(matrix, options) {
  const { luminance, width, height } = render(matrix, options);
  return decodeQr(luminance, width, height);
}

for (const px of [3, 4, 6, 10]) {
  test(`decodeQr reads the pairing link, upright, ${px} px per module`, () => {
    assert.equal(decodeRendered(link, { px }), LINK);
  });
}

for (const item of fixture.cases) {
  test(`decodeQr reads ${item.name} from a rendered image`, () => {
    assert.equal(decodeRendered(toMatrix(item.rows), { px: 4 }), item.text);
  });
}

for (const angle of [90, 180, 270, 17, 45, 133, -60, 300]) {
  test(`decodeQr reads the link rotated by ${angle} degrees`, () => {
    assert.equal(decodeRendered(link, { px: 5, angle }), LINK);
  });
}

const SKEWS = {
  'leaning right': [[0, 0], [0, 0], [3, 0], [3, 0]],
  'looking from below': [[2, 0], [-2, 0], [0, 0], [0, 0]],
  'one corner pulled': [[0, 0], [0, 0], [0, 0], [-3, 2]],
  'strong trapezoid': [[3, 1], [-3, 1], [0, -1], [0, -1]],
};
for (const [name, skew] of Object.entries(SKEWS)) {
  test(`decodeQr reads the link in perspective (${name})`, () => {
    assert.equal(decodeRendered(link, { px: 6, skew }), LINK);
    assert.equal(decodeRendered(link, { px: 6, skew, angle: 25 }), LINK);
  });
}

test('decodeQr reads a blurred link (radius 1, 5 px per module)', () => {
  assert.equal(decodeRendered(link, { px: 5, blur: 1 }), LINK);
});

test('decodeQr reads a noisy link', () => {
  for (const seed of [1, 2, 3]) assert.equal(decodeRendered(link, { px: 5, noise: 28, seed }), LINK, `seed ${seed}`);
});

test('decodeQr reads a link with a strong brightness gradient', () => {
  assert.equal(decodeRendered(link, { px: 5, gradient: 0.7 }), LINK);
  assert.equal(decodeRendered(link, { px: 5, gradient: 0.7, angle: 90 }), LINK);
});

test('decodeQr reads a link with little contrast', () => {
  assert.equal(decodeRendered(link, { px: 5, dark: 105, light: 150 }), LINK);
});

test('decodeQr reads a light-on-dark link (inverted)', () => {
  assert.equal(decodeRendered(link, { px: 5, invert: true }), LINK);
});

test('decodeQr reads a link photographed from a screen: rotation, perspective, blur, noise, gradient', () => {
  const random = lcg(7);
  for (let round = 0; round < 12; round += 1) {
    const options = {
      px: 5,
      angle: (random() - 0.5) * 50,
      skew: Array.from({ length: 4 }, () => [(random() - 0.5) * 3, (random() - 0.5) * 3]),
      blur: 1,
      noise: 10,
      gradient: 0.4,
      dark: 40,
      light: 215,
      seed: round + 1,
    };
    assert.equal(decodeRendered(link, options), LINK, JSON.stringify(options));
  }
});

test('decodeQr works with a large margin of unrelated background', () => {
  assert.equal(decodeRendered(link, { px: 4, margin: 150 }), LINK);
});

test('decodeQr returns null for an empty, a flat and a noisy image', () => {
  const width = 320;
  const height = 240;
  assert.equal(decodeQr(new Uint8ClampedArray(width * height), width, height), null);
  assert.equal(decodeQr(new Uint8ClampedArray(width * height).fill(255), width, height), null);
  const random = lcg(9);
  const noise = new Uint8ClampedArray(width * height).map(() => Math.floor(random() * 256));
  assert.equal(decodeQr(noise, width, height), null);
});

test('decodeQr returns null when a finder pattern is covered', () => {
  const covered = link.map((row) => [...row]);
  for (let y = 0; y < 9; y += 1) for (let x = 0; x < 9; x += 1) covered[y][x] = false;
  assert.equal(decodeRendered(covered, { px: 5 }), null);
});

test('decodeQr returns null for modes it does not read', () => {
  for (const item of fixture.unsupported) assert.equal(decodeRendered(toMatrix(item.rows), { px: 5 }), null, item.name);
});

test('decodeQr returns null for unusable arguments instead of throwing', () => {
  assert.equal(decodeQr(null, 10, 10), null);
  assert.equal(decodeQr(new Uint8ClampedArray(10), 10, 10), null);
  assert.equal(decodeQr(new Uint8ClampedArray(100), 0, 100), null);
  assert.equal(decodeQr(new Uint8ClampedArray(100), 10.5, 10), null);
  assert.equal(decodeQr(new Uint8ClampedArray(100), 10, 10), null);
  assert.equal(decodeQr(new Uint8ClampedArray(4), 2, 2), null);
});

test('decodeQr stays fast on a 640x480 frame of noise and of fine stripes', () => {
  const width = 640;
  const height = 480;
  const random = lcg(11);
  const noise = new Uint8ClampedArray(width * height).map(() => (random() < 0.5 ? 20 : 230));
  const stripes = new Uint8ClampedArray(width * height).map((_, i) => (((i % width) + Math.floor(i / width)) % 2 ? 20 : 230));
  const started = Date.now();
  assert.equal(decodeQr(noise, width, height), null);
  assert.equal(decodeQr(stripes, width, height), null);
  assert.ok(Date.now() - started < 4000, `took ${Date.now() - started} ms`);
});
