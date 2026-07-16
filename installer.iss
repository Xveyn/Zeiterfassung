[Setup]
AppName=Zeiterfassung
AppVersion={#AppVer}
AppPublisher=Margenheld
AppPublisherURL=https://github.com/margenheld/Zeiterfassung
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
Source: "dist\Zeiterfassung.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
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

[Run]
Filename: "{app}\Zeiterfassung.exe"; Description: "Zeiterfassung jetzt starten"; Flags: nowait postinstall skipifsilent
