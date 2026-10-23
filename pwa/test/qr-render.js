// pwa/test/qr-render.js
// Hilfe für qr-image.test.js, kein Test: zeichnet eine QR-Matrix als Luminanzbild und verschlechtert
// es wie eine Kamera — Drehung, Perspektive, Unschärfe, Rauschen, Helligkeitsverlauf, wenig Kontrast.
// Alles deterministisch (fester Zufallsstart), damit ein Fehlschlag reproduzierbar bleibt.

export function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

/** Löst ein lineares Gleichungssystem (Gauß mit Spaltenpivot). */
function solve(matrix, rhs) {
  const n = rhs.length;
  const a = matrix.map((row, i) => [...row, rhs[i]]);
  for (let col = 0; col < n; col += 1) {
    let pivot = col;
    for (let row = col + 1; row < n; row += 1) if (Math.abs(a[row][col]) > Math.abs(a[pivot][col])) pivot = row;
    [a[col], a[pivot]] = [a[pivot], a[col]];
    for (let row = col + 1; row < n; row += 1) {
      const factor = a[row][col] / a[col][col];
      for (let k = col; k <= n; k += 1) a[row][k] -= factor * a[col][k];
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

/** Perspektivische Abbildung von vier Punkten auf vier Punkte; liefert `(x, y) => [x', y']`. */
export function quadMap(from, to) {
  const rows = [];
  const rhs = [];
  for (let i = 0; i < 4; i += 1) {
    const [u, v] = from[i];
    const [x, y] = to[i];
    rows.push([u, v, 1, 0, 0, 0, -u * x, -v * x]); rhs.push(x);
    rows.push([0, 0, 0, u, v, 1, -u * y, -v * y]); rhs.push(y);
  }
  const [a, b, c, d, e, f, g, h] = solve(rows, rhs);
  return (u, v) => {
    const w = g * u + h * v + 1;
    return [(a * u + b * v + c) / w, (d * u + e * v + f) / w];
  };
}

/**
 * Zeichnet `matrix` (Zeilen aus Booleans) als Graubild.
 * Optionen: `px` (Pixel je Modul), `quiet` (Ruhezone in Modulen), `angle` (Grad), `skew` (Verschiebung
 * der vier Ecken in Modulen, [[dx,dy]×4]), `blur` (Radius in Pixeln), `noise` (Amplitude, ±),
 * `gradient` (0..1, Abdunkelung von links nach rechts), `dark`/`light` (Grauwerte), `invert`, `margin`
 * (Pixel um das Symbol), `seed`.
 */
export function render(matrix, options = {}) {
  const {
    px = 6, quiet = 4, angle = 0, skew = null, blur = 0, noise = 0, gradient = 0,
    dark = 25, light = 235, invert = false, margin = 24, seed = 1,
  } = options;
  const size = matrix.length;
  const total = size + 2 * quiet;
  const side = total * px;
  const radians = (angle * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const corners = [[0, 0], [total, 0], [total, total], [0, total]];
  const placed = corners.map(([u, v], i) => {
    const [dx, dy] = skew ? skew[i] : [0, 0];
    const x = (u + dx - total / 2) * px;
    const y = (v + dy - total / 2) * px;
    return [x * cos - y * sin, x * sin + y * cos];
  });
  const xs = placed.map((p) => p[0]);
  const ys = placed.map((p) => p[1]);
  const minX = Math.min(...xs) - margin;
  const minY = Math.min(...ys) - margin;
  const width = Math.ceil(Math.max(...xs) - minX + margin);
  const height = Math.ceil(Math.max(...ys) - minY + margin);
  const toModules = quadMap(placed.map(([x, y]) => [x - minX, y - minY]), corners);

  const random = lcg(seed);
  const image = new Float32Array(width * height);
  const sample = (x, y) => {
    const [u, v] = toModules(x, y);
    const col = Math.floor(u) - quiet;
    const row = Math.floor(v) - quiet;
    const isDark = col >= 0 && row >= 0 && col < size && row < size && matrix[row][col];
    return (isDark !== invert) ? dark : light;
  };
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let sum = 0;
      for (let sy = 0; sy < 3; sy += 1) for (let sx = 0; sx < 3; sx += 1) sum += sample(x + (sx + 0.5) / 3, y + (sy + 0.5) / 3);
      image[y * width + x] = sum / 9;
    }
  }

  let current = image;
  if (blur > 0) {
    const radius = Math.max(1, Math.round(blur));
    for (let pass = 0; pass < 2; pass += 1) {
      const next = new Float32Array(width * height);
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          let sum = 0;
          let count = 0;
          for (let k = -radius; k <= radius; k += 1) {
            const xx = pass === 0 ? Math.min(width - 1, Math.max(0, x + k)) : x;
            const yy = pass === 1 ? Math.min(height - 1, Math.max(0, y + k)) : y;
            sum += current[yy * width + xx];
            count += 1;
          }
          next[y * width + x] = sum / count;
        }
      }
      current = next;
    }
  }

  const out = new Uint8ClampedArray(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let value = current[y * width + x];
      value *= 1 - gradient * (x / width);
      value += (random() * 2 - 1) * noise;
      out[y * width + x] = Math.round(value);
    }
  }
  return { luminance: out, width, height, side };
}
