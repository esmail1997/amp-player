# -*- coding: utf-8 -*-
"""تشخيص التقطيع: يشغّل نفس ملف الفيديو ويقيس:
- تقدّم زمن الوسائط مقابل الزمن الحقيقي
- عدد مرات فراغ مخزن الصوت (underrun) أثناء التشغيل
- عدد إطارات الفيديو المسلّمة (هل الصوت يسبق العرض أو العكس)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from ampplayer import av_engine

MOVIE = r"C:\Users\eksa2\Downloads\Video\Power_Ballad_2026_BluRay_-_[e.cimalight.co].mp4"

class ProbingEngine(av_engine.MediaEngine):
    def __init__(self):
        super().__init__()
        self.underruns = 0
        self.callbacks = 0

    def _pa_callback(self, outdata, frames, time_info, status):
        if self._audio_blocks.empty():
            self.underruns += 1
        self.callbacks += 1
        super()._pa_callback(outdata, frames, time_info, status)


def main():
    if not Path(MOVIE).exists():
        print("movie not found"); return 1
    eng = ProbingEngine()
    ok, err = eng.initialize()
    print("init:", ok, err)
    if not ok:
        return 1
    eng.on_frame = lambda arr, w, h: None   # نتجاهل العرض، نحسبه لاحقاً
    eng.on_error = lambda msg: print("ENGINE ERROR:", msg)
    ok, err = eng.open(MOVIE)
    print("open:", ok, err, "| duration:", eng.get_duration())
    if not ok:
        eng.close(); return 1
    print("audio device error:", eng._sd_error)

    samples = []
    fps_log = {"frames": 0}
    def count_frames(arr, w, h):
        fps_log["frames"] += 1
    eng.on_frame = count_frames
    start = time.perf_counter()
    eng.play()
    last_media = 0.0
    last_wall = start
    while time.perf_counter() - start < 20.0:
        time.sleep(0.5)
        now = time.perf_counter()
        m = eng.get_time()
        samples.append((now, m))
        dm = m - last_media
        dw = now - last_wall
        if dw > 0.4:
            print(f"  t={now-start:5.1f}s media={m:8.1f}/{eng.get_duration():.0f}"
                  f"  rate={dm/dw:6.3f}x  frames_delivered={fps_log['frames']}")
        last_media, last_wall = m, now
    eng.pause()
    print("--- summary ---")
    print(f"underruns: {eng.underruns} / callbacks: {eng.callbacks}")
    print(f"frames delivered: {fps_log['frames']}")
    rates = [m2[1]-m1[1] for m1, m2 in zip(samples, samples[1:])]
    if len(rates) >= 3 and any(r > 0 for r in rates):
        print(f"media advance per 0.5s: min={min(rates):.3f} max={max(rates):.3f}")
    eng.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())