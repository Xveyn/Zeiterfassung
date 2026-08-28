[Setup]
AppName=Zeiterfassung
AppVersion={#AppVer}
AppPublisher=Margenheld
AppPublisherURL=https://github.com/Xveyn/Zeiterfassung
DefaultDirName={autopf}\Zeiterfassung
DefaultGroupName=Zeiterfassung
UninstallDisplayIcon={app}\Zeiterfassung.exe
OutputDir=dist
OutputBaseFilename=Zeiterfassung_Setup
SetupIconFile=assets\margenheld-icon.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
; AppMutex-Wert muss exakt zu _APP_MUTEX_NAME in src/main.py passen. Setup
; erkennt darüber eine laufende Instanz und bittet den User, sie manuell zu
; schließen (Retry-Dialog) — statt des Default-Wegs (CloseApplications via
; Restart Manager: WM_QUERYENDSESSION/WM_ENDSESSION/WM_CLOSE), der bei uns
; scheitert: aktives Minimize-to-Tray behandelt das dabei gesendete WM_CLOSE
; nur als Fenster-Verstecken (App._on_close), der Prozess läuft weiter und
; blockiert die .exe-Datei.
AppMutex=ZeiterfassungAppMutex
CloseApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
; --onedir (#118): PyInstaller legt Exe + _internal\ in dist\Zeiterfassung\ ab.
; Den ganzen Ordner rekursiv nach {app} spiegeln — die Exe landet weiterhin als
; {app}\Zeiterfassung.exe, alle Icon-/Registry-/Run-Verweise unten bleiben gültig.
Source: "dist\Zeiterfassung\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
; Für Verknüpfungs-Icons erforderlich: die [Icons]-Sektion nutzt diese Datei als
; IconFilename für Start-Menü und Desktop. Die App liest Assets seit dem Wechsel
; zu get_resource_path() aus dem PyInstaller-Bundel (_internal\assets), nicht von
; hier. Nicht löschen — die Verknüpfungen verlieren sonst ihr Icon.
Source: "assets\margenheld-icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\margenheld-icon.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\Zeiterfassung"; Filename: "{app}\Zeiterfassung.exe"; IconFilename: "{app}\assets\margenheld-icon.ico"
Name: "{group}\Zeiterfassung deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Zeiterfassung"; Filename: "{app}\Zeiterfassung.exe"; IconFilename: "{app}\assets\margenheld-icon.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Optionen:"
Name: "autostart"; Description: "Mit Windows starten (minimiert)"; GroupDescription: "Zusätzliche Optionen:"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Zeiterfassung"; ValueData: """{app}\Zeiterfassung.exe"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
; Der Uninstaller entfernt von sich aus NUR, was das Setup installiert hat.
; Alles, was die App zur Laufzeit in {app} anlegt, bliebe liegen — darunter
; token.json mit einem langlebigen OAuth-Refresh-Token (Gmail-Versand,
; Drive-Sync, ggf. Kalender). Wer die App entfernt, erwartet zu Recht, dass
; dieser Zugriff endet. Diese vier Dateien sind Zugangsdaten, keine
; Nutzerdaten — sie verschwinden deshalb immer und ohne Rückfrage.
;
; Bewusst explizite Namen statt eines Wildcards: die Inno-Doku warnt
; ausdrücklich davor, den {app}-Ordner pauschal leerzuräumen (der Nutzer könnte
; dort eigene Dateien abgelegt haben, und bei einer versehentlichen
; Installation in ein Systemverzeichnis wäre es fatal).
Type: files; Name: "{app}\token.json"
Type: files; Name: "{app}\instance-secret"
Type: files; Name: "{app}\webhooks.json"
Type: files; Name: "{app}\credentials.json"


[Run]
Filename: "{app}\Zeiterfassung.exe"; Description: "Zeiterfassung jetzt starten"; Flags: nowait postinstall skipifsilent

[Code]
// --- Deinstallation aufräumen (#50) ------------------------------------------
// Zwei Dinge, die [UninstallDelete] oben nicht kann: den Autostart-Wert aus der
// Registry entfernen und die Nutzerdaten nur nach Rückfrage löschen.

const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'Zeiterfassung';

var
  HadToken: Boolean;

procedure DeleteUserData();
begin
  DeleteFile(ExpandConstant('{app}\zeiterfassung.json'));
  DeleteFile(ExpandConstant('{app}\reservations.json'));
  DeleteFile(ExpandConstant('{app}\settings.json'));
  DeleteFile(ExpandConstant('{app}\conflicts.json'));
  DeleteFile(ExpandConstant('{app}\sync_history.json'));
  DeleteFile(ExpandConstant('{app}\sync-apply.journal'));
  DelTree(ExpandConstant('{app}\logs'), True, True, True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    // usUninstall feuert, BEVOR die Dateien entfernt werden — hier ist die
    // token.json also noch da und die Frage nach den Nutzerdaten kann noch
    // wirken, bevor der Ordner abgeräumt wird.
    HadToken := FileExists(ExpandConstant('{app}\token.json'));

    // Bedingungslos, unabhängig vom Setup-Task. Der [Registry]-Eintrag trägt
    // zwar uninsdeletevalue, hängt aber an "Tasks: autostart": wer den Task
    // beim Setup NICHT wählt und den Autostart später in den App-Einstellungen
    // einschaltet, schreibt denselben Wertnamen über autostart._enable_windows
    // per winreg — davon hat der Uninstaller keine Aufzeichnung. Der Eintrag
    // blieb dann stehen und zeigte auf eine gelöschte Exe.
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, RunValue);

    // Nutzerdaten nur auf Nachfrage: erfasste Arbeitszeiten sind Monate an
    // Arbeit, die niemand ungefragt verlieren soll. Im Silent-Uninstall wird
    // nicht gefragt und folglich nichts gelöscht — die konservative Variante.
    if not UninstallSilent then
      if MsgBox('Sollen auch die erfassten Arbeitszeiten und die Einstellungen gelöscht werden?'#13#10#13#10 +
                'Nein: die Daten bleiben erhalten und werden von einer Neuinstallation wiedergefunden.',
                mbConfirmation, MB_YESNO) = IDYES then
        DeleteUserData();
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    // Hier statt per "Type: dirifempty" in [UninstallDelete]: dieser Schritt
    // läuft nachweislich nach der gesamten Log-Verarbeitung — die Reihenfolge
    // INNERHALB von [UninstallDelete] ist dagegen nicht dokumentiert, und der
    // Ordner wäre beim regulären Entfernen ohnehin noch nicht leer gewesen.
    // RemoveDir entfernt ihn nur, wenn er leer ist: wer seine Daten behalten
    // hat, behält auch den Ordner.
    RemoveDir(ExpandConstant('{app}'));

    // Nur wer je ein Google-Konto verbunden hatte, bekommt den Hinweis.
    // Das Löschen der token.json beendet den Zugriff auf DIESEM Rechner; die
    // erteilte Freigabe im Google-Konto bleibt bestehen, bis sie dort
    // zurückgezogen wird. Ohne den Hinweis wiegt sich der Nutzer in einer
    // Sicherheit, die er nicht hat.
    if HadToken and (not UninstallSilent) then
      MsgBox('Die gespeicherte Google-Anmeldung wurde von diesem Rechner entfernt.'#13#10#13#10 +
             'Die Freigabe im Google-Konto selbst bleibt bestehen. Zurückziehen lässt '#13#10 +
             'sie sich unter:'#13#10#13#10 +
             'https://myaccount.google.com/permissions',
             mbInformation, MB_OK);
  end;
end;
