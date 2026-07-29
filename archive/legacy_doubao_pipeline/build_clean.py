import json, os, base64, datetime
import markdown as md

TMP = r"C:\Users\lcz\AppData\Local\Temp"
WS  = r"C:\Users\lcz\WorkBuddy\2026-07-27-09-58-26"

p = json.load(open(os.path.join(TMP, "parsed.json"), encoding="utf-8"))
turns = p["turns"]; uniq = p["uniq"]
si = json.load(open(os.path.join(TMP, "share.json"), encoding="utf-8"))["data"]["share_info"]

# 用户指定的待删除轮次（1-based）
DEL = {8, 10, 12, 14, 18, 20, 22, 24}
del_idx = {r - 1 for r in DEL}

# 记录被删轮次的文本片段，用于事后校验
deleted_snippets = [(i + 1, (turns[i]["text"] or "")[:50]) for i in sorted(del_idx) if i < len(turns)]

kept = [t for i, t in enumerate(turns) if i not in del_idx]

def fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""

title = si.get("share_name", "豆包分享对话")
author = si.get("user", {}).get("nick_name", "未知")
bot = si.get("bot", {}).get("name", "豆包")
st = fmt(int(si.get("share_time", 0)) / 1000) if si.get("share_time") else ""

n_user = sum(1 for t in kept if "用户" in t["role"])
n_bot  = sum(1 for t in kept if "豆包" in t["role"])
nimg_turns = sum(1 for t in kept if t["imgs"])
img_urls = set()
for t in kept:
    for u in t["imgs"]:
        img_urls.add(u)
img_count = len(img_urls)

meta_md = (
    f"> **来源**：豆包分享帖  \n"
    f"> **分享者**：{author}  ｜  **对话对象**：{bot}  \n"
    f"> **消息数**：{len(kept)}（用户 {n_user} / 豆包 {n_bot}；原 112 轮中已移除 8 条用户原始长文，仅保留豆包梳理纠正版）  \n"
    + (f"> **分享时间**：{st}  \n" if st else "")
    + "> **原帖**：https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF  \n"
)
disclaimer = "> ⚠️ 内容为足球盘口（亚盘/澳盘）数据解读科普，原帖已注明网络购彩属违法行为，本文仅作赛事数据参考，不构成任何投注建议。\n"

# ---------- 1) 纯文本 Markdown（无图片） ----------
L = [f"# {title}\n", meta_md, "", disclaimer, "---\n", "## 对话内容\n"]
for idx, t in enumerate(kept, 1):
    L.append(f"### {t['role']}（第 {idx} 轮）")
    L.append("")
    if t["text"].strip():
        L.append(t["text"].strip())
        L.append("")
    L.append("---\n")
open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读.md"), "w", encoding="utf-8").write("\n".join(L))

# ---------- 2) 图文 Markdown（相对路径 images/） ----------
L2 = [f"# {title}\n", meta_md, "", disclaimer, "---\n", "## 对话内容\n"]
for idx, t in enumerate(kept, 1):
    L2.append(f"### {t['role']}（第 {idx} 轮）")
    L2.append("")
    if t["text"].strip():
        L2.append(t["text"].strip())
        L2.append("")
    for u in t["imgs"]:
        rel, sz = uniq.get(u, (None, 0))
        if rel:
            L2.append(f"![图片]({rel})")
            L2.append("")
    L2.append("---\n")
open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_图文版.md"), "w", encoding="utf-8").write("\n".join(L2))

# ---------- 3) 单文件 HTML（图片 base64 内联） ----------
def b64(u):
    rel, sz = uniq.get(u, (None, 0))
    if not rel:
        return None
    fp = os.path.join(WS, rel)
    ext = rel.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else "image/jpeg" if ext in ("jpg", "jpeg") else "image/webp"
    with open(fp, "rb") as f:
        data = f.read()
    return f"data:{mime};base64," + base64.b64encode(data).decode()

body = []
body.append(
    f'<div class="meta"><b>来源</b>：豆包分享帖<br><b>分享者</b>：{author} ｜ <b>对话对象</b>：{bot}<br>'
    f'<b>消息数</b>：{len(kept)}（用户 {n_user} / 豆包 {n_bot}；原 112 轮中已移除 8 条用户原始长文，仅保留豆包梳理纠正版）<br>'
    + (f'<b>分享时间</b>：{st}<br>' if st else "")
    + '<b>原帖</b>：<a href="https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF">https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF</a></div>'
)
body.append('<div class="warn">⚠️ 内容为足球盘口（亚盘/澳盘）数据解读科普，原帖已注明网络购彩属违法行为，本文仅作赛事数据参考，不构成任何投注建议。</div>')
body.append("<hr>")
body.append("<h2>对话内容</h2>")

for idx, t in enumerate(kept, 1):
    role = t["role"]
    cls = "user" if "用户" in role else "bot"
    body.append(f'<div class="turn {cls}"><div class="role">{role}（第 {idx} 轮）</div>')
    if t["text"].strip():
        html = md.markdown(t["text"].strip(), extensions=["tables", "fenced_code", "nl2br"])
        body.append(f'<div class="text">{html}</div>')
    for u in t["imgs"]:
        uri = b64(u)
        if uri:
            body.append(f'<img class="pic" src="{uri}" alt="图片{idx}">')
    body.append("</div><hr>")

CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f5f6f8;color:#1f2329;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.75;font-size:16px}
.wrap{max-width:880px;margin:0 auto;padding:32px 20px 80px}
.meta{background:#fff;border:1px solid #e6e8eb;border-radius:10px;padding:16px 18px;font-size:14px;color:#4b5563}
.warn{background:#fff7e6;border:1px solid #ffe1a8;color:#8a5a00;border-radius:10px;padding:12px 16px;margin-top:14px;font-size:14px}
hr{border:none;border-top:1px solid #e6e8eb;margin:22px 0}
h2{font-size:20px;margin:8px 0 18px}
.turn{background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:18px 20px;margin-bottom:16px}
.turn.bot{border-left:4px solid #3370ff}
.turn.user{border-left:4px solid #34c759}
.role{font-weight:700;font-size:14px;color:#6b7280;margin-bottom:10px}
.text img{max-width:100%}
.pic{display:block;max-width:100%;height:auto;margin:12px 0;border:1px solid #e6e8eb;border-radius:8px;cursor:zoom-in}
.text table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
.text th,.text td{border:1px solid #e0e3e8;padding:8px 10px;text-align:left}
.text th{background:#f2f4f7;font-weight:600}
.text code{background:#f2f4f7;padding:2px 6px;border-radius:4px;font-size:13px}
.text pre{background:#f2f4f7;padding:12px;border-radius:8px;overflow:auto}
.text blockquote{margin:12px 0;padding:8px 14px;border-left:3px solid #d0d5dd;color:#57606a;background:#fafbfc}
a{color:#3370ff}
"""

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}（图文·单文件·精简版）</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<h1>{title}</h1>
{''.join(body)}
</div>
</body>
</html>"""

open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_单文件.html"), "w", encoding="utf-8").write(html)

print("done")
print("保留轮数:", len(kept), " 用户:", n_user, " 豆包:", n_bot)
print("含图轮次:", nimg_turns, " 图片总数:", img_count)
print("被删轮次及片段:")
for r, snip in deleted_snippets:
    print(f"  R{r}: {snip!r}")
