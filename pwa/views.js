// pwa/views.js
// Dünne DOM-Schicht: macht aus den Modellen von `view-model.js` Elemente. Keine Logik, die
// sich ohne Browser testen ließe — die steckt in `view-model.js`. Jede Funktion bekommt ihre
// Handler als Parameter; nichts hier kennt den Store oder das Netz.
import { h } from './dom.js';
import { MAX_CATEGORY_LENGTH } from './minutes.js';

const button = (label, onclick, className = '', extra = {}) =>
  h('button', { type: 'button', class: className, onclick, ...extra }, label);

// --- Hinweise und Statuszeile -----------------------------------------------------------------------

const ACTION_LABELS = { pair: 'Neu koppeln', rescan: 'QR neu scannen', retry: 'Erneut versuchen', reload: 'Neu laden', conflicts: 'Anzeigen' };

export function hintsView(hints, handlers) {
  return h('div', { class: 'hints' }, hints.map((hint) => h('div', { class: `hint ${hint.kind}`, role: hint.kind === 'error' ? 'alert' : 'status' },
    h('div', {}, hint.text),
    hint.action && h('div', { class: 'actions' },
      button(ACTION_LABELS[hint.action], () => handlers[hint.action](), 'link')))));
}

export function statusBar(status, handlers) {
  return h('footer', { class: 'statusbar' },
    h('div', { class: 'text', 'aria-live': 'polite' },
      h('div', { class: status.online ? 'online' : 'offline' }, status.connection),
      status.pendingText && h('div', {}, status.pendingText),
      h('div', { class: 'muted' }, status.lastText)),
    button('Verbindung', handlers.connection),
    button('Jetzt abgleichen', handlers.sync, 'primary', { disabled: !status.canSync }));
}

// --- Koppeln ----------------------------------------------------------------------------------------

export function pairView({ address, code, deviceName, busy, canScan, canCancel }, handlers) {
  const addressInput = h('input', { id: 'pair-address', name: 'address', value: address, inputmode: 'decimal',
    autocomplete: 'off', placeholder: '192.168.178.20:17654', required: true });
  const codeInput = h('input', { id: 'pair-code', name: 'code', value: code, autocapitalize: 'characters',
    autocomplete: 'off', spellcheck: 'false', placeholder: 'K7M2-9QXA', required: true });
  const nameInput = h('input', { id: 'pair-name', name: 'name', value: deviceName, maxlength: 60, autocomplete: 'off' });
  return h('main', {},
    h('h1', {}, 'Mit dem Desktop koppeln'),
    h('p', { class: 'muted' }, 'Am Desktop: Einstellungen → Mobil → „Gerät koppeln …“. Dann den QR-Code scannen oder Adresse und Code eintippen.'),
    canScan && button('QR-Code scannen', handlers.scan, 'primary'),
    h('form', { onsubmit: (event) => { event.preventDefault(); handlers.submit({ address: addressInput.value, code: codeInput.value, deviceName: nameInput.value }); } },
      h('label', { for: 'pair-address' }, 'Adresse des Desktops'), addressInput,
      h('label', { for: 'pair-code' }, 'Code'), codeInput,
      h('label', { for: 'pair-name' }, 'Name dieses Handys'), nameInput,
      h('div', { class: 'error-text', role: 'alert', id: 'pair-error' }),
      h('div', { class: 'buttons' },
        canCancel && button('Abbrechen', handlers.cancel),
        h('button', { type: 'submit', class: 'primary', disabled: busy }, busy ? 'Koppele …' : 'Koppeln'))));
}

export function setPairError(text) {
  const element = document.getElementById('pair-error');
  if (element) element.textContent = text;
}

// --- Woche ---------------------------------------------------------------------------------------------

function dayRow(day, handlers) {
  const classes = ['day', day.state, day.isWeekend && 'weekend', day.isToday && 'today', day.beyondWindow && 'future'];
  return h('li', {}, h('button', { type: 'button', class: classes.filter(Boolean).join(' '),
    'aria-label': `${day.weekday} ${day.label}${day.minutesLabel ? `, ${day.minutesLabel} Stunden` : ''}`,
    onclick: () => handlers.openDay(day.date) },
    h('span', {}, h('div', { class: 'wd' }, day.weekday), h('div', { class: 'date' }, day.label.slice(0, 6))),
    h('ul', { class: 'slots' }, day.state === 'cleared' ? h('li', {}, 'geleert') : day.slots.map((text) => h('li', {}, text))),
    h('span', { class: 'sum' }, day.minutesLabel),
    h('span', { class: 'marks' },
      day.dirty && h('span', { class: 'mark-dirty', title: 'nicht übertragen' }, '● '),
      day.conflict && h('span', { class: 'mark-conflict', title: 'Konflikt' }, '⚠')),
    day.error && h('span', { class: 'err' }, day.error)));
}

export function weekView(model, handlers) {
  return h('main', {},
    h('div', { class: 'weekbar' },
      button('‹', handlers.previous, '', { 'aria-label': 'Vorherige Woche' }),
      h('div', { class: 'title' }, h('strong', {}, model.title), h('span', { class: 'muted' }, model.range)),
      button('›', handlers.next, '', { 'aria-label': 'Nächste Woche' })),
    !model.isCurrent && button('Zur aktuellen Woche', handlers.today, 'link'),
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
export function editorDialog({ title, rows, categories, error, beyondWindow, canClear, validate }, handlers) {
  const list = h('div', {});
  const message = h('div', { class: 'error-text', role: 'alert' }, error ?? '');
  const datalist = h('datalist', { id: 'categories' }, categories.map((name) => h('option', { value: name })));
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
  const build = () => {
    list.replaceChildren(...state.map((_, index) => h('fieldset', { class: 'slot' },
      state.length > 1 && button('×', () => { state.splice(index, 1); build(); refresh(); }, 'remove', { 'aria-label': 'Slot entfernen' }),
      h('div', { class: 'row' },
        field(index, 'start', 'von', { type: 'time', step: 60 }),
        field(index, 'end', 'bis', { type: 'time', step: 60 })),
      h('div', { class: 'row' },
        field(index, 'pause', 'Pause (Min)', { type: 'number', inputmode: 'numeric', min: 0, step: 1 }),
        field(index, 'kategorie', 'Kategorie', { type: 'text', list: 'categories', maxlength: MAX_CATEGORY_LENGTH, autocomplete: 'off' })))));
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
      beyondWindow && h('p', { class: 'hint warn' }, 'Dieser Tag liegt nach morgen: am Desktop gespeichert, nach dem nächsten Abgleich aber nicht mehr hier sichtbar.'),
      list, datalist,
      button('+ Slot', () => { state.push({ start: state.at(-1)?.end ?? '', end: '', pause: '0', kategorie: state.at(-1)?.kategorie ?? '' }); build(); refresh(); }),
      message,
      h('div', { class: 'buttons' },
        canClear && button('Tag leeren', () => handlers.clear(dialog), 'link'),
        button('Abbrechen', () => dialog.close()),
        save)));
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
