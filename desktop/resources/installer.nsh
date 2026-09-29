; Complete all app-owned downloads before NSIS offers Finish / Launch.
; Licensed creative applications and GPU drivers remain separately installed.
!macro customInstall
  Push $0
  Push $1
  DetailPrint "Installing and verifying all Photo Studio components..."
  StrCpy $1 ""
  IfSilent 0 +2
    StrCpy $1 "--silent"
  ClearErrors
  ExecWait '"$INSTDIR\resources\backend\python\pythonw.exe" -I "$INSTDIR\resources\backend\scripts\install_desktop.py" $1' $0
  ${If} ${Errors}
    StrCpy $0 1
  ${EndIf}
  ${If} $0 != 0
    SetErrorLevel $0
    IfSilent +2 0
      MessageBox MB_OK|MB_ICONEXCLAMATION "Photo Studio setup is incomplete. Run this installer again to resume. Existing photos and notes are preserved. Details are in your workspace under desktop\install-logs."
    Abort "Component setup did not finish. Run the installer again to resume."
  ${EndIf}
  Pop $1
  Pop $0
!macroend

; electron-builder removes the installed program and the per-user AppData
; workspace via deleteAppDataOnUninstall. Its update uninstaller preserves data.
; The downloaded updater payload lives separately under LocalAppData.
!macro customUnInstall
  ${IfNot} ${isUpdated}
    SetShellVarContext current
    RMDir /r "$LOCALAPPDATA\photo-workflow-updater"
    ${If} $installMode == "all"
      SetShellVarContext all
    ${EndIf}
  ${EndIf}
!macroend
