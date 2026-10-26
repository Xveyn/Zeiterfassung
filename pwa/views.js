// pwa/views.js
// Dünne DOM-Schicht: macht aus den Modellen von `view-model.js` Elemente. Keine Logik, die
// sich ohne Browser testen ließe — die steckt in `view-model.js`. Jede Funktion bekommt ihre
// Handler als Parameter; nichts hier kennt den Store oder das Netz.
import { focusByKey, h } from './dom.js';
import { MAX_CATEGORY_LENGTH } from './minutes.js';
import { updateStatusText } from './update-policy.js';
import { MAX_NAME_LENGTH, blockSignature, moveRow, rowsToBlock, timesSummary, validateCategoryRows } from './categories.js';
import {
  SETTINGS_TABS, categoryLabel, categoryOptions, categoryRemovalText, categoryRenameHint, hintKey, nextRow, pickCategory,
  settingsTabLabel, windowRow,
} from './view-model.js';

const button = (label, onclick, className = '', extra = {}) =>
  h('button', { type: 'button', class: className, onclick, ...extra }, label);

// --- Hinweise und Statuszeile -----------------------------------------------------------------------

const ACTION_LABELS = { pair: 'Neu koppeln', rescan: 'QR neu scannen', retry: 'Erneut versuchen', reload: 'Neu laden', conflicts: 'Anzeigen' };

/** Persistenter Container der Hinweise. Er bleibt über alle Renders im Dokument, damit Screenreader
 *  Änderungen ansagen; `patchHints` tauscht nur, was sich geändert hat. */
export function hintsHost() {
  return h('div', { class: 'hints', 'aria-live': 'polite', 'aria-relevant': 'additions text' });
}

function hintElement(hint, handlers) {
  return h('div', { class: `hint ${hint.kind}`, role: hint.kind === 'error' ? 'alert' : 'status', 'data-key': hintKey(hint) },
    h('div', {}, hint.text),
    hint.action && h('div', { class: 'actions' },
      button(ACTION_LABELS[hint.action], () => handlers[hint.action](), 'link', { 'data-focus': `hint-${hint.action}` })));
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
  const sync = button('Jetzt abgleichen', handlers.sync, 'primary', { 'data-focus': 'sync' });
  const element = h('footer', { class: 'statusbar' },
    h('div', { class: 'text', 'aria-live': 'polite' }, connection, pending, last),
    button('Einstellungen', handlers.settings, '', { 'data-focus': 'settings' }),
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

export function pairView({ address, code, deviceName, busy, canScan, canCancel, error }, handlers) {
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
  return h('main', {},
    h('h1', {}, 'Mit dem Desktop koppeln'),
    h('p', { class: 'muted' }, 'Am Desktop: Einstellungen → Mobil → „Gerät koppeln …“. Dann den QR-Code scannen oder Adresse und Kopplungscode eintippen.'),
    canScan && button('QR-Code scannen', handlers.scan, 'primary'),
    h('form', { onsubmit: (event) => { event.preventDefault(); handlers.submit({ address: addressInput.value, code: codeInput.value, deviceName: nameInput.value }); } },
      h('label', { for: 'pair-address' }, 'Adresse des Desktops'), addressInput,
      h('label', { for: 'pair-code' }, 'Kopplungscode'), codeInput,
      h('p', { class: 'muted' }, 'Den Code zeigt der Desktop unter dem QR-Code. Er verschlüsselt die Verbindung.'),
      h('label', { for: 'pair-name' }, 'Name dieses Handys'), nameInput,
      h('div', { class: 'error-text', role: 'alert', id: 'pair-error' }, error || ''),
      h('div', { class: 'buttons' },
        canCancel && button('Abbrechen', handlers.cancel),
        h('button', { type: 'submit', class: 'primary', disabled: busy, 'data-focus': 'pair-submit' }, busy ? 'Koppele …' : 'Koppeln'))));
}

// --- Woche ---------------------------------------------------------------------------------------------

function dayRow(day, handlers) {
  const classes = ['day', day.state, day.isWeekend && 'weekend', day.isToday && 'today', day.beyondWindow && 'future'];
  return h('li', {}, h('button', { type: 'button', class: classes.filter(Boolean).join(' '),
    'aria-label': `${day.weekday} ${day.label}${day.minutesLabel ? `, ${day.minutesLabel} Stunden` : ''}`,
    'data-focus': `day-${day.date}`, onclick: () => handlers.openDay(day.date) },
    h('span', {}, h('div', { class: 'wd' }, day.weekday), h('div', { class: 'date' }, day.label.slice(0, 6))),
    h('div', { class: 'content' },
      h('ul', { class: 'slots' }, day.slots.map((text) => h('li', {}, text))),
      day.reservation && h('ul', { class: 'slots reserved' },
        day.reservation.slots.map((text) => h('li', {}, `geplant ${text}`)))),
    h('span', { class: 'sum' }, day.minutesLabel),
    h('span', { class: 'marks' },
      day.dirty && h('span', { class: 'mark-dirty', title: 'nicht übertragen' }, '● '),
      day.reservation?.dirty && h('span', { class: 'mark-dirty', title: 'Reservierung nicht übertragen' }, '○ '),
      day.conflict && h('span', { class: 'mark-conflict', title: 'Konflikt' }, '⚠')),
    day.error && h('span', { class: 'err' }, day.error),
    day.reservation?.error && h('span', { class: 'err' }, day.reservation.error)));
}

export function weekView(model, handlers) {
  return h('div', { class: 'week' },
    h('div', { class: 'weekbar' },
      button('‹', handlers.previous, '', { 'aria-label': 'Vorherige Woche', 'data-focus': 'previous' }),
      h('div', { class: 'title' }, h('strong', {}, model.title), h('span', { class: 'muted' }, model.range)),
      button('›', handlers.next, '', { 'aria-label': 'Nächste Woche', 'data-focus': 'next' })),
    !model.isCurrent && button('Zur aktuellen Woche', handlers.today, 'link', { 'data-focus': 'today' }),
    h('ul', { class: 'days' }, model.days.map((day) => dayRow(day, handlers))),
    model.older && h('div', { class: 'hint older' },
      h('span', {}, model.older.text),
      model.older.action === 'older' && button(model.older.buttonText, () => handlers.older(model.older.wish), 'link', { 'data-focus': 'older' })),
    h('div', { class: 'total' }, h('span', {}, 'Woche gesamt'), h('span', {}, model.totalLabel)),
    model.pendingMinutes > 0 && h('div', { class: 'total pending' },
      h('span', {}, 'Noch ausstehend'), h('span', {}, model.pendingLabel)));
}

// --- Dialoge -----------------------------------------------------------------------------------------------

function openDialog(dialog) {
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  dialog.showModal();
  return dialog;
}

/** Eine Liste von Slot-Zeilen (Arbeitszeit mit Pause, Reservierung ohne). Der Abschnitt hält seinen
 *  Zustand selbst: Eingaben gehen bei Hintergrund-Renders und beim Wechsel des Reiters nicht verloren.
 *  `onChange` meldet jede Eingabe (der Dialog prüft dann neu). */
function slotSection({ rows, categories, defaults, weekday, withPause, onChange }) {
  const list = h('div', {});
  const state = rows.map((row) => ({ ...row, base: row.base && { ...row.base } }));
  const prefix = withPause ? 'slot' : 'res';       // die Ids beider Abschnitte dürfen nicht kollidieren
  const field = (index, key, label, attrs) => {
    const id = `${prefix}-${index}-${key}`;
    const input = h('input', { id, value: state[index][key], ...attrs,
      oninput: () => { state[index][key] = input.value; onChange(); } });
    return h('div', {}, h('label', { for: id }, label), input);
  };
  // Modal statt <datalist>: auf dem Handy zeigt ein Datalist erst nach Eingabe etwas und filtert nach
  // dem Feldinhalt, und Chips blähen den Editor bei mehreren Slots auf.
  const categoryField = (index) => {
    const id = `${prefix}-${index}-kategorie`;
    const text = h('span', { class: 'text' }, categoryLabel(state[index].kategorie));
    const picker = button([text, h('span', { 'aria-hidden': 'true' }, '▾')], () => {
      categoryPickerDialog({ categories, current: state[index].kategorie }, (name) => {
        pickCategory(state[index], name, defaults, weekday);
        build();                                   // Zeiten können sich geändert haben (Vorbelegung, #288)
        onChange();
        document.getElementById(id)?.focus();
      });
    }, 'picker', { id });
    return h('div', {}, h('label', { for: id }, 'Kategorie'), picker);
  };
  const build = () => {
    list.replaceChildren(...state.map((_, index) => h('fieldset', { class: 'slot' },
      state.length > 1 && button('×', () => { state.splice(index, 1); build(); onChange(); }, 'remove', { 'aria-label': 'Slot entfernen' }),
      h('div', { class: 'row' },
        field(index, 'start', 'von', { type: 'time', step: 60 }),
        field(index, 'end', 'bis', { type: 'time', step: 60 })),
      h('div', { class: 'row' },
        withPause && field(index, 'pause', 'Pause (Min)', { type: 'number', inputmode: 'numeric', min: 0, step: 1 }),
        categoryField(index)))));
  };
  build();
  const element = h('div', {}, list, button('+ Slot', () => { state.push(nextRow(state.at(-1))); build(); onChange(); }));
  return { element, state };
}

/** Tag bearbeiten. Mit `reservation` hat der Dialog zwei Reiter (Arbeitszeit / Reservierung); jeder
 *  hält seinen eigenen Zustand, „Speichern“ und „Tag leeren“ wirken auf den aktiven.
 *  `handlers.save(kind, rows)` liefert `null` bei Erfolg oder eine Fehlermeldung; `kind` ist
 *  `'work'` oder `'reservation'`. */
export function editorDialog({ title, rows, categories, defaults = null, weekday = '', errors = {}, outsideWindow, canClear, validate,
  reservation = null, startWith = 'work' }, handlers) {
  const message = h('div', { class: 'error-text', role: 'alert' }, '');
  const save = h('button', { type: 'submit', class: 'primary' }, 'Speichern');
  const dialog = h('dialog', { 'aria-labelledby': 'editor-title' });
  let active = reservation ? startWith : 'work';

  // Der gespeicherte Fehler gehört zu seinem Reiter und bleibt stehen, bis dort etwas geändert wird.
  const edited = { work: false, reservation: false };
  const refresh = () => {
    const check = active === 'work' ? validate(work.state) : reservation.validate(res.state);
    save.disabled = !check.ok;
    if (errors[active] && !edited[active]) message.textContent = errors[active];
    else message.textContent = check.ok ? '' : check.message;
  };
  const work = slotSection({ rows, categories, defaults, weekday, withPause: true,
    onChange: () => { edited.work = true; refresh(); } });
  const res = reservation && slotSection({ rows: reservation.rows, categories, defaults, weekday,
    withPause: false, onChange: () => { edited.reservation = true; refresh(); } });
  const clearButton = button('Tag leeren', () => handlers.clear(active, dialog), 'link');
  const windowHint = outsideWindow && h('p', { class: 'hint warn' }, 'Dieser Tag liegt außerhalb des Zeitraums, den das Handy vom Desktop kennt. Er kann dort bereits Einträge haben: Speichern ersetzt sie, und nach dem Abgleich ist der Tag hier nicht mehr sichtbar.');
  const tabs = reservation && {
    work: h('button', { type: 'button', role: 'tab', 'data-focus': 'tab-work', onclick: () => show('work') }, 'Arbeitszeit'),
    reservation: h('button', { type: 'button', role: 'tab', 'data-focus': 'tab-reservation', onclick: () => show('reservation') }, 'Reservierung'),
  };
  const show = (kind) => {
    active = kind;
    work.element.hidden = kind !== 'work';
    if (res) res.element.hidden = kind !== 'reservation';
    if (windowHint) windowHint.hidden = kind !== 'work';
    if (tabs) {
      tabs.work.setAttribute('aria-selected', String(kind === 'work'));
      tabs.reservation.setAttribute('aria-selected', String(kind === 'reservation'));
    }
    clearButton.textContent = kind === 'work' ? 'Tag leeren' : 'Reservierung löschen';
    clearButton.hidden = !(kind === 'work' ? canClear : reservation.canClear);
    refresh();
  };

  dialog.append(
    h('form', { method: 'dialog', onsubmit: async (event) => {
      event.preventDefault();
      const failure = await handlers.save(active, active === 'work' ? work.state : res.state);
      if (failure) message.textContent = failure; else dialog.close();
    } },
      h('h2', { id: 'editor-title' }, title),
      tabs && h('div', { class: 'tabs', role: 'tablist' }, tabs.work, tabs.reservation),
      windowHint,
      work.element,
      res && res.element,
      message,
      h('div', { class: 'buttons' },
        clearButton,
        button('Abbrechen', () => dialog.close()),
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
  const apply = button('Übernehmen', () => choose(custom.value.trim()), 'primary');
  const sync = () => { apply.disabled = custom.value.trim() === ''; };
  custom.addEventListener('input', sync);
  custom.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !apply.disabled) { event.preventDefault(); apply.click(); } });
  sync();
  dialog.append(
    h('h2', { id: 'category-title' }, 'Kategorie'),
    h('ul', { class: 'options' },
      row('Keine Kategorie', '', !current),
      categoryOptions(categories, current).map((option) => row(option.name, option.name, option.active))),
    h('label', { for: 'category-custom' }, 'Andere …'),
    h('div', { class: 'custom' }, custom, apply),
    h('div', { class: 'buttons' }, button('Abbrechen', () => dialog.close())));
  return openDialog(dialog);
}

export function confirmDialog({ title, text, confirmLabel }, onConfirm) {
  const dialog = h('dialog', { 'aria-labelledby': 'confirm-title' },
    h('h2', { id: 'confirm-title' }, title), h('p', {}, text),
    h('div', { class: 'buttons' },
      button('Abbrechen', () => dialog.close()),
      button(confirmLabel, () => { dialog.close(); onConfirm(); }, 'primary')));
  return openDialog(dialog);
}

export function conflictsDialog(conflicts, handlers) {
  const dialog = h('dialog', { 'aria-labelledby': 'conflicts-title' },
    h('h2', { id: 'conflicts-title' }, 'Konflikte'),
    h('p', { class: 'muted' }, 'Beide Fassungen sind gespeichert. Gelöst wird am Desktop (Einstellungen → Google → „Konflikte ansehen“).'),
    conflicts.length === 0 && h('p', {}, 'Keine offenen Konflikte.'),
    conflicts.map((conflict) => h('section', {},
      h('h2', {}, conflict.dateLabel),
      conflict.versions.map((version) => h('div', { class: 'version' },
        h('strong', {}, version.who), h('span', { class: 'muted' }, ` · ${version.when}`),
        version.slots.length === 0 ? h('p', {}, 'gelöscht') : h('ul', {}, version.slots.map((text) => h('li', {}, text))),
        h('div', {}, `Summe ${version.minutesLabel}`))),
      button('Zu diesem Tag', () => { dialog.close(); handlers.openDay(conflict.date); }, 'link'))),
    h('div', { class: 'buttons' }, button('Schließen', () => dialog.close())));
  return openDialog(dialog);
}

// --- Einstellungen -----------------------------------------------------------------------------------

/** Reiter „Verbindung“: Stand der Kopplung und des Desktops, Verlauf, Neu koppeln. */
function connectionPanel({ desktopName, desktop, hint = '', address, persistent, tokenUntil, window: windowInfo, push }, { closeThen, handlers }) {
  const windowState = windowRow(windowInfo);
  const resetWindow = button('Auf 90 Tage zurücksetzen', () => closeThen(() => handlers.resetWindow()), '', { 'data-focus': 'reset-window' });
  resetWindow.hidden = !windowState.canReset;
  return h('div', {},
    h('dl', {},
      h('dt', { class: 'muted' }, 'Desktop'), h('dd', {}, desktopName || '—'),
      h('dt', { class: 'muted' }, 'Desktop-Version'), h('dd', {}, desktop?.version || '—'),
      h('dt', { class: 'muted' }, 'Plattform'), h('dd', {}, desktop?.platform || '—'),
      h('dt', { class: 'muted' }, 'Adresse'), h('dd', {}, address || '—'),
      h('dt', { class: 'muted' }, 'Kopplung gültig bis'), h('dd', {}, tokenUntil || '—'),
      h('dt', { class: 'muted' }, 'Dauerhafter Speicher'), h('dd', {}, persistent === null ? 'unbekannt' : persistent ? 'ja' : 'nein'),
      h('dt', { class: 'muted' }, 'Verlauf'), h('dd', {}, windowState.text, ' ', resetWindow)),
    pushSection(push, handlers),
    hint && h('p', { class: 'hint warn', role: 'status' }, hint),
    h('div', { class: 'buttons' },
      button('QR neu scannen / Neu koppeln', () => closeThen(() => handlers.pair()), '', { 'data-focus': 'pair' })));
}

/** Abschnitt „Benachrichtigungen“: Zustand als Text, ein Knopf zum Erlauben oder Ausschalten. Der
 *  Knopf ruft `handlers.setPush(on)` (in der Klick-Geste: die Erlaubnis verlangt sie) und bekommt den
 *  neuen Zustand zurück. */
function pushSection(model, handlers) {
  const text = h('p', { role: 'status', class: 'push-state' }, model.text);
  const test = button('Testbenachrichtigung senden', async () => {
    test.disabled = true;
    text.textContent = 'Sendet …';
    text.textContent = await handlers.testPush();
    test.disabled = false;
  }, '', { 'data-focus': 'push-test' });
  test.hidden = !model.canTest;
  const action = button(model.actionLabel, async () => {
    action.disabled = true;
    const next = await handlers.setPush(model.action === 'enable');
    model = next;
    text.textContent = next.text;
    action.textContent = next.actionLabel;
    action.hidden = !next.action;
    test.hidden = !next.canTest;
    action.disabled = false;
  }, '', { 'data-focus': 'push-toggle' });
  action.hidden = !model.action;
  return h('section', { class: 'push' }, h('h3', {}, 'Benachrichtigungen'), text,
    h('div', { class: 'buttons' }, action, test));
}

/** Reiter „Updates“: Version der Handy-App, Suche, Neuladen, automatisches Einspielen. */
function updatesPanel({ build, update }, { guard, handlers }) {
  const updateStatus = h('dd', { role: 'status' }, updateStatusText(update.state));
  const apply = button('Jetzt neu laden', () => guard(() => handlers.applyUpdate()), 'primary', { 'data-focus': 'apply-update' });
  apply.hidden = update.state !== 'available';
  const check = button('Nach Updates suchen', async () => {
    check.disabled = true;
    updateStatus.textContent = updateStatusText('checking');
    const state = await handlers.checkUpdate();
    updateStatus.textContent = updateStatusText(state);
    apply.hidden = state !== 'available';
    check.disabled = false;
  }, '', { 'data-focus': 'check-update' });
  const auto = h('input', { id: 'auto-update', type: 'checkbox', checked: update.auto,
    onchange: () => handlers.setAutoUpdate(auto.checked) });
  return h('div', {},
    h('dl', {},
      h('dt', { class: 'muted' }, 'Handy-App'), h('dd', {}, build),
      h('dt', { class: 'muted' }, 'Updates'), updateStatus),
    h('div', { class: 'buttons' }, check, apply),
    h('label', { class: 'check', for: 'auto-update' }, auto, ' Updates automatisch einspielen'));
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
  const pending = h('p', { class: 'muted', role: 'status', tabindex: -1, 'data-focus': 'categories-status' }, 'Noch nicht an den Desktop übertragen.');
  pending.hidden = !model.dirty;
  const message = h('div', { class: 'error-text', role: 'alert' }, '');
  const save = button('Speichern', async () => {
    save.disabled = true;
    const failure = await handlers.saveCategories(rows.map((row) => ({ ...row })));
    if (failure) {
      message.textContent = failure;
      save.disabled = false;
      return;
    }
    saved = signatureOf(rows);
    storedError.hidden = true;                    // ein neuer Stand ersetzt den abgelehnten
    pending.textContent = 'Gespeichert — wird beim nächsten Abgleich an den Desktop übertragen.';
    pending.hidden = false;
    refresh();
    pending.focus();                              // „Speichern“ ist jetzt gesperrt und hielte den Fokus nicht
  }, 'primary', { 'data-focus': 'categories-save' });
  const dirty = () => signatureOf(rows) !== saved;
  const refresh = () => {
    const check = validateCategoryRows(rows);
    save.disabled = !model.editable || !dirty() || !check.ok;
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
    const info = [h('strong', { class: 'name' }, row.name.trim() || '(ohne Namen)'), h('span', { class: 'muted summary' }, timesSummary(row))];
    if (!model.editable) return h('li', { class: 'category' }, h('div', { class: 'info' }, info));
    return h('li', { class: 'category' },
      button(info, () => edit(index), 'info', { 'aria-label': `Kategorie „${row.name.trim()}“ bearbeiten`, 'data-focus': `category-${index}` }),
      button('▲', () => move(index, -1), 'move', { 'aria-label': 'Nach oben', disabled: index === 0, 'data-focus': `category-${index}-up` }),
      button('▼', () => move(index, +1), 'move', { 'aria-label': 'Nach unten', disabled: index === rows.length - 1, 'data-focus': `category-${index}-down` }));
  };
  const build = () => {
    list.replaceChildren(...rows.map(rowElement));
    if (rows.length === 0) list.append(h('li', { class: 'muted' }, 'Keine Kategorien.'));
  };
  build();
  refresh();
  const element = h('div', {},
    model.hint && h('p', { class: 'hint warn', role: 'status' }, model.hint),
    storedError,
    list,
    pending,
    model.editable && h('div', { class: 'buttons' },
      button('+ Kategorie', () => categoryEditDialog(emptyCategoryRow(), {
        isNew: true, onDone: (row) => change([...rows, row], [`category-${rows.length}`]),
      }), '', { 'data-focus': 'category-add' }),
      save),
    message);
  return { element, dirty };
}

/** Einstellungen mit drei Reitern (Verbindung / Kategorien / Updates). Die Bereiche werden nur
 *  verborgen, nicht neu gebaut: Eingaben überstehen den Reiterwechsel. Schließen mit ungespeicherten
 *  Kategorien fragt nach. */
export function settingsDialog({ tab = 'connection', connection, updates, categories }, handlers) {
  const dialog = h('dialog', { 'aria-labelledby': 'settings-title', class: 'settings-dialog' });
  let cats = null;
  const guard = (then) => {
    if (!cats?.dirty()) { then(); return; }
    confirmDialog({ title: 'Änderungen verwerfen?', text: 'Die Änderungen an den Kategorien sind noch nicht gespeichert.',
      confirmLabel: 'Verwerfen' }, then);
  };
  const closeThen = (then = () => {}) => guard(() => { dialog.close(); then(); });
  cats = categoriesPanel(categories, handlers);
  const panels = {
    connection: connectionPanel(connection, { closeThen, handlers }),
    categories: cats.element,
    updates: updatesPanel(updates, { guard, handlers }),
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
  };
  // Escape schließt einen Dialog von sich aus; mit ungespeicherten Kategorien erst nachfragen.
  dialog.addEventListener('cancel', (event) => {
    if (!cats.dirty()) return;
    event.preventDefault();
    closeThen();
  });
  dialog.append(
    h('h2', { id: 'settings-title' }, 'Einstellungen'),
    h('div', { class: 'tabs', role: 'tablist' }, SETTINGS_TABS.map((key) => tabs[key])),
    ...SETTINGS_TABS.map((key) => panels[key]),
    h('div', { class: 'buttons' }, button('Schließen', () => closeThen(), '', { 'data-focus': 'settings-close' })));
  show(SETTINGS_TABS.includes(tab) ? tab : 'connection');
  return openDialog(dialog);
}

/** Eine Kategorie bearbeiten (Unterdialog). Arbeitet auf einer Kopie; „Fertig“ gibt sie an
 *  `onDone(row)`, „Löschen“ fragt nach und ruft `onRemove()`. Eine Kategorie „pro Wochentag“ lässt
 *  hier nur Name und Löschen zu, ihre Zeiten wandern unverändert durch. */
export function categoryEditDialog(row, { onDone, onRemove, isNew = false }) {
  const dialog = h('dialog', { 'aria-labelledby': 'category-edit-title', class: 'category-edit-dialog' });
  const draft = { ...row, raw: row.raw && structuredClone(row.raw) };
  const message = h('div', { class: 'error-text', role: 'alert' }, '');
  const done = button('Fertig', () => { dialog.close(); onDone(draft); }, 'primary', { 'data-focus': 'category-done' });
  const refresh = () => {
    const check = validateCategoryRows([draft]);
    done.disabled = !check.ok;
    message.textContent = check.ok ? '' : check.message;
  };
  const field = (key, label, attrs) => {
    const id = `category-edit-${key}`;
    const input = h('input', { id, value: draft[key], ...attrs, oninput: () => { draft[key] = input.value; refresh(); } });
    return h('div', {}, h('label', { for: id }, label), input);
  };
  const times = draft.mode === 'per_day'
    ? h('p', { class: 'hint info' }, 'Pro Wochentag eingestellt — am Desktop bearbeiten.')
    : h('div', {},
      h('p', { class: 'muted' }, 'Leere Felder: der allgemeine Standard gilt.'),
      h('div', { class: 'row' },
        field('start', 'Start', { type: 'time', step: 60, placeholder: 'Standard' }),
        field('end', 'Ende', { type: 'time', step: 60, placeholder: 'Standard' })),
      field('pause', 'Pause (Min)', { type: 'number', inputmode: 'numeric', min: 0, step: 1, placeholder: 'Standard' }));
  const remove = !isNew && button('Löschen', () => confirmDialog({
    title: 'Kategorie löschen?', text: categoryRemovalText(row.name), confirmLabel: 'Löschen',
  }, () => { dialog.close(); onRemove(); }), 'link', { 'data-focus': 'category-remove' });
  dialog.append(
    h('form', { class: 'category-form', onsubmit: (event) => { event.preventDefault(); if (!done.disabled) done.click(); } },
      h('h2', { id: 'category-edit-title' }, isNew ? 'Neue Kategorie' : 'Kategorie bearbeiten'),
      field('name', 'Name', { type: 'text', maxlength: MAX_NAME_LENGTH, autocomplete: 'off' }),
      !isNew && h('p', { class: 'muted' }, categoryRenameHint),
      times,
      message,
      h('div', { class: 'buttons' },
        remove,
        button('Abbrechen', () => dialog.close()),
        done)));
  refresh();
  if (isNew) message.textContent = '';             // ein leerer Name ist hier noch kein Fehler
  return openDialog(dialog);
}

export function scanDialog(onClose) {
  const video = h('video', { playsinline: true, muted: true });
  const message = h('p', { class: 'muted', role: 'status' }, 'Kamera wird gestartet …');
  const dialog = h('dialog', { 'aria-labelledby': 'scan-title' },
    h('h2', { id: 'scan-title' }, 'QR-Code scannen'), video, message,
    h('div', { class: 'buttons' }, button('Abbrechen', () => dialog.close())));
  dialog.addEventListener('close', onClose);
  openDialog(dialog);
  return { dialog, video, message };
}

export function fatalView(text) {
  return h('main', {}, h('h1', {}, 'Zeiterfassung'), h('p', { class: 'hint error', role: 'alert' }, text));
}
