@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ============================================================
REM  بناء مُثبِّت ويندوز — استوديو صور المتجر (أحمد الفيفي)
REM
REM  يُشغَّل من جذر المستودع:  build\windows\ابنِ_المثبت.bat
REM
REM  لماذا سكربت لا أوامر يدوية؟ لأن ترتيب الخطوات يهم: الـspec
REM  يقرأ المسارات من مجلد العمل الحالي (os.getcwd)، فتشغيله من
REM  مجلد آخر يُنتج حزمة ناقصة بلا رسالة خطأ.
REM ============================================================

echo.
echo ==== [1/5] التحقق من مجلد العمل ====
if not exist "build\windows\AhmedAlFaifiMarketImageStudioV2.spec" (
    echo.
    echo   خطأ: شغّل هذا الملف من جذر المستودع، لا من مجلد build\windows.
    echo   مثال:  cd C:\market-image-studio-v2
    echo          build\windows\ابنِ_المثبت.bat
    echo.
    exit /b 1
)
echo   المجلد صحيح.

echo.
echo ==== [2/5] التحقق من الأدوات ====
where python >nul 2>&1 || (echo   خطأ: python غير موجود في PATH. & exit /b 1)
python -c "import PyInstaller" 2>nul || (
    echo   PyInstaller غير مثبّت. جارٍ التثبيت...
    python -m pip install --upgrade pyinstaller || exit /b 1
)
where makensis >nul 2>&1
if errorlevel 1 (
    echo   تنبيه: makensis غير موجود في PATH.
    echo   سيُبنى التطبيق لكن لن يُنتج ملف المُثبِّت.
    echo   حمّل NSIS من https://nsis.sourceforge.io ثم أعد التشغيل.
    set "NO_NSIS=1"
) else (
    set "NO_NSIS="
)
echo   الأدوات جاهزة.

echo.
echo ==== [3/5] فحص اكتشاف الوحدات وملفات البيانات ====
python tools\verify_spec_discovery.py
if errorlevel 1 (
    echo.
    echo   فشل الفحص المسبق. أُوقف البناء قبل إهدار الوقت.
    exit /b 1
)

echo.
echo ==== [4/5] بناء التطبيق (PyInstaller) ====
if exist "build_tmp" rmdir /s /q "build_tmp"
python -m PyInstaller --noconfirm --clean ^
    --distpath "dist\windows" ^
    --workpath "build_tmp" ^
    "build\windows\AhmedAlFaifiMarketImageStudioV2.spec"
if errorlevel 1 (
    echo.
    echo   فشل بناء التطبيق. راجع الرسائل أعلاه.
    exit /b 1
)
if not exist "dist\windows\AhmedAlFaifiMarketImageStudio\AhmedAlFaifiMarketImageStudio.exe" (
    echo.
    echo   خطأ: البناء انتهى لكن التنفيذي غير موجود.
    exit /b 1
)
echo   التطبيق جُمِّع بنجاح.

echo.
echo ==== [5/5] بناء المُثبِّت (NSIS) ====
if defined NO_NSIS (
    echo   تُخطّي: makensis غير متاح.
    echo.
    echo   الحزمة جاهزة في: dist\windows\AhmedAlFaifiMarketImageStudio\
    exit /b 0
)
if not exist "dist\installer" mkdir "dist\installer"
makensis "build\windows\installer_v295.nsi"
if errorlevel 1 (
    echo.
    echo   فشل بناء المُثبِّت. راجع الرسائل أعلاه.
    exit /b 1
)

echo.
echo ============================================================
echo   تم بنجاح.
echo   المُثبِّت: dist\installer\AhmedAlFaifiMarketImageStudio-Setup-2.9.5.exe
echo ============================================================
echo.
endlocal
