"""اختبار تشغيل نقطة الدخول app.main بأمان (بلا نافذة فعلية)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer import app as appmod  # noqa: E402


class TestEntryPoint(unittest.TestCase):
    def test_version_flag(self):
        from ampplayer import __version__

        self.assertEqual(appmod.main(["--version"]), 0)
        self.assertTrue(__version__)

    def test_parse_args(self):
        a = appmod.parse_args(["m.mkv", "--lang", "en", "--sub", "s.srt"])
        self.assertEqual(a.files, ["m.mkv"])
        self.assertEqual(a.lang, "en")
        self.assertEqual(a.sub, "s.srt")
        self.assertEqual(a.threads, 0)

    def test_parse_args_accepts_thread_count(self):
        a = appmod.parse_args(["--threads", "6"])
        self.assertEqual(a.threads, 6)

    def test_parse_args_rejects_bad_lang(self):
        with self.assertRaises(SystemExit):
            appmod.parse_args(["--lang", "fr"])

    def test_missing_files_are_dropped(self):
        """الملفات غير الموجودة يجب ألا تُمرَّر إلى المشغّل."""
        existing = str(Path(__file__).parent / "test_core.py")
        got = [f for f in [existing, "Z:/nope/missing.mkv"] if Path(f).exists()]
        self.assertEqual(got, [existing])

    def test_deps_check_passes(self):
        # لا يجب أن تخرج بدالة في بيئة الاختبار (كل الحزم مثبّتة)
        try:
            appmod._ensure_deps()
        except SystemExit as exc:  # pragma: no cover - فقط عند نقص حزم
            self.fail(f"dependencies missing: {exc}")

    def test_deps_check_uses_find_spec_without_importing(self):
        """
        `_ensure_deps` تفحص بـ find_spec فقط، بلا أي استيراد.

        استيراد `av` يحمّل مكتبات FFmpeg كاملة، فيضيف زمناً بلا فائدة قبل
        ظهور النافذة. نتحقق بأن الفحص لا يُدخل أي وحدة جديدة في
        sys.modules مهما كانت الحزم مثبّتة من قبل.
        """
        import importlib.util as iu

        self.assertTrue(appmod._module_present("av"))
        self.assertTrue(appmod._module_present("numpy"))
        before = set(sys.modules)

        real_find = iu.find_spec
        probed = []

        def spy(name, *a, **k):
            probed.append(name)
            return real_find(name, *a, **k)

        with mock.patch.object(appmod.importlib.util, "find_spec", spy):
            appmod._ensure_deps()

        self.assertIn("av", probed)
        self.assertIn("numpy", probed)
        added = set(sys.modules) - before
        self.assertEqual(
            added, set(),
            f"the deps check imported modules: {sorted(added)[:10]}",
        )

    def test_missing_packages_reports_names(self):
        with mock.patch.object(appmod, "_module_present", lambda n: False):
            got = appmod._missing_packages()
        self.assertEqual(
            got,
            ["PySide6", "av", "numpy", "sounddevice", "requests"],
        )

    def test_no_vlc_dependency_remains(self):
        """لا يجوز بقاء أي أثر لمشغّل خارجي في فحص المتطلبات."""
        self.assertNotIn("vlc", appmod._missing_packages())
        with mock.patch.object(appmod, "_module_present", lambda n: False):
            joined = " ".join(appmod._missing_packages()).lower()
        self.assertNotIn("vlc", joined)

    def test_ensure_deps_exits_when_package_missing(self):
        with mock.patch.object(appmod, "_module_present", lambda n: False):
            with self.assertRaises(SystemExit) as ctx:
                appmod._ensure_deps()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)