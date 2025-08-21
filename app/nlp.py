# app/nlp.py
import re
from typing import List, Tuple, Optional, Any, Dict

from .utils import normalize_whitespace

# ====== 规则清洗用常量 ======
BRACKETS = r'[【\[\(（].*?[】\]\)）]'
AUTHOR_HINTS = r'(著|编|译|主编|等)$'

# ====== NER 运行时句柄（按需加载） ======
_NER_BACKEND = None  # 可能是 "hanlp" / "ltp" / "spacy" / None
_NER_MODEL = None    # 实际的模型/对象
_TRIED_LOAD = False  # 防止重复尝试加载


def _try_load_ner():
    """
    尝试按优先级加载一个可用的中文 NER 后端：
    1) HanLP
    2) LTP
    3) spaCy (推荐 zh_core_web_trf；zh_core_web_sm 无 NER)
    加载失败则保持 None，后续自动使用规则法。
    """
    global _NER_BACKEND, _NER_MODEL, _TRIED_LOAD
    if _TRIED_LOAD:
        return
    _TRIED_LOAD = True

    # --- 1) HanLP ---
    try:
        import hanlp  # type: ignore
        # 这里不强行指定具体模型名称，交由 hanlp.load 智能选择；
        # 如果本地无模型，HanLP 可能会尝试联网下载，外部环境若不允许，会抛异常，我们捕获即可。
        _NER_MODEL = hanlp.load(hanlp.pretrained.ner.MSRA_NER_BERT_BASE_ZH)  # 常见中文 NER
        _NER_BACKEND = "hanlp"
        return
    except Exception:
        _NER_BACKEND = None
        _NER_MODEL = None

    # --- 2) LTP ---
    try:
        from ltp import LTP  # type: ignore
        _NER_MODEL = LTP()   # 默认小模型；若无本地权重它可能联网下载
        _NER_BACKEND = "ltp"
        return
    except Exception:
        _NER_BACKEND = None
        _NER_MODEL = None

    # --- 3) spaCy ---
    try:
        import spacy  # type: ignore
        # 优先中文的 Transformer NER；若未安装会抛错
        try:
            _NER_MODEL = spacy.load("zh_core_web_trf")
            _NER_BACKEND = "spacy"
            return
        except Exception:
            # 退而求其次：尝试其它已装的中文模型（提醒：多数 zh_core_web_sm 没有 NER）
            # 若无 NER，后续调用也会返回空结果，我们再回退规则。
            _NER_MODEL = spacy.load("zh_core_web_sm")
            _NER_BACKEND = "spacy"
            return
    except Exception:
        _NER_BACKEND = None
        _NER_MODEL = None


def clean_line(s: str) -> str:
    """
    原有清洗 + 少量增强：
    - 去掉中文/英文括号内容
    - 去掉行首序号（1. / 1、 / 1) / 1- / 1: 等）
    - 将 + / 、 / 全角空格 / 制表符 等统一为单空格
    - 折叠多空格
    """
    s = re.sub(BRACKETS, '', s or '')
    s = re.sub(r'^\s*\d+[\.\、\)\-：:]\s*', '', s)          # "1. " / "1、" / "1) " / "1- " / "1:" 等
    s = re.sub(r'^\s*\d+\s*\.\s*', '', s)                   # "4.  文明简史" 变体
    s = s.replace('+', ' ').replace('/', ' ').replace('、', ' ')
    s = s.replace('　', ' ').replace('\t', ' ')
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s


def _dedup_authors(authors: List[str]) -> List[str]:
    out, seen = [], set()
    for a in authors:
        a = normalize_whitespace(a or "")
        if not a:
            continue
        if a.endswith(("著", "编", "译", "主编")):
            a = a[:-1]
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _heuristic_title_author(s: str) -> Tuple[str, List[str]]:
    """
    原有启发式：在 NER 不可用或置信度不足时的回退。
    """
    s = clean_line(s)

    # 末尾“某某著/编/译/主编/等”
    m = re.search(r'^(.*?)[\s:：\-—·]+([^\d]{1,30})' + AUTHOR_HINTS, s)
    if m:
        title = m.group(1).strip(' -—·:：')
        author = m.group(2).strip()
        return title, _dedup_authors([author])

    # 括号里的人名（备用）
    m = re.search(r'^(.*?)[\s\(（](.*?)[\)）]$', s)
    if m and len(m.group(2)) <= 12:
        return m.group(1), _dedup_authors([m.group(2)])

    # 仅以空格分裂，尝试最后一段是作者
    parts = s.split()
    if len(parts) >= 2 and len(parts[-1]) <= 12:
        return ' '.join(parts[:-1]), _dedup_authors([parts[-1]])

    # 实在不行就全部归入标题
    return s, []


def _extract_with_hanlp(text: str) -> Dict[str, Any]:
    # HanLP 返回 [{'text':..., 'label': 'NR/NS/NT/...'}] 或不同版本结构
    result = {"authors": [], "title": None, "confidence": 0.0}
    try:
        pred = _NER_MODEL(text)
        # HanLP 的标签体系很多，常见人名是 NR；没有“书名”专类，标题依然走规则兜底
        persons = []
        for sent in pred:
            # 兼容多种输出格式
            for span in sent:
                word = span[0] if isinstance(span, (list, tuple)) else getattr(span, "text", "")
                label = span[1] if isinstance(span, (list, tuple)) else getattr(span, "label", "")
                if str(label).upper().startswith("NR"):  # NR 人名
                    persons.append(word)
        result["authors"] = _dedup_authors(persons)
        # 标题仍依赖规则（或其它后端能产出“作品名”的情况下再覆盖）
        # 简单置信度：有人名→0.7，否则 0
        result["confidence"] = 0.7 if result["authors"] else 0.0
    except Exception:
        pass
    return result


def _extract_with_ltp(text: str) -> Dict[str, Any]:
    # LTP: seg, ner 等；ner 输出类似 [ [ (start,end,label), ... ] ]
    result = {"authors": [], "title": None, "confidence": 0.0}
    try:
        # pip install ltp
        # _NER_MODEL 是 LTP 实例
        seg, hidden = _NER_MODEL.seg([text])
        ner = _NER_MODEL.ner(hidden)
        words = seg[0] if seg else []
        persons = []
        if ner and ner[0]:
            for (s, e, label) in ner[0]:
                token = "".join(words[s:e+1])
                if str(label).upper().startswith("NH"):  # LTP 的人名通常是 NH
                    persons.append(token)
        result["authors"] = _dedup_authors(persons)
        result["confidence"] = 0.7 if result["authors"] else 0.0
    except Exception:
        pass
    return result


def _extract_with_spacy(text: str) -> Dict[str, Any]:
    # spaCy 中文：zh_core_web_trf 有 NER；常见标签 PERSON（人名）、WORK_OF_ART（作品）
    result = {"authors": [], "title": None, "confidence": 0.0}
    try:
        doc = _NER_MODEL(text)
        persons, works = [], []
        for ent in getattr(doc, "ents", []):
            label = ent.label_.upper()
            if label in ("PERSON", "PER"):
                persons.append(ent.text)
            if label in ("WORK_OF_ART", "PRODUCT", "TITLE"):
                works.append(ent.text)
        result["authors"] = _dedup_authors(persons)
        # 若有作品类实体，取最长的一个当候选标题
        if works:
            result["title"] = max(works, key=len)
        # 置信度粗略打分：有人名 + 可能有作品名
        score = 0.0
        if result["authors"]:
            score += 0.6
        if result["title"]:
            score += 0.3
        result["confidence"] = score
    except Exception:
        pass
    return result


def _extract_title_author_via_ner(s: str) -> Dict[str, Any]:
    """
    统一对外的 NER 抽取函数：
    返回 {'title': 可选, 'authors': [...], 'confidence': 0..1}
    """
    text = clean_line(s)
    if not text:
        return {"title": None, "authors": [], "confidence": 0.0}

    _try_load_ner()
    if not _NER_BACKEND or not _NER_MODEL:
        return {"title": None, "authors": [], "confidence": 0.0}

    if _NER_BACKEND == "hanlp":
        return _extract_with_hanlp(text)
    if _NER_BACKEND == "ltp":
        return _extract_with_ltp(text)
    if _NER_BACKEND == "spacy":
        return _extract_with_spacy(text)

    return {"title": None, "authors": [], "confidence": 0.0}


def split_title_author(s: str) -> Tuple[str, List[str]]:
    """
    新逻辑：
    1) 先跑 NER：如果抽到作者（PERSON 等）并且标题候选可信，则优先用 NER。
       - 仅抽到作者：作者用 NER，标题用规则兜底。
       - 抽到作品名：作品名与规则标题比一比，取更合理者（更长/更像标题的）。
    2) 若 NER 不可用或置信度不足，回退到旧规则。
    """
    s = normalize_whitespace(s or "")
    if not s:
        return "", []

    # 先规则粗清洗，给 NER/规则都用
    cleaned = clean_line(s)

    # === 1) NER 抽取 ===
    ner = _extract_title_author_via_ner(cleaned)
    ner_title = (ner.get("title") or "").strip(" 《》[]（）()")
    ner_authors = _dedup_authors(ner.get("authors") or [])
    ner_conf = float(ner.get("confidence") or 0.0)

    # === 2) 规则回退/对照 ===
    rule_title, rule_authors = _heuristic_title_author(cleaned)
    rule_title = rule_title.strip(" 《》[]（）()")
    rule_authors = _dedup_authors(rule_authors)

    # 策略：
    # - 若 NER 发现了作者且置信度≥0.6，则作者优先用 NER；
    # - 标题选择：若 NER 给到作品名且长度 ≥ 2，则在 NER / 规则二者中取“更像标题”的一个：
    #     * 更长且不含“著/编/译”等尾缀；
    #     * 或者包含明显的标题特征（比如“简史”、“研究”、“世界”、“文明”等）。
    # - 否则完全回退规则。
    if ner_authors and ner_conf >= 0.6:
        authors = ner_authors
        # 选择标题
        candidates = [t for t in [ner_title, rule_title] if t]
        if candidates:
            def _title_score(t: str) -> int:
                t = t.strip()
                score = len(t)
                if re.search(r'(著|编|译|主编)$', t):
                    score -= 2
                if re.search(r'(研究|简史|教程|导论|原理|方法|文明|世界|社会|历史|算法|原本|文学|文化)', t):
                    score += 2
                return score
            best = max(candidates, key=_title_score)
            title = best
        else:
            title = rule_title or ner_title
        return title or cleaned, authors

    # NER 不足以信任 → 返回规则结果
    return rule_title, rule_authors
