; Inno Setup script for the Bendo installer.
; Build:  ISCC.exe Bendo_installer.iss   (after building dist\Bendo.exe)
; Output: installer\Bendo-Setup-<version>.exe
;
; dist\Bendo.exe is already fully self-contained (Python + all libraries
; are bundled by PyInstaller), so the installer's job is the setup
; experience: Program Files install, Start Menu / desktop shortcuts, an
; uninstaller in "Apps & features", and cleanup of the system artifacts
; Bendo creates (startup scheduled task, firewall rule) on uninstall.

#define MyAppName "Bendo"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "Ben McKenzie"
#define MyAppExeName "Bendo.exe"

[Setup]
; Never change AppId after release - it is how Windows ties upgrades and
; uninstalls to this product.
AppId={{60B587B6-F541-47B2-A2A2-FE974301C31A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Bendo itself requires admin (firewall / shutdown control), so the
; installer elevating once to reach Program Files is no extra burden.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=Bendo-Setup-{#MyAppVersion}
SetupIconFile=Bendo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; If Bendo is running during install/uninstall, ask Windows to close it.
CloseApplications=yes

; --- "Which tools would you like?" page -------------------------------------
; Every tool ships inside the single Bendo.exe (the size is dominated by the
; shared Python runtime, not the tools), so unchecking a component doesn't
; change the download - instead the choices are written to preset.ini and
; Bendo starts with only the chosen tools showing. Tools can be added or
; removed later at any time from Bendo's Settings tab.

[Types]
Name: "full"; Description: "Full - all tools"
Name: "custom"; Description: "Custom - choose your tools"; Flags: iscustom

[Components]
Name: "core"; Description: "Core tools (Internet Blocker, Shutdown Scheduler, Volume Mixer, Notes, Power)"; Types: full custom; Flags: fixed
Name: "clicker"; Description: "Auto Clicker"; Types: full
Name: "timer"; Description: "Timer"; Types: full
Name: "clipboard"; Description: "Clipboard History"; Types: full
Name: "stats"; Description: "System Stats"; Types: full
Name: "bookshelf"; Description: "Bookshelf"; Types: full
Name: "drawpad"; Description: "Drawing Notepad"; Types: full
Name: "photo"; Description: "Photo Tool"; Types: full
Name: "reminders"; Description: "Reminders & Alarms"; Types: full
Name: "media"; Description: "Media Controller"; Types: full
Name: "converter"; Description: "File Converter"; Types: full
Name: "calendar"; Description: "Calendar"; Types: full

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[INI]
; Record the chosen tools for Bendo to read on each user's first run.
; 1 = show the tool's tab, 0 = start without it (Settings can change this).
Filename: "{app}\preset.ini"; Section: "tools"; Key: "clicker"; String: "1"; Components: clicker
Filename: "{app}\preset.ini"; Section: "tools"; Key: "clicker"; String: "0"; Components: not clicker
Filename: "{app}\preset.ini"; Section: "tools"; Key: "timer"; String: "1"; Components: timer
Filename: "{app}\preset.ini"; Section: "tools"; Key: "timer"; String: "0"; Components: not timer
Filename: "{app}\preset.ini"; Section: "tools"; Key: "clipboard"; String: "1"; Components: clipboard
Filename: "{app}\preset.ini"; Section: "tools"; Key: "clipboard"; String: "0"; Components: not clipboard
Filename: "{app}\preset.ini"; Section: "tools"; Key: "stats"; String: "1"; Components: stats
Filename: "{app}\preset.ini"; Section: "tools"; Key: "stats"; String: "0"; Components: not stats
Filename: "{app}\preset.ini"; Section: "tools"; Key: "bookshelf"; String: "1"; Components: bookshelf
Filename: "{app}\preset.ini"; Section: "tools"; Key: "bookshelf"; String: "0"; Components: not bookshelf
Filename: "{app}\preset.ini"; Section: "tools"; Key: "drawpad"; String: "1"; Components: drawpad
Filename: "{app}\preset.ini"; Section: "tools"; Key: "drawpad"; String: "0"; Components: not drawpad
Filename: "{app}\preset.ini"; Section: "tools"; Key: "photo"; String: "1"; Components: photo
Filename: "{app}\preset.ini"; Section: "tools"; Key: "photo"; String: "0"; Components: not photo
Filename: "{app}\preset.ini"; Section: "tools"; Key: "reminders"; String: "1"; Components: reminders
Filename: "{app}\preset.ini"; Section: "tools"; Key: "reminders"; String: "0"; Components: not reminders
Filename: "{app}\preset.ini"; Section: "tools"; Key: "media"; String: "1"; Components: media
Filename: "{app}\preset.ini"; Section: "tools"; Key: "media"; String: "0"; Components: not media
Filename: "{app}\preset.ini"; Section: "tools"; Key: "converter"; String: "1"; Components: converter
Filename: "{app}\preset.ini"; Section: "tools"; Key: "converter"; String: "0"; Components: not converter
Filename: "{app}\preset.ini"; Section: "tools"; Key: "calendar"; String: "1"; Components: calendar
Filename: "{app}\preset.ini"; Section: "tools"; Key: "calendar"; String: "0"; Components: not calendar

[UninstallDelete]
Type: files; Name: "{app}\preset.ini"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallRun]
; Remove the system artifacts Bendo may have created. User data in
; %APPDATA% (settings, notes autosave) is deliberately left in place -
; notes are user content, and settings survive a reinstall.
Filename: "schtasks"; Parameters: "/Delete /F /TN ""Bendo Startup"""; Flags: runhidden; RunOnceId: "RemoveStartupTask"
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=Bendo_InternetBlock"; Flags: runhidden; RunOnceId: "RemoveFirewallRule"
