// pwa/privacy-view.js
// Die Seite „Datenschutzhinweise“ (`datenschutz.html`): lädt `datenschutz.md` (der Pages-Workflow kopiert
// `docs/datenschutz.md` neben die Seite), zerlegt es mit `privacy-doc.js` und baut die Elemente über `dom.js`
// (nie HTML-Strings). Scheitert das Laden, steht ein Ersatztext mit Link auf das Dokument im Projekt da.
import { t } from './i18n.js';
import { h } from './dom.js';
import { isWebUrl, parsePrivacyMarkdown, sectionsOnly } from './privacy-doc.js';
import { PRIVACY_SOURCE_URL } from './relay-client.js';

const TAGS = { bold: 'strong', code: 'code' };

function inline(segments) {
  return segments.map((s) => {
    if (s.style === 'link' && isWebUrl(s.url)) {
      return h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.text);
    }
    return TAGS[s.style] ? h(TAGS[s.style], {}, s.text) : s.text;
  });
}

/** Blöcke → Elemente; aufeinanderfolgende Listenpunkte teilen sich eine Liste (Einrückung per Klasse). */
export function renderBlocks(blocks) {
  const out = [];
  let list = null;
  for (const b of blocks) {
    if (b.kind !== 'bullet') list = null;
    if (b.kind === 'bullet') {
      if (!list) {
        list = h('ul', { class: 'privacy-list' });
        out.push(list);
      }
      list.append(h('li', { class: `level${b.level}` }, inline(b.segments)));
    } else if (b.kind === 'heading' || b.kind === 'title') out.push(h('h2', {}, inline(b.segments)));
    else if (b.kind === 'quote') out.push(h('blockquote', {}, inline(b.segments)));
    else out.push(h('p', {}, inline(b.segments)));
  }
  return out;
}

export function fallbackBlocks() {
  return [{ kind: 'paragraph', level: 0, segments: [
    { text: t('datenschutz.fallback'), style: 'plain', url: null },
    { text: PRIVACY_SOURCE_URL, style: 'link', url: PRIVACY_SOURCE_URL },
  ] }];
}

export async function loadBlocks(fetchFn = fetch) {
  try {
    const response = await fetchFn('./datenschutz.md', { cache: 'no-cache' });
    if (!response.ok) return fallbackBlocks();
    const blocks = sectionsOnly(parsePrivacyMarkdown(await response.text()));
    return blocks.length ? blocks : fallbackBlocks();
  } catch {
    return fallbackBlocks();                    // offline oder Datei fehlt: nie eine leere Seite
  }
}

export async function mountPrivacyPage(root) {
  const back = h('p', {}, h('a', { href: './' }, t('datenschutz.zurueck')));
  const content = h('div', { id: 'privacy-content' }, h('p', { class: 'muted' }, t('datenschutz.laedt')));
  root.replaceChildren(h('main', { class: 'privacy' }, back, h('h1', {}, t('datenschutz.titel')), content));
  content.replaceChildren(...renderBlocks(await loadBlocks()));
}

if (typeof document !== 'undefined' && document.getElementById('app')) {
  void mountPrivacyPage(document.getElementById('app'));
}
