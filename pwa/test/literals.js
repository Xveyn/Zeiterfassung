// pwa/test/literals.js
// Kleiner Tokenizer für die Textratsche (i18n-literals.test.js) und die Inventur
// (scripts/pwa_text_inventory.mjs): findet String-Literale im Quelltext, ohne Kommentare, Regex-
// Literale und `${…}`-Ausdrücke zu verwechseln. Keine Abhängigkeit, damit `pwa/` ohne `npm ci` testbar bleibt.

const REGEX_AFTER_WORD = new Set(['return', 'typeof', 'case', 'do', 'else', 'in', 'of', 'void', 'delete', 'throw', 'new', 'yield', 'await']);
const ID_START = /[A-Za-z_$]/;
const ID_PART = /[\w$]/;

// Liefert Literale `{ text, line, kind, exempt }`. `exempt` ist wahr, wenn das Literal das erste
// Argument von t(, logFailure(, this._log( ist oder irgendwo in einem console.*(-Aufruf steht;
// `callee` nennt dann den Aufrufer (für die Ratsche: t( zählt als „benutzt").
export function scanLiterals(source) {
  const out = [];
  const state = { i: 0, line: 1 };
  scanCode(source, state, out, null);
  return out;
}

function scanCode(src, st, out, endAt) {
  // `endAt === '}'`: Ausdruck in einem Template-String, endet an der passenden schließenden Klammer.
  let depth = 0;
  const parens = [];       // je offener `(`: { callee, console, first }
  let prev = { type: 'start', value: '' };   // letztes bedeutsames Token
  let prevPrev = { type: 'start', value: '' };
  let prev3 = { type: 'start', value: '' };
  const push = (tok) => { prev3 = prevPrev; prevPrev = prev; prev = tok; };
  while (st.i < src.length) {
    const c = src[st.i];
    if (c === '\n') { st.line += 1; st.i += 1; continue; }
    if (/\s/.test(c)) { st.i += 1; continue; }
    if (c === '/' && src[st.i + 1] === '/') { while (st.i < src.length && src[st.i] !== '\n') st.i += 1; continue; }
    if (c === '/' && src[st.i + 1] === '*') {
      const end = src.indexOf('*/', st.i + 2);
      const stop = end === -1 ? src.length : end + 2;
      for (let k = st.i; k < stop; k += 1) if (src[k] === '\n') st.line += 1;
      st.i = stop; continue;
    }
    if (c === "'" || c === '"') {
      const line = st.line;
      let text = '';
      st.i += 1;
      while (st.i < src.length && src[st.i] !== c) {
        if (src[st.i] === '\\') { text += cook(src, st); continue; }
        text += src[st.i]; st.i += 1;
      }
      st.i += 1;
      const ctx = context(parens, prev);
      out.push({ text, line, kind: 'string', exempt: ctx.exempt, callee: ctx.callee });
      push({ type: 'string', value: text });
      continue;
    }
    if (c === '`') {
      const line = st.line;
      st.i += 1;
      let text = '';
      const ctx = context(parens, prev);
      const parts = [];
      while (st.i < src.length && src[st.i] !== '`') {
        if (src[st.i] === '\\') { text += cook(src, st); continue; }
        if (src[st.i] === '$' && src[st.i + 1] === '{') {
          parts.push(text); text = '';
          st.i += 2;
          scanCode(src, st, out, '}');
          continue;
        }
        if (src[st.i] === '\n') st.line += 1;
        text += src[st.i]; st.i += 1;
      }
      st.i += 1;
      parts.push(text);
      out.push({ text: parts.join('${}'), line, kind: 'template', exempt: ctx.exempt, callee: ctx.callee, dynamic: parts.length > 1 });
      push({ type: 'string', value: text });
      continue;
    }
    if (c === '/') {
      const isDivision = prev.type === 'number' || prev.type === 'string' || prev.type === 'close'
        || (prev.type === 'word' && !REGEX_AFTER_WORD.has(prev.value));
      if (isDivision) { st.i += 1; push({ type: 'punct', value: '/' }); continue; }
      st.i += 1;                         // Regex-Literal überspringen
      let inClass = false;
      while (st.i < src.length) {
        const r = src[st.i];
        if (r === '\\') { st.i += 2; continue; }
        if (r === '[') inClass = true;
        else if (r === ']') inClass = false;
        else if (r === '/' && !inClass) break;
        else if (r === '\n') break;
        st.i += 1;
      }
      st.i += 1;
      while (st.i < src.length && ID_PART.test(src[st.i])) st.i += 1;
      push({ type: 'number', value: 'regex' });
      continue;
    }
    if (ID_START.test(c)) {
      let word = '';
      while (st.i < src.length && ID_PART.test(src[st.i])) { word += src[st.i]; st.i += 1; }
      push({ type: 'word', value: word });
      continue;
    }
    if (/[0-9]/.test(c)) {
      while (st.i < src.length && /[\w.]/.test(src[st.i])) st.i += 1;
      push({ type: 'number', value: '0' });
      continue;
    }
    st.i += 1;
    if (c === '(') {
      parens.push(calleeOf(prev, prevPrev, prev3, parens));
      push({ type: 'open', value: '(' });
    } else if (c === ')') {
      parens.pop();
      push({ type: 'close', value: ')' });
    } else if (c === ']') push({ type: 'close', value: ']' });
    else if (c === '{') { depth += 1; push({ type: 'punct', value: '{' }); }
    else if (c === '}') {
      if (endAt === '}' && depth === 0) return;
      depth -= 1;
      push({ type: 'close', value: '}' });
    } else if (c === '.' && src[st.i] === '.' ) push({ type: 'punct', value: '.' });
    else push({ type: 'punct', value: c });
  }
}

// Was ein `\`-Escape im Literal bedeutet; nur so genau, wie die Ratsche es braucht.
function cook(src, st) {
  const e = src[st.i + 1];
  st.i += 2;
  if (e === 'n') return '\n';
  if (e === 't') return '\t';
  if (e === 'u') {
    if (src[st.i] === '{') { const end = src.indexOf('}', st.i); const cp = parseInt(src.slice(st.i + 1, end), 16); st.i = end + 1; return String.fromCodePoint(cp); }
    const cp = parseInt(src.slice(st.i, st.i + 4), 16); st.i += 4; return String.fromCharCode(cp);
  }
  if (e === 'x') { const cp = parseInt(src.slice(st.i, st.i + 2), 16); st.i += 2; return String.fromCharCode(cp); }
  if (e === '\n') { st.line += 1; return ''; }
  return e;
}

// Aufrufer des Aufrufs, der gleich mit `(` geöffnet wird: `t`, `logFailure`, `this._log`, `console.x`.
function calleeOf(prev, prevPrev, prev3, parens) {
  const inherited = parens.some((p) => p.console);
  if (prev.type !== 'word') return { console: inherited, arg0: false };
  const isConsole = prevPrev.value === '.' && prev3.value === 'console';
  return { console: inherited || isConsole, arg0: true, name: prev.value };
}

function context(parens, prev) {
  const top = parens[parens.length - 1];
  if (!top) return { exempt: false, callee: null };
  if (top.console) return { exempt: true, callee: 'console' };
  if (prev.type === 'open' && top.arg0 && ['t', 'logFailure', '_log'].includes(top.name)) return { exempt: true, callee: top.name };
  return { exempt: false, callee: null };
}
