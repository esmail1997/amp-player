# -*- coding: utf-8 -*-
"""تشخيص خامس: هل WASAPI (منفذ ويندوز الحديث) يبقى مستقراً تحت نطق SAPI5؟
- يشغّل الفيلم على الجهاز 8 (Speakers عبر WASAPI, 48000Hz)
- نطق SAPI5 كل ثانيتين كالسابق
- يقيس الفجوات والتقطيع
"""
import os, sys, time, threading, statistics
sys.path.insert(0, r"C:\Users\eksa2\Amp player")
from ampplayer import av_engine

MOVIE = r"C:\Users\eksa2\Downloads\Video\Power_Ballad_2026_BluRay_-_[e.cimalight.co].mp4"
DEVICE = 8  # Speakers - WASAPI

class ProbingEngine(av_engine.MediaEngine):
    def __init__(self):
        super().__init__()
        self.underruns = 0; self.late = 0
        self.last_t = None; self.gaps = []
    def _pa_callback(self, outdata, frames, time_info, status):
        now = time.perf_counter()
        if self.last_t is not None:
            g = (now - self.last_t) * 1000.0
            self.gaps.append(g)
            if g > 60.0:
                self.late += 1
        self.last_t = now
        if self._audio_blocks.empty():
            self.underruns += 1
        return super()._pa_callback(outdata, frames, time_info, status)


def tts_loop(stop):
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
        eng.close(); print("open failed:", err); return 1
    eng._device_index = DEVICE
    # افتح الصوت على WASAPI فوراً بعد بدء التشغيل (شرط _playing)
    t0 = time.perf_counter()
    eng.play()
    time.sleep(1.0)
    eng._reopen_audio_for_rate()
    if eng._out is None:
        print("WASAPI open FAILED:", eng._sd_error)
        eng.close(); return 2
    print("device:", DEVICE, "opened on WASAPI, out_rate:", eng._out_rate)
    stop = threading.Event()
    t = threading.Thread(target=tts_loop, args=(stop,), daemon=True)
    t.start()
    while time.perf_counter() - t0 < 40.0:
        time.sleep(2.0)
        print(f"  t={time.perf_counter()-t0:4.0f}s media={eng.get_time():6.1f}s "
              f"q={eng._audio_blocks.qsize():2d} late={eng.late} underruns={eng.underruns}")
    stop.set(); eng.pause(); eng.close()
    gaps = eng.gaps; n = len(gaps)
    print("--- summary ---")
    print(f"callbacks={n}  late(>60ms)={eng.late}  underruns={eng.underruns}")
    if n >= 20:
        s = sorted(gaps)
        print(f"median={statistics.median(gaps):.1f}ms p95={s[int(n*0.95)]:.1f}ms "
              f"p99={s[int(n*0.99)]:.1f}ms max={max(gaps):.1f}ms")
    return 0

if __name__ == "__main__":
    sys.exit(main())