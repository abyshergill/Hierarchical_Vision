"""Holiday-schedule PDF (ReportLab). Pure Python: no Django imports, so it is easy to test.

Text is escaped before it reaches ReportLab's mini-markup, and Thai runs are switched to a Thai-capable font
(Noto Sans Thai is bundled in ./fonts).
"""
import io
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = Path(__file__).resolve().parent / "fonts"
_FONTS = {"loaded": None}
_THAI = re.compile(r"[\u0E00-\u0E7F]+")
BLUE = colors.HexColor("#0a58b8")


def _load_fonts():
    """Register bundled Unicode fonts once; fall back to Helvetica (Latin only) if the files are missing."""
    if _FONTS["loaded"] is None:
        try:
            for name, file in (("HVSans", "NotoSans-Regular.ttf"), ("HVSans-Bold", "NotoSans-Bold.ttf"),
                               ("HVThai", "NotoSansThai-Regular.ttf"), ("HVThai-Bold", "NotoSansThai-Bold.ttf")):
                pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
            pdfmetrics.registerFontFamily("HVSans", normal="HVSans", bold="HVSans-Bold", italic="HVSans", boldItalic="HVSans-Bold")
            _FONTS["loaded"] = ("HVSans", "HVSans-Bold", True)
        except Exception:
            _FONTS["loaded"] = ("Helvetica", "Helvetica-Bold", False)
    return _FONTS["loaded"]


def _markup(text, bold=False):
    """Escape user text and wrap Thai runs in the Thai font."""
    regular, heavy, unicode_ok = _load_fonts()
    text = " ".join(str(text or "").split())
    if not unicode_ok:                                   # Helvetica cannot draw these glyphs
        return escape(text.encode("latin-1", "replace").decode("latin-1"))
    thai = "HVThai-Bold" if bold else "HVThai"
    out, pos = [], 0
    for m in _THAI.finditer(text):
        out.append(escape(text[pos:m.start()]))
        out.append(f'<font name="{thai}">{escape(m.group())}</font>')
        pos = m.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def build_holiday_pdf(year, holidays, company="Hierarchical Vision", generated_at=None):
    """``holidays`` is an iterable of (date, name, description). Returns the PDF as bytes."""
    regular, bold, _ = _load_fonts()
    generated_at = generated_at or datetime.now()
    rows = list(holidays)

    body = ParagraphStyle("body", fontName=regular, fontSize=10, leading=14, alignment=TA_LEFT)
    head = ParagraphStyle("head", parent=body, fontName=bold, textColor=colors.white)
    title = ParagraphStyle("title", parent=body, fontName=bold, fontSize=20, leading=24, textColor=BLUE)
    sub = ParagraphStyle("sub", parent=body, textColor=colors.HexColor("#555555"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
        title=f"Holiday schedule {year}", author=company, subject="Company holidays",
    )

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(18 * mm, 11 * mm, f"{company} · generated {generated_at:%d %b %Y %H:%M}")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f"Page {d.page}")
        canvas.restoreState()

    story = [
        Paragraph(f"Holiday schedule {int(year)}", title),
        Paragraph(_markup(company), sub),
        Paragraph(f"{len(rows)} public holiday{'s' if len(rows) != 1 else ''}", sub),
        Spacer(1, 8 * mm),
    ]
    if rows:
        data = [[Paragraph(h, head) for h in ("No.", "Date", "Day", "Holiday", "Notes")]]
        for i, (day, name, note) in enumerate(rows, 1):
            data.append([
                Paragraph(str(i), body),
                Paragraph(f"{day:%d %b %Y}", body),
                Paragraph(f"{day:%A}", body),
                Paragraph(_markup(name, bold=False), body),
                Paragraph(_markup(note), body),
            ])
        table = Table(data, colWidths=[12 * mm, 27 * mm, 26 * mm, 55 * mm, None], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fc")]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9dee7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
    else:
        story.append(Paragraph(f"No holidays are published for {int(year)}.", body))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
