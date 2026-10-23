// pwa/qr-decode.js
// QR-Decoder in reinem JavaScript (#326): Luminanz-Bild rein, Text oder `null` raus. Ohne DOM,
// ohne Abhängigkeiten, ohne Build. Er ersetzt `BarcodeDetector` dort, wo es ihn nicht gibt
// (Firefox, Safari/iOS). Umfang: QR Model 2, Versionen 1–10, alle EC-Stufen, alle Masken, nur
// Byte-Modus. Alles andere liefert `null` — das Bild ist ein Kamerabild, kein Vertrag.
//
// Aus der Spezifikation geschrieben, kein Fremdcode übernommen. Algorithmen und Konstanten
// stammen aus ISO/IEC 18004 und den Beschreibungen in ZXing und jsQR (Apache-2.0) sowie dem
// Thonky-Tutorial; die Tabellen sind gegen `segno` (den Encoder des Desktops) geprüft.

// ---------------------------------------------------------------------------------------
// GF(256), Primitivpolynom x^8 + x^4 + x^3 + x^2 + 1 (0x11D), Erzeuger α = 2.
// ---------------------------------------------------------------------------------------
const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
{
  let value = 1;
  for (let i = 0; i < 255; i += 1) {
    EXP[i] = value;
    LOG[value] = i;
    value <<= 1;
    if (value & 0x100) value ^= 0x11d;
  }
  for (let i = 255; i < 512; i += 1) EXP[i] = EXP[i - 255];
}

const gfMul = (a, b) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]]);
const gfInv = (a) => EXP[255 - LOG[a]];
const gfPow = (exponent) => EXP[((exponent % 255) + 255) % 255];

// Polynome als Arrays, niedrigster Grad zuerst: `p[i]` ist der Koeffizient von x^i.
const degreeOf = (p) => {
  for (let i = p.length - 1; i >= 0; i -= 1) if (p[i] !== 0) return i;
  return -1;
};

function polyEval(p, x) {
  let result = 0;
  for (let i = p.length - 1; i >= 0; i -= 1) result = gfMul(result, x) ^ p[i];
  return result;
}

function polyMul(a, b) {
  const out = new Array(a.length + b.length - 1).fill(0);
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] === 0) continue;
    for (let j = 0; j < b.length; j += 1) out[i + j] ^= gfMul(a[i], b[j]);
  }
  return out;
}

function polyAdd(a, b) {
  const out = new Array(Math.max(a.length, b.length)).fill(0);
  for (let i = 0; i < a.length; i += 1) out[i] ^= a[i];
  for (let i = 0; i < b.length; i += 1) out[i] ^= b[i];
  return out;
}

// ---------------------------------------------------------------------------------------
// Reed-Solomon: Syndrome, Euklid (σ und ω), Chien-Suche, Forney. Erste Wurzel α^0.
// ---------------------------------------------------------------------------------------

/** Korrigiert einen Block (Daten, dann EC-Wörter; `ecCount` EC-Wörter) und liefert eine Kopie
 *  mit den korrigierten Werten — oder `null`, wenn mehr als `ecCount / 2` Wörter beschädigt sind
 *  oder die Korrektur nicht aufgeht. Das Ergebnis wird immer gegen die Syndrome gegengeprüft. */
export function correctBlock(block, ecCount) {
  const length = block.length;
  const received = Array.from(block);
  // Das erste Wort ist der höchste Grad: r(x) = c[0]·x^(n-1) + … + c[n-1].
  const syndromes = new Array(ecCount).fill(0);
  let clean = true;
  for (let i = 0; i < ecCount; i += 1) {
    const root = gfPow(i);
    let sum = 0;
    for (let j = 0; j < length; j += 1) sum = gfMul(sum, root) ^ received[j];
    syndromes[i] = sum;
    if (sum !== 0) clean = false;
  }
  if (clean) return received;

  const locator = runEuclid(syndromes, ecCount);
  if (locator === null) return null;
  const { sigma, omega } = locator;

  const errorCount = degreeOf(sigma);
  const positions = [];
  for (let index = 0; index < length; index += 1) {
    // Fehlerort X = α^(n-1-index); gesucht sind die Nullstellen von σ bei X^-1.
    if (polyEval(sigma, gfPow(-(length - 1 - index))) === 0) positions.push(index);
  }
  if (positions.length !== errorCount) return null;

  // σ' (formale Ableitung): in Charakteristik 2 bleiben nur die ungeraden Grade.
  const derivative = sigma.map((coef, i) => (i % 2 === 1 ? coef : 0)).slice(1);
  for (const index of positions) {
    const x = gfPow(length - 1 - index);
    const xInv = gfInv(x);
    const denominator = polyEval(derivative, xInv);
    if (denominator === 0) return null;
    // Wurzelbasis b = 0: Fehlerwert e = X · ω(X^-1) / σ'(X^-1)
    received[index] ^= gfMul(x, gfMul(polyEval(omega, xInv), gfInv(denominator)));
  }

  for (let i = 0; i < ecCount; i += 1) {
    const root = gfPow(i);
    let sum = 0;
    for (let j = 0; j < length; j += 1) sum = gfMul(sum, root) ^ received[j];
    if (sum !== 0) return null;
  }
  return received;
}

/** Erweiterter euklidischer Algorithmus auf x^ecCount und dem Syndrompolynom, bis der Grad des
 *  Rests unter ecCount/2 fällt. Liefert σ (Fehlerortpolynom) und ω (Fehlerwertpolynom), beide
 *  durch σ(0) normiert, oder `null`. */
function runEuclid(syndromes, ecCount) {
  let rLast = new Array(ecCount + 1).fill(0);
  rLast[ecCount] = 1;
  let r = Array.from(syndromes);
  let tLast = [0];
  let t = [1];

  while (2 * degreeOf(r) >= ecCount) {
    const rLastLast = rLast;
    const tLastLast = tLast;
    rLast = r;
    tLast = t;
    if (degreeOf(rLast) < 0) return null;
    r = rLastLast;
    let quotient = [0];
    const leadInverse = gfInv(rLast[degreeOf(rLast)]);
    while (degreeOf(r) >= degreeOf(rLast) && degreeOf(r) >= 0) {
      const shift = degreeOf(r) - degreeOf(rLast);
      const scale = gfMul(r[degreeOf(r)], leadInverse);
      const monomial = new Array(shift + 1).fill(0);
      monomial[shift] = scale;
      quotient = polyAdd(quotient, monomial);
      r = polyAdd(r, polyMul(rLast, monomial));
    }
    t = polyAdd(polyMul(quotient, tLast), tLastLast);
    if (degreeOf(r) >= degreeOf(rLast)) return null;
  }

  const atZero = t[0];
  if (atZero === 0) return null;
  const inverse = gfInv(atZero);
  return {
    sigma: t.map((coef) => gfMul(coef, inverse)),
    omega: r.map((coef) => gfMul(coef, inverse)),
  };
}

// ---------------------------------------------------------------------------------------
// Tabellen (Versionen 1–10). Quelle: ISO/IEC 18004, Tabellen 9 und E.1; Thonky „Error Correction
// Code Words and Block Information“. Gegengeprüft gegen `segno` (`consts.ECC`, `ALIGNMENT_POS`).
// ---------------------------------------------------------------------------------------

// Je Version und EC-Stufe [L, M, Q, H]: [EC-Wörter je Block, Blöcke Gruppe 1, Daten je Block
// Gruppe 1, Blöcke Gruppe 2, Daten je Block Gruppe 2]. Gruppe 2 hat ein Datenwort mehr.
const EC_TABLE = [
  null,
  [[7, 1, 19, 0, 0], [10, 1, 16, 0, 0], [13, 1, 13, 0, 0], [17, 1, 9, 0, 0]],
  [[10, 1, 34, 0, 0], [16, 1, 28, 0, 0], [22, 1, 22, 0, 0], [28, 1, 16, 0, 0]],
  [[15, 1, 55, 0, 0], [26, 1, 44, 0, 0], [18, 2, 17, 0, 0], [22, 2, 13, 0, 0]],
  [[20, 1, 80, 0, 0], [18, 2, 32, 0, 0], [26, 2, 24, 0, 0], [16, 4, 9, 0, 0]],
  [[26, 1, 108, 0, 0], [24, 2, 43, 0, 0], [18, 2, 15, 2, 16], [22, 2, 11, 2, 12]],
  [[18, 2, 68, 0, 0], [16, 4, 27, 0, 0], [24, 4, 19, 0, 0], [28, 4, 15, 0, 0]],
  [[20, 2, 78, 0, 0], [18, 4, 31, 0, 0], [18, 2, 14, 4, 15], [26, 4, 13, 1, 14]],
  [[24, 2, 97, 0, 0], [22, 2, 38, 2, 39], [22, 4, 18, 2, 19], [26, 4, 14, 2, 15]],
  [[30, 2, 116, 0, 0], [22, 3, 36, 2, 37], [20, 4, 16, 4, 17], [24, 4, 12, 4, 13]],
  [[18, 2, 68, 2, 69], [26, 4, 43, 1, 44], [24, 6, 19, 2, 20], [28, 6, 15, 2, 16]],
];

// Mittelpunkte der Alignment-Muster je Version (Zeilen und Spalten).
const ALIGNMENT_CENTERS = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34],
  [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];

// Die zwei Formatbits der EC-Stufe → Index in `EC_TABLE`: L = 01, M = 00, Q = 11, H = 10.
const EC_LEVEL_FROM_BITS = [1, 0, 3, 2];

const MIN_VERSION = 1;
const MAX_VERSION = 10;

const sizeOfVersion = (version) => 17 + 4 * version;
const popCount = (value) => {
  let count = 0;
  for (let rest = value; rest; rest &= rest - 1) count += 1;
  return count;
};

// ---------------------------------------------------------------------------------------
// Format- und Versionsinformation (BCH)
// ---------------------------------------------------------------------------------------

function bchRemainder(value, generator, generatorBits) {
  let rest = value;
  for (let bit = 31 - Math.clz32(rest); bit >= generatorBits - 1; bit -= 1) {
    if ((rest >> bit) & 1) rest ^= generator << (bit - (generatorBits - 1));
  }
  return rest;
}

// 32 gültige Formatwörter: 5 Datenbits (EC-Stufe · 8 + Maske), BCH(15,5) mit 0x537, XOR 0x5412.
const FORMAT_WORDS = Array.from({ length: 32 }, (_, data) => {
  const shifted = data << 10;
  return { data, word: (shifted | (data === 0 ? 0 : bchRemainder(shifted, 0x537, 11))) ^ 0x5412 };
});

// Gültige Versionswörter 7..10: 6 Datenbits, BCH(18,6) mit 0x1F25.
const VERSION_WORDS = [];
for (let version = 7; version <= MAX_VERSION; version += 1) {
  const shifted = version << 12;
  VERSION_WORDS.push({ version, word: shifted | bchRemainder(shifted, 0x1f25, 13) });
}

const nearest = (candidates, observed, maxDistance) => {
  let best = null;
  let bestDistance = maxDistance + 1;
  for (const candidate of candidates) {
    const distance = popCount(candidate.word ^ observed);
    if (distance < bestDistance) { best = candidate; bestDistance = distance; }
  }
  return best === null ? null : { candidate: best, distance: bestDistance };
};

/** `{ecLevel, mask}` (ecLevel = Index in `EC_TABLE`) aus der besseren der beiden Kopien der
 *  Formatinformation, bis Hamming-Abstand 3; sonst `null`. */
function readFormatInfo(matrix, size) {
  const bit = (x, y) => (matrix[y][x] ? 1 : 0);
  let first = 0;
  for (let x = 0; x <= 5; x += 1) first = (first << 1) | bit(x, 8);
  first = (first << 1) | bit(7, 8);
  first = (first << 1) | bit(8, 8);
  first = (first << 1) | bit(8, 7);
  for (let y = 5; y >= 0; y -= 1) first = (first << 1) | bit(8, y);
  let second = 0;
  for (let y = size - 1; y >= size - 7; y -= 1) second = (second << 1) | bit(8, y);
  for (let x = size - 8; x <= size - 1; x += 1) second = (second << 1) | bit(x, 8);

  const a = nearest(FORMAT_WORDS, first, 3);
  const b = nearest(FORMAT_WORDS, second, 3);
  const best = a !== null && (b === null || a.distance <= b.distance) ? a : b;
  if (best === null) return null;
  const { data } = best.candidate;
  return { ecLevel: EC_LEVEL_FROM_BITS[data >> 3], mask: data & 7 };
}

/** Die Version aus der Versionsinformation (ab Version 7, zwei Kopien, bis Abstand 3), sonst
 *  `null` — auch unter Version 7, wo es keine gibt. */
export function readVersionInfo(matrix) {
  const size = Array.isArray(matrix) ? matrix.length : 0;
  if (size < sizeOfVersion(7)) return null;
  const bit = (x, y) => (matrix[y][x] ? 1 : 0);
  let fromTopRight = 0;
  for (let y = 5; y >= 0; y -= 1) {
    for (let x = size - 9; x >= size - 11; x -= 1) fromTopRight = (fromTopRight << 1) | bit(x, y);
  }
  let fromBottomLeft = 0;
  for (let x = 5; x >= 0; x -= 1) {
    for (let y = size - 9; y >= size - 11; y -= 1) fromBottomLeft = (fromBottomLeft << 1) | bit(x, y);
  }
  const a = nearest(VERSION_WORDS, fromTopRight, 3);
  const b = nearest(VERSION_WORDS, fromBottomLeft, 3);
  const best = a !== null && (b === null || a.distance <= b.distance) ? a : b;
  return best === null ? null : best.candidate.version;
}

// ---------------------------------------------------------------------------------------
// Funktionsmuster, Maske, Auslesen der Codewörter
// ---------------------------------------------------------------------------------------

/** `true` für jedes Modul, das kein Datenmodul ist (Finder samt Trennlinie, Format- und
 *  Versionsinformation, Timing, Alignment, dunkles Modul); `mask[y][x]`. */
export function functionPatternMask(version) {
  const size = sizeOfVersion(version);
  const mask = Array.from({ length: size }, () => new Array(size).fill(false));
  const fill = (x0, y0, x1, y1) => {
    for (let y = Math.max(0, y0); y <= Math.min(size - 1, y1); y += 1) {
      for (let x = Math.max(0, x0); x <= Math.min(size - 1, x1); x += 1) mask[y][x] = true;
    }
  };
  fill(0, 0, 8, 8);                         // Finder oben links, Trennlinie, Formatbits
  fill(size - 8, 0, size - 1, 8);           // oben rechts
  fill(0, size - 8, 8, size - 1);           // unten links samt dunklem Modul
  fill(0, 6, size - 1, 6);                  // Timing
  fill(6, 0, 6, size - 1);
  const centers = ALIGNMENT_CENTERS[version];
  const last = centers.length - 1;
  centers.forEach((cy, row) => centers.forEach((cx, column) => {
    const overlapsFinder = (row === 0 && (column === 0 || column === last)) || (row === last && column === 0);
    if (!overlapsFinder) fill(cx - 2, cy - 2, cx + 2, cy + 2);
  }));
  if (version >= 7) {
    fill(size - 11, 0, size - 9, 5);
    fill(0, size - 11, 5, size - 9);
  }
  return mask;
}

// Die acht Datenmasken: wahr heißt, das Modul an (Zeile y, Spalte x) wird invertiert.
const MASKS = [
  (y, x) => (y + x) % 2 === 0,
  (y) => y % 2 === 0,
  (_row, x) => x % 3 === 0,
  (y, x) => (y + x) % 3 === 0,
  (y, x) => (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0,
  (y, x) => ((y * x) % 2) + ((y * x) % 3) === 0,
  (y, x) => (((y * x) % 2) + ((y * x) % 3)) % 2 === 0,
  (y, x) => ((((y + x) % 2) + ((y * x) % 3)) % 2) === 0,
];

/** Liest die Bits im Zickzack (zwei Spalten breit, von unten rechts, die Timing-Spalte 6
 *  übersprungen), entmaskiert und packt sie zu Codewörtern. */
function readCodewords(matrix, version, maskIndex) {
  const size = sizeOfVersion(version);
  const isFunction = functionPatternMask(version);
  const unmask = MASKS[maskIndex];
  const bits = [];
  let upward = true;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let step = 0; step < size; step += 1) {
      const y = upward ? size - 1 - step : step;
      for (let k = 0; k < 2; k += 1) {
        const x = right - k;
        if (isFunction[y][x]) continue;
        bits.push(Boolean(matrix[y][x]) !== unmask(y, x));
      }
    }
    upward = !upward;
  }
  const words = new Array(bits.length >> 3);
  for (let i = 0; i < words.length; i += 1) {
    let word = 0;
    for (let k = 0; k < 8; k += 1) word = (word << 1) | (bits[i * 8 + k] ? 1 : 0);
    words[i] = word;
  }
  return words;
}

/** Entflechtet die Codewörter in Blöcke, korrigiert jeden und liefert die Datenwörter
 *  hintereinander — oder `null`. */
function recoverData(words, version, ecLevel) {
  const [ecPerBlock, count1, data1, count2, data2] = EC_TABLE[version][ecLevel];
  const dataLengths = [];
  for (let i = 0; i < count1; i += 1) dataLengths.push(data1);
  for (let i = 0; i < count2; i += 1) dataLengths.push(data2);
  const total = dataLengths.reduce((sum, length) => sum + length + ecPerBlock, 0);
  if (words.length !== total) return null;

  const blocks = dataLengths.map((length) => new Array(length + ecPerBlock).fill(0));
  let position = 0;
  const longest = Math.max(...dataLengths);
  for (let i = 0; i < longest; i += 1) {
    for (let b = 0; b < blocks.length; b += 1) if (i < dataLengths[b]) blocks[b][i] = words[position++];
  }
  for (let i = 0; i < ecPerBlock; i += 1) {
    for (let b = 0; b < blocks.length; b += 1) blocks[b][dataLengths[b] + i] = words[position++];
  }

  const data = [];
  for (let b = 0; b < blocks.length; b += 1) {
    const fixed = correctBlock(blocks[b], ecPerBlock);
    if (fixed === null) return null;
    for (let i = 0; i < dataLengths[b]; i += 1) data.push(fixed[i]);
  }
  return data;
}

// ---------------------------------------------------------------------------------------
// Segmente: nur der Byte-Modus
// ---------------------------------------------------------------------------------------

const MODE_TERMINATOR = 0;
const MODE_BYTE = 4;

function bytesToText(bytes) {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bytes));
  } catch (error) {
    // Kein gültiges UTF-8: der Standard sieht für den Byte-Modus ISO-8859-1 vor.
    void error;
    return String.fromCharCode(...bytes);
  }
}

/** Liest die Segmente der Datenwörter. Byte-Segmente werden aneinandergehängt; jeder andere
 *  Modus (ECI, Kanji, Numerisch, Alphanumerisch, Structured Append, FNC1) → `null`. */
function parseSegments(data, version) {
  const totalBits = data.length * 8;
  let position = 0;
  const read = (count) => {
    if (position + count > totalBits) return -1;
    let value = 0;
    for (let i = 0; i < count; i += 1, position += 1) {
      value = (value << 1) | ((data[position >> 3] >> (7 - (position & 7))) & 1);
    }
    return value;
  };
  const countBits = version >= 10 ? 16 : 8;
  const bytes = [];
  for (;;) {
    // Läuft der Datenstrom ohne Terminator aus, ist das erlaubt, wenn er voll ist.
    if (totalBits - position < 4) break;
    const mode = read(4);
    if (mode === MODE_TERMINATOR) break;
    if (mode !== MODE_BYTE) return null;
    const length = read(countBits);
    if (length < 0 || position + length * 8 > totalBits) return null;
    for (let i = 0; i < length; i += 1) bytes.push(read(8));
  }
  return bytesToText(bytes);
}

// ---------------------------------------------------------------------------------------
// Matrix → Text
// ---------------------------------------------------------------------------------------

/** Dekodiert eine abgetastete Matrix (`matrix[y][x]`, `true` = dunkel, ohne Ruhezone) oder
 *  liefert `null`. Wirft nie. */
export function decodeMatrix(matrix) {
  if (!Array.isArray(matrix)) return null;
  const size = matrix.length;
  if (size < sizeOfVersion(MIN_VERSION) || size > sizeOfVersion(MAX_VERSION) || (size - 17) % 4 !== 0) return null;
  for (const row of matrix) if (!Array.isArray(row) || row.length !== size) return null;
  const version = (size - 17) / 4;

  const format = readFormatInfo(matrix, size);
  if (format === null) return null;
  const words = readCodewords(matrix, version, format.mask);
  const data = recoverData(words, version, format.ecLevel);
  if (data === null) return null;
  return parseSegments(data, version);
}

// ---------------------------------------------------------------------------------------
// Bild → Bits: Hybrid-Binarisierung
// ---------------------------------------------------------------------------------------

const BLOCK_SIZE = 8;          // Blöcke von 8×8 Pixeln
const MIN_DYNAMIC_RANGE = 24;  // darunter gilt ein Block als kontrastarm
const MIN_IMAGE_SIDE = 21;     // kleiner als das kleinste Symbol (21 Module à 1 Pixel)

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

/** Lokale Schwelle je Block: Mittel der Schwellen der 5×5 Nachbarblöcke; ein Pixel ist schwarz,
 *  wenn `lum <= Schwelle`. Kontrastarme Blöcke (Hintergrund, Himmel) bekommen die halbe
 *  Minimalhelligkeit, wo die Nachbarn heller sind deren Mittel — sonst entstünde dort Rauschen.
 *  Liefert `Uint8Array` (1 = schwarz). */
function binarize(luminance, width, height) {
  const blocksX = Math.ceil(width / BLOCK_SIZE);
  const blocksY = Math.ceil(height / BLOCK_SIZE);
  const points = new Int32Array(blocksX * blocksY);
  const originX = (bx) => Math.min(bx * BLOCK_SIZE, width - BLOCK_SIZE);
  const originY = (by) => Math.min(by * BLOCK_SIZE, height - BLOCK_SIZE);

  for (let by = 0; by < blocksY; by += 1) {
    const y0 = originY(by);
    for (let bx = 0; bx < blocksX; bx += 1) {
      const x0 = originX(bx);
      let sum = 0;
      let min = 255;
      let max = 0;
      for (let y = 0; y < BLOCK_SIZE; y += 1) {
        const row = (y0 + y) * width + x0;
        for (let x = 0; x < BLOCK_SIZE; x += 1) {
          const value = luminance[row + x];
          sum += value;
          if (value < min) min = value;
          if (value > max) max = value;
        }
      }
      let black;
      if (max - min > MIN_DYNAMIC_RANGE) {
        black = sum >> 6;
      } else {
        black = min >> 1;
        if (bx > 0 && by > 0) {
          const neighbours = (points[(by - 1) * blocksX + bx] + 2 * points[by * blocksX + bx - 1]
            + points[(by - 1) * blocksX + bx - 1]) >> 2;
          if (min < neighbours) black = neighbours;
        }
      }
      points[by * blocksX + bx] = black;
    }
  }

  const bits = new Uint8Array(width * height);
  for (let by = 0; by < blocksY; by += 1) {
    const top = clamp(by - 2, 0, Math.max(0, blocksY - 5));
    const bottom = Math.min(top + 4, blocksY - 1);
    const y0 = originY(by);
    for (let bx = 0; bx < blocksX; bx += 1) {
      const left = clamp(bx - 2, 0, Math.max(0, blocksX - 5));
      const right = Math.min(left + 4, blocksX - 1);
      let sum = 0;
      for (let y = top; y <= bottom; y += 1) for (let x = left; x <= right; x += 1) sum += points[y * blocksX + x];
      const threshold = Math.floor(sum / ((bottom - top + 1) * (right - left + 1)));
      const x0 = originX(bx);
      for (let y = 0; y < BLOCK_SIZE; y += 1) {
        const row = (y0 + y) * width + x0;
        for (let x = 0; x < BLOCK_SIZE; x += 1) bits[row + x] = luminance[row + x] <= threshold ? 1 : 0;
      }
    }
  }
  return bits;
}

/** Halbiert die Auflösung (Mittel aus 2×2): eine zweite Stufe für Bilder mit sehr großen Modulen
 *  und für rauschige Aufnahmen, bei denen die Mittelung das Rauschen dämpft. */
function halve(luminance, width, height) {
  const w = width >> 1;
  const h = height >> 1;
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const i = 2 * y * width + 2 * x;
      out[y * w + x] = (luminance[i] + luminance[i + 1] + luminance[i + width] + luminance[i + width + 1]) >> 2;
    }
  }
  return { luminance: out, width: w, height: h };
}

// ---------------------------------------------------------------------------------------
// Muster finden: Finder (1:1:3:1:1) und Alignment (1:1:1:1:1)
// ---------------------------------------------------------------------------------------

/** Passt ein Lauf-Fünfer zu 1:1:3:1:1 (je ±50 % der Modulgröße)? Liefert die Modulgröße oder 0. */
function finderModuleSize(counts) {
  let total = 0;
  for (const count of counts) {
    if (count === 0) return 0;
    total += count;
  }
  if (total < 7) return 0;
  const size = total / 7;
  const variance = size / 2;
  if (Math.abs(size - counts[0]) >= variance || Math.abs(size - counts[1]) >= variance
    || Math.abs(3 * size - counts[2]) >= 3 * variance || Math.abs(size - counts[3]) >= variance
    || Math.abs(size - counts[4]) >= variance) return 0;
  return size;
}

/** Alignment-Muster: die drei mittleren Läufe je ±50 % der Modulgröße; die äußeren dunklen
 *  Läufe dürfen länger sein, weil dort Datenmodule anschließen. */
function alignmentModuleSize(counts) {
  const [outerA, a, b, c, outerB] = counts;
  if (a === 0 || b === 0 || c === 0 || outerA === 0 || outerB === 0) return 0;
  const size = (a + b + c) / 3;
  const variance = size / 2;
  if (Math.abs(size - a) >= variance || Math.abs(size - b) >= variance || Math.abs(size - c) >= variance) return 0;
  if (outerA < variance || outerB < variance) return 0;
  return size;
}

/** Zählt die fünf Läufe quer durch (x, y) in Richtung (dx, dy): der mittlere schwarze Lauf
 *  enthält (x, y). Liefert `{counts, center}` mit `center` als Mitte des mittleren Laufs entlang der
 *  Achse (Pixelgrenzen-Koordinate) oder `null`. Läufe über `limit` brechen ab, nur die äußeren
 *  schwarzen werden gekappt. */
function crossRuns(bits, width, height, x, y, dx, dy, limit) {
  const at = (offset) => {
    const px = x + dx * offset;
    const py = y + dy * offset;
    if (px < 0 || py < 0 || px >= width || py >= height) return -1;
    return bits[py * width + px];
  };
  let back = 0;
  while (at(-back) === 1) {
    back += 1;
    if (back > limit) return null;
  }
  let forward = 0;
  while (at(1 + forward) === 1) {
    forward += 1;
    if (forward > limit) return null;
  }
  if (back === 0) return null;

  const counts = [0, 0, back + forward, 0, 0];
  let offset = -back;
  while (at(offset) === 0) {
    counts[1] += 1;
    offset -= 1;
    if (counts[1] > limit) return null;
  }
  if (counts[1] === 0 || at(offset) === -1) return null;
  while (at(offset) === 1 && counts[0] < limit) {
    counts[0] += 1;
    offset -= 1;
  }
  offset = forward + 1;
  while (at(offset) === 0) {
    counts[3] += 1;
    offset += 1;
    if (counts[3] > limit) return null;
  }
  if (counts[3] === 0 || at(offset) === -1) return null;
  while (at(offset) === 1 && counts[4] < limit) {
    counts[4] += 1;
    offset += 1;
  }
  return { counts, center: (forward - back) / 2 + 1 };
}

/** Prüft einen Treffer der Zeilensuche quer (senkrecht, dann waagerecht) und trägt ihn als
 *  Kandidat ein. `endX` ist die erste Spalte hinter dem Lauf-Fünfer. */
function confirmCandidate(bits, width, height, endX, y, counts, matcher, found) {
  const size = matcher(counts);
  if (size === 0) return;
  const limit = Math.ceil(size * 5);
  const rowCenter = endX - counts[4] - counts[3] - counts[2] / 2;
  const column = Math.floor(rowCenter);
  const vertical = crossRuns(bits, width, height, column, y, 0, 1, limit);
  if (vertical === null) return;
  const verticalSize = matcher(vertical.counts);
  if (verticalSize === 0 || 5 * Math.abs(verticalSize - size) >= 2 * size) return;
  const centerY = y + vertical.center;
  const row = Math.floor(centerY);
  const horizontal = crossRuns(bits, width, height, column, row, 1, 0, limit);
  if (horizontal === null) return;
  const horizontalSize = matcher(horizontal.counts);
  if (horizontalSize === 0 || 5 * Math.abs(horizontalSize - size) >= size) return;
  const centerX = column + horizontal.center;
  const moduleSize = (size + verticalSize + horizontalSize) / 3;

  for (const candidate of found) {
    const diff = Math.abs(candidate.size - moduleSize);
    if (Math.abs(candidate.x - centerX) <= moduleSize && Math.abs(candidate.y - centerY) <= moduleSize
      && (diff <= 1 || diff <= moduleSize)) {
      const n = candidate.count;
      candidate.x = (candidate.x * n + centerX) / (n + 1);
      candidate.y = (candidate.y * n + centerY) / (n + 1);
      candidate.size = (candidate.size * n + moduleSize) / (n + 1);
      candidate.count = n + 1;
      return;
    }
  }
  if (found.length < MAX_CANDIDATES) found.push({ x: centerX, y: centerY, size: moduleSize, count: 1 });
}

const MAX_CANDIDATES = 400;

/** Sucht Zeile für Zeile Läufe schwarz-weiß-schwarz-weiß-schwarz, die `matcher` annimmt, und
 *  bestätigt jeden quer. `region` ist `{x0, y0, x1, y1}` (hinten ausgeschlossen). */
function findPatterns(bits, width, height, region, matcher) {
  const found = [];
  const counts = [0, 0, 0, 0, 0];
  for (let y = region.y0; y < region.y1; y += 1) {
    counts.fill(0);
    let state = 0;
    const base = y * width;
    for (let x = region.x0; x <= region.x1; x += 1) {
      // Eine Spalte hinter dem Rand zählt als weiß und schließt einen offenen Lauf ab.
      const black = x < region.x1 && bits[base + x] === 1;
      if (black) {
        if (state & 1) state += 1;
        counts[state] += 1;
      } else if (state & 1) {
        counts[state] += 1;
      } else if (state === 4) {
        confirmCandidate(bits, width, height, x, y, counts, matcher, found);
        counts[0] = counts[2];
        counts[1] = counts[3];
        counts[2] = counts[4];
        counts[3] = 1;
        counts[4] = 0;
        state = 3;
      } else {
        state += 1;
        counts[state] += 1;
      }
    }
  }
  return found;
}

// ---------------------------------------------------------------------------------------
// Geometrie: drei Finder → Ausrichtung, Dimension, Alignment, Perspektive
// ---------------------------------------------------------------------------------------

const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/** Löst `matrix · x = rhs` (Gauß mit Spaltenpivot); `null` bei singulärer Matrix. */
function solveLinear(matrix, rhs) {
  const n = rhs.length;
  const a = matrix.map((row, i) => [...row, rhs[i]]);
  for (let column = 0; column < n; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < n; row += 1) if (Math.abs(a[row][column]) > Math.abs(a[pivot][column])) pivot = row;
    if (Math.abs(a[pivot][column]) < 1e-12) return null;
    [a[column], a[pivot]] = [a[pivot], a[column]];
    for (let row = column + 1; row < n; row += 1) {
      const factor = a[row][column] / a[column][column];
      for (let k = column; k <= n; k += 1) a[row][k] -= factor * a[column][k];
    }
  }
  const out = new Array(n).fill(0);
  for (let row = n - 1; row >= 0; row -= 1) {
    let sum = a[row][n];
    for (let k = row + 1; k < n; k += 1) sum -= a[row][k] * out[k];
    out[row] = sum / a[row][row];
  }
  return out;
}

/** Perspektivische Abbildung von vier Punkten (`[u, v]`) auf vier Bildpunkte (`{x, y}`). */
function quadToQuad(from, to) {
  const rows = [];
  const rhs = [];
  for (let i = 0; i < 4; i += 1) {
    const [u, v] = from[i];
    const { x, y } = to[i];
    rows.push([u, v, 1, 0, 0, 0, -u * x, -v * x]);
    rhs.push(x);
    rows.push([0, 0, 0, u, v, 1, -u * y, -v * y]);
    rhs.push(y);
  }
  const h = solveLinear(rows, rhs);
  if (h === null) return null;
  const [a, b, c, d, e, f, g, k] = h;
  return (u, v) => {
    const w = g * u + k * v + 1;
    return { x: (a * u + b * v + c) / w, y: (d * u + e * v + f) / w };
  };
}

/** Der Punkt gegenüber der längsten Seite ist oben links; das Vorzeichen des Kreuzprodukts
 *  trennt oben rechts von unten links (Bildkoordinaten, y nach unten). */
function orderCorners(a, b, c) {
  const ab = (a.x - b.x) ** 2 + (a.y - b.y) ** 2;
  const ac = (a.x - c.x) ** 2 + (a.y - c.y) ** 2;
  const bc = (b.x - c.x) ** 2 + (b.y - c.y) ** 2;
  let topLeft;
  let p;
  let q;
  if (bc >= ab && bc >= ac) [topLeft, p, q] = [a, b, c];
  else if (ac >= ab && ac >= bc) [topLeft, p, q] = [b, a, c];
  else [topLeft, p, q] = [c, a, b];
  const cross = (p.x - topLeft.x) * (q.y - topLeft.y) - (p.y - topLeft.y) * (q.x - topLeft.x);
  return cross > 0 ? { topLeft, topRight: p, bottomLeft: q } : { topLeft, topRight: q, bottomLeft: p };
}

/** Dreiergruppen von Finder-Kandidaten, die wie ein rechtwinkliges, gleichschenkliges Dreieck
 *  mit ähnlichen Modulgrößen aussehen, beste zuerst. */
function candidateTriples(finders) {
  const strong = [...finders].filter((f) => f.count >= 2).sort((a, b) => b.count - a.count).slice(0, MAX_TRIPLE_POOL);
  const triples = [];
  for (let i = 0; i < strong.length; i += 1) {
    for (let j = i + 1; j < strong.length; j += 1) {
      for (let k = j + 1; k < strong.length; k += 1) {
        const group = [strong[i], strong[j], strong[k]];
        const sizes = group.map((f) => f.size);
        if (Math.max(...sizes) > 1.5 * Math.min(...sizes)) continue;
        const sides = [distance(group[0], group[1]) ** 2, distance(group[0], group[2]) ** 2,
          distance(group[1], group[2]) ** 2].sort((p, q) => p - q);
        if (sides[0] === 0) continue;
        const skew = (Math.abs(sides[2] - 2 * sides[1]) + Math.abs(sides[2] - 2 * sides[0])) / sides[2];
        if (skew <= MAX_TRIANGLE_SKEW) triples.push({ group, skew });
      }
    }
  }
  return triples.sort((p, q) => p.skew - q.skew).slice(0, MAX_TRIPLES).map((t) => t.group);
}

const MAX_TRIPLE_POOL = 12;
const MAX_TRIPLES = 6;
const MAX_TRIANGLE_SKEW = 0.6;

/** Modulgröße von Finder `from` entlang der Verbindung zu `to`, gemessen in Pixeln auf dieser
 *  Linie: Die Läufe der Zeilensuche sind bei gedrehtem Symbol bis zu √2-mal zu lang, entlang der
 *  Symbolachse stimmt das Maß. Fällt die Messung aus, gilt die Größe aus der Zeilensuche. */
function moduleSizeToward(bits, width, height, from, to) {
  const length = distance(from, to);
  const dx = (to.x - from.x) / length;
  const dy = (to.y - from.y) / length;
  const step = 0.5;
  const limit = Math.ceil((from.size * 5) / step);
  const at = (t) => {
    const x = Math.floor(from.x + dx * t * step);
    const y = Math.floor(from.y + dy * t * step);
    if (x < 0 || y < 0 || x >= width || y >= height) return -1;
    return bits[y * width + x];
  };
  const runs = (direction) => {
    const counts = [0, 0, 0];
    let t = 0;
    for (let k = 0; k < 3; k += 1) {
      const colour = k % 2 === 0 ? 1 : 0;
      while (at(t) === colour) {
        counts[k] += 1;
        t += direction;
        if (counts[k] > limit) return null;
      }
      if (counts[k] === 0 && k > 0) return null;
    }
    return counts;
  };
  if (at(0) !== 1) return from.size;
  const behind = runs(-1);
  const ahead = runs(1);
  if (behind === null || ahead === null) return from.size;
  // Der mittlere Lauf wird von beiden Seiten gezählt, das Mittelpixel zweimal.
  const total = (behind[0] + ahead[0] - 1 + behind[1] + ahead[1] + behind[2] + ahead[2]) * step;
  const size = total / 7;
  return size > 0 && Math.abs(size - from.size) <= from.size ? size : from.size;
}

/** Die möglichen Kantenlängen (21, 25, …, 57 Module) nach Nähe zur Schätzung aus den
 *  Finder-Abständen. Die Schätzung ist auf ±1–2 Module genau; die Nachbarn werden mit
 *  probiert, das Format- und das Fehlerkorrektur-Ergebnis entscheiden. */
function dimensionGuesses(bits, width, height, corners) {
  const { topLeft, topRight, bottomLeft } = corners;
  const across = distance(topLeft, topRight) / ((moduleSizeToward(bits, width, height, topLeft, topRight)
    + moduleSizeToward(bits, width, height, topRight, topLeft)) / 2);
  const down = distance(topLeft, bottomLeft) / ((moduleSizeToward(bits, width, height, topLeft, bottomLeft)
    + moduleSizeToward(bits, width, height, bottomLeft, topLeft)) / 2);
  const raw = (across + down) / 2 + 7;
  const sizes = [];
  for (let version = MIN_VERSION; version <= MAX_VERSION; version += 1) sizes.push(sizeOfVersion(version));
  return sizes.filter((size) => Math.abs(size - raw) <= 6).sort((p, q) => Math.abs(p - raw) - Math.abs(q - raw));
}

/** Das Alignment-Muster unten rechts nahe der Parallelogramm-Schätzung, in Fenstern von 4, 8 und
 *  16 Modulgrößen; `null`, wenn keins gefunden wird. */
function findAlignment(bits, width, height, corners, dimension) {
  const { topLeft, topRight, bottomLeft } = corners;
  const corner = { x: topRight.x + bottomLeft.x - topLeft.x, y: topRight.y + bottomLeft.y - topLeft.y };
  const correction = 1 - 3 / (dimension - 7);
  const estimate = { x: topLeft.x + correction * (corner.x - topLeft.x), y: topLeft.y + correction * (corner.y - topLeft.y) };
  const moduleSize = (distance(topLeft, topRight) + distance(topLeft, bottomLeft)) / (2 * (dimension - 7));
  for (const factor of [4, 8, 16]) {
    const allowance = factor * moduleSize;
    const region = {
      x0: Math.max(0, Math.floor(estimate.x - allowance)),
      y0: Math.max(0, Math.floor(estimate.y - allowance)),
      x1: Math.min(width, Math.ceil(estimate.x + allowance)),
      y1: Math.min(height, Math.ceil(estimate.y + allowance)),
    };
    if (region.x1 - region.x0 < 3 * moduleSize || region.y1 - region.y0 < 3 * moduleSize) continue;
    const found = findPatterns(bits, width, height, region, alignmentModuleSize)
      .filter((c) => c.size >= moduleSize / 2 && c.size <= moduleSize * 2);
    if (found.length > 0) return found.sort((p, q) => distance(p, estimate) - distance(q, estimate))[0];
  }
  return null;
}

/** Tastet `dimension × dimension` Modulmitten ab (Mehrheit aus der Mitte und vier Punkten im
 *  Viertelmodul-Abstand); `null`, wenn ein Punkt außerhalb des Bildes liegt. */
function sampleGrid(bits, width, height, map, dimension) {
  const offsets = [[0, 0], [0.25, 0], [-0.25, 0], [0, 0.25], [0, -0.25]];
  const matrix = [];
  for (let row = 0; row < dimension; row += 1) {
    const line = new Array(dimension);
    for (let column = 0; column < dimension; column += 1) {
      let dark = 0;
      for (const [du, dv] of offsets) {
        const { x, y } = map(column + 0.5 + du, row + 0.5 + dv);
        const px = Math.floor(x);
        const py = Math.floor(y);
        if (!(px >= 0 && py >= 0 && px < width && py < height)) return null;
        dark += bits[py * width + px];
      }
      line[column] = dark >= 3;
    }
    matrix.push(line);
  }
  return matrix;
}

function decodeCorners(bits, width, height, corners) {
  for (const dimension of dimensionGuesses(bits, width, height, corners)) {
    const alignment = dimension >= sizeOfVersion(2) ? findAlignment(bits, width, height, corners, dimension) : null;
    for (const anchor of alignment === null ? [null] : [alignment, null]) {
      const { topLeft, topRight, bottomLeft } = corners;
      const far = dimension - 3.5;
      const bottomRight = anchor === null
        ? { x: topRight.x + bottomLeft.x - topLeft.x, y: topRight.y + bottomLeft.y - topLeft.y }
        : anchor;
      const farUV = anchor === null ? far : dimension - 6.5;
      const map = quadToQuad([[3.5, 3.5], [far, 3.5], [farUV, farUV], [3.5, far]],
        [topLeft, topRight, bottomRight, bottomLeft]);
      if (map === null) continue;
      const matrix = sampleGrid(bits, width, height, map, dimension);
      if (matrix === null) continue;
      const text = decodeMatrix(matrix);
      if (text !== null) return text;
    }
  }
  return null;
}

function decodeBits(bits, width, height) {
  const finders = findPatterns(bits, width, height, { x0: 0, y0: 0, x1: width, y1: height }, finderModuleSize);
  for (const group of candidateTriples(finders)) {
    const text = decodeCorners(bits, width, height, orderCorners(...group));
    if (text !== null) return text;
  }
  return null;
}

// ---------------------------------------------------------------------------------------
// Bild → Text
// ---------------------------------------------------------------------------------------

/** Liest einen QR-Code aus einem Graubild (`luminance[y * width + x]`, 0–255) oder liefert `null`.
 *  Probiert normal, invertiert (hell auf dunkel) und auf halber Auflösung. Wirft nie: das Bild ist
 *  ein Kamerabild und der Aufrufer ruft gleich mit dem nächsten Bild wieder. */
export function decodeQr(luminance, width, height) {
  if (!luminance || typeof luminance.length !== 'number') return null;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < MIN_IMAGE_SIDE || height < MIN_IMAGE_SIDE) return null;
  if (luminance.length < width * height) return null;
  try {
    let level = { luminance, width, height };
    for (let stage = 0; stage < 2; stage += 1) {
      const bits = binarize(level.luminance, level.width, level.height);
      let text = decodeBits(bits, level.width, level.height);
      if (text !== null) return text;
      for (let i = 0; i < bits.length; i += 1) bits[i] ^= 1;
      text = decodeBits(bits, level.width, level.height);
      if (text !== null) return text;
      if (Math.min(level.width, level.height) < 4 * MIN_IMAGE_SIDE) break;
      level = halve(level.luminance, level.width, level.height);
    }
    return null;
  } catch (error) {
    // Ein Fehler im Decoder darf den Scan nicht beenden: das nächste Videobild kommt gleich.
    void error;
    return null;
  }
}
