#!/usr/bin/env python3
"""
[V12.5] paper-qa 集成层。

设计决策:「仅用 paper-qa 的 PDF 解析器 (readers.py),不用其 LLM/embedding 层」

保留 Sci-Bot 三大原创:
  1. section_type 优先 limitations 检索过滤
  2. 第一性原理 5 项追问范式 (What/How/Why/Where/Predict)
  3. V11.5 双门筛选预处理上游

paper-qa 贡献:
  - parse_pdf_to_pages: 比 pymupdf 更鲁棒的 PDF 文本提取
    (内置处理多列布局、旋转页面、嵌入字体乱码)
  - 每页结构化输出 (page_num -> (text, media))
  - 引用追踪元数据 (PageRange 格式: pages X-Y)

LLM 调用: 全部走 pplx llm extract (不调 OpenAI)
ChromaDB + sentence-transformers: 完整保留
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 内部 paper-qa 导入 (仅 readers.py,不触发 LLM 初始化)
# --------------------------------------------------------------------------

def _get_pqa_parser():
    """延迟导入 paper-qa 的 PDF 解析函数,避免启动时联网初始化。"""
    try:
        from paperqa.settings import get_default_pdf_parser
        from paperqa.readers import read_doc
        from paperqa.types import Doc
        return get_default_pdf_parser, read_doc, Doc
    except ImportError as e:
        raise ImportError(
            "paper-qa not installed. Run: pip install paper-qa>=2026.3"
        ) from e


# --------------------------------------------------------------------------
# 章节分类器 (与 parse_pdf.py 保持一致,用于 section_type 标注)
# --------------------------------------------------------------------------

SECTION_MAP = [
    ('abstract',        re.compile(r'^abstract\s*$', re.I)),
    ('introduction',    re.compile(r'^(?:\d+\.?\s+)?introduction\s*$', re.I)),
    ('related_work',    re.compile(r'^(?:\d+\.?\s+)?related\s+work\s*$', re.I)),
    ('background',      re.compile(r'^(?:\d+\.?\s+)?background\s*$', re.I)),
    ('methods',         re.compile(
        r'^(?:\d+\.?\s+)?(?:methods?|methodology|approach|'
        r'materials?\s+and\s+methods?|experimental\s+(?:setup|methods?)|'
        r'experimental\s+section|materials\s+&\s+methods?)\s*$', re.I)),
    ('results',         re.compile(
        r'^(?:\d+\.?\s+)?(?:results?\s*(?:and\s+)?(?:analysis)?'
        r'|experiments?\s*(?:and\s+analysis)?'
        r'|evaluation|performance|numerical\s+results?)\s*$', re.I)),
    ('discussion',      re.compile(
        r'^(?:\d+\.?\s+)?(?:discussion|results\s+and\s+discussion'
        r'|discussion\s+and\s+conclusions?)\s*$', re.I)),
    ('limitations',     re.compile(
        r'^(?:\d+\.?\s+)?limitations?\s*(?:and\s+future\s+work)?\s*$', re.I)),
    ('future_work',     re.compile(
        r'^(?:\d+\.?\s+)?future\s+(?:work|directions?|research)\s*$', re.I)),
    ('conclusion',      re.compile(
        r'^(?:\d+\.?\s+)?conclusions?\s*(?:and\s+future\s+work)?\s*$', re.I)),
    ('appendix',        re.compile(r'^appendix\s*', re.I)),
    ('references',      re.compile(r'^references?\s*$', re.I)),
    ('acknowledgments', re.compile(r'^acknowledgm?ents?\s*$', re.I)),
]

PRIORITY_SECTIONS = {'limitations', 'discussion', 'future_work', 'conclusion'}
SKIP_SECTIONS = {'references', 'acknowledgments', 'appendix'}

LIMITATION_SENTENCE = re.compile(
    r'[^.!?]*\b(?:limitation|however|cannot|can\'t|fail|challenge|difficult|'
    r'unable|prohibit|prevent|restrict|constraint|barrier|bottleneck|drawback|'
    r'shortcoming|inadequate|insufficient|poor performance|does not|did not|'
    r'not able)\b[^.!?]*[.!?]',
    re.I
)


def classify_heading(text: str) -> Optional[str]:
    """把章节标题文字映射到 section_type。"""
    clean = text.strip()
    for sec, pat in SECTION_MAP:
        if pat.match(clean):
            return sec
    return None


def extract_sections_from_text(full_text: str) -> dict[str, str]:
    """
    从 paper-qa 输出的全文中按行扫描,识别章节边界,返回 section_type -> text 映射。
    与 parse_pdf.py 的 raw_text_section_split 逻辑一致,确保双引擎兼容。
    """
    sections: dict[str, list[str]] = {'preamble': []}
    current = 'preamble'

    for line in full_text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        heading = classify_heading(stripped) if len(stripped) < 80 else None
        if heading:
            current = heading
            if current not in sections:
                sections[current] = []
        else:
            if current == 'references':
                continue
            if current not in sections:
                sections[current] = []
            sections[current].append(line)

    result = {sec: '\n'.join(lines).strip() for sec, lines in sections.items()}

    # 后处理: 如果没有显式 limitations 节,从 discussion/conclusion 自动抽取限制句
    if len(result.get('limitations', '')) < 50:
        src = result.get('discussion', '') + ' ' + result.get('conclusion', '')
        lim_sentences = LIMITATION_SENTENCE.findall(src)
        if lim_sentences:
            result['limitations'] = '[Auto-extracted] ' + ' '.join(lim_sentences[:15])

    return result


# --------------------------------------------------------------------------
# EchelonPaperQA: 核心集成类
# --------------------------------------------------------------------------

class EchelonPaperQA:
    """
    Sci-Bot 增强版 paper-qa 集成层。

    职责:
      1. 调用 paper-qa 的 parse_pdf_to_pages 提取更鲁棒的 PDF 文本
      2. 用 Sci-Bot 自有逻辑识别 section_type(保留原创 1)
      3. 返回带 section_type 元数据的 chunks,供 ChromaDB 入库

    不职责:
      - 不调用任何 LLM (OpenAI / pplx)
      - 不持有 embedding (由 build_index.py 的 sentence-transformers 负责)
      - 不替换 ChromaDB (完整保留)
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._parse_pdf_fn = None
        self._read_doc_fn = None
        self._Doc = None
        logger.info("[V12.5] EchelonPaperQA 初始化 (PDF解析模式,无LLM)")

    def _ensure_parser(self):
        if self._parse_pdf_fn is None:
            get_default_pdf_parser, read_doc, Doc = _get_pqa_parser()
            self._parse_pdf_fn = get_default_pdf_parser()
            self._read_doc_fn = read_doc
            self._Doc = Doc

    async def parse_pdf_async(
        self,
        pdf_path: str,
        paper_id: str = '',
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        用 paper-qa 解析 PDF,返回带 sections + chunks 的 dict。

        返回结构:
          {
            'paper_id': str,
            'title': str,               # 从首页提取
            'full_text': str,           # 全文拼接
            'sections': dict,           # section_type -> text
            'pages': dict,              # page_num -> text
            'page_count': int,
            'has_limitations': bool,
            'has_discussion': bool,
            'source': 'paperqa',
          }
        """
        self._ensure_parser()
        metadata = metadata or {}

        doc = self._Doc(
            docname=paper_id or Path(pdf_path).stem,
            dockey=paper_id or Path(pdf_path).stem,
            citation=metadata.get('citation', f'Paper {paper_id}'),
        )

        try:
            parsed = await self._read_doc_fn(
                pdf_path,
                doc,
                parsed_text_only=True,
                parse_pdf=self._parse_pdf_fn,
            )
        except Exception as e:
            logger.warning(f"[V12.5] paper-qa 解析失败 {pdf_path}: {e}, 将由 pymupdf 兜底")
            return {
                'paper_id': paper_id,
                'error': str(e),
                'source': 'paperqa_failed',
            }

        content = parsed.content  # page_num -> (text, media_list) or str
        pages: dict[int, str] = {}

        if isinstance(content, dict):
            for page_num in sorted(content.keys()):
                val = content[page_num]
                if isinstance(val, tuple):
                    pages[page_num] = val[0]  # (text, media)
                else:
                    pages[page_num] = str(val)
        elif isinstance(content, str):
            pages = {1: content}

        full_text = '\n'.join(pages[p] for p in sorted(pages))

        # 提取 title (首页首行较长文本)
        title = _extract_title_from_first_page(pages.get(1, ''))
        if not title:
            title = metadata.get('title', paper_id)

        # 章节识别 (Sci-Bot 原创)
        sections = extract_sections_from_text(full_text)

        has_limitations = len(sections.get('limitations', '')) > 50
        has_discussion = len(sections.get('discussion', '')) > 50

        return {
            'paper_id': paper_id,
            'title': title,
            'full_text': full_text[:80000],   # 限制内存
            'sections': sections,
            'pages': pages,
            'page_count': len(pages),
            'has_limitations': has_limitations,
            'has_discussion': has_discussion,
            'source': 'paperqa',
            'metadata': metadata,
        }

    def parse_pdf(self, pdf_path: str, paper_id: str = '', metadata: Optional[dict] = None) -> dict:
        """同步包装,供非 async 代码调用。"""
        return asyncio.run(self.parse_pdf_async(pdf_path, paper_id, metadata))

    async def add_paper(
        self,
        pdf_path: str,
        paper_id: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        解析 PDF,返回包含 sections 的结构化 dict。
        供 build_index.py 调用: 拿到 sections 后自行入 ChromaDB。
        """
        return await self.parse_pdf_async(pdf_path, paper_id, metadata)

    async def query_with_section_priority(
        self,
        question: str,
        top_k: int = 8,
        priority_sections: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        [Sci-Bot 原创 #1] section_type 优先 limitations 检索。

        注意:实际向量检索由 scibot_query.py 的 ChromaDB 负责。
        此方法是为外部调用者提供一致接口:
          - 当问题含卡点关键词时,priority_sections 自动设为 limitations/discussion 等
          - 返回格式与 scibot_query.query() 一致

        实现:代理到 scibot_query.query(),保留所有原创过滤逻辑。
        """
        from scibot.scibot_query import query, should_filter_by_limitation, PRIORITY_SECTIONS as PQ_PRIO

        # 自动检测是否需要限制章节优先
        if priority_sections is None and should_filter_by_limitation(question):
            priority_sections = list(PQ_PRIO)

        # 代理到 scibot_query.query()
        chunks = query(question, top_k=top_k)

        # 如果调用者明确指定了 priority_sections,做二次过滤
        if priority_sections:
            prio = [c for c in chunks if c['section_type'] in priority_sections]
            non_prio = [c for c in chunks if c['section_type'] not in priority_sections]
            chunks = (prio + non_prio)[:top_k]

        return chunks


# --------------------------------------------------------------------------
# 辅助函数
# --------------------------------------------------------------------------

def _extract_title_from_first_page(text: str) -> str:
    """从首页文本提取标题:取最长的短行(通常是大字号标题)。"""
    if not text:
        return ''
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    candidates = [l for l in lines[:20] if 10 < len(l) < 200]
    if not candidates:
        return ''
    # 启发式:标题往往是前几行中较长的非引用行
    return candidates[0]


def get_pqa_full_text(pdf_path: str) -> Optional[str]:
    """
    便捷函数:用 paper-qa 解析器取全文文本(同步)。
    供 build_index.py 在解析失败兜底时使用。
    """
    pqa = EchelonPaperQA()
    result = pqa.parse_pdf(pdf_path, paper_id=Path(pdf_path).stem)
    if 'error' in result:
        return None
    return result.get('full_text', '')
