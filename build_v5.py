# -*- coding: utf-8 -*-
"""
build_v5.py — 在 build_v4.py 基础上:
  * 数据源改为新分享链接 xjMPFMvYKY241yeEI (newparsed.json / newshare.json)
    - 216 轮消息（旧 112 轮 + 新增 104 轮比赛分析）
    - 251 张图（合并旧 55 张 + 新增 196 张，其中 21 张第三方 CDN 403 无法下载）
  * 拓宽「服务提议句」识别：覆盖新比赛分析中的大量「如果你需要/想要…我可以整理成清单」变体
  * 支持子弹点形式 / 行内形式的提议句删除
  * 缺失图片优雅跳过（不生成裂图）
  * 原帖链接更新为新 share_id
"""
import json, os, re, base64, datetime
import markdown as md

WS = r"C:\Users\lcz\WorkBuddy\2026-07-27-09-58-26"
TMP = r"C:\Users\lcz\AppData\Local\Temp"
SHARE_ID = "xjMPFMvYKY241yeEI"
p = json.load(open(os.path.join(TMP, "newparsed.json"), encoding="utf-8"))
turns = p["turns"]; uniq = p["uniq"]
si = json.load(open(os.path.join(TMP, "newshare.json"), encoding="utf-8"))["data"]["share_info"]

# ============================================================
# 1. 删除 8 条用户长文（原始 1-based 轮次，与旧版一致）
# ============================================================
DEL_USER = {8, 10, 12, 14, 18, 20, 22, 24}
del_idx = {r - 1 for r in DEL_USER}
post = [t for i, t in enumerate(turns) if i not in del_idx]

# ============================================================
# 2. 删除「计数元评论」整段
# ============================================================
for i, t in enumerate(post):
    if "我们梳理一下你发送" in (t["text"] or ""):
        del post[i]
        break

# ============================================================
# 3. R15 切割：删目录部分，保留「完整标准分析流程」方法论
# ============================================================
for t in post:
    if "整套系列学习脉络汇总" in (t["text"] or ""):
        txt = t["text"]
        cut_dir = txt.find("## 三、整套系列学习脉络汇总")
        if cut_dir < 0:
            cut_dir = txt.find("三、整套系列学习脉络汇总")
        if cut_dir >= 0:
            method_start = txt.find("### 整合后的完整标准分析流程", cut_dir)
            if method_start < 0:
                method_start = txt.find("整合后的完整标准分析流程", cut_dir)
            if method_start >= 0:
                offer_start = txt.find("如果你需要", method_start)
                if offer_start < 0:
                    offer_start = txt.find("如果你需要，我可以", method_start)
                if offer_start < 0:
                    offer_start = len(txt)
                method_block = txt[method_start:offer_start].rstrip()
                method_block = method_block.replace("### 整合后的完整标准分析流程（全部课程融会贯通）",
                    "### 完整标准分析流程（全部课程融会贯通）")
                t["text"] = txt[:cut_dir].rstrip() + "\n\n" + method_block
            else:
                t["text"] = txt[:cut_dir].rstrip()
        break

# ============================================================
# 4. 综合文本清洗
# ============================================================
FAN_LINE = re.compile(
    r"(充电粉丝|感谢充电|充电排行|包月充电|每周充电|合买|抽奖|粉丝牌|"
    r"一键三连|点赞支持|点关注支持|制作不易|麻烦点赞|有余力可以(支持|充电)|"
    r"希望新粉丝不要私信|私信索要私单|付费咨询|私单|"
    r"觉得内容不错|分析制作不易|本期内容到此结束|欢迎一键三连|"
    r"感兴趣可以点关注|麻烦点赞支持)"
)
OPENING_LINE = re.compile(
    r"^(大家好[，,].*?(庞哥|盘哥|盘果|旁哥|盘口)教学|大家好[，,].*?国际比赛日|大家好[，,]这里是)"
)
META_LINE = re.compile(
    r"^(>|>⚠️|>前置)(.*?)(短视频博主|博主[「」]|口播文稿|口播稿|"
    r"UP主粉丝运营|粉丝充电合买|视频中粉丝私单|这份是.*?文稿|文本为.*?口播稿)"
)
ENDING_LINE = re.compile(
    r"^(觉得内容|制作不易|分析制作|本期内容|欢迎一键三连|感兴趣可以)"
)
PREVIEW_LINE = re.compile(
    r"^(后续教学预告|下期预告|预告下一期|下一期继续)"
)
BLOGGER_INTRO = re.compile(
    r"^(第一期基础入门教学可以去主页回看|今天次级联赛较多，不做赛事推送|前两期已经做成合集)"
)
META_COUNT_HEADER = re.compile(
    r"^(目前你累计收集完整|##\s*三、全套教学完整学习链路汇总|目前收集全部\d+期完整教学文稿)"
)

def is_fan_or_meta_line(s):
    stripped = s.strip()
    if not stripped:
        return False
    if FAN_LINE.search(stripped):
        return True
    if OPENING_LINE.match(stripped):
        return True
    if META_LINE.match(stripped):
        return True
    if ENDING_LINE.match(stripped):
        return True
    if PREVIEW_LINE.match(stripped):
        return True
    if BLOGGER_INTRO.match(stripped):
        return True
    if META_COUNT_HEADER.match(stripped):
        return True
    if re.search(r"发起活动|开启粉丝|动态公开推单|私信通知", stripped):
        return True
    if re.search(r"(服是清欢|年老的德国|c卧底|鬼鬼|热咖啡|S一九九四|长夜江鸣|早上记得|长岛波波|"
                 r"啥感觉也没有|铁血战士|德保罗|桑贝小哥|仓鼠物|歌坛小丑|卡卡罗特|"
                 r"扫地僧小迷|像阿姆一样|谢王keep|北明|天上掉下|Lowdream|丁文康)", stripped):
        return True
    return False

def replace_terms(text):
    text = text.replace("博主个人观点", "个人观点")
    text = text.replace("博主个人体系", "个人体系")
    text = text.replace("博主补充个人观点", "补充个人观点")
    text = text.replace("博主观点", "个人观点")
    text = text.replace("博主补充", "补充")
    text = text.replace("博主以英超", "以英超")
    text = text.replace("博主预告", "预告")
    text = text.replace("博主", "")
    text = text.replace("UP主思路", "思路")
    text = text.replace("UP主自述", "")
    text = text.replace("UP主粉丝运营活动", "")
    text = text.replace("UP主", "")
    text = text.replace("视频案例", "案例")
    text = text.replace("视频思路", "思路")
    text = text.replace("视频中", "文中")
    text = text.replace("后续视频", "后续")
    text = text.replace("视频提到", "文中提到")
    text = text.replace("视频所说", "所说")
    text = text.replace("视频两个案例", "两个案例")
    text = text.replace("视频结论", "结论")
    text = text.replace("视频", "")
    text = text.replace("口播文稿", "文稿")
    text = text.replace("口播稿", "文稿")
    text = text.replace("短视频", "")
    text = text.replace("庞哥", "")
    text = text.replace("盘哥", "")
    text = text.replace("盘果", "")
    text = text.replace("旁哥", "")
    text = text.replace("昨天动态预告，", "")
    text = text.replace("动态预告", "")
    text = re.sub(r"后续教学预告：欧赔专题，二选一内容：①各大欧洲公司特点；②欧赔解读方法，可以评论区投票。", "", text)
    text = re.sub(r"预告下一期继续讲解小众机构特点。整套学习完整路径：亚盘基础→变盘逻辑→阻诱分辨→欧赔机构风格→欧赔赔率解读。", "", text)
    text = re.sub(r"下期预告：如何判断反弹走势、捕捉冷门要素。", "", text)
    text = re.sub(r"下一期继续深入讲解冷门打出的识别特征，感谢各位，祝大家好运。", "", text)
    text = re.sub(r"第一期基础入门教学可以去主页回看。", "", text)
    text = re.sub(r"可以去主页回看。?", "", text)
    text = re.sub(r"今天次级联赛较多，不做赛事推送，带来亚盘教学第三期。?", "", text)
    text = re.sub(r"前两期已经做成合集，分别是亚盘入门、指数变化逻辑。?", "", text)
    text = re.sub(r"「」", "", text)
    text = re.sub(r"（）", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r" {2,}", " ", text)
    return text

# === 服务提议句（拓宽）===
OFFER = re.compile(
    r"^如果你(需要|想要|想|打算|习惯|愿意|后续|能|告诉我|继续|思路|只看|先做)"
    r".{0,45}?(我(可以|把|们|会|再|帮你)|可以帮你|整理成|做成|压缩成|汇总成|整合|"
    r"梳理成|对比成|生成|提炼|同步对比|跟踪|对照表|虚拟构造|构造)"
)
# 不以「如果你」开头、但本身是「我可以/想把…整理成清单」式服务提议
SELF_OFFER = re.compile(
    r"^(我(可以|想|们|会)|如果想).{0,60}?(整理成|做成|汇总成|整合|压缩成|生成|提炼|"
    r"梳理成|对比成|跟踪|对照表|虚拟构造|构造|把.{0,45}(整理|汇总|整合|对比|梳理|生成|更新|合并))"
)
LITERAL_DROP = [
    "如果你需要，我可以把", "如果你需要我可以把", "我可以把这",
    "合并整理成一份连贯学习笔记", "连贯学习笔记", "学习手册精简版",
    "生成一份完整盘口学习手册", "希望对你有帮助", "祝你好运", "祝运",
    "有疑问随时", "欢迎继续交流", "如果还有其他问题", "有不清楚的地方",
]
SERVICE_TAILS = [
    "如果你想要，我还可以继续扩充：增加【升盘诱下、浅盘升档、平手震荡】等更多模板，做成一套完整盘路智能体。",
    "如果你习惯，赛后我们可以把【升盘守盘 / 升盘退盘】做成两类标准模板方便以后快速识别。",
    "如果你后续把胜平负赔率截图发过来，可以完成欧亚交叉验证。",
    "如果你想要对比威廉/英特，你主动提一句，我再单独拿两家赔率做对比。",
    "如果你后续想启用威廉+英特交叉验证，只需要简单说明，我再叠加这一层维度。",
    "如果你继续深入，我们可以思考：",
    "如果你想对比学习：",
    "如果你想不通，我再展开解析。",
    "如果你打算继续延伸，我可以：",
    "如果你需要，我同步对比甘美奥那场，把两场当前最新状态整理成对比清单。",
    "如果你想，我可以虚拟构造一场完整“浅开低水诱上”时序案例，和赫根走势并排对照，观感会更直观。",
]

def is_offer_line(s):
    core = re.sub(r'^[-*]\s+', '', s).strip()  # 去掉子弹点前缀再判断
    if OFFER.match(s) or OFFER.match(core):
        return True
    if SELF_OFFER.match(s) or SELF_OFFER.match(core):
        return True
    # 删掉「可以思考一道思考题」后残留的悬空「如果你愿意，」等
    if re.match(r'^如果你(愿意|需要|想要|想|后续|能|告诉我|继续|思路|只看|先做)[，,。：:、]\s*$', core):
        return True
    if any(k in s for k in LITERAL_DROP):
        return True
    if any(k in s for k in SERVICE_TAILS):
        return True
    if s.startswith("好的，") and len(s) < 60:
        return True
    if s.startswith("## 下一步可选方向") or s.startswith("下一步可选方向"):
        return True
    if re.match(r"^如果你愿意，我们可以", s):
        return True
    if re.match(r"^如果你告诉我", s):
        return True
    if re.match(r"^如果你能找到", s):
        return True
    if re.match(r"^(2\.\s*)?或者等待后续终盘变动", s):
        return True
    return False

BULLET = re.compile(r"^(方案\d+[.、:]?|[1-9]\d*[.、)】]|[-*]\s)")

# === 行内删除尾句（blockquote 内的"等终盘...反向验证"）+ 新比赛内容的提议尾句 ===
TAIL_REPLACEMENTS = [
    (re.compile(r"。?等终盘与赛果出来可以反向复盘验证。?"), "。"),
    (re.compile(r"。?等待终盘与赛果出炉我们可以反向验证本次判断。?"), "。"),
    (re.compile(r"。?等待终盘和赛果出来可以反向复盘验证。?"), "。"),
    (re.compile(r"。?等待终盘与赛果可反向验证整套逻辑。?"), "。"),
    (re.compile(r"。?等待终盘和赛果可以反向复盘验证。?"), "。"),
    (re.compile(r"。?等待终盘走势继续观察。?"), "。"),
    (re.compile(r"。?赛后拿到比分我们继续反向验证这套升盘守盘模板。?"), "。"),
    (re.compile(r"。?赛后比分出来我们反向验证静态维稳盘的特征。?"), "。"),
    (re.compile(r"。?赛后比分出来反向验证模板有效性。?"), "。"),
    (re.compile(r"。?赛后比分出来统一复盘验证各个模板。?"), "。"),
    (re.compile(r"。?赛后比分出来验证这套深盘降档模板。?"), "。"),
    (re.compile(r"。?赛后比分出来统一验证深盘降档模板。?"), "。"),
    (re.compile(r"。?如果你后续拿到终盘走势以及最终比分，我们可以反向验证本次推演是否成立。?"), "。"),
    (re.compile(r"。?如果你告诉我这场最终比分，我们可以反向验证，看看这条盘路属于【降水实防】还是【低水诱上】。?"), "。"),
    (re.compile(r"。?你可以直接把本场最终比分发出来，我们反向验证这套推演，区分本次属于【实防降水】还是【诱盘陷阱】。?"), "。"),
    (re.compile(r"。?如果你愿意，我们可以拿这条「假撤退降盘」模板，后续遇到同类走势赛事做跟踪对照复盘。?"), "。"),
    (re.compile(r"。?如果你能找到这场完整全程变盘记录，我们可以完整验证这条推演。?"), "。"),
    (re.compile(r"后续赛后拿到比分，我们可以逐场反向对照，区分每一条盘路属于【实防降水】还是【诱盘陷阱】，积累模板样本。?"), ""),
    (re.compile(r"等终盘定型之后，我们可以等待赛后比分，逐条复盘验证每一套盘路对应的结局。?"), ""),
    (re.compile(r"等终盘定型、赛后比分出来，我们可以逐场反向复盘，区分每一条盘路属于【实防降水】还是【诱盘套路】，积累样本模板。?"), ""),
    # 新比赛内容中的提议行内删除
    (re.compile(r"[；;。]?如果你想要对比威廉/英特，你主动提一句，我再单独拿两家赔率做对比[。]?"), ""),
    (re.compile(r"如果你愿意，可以思考一道思考题[:：]?"), ""),
    (re.compile(r"如果你愿意，\s*$"), ""),
]

def clean_tails(text):
    for pattern, repl in TAIL_REPLACEMENTS:
        text = pattern.sub(repl, text)
    return text

def clean_bot(text):
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if is_fan_or_meta_line(s):
            i += 1
            if META_COUNT_HEADER.match(s):
                while i < n:
                    ns = lines[i].strip()
                    if ns == "":
                        i += 1
                        continue
                    if BULLET.match(ns) or ns.startswith("1.") or ns.startswith("2.") or ns.startswith("3.") or ns.startswith("4.") or ns.startswith("5.") or ns.startswith("6.") or ns.startswith("7.") or ns.startswith("8."):
                        i += 1
                        continue
                    if ns.startswith("###") or ns.startswith("##"):
                        break
                    break
            else:
                while i < n:
                    ns = lines[i].strip()
                    if ns == "":
                        break
                    if BULLET.match(ns) or ns in ("：", ":"):
                        i += 1
                        continue
                    break
            continue
        if is_offer_line(s):
            i += 1
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
    text = replace_terms(text)
    text = text.replace("你原文中", "").replace("你原文里", "").replace("你文中", "")
    text = re.sub(r"你原来的文稿", "", text)
    text = re.sub(r"你的原稿", "", text)
    text = text.replace("帮你更正", "更正").replace("帮你梳理", "梳理").replace("帮你整理", "整理")
    text = text.replace("上面那段你", "上面那段").replace("上面你", "上面")
    text = text.replace("我为你", "我").replace("为你梳理", "梳理").replace("为你整理", "整理").replace("为你更正", "更正")
    text = clean_tails(text)
    text = re.sub(r"\n## 下一步可选方向\n1\..*?(?=\n---|\n## |\Z)", "", text, flags=re.DOTALL)
    text = re.sub(r"\n下一步可选方向\n1\..*?(?=\n---|\n## |\Z)", "", text, flags=re.DOTALL)
    text = re.sub(r"\n如果你想要，我还可以继续扩充：.*?(?=\n---|\n## |\Z)", "", text, flags=re.DOTALL)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

for t in post:
    role = t.get("role", "")
    if "豆包" in role and t["text"]:
        t["text"] = clean_bot(t["text"])
        t["role"] = "主讲/作者"
    elif "用户" in role:
        t["role"] = "👤 用户"

# ============================================================
# 5. 重新顺序编号
# ============================================================
post = [t for t in post if (t["text"] or "").strip() or t["imgs"]]
n_user = sum(1 for t in post if "用户" in t.get("role", ""))
n_bot = sum(1 for t in post if "主讲" in t.get("role", ""))
n_img_turns = sum(1 for t in post if t["imgs"])
# 判断文件是否为真图片（跳过下载时落盘的 HTML 错误页/空文件）
def is_real_image(fp):
    try:
        with open(fp, "rb") as f:
            head = f.read(8)
    except Exception:
        return False
    return (
        head[:3] == b"\xff\xd8\xff"
        or head[:8] == b"\x89PNG\r\n\x1a\n"
        or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
        or head[:3] == b"GIF"
    )

total_uniq = len(uniq)
localized = sum(1 for u in uniq if is_real_image(os.path.join(WS, uniq[u][0])))
missing = total_uniq - localized
print(f"重写后 总轮数={len(post)}  用户={n_user}  主讲/作者={n_bot}  含图轮次={n_img_turns}  图片uniq={total_uniq}  已本地化(真图)={localized}  缺失/假图={missing}")

# ============================================================
# 6. 头部信息
# ============================================================
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
    L.append(f"# {title}（主讲整理版·续更）\n")
    L.append("> **来源**：豆包分享帖（续更版，含新增比赛分析）  ")
    L.append(f"> **分享者**：{author}  ｜  **原始对话对象**：{bot}（内容已整理为主讲第一人称口径）  ")
    L.append(f"> **消息数**：{len(post)} 轮（用户 {n_user} / 主讲·作者 {n_bot}）；含图片 {n_img_turns} 轮 / 共 {total_uniq} 张，已本地化 {localized} 张  ")
    if st:
        L.append(f"> **分享时间**：{st}  ")
    L.append(f"> **原帖**：https://www.doubao.com/thread/{SHARE_ID}  ")
    L.append("")
    L.append("> ⚠️ 内容为足球盘口（亚盘/澳盘）数据解读科普，原帖已注明网络购彩属违法行为，本文仅作赛事数据参考，不构成任何投注建议。  ")
    if missing:
        L.append(f"> ⚠️ 其中 {missing} 张图片因来源为第三方 CDN（无有效签名，HTTP 403）无法下载，已在对应位置省略。")
    L.append("")
    L.append("---\n")
    L.append("## 对话内容（整理版）\n")
    return L

# 图片辅助：缺失或非真图片（HTML 错误页）则跳过
def img_rel(url):
    rel, sz = uniq.get(url, (None, 0))
    if not rel:
        return None
    fp = os.path.join(WS, rel)
    if not os.path.exists(fp) or os.path.getsize(fp) == 0:
        return None
    if not is_real_image(fp):  # 跳过下载时落盘的 HTML 错误页/空文件
        return None
    return rel

# ===== A. 纯文本 MD =====
A = header_lines()
for idx, t in enumerate(post, 1):
    A.append(f"### {t['role']}（第 {idx} 轮）")
    A.append("")
    if (t["text"] or "").strip():
        A.append(t["text"].strip())
        A.append("")
    A.append("---\n")
open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读.md"), "w", encoding="utf-8").write("\n".join(A))
print("A 纯文本 md 完成")

# ===== B. 图文 MD =====
B = header_lines()
for idx, t in enumerate(post, 1):
    B.append(f"### {t['role']}（第 {idx} 轮）")
    B.append("")
    if (t["text"] or "").strip():
        B.append(t["text"].strip())
        B.append("")
    for u in t["imgs"]:
        rel = img_rel(u)
        if rel:
            B.append(f"![图片]({rel})")
            B.append("")
    B.append("---\n")
open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_图文版.md"), "w", encoding="utf-8").write("\n".join(B))
print("B 图文 md 完成")

# ===== C. 单文件 HTML =====
def b64(u):
    rel = img_rel(u)
    if not rel:
        return None
    fp = os.path.join(WS, rel)
    ext = rel.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else "image/jpeg" if ext in ("jpg", "jpeg") else "image/webp"
    with open(fp, "rb") as f:
        data = f.read()
    return "data:" + mime + ";base64," + base64.b64encode(data).decode()

body = []
body.append('<div class="meta"><b>来源</b>：豆包分享帖（续更版，含新增比赛分析）<br><b>分享者</b>：' + author +
            ' ｜ <b>原始对话对象</b>：' + bot + '（内容已整理为主讲第一人称口径）<br><b>消息数</b>：'
            + str(len(post)) + ' 轮（用户 ' + str(n_user) + ' / 主讲·作者 ' + str(n_bot) +
            '）；含图片 ' + str(n_img_turns) + ' 轮 / 共 ' + str(total_uniq) + ' 张，已内联 ' + str(localized) + ' 张<br>' +
            ('<b>分享时间</b>：' + st + '<br>' if st else '') +
            '<b>原帖</b>：<a href="https://www.doubao.com/thread/' + SHARE_ID + '">https://www.doubao.com/thread/' + SHARE_ID + '</a></div>')
body.append('<div class="warn">⚠️ 内容为足球盘口（亚盘/澳盘）数据解读科普，原帖已注明网络购彩属违法行为，本文仅作赛事数据参考，不构成任何投注建议。</div>')
if missing:
    body.append('<div class="warn">⚠️ 其中 ' + str(missing) + ' 张图片因来源为第三方 CDN（无有效签名，HTTP 403）无法下载，已在对应位置省略。</div>')
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

CSS = """:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0f1115;color:#e6e8eb;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.75;font-size:16px}
.wrap{max-width:880px;margin:0 auto;padding:32px 20px 80px}
.meta{background:#181b21;border:1px solid #2a2e37;border-radius:10px;padding:16px 18px;font-size:14px;color:#9aa0a8}
.warn{background:#2a2310;border:1px solid #5a4410;color:#e0b860;border-radius:10px;padding:12px 16px;margin-top:14px;font-size:14px}
hr{border:none;border-top:1px solid #2a2e37;margin:22px 0}
h1,h2{color:#f0f2f5}
h2{font-size:20px;margin:8px 0 18px}
.turn{background:#181b21;border:1px solid #2a2e37;border-radius:12px;padding:18px 20px;margin-bottom:16px}
.turn.author{border-left:4px solid #4c8dff}
.turn.user{border-left:4px solid #2ecc71}
.role{font-weight:700;font-size:14px;color:#9aa0a8;margin-bottom:10px}
.text img{max-width:100%}
.pic{display:block;max-width:100%;height:auto;margin:12px 0;border:1px solid #2a2e37;border-radius:8px}
.text table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
.text th,.text td{border:1px solid #2e333d;padding:8px 10px;text-align:left;color:#d8dce2}
.text th{background:#23272f;font-weight:600;color:#e6e8eb}
.text code{background:#23272f;padding:2px 6px;border-radius:4px;font-size:13px;color:#e0b860}
.text pre{background:#23272f;padding:12px;border-radius:8px;overflow:auto}
.text pre code{background:none;padding:0;color:#e6e8eb}
.text blockquote{margin:12px 0;padding:8px 14px;border-left:3px solid #3a3f4a;color:#aab0b8;background:#15181e}
a{color:#5b9bff}"""

html = ('<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>'
        + title + '（主讲整理版·续更·单文件）</title>\n<style>' + CSS + '</style>\n</head>\n<body>\n'
        '<div class="wrap">\n<h1>' + title + '（主讲整理版·续更）</h1>\n' + "".join(body)
        + '\n</div>\n</body>\n</html>')

path_html = os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_单文件.html")
open(path_html, "w", encoding="utf-8").write(html)
print("C 单文件 html 完成, size MB:", round(os.path.getsize(path_html) / 1024 / 1024, 2))
