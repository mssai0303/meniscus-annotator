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
Function .onInit
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
Section "Uninstall"
  !include "${UNINSTALL_FILES}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\Meniscus Annotator 0.1.0\Meniscus Annotator.lnk"
  Delete "$SMPROGRAMS\Meniscus Annotator 0.1.0\User guide.lnk"
  Delete "$SMPROGRAMS\Meniscus Annotator 0.1.0\Uninstall.lnk"
  RMDir "$SMPROGRAMS\Meniscus Annotator 0.1.0"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeniscusAnnotator-0.1.0"
SectionEnd
