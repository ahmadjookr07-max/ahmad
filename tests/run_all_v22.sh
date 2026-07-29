#!/bin/bash
# تشغيل جميع اختبارات المشروع بالتسلسل مع ملخص نهائي
cd "$(dirname "$0")/.."
export PYTHONPATH=src:windows_app
export QT_QPA_PLATFORM=offscreen
pass=0; fail=0; failed_names=""
for t in tests/test_*.py; do
  if timeout 900 python3 "$t" >/tmp/last_test.log 2>&1; then
    echo "PASS  $t"
    pass=$((pass+1))
  else
    echo "FAIL  $t"
    tail -12 /tmp/last_test.log | sed 's/^/      /'
    fail=$((fail+1)); failed_names="$failed_names $t"
  fi
done
echo "=============================="
echo "الناجح: $pass | الفاشل: $fail"
[ -n "$failed_names" ] && echo "الفاشلة:$failed_names"
exit $fail
