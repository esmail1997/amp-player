# -*- coding: utf-8 -*-
"""تشخيص ثالث: قياس جودة جهاز الصوت نفسه.
يقيس لمدة دقيقتين:
- طول الفترات بين استدعاءات PortAudio (المفروض ~21ms)
- عدد مرات كتابة الصمت بسبب فراغ المخزن (underrun)
- أقصى تأخّر استدعاء = مؤشر مباشر على تقطيع من الجهاز/النظام
"""
import os, sys, time, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ampplayer import av_engine

MOVIE = r"C:\Users\eksa2\Downloads\Video\Power_Ballad_2026_BluRay_-_[e.cimalight.co].mp4"

class ProbingEngine(av_engine.MediaEngine):
    def __init__(self):
        super().__init__()
        self.underruns = 0
        self.stalls = 0          # استدعاء تأخّر بين فترتين > 60ms
        self.last_t = None
        self.gaps = []

    def _pa_callback(self, outdata, frames, time_info, status):
        now = time.perf_counter()
        if self.last_t is not None:
            gap = (now - self.last_t) * 1000.0
            self.gaps.append(gap)
            if gap > 60.0:
                self.stalls += 1
        self.last_t = now
        if self._audio_blocks.empty():
            self.underruns += 1
        return super()._pa_callback(outdata, frames, time_info, status)


def main():
    if not os.path.exists(MOVIE):
        print("movie not found"); return 1
    eng = ProbingEngine()
    ok, err = eng.initialize()
    print("init:", ok, err)
    eng.on_frame = lambda arr, w, h: None
    eng.on_error = lambda m: print("ENGINE ERROR:", m)
    ok, err = eng.open(MOVIE)
    print("open:", ok, err, "| duration:", round(eng.get_duration(), 1))
    if not ok:
        eng.close(); return 1
    print("out_rate:", eng._out_rate, "| device idx:", eng._device_index)
    print("playing for 120 seconds ... (be patient)")
    t0 = time.perf_counter()
    eng.play()
    min_q, max_q = 10**9, -1
    while time.perf_counter() - t0 < 120.0:
        time.sleep(2.0)
        q = eng._audio_blocks.qsize()
        min_q, max_q = min(min_q, q), max(max_q, q)
        print(f"  t={time.perf_counter()-t0:5.0f}s media={eng.get_time():8.1f}s qsize={q:2d}")
    eng.pause()
    eng.close()
    gaps = eng.gaps
    n = len(gaps)
    median = statistics.median(gaps) if n else 0
    p95 = sorted(gaps)[int(n * 0.95)] if n >= 20 else 0
    p99 = sorted(gaps)[int(n * 0.99)] if n >= 100 else 0
    print("--- summary ---")
    print(f"callbacks: {n}  (expected interval ~21.3ms)")
    print(f"underruns: {eng.underruns}   stalls(>60ms gap): {eng.stalls}")
    print(f"gap median={median:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms  max={max(gaps):.1f}ms")
    print(f"audio qsize min={min_q} max={max_q}  (32 = full)")
    return 0

if __name__ == "__main__":
    sys.exit(main())