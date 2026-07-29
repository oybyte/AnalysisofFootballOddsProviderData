import json, os, re

TMP = r"C:\Users\lcz\AppData\Local\Temp"
p = json.load(open(os.path.join(TMP, "parsed.json"), encoding="utf-8"))
turns = p["turns"]

# 上一步已删的 8 条用户长文（原始 1-based 轮次）
DEL_USER = {8, 10, 12, 14, 18, 20, 22, 24}
del_idx = {r - 1 for r in DEL_USER}
kept = [t for i, t in enumerate(turns) if i not in del_idx]
print("原始轮数:", len(turns), " 删 8 条后:", len(kept))

# 标记短语
markers = [
    "我们梳理一下你发送", "你原文中", "你原文里", "你文中", "上面那段", "上面你",
    "帮你更正", "帮你梳理", "帮你整理", "如果你需要，我可以把", "如果你需要我可以把",
    "我可以把这", "合并整理成", "学习笔记", "学习手册", "有疑问", "欢迎继续",
    "祝你好运", "希望对你有帮助", "三、整套系列学习脉络汇总", "整套系列学习脉络汇总",
    "完整标准分析流程", "如果你需要", "一键三连", "充电支持",
]
print("\n=== 命中含有标记短语的轮次（在 104 序列中的序号，1-based）===")
for i, t in enumerate(kept, 1):
    role = t["role"]
    txt = t["text"] or ""
    hits = [m for m in markers if m in txt]
    if hits:
        print(f"\n[kept#{i}] {role}  命中: {hits}")
        print("   首行:", txt.strip().splitlines()[0][:80] if txt.strip() else "(空)")

# 精确定位 R15 第三节切割点
print("\n=== R15 第三节切割点核对 ===")
for i, t in enumerate(kept, 1):
    if "整套系列学习脉络汇总" in (t["text"] or ""):
        txt = t["text"]
        pos = txt.find("三、整套系列学习脉络汇总")
        if pos < 0:
            pos = txt.find("整套系列学习脉络汇总")
        print(f"kept#{i} 命中。切割点前 60 字:")
        print(repr(txt[max(0, pos-60):pos+40]))
        print("\n切割点之后内容预览(前 400 字):")
        print(txt[pos:pos+400])
