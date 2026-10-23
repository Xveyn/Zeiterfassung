// pwa/test/qr-decode.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { correctBlock, decodeMatrix, functionPatternMask, readVersionInfo } from '../qr-decode.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/qr-matrices.json', import.meta.url)));
const toMatrix = (rows) => rows.map((row) => Array.from(row, (ch) => ch === '1'));

// Ein eigener, vom Decoder unabhängiger Encoder (Polynomdivision in GF(256), 0x11D): die Tests
// bekommen ihre Codewörter nicht aus dem Code, den sie prüfen.
function rsEncode(data, ecCount) {
  const exp = new Array(512).fill(0);
  const log = new Array(256).fill(0);
  let x = 1;
  for (let i = 0; i < 255; i += 1) {
    exp[i] = x; log[x] = i; x <<= 1;
    if (x & 256) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i += 1) exp[i] = exp[i - 255];
  const mul = (a, b) => (a === 0 || b === 0 ? 0 : exp[log[a] + log[b]]);
  let gen = [1];
  for (let i = 0; i < ecCount; i += 1) {
    const next = new Array(gen.length + 1).fill(0);
    gen.forEach((coef, j) => { next[j] ^= coef; next[j + 1] ^= mul(coef, exp[i]); });
    gen = next;
  }
  const rest = [...data, ...new Array(ecCount).fill(0)];
  for (let i = 0; i < data.length; i += 1) {
    const coef = rest[i];
    if (coef) for (let j = 1; j < gen.length; j += 1) rest[i + j] ^= mul(gen[j], coef);
  }
  return [...data, ...rest.slice(data.length)];
}

// Thonky „QR Code Tutorial“, „HELLO WORLD“ 1-M: 16 Datencodewörter und 10 EC-Wörter.
const HELLO_DATA = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17];
const HELLO_EC = [196, 35, 39, 119, 235, 215, 231, 226, 93, 23];

function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function corrupt(block, count, random) {
  const copy = [...block];
  const positions = new Set();
  while (positions.size < count) positions.add(Math.floor(random() * copy.length));
  for (const at of positions) copy[at] ^= 1 + Math.floor(random() * 255);
  return copy;
}

test('the test encoder reproduces the Thonky vector', () => {
  assert.deepEqual(rsEncode(HELLO_DATA, 10).slice(16), HELLO_EC);
});

test('correctBlock leaves a clean block alone', () => {
  const block = [...HELLO_DATA, ...HELLO_EC];
  assert.deepEqual(correctBlock(block, 10), block);
});

test('correctBlock repairs up to ec/2 damaged bytes (Thonky vector, 5 of 26)', () => {
  const block = [...HELLO_DATA, ...HELLO_EC];
  const random = lcg(1);
  for (let round = 0; round < 50; round += 1) {
    for (let count = 1; count <= 5; count += 1) {
      assert.deepEqual(correctBlock(corrupt(block, count, random), 10), block, `${count} bytes, round ${round}`);
    }
  }
});

test('correctBlock repairs 8 damaged bytes of a version-6-M block (43 data + 16 EC)', () => {
  const random = lcg(2);
  for (let round = 0; round < 50; round += 1) {
    const data = Array.from({ length: 43 }, () => Math.floor(random() * 256));
    const block = rsEncode(data, 16);
    for (const count of [1, 4, 8]) {
      assert.deepEqual(correctBlock(corrupt(block, count, random), 16), block, `${count} bytes, round ${round}`);
    }
  }
});

test('correctBlock gives up on 9 damaged bytes of a version-6-M block', () => {
  const random = lcg(3);
  for (let round = 0; round < 50; round += 1) {
    const data = Array.from({ length: 43 }, () => Math.floor(random() * 256));
    const block = rsEncode(data, 16);
    assert.equal(correctBlock(corrupt(block, 9, random), 16), null, `round ${round}`);
  }
});

test('correctBlock repairs damage in the EC part as well as in the data part', () => {
  const block = [...HELLO_DATA, ...HELLO_EC];
  const damaged = [...block];
  damaged[0] ^= 0xff; damaged[25] ^= 0x01; damaged[16] ^= 0x80;
  assert.deepEqual(correctBlock(damaged, 10), block);
});

test('correctBlock does not modify its input', () => {
  const damaged = [...HELLO_DATA, ...HELLO_EC];
  damaged[3] ^= 0x55;
  const before = [...damaged];
  correctBlock(damaged, 10);
  assert.deepEqual(damaged, before);
});

// ---------------------------------------------------------------------------------------
// Matrix → Text
// ---------------------------------------------------------------------------------------

// Datenmodule je Version laut ISO/IEC 18004 (Codewörter · 8 plus Restbits): sie prüfen die
// Funktionsmuster unabhängig von segno.
const RAW_DATA_MODULES = [0, 208, 359, 567, 807, 1079, 1383, 1568, 1936, 2336, 2768];

for (let version = 1; version <= 10; version += 1) {
  test(`functionPatternMask leaves ${RAW_DATA_MODULES[version]} data modules in version ${version}`, () => {
    const mask = functionPatternMask(version);
    assert.equal(mask.length, 17 + 4 * version);
    const free = mask.flat().filter((isFunction) => !isFunction).length;
    assert.equal(free, RAW_DATA_MODULES[version]);
  });
}

for (const item of fixture.cases) {
  test(`decodeMatrix reads ${item.name} (mask ${item.mask})`, () => {
    assert.equal(decodeMatrix(toMatrix(item.rows)), item.text);
  });
}

test('the fixtures cover every version, EC level and mask', () => {
  const seen = new Set(fixture.cases.map((item) => `${item.version}${item.ec}`));
  assert.equal(seen.size, 40);
  assert.deepEqual([...new Set(fixture.cases.map((item) => item.mask))].sort(), [0, 1, 2, 3, 4, 5, 6, 7]);
});

test('decodeMatrix reads the real pairing link (version 6, 93 characters)', () => {
  assert.equal(fixture.link.text.length, 93);
  assert.equal(decodeMatrix(toMatrix(fixture.link.rows)), fixture.link.text);
});

for (const item of fixture.unsupported) {
  test(`decodeMatrix refuses ${item.name} mode`, () => {
    assert.equal(decodeMatrix(toMatrix(item.rows)), null);
  });
}

test('decodeMatrix refuses matrices of the wrong size', () => {
  for (const size of [0, 1, 20, 22, 25, 26, 61, 81, 177]) {
    assert.equal(decodeMatrix(Array.from({ length: size }, () => new Array(size).fill(false))), null, String(size));
  }
  assert.equal(decodeMatrix(null), null);
  assert.equal(decodeMatrix([[true, false], [false]]), null);
});

test('decodeMatrix refuses an empty and a full matrix', () => {
  const blank = Array.from({ length: 41 }, () => new Array(41).fill(false));
  const full = Array.from({ length: 41 }, () => new Array(41).fill(true));
  assert.equal(decodeMatrix(blank), null);
  assert.equal(decodeMatrix(full), null);
});

test('decodeMatrix survives 3 flipped bits in one copy of the format information', () => {
  const matrix = toMatrix(fixture.link.rows);
  for (const column of [0, 1, 2]) matrix[8][column] = !matrix[8][column];
  assert.equal(decodeMatrix(matrix), fixture.link.text);
});

test('decodeMatrix uses the second copy when the first format copy is destroyed', () => {
  const matrix = toMatrix(fixture.link.rows);
  for (let column = 0; column < 9; column += 1) if (column !== 6) matrix[8][column] = column % 2 === 0;
  for (let row = 0; row < 9; row += 1) if (row !== 6) matrix[row][8] = row % 3 === 0;
  assert.equal(decodeMatrix(matrix), fixture.link.text);
});

test('decodeMatrix uses the first copy when the second format copy is destroyed', () => {
  const matrix = toMatrix(fixture.link.rows);
  const size = matrix.length;
  for (let row = size - 7; row < size; row += 1) matrix[row][8] = !matrix[row][8];
  for (let column = size - 8; column < size; column += 1) matrix[8][column] = !matrix[8][column];
  assert.equal(decodeMatrix(matrix), fixture.link.text);
});

test('decodeMatrix refuses when both format copies are beyond repair', () => {
  const matrix = toMatrix(fixture.link.rows);
  const size = matrix.length;
  for (const column of [0, 1, 2, 3, 4]) matrix[8][column] = !matrix[8][column];
  for (const column of [size - 1, size - 2, size - 3, size - 4, size - 5]) matrix[8][column] = !matrix[8][column];
  assert.equal(decodeMatrix(matrix), null);
});

function flipDataModules(matrix, count, random) {
  const mask = functionPatternMask((matrix.length - 17) / 4);
  const free = [];
  matrix.forEach((row, y) => row.forEach((_, x) => { if (!mask[y][x]) free.push([y, x]); }));
  const copy = matrix.map((row) => [...row]);
  const picked = new Set();
  while (picked.size < count) picked.add(Math.floor(random() * free.length));
  for (const index of picked) { const [y, x] = free[index]; copy[y][x] = !copy[y][x]; }
  return copy;
}

test('decodeMatrix corrects scattered damage in the data area (link, EC M)', () => {
  const random = lcg(4);
  for (let round = 0; round < 40; round += 1) {
    const damaged = flipDataModules(toMatrix(fixture.link.rows), 12, random);
    assert.equal(decodeMatrix(damaged), fixture.link.text, `round ${round}`);
  }
});

test('decodeMatrix corrects a burst of damage inside the error correction budget (v10-Q)', () => {
  const item = fixture.cases.find((entry) => entry.name === 'v10-Q');
  const matrix = toMatrix(item.rows);
  // Ein Block mit weniger als ec/2 beschädigten Wörtern: wenige verstreute Module genügen.
  const damaged = flipDataModules(matrix, 20, lcg(5));
  assert.equal(decodeMatrix(damaged), item.text);
});

test('decodeMatrix gives up when too much of the data area is damaged', () => {
  const damaged = flipDataModules(toMatrix(fixture.link.rows), 700, lcg(6));
  assert.equal(decodeMatrix(damaged), null);
});

test('readVersionInfo returns the version of every symbol from 7 on, and null below', () => {
  for (const item of fixture.cases) {
    const expected = item.version >= 7 ? item.version : null;
    assert.equal(readVersionInfo(toMatrix(item.rows)), expected, item.name);
  }
});

test('readVersionInfo survives 3 flipped bits in one copy', () => {
  const item = fixture.cases.find((entry) => entry.name === 'v8-M');
  const matrix = toMatrix(item.rows);
  const size = matrix.length;
  for (const [row, column] of [[0, size - 11], [1, size - 10], [2, size - 9]]) matrix[row][column] = !matrix[row][column];
  assert.equal(readVersionInfo(matrix), 8);
});
