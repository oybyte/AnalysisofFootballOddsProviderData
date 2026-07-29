import json, os, base64, datetime
import markdown as md

WS = r"C:\Users\lcz\WorkBuddy\2026-07-27-09-58-26"
TMP = r"C:\Users\lcz\AppData\Local\Temp"
p = json.load(open(os.path.join(TMP, "parsed.json"), encoding="utf-8"))
turns = p["turns"]; uniq = p["uniq"]
si = json.load(open(os.path.join(TMP, "share.json"), encoding="utf-8"))["data"]["share_info"]

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

def fmt(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""

title = si.get("share_name", "豆包分享对话")
author = si.get("user", {}).get("nick_name", "未知")
bot = si.get("bot", {}).get("name", "豆包")
st = fmt(int(si.get("share_time", 0)) / 1000) if si.get("share_time") else ""
nimg = sum(1 for t in turns if t["imgs"])

body = []
body.append('<div class="meta"><b>来源</b>：豆包分享帖<br><b>分享者</b>：' + author +
            ' ｜ <b>对话对象</b>：' + bot + '<br><b>消息数</b>：' + str(len(turns)) +
            '（含图片 ' + str(nimg) + ' 轮 / 共 ' + str(len(uniq)) + ' 张，已内联）<br>' +
            ('<b>分享时间</b>：' + st + '<br>' if st else '') +
            '<b>原帖</b>：<a href="https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF">https://www.doubao.com/thread/xm2FuZwnEq2rkjVQF</a></div>')
body.append('<div class="warn">⚠️ 内容为足球盘口（亚盘/澳盘）数据解读科普，原帖已注明网络购彩属违法行为，本文仅作赛事数据参考，不构成任何投注建议。</div>')
body.append("<hr>")
body.append("<h2>对话内容</h2>")

for idx, t in enumerate(turns, 1):
    role = t["role"]
    cls = "user" if "用户" in role else "bot"
    body.append('<div class="turn ' + cls + '"><div class="role">' + role + "（第 " + str(idx) + " 轮）</div>")
    if t["text"].strip():
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
.turn.bot{border-left:4px solid #3370ff}
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
        + title + '（图文·单文件）</title>\n<style>' + CSS + '</style>\n</head>\n<body>\n'
        '<div class="wrap">\n<h1>' + title + '</h1>\n' + "".join(body) + '\n</div>\n</body>\n</html>')

path = os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_单文件.html")
open(path, "w", encoding="utf-8").write(html)
print("written:", path)
print("size MB:", round(os.path.getsize(path) / 1024 / 1024, 2))
