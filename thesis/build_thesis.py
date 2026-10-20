# -*- coding: utf-8 -*-
"""
Assembles the full FYP thesis document (DOCX) for VidFusion, following the
Minhaj University Lahore documentation template. Reads pre-drafted chapter
text from content/*.txt, real diagrams from assets/diagrams/*.png, and real
UI screenshots from assets/screenshots/*.png.

Run: python build_thesis.py
Output: final_output/VidFusion_FYP_Documentation.docx
"""
import os
import re
from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, 'assets')
DIAGRAMS = os.path.join(ASSETS, 'diagrams')
SCREENSHOTS = os.path.join(ASSETS, 'screenshots')
CONTENT = os.path.join(BASE, 'content')
OUTPUT = os.path.join(BASE, 'final_output')
os.makedirs(OUTPUT, exist_ok=True)

# ── Project facts (front matter) ─────────────────────────────────────────────
PROJECT_TITLE = "VIDFUSION: AN AI-POWERED MULTI-VIDEO SUMMARIZATION AND FUSION PLATFORM"
# Two-student team. Muhammad Moazzam is listed first (primary) throughout;
# STUDENT_NAME/STUDENT_REG are kept as aliases to his details so any single-
# student usage elsewhere in this file still refers to the primary author.
STUDENTS = [
    ("Muhammad Moazzam", "2022F-MULBSSWE-042"),
    ("Sultan Kamran", "2022F-MULBSSWE-025"),
]
STUDENT_NAME, STUDENT_REG = STUDENTS[0]
SUPERVISOR_NAME = "Dr. Muhammad Saleem"
SUPERVISOR_DESIGNATION = "Assistant Professor"
DEPARTMENT = "Department of Software Engineering"
SCHOOL = "School of Software Engineering"
UNIVERSITY = "Minhaj University, Lahore"
SESSION = "2022-2026"
DEGREE = "Bachelor of Science (Software Engineering)"
HEAD_OF_DEPT = "Dr. Shahan Yamin Siddiqui"
FYP_COORDINATOR = "Ms. Nayab Gull"
DEAN_NAME = "Prof. Dr. Abdul Aziz"
DEAN_DESIGNATION = "Dean Faculty of CS & IT"

FONT_NAME = "Times New Roman"
BODY_SIZE = 12
H1_SIZE = 16
H2_SIZE = 14
H3_SIZE = 13


def read_content(name):
    path = os.path.join(CONTENT, name)
    if not os.path.exists(path):
        return f"[MISSING CONTENT FILE: {name}]"
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def set_base_style(doc):
    style = doc.styles['Normal']
    style.font.name = FONT_NAME
    style.font.size = Pt(BODY_SIZE)
    # Explicit black at the Normal-style level, rather than relying on a
    # viewer's default theme color, since a run that never sets its own
    # font.color.rgb (most of the plain body text added throughout this
    # script) otherwise rendered in a non-black theme accent colour in some
    # viewers — most visibly on the Certificate of Approval's signature
    # block, which is bold text with no other color set on it.
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.paragraph_format.space_after = Pt(10)
    style.paragraph_format.line_spacing = 1.5
    rpr = style.element.get_or_add_rPr()
    rFonts = rpr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rpr.append(rFonts)
    rFonts.set(qn('w:eastAsia'), FONT_NAME)

    sec = doc.sections[0]
    sec.page_height = Cm(29.7)
    sec.page_width = Cm(21.0)
    sec.left_margin = Cm(3.0)
    sec.right_margin = Cm(2.5)
    sec.top_margin = Cm(2.5)
    sec.bottom_margin = Cm(2.5)


def add_page_number_field(paragraph):
    run = paragraph.add_run()
    fld1 = OxmlElement('w:fldChar'); fld1.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText'); instr.set(qn('xml:space'), 'preserve'); instr.text = 'PAGE'
    fld2 = OxmlElement('w:fldChar'); fld2.set(qn('w:fldCharType'), 'end')
    run._r.append(fld1); run._r.append(instr); run._r.append(fld2)


def add_footer_page_number(section):
    footer = section.footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number_field(p)


# Populated as headings are added, then used to build a real (non-field) Table
# of Contents once the actual page numbers are known from a first PDF pass.
# Only Heading 1/2 entries from CHAPTER 1 onward go in the TOC — front matter
# (Declaration, Abstract, etc.) is listed by the template's own fixed labels,
# and Heading 3 (FR-xx / UC-xx / TC-xx entity blocks) would make the TOC as
# long as the document itself.
TOC_HEADINGS = []
_toc_tracking_started = [False]


def heading(doc, text, level=1, page_break_before=True):
    if page_break_before:
        doc.add_page_break()
    h = doc.add_heading(level=level)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT if level > 1 else WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run(text)
    run.font.name = FONT_NAME
    run.font.bold = True
    run.font.size = Pt(H1_SIZE if level == 1 else (H2_SIZE if level == 2 else H3_SIZE))
    run.font.color.rgb = RGBColor(0, 0, 0)

    if text.startswith('CHAPTER 1:'):
        _toc_tracking_started[0] = True
    if _toc_tracking_started[0] and level in (1, 2) and text != 'REFERENCES':
        TOC_HEADINGS.append((level, text))
    elif text == 'REFERENCES':
        TOC_HEADINGS.append((1, text))
    return h


def chapter_title_page(doc, chapter_label, chapter_name):
    """
    Gives a chapter its own dedicated title page — "CHAPTER N:" centered on
    one line, the chapter name centered on the next, vertically centred in
    the upper-middle of an otherwise blank page — matching the university
    template's own chapter-opener convention (confirmed against the
    reference document: a single real Word "Heading 1" paragraph, with
    leading blank lines inside it for vertical placement, rather than plain
    Normal-style paragraphs), instead of running the title directly into the
    chapter's first body heading on the same page. Using a real Heading 1
    keeps the chapter title visible in Word's Navigation Pane / document
    outline, matching the reference.
    """
    doc.add_page_break()
    full_text = f"{chapter_label}\n{chapter_name}".strip() if chapter_name else chapter_label
    h = doc.add_heading(level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for _ in range(8):
        h.add_run('\n')
    run = h.add_run(full_text)
    run.font.name = FONT_NAME
    run.font.bold = True
    run.font.size = Pt(H1_SIZE)
    run.font.color.rgb = RGBColor(0, 0, 0)

    toc_text = f"{chapter_label} {chapter_name}".strip()
    if toc_text.startswith('CHAPTER 1:'):
        _toc_tracking_started[0] = True
    if _toc_tracking_started[0]:
        TOC_HEADINGS.append((1, toc_text))


def body_paragraph(doc, text, bold=False, italic=False, align=None, size=None):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    run.font.name = FONT_NAME
    run.font.size = Pt(size or BODY_SIZE)
    run.bold = bold
    run.italic = italic
    return p


def add_screenshot_placeholder_image(doc, filename, caption=None, max_width_in=6.0):
    path = os.path.join(SCREENSHOTS, filename)
    if not os.path.exists(path):
        body_paragraph(doc, f"[Screenshot not found: {filename}]", italic=True)
        return
    with Image.open(path) as im:
        w, h = im.size
    ratio = h / w
    width = Inches(max_width_in)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(path, width=width)
    if caption:
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = cap.add_run(caption)
        r.italic = True
        r.font.size = Pt(10)


def add_diagram_image(doc, filename, caption, max_width_in=6.0):
    path = os.path.join(DIAGRAMS, filename)
    if not os.path.exists(path):
        body_paragraph(doc, f"[Diagram not found: {filename}]", italic=True)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(path, width=Inches(max_width_in))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run(caption)
    r.italic = True
    r.font.size = Pt(10)


# A block is a heading line if it's short, has no sentence-ending period, and
# isn't a "Label: value" field line. Covers "1.2 Purpose", "USE CASE 3: ...",
# "Architecture Diagram", "Languages", "5.2.1 Equivalence Partitions (EP)".
NUMBERED_HEADING_RE = re.compile(r'^([A-Z]|\d+)(\.\d+){1,3}\s+\S')
# Matches "Label: value" AND a bare "Label:" with nothing after it on the same
# line (e.g. "Basic Flow:" followed by its numbered steps on later lines).
FIELD_LINE_RE = re.compile(r'^([A-Za-z][A-Za-z0-9 /_\-\(\)]{1,40}):(\s|$)')
ENTITY_HEADER_RE = re.compile(r'^(USE CASE|FR-\d+|TC-\d+|UC-\d+)\b')


def is_standalone_heading(block_text):
    lines = block_text.strip().split('\n')
    if len(lines) != 1:
        return False
    line = lines[0].strip()
    if not line or len(line) > 80:
        return False
    if line.endswith('.'):
        return False
    if FIELD_LINE_RE.match(line):
        return False
    if NUMBERED_HEADING_RE.match(line):
        return True
    # Bare topic header: short, no terminal punctuation, mostly title/upper case.
    words = line.split()
    if len(words) <= 6 and not line.endswith((',', ';', ':')):
        return True
    return False


def heading_level_for(line):
    m = re.match(r'^(\d+)(\.\d+){0,3}\s', line)
    if not m:
        return 2
    dots = line.split(' ', 1)[0].count('.')
    return min(2 + dots, 4)


def render_entity_block(doc, block_text):
    """Renders a USE CASE / FR-xx / TC-xx style block as a labelled two-column
    table: a compact, scannable format matching the university template's own
    ID/Name/Description/... table style, built from the drafted 'Label: value'
    lines rather than prose."""
    lines = [l for l in block_text.strip().split('\n') if l.strip()]
    header_line = lines[0].strip()
    body_lines = lines[1:]

    heading(doc, header_line, level=3, page_break_before=False)

    # Merge continuation lines (e.g. numbered Basic Flow steps) into the value
    # of the most recent "Label:" line.
    fields = []
    for line in body_lines:
        m = FIELD_LINE_RE.match(line.strip())
        if m:
            label = m.group(1).strip()
            value = line.strip()[len(m.group(0)):].strip()
            fields.append([label, value])
        elif fields:
            fields[-1][1] = (fields[-1][1] + '\n' + line.strip()).strip()
        else:
            fields.append(['', line.strip()])

    table = doc.add_table(rows=len(fields), cols=2)
    table.style = 'Table Grid'
    table.columns[0].width = Inches(1.6)
    table.columns[1].width = Inches(4.6)
    for r_idx, (label, value) in enumerate(fields):
        lcell = table.cell(r_idx, 0)
        lcell.text = ''
        lrun = lcell.paragraphs[0].add_run(label)
        lrun.bold = True; lrun.font.size = Pt(10); lrun.font.name = FONT_NAME

        vcell = table.cell(r_idx, 1)
        vcell.text = ''
        for j, part in enumerate(value.split('\n')):
            vp = vcell.paragraphs[0] if j == 0 else vcell.add_paragraph()
            vrun = vp.add_run(part)
            vrun.font.size = Pt(10); vrun.font.name = FONT_NAME
    doc.add_paragraph()


def render_bold_lead_in_paragraph(doc, text):
    """'Term: rest of sentence.' -> bold term, then normal text, in one
    paragraph (used by Chapter 6's tool/language entries and similar)."""
    m = re.match(r'^([A-Z][A-Za-z0-9 /\.\+#\(\)]{1,60}):\s(.+)$', text, re.DOTALL)
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0)
    if m and len(m.group(1)) < 60:
        r1 = p.add_run(m.group(1) + ': ')
        r1.bold = True; r1.font.name = FONT_NAME; r1.font.size = Pt(BODY_SIZE)
        r2 = p.add_run(m.group(2))
        r2.font.name = FONT_NAME; r2.font.size = Pt(BODY_SIZE)
    else:
        r = p.add_run(text)
        r.font.name = FONT_NAME; r.font.size = Pt(BODY_SIZE)


def render_text_block(doc, raw_text, skip_first_line_if_title=True):
    """
    Renders a chapter's drafted plain-text (the real format the content was
    written in: a title line, blank-line-separated blocks, numbered or bare
    topic headings on their own line, 'USE CASE N:'/'FR-xx'/'TC-xx' labelled
    blocks, '[Screenshot: name.png]' markers, and plain prose) into the
    document as real Word headings/paragraphs/tables/images.
    """
    text = raw_text.strip('\n')
    raw_blocks = re.split(r'\n\s*\n', text)

    # A lone "USE CASE N: ..." / "FR-01" / "TC-01" header line is sometimes
    # its own block, separated by a blank line from the "ID: ..." field lines
    # that actually belong to it — merge the two so render_entity_block sees
    # the header and its fields together instead of an empty table followed
    # by an unparsed paragraph.
    blocks = []
    skip_next = False
    for idx, b in enumerate(raw_blocks):
        if skip_next:
            skip_next = False
            continue
        single_line_header = (
            len(b.strip().split('\n')) == 1 and ENTITY_HEADER_RE.match(b.strip())
        )
        if single_line_header and idx + 1 < len(raw_blocks):
            blocks.append(b.strip('\n') + '\n' + raw_blocks[idx + 1].strip('\n'))
            skip_next = True
        else:
            blocks.append(b)

    start = 0
    if skip_first_line_if_title and blocks and blocks[0].strip().isupper() and len(blocks[0].strip().split('\n')) == 1:
        start = 1  # the "CHAPTER N: ..." title line — already added as a Word Heading 1

    SCREENSHOT_LINE_RE = re.compile(r'^\[Screenshot:\s*(.+?)\s*\]$')
    NUMBERED_ITEM_RE = re.compile(r'^\d+\.\s+\S')
    FIGURE_LINE_RE = re.compile(r'^Figure\s+\d+[a-z]?:\s*(.+)$')
    # Maps a Figure caption's own text (matched by substring, case-insensitive)
    # to the rendered diagram file to insert in its place, for figures that
    # appear inline in prose chapters (e.g. Chapter 1's Project Plan) rather
    # than Chapter 4's dedicated design-diagram walkthrough.
    INLINE_FIGURE_MAP = [
        ('work breakdown structure', 'wbs.png'),
        ('gantt chart', 'gantt.png'),
    ]

    for block in blocks[start:]:
        block = block.strip('\n')
        if not block.strip():
            continue
        stripped = block.strip()

        if ENTITY_HEADER_RE.match(stripped):
            render_entity_block(doc, block)
            continue

        fig_m = FIGURE_LINE_RE.match(stripped) if len(stripped.split('\n')) == 1 else None
        if fig_m:
            caption_text = stripped
            low = fig_m.group(1).lower()
            matched_file = next((f for key, f in INLINE_FIGURE_MAP if key in low), None)
            if matched_file:
                add_diagram_image(doc, matched_file, caption_text)
                continue

        if is_standalone_heading(block):
            line = block.strip()
            heading(doc, line, level=heading_level_for(line), page_break_before=False)
            continue

        # A screenshot marker can appear on its own line in the middle of a
        # numbered walkthrough (a step, then its screenshot, then more steps),
        # so the block is split at those lines rather than treated as an
        # all-or-nothing match against the whole block.
        para_lines = block.split('\n')
        text_run = []

        def flush_text_run():
            if not text_run:
                return
            if all(NUMBERED_ITEM_RE.match(l.strip()) for l in text_run if l.strip()):
                # Keep the drafted "1. / 2. / 3." numbers as literal text rather
                # than Word's built-in "List Number" auto-numbering, which
                # continues incrementing across the whole document instead of
                # restarting at 1 for each new walkthrough section.
                for l in text_run:
                    if not l.strip():
                        continue
                    p = doc.add_paragraph()
                    p.paragraph_format.left_indent = Cm(0.6)
                    r = p.add_run(l.strip())
                    r.font.name = FONT_NAME; r.font.size = Pt(BODY_SIZE)
            elif all(l.strip().startswith('- ') for l in text_run if l.strip()):
                for l in text_run:
                    if not l.strip():
                        continue
                    p = doc.add_paragraph(style='List Bullet')
                    r = p.add_run(l.strip()[2:].strip())
                    r.font.name = FONT_NAME; r.font.size = Pt(BODY_SIZE)
            else:
                joined = ' '.join(l.strip() for l in text_run if l.strip())
                if joined:
                    render_bold_lead_in_paragraph(doc, joined)
            text_run.clear()

        for line in para_lines:
            m = SCREENSHOT_LINE_RE.match(line.strip())
            if m:
                flush_text_run()
                add_screenshot_placeholder_image(doc, m.group(1))
            else:
                text_run.append(line)
        flush_text_run()


def fill_table_of_contents(doc, anchor_paragraph, toc_page_map):
    """
    Inserts real Table of Contents entries (with dot leaders and page numbers)
    immediately after `anchor_paragraph`, using `toc_page_map` — a dict from
    heading text to its 1-based page number in a prior PDF render of this same
    document. Without a page map yet (the first pass of the two-pass build),
    a short explanatory placeholder is shown instead of guessed numbers.
    """
    anchor = anchor_paragraph._p

    def insert_after(ref_element, paragraph_xml_source_doc_paragraph):
        ref_element.addnext(paragraph_xml_source_doc_paragraph._p)

    # Fixed front-matter entries always come first, matching the order they
    # actually appear in this document.
    front_matter = [
        "Declaration", "Dedication", "Certificate of Approval",
        "Acknowledgement", "Abstract", "List of Figures", "List of Tables",
    ]

    last = anchor
    if not toc_page_map:
        p = doc.add_paragraph()
        r = p.add_run(
            "(Page numbers below are generated automatically from the actual "
            "layout of this document.)")
        r.italic = True; r.font.size = Pt(10); r.font.name = FONT_NAME
        insert_after(last, p)
        last = p._p
        entries = [(1, t) for t in front_matter] + TOC_HEADINGS
        for level, text in entries:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5 * (level - 1))
            r = p.add_run(text)
            r.font.name = FONT_NAME; r.font.size = Pt(BODY_SIZE)
            r.bold = (level == 1)
            insert_after(last, p)
            last = p._p
        return

    entries = [(1, t) for t in front_matter] + TOC_HEADINGS
    for level, text in entries:
        page = toc_page_map.get(text, '')
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5 * (level - 1))
        pPr = p._p.get_or_add_pPr()
        tabs = OxmlElement('w:tabs')
        tab = OxmlElement('w:tab')
        tab.set(qn('w:val'), 'right')
        tab.set(qn('w:leader'), 'dot')
        tab.set(qn('w:pos'), '9350')
        tabs.append(tab)
        pPr.append(tabs)

        r = p.add_run(text)
        r.font.name = FONT_NAME; r.font.size = Pt(BODY_SIZE)
        r.bold = (level == 1)
        r2 = p.add_run(f"\t{page}")
        r2.font.name = FONT_NAME; r2.font.size = Pt(BODY_SIZE)
        insert_after(last, p)
        last = p._p


def add_pipe_table(doc, table_lines):
    rows = [l for l in table_lines if l.strip() and not set(l.strip()) <= set('-| ')]
    if not rows:
        return
    parsed = [[c.strip() for c in r.strip().strip('|').split('|')] for r in rows]
    ncols = max(len(r) for r in parsed)
    table = doc.add_table(rows=len(parsed), cols=ncols)
    table.style = 'Table Grid'
    for r_idx, row in enumerate(parsed):
        for c_idx in range(ncols):
            cell_text = row[c_idx] if c_idx < len(row) else ''
            cell = table.cell(r_idx, c_idx)
            cell.text = ''
            p = cell.paragraphs[0]
            run = p.add_run(cell_text)
            run.font.size = Pt(10)
            run.font.name = FONT_NAME
            if r_idx == 0:
                run.bold = True
    doc.add_paragraph()


# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────

def build(toc_page_map=None):
    TOC_HEADINGS.clear()
    _toc_tracking_started[0] = False
    doc = Document()
    set_base_style(doc)

    # ---- Title page ----
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    r = p.add_run(PROJECT_TITLE)
    r.bold = True; r.font.size = Pt(16); r.font.name = FONT_NAME

    doc.add_paragraph()
    logo_path = os.path.join(ASSETS, 'mul_logo.png')
    if os.path.exists(logo_path):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(logo_path, width=Inches(1.8))

    title_page_lines = [
        (DEGREE, True, 13, 18),
        (f"Session ({SESSION})", True, 12, 4),
        ("Submitted By:", True, 12, 18),
    ]
    for i, (name, reg) in enumerate(STUDENTS):
        title_page_lines.append((f"{name} ({reg})", True, 12, 2 if i == 0 else 0))
    title_page_lines += [
        ("SUPERVISOR", True, 12, 18),
        (SUPERVISOR_NAME, True, 12, 2),
        (SUPERVISOR_DESIGNATION, False, 12, 0),
        (DEPARTMENT, False, 12, 0),
    ]
    for text, bold, size, space_before in title_page_lines:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(space_before)
        r = p.add_run(text)
        r.bold = bold; r.font.size = Pt(size); r.font.name = FONT_NAME

    doc.add_paragraph()
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    top = OxmlElement('w:top')
    top.set(qn('w:val'), 'single'); top.set(qn('w:sz'), '6'); top.set(qn('w:space'), '1'); top.set(qn('w:color'), 'auto')
    pBdr.append(top)
    pPr.append(pBdr)
    for text, bold in [(SCHOOL.upper(), True), (UNIVERSITY.upper(), True)]:
        pass
    r = p.add_run(SCHOOL.upper())
    r.bold = True; r.font.size = Pt(14); r.font.name = FONT_NAME
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(UNIVERSITY.upper())
    r2.bold = True; r2.font.size = Pt(14); r2.font.name = FONT_NAME

    # ---- Statement of submission ----
    doc.add_page_break()
    heading(doc, PROJECT_TITLE, level=1, page_break_before=False)
    doc.add_paragraph()
    body_paragraph(doc, "Project", align=WD_ALIGN_PARAGRAPH.CENTER, bold=True)
    doc.add_paragraph()
    doc.add_paragraph()
    body_paragraph(doc, "Submitted in Partial Fulfillment of the Requirements for the Degree of",
                   align=WD_ALIGN_PARAGRAPH.CENTER, italic=True)
    doc.add_paragraph()
    body_paragraph(doc, DEGREE, align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, size=13)
    doc.add_paragraph()
    body_paragraph(doc, f"at the\n{UNIVERSITY}", align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()
    doc.add_paragraph()
    body_paragraph(doc, "by", align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()
    for name, reg in STUDENTS:
        body_paragraph(doc, f"{name}    Reg. No. {reg}", align=WD_ALIGN_PARAGRAPH.CENTER, bold=True)

    for _ in range(4):
        doc.add_paragraph()

    table = doc.add_table(rows=2, cols=2)
    table.style = 'Table Grid'
    table.cell(0, 0).text = SUPERVISOR_NAME
    table.cell(0, 1).text = HEAD_OF_DEPT
    table.cell(1, 0).text = f"{SUPERVISOR_DESIGNATION}\n{SCHOOL}"
    table.cell(1, 1).text = f"Head of Department\n{SCHOOL}"

    # ---- Declaration ----
    heading(doc, "DECLARATION", level=1)
    body_paragraph(doc,
        "It is declared that this is an original piece of our own work, except where otherwise "
        "acknowledged in text and references. This work has not been submitted in any form for "
        "another degree or diploma at any university or other institution for tertiary education "
        "and shall not be submitted by us in future for obtaining any degree from this or any "
        "other University or Institution.")
    doc.add_paragraph()
    doc.add_paragraph()
    for name, reg in STUDENTS:
        p = doc.add_paragraph()
        r = p.add_run(f"{name}\t\t\t\tSignature: ______________________")
        r.font.name = FONT_NAME; r.font.size = Pt(BODY_SIZE)
        body_paragraph(doc, f"Reg. No. {reg}")
        doc.add_paragraph()

    # ---- Bismillah (as in the university's own starting-pages template) ----
    doc.add_page_break()
    bismillah_path = os.path.join(ASSETS, 'bismillah.png')
    if os.path.exists(bismillah_path):
        for _ in range(5):
            doc.add_paragraph()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(bismillah_path, width=Inches(5.8))

    # ---- Dedication ----
    heading(doc, "DEDICATION", level=1)
    body_paragraph(doc, "To", align=WD_ALIGN_PARAGRAPH.CENTER, italic=True)
    body_paragraph(doc, "\nOur Parents", align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, italic=True)
    body_paragraph(doc,
        "For their endless prayers, patience and sacrifices, for the quiet certainty that we "
        "could do this even on the days we doubted it ourselves, and for everything they gave up "
        "so that we would never have to choose between an education and anything else.",
        align=WD_ALIGN_PARAGRAPH.CENTER, italic=True)
    body_paragraph(doc, "\nOur Teachers", align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, italic=True)
    body_paragraph(doc,
        "For the guidance, patience and knowledge that shaped the way we think about "
        "engineering, and for asking the questions in class that we only understood the "
        "value of once we were debugging this project late into the night.",
        align=WD_ALIGN_PARAGRAPH.CENTER, italic=True)
    body_paragraph(doc, "\nOur Friends and Classmates", align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, italic=True)
    body_paragraph(doc,
        "For testing early, broken versions of this platform without complaint, and for the "
        "honest feedback that made the finished system better than either of us would have "
        "built working alone.",
        align=WD_ALIGN_PARAGRAPH.CENTER, italic=True)

    # ---- Certificate of Approval ----
    # Kept deliberately compact (small font, tight spacing, one designation
    # line instead of three) so all six signatories fit on a single page, as
    # in the university's own template — this page is meant to be signed by
    # hand and printed, so it must not spill across a page break.
    CERT_SIZE = 10.5
    heading(doc, "CERTIFICATE OF APPROVAL", level=1)
    students_line = " and ".join(f"{name}, {reg}" for name, reg in STUDENTS)
    cert_intro = doc.add_paragraph()
    cert_intro.paragraph_format.space_after = Pt(6)
    r = cert_intro.add_run(
        f'It is certified that the project titled "{PROJECT_TITLE}" carried out by '
        f'{students_line}, under the supervision of {SUPERVISOR_NAME}, {UNIVERSITY}, is '
        f'fully adequate, in scope and quality, as a final year project for the degree of '
        f'{DEGREE}. The undersigned recommend its acceptance.')
    r.font.name = FONT_NAME
    r.font.size = Pt(CERT_SIZE)
    r.font.color.rgb = RGBColor(0, 0, 0)

    for label, name, desig in [
        ("Supervisor", SUPERVISOR_NAME, f"{SUPERVISOR_DESIGNATION}, {SCHOOL}"),
        ("Internal Examiner 1", "", SCHOOL),
        ("Internal Examiner 2", "", SCHOOL),
        ("FYP Coordinator", FYP_COORDINATOR, f"Lecturer, {SCHOOL}"),
        ("Head of Department", HEAD_OF_DEPT, SCHOOL),
        ("Dean", DEAN_NAME, DEAN_DESIGNATION),
    ]:
        row = doc.add_paragraph()
        row.paragraph_format.space_before = Pt(8)
        row.paragraph_format.space_after = Pt(0)
        r1 = row.add_run(f"{label}: " + "_" * 28)
        r1.font.name = FONT_NAME
        r1.font.size = Pt(CERT_SIZE)
        r1.font.color.rgb = RGBColor(0, 0, 0)

        detail = doc.add_paragraph()
        detail.paragraph_format.space_before = Pt(0)
        detail.paragraph_format.space_after = Pt(0)
        detail.paragraph_format.left_indent = Cm(5.0)
        if name:
            nr = detail.add_run(f"{name}, ")
            nr.bold = True
            nr.font.name = FONT_NAME
            nr.font.size = Pt(CERT_SIZE)
            nr.font.color.rgb = RGBColor(0, 0, 0)
        dr = detail.add_run(desig)
        dr.font.name = FONT_NAME
        dr.font.size = Pt(CERT_SIZE)
        dr.font.color.rgb = RGBColor(0, 0, 0)

    # ---- Acknowledgement ----
    heading(doc, "ACKNOWLEDGEMENT", level=1)
    body_paragraph(doc,
        f"All praise is due to Allah Almighty for granting us the strength, patience and "
        f"opportunity to complete this project. We would like to express our sincere gratitude to "
        f"our supervisor, {SUPERVISOR_NAME}, for the guidance, feedback and encouragement "
        f"throughout the development of this project. His advice was instrumental whenever the "
        f"project's technical direction needed to be reconsidered.")
    body_paragraph(doc,
        "We are deeply grateful to our parents and families for their unconditional support, "
        "patience and prayers throughout our academic journey. Their encouragement gave us the "
        "confidence to take on a project of this scale and see it through to completion.")
    body_paragraph(doc,
        "We would also like to thank our teachers at the Department of Software Engineering, "
        "Minhaj University Lahore, for the knowledge and skills they imparted over the course of "
        "our degree, much of which was applied directly in building this system. Finally, we thank "
        "our friends and classmates who tested early versions of the platform and offered honest "
        "feedback that helped improve it.")

    # ---- Abstract ----
    heading(doc, "ABSTRACT", level=1)
    render_text_block(doc, read_content('00_abstract.txt'))

    # ---- List of Figures / Tables (static, matches generated diagrams) ----
    heading(doc, "LIST OF FIGURES", level=1)
    figures = [
        "Figure 1: Use Case Diagram - VidFusion",
        "Figure 2: System Architecture Diagram",
        "Figure 2b: System Architecture Diagram (reference rendering)",
        "Figure 3: Entity Relationship Diagram (ERD)",
        "Figure 4: Data Flow Diagram - Level 0",
        "Figure 5: Data Flow Diagram - Level 1",
        "Figure 6: Class Diagram",
        "Figure 7: Activity Diagram - Create Merge Job",
        "Figure 8: Sequence Diagram - Create Merge Job",
        "Figure 9: Collaboration Diagram - Create Merge Job",
        "Figure 10: State Transition Diagram - Merge Job Lifecycle",
        "Figure 11: Component Diagram",
        "Figure 12: Deployment Diagram",
        "Figure 13: Work Breakdown Structure",
        "Figure 14: Gantt Chart",
    ]
    for f in figures:
        body_paragraph(doc, f)

    heading(doc, "LIST OF TABLES", level=1)
    tables_list = [
        "Table 1: FR-01 Register Account",
        "Table 2: FR-02 Login",
        "Table 3: FR-03 Password Recovery",
        "Table 4: FR-04 Create Merge Job",
        "Table 5: FR-05 Preflight Check Sources",
        "Table 6: FR-06 Monitor Job Progress",
        "Table 7: FR-07 Retrieve Job Result",
        "Table 8: FR-08 Retry a Failed Output Component",
        "Table 9: FR-09 Search Transcripts",
        "Table 10: FR-10 Chat with Video Content",
        "Table 11: FR-11 Record Source Rights",
        "Table 12: FR-12 View Job Rights Manifest",
        "Table 13: FR-13 View History",
        "Table 14: FR-14 Manage Users (Admin)",
        "Table 15: UC-01 Register Account",
        "Table 16: UC-02 Login",
        "Table 17: UC-03 Create Merge Job",
        "Table 18: UC-04 Monitor Job Progress",
        "Table 19: UC-05 Retrieve Job Result",
        "Table 20: UC-06 Retry a Failed Output Component",
        "Table 21: UC-07 Search Transcripts",
        "Table 22: UC-08 Chat with Video Content",
        "Table 23: UC-09 Record Source Rights",
        "Table 24: UC-10 View Job Rights Manifest",
        "Table 25: UC-11 View History",
        "Table 26: UC-12 Manage Users (Admin)",
        "Table 27: TC-01 Successful login with correct email and password",
        "Table 28: TC-02 Failed login with wrong password",
        "Table 29: TC-03 Create a merge job with a feasible duration",
        "Table 30: TC-04 Reject a merge job with an infeasible duration",
        "Table 31: TC-05 Retry only the failed text-output component",
        "Table 32: TC-06 Worker crash recovery via lease expiry",
        "Table 33: TC-07 Duration-accuracy boundary at the Express profile's minimum",
        "Table 34: TC-08 Record a rights attestation and confirm it affects the publication gate",
        "Table 35: TC-09 Non-owner cannot read another user's job rights manifest",
    ]
    for t in tables_list:
        body_paragraph(doc, t)

    # ---- Table of Contents (Word field; user must right-click -> Update Field) ----
    heading(doc, "TABLE OF CONTENTS", level=1)
    toc_anchor_paragraph = doc.add_paragraph()  # filled in below, once headings are known

    # ==================== CHAPTERS ====================

    chapter_title_page(doc, "CHAPTER 1:", "INTRODUCTION TO THE PROBLEM")
    doc.add_page_break()
    render_text_block(doc, read_content('01_chapter1_introduction.txt'))

    chapter_title_page(doc, "CHAPTER 2:", "SOFTWARE REQUIREMENT SPECIFICATION")
    doc.add_page_break()
    render_text_block(doc, read_content('02_chapter2_srs.txt'))

    chapter_title_page(doc, "CHAPTER 3:", "USE CASE ANALYSIS")
    doc.add_page_break()
    add_diagram_image(doc, 'usecase.png', 'Figure 1: Use Case Diagram - VidFusion')
    render_text_block(doc, read_content('03_chapter3_usecases.txt'))

    chapter_title_page(doc, "CHAPTER 4:", "DESIGN")
    doc.add_page_break()
    design_intro = read_content('04_chapter4_design_intro.txt')
    # Matched by substring against the drafted heading text (e.g. the draft's
    # "Entity Relationship Diagram (ERD)" matches the 'erd' key) rather than
    # an exact string, since the drafting pass phrases each heading slightly
    # differently from the short label used elsewhere in this script.
    diagram_map = [
        ('architecture diagram', 'architecture.png', 'Figure 2: System Architecture Diagram'),
        ('entity relationship', 'erd.png', 'Figure 3: Entity Relationship Diagram (ERD)'),
        ('erd', 'erd.png', 'Figure 3: Entity Relationship Diagram (ERD)'),
        ('dfd level 0', 'dfd0.png', 'Figure 4: Data Flow Diagram - Level 0'),
        ('level 0', 'dfd0.png', 'Figure 4: Data Flow Diagram - Level 0'),
        ('dfd level 1', 'dfd1.png', 'Figure 5: Data Flow Diagram - Level 1'),
        ('level 1', 'dfd1.png', 'Figure 5: Data Flow Diagram - Level 1'),
        ('class diagram', 'class.png', 'Figure 6: Class Diagram'),
        ('activity diagram', 'activity.png', 'Figure 7: Activity Diagram - Create Merge Job'),
        ('sequence diagram', 'sequence.png', 'Figure 8: Sequence Diagram - Create Merge Job'),
        ('collaboration diagram', 'collaboration.png', 'Figure 9: Collaboration Diagram - Create Merge Job'),
        ('state transition', 'state.png', 'Figure 10: State Transition Diagram - Merge Job Lifecycle'),
        ('component diagram', 'component.png', 'Figure 11: Component Diagram'),
        ('deployment diagram', 'deployment.png', 'Figure 12: Deployment Diagram'),
    ]

    text = design_intro.strip('\n')
    blocks = re.split(r'\n\s*\n', text)
    used_diagrams = set()
    for idx, block in enumerate(blocks):
        block = block.strip('\n')
        if not block.strip():
            continue
        if idx == 0 and block.strip().isupper():
            continue  # "CHAPTER 4: SYSTEM DESIGN" title line, already added as Heading 1
        if is_standalone_heading(block) and not ENTITY_HEADER_RE.match(block.strip()):
            line = block.strip()
            heading(doc, line, level=2, page_break_before=False)
            match = None
            low = line.lower()
            for key, fname, caption in diagram_map:
                if key in low and fname not in used_diagrams:
                    match = (fname, caption)
                    break
            if match:
                used_diagrams.add(match[0])
                # The next block is this section's explanatory paragraph.
                continue
        else:
            joined = ' '.join(l.strip() for l in block.split('\n') if l.strip())
            render_bold_lead_in_paragraph(doc, joined)
            # If the previous heading matched a diagram, place the figure
            # right after its explanatory paragraph.
            if idx > 0:
                prev = blocks[idx - 1].strip()
                if is_standalone_heading(prev):
                    low = prev.lower()
                    for key, fname, caption in diagram_map:
                        if key in low:
                            add_diagram_image(doc, fname, caption)
                            # The architecture diagram is followed by a second,
                            # more visually detailed reference rendering of the
                            # same architecture, shown as-is alongside the
                            # primary (accurate, hand-verified) diagram above it.
                            if fname == 'architecture.png':
                                add_diagram_image(
                                    doc, 'architecture_diagram.png',
                                    'Figure 2b: System Architecture Diagram (reference rendering)')

                            break

    chapter_title_page(doc, "CHAPTER 5:", "TESTING")
    doc.add_page_break()
    render_text_block(doc, read_content('05_chapter5_testing.txt'))

    chapter_title_page(doc, "CHAPTER 6:", "TOOLS AND TECHNIQUES")
    doc.add_page_break()
    render_text_block(doc, read_content('06_chapter6_tools.txt'))

    chapter_title_page(doc, "CHAPTER 7:", "SUMMARY AND CONCLUSION")
    doc.add_page_break()
    render_text_block(doc, read_content('07_chapter7_conclusion.txt'))

    chapter_title_page(doc, "CHAPTER 8:", "USER MANUAL")
    doc.add_page_break()
    render_text_block(doc, read_content('08_chapter8_usermanual.txt'))

    chapter_title_page(doc, "CHAPTER 9:", "LESSONS LEARNT AND FUTURE WORK")
    doc.add_page_break()
    render_text_block(doc, read_content('09_chapter9_futurework.txt'))

    chapter_title_page(doc, "REFERENCES", "")
    doc.add_page_break()
    render_text_block(doc, read_content('10_references.txt'))

    chapter_title_page(doc, "APPENDIX A:", "ENVIRONMENT SETUP AND INSTALLATION GUIDE")
    doc.add_page_break()
    render_text_block(doc, read_content('11_appendix_setup.txt'), skip_first_line_if_title=True)

    # Now that every heading has been added, fill in the Table of Contents
    # anchor with real dot-leader entries. On the first pass (no page map
    # yet) this shows a placeholder note instead of guessed page numbers.
    fill_table_of_contents(doc, toc_anchor_paragraph, toc_page_map)

    # Footer page numbers on all sections
    for section in doc.sections:
        add_footer_page_number(section)

    out_path = os.path.join(OUTPUT, 'VidFusion_FYP_Documentation.docx')
    doc.save(out_path)
    print(f"Saved: {out_path}")
    return out_path


SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"


def convert_to_pdf(docx_path):
    import subprocess
    subprocess.run(
        [SOFFICE, '--headless', '--convert-to', 'pdf', '--outdir', OUTPUT, docx_path],
        check=True, capture_output=True,
    )
    return os.path.join(OUTPUT, os.path.splitext(os.path.basename(docx_path))[0] + '.pdf')


def build_toc_page_map(pdf_path):
    """
    Matches each tracked heading to its real page number by walking the PDF's
    text spans in document order and looking for bold runs whose text equals a
    heading, consuming the expected heading list in the SAME order headings
    were written (front matter labels, then TOC_HEADINGS) rather than doing an
    unordered text search — a plain substring search matches the wrong
    occurrence whenever a heading's words also appear in a figure caption, the
    List of Figures, or the TOC page itself.
    """
    import fitz
    doc = fitz.open(pdf_path)

    front_matter = [
        "Declaration", "Dedication", "Certificate of Approval",
        "Acknowledgement", "Abstract", "List of Figures", "List of Tables",
    ]
    expected = front_matter + [t for _, t in TOC_HEADINGS]
    page_map = {}
    expected_idx = 0
    # Skip the title/statement/TOC pages themselves: start looking only once
    # we're past the page the "Declaration" heading's OWN section begins,
    # found by scanning from the start but never matching before the first
    # expected entry is found in sequence (this naturally skips the title
    # page and statement-of-submission page, which don't contain these
    # heading strings verbatim anyway).
    expected_set_upper = {e.upper() for e in expected}
    in_toc_overflow = False
    for i, page in enumerate(doc):
        if expected_idx >= len(expected):
            break
        page_lines = [
            ln.strip() for b in page.get_text('dict')['blocks']
            for ln in b.get('lines', [])
            for ln in [''.join(s['text'] for s in ln['spans']).strip()]
            if ln
        ]
        page_text_joined = ' '.join(page_lines)

        # The TOC's own page is found by its unique marker text (written by
        # fill_table_of_contents), not by heading density — heading density
        # alone also fires on a real content page packed with short bare
        # topic subheadings (e.g. Chapter 6's "Languages" / "Database" /
        # "DevOps" list). Once the TOC page is seen, subsequent pages are
        # only treated as its overflow while they contain NO substantial body
        # prose (a real word count check), since the TOC overflow is nothing
        # but a list of headings with page numbers.
        is_toc_marker_page = 'TABLE OF CONTENTS' in page_text_joined or 'generated automatically from the actual layout' in page_text_joined
        if is_toc_marker_page:
            in_toc_overflow = True
            continue
        if in_toc_overflow:
            distinct_hits = {ln for ln in page_lines if ln.upper() in expected_set_upper}
            longest_non_heading_line = max((len(ln) for ln in page_lines if ln.upper() not in expected_set_upper), default=0)
            if len(distinct_hits) >= 2 and longest_non_heading_line < 20:
                continue  # still inside the TOC's overflow onto this page
            in_toc_overflow = False  # first real content page reached

        target = expected[expected_idx]
        blocks = page.get_text('dict')['blocks']

        # Reduce each block to (text, is_bold), skipping empty blocks. A long
        # heading (e.g. "CHAPTER 2: SOFTWARE REQUIREMENT SPECIFICATION") can
        # render as two separate consecutive bold blocks rather than one
        # multi-line block, so runs of consecutive all-bold blocks are joined
        # into one candidate string below rather than matched block-by-block.
        reduced = []
        for block in blocks:
            block_lines = block.get('lines', [])
            if not block_lines:
                continue
            text = ' '.join(
                ''.join(span['text'] for span in line['spans']).strip()
                for line in block_lines
            ).strip()
            text = re.sub(r'\s+', ' ', text)
            if not text:
                continue
            is_bold = any(
                (span['flags'] & 2**4) or 'Bold' in span.get('font', '')
                for line in block_lines for span in line['spans']
            )
            reduced.append((text, is_bold))

        j = 0
        while j < len(reduced) and expected_idx < len(expected):
            text, is_bold = reduced[j]
            if not is_bold:
                j += 1
                continue
            # Try the single block first, then progressively join following
            # consecutive bold blocks, to match a heading that wrapped across
            # more than one block.
            candidate = text
            k = j
            matched = False
            while True:
                if candidate.upper() == target.upper():
                    page_map[target] = i + 1
                    expected_idx += 1
                    if expected_idx >= len(expected):
                        matched = True
                        break
                    target = expected[expected_idx]
                    matched = True
                    break
                k += 1
                if k >= len(reduced) or not reduced[k][1]:
                    break
                candidate = candidate + ' ' + reduced[k][0]
            j = (k + 1) if matched else (j + 1)
    doc.close()
    return page_map


if __name__ == '__main__':
    print("Pass 1: building without real page numbers...")
    docx_path = build(toc_page_map=None)
    print("Converting to PDF to measure real page numbers...")
    pdf_path = convert_to_pdf(docx_path)
    page_map = build_toc_page_map(pdf_path)
    print(f"Resolved {len(page_map)} / {len(TOC_HEADINGS) + 7} TOC entries to real pages.")
    print("Pass 2: rebuilding with a real Table of Contents...")
    docx_path = build(toc_page_map=page_map)
    print("Converting final PDF...")
    convert_to_pdf(docx_path)
    print("Done.")
