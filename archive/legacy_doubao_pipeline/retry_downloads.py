# -*- coding: utf-8 -*-
"""重试下载 newparsed.json 中本地缺失/空的文件。"""
import json, os, subprocess

TMP = r"C:\Users\lcz\AppData\Local\Temp"
WS = r"C:\Users\lcz\WorkBuddy\2026-07-27-09-58-26"

p = json.load(open(os.path.join(TMP, "newparsed.json"), encoding="utf-8"))
uniq = p["uniq"]
missing = []
for url, (rel, sz) in uniq.items():
    fp = os.path.join(WS, rel)
    if not os.path.exists(fp) or os.path.getsize(fp) == 0:
        missing.append((url, rel))

print("本地缺失图片数:", len(missing))
ok = 0
for url, rel in missing:
    fp = os.path.join(WS, rel)
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["curl", "-s", "-L", "--retry", "2", "--retry-delay", "1",
                 url, "-o", fp,
                 "-H", "User-Agent: Mozilla/5.0",
                 "-H", "Referer: https://www.doubao.com/"],
                capture_output=True, timeout=60,
            )
            if os.path.exists(fp) and os.path.getsize(fp) > 0:
                ok += 1
                uniq[url][1] = os.path.getsize(fp)
                break
        except Exception:
            pass
    else:
        print("  仍失败:", rel, url[:90])
# 回写 uniq 尺寸
json.dump(p, open(os.path.join(TMP, "newparsed.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("重试成功:", ok, "/", len(missing))
# 最终统计
still = [(u, r) for u, (r, s) in uniq.items() if not os.path.exists(os.path.join(WS, r)) or os.path.getsize(os.path.join(WS, r)) == 0]
print("最终仍缺失:", len(still))
for u, r in still:
    print("   ", r, u[:90])
