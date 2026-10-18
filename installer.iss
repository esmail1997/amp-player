; ==========================================================
; Amp Player - مثبّت ويندوز (Inno Setup 6)
;
; البناء:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
;   (أو شغّل build_installer.bat)
;
; الناتج:
;   dist\AmpPlayer-1.1.0.exe          ملف تثبيت واحد جاهز للتوزيع
;
; ملاحظات:
; - التثبيت للمستخدم الحالي فقط (بدون طلب صلاحيات مسؤول/UAC):
;   يُثبَّت في AppData\Local\Programs\Amp Player ويظهر في Control Panel.
; - المصدر هو مجلد الناتج من PyInstaller: dist\Amp Player\*
; ==========================================================

#define MyAppName "Amp Player"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "Amp Player Project"
#define MyAppExeName "Amp Player.exe"
#define BuildDir "dist\Amp Player"

[Setup]
AppId={{8F1C4B2A-6D5E-4A7B-9C3F-2E8D0A5B7C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=dist
OutputBaseFilename=AmpPlayer-{#MyAppVersion}
SetupIconFile=tools\amp_player.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; بدون UAC: تثبيت لكل مستخدم لا يحتاج تشغيلاً كمسؤول
PrivilegesRequired=lowest
; البرنامج مبني لمعمارية x64 (ويعمل على ARM64 عبر التوافق)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب"; GroupDescription: "اختصارات إضافية:"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: "selftest.txt"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "تشغيل {#MyAppName} الآن"; \
    Flags: nowait postinstall skipifsilent
