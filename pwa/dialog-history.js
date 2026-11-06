// pwa/dialog-history.js
// Zurück-Geste und Zurück-Taste schließen den obersten Dialog (Android: System-Zurück, iOS: Wisch vom Rand).
// Jeder offene Dialog hält einen Eintrag im Browser-Verlauf; die Geste nimmt ihn weg, und wir schließen den Dialog.
// Rein, ohne DOM: Verlauf, `popstate`-Anmeldung und Dialoge kommen herein.

/** Wie lange wir auf das `popstate` eines eigenen `history.back()` warten; danach war keins zu erwarten. */
const SELF_BACK_TTL_MS = 1000;

/** `history`: `pushState`/`back`; `addPopListener(fn)`: ruft `fn` bei jedem `popstate`; `now`: Uhr (Tests). */
export function createDialogHistory({ history, addPopListener, now = Date.now }) {
  const open = [];          // offene Dialoge, der oberste zuletzt
  // Eigene `history.back()` (Ablaufzeit je Aufruf): ihr `popstate` ist keine Geste. Löst ein `back()` nichts aus
  // (Verlauf schon leer), verfällt der Eintrag, sonst verschluckte die nächste echte Geste.
  let selfBack = [];

  const pushEntry = () => history.pushState({ zeitDialog: open.length }, '');

  addPopListener(() => {
    selfBack = selfBack.filter((expires) => expires > now());
    if (selfBack.length > 0) { selfBack.shift(); return; }
    const top = open.at(-1);
    if (!top) return;       // z. B. ein Vorwärts-Eintrag aus einem früheren Dialog: nichts zu schließen
    // Den Eintrag sofort zurückstellen: bleibt der Dialog offen (Rückfrage bei ungespeicherten Änderungen, `cancel`
    // verhindert), passt der Verlauf weiter; schließt er, nimmt sein `close` den Eintrag wieder weg.
    pushEntry();
    const cancel = new Event('cancel', { cancelable: true });   // wie Escape: der Dialog darf widersprechen
    top.dispatchEvent(cancel);
    if (!cancel.defaultPrevented) top.close();
  });

  return {
    /** Vor `showModal()` aufrufen. */
    attach(dialog) {
      open.push(dialog);
      pushEntry();
      dialog.addEventListener('close', () => {
        const index = open.indexOf(dialog);
        if (index === -1) return;
        open.splice(index, 1);
        selfBack.push(now() + SELF_BACK_TTL_MS);
        history.back();
      }, { once: true });
    },
  };
}
