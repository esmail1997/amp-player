"""
اختبارات محرّك التشغيل نفسه (FFmpeg عبر PyAV).

هذه اختبارات بلا Qt: المحرّك مكتوب بلا اعتماد على الواجهة عمداً، فيمكن
اختباره وحده وبسرعة. كل اختبار يبني ملفه بنفسه بمحرّك FFmpeg نفسه، فلا
نحتاج عيّنة في المستودع ولا مشغّلاً مثبَّتاً على النظام.
"""

from __future__ import annotations

import fractions
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer import av_engine  # noqa: E402

# مهلة انتظار لتقدّم زمن حقيقي. الملفات في هذه الاختبارات ثوانٍ معدودة،
# والانتظار يجب أن يتجاوزه بوضوح حتى لا يفشل الاختبار على جهاز محمول بطيء.
SETTLE = 30.0


def _have_av() -> bool:
    return av_engine.av_available()[0]


def _have_numpy() -> bool:
    try:
        import numpy
    except Exception:
        return False
    return numpy is not None


def build_av(path: Path, *, seconds: float = 4.0, fps: int = 10,
             with_audio: bool = True) -> None:
    """يبني مقطعاً: شريط ألوان متحرك + نغمة واحدة ثابتة النغمة."""
    import av
    import numpy as np

    width, height, rate = 320, 240, 44100
    frames = int(seconds * fps)
    with av.open(str(path), "w") as out:
        vs = out.add_stream("libx264", rate=fps)
        vs.width, vs.height, vs.pix_fmt = width, height, "yuv420p"
        ast = out.add_stream("aac", rate=rate) if with_audio else None

        for i in range(frames):
            arr = np.full((height, width, 3), (i * 7) % 255, dtype=np.uint8)
            vf = av.VideoFrame.from_ndarray(arr, format="rgb24").reformat(
                format="yuv420p")
            vf.pts = i
            for pkt in vs.encode(vf):
                out.mux(pkt)
        for pkt in vs.encode():
            out.mux(pkt)

        if ast is not None:
            step = 1024
            total = rate * seconds
            k = 0
            while k * step < total:
                buf = np.zeros((2, step), dtype="float32")
                t = np.arange(step) / float(rate)
                buf[0, :] = 0.2 * np.sin(2 * np.pi * 440.0 * t)
                buf[1, :] = buf[0, :]
                af = av.AudioFrame.from_ndarray(
                    buf, format="fltp", layout="stereo")
                af.sample_rate = rate
                af.pts = k * step
                k += 1
                for pkt in ast.encode(af):
                    out.mux(pkt)
            for pkt in ast.encode():
                out.mux(pkt)


@contextmanager
def workdir():
    """
    مجلد مؤقت يُغسل بعد إغلاق الملف.

    على ويندوز لا يمكن حذف ملف مفتوح، فإغلاق المحرّك يجب أن يقع داخل
    الكتلة لا بعدها، وإلا فشل التنظيف لا الاختبار.
    """
    tmp = tempfile.TemporaryDirectory()
    try:
        yield Path(tmp.name)
    finally:
        tmp.cleanup()


class _FakeConfig:
    """
    إعدادات في الذاكرة.

    ضبط الإزاحة يكتبها فوراً، ومن يختبر المحرّك لا يجوز أن يغيّر إعدادات
    المستخدم الحقيقية.
    """

    def __init__(self) -> None:
        self.data: dict = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value

    def sync(self) -> None:
        pass


@contextmanager
def opened(path: Path):
    """
    محرّك مفتوح على ملف، يُغلق حتماً عند الخروج.

    نضع الإغلاق في الكتلة نفسها لأن محرّك FFmpeg يُبقي مقبض الملف مفتوحاً،
    وحذف المجلد المؤقت قبل الإغلاق يفشل على ويندوز.
    """
    eng = av_engine.MediaEngine()
    ok, err = eng.initialize()
    if not ok:
        raise AssertionError(f"engine init failed: {err}")
    try:
        ok, err = eng.open(str(path))
        if not ok:
            raise AssertionError(f"open failed: {err}")
        yield eng
    finally:
        eng.close()


class _Collector:
    """يجمع ما يبلّغ به المحرّك في خيوطه، مع عدّاد."""

    def __init__(self) -> None:
        self.frames = 0
        self.width = 0
        self.height = 0
        self.ended = threading.Event()
        self.errors: list[str] = []
        self.lock = threading.Lock()

    def frame(self, arr, width: int, height: int) -> None:
        with self.lock:
            self.frames += 1
            self.width, self.height = width, height

    def error(self, msg: str) -> None:
        with self.lock:
            self.errors.append(str(msg))

    def end(self) -> None:
        self.ended.set()

    @property
    def count(self) -> int:
        with self.lock:
            return self.frames


@unittest.skipUnless(_have_av() and _have_numpy(), "PyAV/numpy not installed")
class TestEnginePlayback(unittest.TestCase):
    """تشغيل حقيقي: إطارات، إيقاف مؤقت، قفز زمني، سرعة، ونهاية ملف."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls._tmp.name) / "clip.mkv"
        build_av(cls.path, seconds=4.0, fps=10)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _engine(self):
        """محرّك مفتوح على المقطع المشترك. يُغلق في نهاية الاختبار."""
        eng = av_engine.MediaEngine()
        ok, err = eng.initialize()
        self.assertTrue(ok, err)
        self.addCleanup(eng.close)
        ok, err = eng.open(str(self.path))
        self.assertTrue(ok, err)
        return eng

    @staticmethod
    def _attach(eng, col: _Collector) -> None:
        eng.on_frame = col.frame
        eng.on_error = col.error
        eng.on_end = col.end

    def test_plays_every_frame_to_the_end(self):
        """
        التشغيل من الأول للنهاية يجب أن يسلّم كل إطار بالضبط مرة.

        هذا الاختبار كان إنذاراً حقيقياً: فقدان الإطارات يعني أن المستخدم
        يرى حركة متقطّعة، وهو أسوأ من البطء لأنه لا يلاحظه إلا بالعين.
        """
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        eng.play()
        self.assertTrue(col.ended.wait(SETTLE), "playback never reached the end")
        # بعد الوصول للنهاية يجب أن يهدأ العدّاد: لا إطارات متأخرة
        time.sleep(0.3)
        self.assertEqual(col.errors, [])
        self.assertEqual(col.count, 40)
        self.assertEqual((col.width, col.height), (320, 240))

    def test_time_reaches_the_end_within_the_duration(self):
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        eng.play()
        self.assertTrue(col.ended.wait(SETTLE))
        self.assertGreaterEqual(eng.get_time(), 3.5)
        # get_time لا يتجاوز المدة أبداً، وإلا انكسر شريط التقدّم
        self.assertLessEqual(eng.get_time(), eng.get_duration() + 0.01)

    def test_pause_holds_time_and_resume_continues(self):
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        eng.play()
        time.sleep(1.0)
        eng.pause()
        self.assertFalse(eng.is_playing())
        held = eng.get_time()
        # هدأة قصيرة: أي إطار كان قيد التوصيل لحظة الإيقاف قد وصل بالفعل.
        # دونها يكون الاختبار سباقاً غير قابل للتكرار (إطارٌ واحد معلّق).
        time.sleep(0.2)
        count_at_pause = col.count

        # وأثناء الإيقاف لا يتقدّم الزمن ولا يستهلك المحرّك إطارات
        time.sleep(0.8)
        self.assertAlmostEqual(eng.get_time(), held, delta=0.05)
        self.assertEqual(col.count, count_at_pause)

        eng.play()
        self.assertTrue(eng.is_playing())
        time.sleep(0.5)
        self.assertGreater(eng.get_time(), held + 0.2)
        self.assertTrue(col.ended.wait(SETTLE))
        self.assertEqual(col.errors, [])

    def test_seek_lands_inside_the_file_and_keeps_playing(self):
        """
        القفز إلى الثانية الثانية يجب أن ينتهي داخل الملف لا عند نهايته.

        هذا كان الخطأ الأخطر في المحرّك: PyAV يفسّر الإزاحة بوحدات
        time_base للمسار عند تمرير مسار، وبالميكروثانية عند عدمه، فالخطأ
        يقفز إلى آخر الملف أو يتجاوزه فتتوقف اللاعب.
        """
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        eng.play()
        time.sleep(0.6)
        eng.set_time(2.0)

        t = eng.get_time()
        self.assertGreater(t, 1.5, f"seek landed at {t}")
        self.assertLess(t, 3.0, f"seek overshot to {t}")

        self.assertTrue(col.ended.wait(SETTLE), "playback died after seek")
        self.assertEqual(col.errors, [])

    def test_relative_seek_moves_in_both_directions(self):
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        eng.play()
        time.sleep(0.6)
        eng.set_time(2.0)
        after_forward = eng.get_time()
        eng.seek_relative(-1.0)
        after_back = eng.get_time()
        self.assertLess(after_back, after_forward)
        self.assertGreater(after_back, 0.5)

    def test_rate_change_keeps_advancing(self):
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        eng.play()
        time.sleep(0.4)
        self.assertEqual(eng.set_rate(2.0), 2.0)
        self.assertEqual(eng.get_rate(), 2.0)
        before = eng.get_time()
        time.sleep(0.6)
        after = eng.get_time()
        self.assertGreater(after, before + 0.5,
                           "time did not advance at 2x")
        eng.set_rate(1.0)
        self.assertEqual(eng.get_rate(), 1.0)

    def test_stop_returns_to_zero_and_allows_play_again(self):
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        eng.play()
        time.sleep(0.6)
        eng.stop()
        self.assertAlmostEqual(eng.get_time(), 0.0, delta=0.1)
        self.assertFalse(eng.is_playing())

        # إعادة التشغيل على الملف نفسه يجب أن تعمل: هذا ما يفعله المستخدم
        # حين يضغط تشغيل مرتين، وقد كان _eos لا يُصفَّر فينتهي فوراً.
        eng.play()
        self.assertTrue(eng.is_playing())
        self.assertTrue(col.ended.wait(SETTLE),
                        "replay after stop did not run to the end")
        self.assertGreater(col.count, 0)

    def test_volume_clamp_and_mute_do_not_break_playback(self):
        eng = self._engine()
        col = _Collector()
        self._attach(eng, col)

        # الحد الأقصى 200% تضخيم، فالصوت فوق 100 مشروع ومقصود
        self.assertEqual(eng.set_volume(0), 0)
        self.assertEqual(eng.set_volume(500), 200)
        self.assertEqual(eng.set_volume(-5), 0)
        self.assertEqual(eng.set_volume(70), 70)
        self.assertEqual(eng.get_volume(), 70)

        # الكتم مستقل عن المستوى: يكتم ولا يغيّر الرقم، فيستعيده فوراً
        eng.set_muted(True)
        self.assertTrue(eng.is_muted())
        self.assertEqual(eng.get_volume(), 70)
        eng.set_muted(False)
        self.assertFalse(eng.is_muted())

        eng.play()
        self.assertTrue(col.ended.wait(SETTLE))
        self.assertEqual(col.errors, [])


@unittest.skipUnless(_have_av() and _have_numpy(), "PyAV/numpy not installed")
class TestEngineSeekStress(unittest.TestCase):
    """القفز المتكرر يجب ألّا يُفقد الإطارات ولا يُطفئ التشغيل."""

    def test_repeated_seeks_keep_frames_flowing(self):
        with workdir() as d:
            path = d / "clip.mkv"
            build_av(path, seconds=6.0, fps=10)
            with opened(path) as eng:
                col = _Collector()
                eng.on_frame = col.frame
                eng.on_error = col.error
                eng.on_end = col.end

                eng.play()
                for target in (3.0, 1.0, 4.0, 0.5, 2.5):
                    time.sleep(0.35)
                    eng.set_time(target)
                    landed = eng.get_time()
                    self.assertGreaterEqual(
                        landed, target - 0.5,
                        f"seek to {target} landed at {landed}")
                    self.assertLess(landed, eng.get_duration(),
                                    f"seek to {target} overshot to {landed}")
                    self.assertEqual(col.errors, [])

                self.assertTrue(col.ended.wait(SETTLE),
                                "engine stopped producing frames after seeks")
                self.assertGreater(col.count, 0)


@unittest.skipUnless(_have_av() and _have_numpy(), "PyAV/numpy not installed")
class TestEngineVideoOnly(unittest.TestCase):
    """ملف بلا صوت مسار حقيقي (مقاطع صامتة شائعة) ويجب أن يُشغَّل."""

    def test_video_only_file_plays_on_the_wall_clock(self):
        with workdir() as d:
            path = d / "silent.mkv"
            build_av(path, seconds=2.0, fps=10, with_audio=False)
            with opened(path) as eng:
                self.assertFalse(eng.info.has_audio)

                col = _Collector()
                eng.on_frame = col.frame
                eng.on_error = col.error
                eng.on_end = col.end

                started = time.perf_counter()
                eng.play()
                self.assertTrue(col.ended.wait(SETTLE))
                elapsed = time.perf_counter() - started
                # بلا ساعة صوت فالزمن يمرّ بالساعة الجدارية، فلا يجوز أن يمرّ
                # أسرع بكثير ولا أبطأ بكثير.
                self.assertGreater(elapsed, 1.0)
                self.assertLess(elapsed, 6.0)
                self.assertEqual(col.count, 20)


@unittest.skipUnless(_have_av(), "PyAV not installed")
class TestEngineMetadata(unittest.TestCase):
    """قراءة البيانات الوصفية والمسارات بلا تشغيل."""

    def test_tracks_expose_kind_and_text_flag(self):
        with workdir() as d:
            path = d / "clip.mkv"
            build_av(path, seconds=1.0, fps=5)
            with opened(path) as eng:
                kinds = {t.kind for t in eng.info.tracks}
                self.assertIn("video", kinds)
                self.assertIn("audio", kinds)

                video = eng.get_tracks("video")
                self.assertTrue(video)
                self.assertEqual(video[0].kind, "video")
                self.assertEqual(
                    (video[0].width, video[0].height), (320, 240))
                self.assertTrue(video[0].label)
                self.assertIn("video", video[0].label)

                audio = eng.get_tracks("audio")
                self.assertTrue(audio)
                self.assertEqual(audio[0].kind, "audio")
                self.assertGreater(audio[0].channels, 0)
                self.assertGreater(audio[0].sample_rate, 0)

                self.assertEqual(eng.get_tracks("subtitle"), [])

    def test_selecting_a_missing_audio_stream_keeps_playing(self):
        with workdir() as d:
            path = d / "clip.mkv"
            build_av(path, seconds=1.0, fps=5)
            with opened(path) as eng:
                # طلب مسار غير موجود يجب أن يُرفض بصمت لا أن يكسر التشغيل
                self.assertFalse(eng.select_audio_stream(999))
                self.assertTrue(eng.info.has_audio)


@unittest.skipUnless(_have_av(), "PyAV not installed")
class TestEmbeddedSubtitles(unittest.TestCase):
    """الترجمة المدمجة لا تُقرأ؛ الترجمة الخارجية هي المصدر المدعوم."""

    SRT = (
        b"1\n00:00:00,000 --> 00:00:01,000\nFirst line\n\n"
        b"2\n00:00:01,000 --> 00:00:02,000\nSecond line\n\n"
        b"3\n00:00:02,000 --> 00:00:03,000\nThird line\n\n"
    )

    def _build_with_subs(self, path: Path) -> None:
        """
        نبني مقطعاً بترجمة مدمجة.

        نحقن نص SRT جاهزاً كحزمة واحدة: هذا أقرب ما يكون لملف حقيقي
        مبنيّ بأداة خارجية، ولا يربط اختبارنا بترميز ASS الداخلي.
        """
        import av
        import numpy as np

        with av.open(str(path), "w") as out:
            vs = out.add_stream("libx264", rate=10)
            vs.width, vs.height, vs.pix_fmt = 320, 240, "yuv420p"
            ss = out.add_stream("ass")
            ss.time_base = fractions.Fraction(1, 1000)
            for i in range(40):
                arr = np.zeros((240, 320, 3), dtype=np.uint8)
                vf = av.VideoFrame.from_ndarray(
                    arr, format="rgb24").reformat(format="yuv420p")
                vf.pts = i
                for pkt in vs.encode(vf):
                    out.mux(pkt)
            for pkt in vs.encode():
                out.mux(pkt)
            pkt = av.Packet(self.SRT)
            pkt.stream = ss
            pkt.pts = 0
            pkt.duration = 4000
            pkt.time_base = fractions.Fraction(1, 1000)
            out.mux(pkt)

    @contextmanager
    def _open(self, d: Path):
        """ملف بترجمة مدمجة ومحرّك مفتوح عليه، داخل كتلة واحدة."""
        path = d / "subs.mkv"
        self._build_with_subs(path)
        with opened(path) as eng:
            yield eng

    def test_embedded_cues_are_ignored(self):
        with workdir() as d:
            with self._open(d) as eng:
                self.assertEqual(eng.cues, [])

    def test_cue_lookup_has_no_embedded_lines(self):
        with workdir() as d:
            with self._open(d) as eng:
                for pos in (0, 500, 1000, 2500, 9999):
                    self.assertIsNone(eng.cue_at(pos))

    def test_sub_delay_does_not_create_embedded_cues(self):
        with workdir() as d:
            with self._open(d) as eng:
                self.assertEqual(eng.get_sub_delay(), 0.0)
                eng.set_sub_delay(1.0)
                self.assertEqual(eng.get_sub_delay(), 1.0)
                self.assertIsNone(eng.cue_at(1500))
                eng.set_sub_delay(0.0)
                self.assertIsNone(eng.cue_at(500))

    def test_sub_delay_sign_matches_the_subtitle_engine(self):
        """
        المحرّك و SubtitleEngine يجب أن يُزيحا في الاتجاه نفسه.

        اختلفت الإشارتان ذات مرة، فكل واحدة تُظهر الترجمة متأخرة عن
        الأخرى فيلغي أثرها، ولا يكتشف المستخدم السبب.
        """
        from ampplayer.subtitle_engine import SubtitleEngine

        with workdir() as d:
            with self._open(d) as eng:
                se = SubtitleEngine(cfg=_FakeConfig())
                se.load_cues(eng.cues, "embedded", None)

                for delay in (-1.0, -0.5, 0.5, 1.0, 2.5):
                    with self.subTest(delay=delay):
                        eng.set_sub_delay(delay)
                        se.set_offset_seconds(delay)
                        for pos in range(0, 3500, 100):
                            mine = eng.cue_at(pos)
                            theirs = se.update(pos)
                            self.assertEqual(
                                mine.text if mine else None,
                                theirs.text if theirs else None,
                                f"disagreement at {pos} ms with delay {delay}",
                            )

@unittest.skipUnless(_have_av(), "PyAV not installed")
class TestEngineErrors(unittest.TestCase):
    """المداخل الخاطئة يجب أن تُبلَّغ برسالة لا بانهيار."""

    def test_missing_file(self):
        eng = av_engine.MediaEngine()
        self.assertTrue(eng.initialize()[0])
        self.addCleanup(eng.close)
        ok, err = eng.open("definitely_not_here_12345.mkv")
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_directory_instead_of_file(self):
        with tempfile.TemporaryDirectory() as d:
            eng = av_engine.MediaEngine()
            self.assertTrue(eng.initialize()[0])
            self.addCleanup(eng.close)
            ok, err = eng.open(d)
            self.assertFalse(ok)
            self.assertTrue(err)

    def test_calls_before_open_are_harmless(self):
        eng = av_engine.MediaEngine()
        self.assertTrue(eng.initialize()[0])
        self.addCleanup(eng.close)
        # الواجهة قد تستدعي هذه قبل الفتح؛ لا يجوز أن تنهار
        eng.play()
        eng.pause()
        eng.stop()
        eng.set_time(5.0)
        eng.seek_relative(10.0)
        eng.set_rate(2.0)
        self.assertEqual(eng.get_time(), 0.0)
        self.assertEqual(eng.get_position(), 0.0)
        self.assertEqual(eng.cues, [])
        self.assertIsNone(eng.cue_at(1000))

    def test_close_twice_is_safe(self):
        with workdir() as d:
            path = d / "clip.mkv"
            build_av(path, seconds=1.0, fps=5)
            eng = av_engine.MediaEngine()
            self.assertTrue(eng.initialize()[0])
            self.assertTrue(eng.open(str(path))[0])
            eng.play()
            eng.close()
            eng.close()


@unittest.skipUnless(_have_av(), "PyAV not installed")
class TestEngineAvailability(unittest.TestCase):
    """المحرّك مدمج في الحزمة، فحالته تُفحص ولا تُثبَّت."""

    def test_av_available_pair(self):
        ok, err = av_engine.av_available()
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_version_mentions_ffmpeg(self):
        ver = av_engine.av_version()
        self.assertTrue(ver)
        self.assertIn("FFmpeg", ver)

    def test_audio_absence_does_not_block_the_engine(self):
        eng = av_engine.MediaEngine()
        ok, err = eng.initialize()
        self.assertTrue(ok, err)


if __name__ == "__main__":
    unittest.main(verbosity=2)