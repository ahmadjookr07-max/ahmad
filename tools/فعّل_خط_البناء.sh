#!/usr/bin/env bash
# تفعيل خط بناء 2.9.5 على GitHub Actions.
#
# لماذا سكربت منفصل؟ لأن GitHub يمنع تطبيقات الأتمتة من إنشاء أو
# تعديل ملفات `.github/workflows/` بلا صلاحية `workflows` خاصة
# (الرسالة الحرفية: "refusing to allow a GitHub App to create or
# update workflow ... without workflows permission"). فالنقل يجب أن
# يجري برمز المالك نفسه.
#
# التشغيل من جذر المشروع:
#   bash tools/فعّل_خط_البناء.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."
NEW="build/ci/build-windows-295.yml"
DEST=".github/workflows/build-windows.yml"
OLD_OWNER=".github/workflows/build-owner-studio.yml"

echo "تفعيل خط بناء 2.9.5"
echo "════════════════════════════════════════"

[ -f "$NEW" ] || { echo "✗ لا يوجد $NEW — استنسخ المستودع كاملًا"; exit 1; }

# 1) أرشفة القديم بدل حذفه: قد نحتاج مراجعته.
if [ -f "$DEST" ]; then
  ver=$(grep -m1 -oE '2\.[0-9]+\.[0-9]+' "$DEST" || echo "غير معروف")
  echo "  القديم: الإصدار $ver — يُؤرشف في build/ci/"
  cp "$DEST" "build/ci/archived-build-windows-${ver}.yml"
fi

# 2) النقل.
mkdir -p .github/workflows
cp "$NEW" "$DEST"
echo "  ✓ نُقل خط بناء 2.9.5 إلى $DEST"

# 3) خط بناء المالك القديم يعمل على push فيستهلك دقائق بلا طلب،
#    وبرنامج المالك صار يُبنى داخل الخط الجديد. نؤرشفه ونحذفه.
if [ -f "$OLD_OWNER" ]; then
  cp "$OLD_OWNER" "build/ci/archived-build-owner-studio.yml"
  rm "$OLD_OWNER"
  echo "  ✓ أُبطل خط بناء المالك القديم (المالك يُبنى في الخط الجديد)"
fi

# 4) الدفع.
git add -A .github/workflows build/ci
if git diff --cached --quiet; then
  echo "  لا تغييرات — الخط مُفعَّل أصلًا"
else
  git commit -q -m "تفعيل خط بناء ويندوز 2.9.5 وإبطال خطوط 2.0.0"
  echo "  ✓ التزام محلي"
  echo
  echo "الدفع إلى GitHub..."
  git push origin main
  echo "  ✓ رُفع"
fi

cat <<'EOF'

════════════════════════════════════════
تمّ. الخطوة التالية على المتصفح:

  1. افتح صفحة Actions في المستودع
  2. اختر «بناء مُثبِّت ويندوز 2.9.5» من القائمة اليسرى
  3. اضغط Run workflow  →  Run workflow

  المدة المتوقعة: 35-50 دقيقة
  الناتج: Setup-User-2.9.5  (أسفل صفحة التشغيل، قسم Artifacts)

ملاحظة: إن أردت تضمين شفرة المالك في البناء، أضف السرّ
OWNER_SECRETS_JSON من Settings > Secrets and variables > Actions
قبل التشغيل. بغيره يُبنى البرنامج لكن مع تحذير عن الربط.
EOF
