# -*- coding: utf-8 -*-
"""تشخيص ثانٍ: المسار الكامل عبر PlayerController + QApplication offscreen.
يقيس:
- underruns في مخزن الصوت أثناء تشغيل واجهة كاملة
- تراكم أحداث إطارات الفيديو في طابور الخيط الرئيسي (تجمد الواجهة)
- استجابة حلقة الأحداث (قفزات المؤقت)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMP_CONFIG_FILE"] = os.environ.get("TEMP", ".") + "\\amp_diag_config.ini"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from ampplayer.player import PlayerController

MOVIE = r"C:\Users\eksa2\Downloads\Video\Power_Ballad_2026_BluRay_-_[e.cimalight.co].mp4"

app = QApplication.instance() or QApplication([])
player = PlayerController()
ok, err = player.initialize()
print("player init:", ok, err)
player.set_frame_sink(lambda img: None)
player.set_render_max(1152, 480)
eng = player._engine

underruns = {"n": 0}
eng._pa_callback_pre = eng._pa_callback
def wrap(outdata, frames, time_info, status):
    if eng._audio_blocks.empty() and eng._playing.is_set():
        underruns["n"] += 1
    return eng._pa_callback_pre(outdata, frames, time_info, status)
eng._pa_callback = wrap

ok, err = player.load(MOVIE)
print("load:", ok, err)
player.play()

# مراقبة استجابة الخيط الرئيسي
last_tick = {"t": time.perf_counter(), "max_gap": 0.0}
def tick():
    now = time.perf_counter()
    gap = now - last_tick["t"]
    last_tick["t"] = now
    if gap > last_tick["max_gap"]:
        last_tick["max_gap"] = gap
ticker = QTimer(); ticker.setInterval(50); ticker.timeout.connect(tick); ticker.start()

samples = []
start = time.perf_counter()
widgets = app.allWidgets()
while time.perf_counter() - start < 15.0:
    app.processEvents()
    time.sleep(0.5)
    samples.append((player.get_time(), eng._audio_blocks.qsize(),
                    player._frame_arr is not None))

player.pause()
print("--- summary ---")
print(f"underruns: {underruns['n']}")
print(f"audio queue sizes seen: {sorted({s[1] for s in samples})}")
print(f"media time at end: {samples[-1][0]}ms  (15s wall)")
print(f"max UI event-loop gap: {last_tick['max_gap']:.3f}s (interval 50ms)")
player.release()
print("done")