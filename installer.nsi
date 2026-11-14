; VibeDownloader Installer (NSIS)

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APP_NAME "VibeDownloader"
!define APP_EXE "VibeDownloader.exe"
!define APP_VERSION "2.4.0"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME}"
OutFile "VibeDownloader_Installer.exe"
InstallDir "$PROGRAMFILES\${APP_NAME}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel admin

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install VibeDownloader"
  ; app may be hidden in the tray -> close it so files can be replaced
  nsExec::Exec 'taskkill /F /IM ${APP_EXE}'

  ; shortcuts for all users (same place the uninstaller cleans)
  SetShellVarContext all

  SetOutPath "$INSTDIR"
  File "dist\${APP_EXE}"
  File "yt-dlp.exe"
  File "VibeDownloader.ico"        ; used by the tray icon
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

  WriteRegStr HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"

  ; Settings > Apps > Installed apps entry (so Windows can uninstall it)
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr   HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninst.exe"'
  WriteRegStr   HKLM "${UNINST_KEY}" "Publisher" "${APP_NAME}"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1

  MessageBox MB_OK|MB_ICONINFORMATION "VibeDownloader installed successfully!$\n$\nYou can now run VibeDownloader and install the browser extension."
SectionEnd

Section "Uninstall"
  ; stop the app even if it is hidden in the tray
  nsExec::Exec 'taskkill /F /IM ${APP_EXE}'
  nsExec::Exec 'taskkill /F /IM yt-dlp.exe'
  Sleep 800

  ; remove shortcuts (all-users AND current-user, in case of old installs)
  SetShellVarContext all
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"

  SetShellVarContext current
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"

  ; app data (history, settings, ffmpeg...) - check yt_helper.app_data_dir()
  RMDir /r "$APPDATA\${APP_NAME}"
  RMDir /r "$LOCALAPPDATA\${APP_NAME}"

  ; program files (also catches files the app created, e.g. updated yt-dlp/ffmpeg)
  RMDir /r "$INSTDIR"

  DeleteRegKey HKLM "${UNINST_KEY}"
  DeleteRegKey HKLM "Software\${APP_NAME}"
SectionEnd
