"""Builds the Aéza defence decks (UMIRHACK 2026 and Хакатон Осень 2026).

Every number and every screenshot comes from the running product on the
organiser dataset (10 accounts / 30 services / 100 transactions) at the fixed
reference instant 2026-10-19 15:00 UTC. Unfilled facts are explicit placeholders
and are listed in aeza_umirhack_placeholder_checklist.md.

All text is wrapped at build time with real Manrope metrics and emitted as one
paragraph per line, so PowerPoint / LibreOffice / Keynote render identically.
"""

from __future__ import annotations

import sys

from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Inches, Pt

from deckkit import (
    CORAL, CORAL_DEEP, DIM, FONT, INK, INK_2, LINE, LINE_DARK, MINT, MUTED,
    PAPER, SH, SW, TEXT,
    WHITE, badge, bg, hairline, notes, numbered_marker, para, picture_fit,
    qr_slot, rect, runs, textbox,
)
from layout import OVERFLOW, lines_box, text_block

# Assets live next to this script; the decks themselves are written to the
# repository root, where the team expects to find them.
HERE = Path(__file__).resolve().parent
IMG = HERE / "shots"
BRAND = HERE / "brand"


def _repo_root() -> Path:
    for cand in (HERE, *HERE.parents):
        if (cand / "dataset").is_dir() and (cand / "backend" / "app" / "domain").is_dir():
            return cand
    return HERE


ROOT = _repo_root()

# Two event briefs were supplied for the same product. Everything that differs
# between them lives here, so both decks come from one verified source of facts.
PROFILES = {
    "hackathon": {
        "out": "aeza_hackathon_osen_2026.pptx",
        "event": "ХАКАТОН ОСЕНЬ 2026 · ДГТУ · РОСТОВ-НА-ДОНУ",
        "cover_sub": "Aéza Analyzer — аналитика риска оттока клиентов "
                     "хостинг-провайдера.",
        "title": "Aéza Analyzer — Хакатон Осень 2026",
        "final_kicker": "РИСК ВИДЕН · ПРИЧИНЫ ПОНЯТНЫ · ШАГ ОПРЕДЕЛЁН",
        "final_title": "Не ждать ухода клиента",
        "final_sub": "Дать команде возможность\nдействовать раньше",
        "next_step": "Предлагаем следующий шаг: вместе проверить модель на данных "
                     "Aéza и определить, какие сигналы действительно полезны "
                     "команде удержания. Это предложение, а не существующая "
                     "договорённость.",
    },
    "umirhack": {
        "out": "aeza_umirhack_defense.pptx",
        "event": "UMIRHACK 2026 · КЕЙС AÉZA",
        "cover_sub": "Aéza Analyzer — инструмент для поиска клиентов под риском, "
                     "объяснения причин и оценки потенциальных потерь.",
        "title": "Aéza Analyzer — защита UMIRHACK 2026",
        "final_kicker": "ИТОГ И СЛЕДУЮЩИЙ ШАГ",
        "final_title": "Не ждать ухода клиента",
        "final_sub": "Дать команде увидеть риск\nи действовать раньше",
        "next_step": "Предлагаем следующий шаг: вместе проверить модель на данных "
                     "Aéza и определить, какие сигналы действительно полезны "
                     "команде удержания. Это предложение, а не существующая "
                     "договорённость.",
    },
}

P = PROFILES["hackathon"]
OUT = ROOT / P["out"]

M = Inches(0.72)
CW = SW - 2 * M
SOFT = RGBColor(0xC9, 0xC9, 0xC9)      # light text on dark
HAIR = RGBColor(0xC9, 0xC9, 0xC9)      # placeholder outline


def E(v) -> Emu:
    return Emu(int(v))


def shot_h(name: str, width) -> Emu:
    """Height that keeps screenshot ``name`` at its true aspect ratio.

    The slides used to hard-code each screenshot's ratio. That silently broke
    whenever a shot was re-captured: the picture was then letterboxed inside a
    box of the wrong shape. Deriving the height from the file means a new
    capture can never disagree with the layout.
    """

    from PIL import Image

    iw, ih = Image.open(IMG / name).size
    return Emu(int(int(width) * ih / iw))


# ------------------------------------------------------------------ heads ---
def head(slide, kicker, title, sub=None, dark=False, y=0.60, title_size=30,
         sub_size=14, sub_w=None):
    """Kicker + statement headline + optional sub. Returns content start y (EMU)."""
    tc = WHITE if dark else TEXT
    kc = MINT if dark else CORAL_DEEP
    sc = SOFT if dark else MUTED
    cy = Inches(y)
    _, tf = textbox(slide, M, cy, CW, Inches(0.22))
    para(tf, kicker.upper(), 10.5, kc, 700, first=True, spacing_pt=1.4)
    cy = E(cy + Inches(0.27))
    cy = E(cy + text_block(slide, M, cy, CW, title, title_size, tc, 700,
                           spacing=1.08, tag=f"title:{title[:24]}"))
    if sub:
        cy = E(cy + Inches(0.13))
        cy = E(cy + text_block(slide, M, cy, Inches(sub_w or 11.0), sub, sub_size,
                               sc, 400, spacing=1.28, tag=f"sub:{title[:18]}"))
    return E(cy + Inches(0.30))


def foot(slide, text, dark=False, y=6.95):
    hairline(slide, M, Inches(y - 0.15), CW, LINE_DARK if dark else LINE)
    text_block(slide, M, Inches(y), CW, text, 9.5, SOFT if dark else MUTED, 400,
               spacing=1.2, tag="foot")


def shot(slide, name, x, y, w, h, align="left", valign="top", pad=0.035,
         line=LINE):
    """Screenshot inside a thin framed panel."""
    rect(slide, E(x - Inches(pad)), E(y - Inches(pad)),
         E(w + Inches(2 * pad)), E(h + Inches(2 * pad)),
         fill=WHITE, line=line, line_w=0.8)
    return picture_fit(slide, IMG / name, x, y, w, h, align=align, valign=valign)


def label(slide, x, y, w, text, color=MUTED, size=9.5):
    text_block(slide, x, y, w, text, size, color, 700, spacing=1.1, tag="label")


def stat(slide, x, y, w, value, caption, vcolor=CORAL_DEEP, vsize=25, csize=9.5):
    lines_box(slide, x, y, w, [value], vsize, vcolor, 700, spacing=1.0, tag="stat")
    text_block(slide, x, E(y + Inches(vsize * 1.05 / 72 + 0.06)), w, caption,
               csize, MUTED, 400, spacing=1.2, tag="statcap")


# ================================================================= SLIDES ===
def s01_cover(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, INK)
    rect(s, E(SW - Inches(3.55)), 0, Inches(3.55), SH, fill=INK_2)
    rect(s, E(SW - Inches(3.55)), 0, Inches(0.045), SH, fill=CORAL)

    picture_fit(s, BRAND / "aeza_logo_on_dark.png", M, Inches(0.58),
                Inches(1.40), Inches(0.34))

    text_block(s, M, Inches(1.16), Inches(8.2), P["event"],
               10.5, MINT, 700, tag="cover-kicker")

    y = Inches(1.86)
    y = E(y + lines_box(s, M, y, Inches(8.6), ["Увидеть риск оттока"], 44, WHITE,
                        700, spacing=1.0, tag="cover-t1"))
    lines_box(s, M, E(y + Inches(0.06)), Inches(8.6), ["раньше, чем клиент уйдёт"],
              44, CORAL, 700, spacing=1.0, tag="cover-t2")

    text_block(s, M, Inches(4.18), Inches(7.9), P["cover_sub"],
               15.5, SOFT, 400, spacing=1.35, tag="cover-sub")

    hairline(s, M, Inches(5.34), Inches(7.9), LINE_DARK)

    text_block(s, M, Inches(5.54), Inches(4.2), "КОМАНДА", 9.5, DIM, 700,
               tag="cover-teamlabel")
    text_block(s, M, Inches(5.80), Inches(5.0), "[НАЗВАНИЕ КОМАНДЫ]", 16, WHITE,
               600, tag="cover-teamname")
    text_block(s, M, Inches(6.18), Inches(5.4),
               "[ИМЯ УЧАСТНИКА 1] · [ИМЯ УЧАСТНИКА 2] · [ИМЯ УЧАСТНИКА 3]",
               10.5, DIM, 400, spacing=1.3, tag="cover-members")
    text_block(s, M, Inches(6.66), Inches(5.6),
               "ЗАПОЛНИТЬ ПЕРЕД ЗАЩИТОЙ · команда и QR-ссылки",
               8, MUTED, 600, spacing=1.2, tag="cover-fill")

    rx = E(SW - Inches(2.72))
    text_block(s, rx, Inches(2.06), Inches(1.9), "ССЫЛКИ ДЛЯ ЖЮРИ", 9, DIM, 700,
               tag="cover-qrlabel")
    qr_slot(s, rx, Inches(2.44), Inches(1.56), "[QR-КОД: ДЕМО]")
    qr_slot(s, rx, Inches(4.42), Inches(1.56), "[QR-КОД: GITHUB]")

    notes(s, """Что сказать (15 сек):
«У Aéza есть снимок клиентской базы. Мы задали один вопрос: как найти клиента,
который может уйти, понять почему и оценить деньги, пока он ещё не ушёл.
Вот что получилось.»

Не начинайте с определения оттока и не читайте подзаголовок вслух — он на экране.
ПЕРЕД ЗАЩИТОЙ: вписать название команды и участников, поставить реальные QR
на демо-стенд и GitHub.""")


def s02_problem(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Бизнес-проблема",
             "Сигналы разрознены — риск остаётся незаметным",
             "Клиент продолжает пользоваться услугой, но отдельные признаки уже "
             "говорят о риске. По одному статусу и общей выручке этого не увидеть.")

    stages = [
        ("Разрозненные сигналы",
         "Дата окончания, автопродление, неуспешные продления, статус услуги — "
         "каждое поле живёт отдельно."),
        ("Риск остаётся незаметным",
         "В общем списке клиентов нет приоритета: проблемный аккаунт выглядит "
         "так же, как здоровый."),
        ("Поздняя реакция",
         "Разбираются, когда услуга уже истекла. Причины не собраны в одном месте, "
         "поэтому действовать заранее не с чем."),
    ]
    w = E((CW - Inches(0.60)) / 3)
    ch = Inches(1.92)
    for i, (t, b) in enumerate(stages):
        x = E(M + i * (w + Inches(0.30)))
        rect(s, x, y, w, ch, fill=WHITE, line=LINE, line_w=0.9)
        rect(s, x, y, w, Inches(0.045), fill=CORAL_DEEP if i == 2 else INK_2)
        numbered_marker(s, E(x + Inches(0.36)), E(y + Inches(0.44)), i + 1,
                        fill=CORAL_DEEP if i == 2 else INK_2)
        ty = E(y + Inches(0.72))
        ty = E(ty + lines_box(s, E(x + Inches(0.22)), ty, E(w - Inches(0.44)), [t],
                              14.5, TEXT, 600, spacing=1.12, tag="stage-t"))
        text_block(s, E(x + Inches(0.22)), E(ty + Inches(0.07)), E(w - Inches(0.44)),
                   b, 10.5, MUTED, 400, spacing=1.30, tag="stage-b")
        if i < 2:
            rect(s, E(x + w + Inches(0.055)), E(y + Inches(0.80)), Inches(0.19),
                 Inches(0.26), fill=LINE, shape=MSO_SHAPE.RIGHT_ARROW)

    # evidence strip
    ey = E(y + ch + Inches(0.30))
    eh = Inches(1.66)
    rect(s, M, ey, CW, eh, fill=WHITE, line=LINE, line_w=0.9)
    text_block(s, E(M + Inches(0.26)), E(ey + Inches(0.26)), Inches(3.10),
               "Сигналы риска в снимке Aéza", 12.5, TEXT, 600, tag="ev-t")
    text_block(s, E(M + Inches(0.26)), E(ey + Inches(0.58)), Inches(3.10),
               "Прямой подсчёт по 30 услугам датасета организатора; одна услуга "
               "может попасть в несколько категорий.",
               9.5, MUTED, 400, spacing=1.3, tag="ev-b")

    stats = [("12", "близость даты окончания"), ("9", "автопродление отключено"),
             ("6", "услуга приостановлена"), ("6", "ожидание продления")]
    sx = E(M + Inches(3.62))
    sw = Inches(2.03)
    for i, (n, lab) in enumerate(stats):
        x = E(sx + i * sw)
        if i:
            rect(s, E(x - Inches(0.09)), E(ey + Inches(0.34)), Pt(0.75),
                 Inches(0.98), fill=LINE)
        stat(s, x, E(ey + Inches(0.34)), E(sw - Inches(0.24)), n, lab)

    foot(s, "Источник: Aéza Analyzer, блок «Основные причины риска», опорный момент "
            "2026-10-19 15:00 UTC. Набор кейса синтетический.")
    notes(s, """Что сказать (35 сек):
«По 30 услугам снимка: 12 уже близки к окончанию, 9 не продлятся автоматически,
6 услуг приостановлены и 6 ждут продления. Каждый сигнал по
отдельности выглядит безобидно. Вместе они описывают клиента, который может уйти.
Проблема в том, что в общем списке этого не видно: нет ни приоритета, ни объяснения.
Отсюда — поздняя реакция.»

Показать: три блока схемы, затем цифры нижней полосы.
Возможный вопрос: «Это статистика реальной базы Aéza?» — Нет. Это подсчёт по
синтетическому снимку из комплекта кейса. Мы не приписываем эти числа реальным
клиентам Aéza.
Переход: «Поэтому мы собрали инструмент, который делает это за аналитика.»""")


def s03_solution(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Наше решение",
             "Один экран: приоритет, причина, деньги",
             "Aéza Analyzer ранжирует клиентов по риску, объясняет каждую оценку "
             "наблюдаемыми сигналами и считает выручку под риском отдельно от баланса.",
             sub_size=13.5)

    items = [
        ("1", "Список клиентов", "сортировка по риску, фильтр по категории"),
        ("2", "Балл риска", "0–100 и категория в карточке клиента"),
        ("3", "Причины оценки", "каждый фактор с числом и вкладом"),
        ("4", "Настройки модели", "веса, горизонт и пороги · /settings"),
    ]
    cw4 = E(CW / 4)
    for i, (n, t, sub) in enumerate(items):
        x = E(M + i * cw4)
        numbered_marker(s, E(x + Inches(0.16)), E(y + Inches(0.16)), n)
        lines_box(s, E(x + Inches(0.36)), E(y - Inches(0.02)), E(cw4 - Inches(0.42)),
                  [t], 12, TEXT, 600, spacing=1.1, tag="sol-t")
        text_block(s, E(x + Inches(0.36)), E(y + Inches(0.20)), E(cw4 - Inches(0.42)),
                   sub, 9.5, MUTED, 400, spacing=1.15, tag="sol-s")

    py = E(y + Inches(0.80))
    lw = Inches(7.10)
    rw = E(CW - lw - Inches(0.30))
    rx = E(M + lw + Inches(0.30))

    # left: the ranked customer list
    label(s, M, py, lw, "РЕАЛЬНЫЙ ИНТЕРФЕЙС · СПИСОК КЛИЕНТОВ ПО РИСКУ")
    shot(s, "cust_table_all.png", M, E(py + Inches(0.26)), lw,
         shot_h("cust_table_all.png", lw))
    h1 = shot_h("cust_table_all.png", lw)
    text_block(s, M, E(py + Inches(0.26) + h1 + Inches(0.12)), lw,
               "Все 10 клиентов снимка отсортированы по риску: балл, уровень и выручка "
               "под риском в одной строке.", 10, MUTED, 400, spacing=1.28, tag="sol-cap-l")

    # right: summary metrics above the risk-reason breakdown
    label(s, rx, py, rw, "СВОДКА ПО БАЗЕ")
    hm = shot_h("w_dash_metrics6.png", rw)
    shot(s, "w_dash_metrics6.png", rx, E(py + Inches(0.26)), rw, hm)
    hy = E(py + Inches(0.26) + hm + Inches(0.22))
    hr = shot_h("w_dash_reasons.png", rw)
    shot(s, "w_dash_reasons.png", rx, hy, rw, hr)
    text_block(s, rx, E(hy + hr + Inches(0.12)), rw,
               "Сводка — по всем клиентам; причины риска — прямой подсчёт по услугам.",
               10, MUTED, 400, spacing=1.28, tag="sol-cap-r")

    notes(s, """Что сказать (30 сек):
«Продукт делает четыре вещи: находит клиентов под риском и сортирует их,
показывает балл риска, объясняет оценку конкретными сигналами и позволяет
менять веса модели. Всё это — реальный интерфейс запущенного приложения, а не макет.»

Показать: маркеры 1–4 сверху, затем слева таблицу клиентов (обратите внимание на
строку user-0010@example.test — балл 71,4, верхняя группа риска), справа сводные
метрики и блок
«Основные причины риска».
Возможный вопрос: «Это прототип на макете?» — Нет. Приложение запущено:
FastAPI + Postgres + React, работает на снимке из комплекта кейса.
Переход: «Пройдём этот путь на конкретном клиенте.»""")


def s04_customer(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Сквозной сценарий · шаг 1–2",
             "Клиент #10 — высокий риск, 71,4 из 100",
             "Список отсортирован по риску по убыванию. Балл 71,4 делят клиенты "
             "#5 и #10 — берём #10, он выше по номеру. Слева — реальные поля снимка, "
             "справа — тот же клиент в интерфейсе.",
             sub_size=13.5)

    lw = Inches(4.20)
    ph = E(Inches(6.62) - y)
    rect(s, M, y, lw, ph, fill=WHITE, line=LINE, line_w=0.9)
    text_block(s, E(M + Inches(0.26)), E(y + Inches(0.24)), E(lw - Inches(0.52)),
               "user-0010@example.test", 15, TEXT, 600, tag="c10-mail")
    text_block(s, E(M + Inches(0.26)), E(y + Inches(0.54)), E(lw - Inches(0.52)),
               "Клиент #10 · 3 услуги, все 3 пригодны для прогноза",
               10, MUTED, 400, tag="c10-sub")
    badge(s, E(M + Inches(0.26)), E(y + Inches(0.86)), Inches(1.18), Inches(0.30),
          "ВЫСОКИЙ", CORAL_DEEP)

    facts = [
        ("Балл риска клиента", "71,4 / 100", CORAL_DEEP, 14),
        ("Категория", "Высокий (порог ≥ 65)", TEXT, 12),
        ("Услуг высокого риска", "2 из 3", TEXT, 12),
        ("Выручка под риском", "0,00 € — сроки уже прошли", MUTED, 12),
        ("Баланс / всего пополнено", "203,79 € / 4 206,69 €", TEXT, 12),
    ]
    fy = E(y + Inches(1.40))
    for k, v, c, vs in facts:
        text_block(s, E(M + Inches(0.26)), fy, E(lw - Inches(0.52)), k, 9, MUTED, 600,
                   spacing=1.05, tag="c10-k")
        h = text_block(s, E(M + Inches(0.26)), E(fy + Inches(0.17)),
                       E(lw - Inches(0.52)), v, vs, c,
                       600 if vs >= 13 else 500, spacing=1.1, tag="c10-v")
        fy = E(fy + Inches(0.17) + h + Inches(0.13))

    rx = E(M + lw + Inches(0.32))
    rw = E(CW - lw - Inches(0.32))
    label(s, rx, E(y - Inches(0.03)), rw, "РЕАЛЬНЫЙ ИНТЕРФЕЙС · КАРТОЧКА КЛИЕНТА #10")
    hh = shot_h("c10_pagehead.png", rw)
    shot(s, "c10_pagehead.png", rx, E(y + Inches(0.24)), rw, hh)
    my = E(y + Inches(0.24) + hh + Inches(0.12))
    hm = shot_h("m_c10_score.png", E((rw - Inches(0.16)) / 2))
    shot(s, "m_c10_score.png", rx, my, E((rw - Inches(0.16)) / 2), hm)
    shot(s, "m_c10_rev.png", E(rx + (rw - Inches(0.16)) / 2 + Inches(0.16)), my,
         E((rw - Inches(0.16)) / 2), hm)
    ly = E(my + hm + Inches(0.26))
    label(s, rx, ly, rw, "ПРИЧИНЫ ОЦЕНКИ ПО УСЛУГЕ service-0030")
    hr = shot_h("w_c10_reasons.png", rw)
    ry = E(ly + Inches(0.27))
    shot(s, "w_c10_reasons.png", rx, ry, rw, hr)
    text_block(s, rx, E(ry + hr + Inches(0.12)), rw,
               "Почему именно этот клиент: максимальный балл в списке, услуга "
               "просрочена на 35 дней, ожидает продления, автопродление отключено.",
               10.5, MUTED, 400, spacing=1.3, tag="c10-why")

    foot(s, "Опорный момент 2026-10-19 15:00 UTC. Данные: dataset/data.json "
            "(10 аккаунтов / 30 услуг / 100 транзакций). Балл риска — не вероятность оттока.")
    notes(s, """Что сказать (60 сек):
«Открываем список клиентов — он уже отсортирован по риску. Сверху двое с
одинаковым баллом 71,4: клиент #5 и клиент #10. Берём #10 — он показывает
то же правило клиентского балла на двух услугах сразу. Максимум по списку
именно 71,4, и ни один клиент не поднялся выше.
Что мы про него знаем из данных: три услуги, все пригодны для прогноза,
баланс 203,79 €, всего пополнено 4 206,69 €. Выручка под риском — ноль,
и это отдельный важный момент, к нему вернёмся на слайде про деньги.
Причины: услуга просрочена на 35 дней, ждёт продления, автопродление выключено.
Три причины — это ровно те три фактора, что дали вклад в балл.»

Показать: /customers → клик по #10 → шапка, метрики, блок «Причины оценки».
Возможный вопрос: «Почему балл клиента 71,4, а не среднее по услугам?» —
Правило продукта: балл клиента — максимум по услугам, пригодным для прогноза.
У #10 это видно наглядно: две услуги по 71,4 и одна 52,4 — берётся максимум.
Среднее замаскировало бы одну критичную услугу.
Переход: «Разберём, из чего складывается этот балл.»""")


def s05_factors(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Почему модель считает клиента рискованным",
             "Балл объясним: видно каждый вклад",
             "Формула: 100 × Σ(вес × значение) / Σвес. По service-0030 сумма вкладов "
             "7,50 при сумме весов 10,5 → 71,4. Ниже — фактические вклады из интерфейса.",
             sub_size=13)

    ch = E(Inches(6.62) - y)
    cw = Inches(6.55)
    rect(s, M, y, cw, ch, fill=WHITE, line=LINE, line_w=0.9)
    text_block(s, E(M + Inches(0.24)), E(y + Inches(0.20)), E(cw - Inches(0.48)),
               "Вклад факторов в балл 71,4 · service-0030", 12.5, TEXT, 600, tag="ch-t")

    cd = CategoryChartData()
    # Only the factors actually rated for this service appear as bars.  The
    # remaining ones are either 0 (a signal was checked and was absent) or
    # "not rated" (no renewal attempts in the window), and mixing those into
    # the bars would read as if the model had scored them.
    cd.categories = [
        "Близость даты окончания · 3,0",
        "Ожидание продления · 2,5",
        "Автопродление отключено · 2,0",
        "Недостаточно средств · 0,0",
        "Услуга приостановлена · 0,0",
    ]
    cd.add_series("Вклад (вес × значение)", (3.0, 2.5, 2.0, 0.0, 0.0))
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, E(M + Inches(0.18)),
                            E(y + Inches(0.56)), E(cw - Inches(0.36)),
                            E(ch - Inches(1.16)), cd)
    chart = gf.chart
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.gap_width = 50
    plot.has_data_labels = True
    plot.data_labels.number_format = '0.00'
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.font.size = Pt(10)
    plot.data_labels.font.name = FONT
    ser = plot.series[0]
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = CORAL
    ca = chart.category_axis
    ca.tick_labels.font.size = Pt(9.5)
    ca.tick_labels.font.name = FONT
    ca.format.line.color.rgb = LINE
    va = chart.value_axis
    va.visible = False
    va.has_major_gridlines = False
    chart.chart_style = 2

    text_block(s, E(M + Inches(0.24)), E(y + ch - Inches(0.52)), E(cw - Inches(0.48)),
               "Не показаны: доля неуспешных продлений и число неуспешных продлений — "
               "за 90 дней попыток не было, фактор не определён и в знаменатель не входит.",
               9, MUTED, 400, spacing=1.22, tag="ch-note")

    rx = E(M + cw + Inches(0.30))
    rw = E(CW - cw - Inches(0.30))
    steps = [
        ("Наблюдение", "Данные снимка: услуга истекла 35 дней назад, "
                       "autoProlong = false, статус prolong_wait.", MINT),
        ("Интерпретация", "Услуга просрочена и ждёт продления, а решение о продлении "
                          "зависит от клиента, потому что автопродление выключено.", MINT),
        ("Влияние на оценку", "Три сработавших фактора дают 3,0 + 2,5 + 2,0 = 7,5. "
                              "Остальные четыре либо равны нулю, либо не определены "
                              "(нет попыток продления за 90 дней) и в знаменатель не "
                              "входят: 100 × 7,5 / 10,5 = 71,4 — выше порога 65.",
         CORAL_DEEP),
    ]
    inner = E((ch - Inches(0.27)) / 3)
    for i, (t, b, c) in enumerate(steps):
        yy = E(y + i * (inner + Inches(0.135)))
        rect(s, rx, yy, rw, inner, fill=WHITE, line=LINE, line_w=0.9)
        rect(s, rx, yy, Inches(0.045), inner, fill=c)
        ty = E(yy + Inches(0.17))
        ty = E(ty + lines_box(s, E(rx + Inches(0.22)), ty, E(rw - Inches(0.44)), [t],
                              12, TEXT, 600, spacing=1.1, tag="step-t"))
        text_block(s, E(rx + Inches(0.22)), E(ty + Inches(0.06)), E(rw - Inches(0.44)),
                   b, 10, MUTED, 400, spacing=1.28, tag="step-b")

    foot(s, "Факторы: expiry_proximity, prolong_wait_status, auto_prolong_disabled, "
            "failed_renewals, renewal_failure_rate, insufficient_balance, suspended_status. "
            "Причинно-следственная связь не доказана: исторических исходов оттока в снимке нет.")
    notes(s, """Что сказать (50 сек):
«Балл — это не «алгоритм решил». Формула простая и проверяемая: сто умножить на
сумму вес×значение, делить на сумму весов. По этой услуге сумма вкладов 7,5 из 10,5 —
отсюда 71,4.
Крупнейшие вклады: близость даты окончания — 3,0, ожидание продления — 2,5,
автопродление отключено — 2,0.
Остальные четыре фактора дали ноль: баланса хватает на продление, услуга не
приостановлена, а попыток продления за 90 дней нет, поэтому доля неуспешных
не определена и в знаменатель не входит.
Это тоже важно: модель не накручивает риск там, где сигналов нет.»

Показать: диаграмму вкладов, затем правые карточки «наблюдение → интерпретация →
влияние». В интерфейсе — кнопку «Показать все факторы (7)».
Возможный вопрос: «Это машинное обучение?» — Нет, и мы это не скрываем.
В снимке нет исторических исходов: обучать и валидировать классификатор не на чем.
Модуль спроектирован под замену на калиброванную модель без смены API.
Переход: «Теперь деньги — отдельно от риска.»""")


def s06_money(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Денежная оценка",
             "Риск и деньги — разные величины",
             "Выручка под риском = стоимость продления × балл риска / 100, и только "
             "для открытых услуг с продлением внутри горизонта.",
             sub_size=13.5)

    fh = Inches(0.84)
    rect(s, M, y, CW, fh, fill=INK)
    _, tf = textbox(s, E(M + Inches(0.30)), E(y + Inches(0.15)), Inches(7.2),
                    Inches(0.56))
    runs(tf, [("выручка под риском  ", SOFT, 500),
              ("=  стоимость продления × балл риска / 100", WHITE, 600)], 15, first=True)
    text_block(s, E(M + Inches(8.10)), E(y + Inches(0.24)), E(CW - Inches(8.4)),
               "Баланс в формулу не входит", 10, MINT, 500,
               spacing=1.2, tag="money-note")

    cy = E(y + fh + Inches(0.30))
    bh = E(Inches(6.62) - cy)
    lw = Inches(4.35)
    rect(s, M, cy, lw, bh, fill=WHITE, line=LINE, line_w=0.9)
    text_block(s, E(M + Inches(0.24)), E(cy + Inches(0.22)), E(lw - Inches(0.48)),
               "Клиент #10 — высокий риск, но 0,00 € под риском", 12, TEXT, 600,
               spacing=1.12, tag="money-h")
    rows = [
        ("БАЛЛ РИСКА КЛИЕНТА", "71,4 / 100", CORAL_DEEP, 13.5),
        ("ВЫРУЧКА ПОД РИСКОМ", "0,00 €", TEXT, 13.5),
        ("ПОЧЕМУ НОЛЬ", "Сроки уже прошли — горизонт смотрит вперёд.", MUTED, 9.5),
        ("БАЛАНС — НЕ ВЫРУЧКА", "203,79 €", MUTED, 13.5),
        ("ВСЕГО ПОПОЛНЕНО — СПРАВОЧНО", "4 206,69 €", MUTED, 13.5),
    ]
    ry = E(cy + Inches(0.64))
    for k, v, c, vs in rows:
        text_block(s, E(M + Inches(0.24)), ry, E(lw - Inches(0.48)), k, 8.5, MUTED,
                   600, spacing=1.05, tag="money-k")
        h = text_block(s, E(M + Inches(0.24)), E(ry + Inches(0.17)),
                       E(lw - Inches(0.48)), v, vs, c, 600 if vs >= 13 else 400,
                       spacing=1.25, tag="money-v")
        ry = E(ry + Inches(0.17) + h + Inches(0.16))

    rx = E(M + lw + Inches(0.30))
    rw = E(CW - lw - Inches(0.30))
    label(s, rx, E(cy - Inches(0.03)), rw,
          "РЕАЛЬНЫЙ ИНТЕРФЕЙС · БЛИЖАЙШИЕ ПРОДЛЕНИЯ В ГОРИЗОНТЕ")
    shot(s, "renew_table.png", rx, E(cy + Inches(0.26)), rw,
         shot_h("renew_table.png", rw))
    ty = E(cy + Inches(0.26) + shot_h("renew_table.png", rw) + Inches(0.26))
    totals = [("ВЫРУЧКА ПОД РИСКОМ", "5,80 €", CORAL_DEEP, "прогнозная экспозиция"),
              ("ПРЕДСТОЯЩИЕ ПРОДЛЕНИЯ", "17,03 €", TEXT, "сумма без учёта риска"),
              ("ИСТОРИЧЕСКИЕ ПОПОЛНЕНИЯ", "22 240,73 €", MUTED,
               "справочно, не суммируется")]
    tw = E((rw - Inches(0.24)) / 3)
    th = E(Inches(6.62) - ty)
    for i, (k, v, c, sub) in enumerate(totals):
        x = E(rx + i * (tw + Inches(0.12)))
        rect(s, x, ty, tw, th, fill=WHITE, line=LINE, line_w=0.9)
        text_block(s, E(x + Inches(0.14)), E(ty + Inches(0.14)), E(tw - Inches(0.28)),
                   k, 8, MUTED, 600, spacing=1.1, tag="tot-k")
        lines_box(s, E(x + Inches(0.14)), E(ty + Inches(0.40)), E(tw - Inches(0.28)),
                  [v], 16, c, 700, spacing=1.0, tag="tot-v")
        text_block(s, E(x + Inches(0.14)), E(ty + Inches(0.74)), E(tw - Inches(0.28)),
                   sub, 8.5, MUTED, 400, spacing=1.15, tag="tot-s")

    foot(s, "Горизонт 30 дней. Четыре продления в горизонте стоят 0,95 + 2,34 + 5,47 "
            "+ 8,27 = 17,03 €; из них под риском 0,36 + 0,70 + 1,81 + 2,93 = 5,80 €. "
            "Оценка не является гарантированным прогнозом потерь.")
    notes(s, """Что сказать (45 сек):
«Здесь важно не сложить несопоставимое. У клиента #10 балл высокий — 71,4,
но выручка под риском ноль. Почему? Все его сроки уже прошли: просроченные
продления лежат в прошлом, а горизонт смотрит вперёд. Услуг с продлением
внутри 30 дней у него нет.
Баланс 203,79 € и пополнения 4 206,69 € — это не потерянные деньги. Мы держим
три величины раздельно: выручка под риском — прогноз, предстоящие продления —
сумма без риска, пополнения — справочная история.»

Показать: формулу, затем таблицу «Ближайшие продления в горизонте» — 4 строки,
и три итоговые метрики внизу.
Возможный вопрос: «Почему сумма такая маленькая?» — Потому что горизонт 30 дней,
и в него попадают 4 продления из 30 услуг. Это честная оценка по доступным полям,
а не бухгалтерский прогноз: календаря будущих списаний в снимке нет.
Переход: «Теперь проверим гипотезу: изменим вес фактора.»""")


def s07_change(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Сквозной сценарий · шаг 4–5",
             "Меняем вес — результат пересчитывается",
             "Гипотеза до изменения: усилим «близость даты окончания» с 3,0 до 9,0 — "
             "баллы вырастут. Проверяем на реальном интерфейсе.",
             sub_size=13.5)

    hh = Inches(0.46)
    rect(s, M, y, CW, hh, fill=WHITE, line=LINE, line_w=0.9)
    rect(s, M, y, Inches(0.045), hh, fill=CORAL_DEEP)
    _, tf = textbox(s, E(M + Inches(0.24)), E(y + Inches(0.11)), E(CW - Inches(0.48)),
                    Inches(0.28))
    runs(tf, [("ГИПОТЕЗА ДО ИЗМЕНЕНИЯ   ", CORAL_DEEP, 700),
              ("вес expiry_proximity 3,0 → 9,0 должен повысить баллы и число "
               "клиентов высокого риска", MUTED, 400)], 11, first=True)

    cy = E(y + hh + Inches(0.26))
    hw = E((CW - Inches(0.34)) / 2)
    label(s, M, cy, hw, "ДО · ВЕС 3,0")
    label(s, E(M + hw + Inches(0.34)), cy, hw, "ПОСЛЕ · ВЕС 9,0", CORAL_DEEP)
    sh_ = shot_h("t_set_before.png", hw)
    shot(s, "t_set_before.png", M, E(cy + Inches(0.24)), hw, sh_)
    shot(s, "t_set_after.png", E(M + hw + Inches(0.34)),
         E(cy + Inches(0.24)), hw, sh_)

    ry = E(cy + Inches(1.36))
    pairs = [
        ("Балл риска клиента #10", "71,4", "81,8"),
        ("Балл service-0030", "71,4", "81,8"),
        ("Услуг высокого риска", "4", "7"),
        ("Выручка под риском", "5,80 €", "7,72 €"),
        ("Сумма весов по услуге", "10,5", "16,5"),
        ("Сумма весов модели", "13,0", "19,0"),
    ]
    cw3 = E((CW - Inches(0.30)) / 3)
    rh = Inches(0.70)
    for i, (k, a, b) in enumerate(pairs):
        x = E(M + (i % 3) * (cw3 + Inches(0.15)))
        yy = E(ry + (i // 3) * (rh + Inches(0.14)))
        rect(s, x, yy, cw3, rh, fill=WHITE, line=LINE, line_w=0.9)
        text_block(s, E(x + Inches(0.16)), E(yy + Inches(0.10)), E(cw3 - Inches(0.32)),
                   k, 8.5, MUTED, 600, spacing=1.05, tag="pair-k")
        _, tf = textbox(s, E(x + Inches(0.16)), E(yy + Inches(0.30)),
                        E(cw3 - Inches(0.32)), Inches(0.34))
        runs(tf, [(a, MUTED, 500), ("   →   ", HAIR, 500), (b, CORAL_DEEP, 700)], 15,
             first=True)

    text_block(s, M, E(ry + 2 * rh + Inches(0.42)), CW,
               "Расчёт: по service-0030 сумма весов выросла с 10,5 до 16,5, вклад "
               "фактора — с 3,0 до 9,0, поэтому 100 × 13,5 / 16,5 = 81,8. Категории "
               "клиентов (3 высокий / 3 средний) не сдвинулись: вес усилил сигналы, но "
               "не перевёл никого через порог. Настройка сохраняется на сервере, сводка "
               "обновляется сразу, без перезагрузки страницы; кнопка «Значения по "
               "умолчанию» возвращает исходные 3,0 и прежние числа.",
               10.5, MUTED, 400, spacing=1.3, tag="change-note")

    notes(s, """Что сказать (60 сек):
«Сначала формулируем ожидание: усилим фактор «близость даты окончания» с трёх
до девяти. Гипотеза — баллы вырастут, клиентов высокого риска станет больше.
Идём в настройки модели, меняем вес, нажимаем «Сохранить».
Смотрите, что произошло. Балл клиента #10: 71,4 → 81,8. Услуг высокого риска:
4 → 7. Выручка под риском: 5,80 → 7,72 €. Категории клиентов при этом не сдвинулись —
это тоже честный результат, и его стоит показать.
Это не декоративный контрол: настройка уходит на сервер, сохраняется в базе и
пересчитывает всю аналитику. Кнопка «Значения по умолчанию» возвращает исходные числа.»

Показать: /settings → поле веса expiry_proximity 3 → 9 → «Сохранить». Сводка в шапке
обновляется на месте, без перезагрузки: услуг высокого риска 4 → 7, выручка
под риском 5,80 → 7,72 €, сумма весов 13,0 → 19,0. Затем открыть карточку клиента #10
(балл 81,8) и вернуться
в настройки, нажав «Значения по умолчанию».
Возможный вопрос: «Пересчёт автоматический?» — Да. Настройки сохраняются на сервере,
бэкенд пересчитывает всю аналитику, и интерфейс подтягивает новые значения сразу,
без ручной перезагрузки. Проверено на стенде: страница настроек остаётся открытой,
URL не меняется, числа в сводке обновляются сами.
Переход: «Что это даёт команде Aéza.»""")


def s08_value(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Результат для бизнеса",
             "Команда видит, с кого начать",
             "Четыре подтверждённые возможности продукта — и то, что мы сознательно "
             "не заявляем.", sub_size=13.5)

    items = [
        ("Приоритет вместо ручного просмотра",
         "Список отсортирован по риску, фильтр по категории оставляет только тех, "
         "кто требует внимания."),
        ("Причина вместо непрозрачного числа",
         "Каждый балл разложен на факторы с числами из данных и рекомендациями "
         "по удержанию."),
        ("Деньги отдельно от риска",
         "Выручка под риском считается по продлениям внутри горизонта; баланс и "
         "пополнения с ней не смешиваются."),
        ("Проверка гипотез",
         "Веса, горизонт и пороги меняются из интерфейса; результат пересчитывается "
         "сразу."),
    ]
    w = E((CW - Inches(0.30)) / 2)
    hh = Inches(1.06)
    for i, (t, b) in enumerate(items):
        x = E(M + (i % 2) * (w + Inches(0.30)))
        yy = E(y + (i // 2) * (hh + Inches(0.18)))
        rect(s, x, yy, w, hh, fill=WHITE, line=LINE, line_w=0.9)
        rect(s, x, yy, Inches(0.045), hh, fill=MINT)
        ty = E(yy + Inches(0.16))
        ty = E(ty + lines_box(s, E(x + Inches(0.26)), ty, E(w - Inches(0.50)), [t],
                              13, TEXT, 600, spacing=1.1, tag="val-t"))
        text_block(s, E(x + Inches(0.26)), E(ty + Inches(0.05)), E(w - Inches(0.50)),
                   b, 10.5, MUTED, 400, spacing=1.3, tag="val-b")

    ny = E(y + 2 * (hh + Inches(0.18)) + Inches(0.12))
    nh = E(Inches(6.62) - ny)
    rect(s, M, ny, CW, nh, fill=WHITE, line=LINE, line_w=0.9)
    rect(s, M, ny, Inches(0.045), nh, fill=CORAL_DEEP)
    ty = E(ny + Inches(0.18))
    ty = E(ty + lines_box(s, E(M + Inches(0.26)), ty, E(CW - Inches(0.52)),
                          ["Чего мы не заявляем"], 12.5, TEXT, 600, spacing=1.1,
                          tag="no-t"))
    text_block(s, E(M + Inches(0.26)), E(ty + Inches(0.06)), E(CW - Inches(0.52)),
               "Балл риска — не вероятность оттока в процентах: в снимке нет исторических "
               "исходов, поэтому модель построена на правилах, а не обучена. Точность, "
               "снижение оттока и рост выручки не измерены — мы их не обещаем. Продукт "
               "помогает анализировать и приоритизировать; удержание зависит от следующих "
               "действий команды.", 10.5, MUTED, 400, spacing=1.3, tag="no-b")

    foot(s, "Подтверждено запуском продукта на датасете организатора: снимок "
            "импортирован, все экраны и пересчёт проверены вживую.")
    notes(s, """Что сказать (35 сек):
«Что получает аналитик Aéza: приоритизированный список вместо ручного просмотра,
объяснение вместо непрозрачного числа, денежную оценку отдельно от баланса и
возможность проверить гипотезу, поменяв веса.
И сразу честно про границы: балл — не вероятность в процентах, точность мы не
измеряли, потому что в снимке нет истории уходов. Мы не обещаем снижение оттока —
мы даём инструмент для решения.»

Показать: четыре карточки, затем нижний блок ограничений — его проговариваем
обязательно, это сильный ход перед бизнес-заказчиком.
Возможный вопрос: «Какая точность модели?» — Не измерена и не заявлена. В данных
нет исходов оттока, обучать и валидировать классификатор не на чем.
Переход: «Коротко про то, как это устроено внутри.»""")


def s09_trust(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, PAPER)
    y = head(s, "Архитектура доверия и ограничения",
             "Данные → проверка → расчёт → интерфейс",
             "Короткий путь данных. Никаких скрытых шагов и никакой подмены "
             "отсутствующих сигналов нулём.", sub_size=13.5)

    chain = [
        ("Снимок Aéza", "data.json: 10 аккаунтов, 30 услуг, 100 транзакций"),
        ("Импорт с проверкой", "валидация целиком до записи, применение атомарно"),
        ("Скоринг", "один модуль: вес × фактор, сумма весов в знаменателе"),
        ("API и интерфейс", "FastAPI + Postgres, панель аналитика на React"),
    ]
    bw = E((CW - Inches(0.90)) / 4)
    bhh = Inches(1.30)
    for i, (t, b) in enumerate(chain):
        x = E(M + i * (bw + Inches(0.30)))
        rect(s, x, y, bw, bhh, fill=WHITE, line=LINE, line_w=0.9)
        rect(s, x, y, bw, Inches(0.045), fill=INK_2 if i < 3 else CORAL_DEEP)
        ty = E(y + Inches(0.20))
        ty = E(ty + lines_box(s, E(x + Inches(0.18)), ty, E(bw - Inches(0.36)), [t],
                              12, TEXT, 600, spacing=1.1, tag="chain-t"))
        text_block(s, E(x + Inches(0.18)), E(ty + Inches(0.05)), E(bw - Inches(0.36)),
                   b, 9.5, MUTED, 400, spacing=1.3, tag="chain-b")
        if i < 3:
            rect(s, E(x + bw + Inches(0.055)), E(y + Inches(0.53)), Inches(0.19),
                 Inches(0.24), fill=LINE, shape=MSO_SHAPE.RIGHT_ARROW)

    ly = E(y + bhh + Inches(0.30))
    lh = E(Inches(6.62) - ly)
    lw = E(CW * 0.485)
    rect(s, M, ly, lw, lh, fill=WHITE, line=LINE, line_w=0.9)
    ty = E(ly + Inches(0.18))
    ty = E(ty + lines_box(s, E(M + Inches(0.24)), ty, E(lw - Inches(0.48)),
                          ["Как обрабатываются пропуски"], 12.5, TEXT, 600,
                          spacing=1.1, tag="m-t"))
    text_block(s, E(M + Inches(0.24)), E(ty + Inches(0.06)), E(lw - Inches(0.48)),
               "• Неизвестное ≠ ноль: фактор без данных исключается из числителя и "
               "знаменателя, веса перенормируются.\n"
               "• Услуги deleted и blocked — состоявшееся событие, а не прогноз: "
               "балл им не присваивается.\n"
               "• Цена не входит в формулу риска: price — это экспозиция, а не "
               "вероятность ухода.\n"
               "• Опорный момент зафиксирован (2026-10-19 15:00 UTC), поэтому числа "
               "воспроизводимы.", 10, MUTED, 400, spacing=1.34, tag="m-b")

    rx = E(M + lw + Inches(0.30))
    rw = E(CW - lw - Inches(0.30))
    rect(s, rx, ly, rw, lh, fill=WHITE, line=LINE, line_w=0.9)
    ty = E(ly + Inches(0.18))
    ty = E(ty + lines_box(s, E(rx + Inches(0.24)), ty, E(rw - Inches(0.48)),
                          ["Ограничения, которые важно знать"], 12.5, TEXT, 600,
                          spacing=1.1, tag="lim-t"))
    text_block(s, E(rx + Inches(0.24)), E(ty + Inches(0.06)), E(rw - Inches(0.48)),
               "• Нет истории оттока — отсюда модель на правилах и отсутствие метрик "
               "точности.\n"
               "• Нет календаря будущих списаний: даты продлений выведены из expiresAt "
               "и paymentTerm.\n"
               "• Нет динамики: снимок описывает один момент, график тренда не строится.\n"
               "• Нагрузка не измерялась: набор кейса — 10 / 30 / 100 записей.",
               10, MUTED, 400, spacing=1.34, tag="lim-b")

    notes(s, """Что сказать (30 сек, при технически подкованном заказчике):
«Путь данных короткий: снимок Aéza проходит валидацию целиком до записи и
применяется атомарно, скоринг живёт в одном модуле, результат уходит в API и в панель.
Отдельно про пропуски: отсутствующий сигнал не превращается в ноль и не понижает
риск — фактор просто исключается, а веса перенормируются.
И про границы: истории уходов нет, календаря списаний нет, динамики нет, нагрузку
на больших объёмах мы не измеряли.»

Показать: цепочку, затем два блока ограничений. Не читать всё вслух — выбрать 2–3 пункта.
Возможный вопрос: «Что будет на 10 000 клиентов?» — Список пагинируется, фильтры и
сортировка выполняются в SQL, а не в браузере. Нагрузочного тестирования не проводили —
говорим честно.
Переход: «Финальный слайд.»""")


def s10_final(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg(s, INK)
    rect(s, 0, 0, Inches(0.06), SH, fill=CORAL)

    picture_fit(s, BRAND / "aeza_logo_on_dark.png", M, Inches(0.62),
                Inches(1.40), Inches(0.34))
    text_block(s, M, Inches(1.16), Inches(8.0), P["final_kicker"], 10.5, MINT,
               700, tag="fin-k")
    y = Inches(1.72)
    y = E(y + lines_box(s, M, y, Inches(8.3), [P["final_title"]], 40, WHITE,
                        700, spacing=1.02, tag="fin-t1"))
    y = E(y + lines_box(s, M, E(y + Inches(0.06)), Inches(8.3),
                        P["final_sub"].split("\n"), 25, CORAL, 600, spacing=1.12,
                        tag="fin-t2"))
    text_block(s, M, E(y + Inches(0.26)), Inches(8.0), P["next_step"],
               13, SOFT, 400, spacing=1.4, tag="fin-sub")

    hairline(s, M, Inches(4.62), Inches(8.0), LINE_DARK)
    text_block(s, M, Inches(4.82), Inches(4.2), "КОМАНДА", 9.5, DIM, 700, tag="fin-tl")
    ty = Inches(5.10)
    ty = E(ty + lines_box(s, M, ty, Inches(5.0), ["[НАЗВАНИЕ КОМАНДЫ]"], 17, WHITE,
                          600, spacing=1.15, tag="fin-tn"))
    for line in ("[ИМЯ УЧАСТНИКА 1] · [РОЛЬ УЧАСТНИКА 1]",
                 "[ИМЯ УЧАСТНИКА 2] · [РОЛЬ УЧАСТНИКА 2]",
                 "[ИМЯ УЧАСТНИКА 3] · [РОЛЬ УЧАСТНИКА 3]"):
        ty = E(ty + text_block(s, M, E(ty + Inches(0.02)), Inches(5.4), line, 10.5,
                               SOFT, 400, spacing=1.35, tag="fin-m"))
    text_block(s, M, E(ty + Inches(0.10)), Inches(5.4), "[КОНТАКТ / TELEGRAM]", 10.5,
               MINT, 500, tag="fin-c")

    rx = E(SW - Inches(3.42))
    rw = Inches(2.30)
    text_block(s, rx, Inches(1.38), rw, "ССЫЛКИ", 9.5, DIM, 700, tag="fin-sl")
    gy = Inches(1.74)
    gsz = Inches(1.20)
    rect(s, E(rx - Inches(0.03)), E(gy - Inches(0.03)),
         E(gsz + Inches(0.06)), E(gsz + Inches(0.06)), fill=WHITE)
    picture_fit(s, BRAND / "qr_github.png", rx, gy, gsz, gsz)
    text_block(s, rx, E(gy + gsz + Inches(0.07)), rw,
               "[QR-КОД: GITHUB] · репозиторий проекта", 8.5, DIM, 600,
               spacing=1.1, tag="fin-qg")

    qr_slot(s, rx, Inches(3.62), gsz, "[QR-КОД: ДЕМО]", caption_color=DIM)
    qr_slot(s, rx, Inches(5.30), gsz, "[QR-КОД: КОНТАКТЫ]", caption_color=DIM)
    text_block(s, rx, Inches(6.72), rw, "ЗАПОЛНИТЬ ПЕРЕД ЗАЩИТОЙ",
               8, MUTED, 700, spacing=1.2, tag="fin-fill")
    text_block(s, rx, Inches(6.92), rw, "Вставьте реальные ссылки",
               8, DIM, 400, spacing=1.25, tag="fin-qn")

    notes(s, """Что сказать (20 сек):
«Мы не обещаем автоматического удержания. Мы даём команде возможность увидеть риск
раньше и действовать до того, как клиент уйдёт.
Предлагаем следующий шаг: вместе проверить модель на данных Aéza и понять, какие
сигналы действительно полезны вашей команде удержания. Спасибо.»

ПЕРЕД ЗАЩИТОЙ: подставить название команды, имена и роли, контакт; заменить два
QR-блока-заглушки (демо и контакты) на реальные ссылки. QR GitHub уже настоящий:
он закодирован из адреса публичного репозитория и проверен декодированием,
заменяйте только если репозиторий переедет.
Возможный вопрос: «Что дальше по продукту?» — Когда появятся исторические исходы,
логистическая регрессия на тех же признаках заменит формулу без изменения контракта
API и интерфейса.""")


def build(which: str) -> None:
    global P, OUT
    P = PROFILES[which]
    OUT = ROOT / P["out"]
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    for fn in (s01_cover, s02_problem, s03_solution, s04_customer, s05_factors,
               s06_money, s07_change, s08_value, s09_trust, s10_final):
        fn(prs)
    cp = prs.core_properties
    cp.title = P["title"]
    cp.author = "[НАЗВАНИЕ КОМАНДЫ]"
    cp.subject = "Анализ риска оттока клиентов хостинг-провайдера"
    cp.comments = ("Все числа и скриншоты получены из запущенного Aéza Analyzer "
                   "на датасете организатора, опорный момент 2026-10-19 15:00 UTC.")
    prs.save(OUT)
    print(f"saved {OUT.name} · slides={len(prs.slides._sldIdLst)} · profile={which}")
    if OVERFLOW:
        print("OVERFLOW:")
        for o in OVERFLOW:
            print("  ", o)
    else:
        print("no overflow")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "hackathon"
    for which in (sorted(PROFILES) if arg == "both" else [arg]):
        build(which)


if __name__ == "__main__":
    main()
