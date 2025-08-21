# app/classify.py
"""
AI/规则 混合的中图法（CLC）分类器。

用法（管道中已集成）：
    code, label, score, src = classify_clc(title, authors, summary, cip=None)

策略：
1) 若有 CIP 且看起来像 CLC（如 "TP391.1"），直接用其前缀映射到门类（T 工业技术 → "TP..." 保留原样）。
2) 否则做“弱监督规则分类”（关键词打分），给出 code/label/score。
3) 若本地部署了 LLM，可在此处接入（已留接口），用 LLM 对“标题+作者+摘要”进行判断，解析回 CLC 代码。
   - 为了避免无网络/无 key 失败，默认不开启；可按注释启用。
"""

from __future__ import annotations
import os
import re
from typing import Dict, List, Tuple, Optional

# ======= CLC 顶层门类（A-Z）与中文名 =======
CLC_LABELS: Dict[str, str] = {
    "A": "马克思主义、列宁主义、毛泽东思想、邓小平理论",
    "B": "哲学、宗教",
    "C": "社会科学总论",
    "D": "政治、法律",
    "E": "军事",
    "F": "经济",
    "G": "文化、科学、教育、体育",
    "H": "语言、文字",
    "I": "文学",
    "J": "艺术",
    "K": "历史、地理",
    "N": "自然科学总论",
    "O": "数理科学和化学",
    "P": "天文学、地球科学",
    "Q": "生物科学",
    "R": "医药、卫生",
    "S": "农业科学",
    "T": "工业技术",
    "U": "交通运输",
    "V": "航空、航天",
    "X": "环境科学、安全科学",
    "Z": "综合性图书",
}

# ======= 规则法：关键词 → 门类权重 =======
# 说明：这只是“弱监督”打分表，命中越多分越高；你可以按自己馆藏不断增补。
KEYWORDS: Dict[str, List[str]] = {
    "A": ["马克思", "列宁", "毛泽东", "邓小平", "社会主义理论"],
    "B": ["哲学", "形而上学", "伦理学", "宗教", "佛教", "基督教", "道教", "心灵"],
    "C": ["社会科学", "社会学", "调查研究方法", "统计年鉴", "社会问题", "公共管理"],
    "D": ["政治", "国际关系", "外交", "法学", "刑法", "民法", "行政法", "宪法"],
    "E": ["军事", "战争", "战略", "战术", "国防"],
    "F": ["经济", "金融", "管理学", "会计", "市场营销", "企业战略", "贸易", "宏观经济"],
    "G": ["教育学", "科普读物", "图书馆学", "文化研究", "体育", "博物馆"],
    "H": ["语言学", "语法", "汉语", "英语", "翻译", "词典", "语料库"],
    "I": ["文学", "小说", "诗歌", "散文", "戏剧", "文学史", "文论", "名著"],
    "J": ["艺术", "绘画", "雕塑", "摄影", "音乐", "电影", "戏曲", "设计"],
    "K": ["历史", "通史", "中国史", "世界史", "地理", "考古", "文明史"],
    "N": ["自然科学", "科研方法", "科学思想史"],
    "O": ["数学", "物理", "化学", "拓扑", "量子", "代数", "微积分"],
    "P": ["天文学", "地质", "地理信息", "气象", "地震", "地图学"],
    "Q": ["生物", "遗传", "细胞", "生态", "神经科学", "生物化学"],
    "R": ["医学", "临床", "解剖", "药学", "护理", "公共卫生", "疾病"],
    "S": ["农业", "作物", "畜牧", "林业", "渔业", "土壤"],
    "T": ["计算机", "算法", "软件工程", "人工智能", "深度学习", "网络", "电子", "机械", "材料", "工业", "自动化"],
    "U": ["交通", "铁路", "公路", "航运", "港口", "车辆工程"],
    "V": ["航空", "航天", "航天器", "火箭", "卫星"],
    "X": ["环境", "生态保护", "污染", "安全工程", "职业安全", "应急"],
    "Z": ["百科全书", "年鉴", "论文集", "综合", "工具书"],
}

# 正则：匹配看起来像 CLC/CIP 号，如 "TP391.1"、"H315.4"
_CLC_RE = re.compile(r"\b([A-Z])[A-Z0-9]{0,2}(?:\.\d+)?", flags=re.I)
_CIP_CLC_RE = re.compile(r"\b([A-Z])([A-Z0-9]{0,2})(?:\.\d+)?", flags=re.I)


def _normalize(s: Optional[str]) -> str:
    s = (s or "").strip()
    # 统一空白/书名号等；避免影响关键词命中
    s = s.replace("《", " ").replace("》", " ").replace("【", " ").replace("】", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def _score_by_keywords(text: str) -> Dict[str, float]:
    text_lc = text.lower()
    scores: Dict[str, float] = {k: 0.0 for k in CLC_LABELS.keys()}
    for code, kws in KEYWORDS.items():
        for kw in kws:
            if kw and kw.lower() in text_lc:
                # 每次命中加 1.0；科教/技术类再稍微加成
                base = 1.2 if code in ("T", "O", "Q", "R", "P", "S", "X") else 1.0
                scores[code] += base
    return scores


def _pick_best(scores: Dict[str, float]) -> Tuple[str, float]:
    # 返回分数最高的 (code, score)
    code = max(scores, key=lambda k: scores[k]) if scores else "Z"
    return code, scores.get(code, 0.0)


def _label(code: str) -> str:
    return CLC_LABELS.get(code.upper(), "未知")


def _from_cip(cip: Optional[str]) -> Optional[str]:
    """
    若给了 CIP/CLC 字段（如 "TP391.1"），直接取其门类前缀（例如 "TP" / "T"）。
    优先返回最长可见的前缀（保留细分），否则至少返回门类字母。
    """
    if not cip:
        return None
    m = _CIP_CLC_RE.search(cip.upper())
    if not m:
        return None
    # 返回如 "TP391.1" 的前两位字母数字前缀，保持更多信息；否则至少返回 "T"
    head = m.group(0)
    # 规范化：去掉多余空白
    return head


def classify_rule_based(title: str, authors: List[str] | None, summary: str | None) -> Tuple[str, str, float, str]:
    """
    规则法分类：返回 (code, label, confidence, source)
    """
    t = _normalize(title)
    a = _normalize(",".join(authors or []))
    s = _normalize(summary or "")

    blob = " ".join([t, a, s]).strip()
    if not blob:
        return "Z", _label("Z"), 0.0, "rule"

    scores = _score_by_keywords(blob)
    code, score = _pick_best(scores)

    # 粗略把分数映射成置信度（0.5~0.95）
    # 命中>=3次关键词 ~ 0.9；命中1次 ~ 0.55；未命中 ~ 0.5/默认 Z
    if score <= 0:
        conf = 0.5 if code == "Z" else 0.55
    elif score < 2:
        conf = 0.65
    elif score < 4:
        conf = 0.8
    else:
        conf = 0.92

    return code, _label(code), conf, "rule"


# ======= 可选：LLM 分类接口（默认关闭，避免环境依赖） =======
_ENABLE_LLM = True  # 如需启用，改成 True 并配置 API Key

def classify_llm(title: str, authors: List[str] | None, summary: str | None) -> Optional[Tuple[str, str, float, str]]:
    """
    可选的 LLM 分类器：返回 (code, label, confidence, source)
    注意：为保持通用性，这里仅提供一个参考实现（OpenAI）。
    默认关闭，避免无网络/无 Key 报错。
    """
    if not _ENABLE_LLM:
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import openai  # pip install openai>=1.0
        client = openai.OpenAI(api_key=api_key)  # type: ignore
        prompt = f"""
你是图书馆编目员，请根据《中图法》给出图书门类代码（仅给出代码，不要解释）。
候选门类：{", ".join([f"{k}:{v}" for k,v in CLC_LABELS.items()])}

标题: {title}
作者: {", ".join(authors or [])}
摘要: {summary or ""}

仅输出一个代码，例如：T 或 TP 或 TP3；若无法判断请输出 Z。
"""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",  # 或任意你可用的模型
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip().upper()
        m = _CLC_RE.search(text)
        if not m:
            return None
        code = m.group(0)
        # 置信度先给一个较高基线，后续可基于 logprobs/对话结构再细化
        return code, _label(code[0]), 0.85, "llm"
    except Exception:
        return None


def classify_clc(
    title: str,
    authors: List[str] | None,
    summary: str | None,
    cip: Optional[str] = None,
) -> Tuple[str, str, float, str]:
    """
    统一入口：
    1) CIP/CLC 号（若可解析） → 直接返回，source="cip"
    2) LLM（可选，开启时） → 若输出有效代码 → source="llm"
    3) 规则法 → source="rule"
    """
    # 1) CIP 优先
    code_from_cip = _from_cip(cip)
    if code_from_cip:
        code = code_from_cip
        # 门类取首字母映射中文名
        return code, _label(code[0]), 0.95, "cip"

    # 2) LLM（可选）
    llm_res = classify_llm(title, authors, summary)
    if llm_res:
        return llm_res

    # 3) 规则法
    return classify_rule_based(title, authors, summary)
