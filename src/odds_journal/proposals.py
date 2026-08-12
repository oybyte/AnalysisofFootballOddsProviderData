from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from .extraction import EXTRACTION_RELATIVE, validate_extraction_state
from .ledger import atomic_write_text


REQUIRED_RULE_IDS = [
    "football-analysis-framework",
    "market-settlement-rules",
    "data-provenance-time-boundary",
    "prematch-stage-positioning",
    "theoretical-vs-actual-market",
    "market-timeline-cross-validation",
    "dual-hypothesis-evidence",
    "layered-decision-confidence-pass",
    "goals-score-separation",
    "prematch-checklist-v1",
    "data-quality-conflict-and-pass",
    "scenario-identification-and-case-retrieval",
    "live-update-and-postmatch-separation",
]
CONDITIONAL_RULE_IDS = [
    "handicap-inducement-resistance",
    "market-heat-chip-distribution",
    "cross-related-same-pattern",
    "water-threshold-operator-style",
    "operator-market-divergence",
    "asian-european-divergence",
    "handicap-total-goals-divergence",
    "late-market-reversal",
]
EXPERIMENTAL_1_3_RULE_IDS = [
    "draw-kelly-parity-v1",
    "deep-line-stable-cover-v1",
    "quarter-low-water-inducement-v1",
    "hidden-draw-away-cut-v1",
    "total-goals-cross-market-v1",
    "score-baseline-v1",
    "korea-goal-drop-v1",
    "korea-deep-line-loss-tolerance-v1",
]
EXPERIMENTAL_1_6_RULE_IDS = [
    "tg-same-line-water-defense-v1",
    "tg-line-drop-over-price-divergence-v1",
    "tg-late-shock-guard-v1",
    "tg-two-dimension-confirmation-v1",
    "tg-dual-line-bracket-v1",
    "tg-handicap-ceiling-risk-v1",
    "tg-head-provider-divergence-nordic-v1",
    "tg-floor-anchor-upper-tail-v1",
    "tg-draw-compression-hypothesis-v1",
    "tg-one-sided-overrun-risk-v1",
    "tg-away-collapse-prior-v1",
    "tg-extreme-under-context-v1",
]
EXPERIMENTAL_1_6_ADVISORY_DOCUMENT_IDS = [
    "advisory-initial-water-guard-pack-v1",
    "advisory-away-brand-trap-pack-v1",
    "advisory-total-water-boundaries-pack-v1",
    "advisory-deep-line-goal-trap-pack-v1",
]

VERSION_DOCUMENT_CONTRACTS = {
    "1.1.0": (REQUIRED_RULE_IDS, CONDITIONAL_RULE_IDS),
    "1.2.0": (
        REQUIRED_RULE_IDS,
        [*CONDITIONAL_RULE_IDS, "low-stability-league-weight-calibration"],
    ),
    "1.3.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
        ],
    ),
    "1.4.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
        ],
    ),
    "1.5.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
        ],
    ),
    "1.6.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
            *EXPERIMENTAL_1_6_RULE_IDS,
            *EXPERIMENTAL_1_6_ADVISORY_DOCUMENT_IDS,
        ],
    ),
    "1.7.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
            *EXPERIMENTAL_1_6_RULE_IDS,
            *EXPERIMENTAL_1_6_ADVISORY_DOCUMENT_IDS,
        ],
    ),
    "1.8.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
        ],
    ),
    "1.9.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
        ],
    ),
    # 2.0.0 keeps the published 1.8.0 document contract as an explicitly
    # hashed baseline.  Its new assets live in the knowledge-engine sidecar;
    # it must never silently inherit a mutable proposal directory.
    "2.0.0": (
        REQUIRED_RULE_IDS,
        [
            *CONDITIONAL_RULE_IDS,
            "low-stability-league-weight-calibration",
            *EXPERIMENTAL_1_3_RULE_IDS,
        ],
    ),
}


def document_contract(version: str) -> tuple[list[str], list[str]]:
    try:
        required, conditional = VERSION_DOCUMENT_CONTRACTS[version]
    except KeyError as exc:
        raise ValueError(f"未定义 football-analysis@{version} 的文档契约") from exc
    return list(required), list(conditional)


@dataclass(frozen=True)
class Blueprint:
    document_id: str
    title: str
    document_type: str
    reliability: str
    markets: list[str]
    phases: list[str]
    tags: list[str]
    atoms: list[str]
    scenarios: list[str]
    purpose: str
    terms: list[str]
    inputs: list[str]
    steps: list[str]
    matrix: list[tuple[str, str, str]]
    hypothesis_a: str
    hypothesis_b: str
    triggers: list[str]
    conflicts: list[str]
    failures: list[str]
    supports: list[str]
    counterexamples: list[str]
    change: str


def _bp(
    identity: str,
    title: str,
    kind: str,
    reliability: str,
    markets: list[str],
    phases: list[str],
    tags: list[str],
    atoms: list[str],
    scenarios: list[str],
    purpose: str,
    terms: list[str],
    inputs: list[str],
    steps: list[str],
    matrix: list[tuple[str, str, str]],
    a: str,
    b: str,
    triggers: list[str],
    conflicts: list[str],
    failures: list[str],
    supports: list[str],
    counterexamples: list[str],
    change: str,
) -> Blueprint:
    return Blueprint(identity, title, kind, reliability, markets, phases, tags, atoms, scenarios,
                     purpose, terms, inputs, steps, matrix, a, b, triggers, conflicts, failures,
                     supports, counterexamples, change)


BLUEPRINTS = [
    _bp(
        "football-analysis-framework", "足球比赛分析基础框架", "method", "supported", ["all"],
        ["prematch", "live", "postmatch"], ["总流程", "门禁", "分层决策"],
        ["doubao-2026-07-28-text-a00049", "doubao-2026-07-28-text-a00375", "doubao-2026-07-28-text-a03721"], [],
        "规定从事实归档到赛后证据追加的唯一顺序，防止先有方向再找理由。",
        ["事实层：可核对且带时间的输入", "解释层：可被反证的假设", "结论层：主市场、选择、置信度与 pass"],
        ["比赛身份与开赛时间", "带来源的基本面和盘赔快照", "活动规则集回执", "场景与历史案例回执"],
        ["核对时间边界和来源", "列出缺失、冲突与不可证实信息", "建立阶段性实力定位和理论区间", "还原实际盘口时序并识别场景", "建立双向假设并检索候选案例", "分层输出主线、总进球、比分、置信度和 pass 条件"],
        [("事实完整且市场一致", "继续推演并保留反证", "不得提高到确定性"), ("关键事实缺失", "先补数据或 pass", "不得用盘口反推伤停"), ("市场冲突无法解释", "降低置信度或 pass", "不得任选一个市场覆盖冲突")],
        "当前盘赔变化主要反映可持续的风险重定价。", "当前盘赔变化主要反映市场噪声、热度吸收或短时再平衡。",
        ["新快照延续同方向且跨机构确认", "基本面信息与理论盘口同向", "欧赔、让球与总进球矛盾得到解释"],
        ["事实优先于解释", "理论定位优先于盘路标签", "同市场时序优先于单点水位", "主市场优先于比分"],
        ["无法确认比赛身份或时间", "只有单一截图且缺少盘向", "规则回执或案例回执无效", "主要证据相互冲突且无区分触发条件"],
        ["韩K四场连续跟踪展示了先记录后复盘的价值", "赫尔辛基复盘推动胜负与让球分离"],
        ["赫尔辛基 1-0 证明稳定升盘不能直接等同穿盘", "罗森博格 4-0 证明诱上解释不能排除大胜"],
        "从简要流程扩展为带规则、场景、案例和证据回执的完整状态机。",
    ),
    _bp(
        "market-settlement-rules", "市场与盘口结算规则", "concept", "established", ["all"],
        ["prematch", "live", "postmatch"], ["结算", "亚洲让球", "大小球", "胜平负"],
        ["doubao-2026-07-28-text-a00026", "doubao-2026-07-28-text-a00094", "doubao-2026-07-28-text-a00112"], [],
        "在任何方向判断前统一市场、盘向、结算比分和赢半输半语义。",
        ["让球方/受让方不等同于主队/客队", "整数盘可能走盘", "四分之一盘把本金等分到相邻两条线"],
        ["市场名称", "投注时盘口与盘向", "结算采用的比赛阶段", "官方最终比分及加时是否计入"],
        ["从主队视角规范盘口符号", "将四分之一盘拆成两条相邻盘口", "对每一半分别计算胜负或走盘", "合并为全赢、赢半、走盘、输半或全输", "胜平负和大小球独立结算", "记录机构特殊条款"],
        [("让球 0，赛果平", "走盘退款", "不能判受让方赢盘"), ("让球 -0.25，赛果平", "让球方输半", "不能判全输"), ("让球 -0.75，净胜 1", "让球方赢半", "不能判全赢"), ("让球 -1，净胜 1", "走盘", "不能判输盘")],
        "记录的盘口和比分足以按标准规则结算。", "市场使用特殊时段、加时或不同盘向，需要机构条款覆盖标准规则。",
        ["机构官方规则页与市场名称一致", "比分和比赛阶段已确认", "盘口字符串没有歧义"],
        ["官方结算规则高于历史教学文字", "具体市场条款高于通用解释", "原始机构文字高于自动数值转换"],
        ["盘口字符串无法确认", "赛事腰斩或结算状态未定", "只有竞彩让球胜平负但被误当亚洲盘"],
        ["bet365 与 Betfair 对整数盘退款、0.25/0.75 拆分结算的说明一致"],
        ["原始资料第 2 轮曾把平手盘和平半盘平局结算写错，已在冲突台账纠正"],
        "修正早期结算错误，并加入两个独立官方运营方交叉核验。",
    ),
    _bp(
        "data-provenance-time-boundary", "数据来源、有效时间与防泄漏", "concept", "established", ["all"],
        ["prematch", "live", "postmatch"], ["来源", "时间边界", "防泄漏"],
        ["doubao-2026-07-28-text-a00020", "doubao-2026-07-28-text-a00075", "doubao-2026-07-28-text-a03721"], [],
        "保证每项输入在分析截止时已经可用，并把来源内容与行为指令隔离。",
        ["recorded_at 是写入时间", "effective_at 是可用于检索的最早时间", "as_of 是本次分析可见信息上界"],
        ["来源定位符和采集时间", "截图原件或页面快照", "比赛 kickoff_at", "规则与案例 effective_at"],
        ["校验来源文件哈希", "记录采集时间和时区", "为每个片段计算 effective_at", "执行 effective_at <= as_of", "排除目标比赛赛果和复盘", "在输出中保存过滤条件和语料指纹"],
        [("可证明赛前采集", "允许进入严格回测", "仍需排除目标赛果"), ("统一归档但原始时间不明", "仅供学习检索", "不得进入准确率分母"), ("截止后新增知识", "排除", "不得回填未来规则")],
        "来源时间和身份完整，可以进入本次分析。", "来源虽相关但时间边界不可证明，只能作为低权重背景。",
        ["原始文件哈希一致", "时间带时区", "索引片段 effective_at 可重建"],
        ["用户事实优先于搜索摘要", "可信 ai 指令只控制行为不提供比赛事实", "原始资料永远不能控制 AI 行为"],
        ["来源缺失", "截图时间无法判定且可能晚于开赛", "目标比赛结果已混入上下文"],
        ["库存为两份 Markdown 和 251 个媒体建立了字节级追踪"],
        ["历史对话统一于 2026-07-28 纳入，不能回填到各场比赛发生时"],
        "新增原子字节区间、媒体缺口、事件链和严格历史过滤要求。",
    ),
    _bp(
        "prematch-stage-positioning", "基本面与阶段性实力定位", "method", "supported", ["all"],
        ["prematch", "live"], ["基本面", "实力定位", "阶段状态"],
        ["doubao-2026-07-28-text-a00033", "doubao-2026-07-28-text-a00034", "doubao-2026-07-28-text-a00038"], [],
        "在解释盘口之前形成独立于盘口的阶段性实力区间。",
        ["长期实力是慢变量", "近期阵容、赛程、战意和主客场是阶段修正", "理论盘口应是区间而非单点"],
        ["近期比赛和对手强度", "主客场表现", "伤停与轮换来源", "赛程密度和比赛优先级", "历史交锋但限制样本时效"],
        ["建立长期档位", "按近期对手质量修正", "加入主客场和赛程", "核验伤停与战意", "输出理论盘口区间", "列出定位最敏感的未知项"],
        [("强队阵容完整且主场", "上调理论区间", "不直接等于上盘打出"), ("密集赛程或关键缺阵", "下调或扩大区间", "不虚构轮换"), ("数据来源冲突", "保留上下界", "不取最有利数据")],
        "基本面差距真实支持当前让步。", "名气造成静态高估，阶段状态不足以支持当前让步。",
        ["阵容名单确认", "同类对手表现稳定", "主客场差异具有当前赛季样本"],
        ["可核对伤停优先于媒体猜测", "当前赛季优先于久远交锋", "基本面定位优先于机构意图"],
        ["核心阵容和赛程缺失", "跨联赛缺少可比基准", "仅有盘口没有基本面"],
        ["FC首尔与蔚山的传统强队认知需要阶段修正"],
        ["赫尔辛基主胜方向成立但深盘穿盘能力被高估"],
        "将球队档位改为带上下界、修正项和敏感条件的阶段定位。",
    ),
    _bp(
        "theoretical-vs-actual-market", "理论盘口与实际盘口比较", "method", "supported", ["handicap", "one_x_two"],
        ["prematch", "live"], ["理论盘口", "实际盘口", "深浅比较"],
        ["doubao-2026-07-28-text-a00049", "doubao-2026-07-28-text-a00241", "doubao-2026-07-28-text-a01462"], ["favorite-line-mismatch"],
        "用独立定位区间识别实际开盘偏深、偏浅或落在合理范围，但不把偏差直接翻译为方向。",
        ["理论盘口区间来自基本面", "实际盘口是价格和风险管理结果", "偏差需要市场与时序解释"],
        ["阶段性定位", "主流机构初盘", "可比比赛或同联赛档位", "当前水位和后续变动"],
        ["先冻结理论区间", "记录实际初盘", "计算偏差方向和幅度", "检查是否由主客场或阵容解释", "建立真实重估与市场造势双假设", "等待后续时序区分"],
        [("实际盘在理论区间", "视为标准定位", "仍需跟踪水位"), ("实际明显偏浅", "检查强队被高估或信息缺失", "不自动选弱队"), ("实际明显偏深", "检查实力重估或热门溢价", "不自动判诱盘")],
        "盘口偏差源于新增事实和真实实力重估。", "盘口偏差源于热度、流动性或机构风险管理。",
        ["多机构同步开盘", "后续档位站稳", "欧赔概率结构同步变化"],
        ["阶段定位优先", "开盘偏差优先于同档微小水位", "后续回撤可否定初始重估"],
        ["没有理论区间", "只看到临场盘而无初盘", "机构盘向不一致且无法规范"],
        ["安养升档并守住与首尔升后回撤形成对照"],
        ["同样低水初盘在金泉与浦项走出相反赛果"],
        "明确偏深偏浅只生成待验证假设，不再直接给方向。",
    ),
    _bp(
        "market-timeline-cross-validation", "盘口时序与多市场交叉验证", "method", "supported", ["all"],
        ["prematch", "live"], ["时序", "欧亚交叉", "大小球"],
        ["doubao-2026-07-28-text-a00039", "doubao-2026-07-28-text-a00075", "doubao-2026-07-28-text-a00085"], ["static-line-water-movement", "line-rise-water-rise", "line-rise-water-fall", "line-drop-water-rise", "line-drop-water-fall"],
        "把离散快照还原为有时间顺序的档位、水位和跨市场变化链。",
        ["档位变化优先于同档水位", "持续变化与短时反转不同", "多市场用途不同不能强求方向一致"],
        ["至少两个时间点", "同一机构的可比盘口", "多机构横截面", "欧赔和大小球同步时间"],
        ["按时间排序并去重", "识别升档、降档或静态调水", "区分渐进、突击、震荡和回撤", "比较机构一致性", "比较欧赔概率结构", "独立检查总进球后记录矛盾"],
        [("渐进升档且站稳", "提高真实重估假设权重", "保留不穿盘反例"), ("升档后快速回撤", "登记 late reversal", "不直接称诱盘"), ("盘口静态仅水位变化", "判断风险价格调整", "不夸大为档位信号")],
        "时序变化是信息吸收后形成的新稳定价格。", "时序变化是短期热度和风险再平衡，方向未改变。",
        ["变化持续时间", "机构覆盖数量", "跨市场是否同步", "临场是否反转"],
        ["完整时序高于单点", "同机构纵向高于不同机构拼接", "让球主线与大小球分别结论"],
        ["快照不足", "时间戳不可靠", "混合不同盘口口径", "短时高频往返无法分类"],
        ["韩K四场和北欧两场提供多种时序结构"],
        ["赫尔辛基升档站稳仍只 1-0；单一结构不能决定结局"],
        "新增节奏、回撤、跨机构和跨市场矩阵。",
    ),
    _bp(
        "dual-hypothesis-evidence", "双向假设、反证与失效条件", "method", "supported", ["all"],
        ["prematch", "live", "postmatch"], ["双向假设", "反证", "触发条件"],
        ["doubao-2026-07-28-text-a00096", "doubao-2026-07-28-text-a00252", "doubao-2026-07-28-text-a00632"], [],
        "强制每个关键盘路信号至少保留两个可区分解释，减少单向叙事和赛后合理化。",
        ["支持证据提高假设权重", "反证限制解释范围", "区分触发条件必须能在锁定前观察"],
        ["关键事实列表", "场景实例", "相反历史案例", "下一次可观察盘口或阵容触发点"],
        ["把观察写成不含意图的事实", "提出假设 A", "提出机制不同的假设 B", "分别列支持与反证", "定义区分触发条件", "选择解释或明确 unresolved/pass"],
        [("只有支持没有反证", "补反例后再选", "禁止锁定确定性结论"), ("A/B 预测相同但机制不同", "记录机制不确定", "结论置信度不得虚高"), ("新事实同时否定 A/B", "新增假设或 pass", "不得硬选")],
        "观察反映真实方向性重估。", "观察反映热度吸收、流动性或噪声。",
        ["档位继续站稳或回撤", "关键阵容确认", "欧赔概率同步或背离", "大小球结构是否改变"],
        ["事实证据高于机构意图推测", "反例高于口号", "可观察触发点高于水位口诀"],
        ["无法提出机制不同的第二假设", "区分条件只能赛后观察", "证据全部来自同一未经核验来源"],
        ["首尔升后退与安养升后守稳可形成对照"],
        ["罗森博格大胜反驳升盘深降水必为诱上的单向解释"],
        "把原有正反解释升级为结构化证据、反证和触发条件。",
    ),
    _bp(
        "layered-decision-confidence-pass", "分层决策、置信度与放弃分析", "method", "supported", ["all", "pass"],
        ["prematch", "live"], ["主线", "置信度", "pass"],
        ["doubao-2026-07-28-text-a00657", "doubao-2026-07-28-text-a01756", "doubao-2026-07-28-text-a03721"], ["insufficient-or-conflicting-data"],
        "将是否参与、主市场、方向、次选、风险与置信度拆开，信息不足时明确 pass。",
        ["置信度是证据质量和一致性的摘要，不是主观胜率", "pass 是有效结论", "次选不能掩盖主线含糊"],
        ["数据完整性", "规则与案例回执", "双向假设结果", "主市场结算定义", "剩余未知项"],
        ["先决定是否可分析", "选择一个 primary_market", "选择与市场匹配的 primary_selection", "记录 secondary_selection", "按证据质量给置信度", "写出触发 pass 或推翻结论的条件"],
        [("关键事实完整且主证据一致", "可给中等以上置信度", "仍保留随机事件"), ("结论依赖单一经验", "低置信度", "不得写确定性"), ("数据冲突或时间不明", "pass", "不计准确率")],
        "主证据足以形成可审计主线。", "剩余不确定性超过可接受范围，应放弃方向。",
        ["规则完整", "主市场被回执覆盖", "反例已处理", "案例差异已说明"],
        ["数据完整性高于方向偏好", "市场主线高于比分", "可复现证据高于样本内命中"],
        ["未知球队或赛事身份", "结算盘口缺失", "只剩相互冲突经验", "开赛后才获得关键赛前信息"],
        ["多轮历史对话反复强调观望与风险等级"],
        ["历史资料常在给出高风险后仍输出明确比分，1.1.0 禁止这种冲突"],
        "新增可执行 pass 门槛和置信度证据清单。",
    ),
    _bp(
        "goals-score-separation", "总进球、比分与让球分层", "method", "supported", ["total_goals", "handicap", "one_x_two"],
        ["prematch", "live", "postmatch"], ["总进球", "比分", "分层"],
        ["doubao-2026-07-28-text-a00159", "doubao-2026-07-28-text-a01429", "doubao-2026-07-28-text-a01503"], ["handicap-total-goals-divergence", "win-without-cover"],
        "阻止从让球方向线性推导总进球和精确比分。",
        ["胜平负描述结果方向", "让球描述净胜差门槛", "大小球描述总进球价格", "比分是最低优先级区间"],
        ["让球时序", "大小球时序", "胜平负概率结构", "攻防与阵容事实", "比分分布基线"],
        ["先独立完成主市场", "独立分析大小球", "记录让球与总进球是否背离", "构建宽比分区间", "按触发条件调整权重", "不删除低概率极端剧本"],
        [("看好主胜但深盘", "可保留赢球不穿", "不能只列大胜"), ("让球走弱但大球稳定", "可能客队得分或对攻", "不能等同小球"), ("平局信号增强", "同时保留 0-0 与 1-1/2-2", "需大小球区分")],
        "让球和大小球共同支持同一比分簇。", "两个市场反映不同维度，冲突意味着比分分布更宽。",
        ["大小球档位变化", "平局概率与凯利", "双方进球阵容", "临场总进球反转"],
        ["总进球市场高于由让球反推", "区间高于精确比分", "极端赛果只能降权不能无证据剔除"],
        ["缺少大小球数据", "比分依赖未经核验阵容", "市场冲突无法形成区间"],
        ["赫尔辛基 1-0 是赢球不穿的清晰样本"],
        ["赫根 0-0 与罗森博格 4-0 同时暴露总进球和极端比分遗漏"],
        "加入市场独立性、比分簇和极端尾部保留。",
    ),
    _bp(
        "prematch-checklist-v1", "赛前锁定检查清单", "checklist", "supported", ["all", "pass"],
        ["prematch"], ["检查清单", "锁定门禁"],
        ["doubao-2026-07-28-text-a00375", "doubao-2026-07-28-text-a01765", "doubao-2026-07-28-text-a03721"], [],
        "在锁定前执行机械检查，避免遗漏来源、时间、场景、案例和反证。",
        ["必填项是最低条件，不代表预测可靠", "每一项需要正文证据或明确缺失"],
        ["完整比赛 Markdown", "规则、场景和案例回执", "市场结算", "分析正文与最终结论"],
        ["核对比赛身份和时区", "核对来源、采集时间和事实哈希", "确认全部必需规则已读", "确认场景和无场景理由", "确认案例差异", "确认双向假设、pass 和结论分层"],
        [("全部通过", "允许进入 lock 技术校验", "不自动锁定"), ("可补项缺失", "返回 facts_ready", "不得写方向"), ("关键项不可补", "primary_market=pass", "记录原因")],
        "检查项完整足以进入锁定。", "形式完整但事实质量不足，仍应 pass。",
        ["无 TODO", "回执哈希有效", "结算方向匹配", "as_of <= data_cutoff <= kickoff"],
        ["机器可校验字段高于人工勾选", "事实完整性高于篇幅", "pass 高于勉强输出"],
        ["规则回执过期", "场景未登记", "案例未检索", "结论与 primary_market 不匹配"],
        ["历史实战显示多数错误来自步骤倒置而非缺少口诀"],
        ["仅勾选清单无法识别赛后补写，因此还需 Git 与哈希"],
        "从文本清单升级为 v2 回执和状态机的锁定前门禁。",
    ),
    _bp(
        "data-quality-conflict-and-pass", "数据质量、冲突处理与 Pass", "method", "supported", ["all", "pass"],
        ["prematch", "live", "postmatch"], ["数据质量", "冲突", "缺失"],
        ["doubao-2026-07-28-text-a00082", "doubao-2026-07-28-text-a00657", "doubao-2026-07-28-text-a01756"], ["insufficient-or-conflicting-data", "unclassified"],
        "用统一严重度处理缺失、来源分歧、术语冲突和不可恢复媒体。",
        ["blocker 阻止发布或锁定", "warning 降低权重", "info 仅记录", "unresolved 不能静默消失"],
        ["数据字段清单", "来源和时间", "冲突台账", "图片解码状态", "别名映射"],
        ["列出缺失字段", "区分事实冲突与解释冲突", "为冲突分组", "记录采用结论与保留条件", "判断是否可补", "不可补且影响主市场时 pass"],
        [("比分或盘口方向冲突", "blocker", "停止结算或锁定"), ("水位末位小差异", "warning", "保留原字符串"), ("媒体不可恢复", "记录缺口", "不得伪造 OCR")],
        "冲突可由更高质量来源或后续快照解决。", "冲突反映口径差异且无法证明哪一方正确。",
        ["官方来源", "原始截图", "时间更早且可验证的记录", "同机构连续快照"],
        ["原始字节高于 OCR", "官方结算高于教学文本", "未解决 blocker 高于方向需求"],
        ["关键盘口不可辨认", "两份来源实质差异未处置", "赛前和赛后文字混合无法分离"],
        ["46 个 403 响应和 21 个零字节文件已作为媒体缺口处置"],
        ["仅凭文件扩展名曾会误把 403 HTML 当作截图"],
        "新增发布阻断、媒体缺口和来源分歧的统一处置矩阵。",
    ),
    _bp(
        "scenario-identification-and-case-retrieval", "场景识别与历史案例检索", "method", "supported", ["all", "pass"],
        ["prematch", "live", "postmatch"], ["场景", "案例检索", "相似候选"],
        ["doubao-2026-07-28-text-a00285", "doubao-2026-07-28-text-a00632", "doubao-2026-07-28-text-a01462"], ["unclassified", "insufficient-or-conflicting-data"],
        "把当前观察登记为可反证场景，再检索历史候选；不把关键词相似宣称为语义等价。",
        ["场景类型描述结构而非结局", "场景实例属于单场观察", "候选案例必须解释差异"],
        ["有效规则回执", "赛前事实哈希", "盘赔时序", "场景白名单", "可用案例语料"],
        ["从无意图事实识别结构", "匹配场景类型或 unclassified", "填写 A/B 假设", "生成元数据与关键词查询", "执行 as_of 和目标排除", "记录选中与排除候选"],
        [("匹配已有类型", "登记实例和触发点", "不继承历史结局"), ("新结构", "使用 unclassified", "禁止强行套规则"), ("无明确结构", "记录 no_scenario_reason", "仍可 pass")],
        "历史候选共享可比较的盘口结构和关键条件。", "候选仅共享球队或关键词，机制不同。",
        ["同联赛/赛季", "相同盘口前置历史", "相同市场冲突", "反例是否存在"],
        ["当前事实高于案例", "场景前置历史高于最终形态", "已复盘且时间有效高于 mixed 案例"],
        ["规则回执无效", "场景未登记", "候选时间晚于 as_of", "案例只有赛后叙述"],
        ["13 个 legacy 案例保留原始时序与复盘供关键词检索"],
        ["同样升盘在安养、首尔和赫尔辛基对应不同结局"],
        "新增场景实例哈希、案例语料指纹和锁定前过期检查。",
    ),
    _bp(
        "live-update-and-postmatch-separation", "临场更新与赛后复盘隔离", "method", "supported", ["all"],
        ["live", "postmatch"], ["临场", "复盘", "不可覆盖"],
        ["doubao-2026-07-28-text-a00075", "doubao-2026-07-28-text-a01159", "doubao-2026-07-28-text-a03634"], ["late-market-reversal"],
        "保证锁定后的新信息只追加到 live-update，赛果后解释只进入 postmatch-review。",
        ["赛前观察一经锁定不可改", "临场场景按检测时间追加", "赛后 resolution 引用原场景而不覆盖它"],
        ["locked_at", "临场快照时间", "赛果记录时间", "场景实例和复盘回执"],
        ["核验状态为 locked", "追加带时间临场事实", "必要时登记 live 场景", "录入赛果后准备复盘", "逐场景填写 resolution", "reviewed 后再链接证据"],
        [("锁定后普通变化", "追加 live-update", "不改赛前结论"), ("录入错误", "追加更正说明", "不静默覆盖"), ("赛果已知", "只做 resolution/review", "不得重写 hypothesis")],
        "临场变化在赛前假设的触发范围内。", "临场出现新结构，需要新场景而非篡改旧实例。",
        ["变化时间晚于 locked_at", "来源可核对", "新场景 ID 唯一", "赛后解析覆盖所有场景"],
        ["锁定哈希最高", "临场事实高于赛前推测", "赛后事实不能反向进入赛前证据"],
        ["无法确认变化发生时间", "赛果已知但仍尝试改赛前正文", "场景解析遗漏"],
        ["FC首尔多次临场更新展示了档位回撤的重要性"],
        ["历史长文存在赛后用机构意图解释结果的倾向，不能回写为赛前判断"],
        "新增 live 场景、review receipt 和 resolution 追加机制。",
    ),
]


def _heuristic_blueprints() -> list[Blueprint]:
    specs = [
        ("handicap-inducement-resistance", "阻盘、诱盘与升降盘双向解释", ["handicap"], ["handicap-inducement-resistance", "favorite-line-mismatch"], ["doubao-2026-07-28-text-a00153", "doubao-2026-07-28-text-a00242", "doubao-2026-07-28-text-a00632"], "升降盘可能是信息重估，也可能是热度与风险管理，必须结合前置历史。", "升盘站稳且跨市场同步，真实支持权重上升。", "升盘突击、反复或回撤，热度吸收权重上升。", ["安养升后守稳并取胜"], ["赫尔辛基升盘站稳仍赢球不穿", "罗森博格深降水后 4-0"]),
        ("market-heat-chip-distribution", "市场热度、人气与筹码假设", ["all"], [], ["doubao-2026-07-28-text-a00236", "doubao-2026-07-28-text-a00323", "doubao-2026-07-28-text-a00443"], "把球队名气、媒体关注和价格变化写成热度假设，而不是内部资金事实。", "公开价格与外部关注共同支持单边热度。", "价格变化来自信息或流动性，不能证明筹码方向。", ["首尔与蔚山案例包含传统强队认知"], ["没有成交量数据，资金流向均不可直接验证"]),
        ("cross-related-same-pattern", "交叉盘、关联盘与同型盘", ["all"], [], ["doubao-2026-07-28-text-a00285", "doubao-2026-07-28-text-a00292", "doubao-2026-07-28-text-a00300"], "同时间或同联赛比赛可作风险对照，但不得假设机构必须让结果互补。", "两场存在共同市场背景，价格联动可能有信息价值。", "所谓交叉只是样本内巧合或选择偏差。", ["赫根与罗森博格一上一下"], ["单次互补结果不足以证明交叉规律"]),
        ("water-threshold-operator-style", "水位区间与机构风格", ["handicap", "total_goals"], ["static-line-water-movement"], ["doubao-2026-07-28-text-a00030", "doubao-2026-07-28-text-a00072", "doubao-2026-07-28-text-a00374"], "只在同机构、同市场、同盘口和相邻时点比较水位，不设通用高低水阈值。", "相对水位变化反映该机构风险价格调整。", "变化来自报价口径、汇率或流动性，方向含义弱。", ["多场同机构时序提供相对比较"], ["第 174 轮明确指出 0.95 阈值存在漏洞"]),
        ("operator-market-divergence", "机构间盘口分歧", ["handicap", "one_x_two"], ["operator-market-divergence"], ["doubao-2026-07-28-text-a00947", "doubao-2026-07-28-text-a00984", "doubao-2026-07-28-text-a01221"], "识别同一时点机构档位或价格显著分歧，并优先检查口径与更新时间。", "分歧反映机构模型或风险暴露不同。", "分歧只是更新时间、限额或展示口径不同。", ["首尔多机构升盘而澳盘留在半球"], ["单机构被称为龙头不构成预测证据"]),
        ("asian-european-divergence", "亚盘与欧赔背离", ["handicap", "one_x_two"], ["asian-european-divergence"], ["doubao-2026-07-28-text-a01285", "doubao-2026-07-28-text-a01314", "doubao-2026-07-28-text-a01383"], "比较欧赔胜平负概率结构与让球净胜门槛，背离时扩大结局范围。", "欧亚共同支持同一实力差。", "欧亚关注不同结算维度，表面背离可同时成立。", ["光州/济州案例使用欧亚交叉"], ["欧赔支持主胜不等于让球穿盘"]),
        ("handicap-total-goals-divergence", "让球与总进球背离", ["handicap", "total_goals"], ["handicap-total-goals-divergence", "win-without-cover"], ["doubao-2026-07-28-text-a01429", "doubao-2026-07-28-text-a01502", "doubao-2026-07-28-text-a01503"], "当净胜门槛和总进球预期不协调时，独立保留小胜、对攻或闷平剧本。", "两个市场共同收敛到一致比分簇。", "市场维度不同，背离是有效风险提示。", ["赫尔辛基 1-0 暴露亚盘与大小球矛盾"], ["赫根 0-0 说明高大小球不能排除闷平"]),
        ("late-market-reversal", "临场盘口反转与回撤", ["handicap", "one_x_two", "total_goals"], ["late-market-reversal", "line-drop-water-fall", "line-drop-water-rise"], ["doubao-2026-07-28-text-a00075", "doubao-2026-07-28-text-a00632", "doubao-2026-07-28-text-a01159"], "登记锁定前最后阶段的档位回撤或价格反向，但要求时间、持续长度和多机构确认。", "反转吸收了新的高质量信息。", "反转是临场流动性和短时风险再平衡。", ["FC首尔升 0.75 后回撤 0.5"], ["单次回撤样本不足以建立必然下盘规则"]),
    ]
    output: list[Blueprint] = []
    for identity, title, markets, scenarios, atoms, purpose, a, b, supports, counters in specs:
        output.append(_bp(
            identity, title, "heuristic", "experimental", markets, ["prematch", "live", "postmatch"],
            ["经验假设", *scenarios], atoms, scenarios, purpose,
            ["经验规则不是事实", "样本量按独立 case_cluster 计算", "支持、反例和模糊样本全部保留"],
            ["完整盘口前置历史", "至少两个可比较时点", "基本面理论定位", "反例和失效条件"],
            ["登记无意图观察", "提出双向机制", "检查适用前提", "检索当前规则白名单内案例", "记录反例", "只调整权重不生成确定结论"],
            [("前提完整且多源同向", "仅提高假设权重", "不得写必然"), ("前置历史不同", "判不适用", "不得类比"), ("样本不足 30 独立案例", "保持 experimental", "不得晋级")],
            a, b,
            ["多机构同步", "档位持续时间", "后续回撤或站稳", "跨市场同向或背离"],
            ["数据质量规则优先", "事实与理论定位优先", "反例与不适用优先", "经验只作末级修正"],
            ["前置历史缺失", "只有赛后叙述", "无法定义目标和基线", "当前样本为 mixed/unknown chronology"],
            supports, counters,
            "由历史强表述降级为 experimental，补齐前提、反例、基线与晋级门槛。",
        ))
    return output


BLUEPRINTS.extend(_heuristic_blueprints())


FILE_NAMES = {
    "football-analysis-framework": "00-足球比赛分析基础框架.md",
    "market-settlement-rules": "concepts/市场与盘口结算规则.md",
    "data-provenance-time-boundary": "concepts/数据来源有效时间与防泄漏.md",
    "prematch-stage-positioning": "methods/基本面与阶段性实力定位.md",
    "theoretical-vs-actual-market": "methods/理论盘口与实际盘口比较.md",
    "market-timeline-cross-validation": "methods/盘口时序与多市场交叉验证.md",
    "dual-hypothesis-evidence": "methods/双向假设反证与失效条件.md",
    "layered-decision-confidence-pass": "methods/分层决策置信度与放弃分析.md",
    "goals-score-separation": "methods/总进球比分与让球分层.md",
    "prematch-checklist-v1": "checklists/赛前锁定检查清单.md",
    "data-quality-conflict-and-pass": "methods/数据质量冲突处理与放弃.md",
    "scenario-identification-and-case-retrieval": "methods/场景识别与历史案例检索.md",
    "live-update-and-postmatch-separation": "methods/临场更新与赛后复盘隔离.md",
    "handicap-inducement-resistance": "heuristics/阻盘诱盘与升降盘双向解释.md",
    "market-heat-chip-distribution": "heuristics/市场热度人气与筹码假设.md",
    "cross-related-same-pattern": "heuristics/交叉关联与同型盘.md",
    "water-threshold-operator-style": "heuristics/水位区间与机构风格.md",
    "operator-market-divergence": "heuristics/机构间盘口分歧.md",
    "asian-european-divergence": "heuristics/亚盘与欧赔背离.md",
    "handicap-total-goals-divergence": "heuristics/让球与总进球背离.md",
    "late-market-reversal": "heuristics/临场盘口反转与回撤.md",
}


POLICY_APPENDICES = {
    "football-analysis-framework": """
## 项目固定权重与执行顺序

- 使用 `asian-core-v1`：亚洲让球 60、欧赔 20、凯利 15、大小球 5。
- 每个维度只可使用 `-1/-0.5/0/0.5/1` 给候选方向评分，综合分为 `Σ(配置权重 × 维度评分)`。
- 缺失维度计零且不重分配权重；同源欧赔与凯利相关时，凯利有效权重减半。
- 固定顺序为：事实/基本面/理论盘预检 → 亚盘 → 欧赔 → 凯利 → 大小球 → 加权合成。
- 先形成胜平负方向，再推导净胜球和两类让球结果；盘口不能反向生成基本面或胜负事实。
- 非 `pass` 输出必须包含胜平负前二、亚洲让球前二、固定让球胜平负前二、总进球区间和恰好两个比分。
""",
    "market-timeline-cross-validation": """
## 三节点与降级处理

- 完整模式要求初盘、中盘、临盘至少三个可比节点；每个节点保存机构、采集时间、原始字符串、赔率格式和归一化值。
- 澳彩缺失或不足三个节点可进入 `degraded`，必须列出缺失项，置信度上限为 `0.69`。
- 盘口跨档优先于同档水位；盘口未跨档时，水位变化默认先解释为筹码和赔付微调。
- 欧赔优先对照澳彩、威廉、立博；多机构同向才提高独立确认强度。
""",
    "water-threshold-operator-style": """
## 归一化水位变化分级

本分级只适用于完成格式归一化后的香港盘水位，比较同机构、同市场、同盘口、相邻时间点的同一方向：

| 绝对变化 | 分类 | 动作 |
|---:|---|---|
| `<= 0.05` | normal | 视作正常流动，不改变主线 |
| `> 0.05` 且 `<= 0.12` | effective | 调整方向权重，不单独反转主线 |
| `> 0.12` 且 `< 0.15` | significant_warning | 强化风险提示并要求跨市场复核 |
| `>= 0.15` | strong_anomaly | 暂停原结论并重新评估 |

马来盘、印尼盘或格式未知时禁止套用。该阈值虽由项目所有者确认已外部验证，但逐场验证数据尚未登记，因此规则继续保持 `experimental`。
""",
    "asian-european-divergence": """
## 欧赔与凯利共振判定

- 亚盘、欧赔、凯利至少两个独立维度同向才可确认共振；同源欧赔与凯利只算一个独立来源，并对凯利有效权重减半。
- 亚盘水位下调、对应欧赔下调且凯利同步走低，可提高正向共振权重，但不得越过基本面和盘口档位。
- 对应方向凯利 `<=0.75` 记强收紧，`>=1.00` 记高风险；单一极端值不能定方向。
- 欧赔倾斜而凯利 `>=0.95` 时登记欧亚撕裂，降低极端赛果权重并保留反向假设。
""",
    "layered-decision-confidence-pass": """
## 数据模式与置信度硬约束

- `complete`：关键市场口径完整，可按固定权重输出四层结论。
- `degraded`：缺少澳彩、三节点或某辅助维度；缺失维度计零，不重分配权重，置信度不得超过 `0.69`。
- `pass`：只记录原因，不输出置信度、市场方向、总进球区间或比分。
- 每个方向均给前二排序，不使用“必中”或无次选的极端表述。
""",
    "live-update-and-postmatch-separation": """
## 临场三步与四类动作

1. 先看盘口是否跨档；跨档直接触发结论重估。
2. 再按归一化香港盘水位的 `0.05/0.12/0.15` 边界分级。
3. 最后核对战意、伤停等可验证基本面，排除无法证明的资金叙事。

正向延续只强化原主线；同档反向反弹通常削弱赢盘预期而不自动反转胜平负；宽幅震荡优先覆盖范围更广的次选；跨档极端异动必须暂停并重做欧亚凯利交叉验证。
""",
}


def _render_body(item: Blueprint) -> str:
    def bullets(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values)

    rows = "\n".join(f"| {condition} | {action} | {boundary} |" for condition, action, boundary in item.matrix)
    source_links = "\n".join(
        f"- source_atom_id: `{atom}`；claim_id: `claim-{atom}`" for atom in item.atoms
    )
    return f"""# {item.title}

## 目的和适用范围

{item.purpose}

## 术语

{bullets(item.terms)}

## 必需输入

{bullets(item.inputs)}

## 数据质量要求

- 所有事实必须记录来源、采集时间和时区；不得用盘口反推不存在的伤停或资金事实。
- 原始盘口、水位和机构文字保留原字符串；无法确认口径时登记冲突。
- 历史案例只有 `prematch_verified` 且时间边界可证明时才可能进入统计。

## 逐步执行过程

{chr(10).join(f'{index}. {value}' for index, value in enumerate(item.steps, start=1))}

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
{rows}

## 双向假设

- 假设 A：{item.hypothesis_a}
- 假设 B：{item.hypothesis_b}
- 两个假设都必须填写支持证据、反证和锁定前可观察的区分条件。

## 区分触发条件

{bullets(item.triggers)}

## 跨市场冲突优先级

{chr(10).join(f'{index}. {value}' for index, value in enumerate(item.conflicts, start=1))}

## 失效和 Pass 条件

{bullets(item.failures)}

满足任一关键失效条件且无法在截止前补齐时，主市场应为 `pass`；不得用降低措辞强度代替 pass。

## 支持案例

{bullets(item.supports)}

以上案例只说明规则的适用讨论，不自动计为合格证据。

## 反例

{bullets(item.counterexamples)}

## Source Atom 与声明引用

{source_links}

原子全文通过 `text-inventory.jsonl` 的字节区间回读；对应声明在 `claim-events.jsonl`，冲突结论在 `conflict-events.jsonl`。

## 证据快照

- 当前合格独立案例：0。
- 历史豆包案例统一为 `statistics_eligible: false`。
- 经验规则不得因单场命中晋级；支持、反例、模糊和不适用事件都必须保留。

## 版本变更说明

{item.change}

{POLICY_APPENDICES.get(item.document_id, '')}
"""


def scaffold_ruleset_proposal(
    root: Path,
    version: str,
    *,
    prepared_at: datetime,
    base_version: str | None = None,
) -> Path:
    if base_version is not None:
        document_contract(version)
        source = root / "knowledge/rulesets/football-analysis" / base_version
        if not source.is_dir():
            raise ValueError(f"基础已发布规则集不存在：football-analysis@{base_version}")
        source_manifest = yaml.safe_load((source / "manifest.yml").read_text(encoding="utf-8")) or {}
        if source_manifest.get("publication_status") != "published":
            raise ValueError("脚手架基础版本必须是已发布规则集")
        directory = root / "knowledge/rule-proposals/football-analysis" / version
        if directory.exists():
            raise ValueError(f"规则提案目录已存在：{directory}")
        shutil.copytree(source, directory, ignore=shutil.ignore_patterns("APPROVAL.yml"))
        evidence_path = root / "knowledge/evidence/rule-evidence.jsonl"
        evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        gate = yaml.safe_load(
            (root / EXTRACTION_RELATIVE / "release-gate.yml").read_text(encoding="utf-8")
        ) or {}
        required_ids, conditional_ids = document_contract(version)
        manifest = source_manifest | {
            "ruleset_version": version,
            "publication_status": "proposal",
            "effective_at": None,
            "required_document_ids": required_ids,
            "conditional_document_ids": conditional_ids,
            "source_coverage_sha256": gate["coverage_report_sha256"],
            "evidence_snapshot_sha256": evidence_hash,
            "proposal_prepared_at": prepared_at.isoformat(),
        }
        atomic_write_text(
            directory / "manifest.yml",
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        )
        for path in sorted(directory.glob("**/*.md")):
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                continue
            _, header, body = text.split("---", 2)
            metadata = yaml.safe_load(header) or {}
            metadata.update(
                {
                    "rule_version": version,
                    "effective_at": None,
                    "evidence_snapshot": {
                        "as_of": prepared_at.isoformat(),
                        "eligible_independent_cases": 0,
                        "support": 0,
                        "counterexample": 0,
                        "ambiguous": 0,
                        "ledger_sha256": evidence_hash,
                    },
                }
            )
            atomic_write_text(
                path,
                "---\n"
                + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, width=1000).rstrip()
                + "\n---"
                + body,
            )
        return directory
    if version != "1.1.0":
        raise ValueError("新版本脚手架必须通过 --base-version 指定已发布基础版本")
    extraction_errors = validate_extraction_state(root)
    if extraction_errors:
        raise ValueError("；".join(extraction_errors))
    gate_path = root / EXTRACTION_RELATIVE / "release-gate.yml"
    gate = yaml.safe_load(gate_path.read_text(encoding="utf-8")) or {}
    evidence_path = root / "knowledge/evidence/rule-evidence.jsonl"
    evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    directory = root / "knowledge/rule-proposals/football-analysis" / version
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 3,
        "ruleset_id": "football-analysis",
        "ruleset_version": version,
        "publication_status": "proposal",
        "effective_at": None,
        "entry_document_id": "football-analysis-framework",
        "required_document_ids": REQUIRED_RULE_IDS,
        "conditional_document_ids": CONDITIONAL_RULE_IDS,
        "source_coverage_sha256": gate["coverage_report_sha256"],
        "evidence_snapshot_sha256": evidence_hash,
        "proposal_prepared_at": prepared_at.isoformat(),
        "weight_model_id": "asian-core-v1",
        "market_data_contract_version": 1,
        "analysis_receipt_schema_version": 3,
        "review_receipt_schema_version": 2,
        "index_schema_version": 5,
        "retrieval_contract_version": 4,
    }
    atomic_write_text(directory / "manifest.yml", yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    for item in BLUEPRINTS:
        metadata = {
            "schema_version": 3,
            "document_id": item.document_id,
            "document_type": item.document_type,
            "title": item.title,
            "rule_version": version,
            "reliability": item.reliability,
            "status": "active",
            "effective_at": None,
            "evidence_level": "high" if item.reliability == "established" else "medium" if item.reliability == "supported" else "low",
            "evidence_snapshot": {
                "as_of": prepared_at.isoformat(),
                "eligible_independent_cases": 0,
                "support": 0,
                "counterexample": 0,
                "ambiguous": 0,
                "ledger_sha256": evidence_hash,
            },
            "source_atom_ids": item.atoms,
            "scenario_type_ids": item.scenarios,
            "promotion_reviewed_by": None,
            "markets": item.markets,
            "phases": item.phases,
            "tags": item.tags,
            "source_refs": [
                {
                    "kind": "local",
                    "locator": "knowledge/sources/doubao-2026-07-28/原始学习合集.md",
                    "anchor": "对应 source_atom_ids",
                }
            ],
            "index": True,
        }
        if item.document_id in POLICY_APPENDICES:
            metadata["source_refs"].append(
                {
                    "kind": "local",
                    "locator": "knowledge/validation/frameworks/asian-core-v1.md",
                    "anchor": item.document_id,
                }
            )
        if item.document_id == "market-settlement-rules":
            metadata["source_refs"].extend(
                [
                    {
                        "kind": "external",
                        "locator": "https://help.bet365.com/s/en/sportsrules/soccer/asian-handicap",
                        "title": "Asian Handicap - Football Rules",
                        "accessed_at": prepared_at.isoformat(),
                        "summary": "0、0/0.5、0.5、0.5/1、1 球盘口的官方结算说明。",
                    },
                    {
                        "kind": "external",
                        "locator": "https://support.betfair.com/app/answers/detail/a_id/6418/",
                        "title": "Exchange: What is Asian Handicap Betting?",
                        "accessed_at": prepared_at.isoformat(),
                        "summary": "整数盘退款与四分之一盘 50/50 拆分的官方说明。",
                    },
                ]
            )
        path = directory / FILE_NAMES[item.document_id]
        path.parent.mkdir(parents=True, exist_ok=True)
        front = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, width=1000).rstrip()
        atomic_write_text(path, f"---\n{front}\n---\n{_render_body(item).rstrip()}\n")
    return directory
