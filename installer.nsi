; Build with: makensis /DAPP_VERSION=<app_info.APP_VERSION> installer.nsi
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef APP_VERSION
  !error "APP_VERSION is required. Use build_windows.bat or the GitHub Actions workflow."
!endif
!ifndef APP_NAME
  !define APP_NAME "VibeDownloader"
!endif
!ifndef APP_EXE
  !define APP_EXE "VibeDownloader.exe"
!endif
!ifndef APP_BINARY
  !define APP_BINARY "dist\release\${APP_EXE}"
!endif
!ifndef INSTALLER_OUTPUT
  !define INSTALLER_OUTPUT "VibeDownloader_Installer.exe"
!endif
!define APP_KEY "Software\${APP_NAME}"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${INSTALLER_OUTPUT}"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${APP_KEY}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
ShowInstDetails show
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "${APP_NAME} Windows installer"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "${APP_NAME} contributors"

!define MUI_ICON "VibeDownloader.ico"
!define MUI_UNICON "VibeDownloader.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APP_NAME}"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var Parameters
Var IsUpdate
Var RestartAfterUpdate
Var WaitPid
Var ExplicitDirectory

; Do not kill a user's active downloads or unrelated yt-dlp processes.
!macro REQUIRE_APP_CLOSED PREFIX
Function ${PREFIX}RequireAppClosed
  retry:
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "Local\${APP_NAME}.SingleInstance") p.r1'
  ${If} $1 != 0
    System::Call 'kernel32::CloseHandle(p r1)'
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION \
      "Please exit ${APP_NAME} from its tray menu before continuing. Your downloads and history will be kept." \
      /SD IDCANCEL IDRETRY retry
    SetErrorLevel 2
    Abort
  ${EndIf}
FunctionEnd
!macroend
!insertmacro REQUIRE_APP_CLOSED ""
!insertmacro REQUIRE_APP_CLOSED "un."

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "${APP_NAME} requires 64-bit Windows." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "${APP_NAME} requires Windows 10 or newer." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  SetShellVarContext all
  StrCpy $IsUpdate 0
  StrCpy $RestartAfterUpdate 1
  StrCpy $WaitPid ""
  ${GetParameters} $Parameters
  ${GetOptions} $Parameters "/UPDATE" $0
  ${IfNot} ${Errors}
    StrCpy $IsUpdate 1
    SetSilent silent
  ${EndIf}
  ; Compatibility with the 2.4 updater, which passed Inno-style arguments.
  ClearErrors
  ${GetOptions} $Parameters "/SILENT" $0
  ${IfNot} ${Errors}
    StrCpy $IsUpdate 1
    SetSilent silent
  ${EndIf}
  ClearErrors
  ${GetOptions} $Parameters "/NORESTART" $0
  ${IfNot} ${Errors}
    StrCpy $RestartAfterUpdate 0
  ${EndIf}
  ClearErrors
  ${GetOptions} $Parameters "/WAITPID=" $WaitPid

  ; Native NSIS /D= is parsed by the loader and already has precedence over
  ; InstallDirRegKey. Parsing it again would truncate an unquoted path at its
  ; first space. /DIR= exists only for compatibility with the 2.4 updater.
  SetRegView 64
  ClearErrors
  ${GetOptions} $Parameters "/DIR=" $ExplicitDirectory
  ${IfNot} ${Errors}
    StrCpy $INSTDIR $ExplicitDirectory
  ${EndIf}

  ${If} $WaitPid != ""
    System::Call 'kernel32::OpenProcess(i 0x00100000, i 0, i $WaitPid) p.r2'
    ${If} $2 != 0
      System::Call 'kernel32::WaitForSingleObject(p r2, i 120000) i.r3'
      System::Call 'kernel32::CloseHandle(p r2)'
      ${If} $3 != 0
        MessageBox MB_OK|MB_ICONSTOP "The app could not finish closing. Exit it from the tray and run the update again." /SD IDOK
        SetErrorLevel 2
        Abort
      ${EndIf}
      Sleep 1000
    ${EndIf}
  ${ElseIf} $IsUpdate == 1
    ; Give a legacy updater time to save its history and exit.
    Sleep 5000
  ${EndIf}
  Call RequireAppClosed
FunctionEnd

Function LaunchApp
  ; Do not let a previous one-file process's extraction state affect restart.
  System::Call 'kernel32::SetEnvironmentVariableW(w "PYINSTALLER_RESET_ENVIRONMENT", w "1")'
  ExecShell "open" "$INSTDIR\${APP_EXE}" "--updated"
FunctionEnd

Function .onInstSuccess
  ${If} $IsUpdate == 1
  ${AndIf} $RestartAfterUpdate == 1
    Call LaunchApp
  ${EndIf}
FunctionEnd

Section "Install ${APP_NAME}"
  SetShellVarContext all
  SetRegView 64
  SetOutPath "$INSTDIR"
  File "${APP_BINARY}"
  File "yt-dlp.exe"
  File "VibeDownloader.ico"
  File "classic_icons.py"
  File "windows_startup.py"
  File "THIRD_PARTY_NOTICES.md"
  SetOutPath "$INSTDIR\licenses"
  File /r "tools\licenses\*"
  SetOutPath "$INSTDIR\extension"
  File /r "extension\*"
  SetOutPath "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\uninst.exe"
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  WriteUninstaller "$INSTDIR\uninst.exe"

  ; Remove the old 32-bit registration only when it describes this install.
  SetRegView 32
  ReadRegStr $0 HKLM "${APP_KEY}" "InstallDir"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKLM "${UNINST_KEY}"
    DeleteRegKey HKLM "${APP_KEY}"
  ${EndIf}
  SetRegView 64
  WriteRegStr HKLM "${APP_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninst.exe"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninst.exe" /S'
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "${APP_NAME}"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" $0
SectionEnd

Function un.onInit
  SetShellVarContext all
  SetRegView 64
  Call un.RequireAppClosed
FunctionEnd

Section "Uninstall"
  SetShellVarContext all
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  SetShellVarContext current
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${APP_NAME}"

  ; Only installed app resources are removed. User data/downloads are retained.
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\yt-dlp.exe"
  Delete "$INSTDIR\yt-dlp.exe.bak"
  Delete "$INSTDIR\VibeDownloader.ico"
  Delete "$INSTDIR\classic_icons.py"
  Delete "$INSTDIR\windows_startup.py"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  RMDir /r "$INSTDIR\extension"
  RMDir /r "$INSTDIR\licenses"
  Delete "$INSTDIR\uninst.exe"
  RMDir "$INSTDIR"

  SetRegView 32
  ReadRegStr $0 HKLM "${APP_KEY}" "InstallDir"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKLM "${UNINST_KEY}"
    DeleteRegKey HKLM "${APP_KEY}"
  ${EndIf}
  SetRegView 64
  ReadRegStr $0 HKLM "${APP_KEY}" "InstallDir"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKLM "${UNINST_KEY}"
    DeleteRegKey HKLM "${APP_KEY}"
  ${EndIf}
SectionEnd
