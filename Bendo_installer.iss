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
#define MyAppVersion "1.0.0"
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

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

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
