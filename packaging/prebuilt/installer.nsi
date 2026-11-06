Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!ifndef PAYLOAD
!error "PAYLOAD must be supplied"
!endif
!ifndef OUTPUT
!error "OUTPUT must be supplied"
!endif
!ifndef UNINSTALL_FILES
!error "UNINSTALL_FILES must be supplied"
!endif
!ifndef LICENSE_FILE
!error "LICENSE_FILE must be supplied"
!endif
Name "Meniscus Annotator 0.1.0"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\Meniscus Annotator\0.1.0"
RequestExecutionLevel user
ManifestDPIAware true
ManifestLongPathAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 32
Icon "${PAYLOAD}\MeniscusAnnotator.ico"
UninstallIcon "${PAYLOAD}\MeniscusAnnotator.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\MeniscusAnnotator.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open Meniscus Annotator"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Var RuntimeGuard1
Var RuntimeGuard2
Var RuntimeGuard3
Var RuntimeGuard4
Var RuntimeGuard5
Function .onInit
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "InstallLocation"
  StrCmp $0 "" no_registered_install
    MessageBox MB_ICONSTOP "Meniscus Annotator 0.1.0 is already registered at $0. Close it and use its uninstaller before installing another copy of this fixed version. Saved work is outside the installation folder." /SD IDOK
    Abort
  no_registered_install:
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "This application requires Windows x64."
    Abort
  ${EndIf}
FunctionEnd
Section "Application" SEC_APP
  SectionIn RO
  ; Upstream Slicer documents ASCII-only installation paths. UTF-8 byte length
  ; equals UTF-16 character count only for an ASCII path (including terminator).
  StrLen $0 "$INSTDIR"
  IntOp $0 $0 + 1
  System::Call 'kernel32::WideCharToMultiByte(i 65001, i 0, w "$INSTDIR", i -1, p 0, i 0, p 0, p 0) i.r1'
  IntCmp $0 $1 ascii_install_path ascii_install_error ascii_install_error
  ascii_install_error:
    MessageBox MB_ICONSTOP "Slicer requires an installation path containing only ASCII characters. Choose a writable folder with English letters, numbers and spaces. Dataset and work locations are separate." /SD IDOK
    Abort
  ascii_install_path:
  FindFirst $0 $1 "$INSTDIR\*"
  empty_check_loop:
    StrCmp $1 "" empty_check_done
    StrCmp $1 "." empty_check_next
    StrCmp $1 ".." empty_check_next
    FindClose $0
    MessageBox MB_ICONSTOP "Choose an empty installation folder. Existing files will not be overwritten. Saved annotation work belongs in a separate local work folder."
    Abort
  empty_check_next:
    FindNext $0 $1
    Goto empty_check_loop
  empty_check_done:
    FindClose $0
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Meniscus Annotator 0.1.0"
  CreateShortCut "$SMPROGRAMS\Meniscus Annotator 0.1.0\Meniscus Annotator.lnk" "$INSTDIR\MeniscusAnnotator.exe" "" "$INSTDIR\MeniscusAnnotator.ico"
  CreateShortCut "$SMPROGRAMS\Meniscus Annotator 0.1.0\User guide.lnk" "$INSTDIR\UserGuide.txt"
  CreateShortCut "$SMPROGRAMS\Meniscus Annotator 0.1.0\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "DisplayName" "Meniscus Annotator 0.1.0 (3D Slicer 5.12.4 runtime)"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "DisplayVersion" "0.1.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "DisplayIcon" "$INSTDIR\MeniscusAnnotator.exe"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "NoRepair" 1
SectionEnd
# Obtain exclusive write guards before deleting anything. Existing executable/DLL
# mappings reject these opens; new application launches are blocked until removal.
Function un.LockRuntimeFile
  Pop $0
  IfFileExists "$0" 0 missing_runtime_file
  System::Call 'kernel32::CreateFileW(w r0, i 0x40000000, i 4, p 0, i 3, i 0, p 0) p.r1'
  IntCmp $1 -1 runtime_file_busy
  Push $1
  Return
  runtime_file_busy:
    MessageBox MB_ICONSTOP "Close Meniscus Annotator, Slicer and any Python process using this installation, then retry uninstalling. No application files have been removed. If it is already closed, check file permissions." /SD IDOK
    Abort
  missing_runtime_file:
    Push 0
FunctionEnd
Function un.ReleaseRuntimeGuards
  StrCmp $RuntimeGuard1 0 +2
    System::Call 'kernel32::CloseHandle(p $RuntimeGuard1)'
  StrCmp $RuntimeGuard2 0 +2
    System::Call 'kernel32::CloseHandle(p $RuntimeGuard2)'
  StrCmp $RuntimeGuard3 0 +2
    System::Call 'kernel32::CloseHandle(p $RuntimeGuard3)'
  StrCmp $RuntimeGuard4 0 +2
    System::Call 'kernel32::CloseHandle(p $RuntimeGuard4)'
  StrCmp $RuntimeGuard5 0 +2
    System::Call 'kernel32::CloseHandle(p $RuntimeGuard5)'
FunctionEnd
Function un.onInit
  Push "$INSTDIR\MeniscusAnnotator.exe"
  Call un.LockRuntimeFile
  Pop $RuntimeGuard1
  Push "$INSTDIR\bin\MeniscusAnnotatorApp-real.exe"
  Call un.LockRuntimeFile
  Pop $RuntimeGuard2
  Push "$INSTDIR\Slicer.exe"
  Call un.LockRuntimeFile
  Pop $RuntimeGuard3
  Push "$INSTDIR\bin\SlicerApp-real.exe"
  Call un.LockRuntimeFile
  Pop $RuntimeGuard4
  Push "$INSTDIR\bin\python312.dll"
  Call un.LockRuntimeFile
  Pop $RuntimeGuard5
FunctionEnd
Section "Uninstall"
  !include "${UNINSTALL_FILES}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0" "InstallLocation"
  StrCmp $0 "$INSTDIR" 0 uninstall_registration_done
  Delete "$SMPROGRAMS\Meniscus Annotator 0.1.0\Meniscus Annotator.lnk"
  Delete "$SMPROGRAMS\Meniscus Annotator 0.1.0\User guide.lnk"
  Delete "$SMPROGRAMS\Meniscus Annotator 0.1.0\Uninstall.lnk"
  RMDir "$SMPROGRAMS\Meniscus Annotator 0.1.0"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0"
  uninstall_registration_done:
SectionEnd
