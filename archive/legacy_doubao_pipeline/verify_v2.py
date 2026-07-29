import os, re
WS = r"C:\Users\lcz\WorkBuddy\2026-07-27-09-58-26"

bad_proposals = ["如果你需要，我可以把", "如果你需要我可以把", "我可以把这", "合并整理成一份连贯学习笔记",
                 "连贯学习笔记", "学习手册精简版", "生成一份完整盘口学习手册"]
meta = ["我们梳理一下你发送", "你原文中", "你原文里", "你文中", "你原来的文稿", "帮你更正", "帮你梳理"]
leftover = ["整套系列学习脉络汇总", "完整标准分析流程"]

for name, fn in [("纯文本md", "豆包对话_FC首尔VS蔚山HD澳盘数据解读.md"),
                 ("图文md", "豆包对话_FC首尔VS蔚山HD澳盘数据解读_图文版.md"),
                 ("单文件html", "豆包对话_FC首尔VS蔚山HD澳盘数据解读_单文件.html")]:
    t = open(os.path.join(WS, fn), encoding="utf-8").read()
    bp = [x for x in bad_proposals if x in t]
    mt = [x for x in meta if x in t]
    lv = [x for x in leftover if x in t]
    role_bot = "🤖 豆包" in t
    role_author = "主讲/作者" in t
    n_turns = len(re.findall(r"（第 \d+ 轮）", t))
    if name == "图文md":
        imgs = len(re.findall(r"!\[图片\]\(images/[^)]+\)", t))
        missing = [m for m in re.findall(r"images/([^)]+)", t) if not os.path.exists(os.path.join(WS, "images", m))]
    elif name == "单文件html":
        imgs = len(re.findall(r"data:image/(png|jpeg|webp);base64,", t))
        rel = len(re.findall(r'src="images/', t))
    else:
        imgs = 0; missing = []; rel = -1
    print(f"[{name}] 轮次={n_turns} 标签主讲/作者={role_author} 旧标签豆包残留={role_bot}")
    print(f"   提议句残留={bp if bp else '无'}  元评论残留={mt if mt else '无'}  R15第三节残留={lv if lv else '无'}")
    if name == "图文md":
        print(f"   图片引用={imgs} 缺失={missing if missing else '无'}")
    if name == "单文件html":
        print(f"   内联图片={imgs} 相对路径残留={rel}")
    print()

# 抽查第一段主讲改写效果
print("=== 抽查：原计数元评论是否彻底消失 ===")
t = open(os.path.join(WS, "豆包对话_FC首尔VS蔚山HD澳盘数据解读_图文版.md"), encoding="utf-8").read()
print("'一共5段' 出现:", t.count("一共**5段") , "| '合计：4段' 出现:", t.count("合计：4段"))
