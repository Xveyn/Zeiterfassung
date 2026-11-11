// pwa/views.js
// Dünne DOM-Schicht: macht aus den Modellen von `view-model.js` Elemente. Keine Logik, die
// sich ohne Browser testen ließe — die steckt in `view-model.js`. Jede Funktion bekommt ihre
// Handler als Parameter; nichts hier kennt den Store oder das Netz.
import { DEFAULT_RETENTION_DAYS, RETENTION_CHOICES, formatEntry } from './debug-log.js';
import { focusByKey, h } from './dom.js';
import { MAX_CATEGORY_LENGTH, TIME_STEP_MINUTES, formatMinutes, snapPause, snapTime } from './minutes.js';
import { mayStartShift, shiftLabel, shiftWindow, stepsForDistance } from './shift-policy.js';
import { updateStatusText } from './update-policy.js';
import { createDialogHistory } from './dialog-history.js';
import { t } from './i18n.js';
import { PRIVACY_URL } from './relay-client.js';
import { MAX_NAME_LENGTH, blockSignature, moveRow, rowsToBlock, timesSummary, validateCategoryRows } from './categories.js';
import {
  QUICK_END_MINUTES, QUICK_PAUSES, SETTINGS_TABS, addToTime, categoryDisplay, categoryOptions, categoryRemovalText,
  categoryRenameHint, connectionSummary, dayNetMinutes, editorTitle, hintKey, nextRow, pickCategory, pairFields, rowNetMinutes, rowProblems,
  retentionLabel, settingsTabLabel, storageNotice, windowRow,
} from './view-model.js';

const button = (label, onclick, className = '', extra = {}) =>
  h('button', { type: 'button', class: className, onclick, ...extra }, label);

// --- Hinweise und Statuszeile -----------------------------------------------------------------------

const actionLabels = () => ({ pair: t('aktion.neu_koppeln'), rescan: t('hinweis.aktion.rescan'), retry: t('hinweis.aktion.retry'), reload: t('hinweis.aktion.reload'), conflicts: t('hinweis.aktion.conflicts'), persist: t('hinweis.aktion.persist') });

/** Persistenter Container der Hinweise. Er bleibt über alle Renders im Dokument, damit Screenreader
 *  Änderungen ansagen; `patchHints` tauscht nur, was sich geändert hat. */
export function hintsHost() {
  return h('div', { class: 'hints', 'aria-live': 'polite', 'aria-relevant': 'additions text' });
}

function hintElement(hint, handlers) {
  return h('div', { class: `hint ${hint.kind}${hint.dismissible ? ' dismissible' : ''}`, role: hint.kind === 'error' ? 'alert' : 'status', 'data-key': hintKey(hint) },
    h('div', {}, hint.text),
    hint.action && h('div', { class: 'actions' },
      button(actionLabels()[hint.action], () => handlers[hint.action](), 'link', { 'data-focus': `hint-${hint.action}` })),
    hint.dismissible && button('✕', () => handlers.dismiss(hint.id), 'dismiss', { 'aria-label': t('hinweis.schliessen'), 'data-focus': `hint-dismiss-${hint.id}` }));
}

/** Gleicht die Hinweise im Container mit der Liste ab: unveränderte bleiben stehen (nicht erneut
 *  angesagt, Fokus bleibt), nur Entfernte gehen, nur Neue kommen dazu. */
export function patchHints(host, hints, handlers) {
  const keys = hints.map(hintKey);
  for (const child of [...host.children]) {
    if (!keys.includes(child.getAttribute('data-key'))) child.remove();
  }
  hints.forEach((hint, index) => {
    const current = host.children[index];
    if (current && current.getAttribute('data-key') === keys[index]) return;
    host.insertBefore(hintElement(hint, handlers), current ?? null);
  });
}

/** Statuszeile: einmal gebaut, danach nur `update(status)` — die Live-Region bleibt dieselbe, und nur
 *  geänderter Text wird ersetzt. */
export function statusBar(handlers) {
  const connection = h('div', {});
  const pending = h('div', {});
  const last = h('div', { class: 'muted' });
  const sync = button(t('status.jetzt_abgleichen'), handlers.sync, 'primary', { 'data-focus': 'sync' });
  const element = h('footer', { class: 'statusbar' },
    h('div', { class: 'text', 'aria-live': 'polite' }, connection, pending, last),
    button(t('einstellungen.titel'), handlers.settings, '', { 'data-focus': 'settings' }),
    sync);
  const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
  const update = (status) => {
    setText(connection, status.connection);
    connection.className = status.online ? 'online' : 'offline';
    setText(pending, status.pendingText || '');
    pending.hidden = !status.pendingText;
    setText(last, status.lastText);
    sync.disabled = !status.canSync;
  };
  return { element, update };
}

// --- Koppeln ----------------------------------------------------------------------------------------

/** Link auf die Datenschutzhinweise; öffnet in einem neuen Tab, damit die Web-App (und ein halb ausgefülltes
 *  Koppel-Formular) stehen bleibt. */
const privacyLink = (label = t('datenschutz.link')) =>
  h('a', { href: PRIVACY_URL, target: '_blank', rel: 'noopener noreferrer' }, label);

/** Der Einrichtungs-Screen (#496): Logo, Titel, nummerierte Schritte, der eine rote Knopf und, grau und
 *  eingeklappt, die Nebenwege. Ein Nebenweg mit `action` ist ein Knopf, einer ohne nur ein Hinweis. */
function setupView(model, { canCancel }, handlers) {
  const alternative = (alt) => {
    const label = h('span', {}, alt.title, h('small', {}, alt.text));
    return alt.action
      ? h('button', { type: 'button', class: 'alt', onclick: () => handlers[alt.action](), 'data-focus': `setup-${alt.id}` },
        label, h('span', { class: 'chev', 'aria-hidden': 'true' }, '›'))
      : h('div', { class: 'alt info' }, label);
  };
  return h('main', { class: 'setup' },
    h('div', { class: 'setup-hero' },
      h('img', { src: 'icons/icon-192.png', alt: '', width: 84, height: 84 }),
      h('h1', {}, model.title),
      h('p', { class: 'muted' }, model.lead)),
    h('h2', { class: 'setup-heading' }, t('einrichtung.ueberschrift', { count: model.steps.length })),
    h('ol', { class: 'setup-steps' }, model.steps.map((step, index) =>
      h('li', { class: `setup-step ${step.state}` },
        h('span', { class: 'num', 'aria-hidden': 'true' }, String(index + 1)),
        h('div', {}, h('b', {}, step.title), h('span', {}, step.text))))),
    model.scan && button(t('aktion.qr_scannen'), handlers.scan, 'primary', { 'data-focus': 'setup-scan' }),
    model.note && h('p', { class: `hint ${model.note.kind}`, role: 'status' }, model.note.text),
    model.alternatives.length > 0 && h('details', { class: 'setup-more' },
      h('summary', { 'data-focus': 'setup-more' }, t('einrichtung.andere')),
      model.alternatives.map(alternative)),
    canCancel && h('div', { class: 'buttons' }, button(t('aktion.abbrechen'), handlers.cancel, '', { 'data-focus': 'setup-cancel' })),
    h('p', { class: 'setup-foot' }, t('einrichtung.relay_verarbeitet'), privacyLink()));
}

/** Die Koppel-Seite. Mit `setup` (Modell aus `setupModel`) erscheint der Einrichtungs-Screen, sonst das Formular
 *  (Link gelesen, Adresse und Code von Hand, Fehler); „Zurück“ (`canBack`) führt von dort zum Einrichtungs-Screen. */
export function pairView({ address, code, deviceName, busy, canScan, canCancel, canBack = false, error, relay = false, installHint = '', setup = null }, handlers) {
  if (setup) return setupView(setup, { canCancel }, handlers);
  const fields = pairFields({ relay });
  const addressInput = h('input', { id: 'pair-address', name: 'address', value: address, inputmode: 'decimal',
    autocomplete: 'off', placeholder: '192.168.178.20:17654', required: true, 'data-focus': 'pair-address' });
  const codeInput = h('input', { id: 'pair-code', name: 'code', value: code, autocapitalize: 'characters',
    autocomplete: 'off', spellcheck: 'false', maxlength: 48, required: true,
    placeholder: 'K7M2-9QXA-K7M2-9QXA-K7M2-9QXA-K7M2', 'data-focus': 'pair-code' });
  const nameInput = h('input', { id: 'pair-name', name: 'name', value: deviceName, maxlength: 60, autocomplete: 'off', 'data-focus': 'pair-name' });
  // Eingaben sofort merken: ein Hintergrund-Render (online, Sichtbarwerden, Abgleich-Ende) baut das
  // Formular neu und würde sonst alles Getippte verwerfen.
  for (const [input, field] of [[addressInput, 'address'], [codeInput, 'code'], [nameInput, 'deviceName']]) {
    input.addEventListener('input', () => handlers.change(field, input.value));
  }
  const intro = relay
    ? t('kopplung.intro.relay')
    : t('kopplung.intro.lan');
  return h('main', {},
    h('h1', {}, relay ? t('kopplung.titel.relay') : t('kopplung.titel.lan')),
    installHint && h('p', { class: 'hint warn', role: 'status' }, installHint),
    h('p', { class: 'muted' }, intro),
    h('p', { class: 'muted' }, t('kopplung.dienst_hinweis'), privacyLink(), '.'),
    canScan && button(relay ? t('kopplung.anderer_qr') : t('aktion.qr_scannen'), handlers.scan, relay ? '' : 'primary'),
    h('form', { onsubmit: (event) => { event.preventDefault(); handlers.submit({ address: addressInput.value, code: codeInput.value, deviceName: nameInput.value }); } },
      fields.address && h('label', { for: 'pair-address' }, t('kopplung.adresse')), fields.address && addressInput,
      fields.code && h('label', { for: 'pair-code' }, t('kopplung.code')), fields.code && codeInput,
      fields.code && h('p', { class: 'muted' }, t('kopplung.code_hinweis')),
      h('label', { for: 'pair-name' }, t('kopplung.name')), nameInput,
      h('div', { class: 'error-text', role: 'alert', id: 'pair-error' }, error || ''),
      h('div', { class: 'buttons' },
        canCancel && button(t('aktion.abbrechen'), handlers.cancel),
        canBack && button(t('aktion.zurueck'), handlers.back, '', { disabled: busy, 'data-focus': 'pair-back' }),
        h('button', { type: 'submit', class: 'primary', disabled: busy, 'data-focus': 'pair-submit' }, busy ? t('kopplung.koppele') : t('kopplung.koppeln')))));
}

// --- Woche ---------------------------------------------------------------------------------------------

function dayAriaLabel(day) {
  const params = { weekday: day.weekday, label: day.label, minutes: day.minutesLabel };
  if (day.isToday) return day.minutesLabel ? t('woche.tag.aria_heute_stunden', params) : t('woche.tag.aria_heute', params);
  return day.minutesLabel ? t('woche.tag.aria_stunden', params) : t('woche.tag.aria', params);
}

function dayRow(day, handlers) {
  const classes = ['day', day.state, day.isWeekend && 'weekend', day.isToday && 'today', day.beyondWindow && 'future'];
  return h('li', {}, h('button', { type: 'button', class: classes.filter(Boolean).join(' '),
    'aria-label': dayAriaLabel(day),
    'data-focus': `day-${day.date}`, onclick: () => handlers.openDay(day.date) },
    h('span', {}, h('div', { class: 'wd' }, day.weekday), h('div', { class: 'date' }, day.label.slice(0, 6)),
      day.isToday && h('div', { class: 'tag' }, t('woche.heute'))),
    h('div', { class: 'content' },
      day.addHint && h('div', { class: 'add muted' }, day.addHint),
      h('ul', { class: 'slots' }, day.slots.map((text) => h('li', {}, text))),
      day.reservation?.slots.length > 0 && h('ul', { class: 'slots reserved' },
        day.reservation.slots.map((text) => h('li', {}, t('woche.geplant', { text }))))),
    h('span', { class: 'sum' }, day.minutesLabel, day.addHint && h('span', { class: 'plus', 'aria-hidden': 'true' }, '+')),
    h('span', { class: 'marks' },
      day.dirty && h('span', { class: 'mark-dirty', title: t('woche.nicht_uebertragen') }, '● '),
      day.reservation?.dirty && h('span', { class: 'mark-dirty', title: t('woche.reservierung_nicht_uebertragen') }, '○ '),
      day.conflict && h('span', { class: 'mark-conflict', title: t('woche.konflikt') }, '⚠')),
    day.error && h('span', { class: 'err' }, day.error),
    day.reservation?.error && h('span', { class: 'err' }, day.reservation.error)));
}

export function weekView(model, handlers) {
  return h('div', { class: 'week' },
    h('div', { class: 'weekbar' },
      button('‹', handlers.previous, '', { 'aria-label': t('woche.vorherige'), 'data-focus': 'previous' }),
      h('div', { class: 'title' }, h('strong', {}, model.title), h('span', { class: 'muted' }, model.range)),
      button('›', handlers.next, '', { 'aria-label': t('woche.naechste'), 'data-focus': 'next' })),
    !model.isCurrent && button(t('woche.aktuelle'), handlers.today, 'link', { 'data-focus': 'today' }),
    h('ul', { class: 'days' }, model.days.map((day) => dayRow(day, handlers))),
    model.older && h('div', { class: 'hint older' },
      h('span', {}, model.older.text),
      model.older.action === 'older' && button(model.older.buttonText, () => handlers.older(model.older.wish), 'link', { 'data-focus': 'older' })),
    h('div', { class: 'total' }, h('span', {}, t('woche.gesamt')), h('span', {}, model.totalLabel)),
    model.pendingMinutes > 0 && h('div', { class: 'total pending' },
      h('span', {}, t('woche.ausstehend')), h('span', {}, model.pendingLabel)));
}

// --- Dialoge -----------------------------------------------------------------------------------------------

// Zurück-Geste/-Taste schließt den obersten Dialog (`dialog-history.js`). Erst beim ersten Dialog gebaut: das Modul
// soll sich auch ohne `window` laden lassen.
let dialogHistory = null;

function openDialog(dialog) {
  dialogHistory ??= createDialogHistory({ history: window.history, addPopListener: (listener) => window.addEventListener('popstate', listener) });
  dialogHistory.attach(dialog);
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  dialog.showModal();
  return dialog;
}

/** Fußzeile eines Dialogs mit „Löschen“: das Löschen links, „Abbrechen“ und der Hauptknopf rechts als **eine** Gruppe.
 *  Passt alles nicht in eine Zeile (schmales Handy, langer Text wie „Reservierung löschen“), bricht die Gruppe als Ganzes um;
 *  sonst stünde „Speichern“ allein unter „Abbrechen“. `destructive` darf fehlen oder verborgen sein. */
function footerButtons(destructive, cancel, primary) {
  return h('div', { class: 'buttons' }, destructive, h('div', { class: 'button-group' }, cancel, primary));
}

/** Eine Liste von Slot-Zeilen (Arbeitszeit mit Pause, Reservierung ohne). Der Abschnitt hält seinen
 *  Zustand selbst: Eingaben gehen bei Hintergrund-Renders und beim Wechsel des Reiters nicht verloren.
 *  `onChange` meldet jede Eingabe (der Dialog prüft dann neu). */
const SHIFT_LABEL_MS = 900;          // so lange bleibt „+20 min“ nach dem Loslassen stehen
const SHIFT_CLICK_GUARD_MS = 400;    // ein Klick direkt nach dem Zug öffnete sonst die Zeitauswahl

function slotSection({ rows, categories, defaults, weekday, withPause, pauseEnabled = false, shiftStep = 0, onChange }) {
  const list = h('div', {});
  const state = rows.map((row) => ({ ...row, base: row.base && { ...row.base } }));
  const prefix = withPause ? 'slot' : 'res';       // die Ids beider Abschnitte dürfen nicht kollidieren
  const labels = [];                                // Kategorie-Label je Zeile; das `*` folgt jeder Zeiteingabe
  const showPause = withPause || pauseEnabled;
  const refs = [];                                  // je Zeile: Felder, Fehlertext, Netto, Schnellwahl
  const touched = new Set();                        // Zeilen, deren Zeitfeld schon verlassen wurde
  let revealed = false;                             // nach einem Speicherversuch zeigen alle Zeilen ihre Fehler
  const total = h('span', {}, '');
  const totalRow = h('div', { class: 'daysum' }, h('span', {}, t('editor.tag_gesamt')), total);
  // Fehler am Feld, Netto und Schnellwahl folgen jeder Eingabe, ohne die Zeilen neu zu bauen (der Fokus bliebe sonst nicht).
  const update = () => {
    state.forEach((row, index) => {
      const ref = refs[index];
      if (!ref) return;
      const problems = revealed || touched.has(row) ? rowProblems(row) : {};
      ref.start.setAttribute('aria-invalid', String(Boolean(problems.start)));
      ref.end.setAttribute('aria-invalid', String(Boolean(problems.end)));
      ref.error.textContent = problems.start ?? problems.end ?? '';
      ref.fieldset.classList.toggle('bad', Boolean(problems.start || problems.end));
      const net = rowNetMinutes(showPause ? row : { ...row, pause: '0' });
      ref.net.hidden = net === null;
      ref.netValue.textContent = net === null ? '' : `${formatMinutes(net)} h`;
      ref.endChips.forEach(({ chip, minutes }) => { chip.disabled = addToTime(row.start, minutes) === ''; });
      ref.pauseChips.forEach(({ chip, minutes }) => chip.setAttribute('aria-pressed', String(row.pause === String(minutes))));
    });
    totalRow.hidden = state.length < 2;
    total.textContent = formatMinutes(dayNetMinutes(state, { withPause: showPause }));
  };
  const showCategory = (index) => categoryDisplay(state[index], defaults, weekday, withPause);
  const field = (index, key, label, attrs) => {
    const id = `${prefix}-${index}-${key}`;
    const apply = () => {
      state[index][key] = input.value;
      if (labels[index]) labels[index].textContent = showCategory(index);
      update();
      onChange();
    };
    // Zeiten und Pause rasten auf 5 Minuten wie die Auswahl am Desktop: beim Tippen (`input`) bleibt der
    // Wert, wie er ist; erst beim Übernehmen (`change`) wird gerundet.
    const snapper = key === 'pause' ? snapPause : attrs.type === 'time' ? snapTime : null;
    const snap = () => {
      const snapped = snapper(input.value);
      if (snapped !== input.value) { input.value = snapped; apply(); }
    };
    const input = h('input', { id, value: state[index][key], ...attrs, oninput: apply,
      ...(snapper ? { onchange: snap } : {}),
      onblur: () => { touched.add(state[index]); update(); } });
    if (refs[index]) refs[index][key] = input;
    return h('div', {}, h('label', { for: id }, label), input);
  };
  // Ein waagerechter Zug auf den Zeitfeldern verschiebt Start und Ende gemeinsam (#500); die Regeln stehen in
  // `shift-policy.js`. Die Zeile wird dabei nicht neu gebaut: das berührte Feld muss das Ziel der Geste bleiben.
  const watchShift = (row, index, line, hint) => {
    let drag = null;
    let guardUntil = -Infinity;
    let resetTimer = null;
    const finish = (event) => {
      if (!drag || event.pointerId !== drag.id) return;
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
      if (drag.moved) guardUntil = event.timeStamp + SHIFT_CLICK_GUARD_MS;
      drag = null;
      resetTimer = setTimeout(() => { hint.textContent = t('editor.ziehen_hinweis'); hint.classList.remove('live'); }, SHIFT_LABEL_MS);
    };
    line.addEventListener('pointerdown', (event) => {
      if (drag || !mayStartShift({ pointerType: event.pointerType, width: window.innerWidth, startX: event.clientX })) return;
      if (!shiftWindow(row.start, row.end, 0, shiftStep)) return;
      drag = { id: event.pointerId, x: event.clientX, start: row.start, end: row.end, steps: 0, moved: false };
      // Am Fenster: verlässt der Finger den Bildschirm, kommt das Ende nicht mehr in der Zeile an.
      window.addEventListener('pointerup', finish);
      window.addEventListener('pointercancel', finish);
    });
    line.addEventListener('pointermove', (event) => {
      if (!drag || event.pointerId !== drag.id) return;
      const next = shiftWindow(drag.start, drag.end, stepsForDistance(event.clientX - drag.x), shiftStep);
      if (!next || next.steps === drag.steps) return;
      drag.steps = next.steps;
      drag.moved = true;
      row.start = next.start;
      row.end = next.end;
      refs[index].start.value = next.start;
      refs[index].end.value = next.end;
      if (labels[index]) labels[index].textContent = showCategory(index);
      clearTimeout(resetTimer);
      hint.textContent = shiftLabel(next.steps * shiftStep);
      hint.classList.add('live');
      update();
      onChange();
    });
    line.addEventListener('click', (event) => {
      if (event.timeStamp < guardUntil) { event.stopPropagation(); event.preventDefault(); }
    }, true);
  };
  // Modal statt <datalist>: auf dem Handy zeigt ein Datalist erst nach Eingabe etwas und filtert nach
  // dem Feldinhalt, und Chips blähen den Editor bei mehreren Slots auf.
  const categoryField = (index) => {
    const id = `${prefix}-${index}-kategorie`;
    const text = h('span', { class: 'text' }, showCategory(index));
    labels[index] = text;
    const picker = button([text, h('span', { 'aria-hidden': 'true' }, '▾')], () => {
      categoryPickerDialog({ categories, current: state[index].kategorie }, (name) => {
        pickCategory(state[index], name, defaults, weekday);
        build();                                   // Zeiten können sich geändert haben (Vorbelegung, #288)
        onChange();
        document.getElementById(id)?.focus();
      });
    }, 'picker', { id });
    return h('div', {}, h('label', { for: id }, t('editor.kategorie')), picker);
  };
  // Eine Schnellwahl schreibt in die Zeile und baut neu; die Felder zeigen den neuen Wert.
  const chipLabel = (minutes) => (minutes < 60 ? t('editor.chip.minuten', { minutes }) : t('editor.chip.stunden', { hours: minutes / 60 }));
  const build = () => {
    refs.length = 0;
    list.replaceChildren(...state.map((row, index) => {
      const ref = { start: null, end: null, endChips: [], pauseChips: [] };
      refs[index] = ref;
      const startField = field(index, 'start', t('editor.von'), { type: 'time', step: TIME_STEP_MINUTES * 60 });
      const endField = field(index, 'end', t('editor.bis'), { type: 'time', step: TIME_STEP_MINUTES * 60 });
      const endChips = QUICK_END_MINUTES.map((minutes) => {
        const chip = button(chipLabel(minutes), () => {
          row.end = addToTime(row.start, minutes);
          touched.add(row);
          build();
          onChange();
        }, 'chip', { 'aria-label': t('editor.chip.ende_aria', { dauer: chipLabel(minutes) }) });
        ref.endChips.push({ chip, minutes });
        return chip;
      });
      const pauseChips = showPause ? QUICK_PAUSES.map((minutes) => {
        const chip = button(String(minutes), () => {
          row.pause = String(minutes);
          build();
          onChange();
        }, 'chip', { 'aria-label': t('editor.chip.pause_aria', { minutes }) });
        ref.pauseChips.push({ chip, minutes });
        return chip;
      }) : [];
      const timeRow = h('div', { class: shiftStep > 0 ? 'row shiftable' : 'row' }, startField, endField);
      // Für Screenreader verborgen: die Geste gibt es nur per Finger, die Felder bleiben der barrierefreie Weg.
      const shiftHint = shiftStep > 0 && h('div', { class: 'shift-hint', 'aria-hidden': 'true' }, t('editor.ziehen_hinweis'));
      if (shiftHint) watchShift(row, index, timeRow, shiftHint);
      ref.error = h('div', { class: 'field-error', role: 'status' }, '');
      ref.netValue = h('b', {}, '');
      ref.net = h('div', { class: 'net' }, h('span', {}, t('editor.netto')), ref.netValue);
      ref.fieldset = h('fieldset', { class: 'slot' },
        state.length > 1 && h('div', { class: 'slot-head' },
          h('span', { class: 'muted' }, t('editor.slot', { nummer: index + 1 })),
          button('×', () => { state.splice(index, 1); build(); onChange(); }, 'remove', { 'aria-label': t('editor.slot_entfernen', { nummer: index + 1 }) })),
        timeRow,
        shiftHint,
        h('div', { class: 'chips', role: 'group', 'aria-label': t('editor.ende_setzen') }, ...endChips),
        ref.error,
        h('div', { class: 'row' },
          showPause && field(index, 'pause', t('editor.pause_min'), { type: 'number', inputmode: 'numeric', min: 0, step: TIME_STEP_MINUTES }),
          categoryField(index)),
        pauseChips.length > 0 && h('div', { class: 'chips', role: 'group', 'aria-label': t('editor.pause_setzen') }, ...pauseChips),
        ref.net);
      return ref.fieldset;
    }));
    update();
  };
  build();
  const element = h('div', {}, list,
    button(t('editor.slot_hinzu'), () => { state.push(nextRow(state.at(-1))); build(); onChange(); }, 'link'),
    totalRow,
    !withPause && pauseEnabled && h('p', { class: 'muted note' }, 'ⓘ ', t('editor.reservierung_kalender_hinweis')));
  update();
  return { element, state, reveal: () => { revealed = true; update(); } };
}

/** Tag bearbeiten. Mit `reservation` hat der Dialog zwei Reiter (Arbeitszeit / Reservierung); jeder
 *  hält seinen eigenen Zustand, „Speichern“ und „Tag leeren“ wirken auf den aktiven.
 *  `handlers.save(kind, rows)` liefert `null` bei Erfolg oder eine Fehlermeldung; `kind` ist
 *  `'work'` oder `'reservation'`. */
export function editorDialog({ title, rows, categories, defaults = null, weekday = '', errors = {}, lock = null, canClear, validate,
  reservation = null, startWith = 'work', pauseEnabled = false, shiftStep = 0 }, handlers) {
  const message = h('div', { class: 'error-text', role: 'alert' }, '');
  const save = h('button', { type: 'submit', class: 'primary' }, t('aktion.speichern'));
  const dialog = h('dialog', { 'aria-labelledby': 'editor-title' });
  let active = reservation ? startWith : 'work';

  // Der gespeicherte Fehler gehört zu seinem Reiter und bleibt stehen, bis dort etwas geändert wird.
  const edited = { work: false, reservation: false };
  const attempted = { work: false, reservation: false };   // erst nach einem Speicherversuch steht die Meldung unten
  const current = () => (active === 'work' ? work : res);
  const check = () => (active === 'work' ? validate(work.state) : reservation.validate(res.state));
  const refresh = () => {
    // „Speichern“ bleibt anklickbar: ein stummes Grau erklärt nicht, was fehlt. Nur die Sperre (#273) deaktiviert es.
    save.disabled = active === 'work' && Boolean(lock);
    const result = check();
    if (active === 'work' && lock) message.textContent = '';
    else if (errors[active] && !edited[active]) message.textContent = errors[active];
    else message.textContent = attempted[active] && !result.ok ? result.message : '';
  };
  const work = slotSection({ rows, categories, defaults, weekday, withPause: true, shiftStep,
    onChange: () => { edited.work = true; refresh(); } });
  const res = reservation && slotSection({ rows: reservation.rows, categories, defaults, weekday,
    withPause: false, pauseEnabled, shiftStep, onChange: () => { edited.reservation = true; refresh(); } });
  const heading = h('h2', { id: 'editor-title' }, title);
  const clearButton = button(t('editor.tag_leeren'), () => handlers.clear(active, dialog), 'link destructive');
  // Gesperrte Arbeitszeit (#273): statt der Zeilen ein Hinweis, mit dem Ausweg „Ältere Zeiten laden“, wo es ihn gibt.
  const windowHint = lock && h('div', { class: 'hint warn', 'data-focus': 'edit-lock' },
    h('p', {}, lock.text),
    lock.action === 'older' && button(lock.buttonText, () => handlers.loadOlder(), 'primary', { 'data-focus': 'load-older' }));
  const tabs = reservation && {
    work: h('button', { type: 'button', role: 'tab', 'data-focus': 'tab-work', onclick: () => show('work') }, t('editor.tab.arbeitszeit')),
    reservation: h('button', { type: 'button', role: 'tab', 'data-focus': 'tab-reservation', onclick: () => show('reservation') }, t('editor.tab.reservierung')),
  };
  const show = (kind) => {
    active = kind;
    work.element.hidden = kind !== 'work' || Boolean(lock);
    if (res) res.element.hidden = kind !== 'reservation';
    if (windowHint) windowHint.hidden = kind !== 'work';
    if (tabs) {
      tabs.work.setAttribute('aria-selected', String(kind === 'work'));
      tabs.reservation.setAttribute('aria-selected', String(kind === 'reservation'));
    }
    clearButton.textContent = kind === 'work' ? t('editor.tag_leeren') : t('editor.reservierung_loeschen');
    clearButton.hidden = !(kind === 'work' ? canClear : reservation.canClear);
    heading.textContent = editorTitle(title, kind, Boolean(reservation));
    refresh();
  };

  dialog.append(
    h('form', { method: 'dialog', onsubmit: async (event) => {
      event.preventDefault();
      if (!check().ok) {
        attempted[active] = true;
        current().reveal();
        refresh();
        return;
      }
      const failure = await handlers.save(active, active === 'work' ? work.state : res.state);
      if (failure) message.textContent = failure; else dialog.close();
    } },
      heading,
      tabs && h('div', { class: 'tabs', role: 'tablist' }, tabs.work, tabs.reservation),
      windowHint,
      work.element,
      res && res.element,
      message,
      footerButtons(
        clearButton,
        button(t('aktion.abbrechen'), () => dialog.close()),
        save)));
  show(active);
  return openDialog(dialog);
}

/** Kategorie wählen. Antippen einer Zeile übernimmt und schließt sofort; „Andere …“ nimmt freie
 *  Eingabe. `onPick(name)` bekommt `''` für „Keine Kategorie“. */
export function categoryPickerDialog({ categories, current }, onPick) {
  const dialog = h('dialog', { 'aria-labelledby': 'category-title', class: 'picker-dialog' });
  const choose = (name) => { dialog.close(); onPick(name); };
  const row = (label, name, active) => h('li', {},
    h('button', { type: 'button', class: active ? 'option active' : 'option', 'aria-pressed': String(active), onclick: () => choose(name) },
      label, active && h('span', { 'aria-hidden': 'true' }, '✓')));
  const custom = h('input', { id: 'category-custom', type: 'text', maxlength: MAX_CATEGORY_LENGTH, autocomplete: 'off' });
  const apply = button(t('kategorie.uebernehmen'), () => choose(custom.value.trim()), 'primary');
  const sync = () => { apply.disabled = custom.value.trim() === ''; };
  custom.addEventListener('input', sync);
  custom.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !apply.disabled) { event.preventDefault(); apply.click(); } });
  sync();
  dialog.append(
    h('h2', { id: 'category-title' }, t('editor.kategorie')),
    h('ul', { class: 'options' },
      row(t('kategorie.keine'), '', !current),
      categoryOptions(categories, current).map((option) => row(option.name, option.name, option.active))),
    h('label', { for: 'category-custom' }, t('kategorie.andere')),
    h('div', { class: 'custom' }, custom, apply),
    h('div', { class: 'buttons' }, button(t('aktion.abbrechen'), () => dialog.close())));
  return openDialog(dialog);
}

export function confirmDialog({ title, text, confirmLabel }, onConfirm) {
  const dialog = h('dialog', { 'aria-labelledby': 'confirm-title' },
    h('h2', { id: 'confirm-title' }, title), h('p', {}, text),
    h('div', { class: 'buttons' },
      button(t('aktion.abbrechen'), () => dialog.close()),
      button(confirmLabel, () => { dialog.close(); onConfirm(); }, 'primary')));
  return openDialog(dialog);
}

/** Die Rückfrage vor dem Trennen (#499). `dialog.update({ phase, model, error })` zeichnet den Stand neu: `checking` (der
 *  Abgleich läuft), `ready` (Modell aus `unpairDialogModel`), `running` (nach der Bestätigung: alles gesperrt, nicht mehr
 *  schließbar, weder per Escape noch per Zurück-Geste), `error` (wie `ready`, mit Fehlertext). „Abbrechen“ hat den Anfangsfokus. */
export function unpairDialog({ retry, confirm }) {
  const dialog = h('dialog', { 'aria-labelledby': 'unpair-title', class: 'unpair-dialog' });
  let phase = 'checking';
  const body = h('div', {});
  const cancel = button(t('aktion.abbrechen'), () => dialog.close(), '', { 'data-focus': 'unpair-cancel', autofocus: true });
  const retryButton = button(t('trennen.erneut_abgleichen'), () => retry(), '', { 'data-focus': 'unpair-retry' });
  const confirmButton = button(t('trennen.bestaetigen'), () => confirm(), 'primary', { 'data-focus': 'unpair-confirm' });
  const buttons = h('div', { class: 'buttons' }, retryButton, cancel, confirmButton);
  // Läuft die Abmeldung schon, ist sie womöglich unterwegs: dann gibt es kein Zurück.
  dialog.addEventListener('cancel', (event) => { if (phase === 'running') event.preventDefault(); });
  // Chromium vergibt für ein zweites Escape ohne neue Nutzeraktivierung kein `cancel` mehr, sondern schließt: die Taste selbst abfangen.
  dialog.addEventListener('keydown', (event) => { if (phase === 'running' && event.key === 'Escape') event.preventDefault(); });
  dialog.append(h('h2', { id: 'unpair-title' }, t('trennen.titel')), body, buttons);
  dialog.update = ({ phase: next, model = null, error = '' }) => {
    phase = next;
    const running = next === 'running';
    const busy = running || next === 'checking';
    const lines = [];
    if (next === 'checking') lines.push(h('p', { class: 'muted', role: 'status' }, t('trennen.gleicht_ab')));
    if (model) {
      lines.push(h('div', { class: `hint ${model.summary.kind === 'ok' ? 'ok' : 'warn'}`, role: 'status' }, model.summary.text));
      if (model.warnDesktop) lines.push(h('div', { class: 'hint warn', role: 'status' }, model.warnDesktop));
      lines.push(h('ul', { class: 'unpair-folgen' },
        model.notifiesDesktop && h('li', {}, t('trennen.folge.desktop')),
        h('li', {}, t('trennen.folge.daten')),
        h('li', {}, t('trennen.folge.neu_koppeln'))));
    }
    if (running) lines.push(h('p', { class: 'muted', role: 'status' }, t('trennen.laeuft')));
    if (error) lines.push(h('div', { class: 'hint error', role: 'alert' }, error));
    body.replaceChildren(...lines);
    // Nach einem Fehler beim Löschen kein erneuter Abgleich: ein weiterer `put` ersetzte die schon eingereihte Abmeldung.
    retryButton.hidden = !(model?.canRetry && next === 'ready');
    retryButton.disabled = busy;
    cancel.disabled = running;
    confirmButton.disabled = busy || !model;
    if (model) confirmButton.textContent = model.confirmLabel;
  };
  dialog.update({ phase });
  return openDialog(dialog);
}

export function conflictsDialog(conflicts, handlers) {
  const dialog = h('dialog', { 'aria-labelledby': 'conflicts-title' },
    h('h2', { id: 'conflicts-title' }, t('konflikte.titel')),
    h('p', { class: 'muted' }, t('konflikte.hinweis')),
    conflicts.length === 0 && h('p', {}, t('konflikte.keine')),
    conflicts.map((conflict) => h('section', {},
      h('h2', {}, conflict.dateLabel),
      conflict.versions.map((version) => h('div', { class: 'version' },
        h('strong', {}, version.who), h('span', { class: 'muted' }, ` · ${version.when}`),
        version.slots.length === 0 ? h('p', {}, t('konflikte.geloescht')) : h('ul', {}, version.slots.map((text) => h('li', {}, text))),
        h('div', {}, t('konflikte.summe', { summe: version.minutesLabel })))),
      button(t('konflikte.zum_tag'), () => { dialog.close(); handlers.openDay(conflict.date); }, 'link'))),
    h('div', { class: 'buttons' }, button(t('aktion.schliessen'), () => dialog.close())));
  return openDialog(dialog);
}

// --- Einstellungen -----------------------------------------------------------------------------------

/** Reiter „Verbindung“: Stand der Kopplung und des Desktops, Verlauf, Neu koppeln. */
function connectionPanel({ desktopName, desktop, hint = '', address, transport = 'lan', persistent, tokenUntil, window: windowInfo, push, lock, shift,
  language, online = true, lastSyncAt = '' }, { closeThen, handlers }) {
  const windowState = windowRow(windowInfo);
  const resetWindow = button(t('einstellungen.verbindung.zuruecksetzen'), () => closeThen(() => handlers.resetWindow()), '', { 'data-focus': 'reset-window' });
  resetWindow.hidden = !windowState.canReset;
  const summary = connectionSummary({ online, desktopName, lastSyncAt, tokenUntil });
  const notice = h('div', { class: 'hint warn', role: 'status', 'data-focus': 'storage-notice' });
  const showNotice = (refused) => {
    const model = storageNotice(persistent, { refused });
    notice.hidden = !model;
    if (!model) return;
    const ask = model.action && button(t('hinweis.aktion.persist'), async () => {
      ask.disabled = true;
      persistent = await handlers.persist();
      showNotice(!persistent);
    }, 'link', { 'data-focus': 'persist' });
    // Nativ `replaceChildren` macht aus `null` den Text „null“: nur echte Knoten übergeben.
    notice.replaceChildren(...[h('div', {}, model.text), ask ? h('div', { class: 'actions' }, ask) : null].filter(Boolean));
  };
  showNotice(false);
  return h('div', {},
    h('section', { class: 'status-card' },
      h('span', { class: `pill ${summary.kind}` }, `● ${summary.pill}`),
      h('div', { class: 'name' }, summary.name),
      h('div', { class: 'muted' }, summary.detail)),
    notice,
    hint && h('p', { class: 'hint warn', role: 'status' }, hint),
    pushSection(push, handlers),
    lock && lockSection(lock, handlers),
    shift && shiftSection(shift, handlers),
    language && languageSection(language, handlers),
    h('p', { class: 'muted' }, t('einstellungen.verbindung.relay_datenschutz'), privacyLink(), '.'),
    h('details', { class: 'tech' },
      h('summary', {}, t('einstellungen.verbindung.technik')),
      h('dl', {},
        h('dt', { class: 'muted' }, t('einstellungen.verbindung.desktop_version')), h('dd', {}, desktop?.version || '—'),
        h('dt', { class: 'muted' }, t('einstellungen.verbindung.plattform')), h('dd', {}, desktop?.platform || '—'),
        h('dt', { class: 'muted' }, transport === 'relay' ? t('einstellungen.verbindung.verbindung') : t('einstellungen.verbindung.adresse')), h('dd', {}, address || '—'),
        h('dt', { class: 'muted' }, t('einstellungen.verbindung.speicher')), h('dd', {}, persistent === null ? t('einstellungen.verbindung.unbekannt') : persistent ? t('einstellungen.verbindung.ja') : t('einstellungen.verbindung.nein')),
        h('dt', { class: 'muted' }, t('einstellungen.verbindung.verlauf')), h('dd', {}, windowState.text, ' ', resetWindow))),
    h('div', { class: 'buttons' },
      button(t('einstellungen.verbindung.neu_koppeln'), () => closeThen(() => handlers.pair()), '', { 'data-focus': 'pair' })),
    unpairSection({ closeThen, handlers }));
}

/** Abschnitt „Sprache“: die Sprache der PWA, unabhängig vom Desktop (vorerst nur Deutsch). */
function languageSection(model, handlers) {
  const select = h('select', { id: 'app-language', 'data-focus': 'app-language' },
    model.options.map((option) => h('option', { value: option.value }, option.label)));
  select.value = model.value;
  select.addEventListener('change', () => { void handlers.setLanguage(select.value); });
  return h('section', { class: 'language' },
    h('h3', {}, t('einstellungen.sprache.titel')),
    h('label', { for: 'app-language' }, t('einstellungen.sprache.label')), select);
}

/** Abschnitt „Trennen“ (#499): öffnet nur die Rückfrage, löscht nichts. Der Knopf ist kein Hauptknopf (rot umrandet,
 *  nicht gefüllt), damit er nicht neben „Neu koppeln“ zum Antippen einlädt. */
function unpairSection({ closeThen, handlers }) {
  return h('section', { class: 'unpair' },
    h('h3', {}, t('einstellungen.trennen.titel')),
    h('p', { class: 'muted' }, t('einstellungen.trennen.text')),
    button(t('einstellungen.trennen.knopf'), () => closeThen(() => handlers.unpair()), 'unpair-open', { 'data-focus': 'unpair-open' }));
}

/** Abschnitt „Benachrichtigungen“: ein Schalter mit Statuszeile. Der Schalter ruft `handlers.setPush(on)` (in der
 *  Klick-Geste: die Erlaubnis verlangt sie) und bekommt den neuen Zustand zurück; gesperrt oder nicht
 *  unterstützt ist er ausgegraut, und der Text sagt warum. */
function pushSection(model, handlers) {
  const text = h('p', { role: 'status', class: 'push-state muted' }, model.text);
  const test = button(t('einstellungen.push.test'), async () => {
    test.disabled = true;
    text.textContent = t('einstellungen.push.sendet');
    text.textContent = await handlers.testPush();
    test.disabled = false;
  }, '', { 'data-focus': 'push-test' });
  test.hidden = !model.canTest;
  const toggle = h('input', { id: 'push-toggle', type: 'checkbox', role: 'switch', class: 'switch-input', checked: model.on,
    disabled: !model.toggle, 'data-focus': 'push-toggle',
    onchange: async () => {
      toggle.disabled = true;
      const next = await handlers.setPush(toggle.checked);
      toggle.checked = next.on;
      toggle.disabled = !next.toggle;
      text.textContent = next.text;
      test.hidden = !next.canTest;
    } });
  return h('section', { class: 'push' },
    h('h3', {}, t('einstellungen.push.titel')),
    h('label', { class: 'switch', for: 'push-toggle' }, h('span', {}, t('einstellungen.push.schalter')), toggle),
    text, test);
}

/** Abschnitt „Sperre“ (#490): Schalter, Frist und der Hinweis, dass es eine Komfort-Sperre ist. Einschalten legt den Passkey an
 *  und verlangt danach eine Probe-Entsperrung mit frischer Nutzergeste, erst dann gilt die Sperre: Safari verlangt eine Geste
 *  je Abfrage, und eine Sperre, die sich nicht öffnen lässt, wäre eine Falle. Ausschalten verlangt ebenfalls die Entsperrung. */
function lockSection(initial, handlers) {
  let model = initial;
  let pendingId = null;
  const note = h('p', { class: 'muted' });
  const status = h('p', { class: 'muted', role: 'status' });
  const message = h('p', { class: 'hint error', role: 'alert' });
  const toggle = h('input', { id: 'lock-toggle', type: 'checkbox', role: 'switch', class: 'switch-input', 'data-focus': 'lock-toggle' });
  const delay = h('select', { id: 'lock-delay', 'data-focus': 'lock-delay' },
    model.delayOptions.map((option) => h('option', { value: String(option.value) }, option.label)));
  const confirm = button(t('einstellungen.sperre.pruefen'), () => {}, 'primary', { 'data-focus': 'lock-confirm' });
  const cancel = button(t('aktion.abbrechen'), () => {}, '', { 'data-focus': 'lock-cancel' });
  const pending = h('div', { class: 'buttons' }, confirm, cancel);
  const show = (next, { error = '', info = '' } = {}) => {
    model = next;
    toggle.checked = model.on;
    toggle.disabled = !model.canChange || pendingId !== null;
    delay.value = String(model.delayMs);
    delay.disabled = model.delayDisabled || pendingId !== null;
    note.textContent = model.available ? model.note : model.hint;
    status.textContent = info;
    status.hidden = !info;
    message.textContent = error;
    message.hidden = !error;
    pending.hidden = pendingId === null;
  };
  toggle.addEventListener('change', async () => {
    toggle.disabled = true;
    if (!toggle.checked) {
      const result = await handlers.removeLock();
      show(result.model ?? model, { error: result.error });
      toggle.focus();
      return;
    }
    const created = await handlers.createLock();
    if (!created.ok) {
      show(model, { error: created.error });
      toggle.focus();
      return;
    }
    pendingId = created.id;
    show(model, { info: t('einstellungen.sperre.passkey') });
    confirm.focus();
  });
  confirm.addEventListener('click', async () => {
    confirm.disabled = true;
    const result = await handlers.confirmLock(pendingId);
    confirm.disabled = false;
    if (!result.ok) {
      show(model, { error: result.error, info: t('einstellungen.sperre.passkey') });
      return;
    }
    pendingId = null;
    show(result.model);
    toggle.focus();
  });
  cancel.addEventListener('click', () => {
    pendingId = null;
    show(model);
    toggle.focus();
  });
  delay.addEventListener('change', async () => {
    delay.disabled = true;
    show(await handlers.setLockDelay(Number(delay.value)));
    delay.focus();
  });
  show(model);
  return h('section', { class: 'lock' },
    h('h3', {}, t('einstellungen.sperre.titel')),
    h('label', { class: 'switch', for: 'lock-toggle' }, h('span', {}, t('einstellungen.sperre.schalter')), toggle),
    h('label', { for: 'lock-delay' }, t('einstellungen.sperre.frist')), delay,
    note, status, message, pending);
}

/** Abschnitt „Zeiten verschieben“ (#500): Schrittweite des Wischs auf den Zeitfeldern des Tages-Editors, oder aus. */
function shiftSection(model, handlers) {
  const select = h('select', { id: 'shift-step', 'data-focus': 'shift-step' },
    model.options.map((option) => h('option', { value: String(option.value) }, option.label)));
  select.value = String(model.step);
  select.addEventListener('change', async () => {
    select.disabled = true;
    select.value = String(await handlers.setShiftStep(Number(select.value)));
    select.disabled = false;
    select.focus();
  });
  return h('section', { class: 'shift' },
    h('h3', {}, t('einstellungen.verschieben.titel')),
    h('label', { for: 'shift-step' }, t('einstellungen.verschieben.label')), select,
    h('p', { class: 'muted' }, t('einstellungen.verschieben.text')));
}

/** Die Sperre selbst: ein Dialog über allem, was offen ist (ein später geöffneter modaler Dialog liegt weiter oben in der
 *  Top-Layer-Reihenfolge, darunter bleiben Zustand und Eingaben eines geöffneten Editors erhalten). Bewusst **nicht** über
 *  `openDialog`: der hängt jeden Dialog an den Browser-Verlauf, und die Zurück-Geste schlösse dann auch die Sperre.
 *  Escape schließt sie nicht; ein zweites Escape, das Chrome trotz `preventDefault` durchlässt, öffnet sie sofort wieder. */
export function lockDialog(handlers) {
  const message = h('p', { class: 'hint error', role: 'alert' });
  message.hidden = true;
  const unlock = button(t('aktion.entsperren'), async () => {
    unlock.disabled = true;
    const result = await handlers.unlock();
    unlock.disabled = false;
    if (result.ok) return;
    message.textContent = result.text;
    message.hidden = false;
    reset.hidden = false;
    unlock.focus();
  }, 'primary', { 'data-focus': 'unlock' });
  const reset = button(t('neu_koppeln.knopf'), () => confirmDialog({
    title: t('neu_koppeln.titel'),
    text: t('neu_koppeln.text'),
    confirmLabel: t('neu_koppeln.bestaetigen'),
  }, handlers.reset), 'link', { 'data-focus': 'lock-reset' });
  reset.hidden = true;
  const dialog = h('dialog', { 'aria-labelledby': 'lock-title', class: 'lock-dialog' },
    h('h2', { id: 'lock-title' }, t('sperre.titel')),
    h('p', {}, t('sperre.text')),
    message,
    h('div', { class: 'buttons' }, unlock),
    h('div', { class: 'buttons' }, reset));
  dialog.addEventListener('cancel', (event) => event.preventDefault());
  dialog.addEventListener('close', () => { if (handlers.isLocked()) dialog.showModal(); });
  document.body.append(dialog);
  dialog.showModal();
  unlock.focus();
  return dialog;
}

/** Reiter „Updates“: Version der Handy-App, Suche, Neuladen, automatisches Einspielen. */
function updatesPanel({ build, update }, { guard, handlers }) {
  const updateStatus = h('dd', { role: 'status' }, updateStatusText(update.state, update.detail));
  const apply = button(t('einstellungen.updates.neu_laden'), () => guard(() => handlers.applyUpdate()), 'primary', { 'data-focus': 'apply-update' });
  apply.hidden = update.state !== 'available';
  const check = button(t('einstellungen.updates.suchen'), async () => {
    check.disabled = true;
    updateStatus.textContent = updateStatusText('checking');
    const { state, detail } = await handlers.checkUpdate();
    updateStatus.textContent = updateStatusText(state, detail);
    apply.hidden = state !== 'available';
    check.disabled = false;
  }, '', { 'data-focus': 'check-update' });
  // Meldet die Suche einen Fehler wie „ServiceWorker cannot be started“, richtet das den Worker neu ein (#390).
  const repair = button(t('einstellungen.updates.reparieren'), async () => {
    repair.disabled = true;
    check.disabled = true;
    updateStatus.textContent = t('einstellungen.updates.repariert');
    const result = await handlers.repairUpdates();
    if (result.ok) return;                       // die Seite lädt neu
    updateStatus.textContent = result.text;
    repair.disabled = false;
    check.disabled = false;
  }, '', { 'data-focus': 'repair-sw' });
  repair.hidden = update.state === 'unsupported';
  const auto = h('input', { id: 'auto-update', type: 'checkbox', checked: update.auto,
    onchange: () => handlers.setAutoUpdate(auto.checked) });
  return h('div', {},
    h('dl', {},
      h('dt', { class: 'muted' }, t('einstellungen.updates.handy_app')), h('dd', {}, build),
      h('dt', { class: 'muted' }, t('einstellungen.updates.updates')), updateStatus),
    h('div', { class: 'buttons' }, check, apply, repair),
    h('p', { class: 'muted' }, t('einstellungen.updates.reparatur_text')),
    h('label', { class: 'check', for: 'auto-update' }, auto, t('einstellungen.updates.automatisch')));
}

/** Reiter „Debug“: technischer Zustand, Protokoll (neueste zuerst), Haltezeit, Kopieren/Teilen/Löschen.
 *  Die Daten kommen erst beim Zeigen des Reiters über `handlers.loadDebug()` (jedes Zeigen liest neu: ein Fehler,
 *  der bei offenem Dialog entstand, soll dort stehen). Nach Löschen und Haltezeit-Wechsel liest
 *  `handlers.refreshDebug()` die Liste neu. Liefert `{ element, load }`. */
function debugPanel({ handlers }) {
  const info = h('dl', {});
  const list = h('ol', { class: 'debug-log', tabindex: 0, 'aria-label': t('einstellungen.debug.protokoll') });
  const empty = h('p', { class: 'muted' }, t('einstellungen.debug.leer'));
  const memoryNote = h('p', { class: 'hint warn' }, t('einstellungen.debug.nur_speicher'));
  const loading = h('p', { class: 'muted', role: 'status' }, t('einstellungen.debug.laedt'));
  const fill = (rows, isPersistent) => {
    list.replaceChildren(...rows.map((entry) => h('li', {}, formatEntry(entry))));
    list.hidden = rows.length === 0;
    empty.hidden = rows.length > 0;
    memoryNote.hidden = isPersistent !== false;
  };
  fill([], true);
  empty.hidden = true;                        // bis zum ersten Laden weder „leer“ noch Liste behaupten
  const status = h('p', { class: 'muted', role: 'status' }, '');
  let stored = DEFAULT_RETENTION_DAYS;
  const select = h('select', { id: 'debug-retention', onchange: async () => {
    status.textContent = '';
    select.disabled = true;
    try {
      try {
        await handlers.setRetention(Number(select.value));
        stored = Number(select.value);
      } catch {
        select.value = String(stored);
        status.textContent = t('einstellungen.debug.haltezeit_fehler');
        return;
      }
      await refresh();
    } catch {
      status.textContent = t('einstellungen.debug.nicht_lesbar');
    } finally { select.disabled = false; }
  } }, RETENTION_CHOICES.map((days) => h('option', { value: String(days), selected: days === DEFAULT_RETENTION_DAYS }, retentionLabel(days))));
  const refresh = async () => {
    const next = await handlers.refreshDebug();
    fill(next.entries, next.persistent);
  };
  // Der Export liegt erst nach dem Laden vor; bis dahin sind Kopieren und Teilen aus.
  const run = (control, action, failure) => async () => {
    status.textContent = '';
    control.disabled = true;
    try { await action(); } catch { status.textContent = failure; } finally { control.disabled = false; }
  };
  const copy = button(t('einstellungen.debug.kopieren'), () => run(copy, async () => {
    status.textContent = (await handlers.copyDebug()) === 'copied' ? t('einstellungen.debug.kopiert') : t('einstellungen.debug.kopieren_fehler');
  }, t('einstellungen.debug.kopieren_fehler'))(), '', { 'data-focus': 'debug-copy' });
  const share = button(t('einstellungen.debug.teilen'), () => run(share, async () => {
    const result = await handlers.shareDebug();
    status.textContent = { shared: t('einstellungen.debug.geteilt'), downloaded: t('einstellungen.debug.heruntergeladen'), cancelled: t('einstellungen.debug.abgebrochen') }[result] ?? '';
  }, t('einstellungen.debug.teilen_fehler'))(), '', { 'data-focus': 'debug-share' });
  const clearLog = button(t('aktion.loeschen'), () => confirmDialog({ title: t('einstellungen.debug.loeschen_titel'),
    text: t('einstellungen.debug.loeschen_text'), confirmLabel: t('aktion.loeschen') }, async () => {
    status.textContent = '';
    let cleared = false;
    try {
      cleared = (await handlers.clearDebug()) === true;
    } catch {
      cleared = false;
    }
    try { await refresh(); } catch { if (cleared) fill([], true); }
    status.textContent = cleared ? t('einstellungen.debug.geloescht') : t('einstellungen.debug.loeschen_fehler');
  }), '', { 'data-focus': 'debug-clear' });
  for (const control of [copy, share, clearLog, select]) control.disabled = true;
  let latest = 0;
  const load = async () => {
    const mine = ++latest;
    status.textContent = '';
    loading.hidden = false;
    let model;
    try {
      model = await handlers.loadDebug();
    } catch {
      model = { info: [{ label: t('einstellungen.debug.zustand'), value: t('einstellungen.verbindung.unbekannt') }], entries: [], retention: stored, persistent: true };
    }
    if (mine !== latest) return;              // ein neueres Laden ist unterwegs
    info.replaceChildren(...model.info.flatMap(({ label, value }) => [h('dt', { class: 'muted' }, label), h('dd', {}, value)]));
    fill(model.entries, model.persistent);
    stored = model.retention;
    select.value = String(model.retention);
    loading.hidden = true;
    for (const control of [copy, share, clearLog, select]) control.disabled = false;
  };
  const element = h('div', {},
    loading, info,
    h('h3', {}, t('einstellungen.debug.protokoll')),
    memoryNote, empty, list,
    h('label', { for: 'debug-retention' }, t('einstellungen.debug.aufbewahren')), select,
    h('div', { class: 'buttons' }, copy, share, clearLog),
    status,
    h('p', { class: 'muted' }, t('einstellungen.debug.datenschutz')));
  return { element, load };
}

const signatureOf = (rows) => {
  const block = rowsToBlock(rows);
  return blockSignature(block.categories, block.category_times);
};
const emptyCategoryRow = () => ({ name: '', mode: 'general', start: '', end: '', pause: '', raw: null });

/** Reiter „Kategorien“. Hält die Zeilen als eigenen Zustand (eine Kopie des Modells): jede Änderung
 *  bleibt hier, bis „Speichern“ sie an `handlers.saveCategories(rows)` gibt (liefert `null` oder eine
 *  Meldung). `dirty()` sagt dem Dialog, ob beim Schließen nachgefragt werden muss. */
function categoriesPanel(model, handlers) {
  let rows = model.rows.map(({ summary, ...row }) => ({ ...row, raw: row.raw && structuredClone(row.raw) }));
  let saved = signatureOf(rows);
  const list = h('ul', { class: 'categories' });
  const storedError = h('p', { class: 'hint error', role: 'alert' }, model.error || '');
  storedError.hidden = !model.error;
  const pending = h('p', { class: 'muted', role: 'status', tabindex: -1, 'data-focus': 'categories-status' }, t('einstellungen.kategorien.nicht_uebertragen'));
  pending.hidden = !model.dirty;
  const message = h('div', { class: 'error-text', role: 'alert' }, '');
  const save = button(t('aktion.speichern'), async () => {
    save.disabled = true;
    const failure = await handlers.saveCategories(rows.map((row) => ({ ...row })));
    if (failure) {
      message.textContent = failure;
      save.disabled = false;
      return;
    }
    saved = signatureOf(rows);
    storedError.hidden = true;                    // ein neuer Stand ersetzt den abgelehnten
    pending.textContent = t('einstellungen.kategorien.gespeichert');
    pending.hidden = false;
    refresh();
    pending.focus();                              // „Speichern“ ist jetzt gesperrt und hielte den Fokus nicht
  }, 'primary', { 'data-focus': 'categories-save' });
  const dirty = () => signatureOf(rows) !== saved;
  // Die Leiste steht oben und trägt „Speichern“ — sichtbar, sobald etwas geändert ist (der Knopf unten war grau und unscheinbar).
  const dirtyBar = h('div', { class: 'dirty', role: 'status' }, h('span', {}, t('einstellungen.kategorien.ungespeichert')), save);
  const refresh = () => {
    const check = validateCategoryRows(rows);
    save.disabled = !model.editable || !dirty() || !check.ok;
    dirtyBar.hidden = !(model.editable && dirty());
    message.textContent = check.ok ? '' : check.message;
  };
  // Jede Änderung baut die Liste neu, der fokussierte Knopf verschwindet dabei: danach den ersten
  // passenden (nicht gesperrten) Schlüssel fokussieren.
  const change = (next, focusKeys = []) => {
    rows = next;
    build();
    refresh();
    focusKeys.some((key) => focusByKey(element, key));
  };
  const move = (index, direction) => {
    const target = index + direction;
    const [same, other] = direction < 0 ? ['up', 'down'] : ['down', 'up'];
    change(moveRow(rows, index, direction), [`category-${target}-${same}`, `category-${target}-${other}`]);
  };
  const edit = (index) => categoryEditDialog(rows[index], {
    onDone: (row) => change(rows.map((current, i) => (i === index ? row : current)), [`category-${index}`]),
    onRemove: () => {
      const next = rows.filter((_, i) => i !== index);
      change(next, [`category-${Math.min(index, next.length - 1)}`, 'category-add']);
    },
  });
  const rowElement = (row, index) => {
    const info = [h('strong', { class: 'name' }, row.name.trim() || t('einstellungen.kategorien.ohne_namen')), h('span', { class: 'muted summary' }, timesSummary(row))];
    if (!model.editable) return h('li', { class: 'category' }, h('div', { class: 'info' }, info));
    return h('li', { class: 'category' },
      button(info, () => edit(index), 'info', { 'aria-label': t('einstellungen.kategorien.bearbeiten_aria', { name: row.name.trim() }), 'data-focus': `category-${index}` }),
      button('▲', () => move(index, -1), 'move', { 'aria-label': t('einstellungen.kategorien.nach_oben'), disabled: index === 0, 'data-focus': `category-${index}-up` }),
      button('▼', () => move(index, +1), 'move', { 'aria-label': t('einstellungen.kategorien.nach_unten'), disabled: index === rows.length - 1, 'data-focus': `category-${index}-down` }));
  };
  const build = () => {
    list.replaceChildren(...rows.map(rowElement));
    if (rows.length === 0) list.append(h('li', { class: 'muted' }, t('einstellungen.kategorien.keine')));
  };
  build();
  refresh();
  const element = h('div', {},
    model.hint && h('p', { class: 'hint warn', role: 'status' }, model.hint),
    storedError,
    dirtyBar,
    list,
    pending,
    message,
    model.editable && h('div', { class: 'buttons' },
      button(t('einstellungen.kategorien.neu'), () => categoryEditDialog(emptyCategoryRow(), {
        isNew: true, onDone: (row) => change([...rows, row], [`category-${rows.length}`]),
      }), '', { 'data-focus': 'category-add' })));
  return { element, dirty };
}

/** Einstellungen mit vier Reitern (Verbindung / Kategorien / Updates / Debug). Die Bereiche werden nur
 *  verborgen, nicht neu gebaut: Eingaben überstehen den Reiterwechsel. Schließen mit ungespeicherten
 *  Kategorien fragt nach. */
export function settingsDialog({ tab = 'connection', connection, updates, categories }, handlers) {
  const dialog = h('dialog', { 'aria-labelledby': 'settings-title', class: 'settings-dialog' });
  let cats = null;
  const guard = (then) => {
    if (!cats?.dirty()) { then(); return; }
    confirmDialog({ title: t('einstellungen.kategorien.verwerfen_titel'), text: t('einstellungen.kategorien.verwerfen_text'),
      confirmLabel: t('aktion.verwerfen') }, then);
  };
  const closeThen = (then = () => {}) => guard(() => { dialog.close(); then(); });
  cats = categoriesPanel(categories, handlers);
  const debug = debugPanel({ handlers });
  const panels = {
    connection: connectionPanel(connection, { closeThen, handlers }),
    categories: cats.element,
    updates: updatesPanel(updates, { guard, handlers }),
    debug: debug.element,
  };
  const tabs = Object.fromEntries(SETTINGS_TABS.map((key) => [key,
    h('button', { type: 'button', role: 'tab', id: `settings-tab-${key}`, 'aria-controls': `settings-panel-${key}`,
      'data-focus': `settings-tab-${key}`, onclick: () => show(key) }, settingsTabLabel(key))]));
  for (const key of SETTINGS_TABS) {
    panels[key].setAttribute('role', 'tabpanel');
    panels[key].id = `settings-panel-${key}`;
    panels[key].setAttribute('aria-labelledby', `settings-tab-${key}`);
  }
  const show = (key) => {
    for (const other of SETTINGS_TABS) {
      panels[other].hidden = other !== key;
      tabs[other].setAttribute('aria-selected', String(other === key));
    }
    if (key === 'debug') void debug.load();      // jedes Zeigen liest neu
  };
  // Escape schließt einen Dialog von sich aus; mit ungespeicherten Kategorien erst nachfragen.
  dialog.addEventListener('cancel', (event) => {
    if (!cats.dirty()) return;
    event.preventDefault();
    closeThen();
  });
  // Kopfzeile mit ‹ (auf schmalen Bildschirmen füllt der Dialog den Schirm, dort ersetzt sie „Schließen“ unten); der Inhalt scrollt.
  dialog.append(
    h('div', { class: 'settings-head' },
      button('‹', () => closeThen(), 'back', { 'aria-label': t('aktion.zurueck'), 'data-focus': 'settings-back' }),
      h('h2', { id: 'settings-title' }, t('einstellungen.titel'))),
    h('div', { class: 'settings-body' },
      h('div', { class: 'tabs', role: 'tablist' }, SETTINGS_TABS.map((key) => tabs[key])),
      ...SETTINGS_TABS.map((key) => panels[key])),
    h('div', { class: 'buttons' }, button(t('aktion.schliessen'), () => closeThen(), '', { 'data-focus': 'settings-close' })));
  const initial = SETTINGS_TABS.includes(tab) ? tab : 'connection';
  show(initial);
  tabs[initial].autofocus = true;                 // Anfangsfokus auf den Reiter, nicht auf das ‹ in der Kopfzeile
  return openDialog(dialog);
}

/** Eine Kategorie bearbeiten (Unterdialog). Arbeitet auf einer Kopie; „Fertig“ gibt sie an
 *  `onDone(row)`, „Löschen“ fragt nach und ruft `onRemove()`. Eine Kategorie „pro Wochentag“ lässt
 *  hier nur Name und Löschen zu, ihre Zeiten wandern unverändert durch. */
export function categoryEditDialog(row, { onDone, onRemove, isNew = false }) {
  const dialog = h('dialog', { 'aria-labelledby': 'category-edit-title', class: 'category-edit-dialog' });
  const draft = { ...row, raw: row.raw && structuredClone(row.raw) };
  const message = h('div', { class: 'error-text', role: 'alert' }, '');
  const done = button(t('aktion.fertig'), () => { dialog.close(); onDone(draft); }, 'primary', { 'data-focus': 'category-done' });
  const refresh = () => {
    const check = validateCategoryRows([draft]);
    done.disabled = !check.ok;
    message.textContent = check.ok ? '' : check.message;
  };
  const field = (key, label, attrs) => {
    const id = `category-edit-${key}`;
    const snapper = key === 'pause' ? snapPause : attrs.type === 'time' ? snapTime : null;
    const snap = () => {
      const snapped = snapper(input.value);
      if (snapped !== input.value) { input.value = snapped; draft[key] = snapped; refresh(); }
    };
    const input = h('input', { id, value: draft[key], ...attrs, oninput: () => { draft[key] = input.value; refresh(); },
      ...(snapper ? { onchange: snap } : {}) });
    return h('div', {}, h('label', { for: id }, label), input);
  };
  const times = draft.mode === 'per_day'
    ? h('p', { class: 'hint info' }, t('kategorie_dialog.pro_wochentag'))
    : h('div', {},
      h('p', { class: 'muted' }, t('kategorie_dialog.leer_standard')),
      h('div', { class: 'row' },
        field('start', t('kategorie_dialog.start'), { type: 'time', step: TIME_STEP_MINUTES * 60, placeholder: t('kategorie_dialog.standard') }),
        field('end', t('kategorie_dialog.ende'), { type: 'time', step: TIME_STEP_MINUTES * 60, placeholder: t('kategorie_dialog.standard') })),
      field('pause', t('editor.pause_min'), { type: 'number', inputmode: 'numeric', min: 0, step: TIME_STEP_MINUTES, placeholder: t('kategorie_dialog.standard') }));
  const remove = !isNew && button(t('aktion.loeschen'), () => confirmDialog({
    title: t('kategorie_dialog.loeschen_titel'), text: categoryRemovalText(row.name), confirmLabel: t('aktion.loeschen'),
  }, () => { dialog.close(); onRemove(); }), 'link destructive', { 'data-focus': 'category-remove' });
  dialog.append(
    h('form', { class: 'category-form', onsubmit: (event) => { event.preventDefault(); if (!done.disabled) done.click(); } },
      h('h2', { id: 'category-edit-title' }, isNew ? t('kategorie_dialog.neu') : t('kategorie_dialog.bearbeiten')),
      field('name', t('kategorie_dialog.name'), { type: 'text', maxlength: MAX_NAME_LENGTH, autocomplete: 'off' }),
      !isNew && h('p', { class: 'muted' }, categoryRenameHint),
      times,
      message,
      footerButtons(
        remove,
        button(t('aktion.abbrechen'), () => dialog.close()),
        done)));
  refresh();
  if (isNew) message.textContent = '';             // ein leerer Name ist hier noch kein Fehler
  return openDialog(dialog);
}

export function scanDialog(onClose) {
  const video = h('video', { playsinline: true, muted: true });
  const message = h('p', { class: 'muted', role: 'status' }, t('scan.kamera_startet'));
  const dialog = h('dialog', { 'aria-labelledby': 'scan-title' },
    h('h2', { id: 'scan-title' }, t('aktion.qr_scannen')), video, message,
    h('div', { class: 'buttons' }, button(t('aktion.abbrechen'), () => dialog.close())));
  dialog.addEventListener('close', onClose);
  openDialog(dialog);
  return { dialog, video, message };
}

export function fatalView(text) {
  return h('main', {}, h('h1', {}, t('app.titel')), h('p', { class: 'hint error', role: 'alert' }, text));
}

/** Der Speicher enthält verschlüsselte Daten, die sich nicht öffnen lassen (`vault.js`, `describeVaultError`).
 *  Nichts wird still gelöscht: „Neu koppeln“ fragt nach und verwirft die lokalen Daten erst dann. */
export function vaultView({ text, canReset }, handlers) {
  return h('main', {}, h('h1', {}, t('app.titel')), h('p', { class: 'hint error', role: 'alert' }, text),
    h('div', { class: 'buttons' },
      button(t('vault.neu_laden'), handlers.reload),
      canReset && button(t('aktion.neu_koppeln'), () => confirmDialog({
        title: t('neu_koppeln.titel'),
        text: t('neu_koppeln.text'),
        confirmLabel: t('neu_koppeln.bestaetigen'),
      }, handlers.reset), 'primary')));
}
