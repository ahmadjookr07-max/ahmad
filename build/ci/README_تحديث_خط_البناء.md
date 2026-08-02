# تحديث خط البناء الآلي

منصة Manus لا تملك صلاحية `workflows` لتعديل ملفات `.github/workflows/` مباشرة،
لذلك النسخة الجديدة من خط البناء محفوظة هنا: `build/ci/build-windows.yml`.

## لتفعيلها (خطوة واحدة على جهازك)

```bash
git pull
cp build/ci/build-windows.yml .github/workflows/build-windows.yml
git add .github/workflows/build-windows.yml
git commit -m "تحديث خط البناء 2.9.5"
git push
```

أو من موقع GitHub مباشرة: افتح `.github/workflows/build-windows.yml`
واضغط زر التعديل (قلم) والصق محتوى `build/ci/build-windows.yml` ثم احفظ.

## ماذا يفعل خط البناء الجديد
- يتحقق من سلامة الربط بين برنامج المالك والمستخدم قبل أي بناء (`tools/verify_owner_link.py`)
- ينزّل نماذج القص تلقائيًا (ISNet + U2Net)
- يبني برنامج المستخدم بـ PyInstaller
- يبني برنامج المالك بـ PyInstaller
- يبني مثبّت المستخدم بـ NSIS (`installer_v295.nsi`)
- يبني مثبّت المالك بـ NSIS (`installer_owner_v295.nsi`)
- يرفع المثبّتين كـ artifacts جاهزين للتنزيل
