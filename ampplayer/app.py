"""نقطة تشغيل Amp Player."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

# التشغيل المباشر: حين يُنفَّذ هذا الملف بنفسه (`python ampplayer/app.py`،
# أو زر التشغيل في المحرّر) يضع بايثون *مجلد ampplayer* في المسار لا جذر
# المشروع، فيفشل `import ampplayer` بـ ModuleNotFoundError. نضيف الجذر هنا
# حتى يعمل التشغيل المباشر تماماً كتشغيل main.py.
_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, "") and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ضمان الترميز الصحيح للمخرجات على ويندوز (مهم للطباعة العربية)
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _module_present(name: str) -> bool:
    """
    يفحص وجود وحدة بايثون دون استيرادها.

    مهم: نكتفي بـ find_spec ولا نستورد. استيراد `av` يحمّل مكتبات FFmpeg
    كاملة، فالفحص بالاستيراد يبتلع وقت الإقلاع بلا فائدة، ويخالف هدف
    هذه الدالة أصلاً: أن تخبر المستخدم بما ينقص دون أن تُحمّل شيئاً.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _missing_packages() -> list[str]:
    """قائمة الحزم البايثونية الناقصة."""
    missing = []
    for mod, pkg in (("PySide6", "PySide6"), ("av", "av"),
                      ("numpy", "numpy"), ("sounddevice", "sounddevice"),
                      ("requests", "requests")):
        if not _module_present(mod):
            missing.append(pkg)
    return missing


def _ensure_deps() -> None:
    """
    رسالة واضحة إن كانت المكتبات مفقودة.

    ملاحظة: غياب FFmpeg المثبّت على النظام ليس خطأ قاتلاً. حزمة `av`
    تحمل مكتبات FFmpeg داخلها، فالتشغيل لا يحتاج تثبيتاً خارجياً؛ إن أُسقطت
    الحزمة فالواجهة تعرض نافذة المتطلبات.
    """
    missing = _missing_packages()
    if not missing:
        return
    print("=" * 62)
    print("Amp Player - missing dependencies")
    print("=" * 62)
    print("The following packages are required:")
    for m in missing:
        print(f"  - {m}")
    print()
    print("Install them with:")
    print(f"  {sys.executable} -m pip install -r requirements.txt")

    # الأغلب الساحق للحالات على ويندوز: شغّل المستخدم الملف بايثونِ
    # النظام بينما المكتبات مثبّتة في البيئة الافتراضية .venv.
    using_venv = ".venv" in str(Path(sys.executable)).replace("\\", "/")
    if os.name == "nt" and (_ROOT / ".venv").exists() and not using_venv and missing:
        print("-" * 62)
        print("The project libraries live in .venv; the system Python")
        print("does not have them. Launch the app normally instead:")
        print("  run.bat          (from the project folder)")
        print("  Amp Player.exe   (the installed app)")
        print("المكتبات مثبّتة داخل البيئة الافتراضية للبرنامج، وبايثون النظام لا "
              "يراها. شغّل البرنامج بالطريقة الصحيحة:")
        print("  run.bat          (من مجلد المشروع)")
        print("  Amp Player.exe   (التطبيق المثبّت)")
    print("=" * 62)
    sys.exit(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="amp-player",
        description="Amp Player - accessible audio/video player with subtitle support",
    )
    ap.add_argument("files", nargs="*", help="media files to open")
    ap.add_argument("--lang", choices=["ar", "en"], help="force interface language")
    ap.add_argument("--sub", dest="sub", help="subtitle file to load")
    ap.add_argument("--threads", type=int, default=0,
                    help="decoder threads (0 = let FFmpeg decide)")
    ap.add_argument("--selftest", action="store_true",
                    help="check every component and write selftest.txt, then exit")
    ap.add_argument("--version", action="store_true", help="show version and exit")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.version:
        from ampplayer import __version__

        print(f"Amp Player {__version__}")
        return 0

    if args.selftest:
        # ننفّذه قبل فحص المتطلبات: الفحص الذاتي نفسه يبلغ عن أي نقص
        from ampplayer.selftest import run

        return run()

    _ensure_deps()

    from ampplayer import config
    from ampplayer.ui.main_window import MainWindow
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    cfg = config.Config()
    if args.lang:
        cfg.set("lang", args.lang)
    if args.threads > 0:
        cfg.set("decode_threads", args.threads)
    cfg.sync()

    # دعم DPI العالي (مهم لقراءة أوضح)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv[:1] + (argv or []))
    app.setApplicationName("Amp Player")
    app.setApplicationDisplayName("Amp Player")
    app.setOrganizationName("AmpPlayer")
    app.setApplicationVersion(_version())

    # تحميل خط مناسب للعربية إن وُجد
    _apply_fonts(app)

    win = MainWindow()

    existing = [f for f in args.files if Path(f).exists()]
    if existing:
        # نضيف كل الملفات إلى القائمة ثم نشغّل أولها
        win.open_paths(existing, play_first=len(existing) == 1)
    if args.sub:
        win.load_subtitle_path(args.sub)

    win.show()

    # الترحيب في أول تشغيل
    if not cfg.get("onboarding_seen"):
        cfg.set("onboarding_seen", True)
        cfg.sync()
        try:
            from ampplayer.ui.onboarding import OnboardingDialog

            OnboardingDialog(win, win.tr).exec()
        except Exception:
            pass

    return app.exec()


def _version() -> str:
    try:
        from ampplayer import __version__

        return __version__
    except Exception:
        return "1.0.0"


def _apply_fonts(app) -> None:
    """يختار خطاً يدعم العربية بشكل جيد."""
    from PySide6.QtGui import QFont, QFontDatabase

    families = set(QFontDatabase.families())
    for name in ("Segoe UI", "Tahoma", "Arial", "Dubai", "Noto Sans Arabic"):
        if name in families:
            f = QFont(name, 11)
            f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
            app.setFont(f)
            return


if __name__ == "__main__":
    raise SystemExit(main())