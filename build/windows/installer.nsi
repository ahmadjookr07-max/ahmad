Unicode True
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "WinVer.nsh"

!define APP_ID "AhmedAlFaifiMarketImageStudio"
!define APP_GUID "{B7E4A9D2-5C31-4F8E-9A6B-2D7F0C4E8A15}"
!define APP_NAME "Ahmed Al-Faifi Market Image Studio"
!define APP_NAME_AR "استوديو صور المتجر — أحمد الفيفي"
; ── الإصدار مصدره الوحيد ملف VERSION في جذر المشروع ─────────────
; قاعدة «لا تكرار»: لا يُكتب رقم الإصدار في هذا الملف إطلاقًا، فلا
; يتناقض المثبت مع التطبيق كما حدث في 2.9.8 (version_info.txt).
; يفشل البناء صراحةً إن غاب VERSION — أفضل من مثبت بإصدار خاطئ.
; المسار نسبي مجرّد قصدًا: makensis يجعل مجلد عمله مجلد السكربت
; نفسه قبل التحليل، فـ`..\..\VERSION` صحيح من أي مجلد تشغيل
; وعلى ويندوز ولينكس معًا — وهو نفس أسلوب APP_SOURCE وMUI_ICON
; وEULA_ar.txt أدناه وكلها تعمل.
; تحذير: لا تُعد إلى `${__FILEDIR__}` هنا. هو يُبقِي المسار كما ورد
; في سطر الأوامر؛ فإن نودي السكربت بمسار نسبي من جذر المشروع
; (`makensis build/windows/installer.nsi`) صار الناتج مزدوجًا:
; `build/windows/\..\..\VERSION` يُحلّ من داخل `build/windows` فيخفق:
;   !searchparse /file: error opening "build/windows/\..\..\VERSION"
; أي أنه ينجح على ورشة windows-latest ويخفق في أي بناء محلي
; من الجذر — عطب «يعمل عندي». مُثبت بـ`!system 'pwd'`.
; ولا فرع احتياطي: غياب VERSION يُفشل البناء صراحةً بدل إنتاج
; مثبت بإصدار كاذب. مُتحقَق منه بـmakensis ⇒ [2.9.9].
!searchparse /file "..\..\VERSION" "" APP_VERSION "$\n"
!define APP_PUBLISHER "Ahmed Al-Faifi"
!define APP_EXE "AhmedAlFaifiMarketImageStudio.exe"
!define APP_SOURCE "..\..\dist\windows\AhmedAlFaifiMarketImageStudio"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
!define SUPPORT_MAIL "ahmadjookr06@gmail.com"
!define SUPPORT_PHONE "0582381000"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "..\..\dist\installer\AhmedAlFaifiMarketImageStudio-Setup-${APP_VERSION}.exe"
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

VIProductVersion "${APP_VERSION}.0"
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
!define MUI_FINISHPAGE_RUN_TEXT "تشغيل ${APP_NAME_AR}"
!define MUI_FINISHPAGE_TEXT "اكتمل التثبيت.$\r$\n$\r$\nتبدأ فترة تجريبية مجانية 3 أيام تلقائيًا بكامل الميزات.$\r$\nللاشتراك أو التجديد: ${SUPPORT_MAIL} — ${SUPPORT_PHONE}"
; صفحة الاتفاقية إلزامية: لا يمكن المتابعة دون الموافقة
!define MUI_LICENSEPAGE_CHECKBOX
!define MUI_LICENSEPAGE_CHECKBOX_TEXT "أوافق على شروط الاتفاقية (بما فيها عدم استرداد المبالغ بعد الدفع)"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "EULA_ar.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "Arabic"
!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------ فحوص ما قبل التثبيت
Function .onInit
    ; ويندوز 10 أو أحدث 64-بت (PySide6 6.8 لا يعمل على أقدم)
    ${IfNot} ${AtLeastWin10}
        MessageBox MB_ICONSTOP "هذا البرنامج يتطلب Windows 10 أو أحدث (64-بت)."
        Abort
    ${EndIf}
    ; 64-بت فقط — فحص معمارية المعالج دون الحاجة لـ x64.nsh
    ReadEnvStr $0 "PROCESSOR_ARCHITECTURE"
    ReadEnvStr $1 "PROCESSOR_ARCHITEW6432"
    ${If} $0 == "x86"
    ${AndIf} $1 == ""
        MessageBox MB_ICONSTOP "هذا البرنامج يتطلب نظام ويندوز 64-بت."
        Abort
    ${EndIf}
    ; أغلق البرنامج إن كان يعمل قبل التحديث (وإلا يفشل استبدال الملفات)
    ; إغلاق لطيف ثم قسري — taskkill لا يفشل التثبيت إن لم يكن البرنامج عاملاً
    nsExec::ExecToLog 'cmd /c taskkill /IM "${APP_EXE}" /T'
    Pop $0
    Sleep 1200
    nsExec::ExecToLog 'cmd /c taskkill /F /IM "${APP_EXE}" /T'
    Pop $0
    Sleep 400
FunctionEnd

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
    WriteRegStr HKCU "Software\${APP_PUBLISHER}\${APP_ID}" "Version" "${APP_VERSION}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "HelpLink" "mailto:${SUPPORT_MAIL}"
    WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
    SetShellVarContext current
    ; أوقف البرنامج إن كان يعمل
    nsExec::ExecToLog 'cmd /c taskkill /F /IM "${APP_EXE}" /T'
    Pop $0
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    DeleteRegKey HKCU "${UNINSTALL_KEY}"
    DeleteRegKey HKCU "Software\${APP_PUBLISHER}\${APP_ID}"
    RMDir /r "$INSTDIR"
    ; بيانات الترخيص والتجربة تبقى في %LOCALAPPDATA% حتى لا تُستغل
    ; إعادة التثبيت لتجديد الفترة التجريبية. الاشتراك المدفوع يبقى صالحًا
    ; بعد إعادة التثبيت على الجهاز نفسه.
    MessageBox MB_ICONINFORMATION|MB_OK "تمت إزالة البرنامج.$\r$\n$\r$\nملاحظة: يبقى ترخيصك محفوظًا على هذا الجهاز، فإن أعدت التثبيت يعمل اشتراكك تلقائيًا دون مفتاح جديد.$\r$\n$\r$\nللدعم: ${SUPPORT_MAIL} — ${SUPPORT_PHONE}"
SectionEnd
