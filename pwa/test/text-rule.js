// pwa/test/text-rule.js
// Was als Nutzertext gilt (Textratsche und Inventur): ein Literal mit Buchstaben, dazu Leerraum oder
// ein Großbuchstabe am Anfang. Ausgenommen, weil technisch: ein Wort ohne Kleinbuchstaben (`AES-GCM`,
// `GET`), Klassenlisten aus kleingeschriebenen Wörtern (`hint warn`) und Fehlernamen (`AbortError`).
// Grenze: ein Text, der nur aus kleingeschriebenen Wörtern besteht, fällt durch; das fängt Review.
export function looksLikeText(text) {
  const s = text.replace(/\$\{\}/g, '').trim();
  if (!/\p{L}/u.test(s)) return false;
  if (!/\p{Ll}/u.test(s) && !/\s/.test(s)) return false;
  if (/^[a-z][\w-]*(\s+[a-z][\w-]*)*$/.test(s)) return false;
  if (/^[A-Z][A-Za-z]*(Error|Failure)$/.test(s)) return false;
  return /\s/.test(s) || /^\p{Lu}/u.test(s);
}
