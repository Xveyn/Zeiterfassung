// pwa/dom.js
// Der einzige Weg, Elemente zu bauen: `createElement` und Textknoten. Keine HTML-Strings — Namen,
// Kategorien und Fehlertexte kommen vom Desktop beziehungsweise aus einem QR-Code (Fremddaten)
// und erscheinen deshalb immer als Text.

/** @param {string} tag @param {Record<string, unknown>} [attrs] @param {...unknown} children */
export function h(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (name === 'class') element.className = String(value);
    else if (name.startsWith('on') && typeof value === 'function') element.addEventListener(name.slice(2), value);
    else if (value === true) element.setAttribute(name, '');
    else element.setAttribute(name, String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

export function clear(element) {
  while (element.firstChild) element.firstChild.remove();
}

/** Der `data-focus`-Schlüssel des fokussierten Elements, wenn es in `root` liegt. */
export function focusState(root) {
  const active = document.activeElement;
  const inRoot = Boolean(active) && active !== document.body && root.contains(active);
  return {
    activeKey: inRoot ? active.getAttribute('data-focus') : null,
    inRoot,
    isBody: !active || active === document.body,
  };
}

/** Gibt dem Element mit diesem `data-focus`-Schlüssel den Fokus (falls es da und nicht gesperrt ist). */
export function focusByKey(root, key) {
  if (!key) return false;
  const target = [...root.querySelectorAll('[data-focus]')].find((element) => element.getAttribute('data-focus') === key);
  if (!target || target.disabled) return false;
  target.focus();
  return true;
}
