"""
Генерация PDF-отчёта по району/городу за период.

Использует reportlab — один из немногих PDF-движков с нормальной
поддержкой кириллицы и без тяжёлых системных зависимостей (как у
weasyprint, который требует cairo/pango).

Шрифт DejaVuSans подгружается лениво. Если он недоступен, код падает
обратно на Helvetica с латинскими-only символами и предупреждает.

API:
    build_district_report(
        path, district_id, start_dt, end_dt
    ) -> Path

UI и CLI вызывают одну и ту же функцию.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta as dtdelta
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from modules import data_repo
from modules.districts import DISTRICT_BY_ID

log = logging.getLogger(__name__)

# Поищем шрифт DejaVu в типичных местах macOS / linux. Если не нашли —
# используем встроенный Helvetica (с предупреждением о кириллице).
_FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    str(Path(__file__).resolve().parent.parent / "data" / "DejaVuSans.ttf"),
]

_FONT_NAME = "Helvetica"  # переопределится в _ensure_font()
_FONT_BOLD = "Helvetica-Bold"
_FONT_REGISTERED = False


def _ensure_font() -> None:
    """Регистрируем шрифт с кириллицей единожды за процесс."""
    global _FONT_NAME, _FONT_BOLD, _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    for path in _FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            try:
                pdfmetrics.registerFont(TTFont("ReportFont", str(p)))
                # bold берём тот же — для DejaVu это нормально
                pdfmetrics.registerFont(TTFont("ReportFontBold", str(p)))
                _FONT_NAME = "ReportFont"
                _FONT_BOLD = "ReportFontBold"
                _FONT_REGISTERED = True
                return
            except Exception as e:  # noqa: BLE001
                log.warning("Не удалось загрузить шрифт %s: %s", path, e)
    log.warning(
        "Не найден шрифт с кириллицей. Кириллические символы могут "
        "отображаться квадратиками. Скачайте DejaVuSans.ttf и положите "
        "в data/ — это решит проблему."
    )
    _FONT_REGISTERED = True


# ----------------------------------------------------------------------
# Стили
# ----------------------------------------------------------------------
def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"],
            fontName=_FONT_BOLD, fontSize=20, leading=24,
            spaceAfter=8, alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"],
            fontName=_FONT_NAME, fontSize=11, leading=14,
            textColor=colors.HexColor("#5d6d7e"), spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"],
            fontName=_FONT_BOLD, fontSize=14, leading=18,
            textColor=colors.HexColor("#1a5276"),
            spaceBefore=14, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName=_FONT_NAME, fontSize=10, leading=14,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"],
            fontName=_FONT_NAME, fontSize=8, leading=11,
            textColor=colors.HexColor("#7f8c8d"),
        ),
        "neg": ParagraphStyle(
            "neg", parent=base["Normal"],
            fontName=_FONT_NAME, fontSize=10, leading=13,
            textColor=colors.HexColor("#c0392b"),
        ),
        "pos": ParagraphStyle(
            "pos", parent=base["Normal"],
            fontName=_FONT_NAME, fontSize=10, leading=13,
            textColor=colors.HexColor("#27ae60"),
        ),
    }


def _table_style(header_row: bool = True) -> TableStyle:
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN",   (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f7f9fb")]),
    ]
    if header_row:
        cmds += [
            ("FONTNAME",   (0, 0), (-1, 0), _FONT_BOLD),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ]
    return TableStyle(cmds)


def _safe(text: str | None, max_len: int = 200) -> str:
    """Подготовить строку для Paragraph: обрезка + экранирование <>."""
    if not text:
        return "—"
    s = (text[:max_len] + "…") if len(text) > max_len else text
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ----------------------------------------------------------------------
# Сборка PDF
# ----------------------------------------------------------------------
def build_district_report(
    output_path: Path | str | None,
    district_id: str | None,
    start_dt: datetime,
    end_dt: datetime,
) -> bytes:
    """
    Собрать PDF-отчёт. Если output_path указан — сохранит файл и вернёт
    его байты. Если None — вернёт байты, файл не пишется (для UI).
    """
    _ensure_font()
    styles = _styles()

    # ---- 1) собираем данные через data_repo ----
    metrics = data_repo.get_district_metrics(start_dt=start_dt, end_dt=end_dt)
    metrics_by_id = {m.district_id: m for m in metrics}
    m = metrics_by_id.get(district_id) if district_id else None

    top_topics = data_repo.get_top_topics(district_id, start_dt, end_dt, limit=5)
    bursts     = data_repo.get_bursts(district_id, start_dt, end_dt, limit=5)
    top_users  = data_repo.get_top_users(start_dt=start_dt, end_dt=end_dt, limit=10)
    # для района оставляем только тех, кто активен в нём
    if district_id:
        top_users = [u for u in top_users if district_id in u.districts][:5]

    if district_id:
        comments_neg = data_repo.get_recent_comments(
            district_id, start_dt, end_dt, limit=5, sentiment="negative")
        comments_pos = data_repo.get_recent_comments(
            district_id, start_dt, end_dt, limit=5, sentiment="positive")
    else:
        comments_neg, comments_pos = [], []

    # ---- 2) собираем PDF ----
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Civic Monitor НН — отчёт",
        author="Civic Monitor НН",
    )
    story: list = []

    # ---- title ----
    if district_id:
        title = f"{DISTRICT_BY_ID[district_id]['name_ru']} район"
    else:
        title = "Нижний Новгород — весь город"
    story.append(Paragraph(title, styles["title"]))

    period_str = (
        f"{start_dt.strftime('%d.%m.%Y %H:%M')} → "
        f"{(end_dt - dtdelta(seconds=1)).strftime('%d.%m.%Y %H:%M')}"
    )
    story.append(Paragraph(
        f"Период: {period_str}<br/>"
        f"Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        styles["subtitle"],
    ))

    # ---- summary ----
    story.append(Paragraph("Сводка", styles["h2"]))
    if m and m.total_posts > 0:
        delta_pp = m.delta_vs_city * 100
        delta_str = (f"+{delta_pp:.1f}" if delta_pp >= 0 else f"{delta_pp:.1f}")
        rows = [
            ["Метрика", "Значение"],
            ["Всего сообщений (посты + комментарии)", f"{m.total_posts}"],
            ["Негативных", f"{m.negative} ({m.neg_share*100:.1f}%)"],
            ["Нейтральных", f"{m.neutral}"],
            ["Позитивных", f"{m.positive}"],
            ["Отклонение от средней негативности по городу",
             f"{delta_str} п.п."],
            ["Score (0..1, выше = хуже)", f"{m.negativity_score:.2f}"],
        ]
        t = Table(rows, colWidths=[10 * cm, 6 * cm])
        t.setStyle(_table_style())
        story.append(t)
    else:
        story.append(Paragraph("За выбранный период нет данных.", styles["body"]))

    # ---- top topics ----
    story.append(Paragraph("Топ-5 тем района", styles["h2"]))
    if top_topics:
        rows = [["Тема", "Сообщений", "Негатив %"]]
        for t in top_topics:
            rows.append([
                _safe(t.label, 60),
                str(t.count),
                f"{int(t.neg_share * 100)}%",
            ])
        tbl = Table(rows, colWidths=[10 * cm, 3 * cm, 3 * cm])
        tbl.setStyle(_table_style())
        story.append(tbl)
        # ключевые слова отдельно — они длинные
        for t in top_topics:
            story.append(Paragraph(
                f"<b>{_safe(t.label, 80)}</b>: "
                f"<font color='#7f8c8d'>{_safe(t.keywords, 200)}</font>",
                styles["body"],
            ))
    else:
        story.append(Paragraph("Нет тем за период.", styles["body"]))

    # ---- bursts ----
    story.append(Paragraph("Активные всплески", styles["h2"]))
    if bursts:
        rows = [["Дата", "Тема", "Объём", "z", "Интенс.", "Негатив%"]]
        for b in bursts:
            neg_str = (f"{int(b.neg_share*100)}%"
                       if b.neg_share is not None else "—")
            rows.append([
                b.date.strftime("%d.%m.%Y"),
                _safe(b.topic_label, 50),
                str(b.volume),
                f"{b.z_score:.1f}",
                b.intensity,
                neg_str,
            ])
        tbl = Table(rows,
                    colWidths=[2.4 * cm, 6.6 * cm, 1.6 * cm, 1.4 * cm,
                               2.0 * cm, 2.0 * cm])
        tbl.setStyle(_table_style())
        story.append(tbl)
    else:
        story.append(Paragraph("Всплесков не зафиксировано.", styles["body"]))

    # ---- top users ----
    if top_users:
        story.append(Paragraph("Самые активные авторы", styles["h2"]))
        rows = [["Автор", "Комментариев", "Окрас", "Бот?"]]
        for u in top_users:
            rows.append([
                _safe(u.name, 50),
                str(u.comments_in_period),
                f"{u.avg_sentiment:+.2f}",
                "⚠ да" if u.suspected_bot else "—",
            ])
        tbl = Table(rows,
                    colWidths=[7 * cm, 3 * cm, 3 * cm, 2 * cm])
        tbl.setStyle(_table_style())
        story.append(tbl)

    # ---- examples ----
    if comments_neg or comments_pos:
        story.append(PageBreak())
        story.append(Paragraph("Примеры сообщений", styles["h2"]))

        if comments_neg:
            story.append(Paragraph(
                "<b>Негативные:</b>", styles["body"]))
            for c in comments_neg:
                meta = (f"{c.author} · {c.group} · "
                        f"{c.created_at.strftime('%d.%m %H:%M')} · "
                        f"score {c.score:.2f}")
                story.append(Paragraph(_safe(c.text, 350), styles["neg"]))
                story.append(Paragraph(meta, styles["small"]))
                story.append(Spacer(1, 4))

        if comments_pos:
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                "<b>Позитивные:</b>", styles["body"]))
            for c in comments_pos:
                meta = (f"{c.author} · {c.group} · "
                        f"{c.created_at.strftime('%d.%m %H:%M')} · "
                        f"score {c.score:.2f}")
                story.append(Paragraph(_safe(c.text, 350), styles["pos"]))
                story.append(Paragraph(meta, styles["small"]))
                story.append(Spacer(1, 4))

    doc.build(story)
    pdf_bytes = buffer.getvalue()

    if output_path is not None:
        Path(output_path).write_bytes(pdf_bytes)
        log.info("PDF сохранён: %s (%d байт)", output_path, len(pdf_bytes))

    return pdf_bytes
