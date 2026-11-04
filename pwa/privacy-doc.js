// pwa/privacy-doc.js
// Parser für `docs/datenschutz.md`, das Gegenstück zu `src/privacy_doc.py`: dieselbe Teilmenge von Markdown
// (Titel, Überschriften, Absätze, Listen mit Einrückung, Zitat, fett, Code, Links), dieselben Blöcke
// `{kind, segments: [{text, style, url}], level}`. Den Gleichlauf hält `test/fixtures/privacy-blocks.json`
// (erzeugt von `scripts/privacy_fixtures.py`, geprüft von beiden Seiten). Links nur für `http(s)`: das
// Dokument ist Fremddatei im Sinne der Seite. Ohne Browser-API, damit Node es testen kann.

const HTML_COMMENT = /<!--[\s\S]*?-->/g;
const BULLET = /^(\s*)[-*]\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const UNKNOWN = /^(\||\d+[.)]\s|```|~~~|<)/;
const LINK = /\[([^\]]*)\]\(((?:[^()\s]|\([^()\s]*\))*)\)/y;

/** Nur `https://` und `http://` (Groß-/Kleinschreibung egal). */
export function isWebUrl(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url);
}

const segment = (text, style = 'plain', url = null) => ({ text, style, url });

/** `**fett**`, `` `code` `` und `[Text](URL)`; nicht geschlossene Auszeichnung bleibt als Text stehen. */
export function parseInline(text) {
  const segments = [];
  let plain = '';
  const flush = () => {
    if (plain) segments.push(segment(plain));
    plain = '';
  };
  let i = 0;
  while (i < text.length) {
    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2);
      if (end > i + 2) {
        flush();
        segments.push(segment(text.slice(i + 2, end), 'bold'));
        i = end + 2;
        continue;
      }
    } else if (text[i] === '`') {
      const end = text.indexOf('`', i + 1);
      if (end > i + 1) {
        flush();
        segments.push(segment(text.slice(i + 1, end), 'code'));
        i = end + 1;
        continue;
      }
    } else if (text[i] === '[') {
      LINK.lastIndex = i;
      const match = LINK.exec(text);
      if (match) {
        const [whole, label, url] = match;
        if (label && isWebUrl(url)) {
          flush();
          segments.push(segment(label, 'link', url));
        } else {
          plain += label;                         // ohne Link: nur der Text, nie die URL
        }
        i += whole.length;
        continue;
      }
    }
    plain += text[i];
    i += 1;
  }
  flush();
  return segments;
}

const block = (kind, text, level = 0) => ({ kind, segments: parseInline(text), level });

/** Das Dokument als Blöcke in Dokumentreihenfolge; Fortsetzungszeilen werden mit einem Leerzeichen
 *  zusammengeführt. */
export function parsePrivacyMarkdown(source) {
  // Wiederholt bis zum Fixpunkt: ein einmaliges Entfernen kann aus verschachteltem Text (`<<!-- x -->!-- y -->`)
  // einen neuen Kommentar zusammensetzen.
  let text = source.replace(/^﻿/, '');
  for (let previous = null; previous !== text;) {
    previous = text;
    text = text.replace(HTML_COMMENT, '');
  }
  const blocks = [];                              // [kind, level, teile[]]
  let openLast = false;                           // darf die nächste Zeile den letzten Block fortsetzen?
  for (const raw of text.split(/\r\n|\r|\n/)) {
    const line = raw.trimEnd();
    const stripped = line.trim();
    if (!stripped) {
      openLast = false;
      continue;
    }
    const heading = HEADING.exec(stripped);
    const bullet = BULLET.exec(line);
    if (heading && !line.startsWith(' ')) {
      blocks.push([heading[1].length === 1 ? 'title' : 'heading', 0, [heading[2].trim()]]);
      openLast = false;
    } else if (stripped.startsWith('>')) {
      const body = stripped.replace(/^>+/, '').trim();
      if (openLast && blocks[blocks.length - 1][0] === 'quote') blocks[blocks.length - 1][2].push(body);
      else {
        blocks.push(['quote', 0, [body]]);
        openLast = true;
      }
    } else if (bullet) {
      blocks.push(['bullet', Math.min(Math.floor(bullet[1].length / 2), 2), [bullet[2].trim()]]);
      openLast = true;
    } else if (UNKNOWN.test(stripped)) {
      blocks.push(['paragraph', 0, [stripped]]);
      openLast = false;
    } else if (openLast) {
      blocks[blocks.length - 1][2].push(stripped);
    } else {
      blocks.push(['paragraph', 0, [stripped]]);
      openLast = true;
    }
  }
  return blocks.map(([kind, level, parts]) => block(kind, parts.join(' '), level));
}

/** Ab der ersten Abschnittsüberschrift (`## …`); ohne Überschrift bleibt alles stehen. Wie
 *  `privacy_doc.sections_only`. */
export function sectionsOnly(blocks) {
  const index = blocks.findIndex((b) => b.kind === 'heading');
  return index < 0 ? blocks : blocks.slice(index);
}
