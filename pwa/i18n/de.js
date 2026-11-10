// pwa/i18n/de.js
// Text-Katalog Deutsch: Schlüssel (punktiert) → Text mit `{name}`-Platzhaltern. Die Schlüssel mit
// Präfix `i18n.` gehören der Textschicht selbst (Tests); alle anderen müssen von einem `t('…')`-
// Aufruf in pwa/*.js benutzt werden (pwa/test/i18n.test.js).
export default {
  'i18n.beispiel': 'Hallo {name}, es sind {count} Einträge.',
  'i18n.ohne_parameter': 'Nur Text',
};
