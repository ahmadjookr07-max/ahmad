import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "windows_app")
sys.path.insert(0, "src")
import native_app_v2 as v2
# محاكاة مسار الإقلاع الحقيقي: السبلاش أولاً (ينشئ QApplication) ثم native_app.main
v2._show_splash()
from PySide6.QtWidgets import QApplication
app1 = QApplication.instance()
assert app1 is not None, "splash did not create QApplication"
v2._activate_engine()
import native_app
native_app.APP_VERSION = v2.APP_VERSION_V2
# بوابة الترخيص تحتاج تفعيل — نتجاوزها للاختبار (نختبر إنشاء QApplication فقط)
import license_ui
license_ui.ensure_activated = lambda *a, **k: True
v2._gate_startup(native_app)
v2._patch_ui(native_app)
# استدعاء main مع إغلاق فوري عبر QTimer
from PySide6.QtCore import QTimer
orig_exec = QApplication.exec
def fake_exec(self=None):
    return 0
QApplication.exec = fake_exec
rc = native_app.main()
print("BOOT OK rc=", rc)
app2 = QApplication.instance()
assert app1 is app2, "QApplication recreated!"
print("SAME QAPP INSTANCE — FIX CONFIRMED")
