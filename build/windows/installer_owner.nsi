; ============================================================
;  مثبّت استوديو المالك — Ahmed Al-Faifi Owner Studio
;  سري: للمالك وحده. لا يوزع على العملاء إطلاقًا.
;  الترجمة:  makensis build/windows/installer_owner.nsi
; ============================================================

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!define APP_NAME      "Ahmed Al-Faifi Owner Studio"
!define APP_NAME_AR   "استوديو المالك"
!define APP_ID        "AhmedAlFaifiOwnerStudio"
; الإصدار مصدره الوحيد ملف VERSION. __FILEDIR__ يضمن الحل من موضع
; هذا الملف لا من مجلد تشغيل البناء، ولا فرع احتياطي: غياب VERSION
; يُفشل البناء صراحةً بدل إنتاج مُثبِّت بإصدار كاذب.
!searchparse /file "${__FILEDIR__}\..\..\VERSION" "" APP_VERSION "$\n"
!define APP_PUBLISHER "Ahmed Al-Faifi"
!define APP_EXE       "AhmedAlFaifiOwnerStudio.exe"
!define SECRETS_DIR   "بيانات_المالك"

Name "${APP_NAME_AR} ${APP_VERSION}"
OutFile "..\..\dist\installer\AhmedAlFaifiOwnerStudio-Setup-${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APP_ID}"
InstallDirRegKey HKLM "Software\${APP_ID}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
BrandingText "${APP_PUBLISHER} — ${APP_NAME} ${APP_VERSION}"

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=1033 "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "Owner Studio Installer"
VIAddVersionKey /LANG=1033 "FileVersion"     "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductVersion"  "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "LegalCopyright"  "Copyright (c) 2026 ${APP_PUBLISHER}"

!define MUI_ICON   "..\..\windows_app\assets\app_icon.ico"
!define MUI_UNICON "..\..\windows_app\assets\app_icon.ico"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "تثبيت ${APP_NAME_AR} ${APP_VERSION}"
!define MUI_WELCOMEPAGE_TEXT  "هذا برنامج المالك السري لإدارة التراخيص والاشتراكات.$\r$\n$\r$\nيصدر مفاتيح التفعيل المرتبطة ببصمة جهاز كل عميل، ويدير سجل العملاء ومدد الاشتراك (أسبوعي / شهري / سنوي / دائم)، ويصدر ملفات الإلغاء الموقّعة.$\r$\n$\r$\nتحذير: لا توزع هذا البرنامج ولا مجلد (${SECRETS_DIR}) على أي شخص. من يملكهما يستطيع إصدار تراخيص مجانية بلا حد."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "تم التثبيت بنجاح"
!define MUI_FINISHPAGE_TEXT  "ثُبّت ${APP_NAME_AR} ${APP_VERSION}.$\r$\n$\r$\nمهم جدًا: عند أول تشغيل تُولَّد شفرة المالك في مجلد (${SECRETS_DIR}). افتح تبويب (الإعدادات) داخل البرنامج واضغط (فتح مجلد البيانات) لترى موقعها الدقيق، وخذ نسخة احتياطية فورًا في مكان آمن — فقدانها يعني عدم قدرتك على إصدار مفاتيح جديدة لنسختك الموزعة على العملاء."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "تشغيل ${APP_NAME_AR} الآن"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Arabic"
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ; 64-بت فقط — فحص معمارية المعالج دون الحاجة لـ x64.nsh
  ReadEnvStr $0 "PROCESSOR_ARCHITECTURE"
  ReadEnvStr $1 "PROCESSOR_ARCHITEW6432"
  ${If} $0 == "x86"
  ${AndIf} $1 == ""
    MessageBox MB_ICONSTOP "يتطلب برنامج المالك ويندوز 64-بت."
    Abort
  ${EndIf}

  ; أغلق نسخة قيد التشغيل قبل التحديث
  nsExec::ExecToStack 'taskkill /F /IM "${APP_EXE}"'
  Pop $0
  Pop $1
FunctionEnd

Section "البرنامج الرئيسي" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  SetOverwrite ifnewer
  File /r "..\..\dist\windows\${APP_ID}\*.*"

  ; مجلد شفرة المالك. يُنشأ هنا وتُمنح مجموعة (Users) صلاحية الكتابة عليه
  ; حتى تبقى البيانات بجانب البرنامج (أسهل للنسخ الاحتياطي).
  ; إن تعذّر منح الصلاحية فالبرنامج ينتقل تلقائيًا إلى %LOCALAPPDATA%
  ; وينقل أي بيانات قديمة معه — لا فقدان للشفرة ولا لسجل العملاء.
  CreateDirectory "$INSTDIR\${SECRETS_DIR}"
  ; icacls مدمج في ويندوز — لا يحتاج إضافة NSIS خارجية.
  ; *S-1-5-32-545 هو SID مجموعة Users، مستقل عن لغة النظام.
  nsExec::ExecToLog 'cmd /c icacls "$INSTDIR\${SECRETS_DIR}" /grant *S-1-5-32-545:(OI)(CI)M /T /C'
  Pop $0
  ${If} $0 != 0
    DetailPrint "تنبيه: لم تُمنح صلاحية الكتابة على مجلد البيانات — سيستخدم البرنامج %LOCALAPPDATA% تلقائيًا"
  ${EndIf}

  WriteRegStr HKLM "Software\${APP_ID}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\${APP_ID}" "Version"    "${APP_VERSION}"

  CreateDirectory "$SMPROGRAMS\${APP_NAME_AR}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME_AR}\${APP_NAME_AR}.lnk" \
                 "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortCut "$SMPROGRAMS\${APP_NAME_AR}\إزالة ${APP_NAME_AR}.lnk" \
                 "$INSTDIR\uninstall.exe"
  CreateShortCut "$DESKTOP\${APP_NAME_AR}.lnk" \
                 "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0

  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "DisplayName"     "${APP_NAME_AR} ${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "EstimatedSize"   $0
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
              "NoRepair" 1
SectionEnd

Section "Uninstall"
  nsExec::ExecToStack 'taskkill /F /IM "${APP_EXE}"'
  Pop $0
  Pop $1

  ; لا تُحذف شفرة المالك وسجل العملاء تلقائيًا — قيمتها لا تُعوَّض
  IfFileExists "$INSTDIR\${SECRETS_DIR}\*.*" 0 skip_secrets
    MessageBox MB_YESNO|MB_ICONEXCLAMATION \
      "هل تريد حذف شفرة المالك وسجل العملاء أيضًا؟$\r$\n$\r$\nتحذير: حذفها نهائي. لن تستطيع بعدها إصدار أي مفتاح تفعيل جديد للنسخ الموزعة على عملائك، وستفقد سجل اشتراكاتهم.$\r$\n$\r$\nاختر (لا) للاحتفاظ بها — وهو المستحسن." \
      IDYES del_secrets IDNO skip_secrets
    del_secrets:
      RMDir /r "$INSTDIR\${SECRETS_DIR}"
  skip_secrets:

  Delete "$INSTDIR\uninstall.exe"
  Delete "$INSTDIR\${APP_EXE}"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\*.dll"
  Delete "$INSTDIR\*.pyd"
  Delete "$INSTDIR\*.txt"
  Delete "$INSTDIR\*.md"
  RMDir "$INSTDIR"

  Delete "$DESKTOP\${APP_NAME_AR}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME_AR}"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
  DeleteRegKey HKLM "Software\${APP_ID}"
SectionEnd
