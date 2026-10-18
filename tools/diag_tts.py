# -*- coding: utf-8 -*-
"""تشخيص رابع - حاسم: هل نطق SAPI5 (قارئ الترجمة/الإعلانات) على نفس جهاز
الصوت يسبّب تقطيعاً في صوت الفيلم الذي يعمل عبر PortAudio؟

- يشغّل الفيلم بالمحرّك الحقيقي على الجهاز الافتراضي
- من خيط منفصل ينطق عبر pyttsx3 (SAPI5) عبارة كل ثانيتين
- يقيس: فجوات استدعاء الجهاز (late) وفراغ المخزن (underruns) أثناء النطق
"""
import os, sys, time, threading
sys.path.insert(0, r"C:\Users\eksa2\Amp player")
from ampplayer import av_engine

MOVIE = r"C:\Users\eksa2\Downloads\Video\Power_Ballad_2026_BluRay_-_[e.cimalight.co].mp4"

class ProbingEngine(av_engine.MediaEngine):
    def __init__(self):
        super().__init__()
        self.underruns = 0
        self.late = 0
        self.last_t = None
        self.gaps = []
    def _pa_callback(self, outdata, frames, time_info, status):
        now = time.perf_counter()
        if self.last_t is not None:
            gap = (now - self.last_t) * 1000.0
            self.gaps.append(gap)
            if gap > 60.0:
                self.late += 1
        self.last_t = now
        if self._audio_blocks.empty():
            self.underruns += 1
        return super()._pa_callback(outdata, frames, time_info, status)


def tts_loop(stop: threading.Event):
    """ينطق عبارة عربية كل ثانيتين عبر SAPI5 لمدة محددة."""
    import pyttsx3
    t0 = time.perf_counter()
    n = 0
    while time.perf_counter() - t0 < 40.0 and not stop.is_set():
        try:
            if n % 2 == 0:
                eng = pyttsx3.init()
                eng.setProperty("rate", 175)
                eng.say("واحد اثنان ثلاثة جملة اختبارية")
                eng.runAndWait()
                eng.stop()
        except Exception as exc:
            print("tts error:", exc)
        n += 1
        time.sleep(1.5)


def main():
    if not os.path.exists(MOVIE):
        print("movie not found"); return 1
    eng = ProbingEngine()
    ok, err = eng.initialize()
    eng.on_frame = lambda arr, w, h: None
    eng.on_error = lambda m: print("ENGINE ERROR:", m)
    ok, err = eng.open(MOVIE)
    if not ok:
        eng.close(); return 1
    stop = threading.Event()
    t = threading.Thread(target=tts_loop, args=(stop,), daemon=True)
    print("playing 40s while SAPI5 speaks every ~2s ...")
    t0 = time.perf_counter()
    eng.play()
    t.start()
    while time.perf_counter() - t0 < 40.0:
        time.sleep(2.0)
        print(f"  t={time.perf_counter()-t0:4.0f}s media={eng.get_time():6.1f}s "
              f"q={eng._audio_blocks.qsize():2d} late={eng.late} underruns={eng.underruns}")
    stop.set()
    eng.pause(); eng.close()
    gaps = eng.gaps
    n = len(gaps)
    print("--- summary ---")
    print(f"callbacks: {n}  late gaps(>60ms): {eng.late}  underruns: {eng.underruns}")
    if n >= 20:
        import statistics
        s = sorted(gaps)
        print(f"gap median={statistics.median(gaps):.1f}ms p95={s[int(n*0.95)]:.1f}ms "
              f"p99={s[int(n*0.99)]:.1f}ms max={max(gaps):.1f}ms")
    return 0

if __name__ == "__main__":
    sys.exit(main())