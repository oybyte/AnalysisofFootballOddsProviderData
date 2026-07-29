import json, os, re, base64, datetime
import markdown as md

WS = r"C:\Users\lcz\WorkBuddy\2026-07-27-09-58-26"
TMP = r"C:\Users\lcz\AppData\Local\Temp"
p = json.load(open(os.path.join(TMP, "parsed.json"), encoding="utf-8"))
turns = p["turns"]; uniq = p["uniq"]
si = json.load(open(os.path.join(TMP, "share.json"), encoding="utf-8"))["data"]["share_info"]

# ---------- 1. 应用上一步已确认的 8 条用户长文删除（原始 1-based 轮次） ----------
DEL_USER = {8, 10, 12, 14, 18, 20, 22, 24}
del_idx = {r - 1 for r in DEL_USER}
post = [t for i, t in enumerate(turns) if i not in del_idx]

# ---------- 2. 删除「计数元评论」整段（内容 "我们梳理一下你发送"） ----------
for i, t in enumerate(post):
    if "我们梳理一下你发送" in (t["text"] or ""):
        print("删除整段（计数元评论）-> kept#", i + 1)
        del post[i]
        break

# ---------- 3. 删除 R15 第三节（从 "## 三、整套系列学习脉络汇总" 起） ----------
for t in post:
    if "整套系列学习脉络汇总" in (t["text"] or ""):
        txt = t["text"]
        cut = txt.find("## 三、整套系列学习脉络汇总")
        if cut < 0:
            cut = txt.find("三、整套系列学习脉络汇总")
        if cut >= 0:
            t["text"] = txt[:cut].rstrip()
            print("切割 R15 第三节完成")
        break

# ---------- 4. 文本清洗：删除提议/客套/元评论 + 第一人称化（仅豆包轮次） ----------
PROPOSAL = re.compile(r"我可以把.{0,30}(合并|整理|生成|梳理|提炼|汇总|整合|更新|做成|压缩)")
OFFER = re.compile(r"^如果你(需要|想要|想|打算).{0,15}?我(可以|把|同步|能)")
LITERAL_DROP = [
    "如果你需要，我可以把", "如果你需要我可以把", "我可以把这",
    "合并整理成一份连贯学习笔记", "连贯学习笔记", "学习手册精简版",
    "生成一份完整盘口学习手册", "希望对你有帮助", "祝你好运", "祝运",
    "有疑问随时", "欢迎继续交流", "如果还有其他问题", "有不清楚的地方",
]

def is_drop_line(s):
    if OFFER.match(s):
        return True
    if PROPOSAL.search(s):
        return True
    if any(k in s for k in LITERAL_DROP):
        return True
    if s.startswith("好的，") and len(s) < 60:
        return True
    return False

BULLET = re.compile(r"^(方案\d+[.、:]?|[1-9]\d*[.、)】]|[-*]\s)")

def clean_bot(text):
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if is_drop_line(s):
            i += 1
            # 连同其后连续的方案/列表项一并删除
            while i < n:
                ns = lines[i].strip()
                if ns == "":
                    break
                if BULLET.match(ns) or ns in ("：", ":"):
                    i += 1
                    continue
                break
            continue
        out.append(lines[i])
        i += 1
    text = "\n".join(out)
    # 内联元评论去除
    text = text.replace("你原文中", "").replace("你原文里", "").replace("你文中", "")
    text = re.sub(r"你原来的文稿", "", text)
    text = re.sub(r"你的原稿", "", text)
    # 第一人称化（去除助手指向用户的措辞）
    text = text.replace("帮你更正", "更正").replace("帮你梳理", "梳理").replace("帮你整理", "整理")
    text = text.replace("上面那段你", "上面那段").replace("上面你", "上面")
    text = text.replace("我为你", "我").replace("为你梳理", "梳理").replace("为你整理", "整理").replace("为你更正", "更正")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

for t in post:
    role = t.get("role", "")
    if "豆包" in role and t["text"]:
        t["text"] = clean_bot(t["text"])
        t["role"] = "主讲/作者"   # 改标签
    elif "用户" in role:
        t["role"] = "👤 用户"

# ---------- 5. 重新顺序编号 ----------
post = [t for t in post if (t["text"] or "").strip() or t["imgs"]]
n_user = sum(1 for t in post if "用户" in t.get("role", ""))
n_bot = sum(1 for t in post if "主讲" in t.get("role", ""))
n_img_turns = sum(1 for t in post if t["imgs"])
print(f"重写后 总轮数={len(post)}  用户={n_user}  主讲/作者={n_bot}  含图轮次={n_img_turns}  图片数={len(uniq)}")

# ---------- 头部信息 ----------
title = si.get("share_name", "豆包分享对话")
author = si.get("user", {}).get("nick_name", "未知")
bot = si.get("bot", {}).get("name", "豆包")
def fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""
st = fmt(int(si.get("share_time", 0)) / 1000) if si.get("share_time") else ""

def header_lines():
    L = []
    L.append(f"# {title}（主讲整理版）\n")
    L.append("> **来源**：豆包分享帖  ")
    L.append(f"> **分享者**：{author}  ｜  **原始对话对象**：{bot}（内容已整理为主讲第一人称口径）  ")
    L.append(f"> **消息数**：{len(post)} 轮（用户 {n_user} / 主讲·作者 {n_bot}）；含图片 {n_img_turns} 轮 / 共 {len(uniq)} 张，已本地化  ")
    if st:
        L.append(f"> **分享时间**：{st}  ")
    L.append("> **原帖**：https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF  ")
    L.append("")
    L.append("> ⚠️ 内容为足球盘口（亚盘/澳盘）数据解读科普，原帖已注明网络购彩属违法行为，本文仅作赛事数据参考，不构成任何投注建议。\n")
    L.append("---\n")
    L.append("## 对话内容（整理版）\n")
    return L

# ===== A. 纯文本 MD =====
A = header_lines()
for idx, t in enumerate(post, 1):
    A.append(f"### {t['role']}（第 {idx} 轮）")
    A.append("")
    if (t["text"] or "").strip():
        A.append(t["text"].strip())
        A.append("")
    for u in t["imgs"]:
        A.append("")  # 纯文本版不嵌图
    A.append("---\n")
open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读.md"), "w", encoding="utf-8").write("\n".join(A))
print("A 纯文本 md 完成")

# ===== B. 图文 MD（相对路径 images/） =====
B = header_lines()
for idx, t in enumerate(post, 1):
    B.append(f"### {t['role']}（第 {idx} 轮）")
    B.append("")
    if (t["text"] or "").strip():
        B.append(t["text"].strip())
        B.append("")
    for u in t["imgs"]:
        rel, sz = uniq.get(u, (None, 0))
        if rel:
            B.append(f"![图片]({rel})")
            B.append("")
    B.append("---\n")
open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_图文版.md"), "w", encoding="utf-8").write("\n".join(B))
print("B 图文 md 完成")

# ===== C. 单文件 HTML（图片 base64 内联） =====
def b64(u):
    rel, sz = uniq.get(u, (None, 0))
    if not rel:
        return None
    fp = os.path.join(WS, rel)
    ext = rel.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else "image/jpeg" if ext in ("jpg", "jpeg") else "image/webp"
    with open(fp, "rb") as f:
        data = f.read()
    return "data:" + mime + ";base64," + base64.b64encode(data).decode()

body = []
body.append('<div class="meta"><b>来源</b>：豆包分享帖<br><b>分享者</b>：' + author +
            ' ｜ <b>原始对话对象</b>：' + bot + '（内容已整理为主讲第一人称口径）<br><b>消息数</b>：'
            + str(len(post)) + ' 轮（用户 ' + str(n_user) + ' / 主讲·作者 ' + str(n_bot) +
            '）；含图片 ' + str(n_img_turns) + ' 轮 / 共 ' + str(len(uniq)) + ' 张，已内联<br>' +
            ('<b>分享时间</b>：' + st + '<br>' if st else '') +
            '<b>原帖</b>：<a href="https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF">https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF</a></div>')
body.append('<div class="warn">⚠️ 内容为足球盘口（亚盘/澳盘）数据解读科普，原帖已注明网络购彩属违法行为，本文仅作赛事数据参考，不构成任何投注建议。</div>')
body.append("<hr>")
body.append("<h2>对话内容（整理版）</h2>")

for idx, t in enumerate(post, 1):
    role = t["role"]
    cls = "user" if "用户" in role else "author"
    body.append('<div class="turn ' + cls + '"><div class="role">' + role + "（第 " + str(idx) + " 轮）</div>")
    if (t["text"] or "").strip():
        html = md.markdown(t["text"].strip(), extensions=["tables", "fenced_code", "nl2br"])
        body.append('<div class="text">' + html + "</div>")
    for u in t["imgs"]:
        uri = b64(u)
        if uri:
            body.append('<img class="pic" src="' + uri + '" alt="图片' + str(idx) + '">')
    body.append("</div><hr>")

CSS = """:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f5f6f8;color:#1f2329;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.75;font-size:16px}
.wrap{max-width:880px;margin:0 auto;padding:32px 20px 80px}
.meta{background:#fff;border:1px solid #e6e8eb;border-radius:10px;padding:16px 18px;font-size:14px;color:#4b5563}
.warn{background:#fff7e6;border:1px solid #ffe1a8;color:#8a5a00;border-radius:10px;padding:12px 16px;margin-top:14px;font-size:14px}
hr{border:none;border-top:1px solid #e6e8eb;margin:22px 0}
h2{font-size:20px;margin:8px 0 18px}
.turn{background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:18px 20px;margin-bottom:16px}
.turn.author{border-left:4px solid #3370ff}
.turn.user{border-left:4px solid #34c759}
.role{font-weight:700;font-size:14px;color:#6b7280;margin-bottom:10px}
.text img{max-width:100%}
.pic{display:block;max-width:100%;height:auto;margin:12px 0;border:1px solid #e6e8eb;border-radius:8px}
.text table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
.text th,.text td{border:1px solid #e0e3e8;padding:8px 10px;text-align:left}
.text th{background:#f2f4f7;font-weight:600}
.text code{background:#f2f4f7;padding:2px 6px;border-radius:4px;font-size:13px}
.text pre{background:#f2f4f7;padding:12px;border-radius:8px;overflow:auto}
.text blockquote{margin:12px 0;padding:8px 14px;border-left:3px solid #d0d5dd;color:#57606a;background:#fafbfc}
a{color:#3370ff}"""

html = ('<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>'
        + title + '（主讲整理版·单文件）</title>\n<style>' + CSS + '</style>\n</head>\n<body>\n'
        '<div class="wrap">\n<h1>' + title + '（主讲整理版）</h1>\n' + "".join(body)
        + '\n</div>\n</body>\n</html>')

path_html = os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_单文件.html")
open(path_html, "w", encoding="utf-8").write(html)
print("C 单文件 html 完成, size MB:", round(os.path.getsize(path_html) / 1024 / 1024, 2))
