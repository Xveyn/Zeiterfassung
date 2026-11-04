// pwa/test/privacy-doc.test.js
// Der Markdown-Parser der Datenschutzseite gegen die Blöcke des Python-Parsers (Fixture aus
// `scripts/privacy_fixtures.py`) und die Darstellung der Seite.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

import { isWebUrl, parseInline, parsePrivacyMarkdown, sectionsOnly } from '../privacy-doc.js';
import { fallbackBlocks, loadBlocks } from '../privacy-view.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/privacy-blocks.json', import.meta.url), 'utf8'));
const doc = new URL('../../docs/datenschutz.md', import.meta.url);

test('the cases give exactly the blocks of the desktop parser', () => {
  assert.ok(fixture.cases.length > 0);
  for (const c of fixture.cases) {
    assert.deepEqual(sectionsOnly(parsePrivacyMarkdown(c.markdown)), c.blocks, JSON.stringify(c.markdown));
  }
});

test('the real document gives exactly the blocks of the desktop parser, starting at section 1', () => {
  assert.ok(existsSync(doc));
  const blocks = sectionsOnly(parsePrivacyMarkdown(readFileSync(doc, 'utf8')));
  assert.deepEqual(blocks, fixture.document, 'Fixture veraltet? python scripts/privacy_fixtures.py');
  assert.equal(blocks[0].kind, 'heading');
  assert.match(blocks[0].segments[0].text, /^1\. Was der Relay sieht/);
  assert.ok(!blocks.some((b) => b.kind === 'title'));
});

test('only web links become links, never javascript: or relative targets', () => {
  const segments = parseInline('[a](javascript:alert(1)) [b](docs/x.md) [c](https://x.example)');
  assert.deepEqual(segments.filter((s) => s.style === 'link').map((s) => s.url), ['https://x.example']);
  assert.equal(isWebUrl('JAVASCRIPT:1'), false);
  assert.equal(isWebUrl('HTTPS://x.example'), true);
});

test('a fetch that fails or answers an error shows the fallback with the project link', async () => {
  const bad = await loadBlocks(async () => { throw new TypeError('offline'); });
  assert.deepEqual(bad, fallbackBlocks());
  const missing = await loadBlocks(async () => ({ ok: false }));
  assert.deepEqual(missing, fallbackBlocks());
  assert.equal(fallbackBlocks()[0].segments.at(-1).style, 'link');
});

test('the page loads the text and skips the introduction', async () => {
  const text = readFileSync(doc, 'utf8');
  const blocks = await loadBlocks(async () => ({ ok: true, text: async () => text }));
  assert.equal(blocks[0].kind, 'heading');
});
