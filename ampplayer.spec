# -*- mode: python ; coding: utf-8 -*-
"""
حزمة Amp Player إلى مجلد تنفيذي واحد.

البناء:
    .venv\\Scripts\\python.exe -m PyInstaller ampplayer.spec --noconfirm

الناتج:
    dist\\Amp Player\\Amp Player.exe     (مجلد كامل جاهز للنسخ)
    dist\\Amp Player\\selftest.txt       (يكتب نفسه بعد --selftest)

ملاحظات:
- الخطافات الرسمية لـ PyInstaller تتكفّل بـ av (بما فيها DLLات FFmpeg داخل
  av.libs) و sounddevice (PortAudio) و pyttsx3 و lxml و comtypes؛ لذلك لا
  نجمّع يدوياً إلا ما يُستورد ديناميكياً.
- الترشيح أسفله لوحدات Qt غير المستخدمة: البرنامج يكتفي بـ
  QtCore / QtGui / QtWidgets.
"""

from pathlib import Path

ROOT = Path(SPECPATH)

# ---------------------------------------------------------------- رشوّح Qt
# المستخدَم فعلاً في ampplayer/: QtCore, QtGui, QtWidgets (بالإضافة إلى
# QtSvg و QtNetwork الصغيرين لأن إضافات Qt مثل محوّلات الصور ت linking
# عليهما؛ استبعادهما يسبّب تحذيرات تحميل لا أخطاء، فالأفضل إبقاؤهما).
EXCLUDED_QT = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtAxContainer", "PySide6.QtBluetooth", "PySide6.QtCharts",
    "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtGraphs", "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp", "PySide6.QtHttpServer", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
    "PySide6.QtNetworkAuth", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
    "PySide6.QtPrintSupport", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTest",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    "PySide6.QtWinExtras", "PySide6.QtXml",
]

EXCLUDES = EXCLUDED_QT + [
    "tkinter",
    "PyQt5", "PyQt6", "PySide2",
    "av.tests",         # حزمة اختبارات PyAV لا حاجة لها داخل البرنامج
    "setuptools", "pkg_resources",
]

# -------------------------------------------------- استيرادات ديناميكية
HIDDEN = [
    # pyttsx3 يبني محرك النطق ديناميكياً (الخطاف الرسمي يضيف sapi5 أيضاً)
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "pyttsx3.drivers.dummy",
    # مطلوب لمحرّك SAPI عبر comtypes (واجهة IStream)
    "comtypes.stream",
    # وحدات محرّك الترجمة الشامل: بعضها يُستورد داخل دوال (استيراد مؤجّل)
    # في main_window، فنضمّنها صراحةً لضمان وجودها في النسخة المُجمَّعة.
    "ampplayer.subtitle_text",
    "ampplayer.subtitle_manager",
    "ampplayer.youtube_subs",
    "ampplayer.contact",
    "ampplayer.ui.about_dialog",
]

# لا نضيف استيرادات صريحة لـ bs4/lxml: البرنامج لا يستخدمهما أصلاً
# (المواقع تُحلَّل بتعبيرات نمطية)، وإضافتهما تسترجع الحزمتين بالكامل.

# --------------------------------------------------- إزالة مكتبات زائدة
# فحص مرجعي: مسحت كل DLL/PYD في الحزمة بحثاً عن من يعتمد على ما يلي،
# ولم يشأر إلا الإضافتين الجذريتين نفسيهما. أي حذف لهما يُسقط مكتباتهما
# معها، ولا شيء في البرنامج يحتاج أيّاً منها (لا نرسم بـ OpenGL ولا نعرض
# PDF ولا لوحة مفاتيح افتراضية).
DROP_NAMES = {
    # Qt uses Windows ICU. A Poppler ICU from the build PATH is incompatible.
    "icuuc.dll", "icudt78.dll",
    "opengl32sw.dll",           # OpenGL برمجي بـ 19.7 م.ب: رسوماتنا widgets فقط
    "qpdf.dll",                 # إضافة صور PDF
    "qtvirtualkeyboardplugin.dll",  # إضافة لوحة المفاتيح على اللمس
    "Qt6Pdf.dll",
    "Qt6VirtualKeyboard.dll",
    "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlMeta.dll",
    "Qt6QmlWorkerScript.dll", "Qt6OpenGL.dll",
}


def _wanted(toc_entry) -> bool:
    dest = str(toc_entry[0]).replace("\\", "/").lower()
    return not any(dest.endswith(name.lower()) for name in DROP_NAMES)


ICON = str(ROOT / "tools" / "amp_player.ico")
VERSION = str(ROOT / "version_info.txt")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    excludes=EXCLUDES,
    noarchive=False,
)

# فرز ما جمعه خطاف PySide6 (الإضافات تُجلَب كملفات، فلا يكفي الاستبعاد)
a.binaries = [e for e in a.binaries if _wanted(e)]
a.datas = [e for e in a.datas if _wanted(e)]

# ملفات ثنائية نضمّنها يدوياً:
#  - nvdaControllerClient.dll: جسر NVDA Controller Client (رخصة LGPL يجيز التضمين)
#  - libmpv-2.dll: mpv نفسها لمحرك التشغيل الجديد
import os as _os

for _src, _dst in (
    (_os.path.join(ROOT, "vendor", "controllerClient", "x64", "nvdaControllerClient.dll"), "nvdaControllerClient.dll"),
    (_os.path.join(ROOT, "vendor", "mpv", "libmpv-2.dll"), "libmpv-2.dll"),
):
    if _os.path.exists(_src):
        a.binaries.append((_dst, _src, "BINARY"))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Amp Player",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # بلا وحدة تحكم: نافذة عادية لا تفتح نافذة سطر أوامر سوداء
    console=False,
    # نافذة الخطأ عند التعطّل أرحم من الإغلاق الصامت (وقارئ الشاشة يقرأها)
    disable_windowed_traceback=False,
    icon=ICON,
    version=VERSION,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Amp Player",
)
