Unicode True
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!define APP_ID "AhmedAlFaifiMarketImageStudio"
!define APP_GUID "{B7E4A9D2-5C31-4F8E-9A6B-2D7F0C4E8A15}"
!define APP_NAME "Ahmed Al-Faifi Market Image Studio"
!define APP_VERSION "2.1.0"
!define APP_PUBLISHER "Ahmed Al-Faifi"
!define APP_EXE "AhmedAlFaifiMarketImageStudio.exe"
!define APP_SOURCE "..\..\dist\windows\AhmedAlFaifiMarketImageStudio"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
Name "${APP_NAME} ${APP_VERSION}"
; ملاحظة: اسم الملف يطابق مسار سير عمل GitHub Actions (Setup-2.0.0) — نسخة التطبيق الفعلية 2.1.0
OutFile "..\..\dist\installer\AhmedAlFaifiMarketImageStudio-Setup-2.0.0.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_PUBLISHER}\${APP_ID}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
SetDatablockOptimize on
CRCCheck on
XPStyle on
BrandingText "${APP_NAME} ${APP_VERSION}"
Icon "..\..\windows_app\assets\app_icon.ico"
UninstallIcon "..\..\windows_app\assets\app_icon.ico"
VIProductVersion "2.1.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "${APP_NAME} Setup (Professional Market Product Image Studio)"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright 2026 Ahmed Al-Faifi. All rights reserved."
!define MUI_ABORTWARNING
!define MUI_ICON "..\..\windows_app\assets\app_icon.ico"
!define MUI_UNICON "..\..\windows_app\assets\app_icon.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Run ${APP_NAME}"
!insertmacro MUI_PAGE_WELCOME
; EULA page — installation cannot proceed without acceptance
!insertmacro MUI_PAGE_LICENSE "EULA_ar.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "English"
Section "Application" SEC_APP
    SetShellVarContext current
    SetOutPath "$INSTDIR"
    SetOverwrite on
    File /r "${APP_SOURCE}\*.*"
    File "/oname=EULA_ar.txt" "EULA_ar.txt"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
    WriteRegStr HKCU "Software\${APP_PUBLISHER}\${APP_ID}" "InstallDir" "$INSTDIR"
    WriteRegStr HKCU "Software\${APP_PUBLISHER}\${APP_ID}" "ProductGUID" "${APP_GUID}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" $0
SectionEnd
Section "Uninstall"
    SetShellVarContext current
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    DeleteRegKey HKCU "${UNINSTALL_KEY}"
    DeleteRegKey HKCU "Software\${APP_PUBLISHER}\${APP_ID}"
    RMDir /r "$INSTDIR"
SectionEnd
