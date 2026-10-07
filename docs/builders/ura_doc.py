"""
Build Word documents in the URA house format.

What: a small helper that writes a .docx with the house layout: cover page, Document Control and
      Authority, Distribution, Table of Contents, List of Tables, List of Figures, List of Acronyms,
      then a PART-based body (each PART on its own divider page with a short summary), Roman page
      numbers on the front matter and Arabic numbers on the body, and numbered captions
      ("Table n:" above every table, "Figure n:" below every figure).
Why:  every model document then looks the same and nobody re-formats by hand.

The fonts, heading colours and caption style are taken from a reference URA document (the
template), so the output matches it.

    doc = UraDoc('template.docx', logo='logo.png')
    doc.cover(...); doc.front_matter(...); doc.part('PART 1: ...', 'summary'); doc.h2('1.1 ...')
    doc.p('text with **bold**'); doc.table('caption', header, rows); doc.save('out.docx')

Fields (contents, lists of tables and figures, caption numbers) refresh when the file is opened in
Word: accept the prompt "update the fields", or press Ctrl+A then F9.
"""
import copy
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BLUE = RGBColor(0x2F, 0x54, 0x96)
HEAD_FILL = 'D9E2F3'
BORDER = '8EAADB'
NOTE_FILL = 'F2F6FC'
FONT = 'Bookman Old Style'


def _set_cell_fill(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_fill)
    tcPr.append(shd)


def _table_borders(table, color=BORDER):
    tblPr = table._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), '4')
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), color)
        borders.append(el)
    tblPr.append(borders)


def _field(paragraph, instr, shown=''):
    """Insert a Word field (TOC, SEQ, PAGE) with a cached result so it reads well before updating."""
    r = paragraph.add_run()
    b = OxmlElement('w:fldChar'); b.set(qn('w:fldCharType'), 'begin'); r._r.append(b)
    r2 = paragraph.add_run()
    it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve'); it.text = f' {instr} '; r2._r.append(it)
    r3 = paragraph.add_run()
    s = OxmlElement('w:fldChar'); s.set(qn('w:fldCharType'), 'separate'); r3._r.append(s)
    r4 = paragraph.add_run(shown)
    r5 = paragraph.add_run()
    e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'end'); r5._r.append(e)
    return r4


def _rich(paragraph, text, size=None, color=None):
    """Write text, turning **bold** and `code` into formatted runs."""
    for part in re.split(r'(\*\*[^*]+\*\*|`[^`]+`)', text):
        if not part:
            continue
        if part.startswith('**'):
            run = paragraph.add_run(part[2:-2]); run.bold = True
        elif part.startswith('`'):
            run = paragraph.add_run(part[1:-1]); run.font.name = 'Consolas'
            run._r.get_or_add_rPr().get_or_add_rFonts().set(qn('w:hAnsi'), 'Consolas')
        else:
            run = paragraph.add_run(part)
        if size:
            run.font.size = Pt(size)
        if color:
            run.font.color.rgb = color
    return paragraph


class UraDoc:
    def __init__(self, template, logo=None):
        self.d = Document(str(template))
        self.logo = logo
        body = self.d.element.body
        for child in list(body):
            if child.tag != qn('w:sectPr'):
                body.remove(child)
        self.sec = self.d.sections[0]
        self._page_setup(self.sec)
        self.n_table = 0
        self.n_figure = 0
        self.in_body = False
        self._setup_numbering()
        settings = self.d.settings.element
        upd = OxmlElement('w:updateFields'); upd.set(qn('w:val'), 'true'); settings.append(upd)

    # ---------------------------------------------------------------- page layout
    def _page_setup(self, sec):
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(1.9)
        sec.top_margin = sec.bottom_margin = Cm(2.54)
        sec.different_first_page_header_footer = False

    def _footer(self, sec, fmt):
        """Page number centred in the footer; fmt 'lowerRoman' or 'decimal', restarting at 1."""
        sec.footer.is_linked_to_previous = False
        ft = sec.footer
        for p in ft.paragraphs[1:]:
            p._p.getparent().remove(p._p)
        p = ft.paragraphs[0]
        for r in list(p.runs):
            r._r.getparent().remove(r._r)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if fmt:
            _field(p, 'PAGE', '1')
        sectPr = sec._sectPr
        for old in sectPr.findall(qn('w:pgNumType')):
            sectPr.remove(old)
        if fmt:
            pg = OxmlElement('w:pgNumType'); pg.set(qn('w:fmt'), fmt); pg.set(qn('w:start'), '1')
            sectPr.append(pg)
        sec.header.is_linked_to_previous = False
        for p in sec.header.paragraphs:
            for r in list(p.runs):
                r._r.getparent().remove(r._r)

    def _new_section(self):
        sec = self.d.add_section(WD_SECTION.NEW_PAGE)
        self._page_setup(sec)
        return sec

    def page_break(self):
        self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---------------------------------------------------------------- numbering (real Word lists)
    def _setup_numbering(self):
        numbering = self.d.part.numbering_part.element
        self._abs = {}
        for key, fmt, text in (('bullet', 'bullet', '•'), ('number', 'decimal', '%1.')):
            aid = str(900 + len(self._abs))
            a = OxmlElement('w:abstractNum'); a.set(qn('w:abstractNumId'), aid)
            for lvl in range(2):
                l = OxmlElement('w:lvl'); l.set(qn('w:ilvl'), str(lvl))
                st = OxmlElement('w:start'); st.set(qn('w:val'), '1'); l.append(st)
                nf = OxmlElement('w:numFmt'); nf.set(qn('w:val'), fmt if lvl == 0 or fmt == 'bullet' else 'lowerLetter'); l.append(nf)
                lt = OxmlElement('w:lvlText')
                lt.set(qn('w:val'), text if fmt == 'bullet' else ('%1.' if lvl == 0 else '%2.')); l.append(lt)
                pPr = OxmlElement('w:pPr'); ind = OxmlElement('w:ind')
                ind.set(qn('w:left'), str(567 * (lvl + 1))); ind.set(qn('w:hanging'), '284'); pPr.append(ind); l.append(pPr)
                a.append(l)
            first_num = numbering.find(qn('w:num'))
            if first_num is not None:
                first_num.addprevious(a)
            else:
                numbering.append(a)
            self._abs[key] = aid
        self._next_num = 900

    def _new_num(self, key):
        numbering = self.d.part.numbering_part.element
        self._next_num += 1
        n = OxmlElement('w:num'); n.set(qn('w:numId'), str(self._next_num))
        an = OxmlElement('w:abstractNumId'); an.set(qn('w:val'), self._abs[key]); n.append(an)
        ov = OxmlElement('w:lvlOverride'); ov.set(qn('w:ilvl'), '0')
        so = OxmlElement('w:startOverride'); so.set(qn('w:val'), '1'); ov.append(so); n.append(ov)
        numbering.append(n)
        return str(self._next_num)

    def _list(self, items, key):
        num = self._new_num(key)
        for it in items:
            level = 0
            if isinstance(it, tuple):
                level, it = it
            p = self.d.add_paragraph(style='List Paragraph')
            pPr = p._p.get_or_add_pPr()
            numPr = OxmlElement('w:numPr')
            il = OxmlElement('w:ilvl'); il.set(qn('w:val'), str(level)); numPr.append(il)
            ni = OxmlElement('w:numId'); ni.set(qn('w:val'), num); numPr.append(ni)
            pPr.append(numPr)
            p.paragraph_format.space_after = Pt(3)
            _rich(p, it)

    def bullets(self, items):
        self._list(items, 'bullet')

    def numbered(self, items):
        self._list(items, 'number')

    # ---------------------------------------------------------------- text
    def p(self, text, size=None, align=None, italic=False):
        para = self.d.add_paragraph()
        _rich(para, text, size=size)
        if italic:
            for r in para.runs:
                r.italic = True
        if align == 'center':
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(6)
        return para

    def h1(self, text):
        return self.d.add_paragraph(text, style='Heading 1')

    def h2(self, text):
        return self.d.add_paragraph(text, style='Heading 2')

    def h3(self, text):
        return self.d.add_paragraph(text, style='Heading 3')

    def code(self, lines):
        """A grey box of commands or code, one line per string."""
        t = self.d.add_table(rows=1, cols=1)
        _table_borders(t, 'BFBFBF')
        c = t.cell(0, 0)
        _set_cell_fill(c, 'F3F3F3')
        c.paragraphs[0].text = ''
        for i, line in enumerate(lines):
            para = c.paragraphs[0] if i == 0 else c.add_paragraph()
            run = para.add_run(line); run.font.name = 'Consolas'; run.font.size = Pt(9)
            run._r.get_or_add_rPr().get_or_add_rFonts().set(qn('w:hAnsi'), 'Consolas')
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.0
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def note(self, title, text):
        """A shaded box for 'In plain words' or 'Defending this decision' notes."""
        t = self.d.add_table(rows=1, cols=1)
        _table_borders(t, BORDER)
        c = t.cell(0, 0)
        _set_cell_fill(c, NOTE_FILL)
        p0 = c.paragraphs[0]
        r = p0.add_run(title); r.bold = True; r.font.color.rgb = BLUE; r.font.size = Pt(10)
        paras = text if isinstance(text, list) else [text]
        for t_ in paras:
            para = c.add_paragraph()
            _rich(para, t_, size=10)
            para.paragraph_format.space_after = Pt(3)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    # ---------------------------------------------------------------- tables and figures
    def caption(self, kind, text):
        para = self.d.add_paragraph(style='Caption')
        n = self.n_table if kind == 'Table' else self.n_figure
        para.add_run(f'{kind} ')
        _field(para, f'SEQ {kind} \\* ARABIC', str(n))
        para.add_run(f': {text}')
        return para

    def table(self, caption, header, rows, widths=None, size=9):
        self.n_table += 1
        self.caption('Table', caption)
        t = self.d.add_table(rows=1 + len(rows), cols=len(header))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        _table_borders(t)
        total = 17.2
        widths = widths or [total / len(header)] * len(header)
        scale = total / sum(widths)
        for j, h in enumerate(header):
            c = t.cell(0, j)
            _set_cell_fill(c, HEAD_FILL)
            c.paragraphs[0].text = ''
            r = c.paragraphs[0].add_run(str(h)); r.bold = True; r.font.size = Pt(size)
        for i, row in enumerate(rows, start=1):
            for j, v in enumerate(row):
                c = t.cell(i, j)
                c.paragraphs[0].text = ''
                _rich(c.paragraphs[0], '' if v is None else str(v), size=size)
        for row in t.rows:
            for j, c in enumerate(row.cells):
                c.width = Cm(widths[j] * scale)
                for para in c.paragraphs:
                    para.paragraph_format.space_after = Pt(1)
                    para.paragraph_format.space_before = Pt(1)
                    para.paragraph_format.line_spacing = 1.0
        # repeat the header row on every page
        trPr = t.rows[0]._tr.get_or_add_trPr()
        th = OxmlElement('w:tblHeader'); th.set(qn('w:val'), 'true'); trPr.append(th)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    def figure(self, path, caption, width_cm=16.5):
        self.n_figure += 1
        para = self.d.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run().add_picture(path, width=Cm(width_cm))
        para.paragraph_format.keep_with_next = True
        self.caption('Figure', caption)

    # ---------------------------------------------------------------- the house front matter
    def cover(self, title_lines, subtitle, version_line, classification='CLASSIFICATION: CONFIDENTIAL',
              dept='Information Technology and Innovation Department'):
        self._footer(self.sec, None)
        p = self.d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(classification); r.bold = True; r.font.size = Pt(8); r.font.color.rgb = BLUE
        for _ in range(3):
            self.d.add_paragraph()
        if self.logo:
            p = self.d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(str(self.logo), width=Cm(5.0))
        self.d.add_paragraph()
        self.p(dept, align='center')
        for _ in range(2):
            self.d.add_paragraph()
        for line in title_lines:
            p = self.d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(line); r.bold = True; r.font.size = Pt(15); r.font.color.rgb = BLUE
        self.p(subtitle, align='center')
        self.d.add_paragraph()
        p = self.d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(version_line); r.bold = True; r.font.size = Pt(9)
        self.sec = self._new_section()
        self._footer(self.sec, 'lowerRoman')

    def front_heading(self, text):
        p = self.d.add_paragraph(text, style='Heading 1')
        return p

    def contents(self):
        self.page_break()
        p = self.d.add_paragraph(style='TOC Heading'); p.add_run('Table of Contents')
        para = self.d.add_paragraph()
        _field(para, 'TOC \\o "1-3" \\h \\z \\u', 'Right-click here and choose Update Field to build the contents.')
        self.page_break()
        self.front_heading('List of Tables')
        para = self.d.add_paragraph()
        _field(para, 'TOC \\h \\z \\c "Table"', 'Right-click here and choose Update Field to list the tables.')
        self.front_heading('List of Figures')
        para = self.d.add_paragraph()
        _field(para, 'TOC \\h \\z \\c "Figure"', 'Right-click here and choose Update Field to list the figures.')

    def part(self, title, summary):
        """A PART divider page: heading and short summary on their own page, then a new page."""
        if not self.in_body:
            self.sec = self._new_section()
            self._footer(self.sec, 'decimal')
            self.in_body = True
        else:
            self.page_break()
        for _ in range(6):
            self.d.add_paragraph()
        self.h1(title)
        self.p(summary)
        self.page_break()

    def annex(self, title):
        self.page_break()
        self.h1(title)

    def save(self, path):
        self.d.save(str(path))
        return path
