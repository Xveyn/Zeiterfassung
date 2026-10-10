// pwa/views.js
// Dünne DOM-Schicht: macht aus den Modellen von `view-model.js` Elemente. Keine Logik, die
// sich ohne Browser testen ließe — die steckt in `view-model.js`. Jede Funktion bekommt ihre
// Handler als Parameter; nichts hier kennt den Store oder das Netz.
import { h } from './dom.js';
import { MAX_CATEGORY_LENGTH } from './minutes.js';
import { categoryLabel, categoryOptions, hintKey } from './view-model.js';

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
    button('Verbindung', handlers.connection, '', { 'data-focus': 'connection' }),
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
    h('ul', { class: 'slots' }, day.state === 'cleared' ? h('li', {}, 'geleert') : day.slots.map((text) => h('li', {}, text))),
    h('span', { class: 'sum' }, day.minutesLabel),
    h('span', { class: 'marks' },
      day.dirty && h('span', { class: 'mark-dirty', title: 'nicht übertragen' }, '● '),
      day.conflict && h('span', { class: 'mark-conflict', title: 'Konflikt' }, '⚠')),
    day.error && h('span', { class: 'err' }, day.error)));
}

export function weekView(model, handlers) {
  return h('div', { class: 'week' },
    h('div', { class: 'weekbar' },
      button('‹', handlers.previous, '', { 'aria-label': 'Vorherige Woche', 'data-focus': 'previous' }),
      h('div', { class: 'title' }, h('strong', {}, model.title), h('span', { class: 'muted' }, model.range)),
      button('›', handlers.next, '', { 'aria-label': 'Nächste Woche', 'data-focus': 'next' })),
    !model.isCurrent && button('Zur aktuellen Woche', handlers.today, 'link', { 'data-focus': 'today' }),
    h('ul', { class: 'days' }, model.days.map((day) => dayRow(day, handlers))),
    h('div', { class: 'total' }, h('span', {}, 'Woche gesamt'), h('span', {}, model.totalLabel)));
}

// --- Dialoge -----------------------------------------------------------------------------------------------

function openDialog(dialog) {
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  dialog.showModal();
  return dialog;
}

/** Tag bearbeiten. Der Dialog hält seine Zeilen selbst (Eingaben gehen bei Hintergrund-Renders
 *  nicht verloren). `handlers.save(rows)` liefert `null` bei Erfolg oder eine Fehlermeldung. */
export function editorDialog({ title, rows, categories, error, outsideWindow, canClear, validate }, handlers) {
  const list = h('div', {});
  const message = h('div', { class: 'error-text', role: 'alert' }, error ?? '');
  const save = h('button', { type: 'submit', class: 'primary' }, 'Speichern');
  const state = rows.map((row) => ({ ...row }));
  const dialog = h('dialog', { 'aria-labelledby': 'editor-title' });

  const refresh = () => {
    const check = validate(state);
    save.disabled = !check.ok;
    if (!error || check.ok) message.textContent = check.ok ? '' : check.message;
  };
  const field = (index, key, label, attrs) => {
    const id = `slot-${index}-${key}`;
    const input = h('input', { id, value: state[index][key], ...attrs,
      oninput: () => { state[index][key] = input.value; refresh(); } });
    return h('div', {}, h('label', { for: id }, label), input);
  };
  // Modal statt <datalist>: auf dem Handy zeigt ein Datalist erst nach Eingabe etwas und filtert nach
  // dem Feldinhalt, und Chips blähen den Editor bei mehreren Slots auf.
  const categoryField = (index) => {
    const id = `slot-${index}-kategorie`;
    const text = h('span', { class: 'text' }, categoryLabel(state[index].kategorie));
    const picker = button([text, h('span', { 'aria-hidden': 'true' }, '▾')], () => {
      categoryPickerDialog({ categories, current: state[index].kategorie }, (name) => {
        state[index].kategorie = name;
        text.textContent = categoryLabel(name);
        refresh();
      });
    }, 'picker', { id });
    return h('div', {}, h('label', { for: id }, 'Kategorie'), picker);
  };
  const build = () => {
    list.replaceChildren(...state.map((_, index) => h('fieldset', { class: 'slot' },
      state.length > 1 && button('×', () => { state.splice(index, 1); build(); refresh(); }, 'remove', { 'aria-label': 'Slot entfernen' }),
      h('div', { class: 'row' },
        field(index, 'start', 'von', { type: 'time', step: 60 }),
        field(index, 'end', 'bis', { type: 'time', step: 60 })),
      h('div', { class: 'row' },
        field(index, 'pause', 'Pause (Min)', { type: 'number', inputmode: 'numeric', min: 0, step: 1 }),
        categoryField(index)))));
  };
  build();
  refresh();

  dialog.append(
    h('form', { method: 'dialog', onsubmit: async (event) => {
      event.preventDefault();
      const failure = await handlers.save(state);
      if (failure) message.textContent = failure; else dialog.close();
    } },
      h('h2', { id: 'editor-title' }, title),
      outsideWindow && h('p', { class: 'hint warn' }, 'Dieser Tag liegt außerhalb des Zeitraums, den das Handy vom Desktop kennt. Er kann dort bereits Einträge haben: Speichern ersetzt sie, und nach dem Abgleich ist der Tag hier nicht mehr sichtbar.'),
      list,
      button('+ Slot', () => { state.push({ start: state.at(-1)?.end ?? '', end: '', pause: '0', kategorie: state.at(-1)?.kategorie ?? '' }); build(); refresh(); }),
      message,
      h('div', { class: 'buttons' },
        canClear && button('Tag leeren', () => handlers.clear(dialog), 'link'),
        button('Abbrechen', () => dialog.close()),
        save)));
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

export function connectionDialog({ desktopName, address, build, persistent, tokenUntil }, handlers) {
  const dialog = h('dialog', { 'aria-labelledby': 'connection-title' },
    h('h2', { id: 'connection-title' }, 'Verbindung'),
    h('dl', {},
      h('dt', { class: 'muted' }, 'Desktop'), h('dd', {}, desktopName || '—'),
      h('dt', { class: 'muted' }, 'Adresse'), h('dd', {}, address || '—'),
      h('dt', { class: 'muted' }, 'Kopplung gültig bis'), h('dd', {}, tokenUntil || '—'),
      h('dt', { class: 'muted' }, 'Dauerhafter Speicher'), h('dd', {}, persistent === null ? 'unbekannt' : persistent ? 'ja' : 'nein'),
      h('dt', { class: 'muted' }, 'Version'), h('dd', {}, build)),
    h('div', { class: 'buttons' },
      button('QR neu scannen / Neu koppeln', () => { dialog.close(); handlers.pair(); }),
      button('Schließen', () => dialog.close(), 'primary')));
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
