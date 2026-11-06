// pwa/test/debug-info.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { capped, describeEnvironment, workerFromRegistration } from '../debug-info.js';

const CHROME_ANDROID = 'Mozilla/5.0 (Linux; Android 10; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36';
const FIREFOX_ANDROID = 'Mozilla/5.0 (Android 13; Mobile; SM-S918B; rv:128.0) Gecko/128.0 Firefox/128.0';
const LABELS = ['Browser', 'Betriebssystem', 'Als App installiert', 'Online', 'Sprache', 'Bildschirm', 'Build',
  'Service Worker', 'Benachrichtigungen', 'Speicher', 'Kopplungsweg', 'Protokoll'];

const asMap = (lines) => Object.fromEntries(lines.map((line) => [line.label, line.value]));

test('Chrome auf Android: Version aus dem UA, Android-Version aus platformVersion', () => {
  const map = asMap(describeEnvironment({ userAgent: CHROME_ANDROID, platformVersion: '14.0.0' }));
  assert.equal(map.Browser, 'Chrome 131');
  assert.equal(map.Betriebssystem, 'Android 14');
});

test('Firefox auf Android', () => {
  const map = asMap(describeEnvironment({ userAgent: FIREFOX_ANDROID }));
  assert.equal(map.Browser, 'Firefox 128');
  assert.equal(map.Betriebssystem, 'Android 13');
});

test('kein Gerätemodell in Labels oder Werten', () => {
  for (const userAgent of [CHROME_ANDROID, FIREFOX_ANDROID]) {
    const lines = describeEnvironment({ userAgent, platformVersion: '14.0.0' });
    for (const { label, value } of lines) {
      assert.doesNotMatch(label + value, /Pixel|SM-S918B|SM-/);
    }
  }
});

test('alles fehlt: zwölf Zeilen, jede unbekannt', () => {
  for (const env of [undefined, {}, {
    userAgent: null, userAgentData: null, platformVersion: null, standalone: null, online: null, language: null,
    screen: null, build: null, worker: null, notification: null, subscribed: null, storage: null, pairing: null, protocol: null,
  }]) {
    const lines = describeEnvironment(env);
    assert.deepEqual(lines.map((line) => line.label), LABELS);
    assert.ok(lines.every((line) => line.value === 'unbekannt'), JSON.stringify(lines));
  }
});

test('Speicher', () => {
  assert.equal(asMap(describeEnvironment({ storage: { persisted: true, usage: 8388608 } })).Speicher, 'dauerhaft ja, 8 MB');
  assert.equal(asMap(describeEnvironment({ storage: { persisted: false, usage: null } })).Speicher, 'dauerhaft nein');
});

test('Texte der übrigen Zeilen', () => {
  const map = asMap(describeEnvironment({
    userAgent: CHROME_ANDROID, standalone: true, online: false, language: 'de-DE', screen: { width: 412, height: 915 },
    build: '12/1.27.0 (a1b2c3d)', worker: { active: true, waiting: false }, notification: 'granted', subscribed: true,
    pairing: 'relay', protocol: 2,
  }));
  assert.equal(map['Als App installiert'], 'ja');
  assert.equal(map.Online, 'nein');
  assert.equal(map.Sprache, 'de-DE');
  assert.equal(map.Bildschirm, '412 × 915');
  assert.equal(map.Build, '12/1.27.0 (a1b2c3d)');
  assert.equal(map['Service Worker'], 'aktiv');
  assert.equal(map.Benachrichtigungen, 'erlaubt, Abo ja');
  assert.equal(map.Kopplungsweg, 'Relay');
  assert.equal(map.Protokoll, '2');
  assert.equal(asMap(describeEnvironment({ standalone: false, online: true, pairing: 'lan' }))['Als App installiert'], 'nein');
  assert.equal(asMap(describeEnvironment({ pairing: 'lan' })).Kopplungsweg, 'LAN');
});

test('Service Worker und Benachrichtigungen: alle Zustände', () => {
  const worker = (w) => asMap(describeEnvironment({ worker: w }))['Service Worker'];
  assert.equal(worker({ active: true, waiting: true }), 'wartet auf Neustart');
  assert.equal(worker({ active: false, waiting: false }), 'nicht registriert');
  const note = (notification, subscribed) => asMap(describeEnvironment({ notification, subscribed })).Benachrichtigungen;
  assert.equal(note('denied', null), 'blockiert');
  assert.equal(note('default', null), 'nicht gefragt');
  assert.equal(note('granted', false), 'erlaubt, Abo nein');
});

test('keine Adresse, URL oder IP in den Werten', () => {
  const lines = describeEnvironment({
    userAgent: `${CHROME_ANDROID} http://192.168.1.5:8080`, build: '12/1.27.0 (a1b2c3d)', language: 'de-DE',
    screen: { width: 412, height: 915 }, protocol: 2, pairing: 'lan', platformVersion: '14.0.0',
  });
  for (const { value } of lines) {
    assert.doesNotMatch(value, /http|:\d{2,5}\b|\d+\.\d+\.\d+\.\d+/);
  }
});

test('workerFromRegistration: keine Registrierung ist etwas anderes als eine gescheiterte Abfrage', () => {
  const state = (reg) => asMap(describeEnvironment({ worker: workerFromRegistration(reg) }))['Service Worker'];
  assert.equal(state(undefined), 'nicht registriert');
  assert.equal(state(null), 'unbekannt');
  assert.equal(state({ active: {}, waiting: null }), 'aktiv');
  assert.equal(state({ active: {}, waiting: {} }), 'wartet auf Neustart');
});

test('capped: Ergebnis, undefined bleibt undefined, Fehler und Zeitüberschreitung ergeben null', async () => {
  assert.equal(await capped(async () => 5, 50), 5);
  assert.equal(await capped(() => undefined, 50), undefined);
  assert.equal(await capped(() => { throw new Error('x'); }, 50), null);
  assert.equal(await capped(() => new Promise(() => {}), 20), null);
});

test('capped: unabhängige Abfragen laufen nebeneinander, die Grenze gilt für alle zusammen', async () => {
  const start = Date.now();
  const hang = () => new Promise(() => {});
  await Promise.all([capped(hang, 100), capped(hang, 100), capped(hang, 100), capped(hang, 100)]);
  assert.ok(Date.now() - start < 250);
});
