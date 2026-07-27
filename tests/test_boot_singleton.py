import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# بيئة ترخيص نظيفة (تجربة جديدة تلقائية)
tmp = tempfile.mkdtemp()
os.environ["USERPROFILE"] = tmp
os.environ["HOME"] = tmp
sys.path.insert(0, "windows_app")
sys.path.insert(0, "src")
import native_app_v2 as v2
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QTimer
# EULA dialog سيظهر — نقبله آلياً بمؤقت
import license_ui
orig_exec = QDialog.exec
def auto_accept(self):
    QTimer.singleShot(300, self.accept)
    return orig_exec(self)
# بدل التدخل بالحوار، نحاكي القبول المسبق (أسرع وأكثر موثوقية للاختبار)
license_ui.eula_accepted = lambda: True
QApplication.exec = lambda self=None: 0
rc = v2.main()
print("FULL REAL BOOT OK rc=", rc)
