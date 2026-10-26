"""
Build Word versions (URA house format) of the two Markdown guides.

What: docs/CTRP_How_It_Works.md   -> docs/CTRP_How_It_Works.docx
      docs/CODE_WALKTHROUGH.md     -> docs/CTRP_Code_Walkthrough.docx
Why:  the Markdown files are the source (easy to edit and review in git); reviewers and officers
      read Word. Rebuilding from the Markdown keeps the two from drifting apart.

    python main.py docs        (or: python docs/builders/build_markdown_docs.py)

The Markdown is read with a few simple rules, matching how the two files are written:
  '# '  the title (cover page)        '## ' Heading 1    '### ' Heading 2    '#### ' Heading 3
  '|'   table rows (the first row is the header; the caption is the heading above it)
  '```' a code box                    '- ' bullets       '1. ' numbered items
  indented lines continue the bullet or numbered item above; '---' lines are skipped.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # docs/builders
ROOT = HERE.parents[1]                          # the project folder
sys.path.insert(0, str(HERE))
from docx.shared import Pt  # noqa: E402
from ura_doc import UraDoc  # noqa: E402

TEMPLATE = HERE / 'ura_template.docx'
LOGO = HERE / 'ura_logo.png'
DATE = 'October 2026'
DOCS = [
    (ROOT / 'docs' / 'CTRP_How_It_Works.md', ROOT / 'docs' / 'CTRP_How_It_Works.docx',
     'How the Model Works: a Plain-Language and Technical Explanation'),
    (ROOT / 'docs' / 'CODE_WALKTHROUGH.md', ROOT / 'docs' / 'CTRP_Code_Walkthrough.docx',
     'Code Walkthrough: Track A and Track B'),
]


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def blocks(text):
    """The Markdown as a list of (kind, content) blocks, in order."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s or s == '---':
            i += 1
        elif s.startswith('```'):
            j = i + 1
            while not lines[j].strip().startswith('```'):
                j += 1
            out.append(('code', lines[i + 1:j]))
            i = j + 1
        elif m := re.match(r'(#{1,4}) (.*)', s):
            out.append((f'h{len(m.group(1))}', m.group(2)))
            i += 1
        elif s.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                if not re.fullmatch(r'\|[\s:|-]+\|', lines[i].strip()):     # skip the |---|---| line
                    rows.append(_cells(lines[i]))
                i += 1
            out.append(('table', rows))
        elif re.match(r'(- |\d+\. )', s):
            kind = 'bullets' if s.startswith('- ') else 'numbered'
            items = []
            while i < len(lines) and lines[i].strip():
                t = lines[i].strip()
                if re.match(r'(- |\d+\. )', t) and not lines[i].startswith(' '):
                    items.append(re.sub(r'^(- |\d+\. )', '', t))
                else:
                    items[-1] += ' ' + t                                  # continuation line
                i += 1
            out.append((kind, items))
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r'(#|\||```|- |\d+\. )', lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            out.append(('p', ' '.join(para)))
    return out


def build(src, dst, subtitle):
    parts = blocks(src.read_text(encoding='utf-8'))
    title = next(c for k, c in parts if k == 'h1')
    d = UraDoc(TEMPLATE, logo=LOGO)
    d.cover(['CUSTOMS TAXPAYER RISK PROFILING MODEL'], subtitle, f'VERSION 0.1, {DATE.upper()} (DRAFT)')
    d.front_heading('Document Control & Authority')
    d.table('Document Information', ['Field', 'Details'], [
        ['Document Title', f'Customs Taxpayer Risk Profiling Model: {title}'],
        ['Version', '0.1 (draft)'],
        ['Classification', 'Confidential'],
        ['Owner', 'Data Science Section, Data, Innovations and Projects Division, ITID'],
        ['Describes', 'Model version 1.0.0-dev5 and the ctrp project'],
        ['Source', f'{src.relative_to(ROOT).as_posix()} (edit the Markdown, then rebuild with python main.py docs)'],
    ], [4, 13])
    d.contents()

    # the body: its own section with Arabic page numbers (as UraDoc.part does, without a divider page)
    d.sec = d._new_section()
    d._footer(d.sec, 'decimal')
    d.in_body = True
    heading = title
    first_h2 = True
    for kind, c in parts:
        if kind == 'h1':
            continue
        if kind == 'h2':
            if not first_h2:
                d.page_break()
            first_h2 = False
            d.h1(c)
            heading = c
        elif kind in ('h3', 'h4'):
            (d.h2 if kind == 'h3' else d.h3)(c)
            heading = c if kind == 'h3' else heading
        elif kind == 'p':
            d.p(c)
        elif kind == 'bullets':
            d.bullets(c)
        elif kind == 'numbered':
            d.numbered(c)
        elif kind == 'code':
            d.code(c)
            if max(map(len, c)) > 85:                 # wide lines: smaller type so they do not wrap
                for para in d.d.tables[-1].cell(0, 0).paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(7)
        elif kind == 'table':
            header, rows = c[0], c[1:]
            widths = [max(3, min(14, max(len(r[j]) if j < len(r) else 0 for r in c))) for j in range(len(header))]
            d.table(re.sub(r'^[\d.]+\s*', '', heading).strip(), header, rows, widths,
                    size=8 if len(header) > 5 else 9)
    d.save(dst)
    print(f'written {dst.relative_to(ROOT)}')


if __name__ == '__main__':
    for src, dst, subtitle in DOCS:
        build(src, dst, subtitle)
