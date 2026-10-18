"""فحص محرك mpv (python-mpv) كاملاً: التحميل، الرسم، الصوت، الزمن.

التشغيل (من مجلد المشروع):
    .venv\\Scripts\\python.exe -X utf8 tools\\diag_mpv_engine.py <فيديو>
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ampplayer import config
from ampplayer.mpv_engine import MpvEngine, mpv_version
from ampplayer import nvda_bridge


def main() -> int:
    sys.stdout.write(f"mpv version: {mpv_version()!r}\n")
    if len(sys.argv) < 2:
        sys.stdout.write("usage: diag_mpv_engine.py <video.mp4>\n")
        return 2
    path = sys.argv[1]

    eng = MpvEngine(config.Config())
    sys.stdout.write(f"available: {eng.available}\n")
    if not eng.available:
        sys.stdout.write("FAIL mpv unavailable\n")
        return 1

    frames: list[tuple[int, int]] = []
    states: list[str] = []

    def on_frame(arr, w, h):
        frames.append((w, h, int(arr.shape[0]), int(arr.shape[1])))
        if len(frames) <= 3:
            sys.stdout.write(f"frame {arr.shape} strides={arr.strides} dtype={arr.dtype}\n")

    def on_state(s):
        states.append(s)
        sys.stdout.write(f"[state] {s}\n")

    eng.on_frame = on_frame
    eng.on_state = on_state

    ok, err = eng.initialize()
    sys.stdout.write(f"initialize: {ok} {err}\n")
    if not ok:
        return 1

    ok, err = eng.open(path)
    sys.stdout.write(f"open: {ok} {err}\n")
    if not ok:
        eng.close()
        return 1

    tracks = eng.get_tracks("audio") + eng.get_tracks("subtitle") + eng.get_tracks("video")
    sys.stdout.write(f"tracks: {len(tracks)}  dur={eng.get_duration():.1f}s "
                     f"cues={len(eng.cues)}\n")

    eng.play()
    time.sleep(3.0)
    sys.stdout.write(f"time after 3s: {eng.get_time():.2f}s\n")
    sys.stdout.write(f"frames received: {len(frames)}\n")
    sys.stdout.write(f"playing={eng.is_playing()} paused={eng.is_paused()}\n")

    eng.pause()
    t1 = eng.get_time()
    time.sleep(0.4)
    sys.stdout.write(f"paused: time stable {t1:.2f} -> {eng.get_time():.2f}\n")

    eng.play()
    eng.set_time(10.0)
    time.sleep(0.6)
    sys.stdout.write(f"after seek: {eng.get_time():.2f}s\n")

    eng.set_volume(60)
    eng.set_duck(True)
    time.sleep(0.3)
    eng.set_duck(False)

    sys.stdout.write(f"devices: {eng.list_output_devices()[:4]}\n")
    sys.stdout.write(f"diag: {eng.audio_diagnostics()}\n")
    sys.stdout.write(f"kind: {eng.engine_version}\n")

    ok_frames = len(frames) >= 5
    ok_play = eng.get_time() > 1.0
    sys.stdout.write(f"RESULT frames={'PASS' if ok_frames else 'FAIL'} "
                     f"playback={'PASS' if ok_play else 'FAIL'}\n")

    eng.close()
    sys.stdout.write(f"NVDA bridge: dll={nvda_bridge.dll_available()} "
                     f"running={nvda_bridge.is_running()} {nvda_bridge.engine_summary()}\n")
    return 0 if (ok_frames and ok_play) else 1


if __name__ == "__main__":
    raise SystemExit(main())