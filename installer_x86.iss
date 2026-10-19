; Fixbot AI 32-bit Windows Installer Script
; Generated for: dineshkumarAS-creator / fixbot-ai
; Source repo: https://github.com/dineshkumarAS-creator/fixbot-ai.git
; Compile this with Inno Setup: https://jrsoftware.org/isdl.php

[Setup]
AppName=Fixbot
AppVersion=4.0
AppVerName=Fixbot AI v4.0 (x86)
AppPublisher=Fixbot AI
AppPublisherURL=https://github.com/dineshkumarAS-creator/fixbot-ai
AppSupportURL=https://github.com/dineshkumarAS-creator/fixbot-ai/issues
AppUpdatesURL=https://github.com/dineshkumarAS-creator/fixbot-ai/releases
DefaultDirName={autopf}\Fixbot
DefaultGroupName=Fixbot
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=FixbotAI_x86_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist32\Fixbot_x86.exe"; DestDir: "{app}"; DestName: "Fixbot.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\Fixbot"; Filename: "{app}\Fixbot.exe"
Name: "{group}\Uninstall Fixbot"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Fixbot"; Filename: "{app}\Fixbot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Fixbot.exe"; Description: "Launch Fixbot now"; Flags: nowait postinstall skipifsilent
