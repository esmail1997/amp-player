# -*- coding: utf-8 -*-
"""يتحقّق أن كل مفتاح i18n مستخدم في الكود موجود في اللغتين."""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ampplayer import i18n  # noqa: E402

PATTERNS = [
    re.compile(r"\btr\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\.tr\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\btr\(\s*f[\"']([^\"'{]+?)[\"']"),
]

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ampplayer")
KEYS: set[str] = set()

for dirpath, _dirs, files in os.walk(ROOT):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(dirpath, fn)
        text = open(path, encoding="utf-8").read()
        for pat in PATTERNS:
            for m in pat.finditer(text):
                KEYS.add(m.group(1))

# مفاتيح ديناميكية: subtitle_manager.LABEL_KEY
from ampplayer import subtitle_manager  # noqa: E402
KEYS.update(subtitle_manager.LABEL_KEY.values())

missing = []
for k in sorted(KEYS):
    if k.endswith("."):
        continue  # بادئة ديناميكية مثل "shortcuts." + group_key
    if k not in i18n._STRINGS:
        missing.append(k)

print(f"referenced keys: {len(KEYS)}")
print(f"defined keys   : {len(i18n._STRINGS)}")
if missing:
    print(f"MISSING ({len(missing)}):")
    for k in missing:
        print("  -", k)
else:
    print("OK: every referenced key is defined")

# empty translations?
empty = [k for k, (a, e) in i18n._STRINGS.items() if not a or not e]
if empty:
    print(f"EMPTY translations ({len(empty)}): {empty[:20]}")

sys.exit(1 if missing else 0)
