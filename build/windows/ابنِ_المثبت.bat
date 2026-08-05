@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
REM  ترميز مخرجات بايثون. `chcp 65001` أعلاه يضبط الطرفية وحدها، أمّا
REM  مفسّر بايثون فيبقى على ترميز اللغة (cp1252 على ويندوز الإنجليزي)
REM  لمجرى الإخراج، فتنفجر أول `print` عربية بـUnicodeEncodeError.
REM  حدث فعلًا: ملف الـspec يطبع «[spec] وحدات مكتشفة: 55» فسقط
REM  البناء عند هذا السطر قبل تجميع أي ملف. المتغيّران أدناه
REM  يُلزمان كل خطوة بايثون تالية بـUTF-8، وهما محليّان لأن setlocal يحدّهما.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0..\.."

REM ============================================================
REM  بناء مُثبِّت ويندوز — استوديو صور المتجر (أحمد الفيفي)
REM
REM  انقر عليه مرتين، أو شغّله من أي مجلد:
REM      build\windows\ابنِ_المثبت.bat
REM
REM  لماذا سكربت لا أوامر يدوية؟ لأن ترتيب الخطوات يهم: ملف الـspec
REM  يقرأ المسارات من مجلد العمل الحالي (os.getcwd)، فتشغيله من مجلد
REM  آخر يُنتج حزمة ناقصة بلا رسالة خطأ. لذا يقفز السكربت إلى جذر
REM  المستودع بنفسه في السطر أعلاه — فلا يُشترط عليك مكان التشغيل.
REM
REM  يؤدي كل ما كانت ورشة GitHub تؤديه، محليًا وبلا حساب ولا انتظار:
REM  المتطلبات، النماذج، بيانات الإصدار، محرك OCR المحمول، التطبيق،
REM  المُثبِّتان (المستخدم والمالك)، وبصمة SHA-256.
REM ============================================================

set "EXITCODE=0"

echo.
echo ============================================================
echo   بناء استوديو صور المتجر — محليًا بلا GitHub
echo ============================================================

echo.
echo ==== [1/9] قراءة الإصدار من ملف VERSION ====
if not exist "VERSION" (
    echo   خطأ: ملف VERSION غير موجود. هل هذه شفرة المشروع كاملة؟
    goto :fail
)
set /p APPVER=<VERSION
set "APPVER=%APPVER: =%"
if "%APPVER%"=="" (
    echo   خطأ: ملف VERSION فارغ.
    goto :fail
)
echo   الإصدار: %APPVER%
echo   (هذا هو المصدر الوحيد للرقم: التطبيق والمُثبِّت وخصائص الملف)

echo.
echo ==== [2/9] التحقق من بايثون ====
where python >nul 2>&1
if errorlevel 1 (
    echo   خطأ: python غير موجود في PATH.
    echo   حمّله من https://www.python.org ومعه خيار "Add to PATH".
    goto :fail
)
for /f "delims=" %%v in ('python -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%v"
echo   بايثون %PYVER%

echo.
echo ==== [3/9] تركيب المتطلبات ====
echo   (من requirements.txt — مصدر وحيد، لا قائمة موازية)
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo   فشل تركيب المتطلبات. راجع الرسائل أعلاه.
    goto :fail
)
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo   تركيب PyInstaller...
    python -m pip install --upgrade pyinstaller --quiet
    if errorlevel 1 goto :fail
)
echo   المتطلبات جاهزة.

echo.
echo ==== [4/9] جلب نماذج عزل الخلفية ====
echo   (مستبعدة من git لحجمها؛ تُنزَّل مرة واحدة ثم تُخطّى)
python tools\fetch_models.py
if errorlevel 1 (
    echo.
    echo   فشل جلب النماذج. تحقق من الاتصال بالإنترنت.
    echo   إن كانت لديك نسخة، انسخها إلى src\engine_v2\models\
    goto :fail
)

echo.
echo ==== [5/9] توليد بيانات الإصدار من VERSION ====
echo   (خصائص الملف على ويندوز — لولاها يتخلّف الرقم عن التطبيق)
python "build\windows\توليد_بيانات_الإصدار.py"
if errorlevel 1 goto :fail

echo.
echo ==== [6/9] فحص مسبق لاكتشاف الوحدات والبيانات ====
echo   (يوقف البناء الآن بدل الفشل بعد ثلاثين دقيقة)
python tools\verify_spec_discovery.py
if errorlevel 1 (
    echo.
    echo   فشل الفحص المسبق. أُوقف البناء قبل إهدار الوقت.
    goto :fail
)

echo.
echo ==== [7/9] بناء التطبيق (PyInstaller) ====
echo   يستغرق عادة 5-15 دقيقة. لا تُغلق النافذة.
if exist "build_tmp" rmdir /s /q "build_tmp"
python -m PyInstaller --noconfirm --clean ^
    --distpath "dist\windows" ^
    --workpath "build_tmp" ^
    "build\windows\AhmedAlFaifiMarketImageStudioV2.spec"
if errorlevel 1 (
    echo   فشل بناء التطبيق. راجع الرسائل أعلاه.
    goto :fail
)
set "APPDIR=dist\windows\AhmedAlFaifiMarketImageStudio"
if not exist "%APPDIR%\AhmedAlFaifiMarketImageStudio.exe" (
    echo   خطأ: البناء انتهى لكن التنفيذي غير موجود.
    goto :fail
)
echo   التطبيق جُمِّع بنجاح.

echo.
echo ==== [8/9] إضافة محرك OCR المحمول (عربي + إنجليزي) ====
rem لماذا إلزامي لا «اختياري»؟ لأن الشافي الذاتي داخل التطبيق يقول
rem للمستخدم حرفيًا إن «سيتب التثبيت المرفق يثبّته تلقائيًا»، و`installer.nsi`
rem يرفض البناء بدونه. والاعتماد على وجود tesseract في PATH يعني أن
rem حزمة العميل تعتمد على ما صادف تركيبه على آلة الباني — فننزّله
rem بأنفسنا ليكون المخرج واحدًا على أي آلة بناء.
set "TESSDIR=%APPDIR%\tesseract"
if exist "%TESSDIR%\tesseract.exe" (
    echo   موجود مسبقًا — تُخطّى.
    goto :after_tess
)
where tesseract >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%t in ('where tesseract') do set "SYSTESS=%%t"
    for %%d in ("!SYSTESS!") do set "SYSTESSDIR=%%~dpd"
    echo   نسخ المحرك المُركَّب من: !SYSTESSDIR!
    if not exist "%TESSDIR%" mkdir "%TESSDIR%"
    xcopy /E /I /Y /Q "!SYSTESSDIR!*" "%TESSDIR%\" >nul 2>&1
    if exist "%TESSDIR%\tesseract.exe" (
        echo   تم شحن المحرك مع الحزمة.
        goto :check_tessdata
    )
)

echo   غير موجود على الجهاز — يُنزّل تلقائيًا (~50 م.ب)...
set "TESSSETUP=%TEMP%\tesseract-w64-setup.exe"
set "TESSURL=https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
if not exist "%TESSSETUP%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "try { [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '%TESSURL%' -OutFile '%TESSSETUP%' -UseBasicParsing; exit 0 } catch { exit 1 }"
)
if exist "%TESSSETUP%" (
    if not exist "%TESSDIR%" mkdir "%TESSDIR%"
    rem تثبيت صامت إلى مجلد معزول داخل الحزمة (مثبِّت Inno)
    "%TESSSETUP%" /S /D=%CD%\%TESSDIR% >nul 2>&1
    if exist "%TESSDIR%\tesseract.exe" (
        echo   تم تنزيل المحرك وشحنه مع الحزمة.
        goto :check_tessdata
    )
)

echo   خطأ: تعذر شحن محرك OCR — والمُثبِّت يرفض البناء بدونه
echo   لأن التطبيق يوعد المستخدم بأن السيتب يحمله.
echo   الحل: ركّب Tesseract من الرابط أدناه ثم أعد تشغيل هذا الملف:
echo   https://github.com/UB-Mannheim/tesseract/wiki
goto :fail

:check_tessdata
rem المحرك بلا بيانات عربية يقرأ الجداول خطأ بلا سبب مفهوم، وهو
rem أسوأ من غيابه: فالغائب يُعلن والناقص يُفسد بصمت. فننزّل ara.
if not exist "%TESSDIR%\tessdata\ara.traineddata" (
    echo   تنزيل بيانات اللغة العربية...
    if not exist "%TESSDIR%\tessdata" mkdir "%TESSDIR%\tessdata"
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "try { [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata/raw/main/ara.traineddata' -OutFile '%TESSDIR%\tessdata\ara.traineddata' -UseBasicParsing; exit 0 } catch { exit 1 }"
)
if not exist "%TESSDIR%\tessdata\ara.traineddata" (
    echo   تنبيه: بيانات العربية غير متوفرة — قراءة الجداول العربية ستضعف.
) else (
    echo   اللغة العربية جاهزة.
)
rem حذف أدوات التدريب — لا يستخدمها التطبيق وتزيد الحجم بلا فائدة.
del /Q "%TESSDIR%\*train*.exe" >nul 2>&1
del /Q "%TESSDIR%\unicharset_extractor.exe" >nul 2>&1
:after_tess

echo.
echo ==== [9/9] بناء المُثبِّتين (NSIS) ====
set "MAKENSIS="
where makensis >nul 2>&1 && set "MAKENSIS=makensis"
if not defined MAKENSIS if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles(x86)%\NSIS\makensis.exe"
if not defined MAKENSIS if exist "%ProgramFiles%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles%\NSIS\makensis.exe"
if not defined MAKENSIS (
    echo   تنبيه: NSIS غير موجود، فلن يُنتج ملف مُثبِّت.
    echo   حمّله من https://nsis.sourceforge.io ثم أعد التشغيل.
    echo.
    echo   لكن الحزمة المحمولة جاهزة وتعمل بالنقر على:
    echo   %APPDIR%\AhmedAlFaifiMarketImageStudio.exe
    goto :done_portable
)
if not exist "dist\installer" mkdir "dist\installer"
"%MAKENSIS%" "build\windows\installer.nsi"
if errorlevel 1 (
    echo   فشل بناء مُثبِّت المستخدم. راجع الرسائل أعلاه.
    goto :fail
)
set "SETUPUSER=dist\installer\AhmedAlFaifiMarketImageStudio-Setup-%APPVER%.exe"
if not exist "%SETUPUSER%" (
    echo   خطأ: makensis نجح لكن الملف المتوقع غير موجود:
    echo   %SETUPUSER%
    echo   الموجود فعلًا في dist\installer:
    dir /b "dist\installer\*.exe"
    goto :fail
)

REM  مُثبِّت المالك: برنامج آخر (صلاحيات مدير وأسرار إصدار المفاتيح).
REM  يُبنى إن وُجد سبيكه، ويُخطّى بلا إفشال البناء إن لم يوجد.
set "OWNERBUILT="
if exist "build\windows\AhmedAlFaifiOwnerStudio.spec" (
    echo.
    echo   بناء استوديو المالك...
    python -m PyInstaller --noconfirm --clean ^
        --distpath "dist\windows" ^
        --workpath "build_tmp_owner" ^
        "build\windows\AhmedAlFaifiOwnerStudio.spec"
    if not errorlevel 1 (
        "%MAKENSIS%" "build\windows\installer_owner.nsi"
        if not errorlevel 1 set "OWNERBUILT=1"
    )
    if not defined OWNERBUILT echo   تنبيه: تعذّر بناء مُثبِّت المالك — مُثبِّت المستخدم سليم.
)

echo.
echo ==== بصمة SHA-256 للتحقق من سلامة الملف ====
certutil -hashfile "%SETUPUSER%" SHA256 | findstr /v ":" > "%SETUPUSER%.sha256"
type "%SETUPUSER%.sha256"

echo.
echo ============================================================
echo   تم بنجاح — الإصدار %APPVER%
echo ============================================================
echo   مُثبِّت المستخدم:
echo     %SETUPUSER%
if defined OWNERBUILT (
    echo   مُثبِّت المالك (سرّي — لا يُوزَّع):
    echo     dist\installer\AhmedAlFaifiOwnerStudio-Setup-%APPVER%.exe
)
echo   النسخة المحمولة (تعمل بلا تثبيت):
echo     %APPDIR%\AhmedAlFaifiMarketImageStudio.exe
echo ============================================================
goto :end

:done_portable
echo.
echo ============================================================
echo   اكتمل بناء التطبيق — الإصدار %APPVER%
echo   (بلا مُثبِّت: NSIS غير مُركَّب)
echo ============================================================
goto :end

:fail
set "EXITCODE=1"
echo.
echo ============================================================
echo   توقف البناء. السبب في الرسائل أعلاه.
echo ============================================================

:end
echo.
echo اضغط أي مفتاح للإغلاق...
pause >nul
endlocal & exit /b %EXITCODE%
