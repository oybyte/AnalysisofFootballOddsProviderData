# -*- coding: utf-8 -*-
"""抓取新分享链接，解析消息，与旧 parsed.json 合并图片，下载新增图片。"""
import json, os, re, subprocess

SHARE_ID = "xjMPFMvYKY241yeEI"
TMP = r"C:\Users\lcz\AppData\Local\Temp"
WS = r"C:\Users\lcz\WorkBuddy\2026-07-27-09-58-26"
IMG_DIR = os.path.join(WS, "images")

def fetch():
    cmd = [
        "curl", "-s", "-X", "POST",
        "https://www.doubao.com/im/message/share/get",
        "-H", "Content-Type: application/json",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "-H", "Referer: https://www.doubao.com/",
        "-d", json.dumps({"share_id": SHARE_ID, "need_bot_info": True}),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("curl failed: " + r.stderr)
    raw = r.stdout
    open(os.path.join(TMP, "newshare.json"), "w", encoding="utf-8").write(raw)
    return json.loads(raw)

def parse_messages(ml):
    turns = []
    for m in ml:
        ut = m.get("user_type")
        if ut == 1:
            role = "👤 用户"
        elif ut == 2:
            role = "豆包"
        else:
            role = f"role{ut}"
        content = m.get("content", "")
        try:
            cj = json.loads(content) if isinstance(content, str) else (content or {})
        except Exception:
            cj = {}
        text = cj.get("text", "") if isinstance(cj, dict) else ""
        imgs = []
        if isinstance(cj, dict):
            for e in cj.get("entities", []):
                if e.get("entity_type") == 2:
                    ic = e.get("entity_content", {})
                    img = ic.get("image", {}) or {}
                    url = (img.get("image_ori") or {}).get("url") or (img.get("image_thumb") or {}).get("url")
                    if url:
                        imgs.append(url)
        # 兜底：content 文本里直接包含图片 url
        if not imgs:
            for u in re.findall(r'https?://[^\s",}\\]+byteimg\.com[^\s",}\\]+', str(content)):
                if "image" in u:
                    imgs.append(u)
        turns.append({"role": role, "text": text or "", "imgs": imgs})
    return turns

def ext_of(url):
    seg = url.split("?")[0].lower()
    if seg.endswith(".png"):
        return "png"
    if seg.endswith(".jpeg") or seg.endswith(".jpg"):
        return "jpeg"
    if seg.endswith(".webp"):
        return "webp"
    if "image.png" in url:
        return "png"
    if "image.jpeg" in url or "image.jpg" in url:
        return "jpeg"
    if "image.webp" in url:
        return "webp"
    return "png"

def main():
    s = fetch()
    si = s.get("data", {}).get("share_info", {})
    ml = s.get("data", {}).get("message_snapshot", {}).get("message_list", [])
    print("share_name:", si.get("share_name"))
    print("share_time:", si.get("share_time"))
    print("message_list len:", len(ml))

    turns = parse_messages(ml)

    # 合并旧 uniq
    old = json.load(open(os.path.join(TMP, "parsed.json"), encoding="utf-8"))
    old_uniq = old["uniq"]
    uniq = {k: list(v) for k, v in old_uniq.items()}
    next_num = len(uniq) + 1  # 56
    new_img_urls = []
    for t in turns:
        for url in t["imgs"]:
            if url not in uniq:
                ext = ext_of(url)
                rel = f"images/img_{next_num:03d}.{ext}"
                uniq[url] = [rel, 0]
                new_img_urls.append((url, rel))
                next_num += 1

    print(f"总轮数={len(turns)}  旧uniq={len(old_uniq)}  新uniq={len(uniq)}  本次新增图片={len(new_img_urls)}")

    # 下载新增图片
    os.makedirs(IMG_DIR, exist_ok=True)
    downloaded = 0
    for url, rel in new_img_urls:
        fp = os.path.join(WS, rel)
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            continue
        try:
            r = subprocess.run(
                ["curl", "-s", "-L", url, "-o", fp,
                 "-H", "User-Agent: Mozilla/5.0",
                 "-H", "Referer: https://www.doubao.com/"],
                capture_output=True,
            )
            if os.path.exists(fp) and os.path.getsize(fp) > 0:
                sz = os.path.getsize(fp)
                uniq[url][1] = sz
                downloaded += 1
            else:
                print("  下载失败:", rel, url[:80])
        except Exception as e:
            print("  异常:", rel, e)
    print("实际下载新增图片:", downloaded)

    json.dump({"turns": turns, "uniq": uniq},
              open(os.path.join(TMP, "newparsed.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("已保存 newparsed.json, newshare.json")

    # 前缀一致性校验
    old_turns = old["turns"]
    n = min(len(old_turns), len(turns))
    mismatch = 0
    for i in range(n):
        a, b = old_turns[i], turns[i]
        if a.get("role") != b.get("role") or a.get("text", "") != b.get("text", "") or a.get("imgs") != b.get("imgs"):
            print(f"  前缀差异 @index {i} (1-based {i+1})")
            print("    old:", (a.get('text','') or '')[:60], "| imgs", len(a.get('imgs',[])))
            print("    new:", (b.get('text','') or '')[:60], "| imgs", len(b.get('imgs',[])))
            mismatch += 1
            if mismatch > 5:
                break
    print("前缀一致(前%d条) mismatch=%d" % (n, mismatch))
    print("新增消息数(末尾):", len(turns) - n)

if __name__ == "__main__":
    main()
