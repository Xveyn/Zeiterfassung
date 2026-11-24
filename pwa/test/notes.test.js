// pwa/test/notes.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { MAX_NOTE_LEN, cleanNote, checkNote, groupKey, noteSuggestions } from '../notes.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/note-cases.json', import.meta.url)));

test('MAX_NOTE_LEN gleicht der Fixture', () => {
  assert.equal(MAX_NOTE_LEN, cases.max_len);
});

cases.clean.forEach((c, i) => {
  test(`cleanNote #${i}`, () => assert.equal(cleanNote(c.in), c.out));
});

cases.check.forEach((c, i) => {
  test(`checkNote #${i}`, () => {
    const r = checkNote(c.in);
    if (c.ok) assert.deepEqual(r, { ok: true, note: c.out });
    else assert.equal(r.ok, false);
  });
});

cases.group.forEach((c, i) => {
  test(`groupKey #${i}`, () => assert.equal(groupKey(c.in), c.key));
});

cases.suggestions.forEach((c, i) => {
  test(`noteSuggestions #${i}`, () => {
    const args = [c.days, c.kategorie];
    if ('limit' in c) args.push(c.limit);
    assert.deepEqual(noteSuggestions(...args), c.out);
  });
});

test('200 Emoji sind gültig, 201 nicht', () => {
  assert.equal(checkNote('😀'.repeat(200)).ok, true);
  assert.equal(checkNote('😀'.repeat(201)).ok, false);
});

test('checkNote meldet auf Deutsch, eine Zeile', () => {
  assert.deepEqual(checkNote('x'.repeat(201)), { ok: false, message: 'Höchstens 200 Zeichen.' });
  assert.deepEqual(checkNote('a\nb'), { ok: false, message: 'Nur eine Zeile, keine Steuerzeichen.' });
  assert.equal(checkNote(5).ok, false);
});

test('cleanNote wirft nie bei Fremddaten', () => {
  for (const v of [5, null, undefined, {}, [], true]) assert.equal(cleanNote(v), '');
});

test('noteSuggestions verträgt Fremdformen', () => {
  for (const days of [null, undefined, 5, 'x', []]) assert.deepEqual(noteSuggestions(days, ''), []);
});
