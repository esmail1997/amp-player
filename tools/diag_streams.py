# -*- coding: utf-8 -*-
"""فحص مسارات الفيلم: فيديو/صوت/ترجمة (مدمجة أم خارجية؟)"""
import sys
sys.path.insert(0, r"C:\Users\eksa2\Amp player")
import av

c = av.open(r"C:\Users\eksa2\Downloads\Video\Power_Ballad_2026_BluRay_-_[e.cimalight.co].mp4")
print("format:", c.format.name, "| duration:", c.duration / av.time_base if c.duration else None, "s")
for i, st in enumerate(c.streams):
    cc = st.codec_context
    lang = None
    try:
        lang = st.language
    except Exception:
        pass
    print(f"  stream {i}: type={st.type}  codec={cc.codec.name if cc and cc.codec else None}  lang={lang}")
print("attached pics:", [s.type for s in c.streams if s.type == "attached_pic"])
c.close()