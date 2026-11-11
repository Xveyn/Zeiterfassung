// pwa/test/views-texts.test.js
// Wortlaut der Texte mit Parametern aus views.js (Nachweis, dass die Umstellung auf den Katalog die
// ausgegebenen Strings nicht verändert hat). views.js baut DOM und ist in Node nicht ausführbar.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { t } from '../i18n.js';

test('parameterised texts of views.js read as before', () => {
  assert.equal(t('einrichtung.ueberschrift', { count: 4 }), 'Einrichtung · 4 Schritte');
  assert.equal(t('woche.tag.aria', { weekday: 'Mo', label: '09.11.2026', minutes: '' }), 'Mo 09.11.2026');
  assert.equal(t('woche.tag.aria_heute', { weekday: 'Mo', label: '09.11.2026', minutes: '' }), 'Mo 09.11.2026, heute');
  assert.equal(t('woche.tag.aria_stunden', { weekday: 'Mo', label: '09.11.2026', minutes: '7:30' }), 'Mo 09.11.2026, 7:30 Stunden');
  assert.equal(t('woche.tag.aria_heute_stunden', { weekday: 'Mo', label: '09.11.2026', minutes: '7:30' }), 'Mo 09.11.2026, heute, 7:30 Stunden');
  assert.equal(t('woche.geplant', { text: '08:00–12:00' }), 'geplant 08:00–12:00');
  assert.equal(t('editor.chip.minuten', { minutes: 20 }), '+20 min');
  assert.equal(t('editor.chip.stunden', { hours: 2 }), '+2 h');
  assert.equal(t('editor.chip.ende_aria', { dauer: '+20 min' }), 'Ende +20 min nach dem Start');
  assert.equal(t('editor.chip.pause_aria', { minutes: 30 }), 'Pause 30 Minuten');
  assert.equal(t('editor.slot', { nummer: 2 }), 'Slot 2');
  assert.equal(t('editor.slot_entfernen', { nummer: 2 }), 'Slot 2 entfernen');
  assert.equal(t('konflikte.summe', { summe: '8:00' }), 'Summe 8:00');
  assert.equal(t('einstellungen.kategorien.bearbeiten_aria', { name: 'Projekt' }), 'Kategorie „Projekt“ bearbeiten');
});
