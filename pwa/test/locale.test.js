import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  formatClock, formatDate, formatDateShort, getLocale, localeTag, setLocale, weekdayShort,
} from '../locale.js';

test('formatDate: de-DE ist TT.MM.JJJJ', () => {
  assert.equal(formatDate('2026-06-02'), '02.06.2026');
  assert.equal(formatDateShort('2026-06-02'), '02.06.');
  assert.equal(formatDate('kaputt'), 'kaputt');
});

test('localeTag: Unbrauchbares ergibt de-DE, ohne zu werfen', () => {
  for (const [l, c] of [['xx', 'ZZZ'], ['', ''], ['de_DE', 'DE'], [undefined, null], ['de', 'DE'], ['-', '-'], ['de', '']]) {
    assert.equal(localeTag(l, c), 'de-DE', `${l}/${c}`);
  }
  assert.equal(localeTag('en', 'GB'), 'en-GB');
});

test('Formatierer mit kaputtem Tag werfen nicht', () => {
  assert.ok(formatClock(Date.UTC(2026, 5, 2, 10, 5), 'UTC', 'de_DE'));
  assert.equal(formatDate('2026-06-02', ''), '02.06.2026');
  assert.ok(weekdayShort(0, 'xx-ZZZ'));
});

test('setLocale/getLocale: kaputter Tag lässt de-DE', () => {
  try {
    setLocale('en-GB');
    assert.equal(getLocale(), 'en-GB');
    assert.notEqual(formatDate('2026-06-02'), '02.06.2026');
    setLocale('de_DE');
    assert.equal(getLocale(), 'de-DE');
    assert.equal(formatDate('2026-06-02'), '02.06.2026');
  } finally {
    setLocale('de-DE');
  }
});
