# -*- coding: utf-8 -*-
import sounddevice as sd

for i, ha in enumerate(sd.query_hostapis()):
    print(f"hostapi {i}: {ha['name']}  default_out={ha['default_output_device']}")

for dev in range(0, 12):
    try:
        info = sd.query_devices(dev)
        if info.get("max_output_channels", 0) <= 0:
            continue
        tag = ""
        try:
            s = sd.OutputStream(samplerate=48000, channels=2, dtype="float32",
                                blocksize=1024, device=dev, callback=lambda *a: None)
            s.start(); s.stop(); s.close()
            tag = "OK"
        except Exception as e:
            tag = "FAIL: " + str(e)
        print(f"dev {dev}: {info['name']}  -> {tag}")
    except Exception as e:
        print(f"dev {dev}: query fail {e}")