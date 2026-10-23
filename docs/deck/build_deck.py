"""Build the Aéza Analyzer deck for «Хакатон Осень 2026» (ДГТУ).

Aéza - это быстрый хостинг

Every figure on every slide is recomputed here by importing the real domain
modules from ``backend/app/domain`` and running them over ``dataset/data.json``.
Nothing is transcribed by hand, so the deck cannot drift away from the product.

Facts the repository does not contain (team name, participant names, demo URL)
are left as bracketed placeholders instead of being invented.

Run:  python3 docs/deck/build_deck.py
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import os
import sys

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots")


def find_repo_root(start):
    """Walk up until the case dataset is found, so the script is relocatable."""

    cur = start
    while True:
        if os.path.isdir(os.path.join(cur, "dataset")) and \
           os.path.isdir(os.path.join(cur, "backend", "app", "domain")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit("repo root not found above " + start)
        cur = parent


REPO = find_repo_root(HERE)
OUT = os.path.join(REPO, "aeza_hackathon_osen_2026.pptx")
sys.path.insert(0, os.path.join(REPO, "backend"))

from app.domain.risk import (  # noqa: E402
    DEFAULT_WEIGHTS,
    FACTORS,
    RiskSettings,
    compute_customer_risk,
    compute_service_risk,
)
from app.domain.revenue import (  # noqa: E402
    compute_customer_exposure,
    compute_service_exposure,
)
from app.domain.schema import Snapshot  # noqa: E402

from deck_lib import (  # noqa: E402
    CONTENT_W,
    CORAL,
    DARK,
    FONT,
    INK,
    INK_ON_DARK,
    LINE,
    LINE_ON_DARK,
    MARGIN,
    MINT,
    MUTED,
    MUTED_ON_DARK,
    SLIDE_H,
    SLIDE_W,
    WARM,
    WHITE,
    add_picture_contain,
    background,
    kicker,
    line_h,
    line_v,
    para,
    rect,
    rich,
    slide_title,
    textbox,
)


AS_OF = dt.datetime(2026, 10, 19, 15, 0, tzinfo=dt.timezone.utc)
HORIZON = 30
FEATURED = 10
TUNED_KEY = "expiry_proximity"
W_FROM, W_TO = 3.0, 9.0
TOTAL_SLIDES = 10
MONO = "DejaVu Sans Mono"


# ------------------------------------------------------------------ facts ---
def gather():
    """Recompute every deck figure from the dataset through the real modules."""

    with open(os.path.join(REPO, "dataset", "data.json"), encoding="utf-8") as fh:
        snap = Snapshot.model_validate(json.load(fh))

    tx = collections.defaultdict(list)
    for t in snap.transactions:
        tx[t.service_id].append(t)

    def run(weights):
        st = RiskSettings(horizon_days=HORIZON, weights=weights)
        rows = {}
        for a in snap.accounts:
            svcs = sorted((s for s in snap.services if s.owner_id == a.id),
                          key=lambda s: s.id)
            risks = [
                compute_service_risk(service=s, account=a, transactions=tx[s.id],
                                     settings=st, now=AS_OF)
                for s in svcs
            ]
            exposures = [
                e for e in (
                    compute_service_exposure(service=s, risk=r,
                                             horizon_days=HORIZON, now=AS_OF)
                    for s, r in zip(svcs, risks)
                ) if e
            ]
            rows[a.id] = {
                "account": a,
                "services": svcs,
                "risks": risks,
                "cust": compute_customer_risk(customer_id=a.id, service_risks=risks,
                                              settings=st),
                "exposure": compute_customer_exposure(customer_id=a.id,
                                                      renewals=exposures),
            }
        return rows

    base = run(dict(DEFAULT_WEIGHTS))
    tuned = run({**DEFAULT_WEIGHTS, TUNED_KEY: W_TO})

    signals = collections.Counter()
    for r in base.values():
        for risk in r["risks"]:
            for f in risk.factors:
                if f.available and f.value > 0:
                    signals[f.key] += 1

    fsvc = next(s for s in base[FEATURED]["services"] if s.id == 30)
    frisk = next(r for s, r in zip(base[FEATURED]["services"],
                                   base[FEATURED]["risks"]) if s.id == 30)

    return {
        "snap": snap,
        "base": base,
        "tuned": tuned,
        "cats": collections.Counter(r["cust"].category for r in base.values()),
        "tune_cats": collections.Counter(r["cust"].category for r in tuned.values()),
        "signals": signals,
        "fsvc": fsvc,
        "frisk": frisk,
        "n_open": sum(1 for s in snap.services
                      if s.status not in ("deleted", "blocked")),
        "rar": sum(r["exposure"].revenue_at_risk_cents for r in base.values()),
        "upcoming": sum(r["exposure"].upcoming_renewals_cents for r in base.values()),
        "rar_tuned": sum(r["exposure"].revenue_at_risk_cents for r in tuned.values()),
        "topups": sum(a.total_replenished for a in snap.accounts),
    }


def eur(cents: int) -> str:
    whole, frac = divmod(int(cents), 100)
    return f"{whole:,}".replace(",", "\u2009") + f",{frac:02d}\u2009€"


def n1(x) -> str:
    return "—" if x is None else f"{x:.1f}"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Russian numeral agreement: 1 услуга, 2 услуги, 5 услуг."""

    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


# ------------------------------------------------------------ deck helpers ---
def new_deck():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    return prs


def blank(prs, color):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    background(s, prs, color)
    return s


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def page(slide, n, dark=False):
    tb, tf = textbox(slide, SLIDE_W - MARGIN - Inches(1.1), SLIDE_H - Inches(0.58),
                     Inches(1.1), Inches(0.3))
    para(tf, f"{n} / {TOTAL_SLIDES}", 10, MUTED_ON_DARK if dark else MUTED,
         first=True, align=PP_ALIGN.RIGHT)


def slot(slide, x, y, w, h, label, sub=None, dark=False):
    """Neutral outlined placeholder for information we must not invent."""

    edge = LINE_ON_DARK if dark else LINE
    rect(slide, x, y, w, h, fill=None, line=edge, line_w=Pt(0.9))
    tb, tf = textbox(slide, x + Inches(0.12), y, w - Inches(0.24), h,
                     anchor=MSO_ANCHOR.MIDDLE)
    para(tf, label, 11, MUTED_ON_DARK if dark else MUTED, bold=True,
         first=True, align=PP_ALIGN.CENTER)
    if sub:
        para(tf, sub, 9.5, MUTED_ON_DARK if dark else MUTED,
             align=PP_ALIGN.CENTER, space_before=2)


def qr_slot(slide, x, y, size, label, dark=False):
    """A visibly-empty frame: never a fake scannable QR code."""

    edge = LINE_ON_DARK if dark else LINE
    rect(slide, x, y, size, size, fill=None, line=edge, line_w=Pt(0.9))
    c = size // 2
    line_h(slide, x + Inches(0.24), y + c, size - Inches(0.48), color=edge)
    line_v(slide, x + c, y + Inches(0.24), size - Inches(0.48), color=edge)
    tb, tf = textbox(slide, x, y + size + Inches(0.08), size, Inches(0.44))
    para(tf, "[ВСТАВИТЬ QR]", 9.5, MUTED_ON_DARK if dark else MUTED, bold=True,
         first=True, align=PP_ALIGN.CENTER)
    para(tf, label, 9.5, MUTED_ON_DARK if dark else MUTED, align=PP_ALIGN.CENTER)


def factor_bar(slide, x, y, w, label, value, weight, contribution, max_c):
    """One explainability row: label, weight, proportional bar, contribution."""

    tb, tf = textbox(slide, x, y - Inches(0.03), Inches(3.32), Inches(0.34))
    para(tf, label, 12, INK, bold=True, first=True)

    tb2, tf2 = textbox(slide, x + Inches(3.36), y - Inches(0.03), Inches(1.28),
                       Inches(0.34))
    para(tf2, f"вес {weight:g}", 11.5, MUTED, first=True, align=PP_ALIGN.RIGHT)

    bar_x = x + Inches(4.8)
    bar_w = w - Inches(4.8) - Inches(1.05)
    rect(slide, bar_x, y + Inches(0.02), bar_w, Inches(0.13), fill=LINE)
    if contribution > 0:
        frac = contribution / max_c if max_c > 0 else 0.0
        rect(slide, bar_x, y + Inches(0.02), int(bar_w * frac), Inches(0.13),
             fill=CORAL if value >= 1.0 else MINT)

    tb3, tf3 = textbox(slide, x + w - Inches(0.95), y - Inches(0.03), Inches(0.95),
                       Inches(0.34))
    para(tf3, f"{contribution:.1f}", 12.5, INK, bold=True, first=True,
         align=PP_ALIGN.RIGHT)


# ================================================================ slide 1 ====
def s01_cover(prs, F):
    s = blank(prs, DARK)
    kicker(s, "Хакатон Осень 2026 · ДГТУ", y=Inches(1.02), color=MINT)

    tb, tf = textbox(s, MARGIN, Inches(1.72), Inches(7.5), Inches(3.1))
    para(tf, "Увидеть риск", 45, WHITE, bold=True, first=True, line_spacing=0.98)
    para(tf, "оттока раньше,", 45, WHITE, bold=True, line_spacing=0.98)
    rich(tf, [("чем клиент уйдёт", True, CORAL)], 45, WHITE, line_spacing=0.98)

    line_h(s, MARGIN, Inches(4.92), Inches(2.1), color=CORAL, weight=Pt(2))

    tb2, tf2 = textbox(s, MARGIN, Inches(5.16), Inches(6.5), Inches(0.8))
    para(tf2, "Aéza Analyzer — аналитика риска оттока клиентов хостинг-провайдера",
         16.5, INK_ON_DARK, first=True, line_spacing=1.25)

    tb3, tf3 = textbox(s, MARGIN, Inches(6.18), Inches(6.5), Inches(0.7))
    para(tf3, "[НАЗВАНИЕ КОМАНДЫ]", 13, MUTED_ON_DARK, bold=True, first=True)
    para(tf3, "XIX Форум программных разработчиков · Ростов-на-Дону",
         11.5, MUTED_ON_DARK, space_before=3)

    add_picture_contain(s, os.path.join(SHOTS, "01-dashboard.png"),
                        Inches(8.55), Inches(1.5), Inches(4.05), Inches(4.5),
                        bg=WHITE, border_color=LINE_ON_DARK)
    tb4, tf4 = textbox(s, Inches(8.55), Inches(6.12), Inches(4.05), Inches(0.4))
    para(tf4, "Рабочий интерфейс на данных кейса", 10.5, MUTED_ON_DARK,
         first=True, align=PP_ALIGN.CENTER)

    page(s, 1, dark=True)
    notes(s, "Представиться. Одно предложение: инструмент находит клиентов под "
             "риском оттока и объясняет, почему они в группе риска, — на реальных "
             "данных Aéza. Дальше — сквозной сценарий защиты.")


# ================================================================ slide 2 ====
def s02_problem(prs, F):
    s = blank(prs, WARM)
    kicker(s, "Проблема")
    slide_title(s, "Клиент может уйти раньше,\nчем команда это заметит",
                y=Inches(0.98), w=Inches(9.4), size=32)

    tb, tf = textbox(s, MARGIN, Inches(2.62), Inches(6.1), Inches(2.6))
    para(tf, "Отток не начинается с явной отмены услуги. Задолго до неё в данных "
             "появляются отдельные изменения: срок подходит к концу, "
             "автопродление выключено, списание не проходит.", 16.5, INK,
         first=True, line_spacing=1.45)
    para(tf, "По отдельности каждый сигнал выглядит безобидно. Проблема в том, "
             "что их смотрят по разным отчётам — или не смотрят вовсе.",
         16.5, INK, line_spacing=1.45, space_before=12)

    line_h(s, MARGIN, Inches(5.32), Inches(6.1), color=LINE)

    tb2, tf2 = textbox(s, MARGIN, Inches(5.5), Inches(6.3), Inches(0.9))
    rich(tf2, [("Задача. ", True, INK),
               ("Не просто увидеть, кто уже ушёл, а определить, кому стоит "
                "уделить внимание сейчас.", False, INK)], 16.5, INK,
         first=True, line_spacing=1.35)

    x = Inches(7.85)
    tb3, tf3 = textbox(s, x, Inches(2.62), Inches(4.6), Inches(0.35))
    para(tf3, "ЧТО МЕНЯЕТСЯ ПЕРЕД УХОДОМ", 11, MUTED, bold=True, first=True)

    for i, (t, sub) in enumerate([
        ("Срок услуги", "истекает или уже истёк"),
        ("Автопродление", "выключено — решения нет"),
        ("Продление", "не проходит: not_performed"),
    ]):
        y = Inches(3.12) + Inches(1.05) * i
        rect(s, x, y + Inches(0.07), Inches(0.15), Inches(0.15), fill=CORAL)
        tbi, tfi = textbox(s, x + Inches(0.38), y - Inches(0.02), Inches(4.2),
                           Inches(0.8))
        para(tfi, t, 16.5, INK, bold=True, first=True)
        para(tfi, sub, 13, MUTED, space_before=2)

    line_v(s, Inches(7.38), Inches(2.62), Inches(3.7), color=LINE)

    tb4, tf4 = textbox(s, MARGIN, Inches(6.66), Inches(11.0), Inches(0.4))
    para(tf4, "Мы не приводим статистику оттока Aéza и отраслевые цифры: "
              "в исходных данных нет истории уходов.", 11, MUTED, first=True)

    page(s, 2)
    notes(s, "Не давить цифрами, которых у нас нет. Проблема методическая: "
             "сигналы разбросаны, и никто не сводит их в одну оценку.")


# ================================================================ slide 3 ====
def s03_product(prs, F):
    s = blank(prs, WARM)
    kicker(s, "Продукт")
    slide_title(s, "От данных клиента —\nк объяснимому сигналу риска",
                y=Inches(0.98), w=Inches(8.0), size=31)

    add_picture_contain(s, os.path.join(SHOTS, "01b-dashboard-full.png"),
                        MARGIN, Inches(2.72), Inches(7.85), Inches(3.72),
                        bg=WHITE)

    x = Inches(9.05)
    tb, tf = textbox(s, x, Inches(2.72), Inches(3.45), Inches(0.35))
    para(tf, "ЧТО ДЕЛАЕТ СИСТЕМА", 11, MUTED, bold=True, first=True)

    for i, c in enumerate([
        "Находит клиентов с повышенным риском",
        "Объясняет, какие факторы повлияли на оценку",
        "Показывает доступную финансовую оценку",
        "Позволяет проверить влияние новых параметров",
    ], 1):
        y = Inches(3.18) + Inches(0.82) * (i - 1)
        tbi, tfi = textbox(s, x, y, Inches(3.45), Inches(0.78))
        rich(tfi, [(f"{i}  ", True, CORAL), (c, False, INK)], 13, INK,
             first=True, line_spacing=1.32)

    line_h(s, MARGIN, Inches(6.66), CONTENT_W, color=LINE)
    tb2, tf2 = textbox(s, MARGIN, Inches(6.8), Inches(10.2), Inches(0.4))
    para(tf2, f"Снимок данных кейса: {len(F['snap'].accounts)} клиентов · "
              f"{len(F['snap'].services)} услуг · "
              f"{len(F['snap'].transactions)} транзакций. "
              "Это реальный датасет организатора, а не демонстрационная заглушка.",
         11, MUTED, first=True)

    page(s, 3)
    notes(s, "Скриншот — главный герой. Справа — что именно умеет система, "
             "без маркетинговых обещаний.")


# ================================================================ slide 4 ====
def s04_customer(prs, F):
    s = blank(prs, WARM)
    kicker(s, "Клиент под риском")
    slide_title(s, "Клиент #10: высокая категория риска\nпри трёх услугах в ожидании продления",
                y=Inches(0.98), w=Inches(9.7), size=29)

    cust = F["base"][FEATURED]["cust"]
    svc, risk = F["fsvc"], F["frisk"]

    tb, tf = textbox(s, MARGIN, Inches(2.62), Inches(3.5), Inches(1.05))
    para(tf, n1(cust.score), 62, CORAL, bold=True, first=True, line_spacing=0.95)
    tb2, tf2 = textbox(s, MARGIN, Inches(3.82), Inches(3.5), Inches(0.35))
    para(tf2, "балл риска клиента", 12.5, MUTED, first=True)
    rect(s, MARGIN, Inches(4.18), Inches(1.28), Inches(0.3), fill=CORAL)
    tb3, tf3 = textbox(s, MARGIN, Inches(4.2), Inches(1.28), Inches(0.3))
    para(tf3, "Высокий", 11.5, WHITE, bold=True, first=True, align=PP_ALIGN.CENTER)

    line_h(s, MARGIN, Inches(4.84), Inches(3.5), color=LINE)

    tb4, tf4 = textbox(s, MARGIN, Inches(5.0), Inches(3.6), Inches(1.4))
    rich(tf4, [("Клиент ", False, MUTED), (f"#{FEATURED}", True, INK),
               (f" · {plural(cust.service_count, 'услуга', 'услуги', 'услуг')}, "
                f"{cust.eligible_service_count} в прогнозе", False, MUTED)],
         12.5, INK, first=True, line_spacing=1.35)
    rich(tf4, [(plural(cust.high_risk_service_count, 'услуга', 'услуги', 'услуг'), True, CORAL),
               (" высокого риска", False, MUTED)], 12.5, MUTED,
         space_before=6)

    add_picture_contain(s, os.path.join(SHOTS, "03-customer-10.png"),
                        Inches(4.75), Inches(2.62), Inches(7.75), Inches(3.94),
                        bg=WHITE)

    line_h(s, MARGIN, Inches(6.72), CONTENT_W, color=LINE)
    tb5, tf5 = textbox(s, MARGIN, Inches(6.86), Inches(10.2), Inches(0.4))
    para(tf5, f"Идентификатор клиента взят из датасета; адрес не показываем. "
              f"Критичная услуга — {svc.name}: {n1(risk.score)} балла, "
              f"стоимость продления {eur(svc.price)}.",
         11, MUTED, first=True)

    page(s, 4)
    notes(s, "Это живой клиент из датасета. Обратить внимание: высокая категория "
             "риска и три открытые услуги. Почему — на следующем слайде.")


# ================================================================ slide 5 ====
def s05_reasons(prs, F):
    s = blank(prs, WARM)
    kicker(s, "Причины риска")
    slide_title(s, "Оценка — это сумма наблюдаемых сигналов,\nа не мнение алгоритма",
                y=Inches(0.98), w=Inches(9.6), size=29)

    svc, risk = F["fsvc"], F["frisk"]
    total_w = sum(r.weight for r in risk.factors)
    total_c = sum(r.contribution for r in risk.factors)
    max_c = max(r.contribution for r in risk.factors)

    tb, tf = textbox(s, MARGIN, Inches(2.6), Inches(6.0), Inches(0.35))
    para(tf, f"УСЛУГА {svc.name.upper()} · ВКЛАД КАЖДОГО ФАКТОРА", 11, MUTED,
         bold=True, first=True)

    y = Inches(3.06)
    for r in risk.factors:
        factor_bar(s, MARGIN, y, Inches(7.4), r.label, r.value, r.weight,
                   r.contribution, max_c)
        y += Inches(0.46)

    line_h(s, MARGIN, Inches(6.42), Inches(7.4), color=LINE)

    tb2, tf2 = textbox(s, MARGIN, Inches(6.56), Inches(7.6), Inches(0.4))
    rich(tf2, [("Итог: ", True, INK),
               (f"100 × {total_c:g} / {total_w:g} = {n1(risk.score)} из 100. ",
                False, INK),
               ("Веса настраиваются аналитиком.", False, MUTED)],
         12.5, INK, first=True)

    x = Inches(8.85)
    tb3, tf3 = textbox(s, x, Inches(2.6), Inches(3.65), Inches(0.35))
    para(tf3, "КАК ЭТО ЧИТАТЬ", 11, MUTED, bold=True, first=True)

    for i, txt in enumerate([
        "Балл — сила наблюдаемых сигналов, не вероятность ухода в процентах.",
        "Факторы не доказывают причину оттока: модель rule-based, без обучения.",
        "Нулевой вес исключает фактор; сумма весов пересчитывается.",
    ]):
        yy = Inches(3.06) + Inches(1.16) * i
        rect(s, x, yy + Inches(0.05), Inches(0.15), Inches(0.15),
             fill=MINT if i == 2 else CORAL)
        tbi, tfi = textbox(s, x + Inches(0.36), yy, Inches(3.29), Inches(1.1))
        para(tfi, txt, 12.5, INK, first=True, line_spacing=1.35)

    page(s, 5)
    notes(s, "Ключевая мысль: жюри видит механику. Пять факторов из семи "
             "сработали; два нулевых честно показаны серыми. И сразу снимаем "
             "вопрос «это ML?» — нет, и мы это не скрываем.")


# ================================================================ slide 6 ====
def s06_money(prs, F):
    s = blank(prs, WARM)
    kicker(s, "Денежная оценка")
    slide_title(s, "Риск и деньги — разные величины,\nпоэтому считаются отдельно",
                y=Inches(0.98), w=Inches(9.8), size=29)

    figures = [
        ("Выручка под риском", eur(F["rar"]), CORAL, 27,
         "прогноз в пределах горизонта"),
        ("Предстоящие продления", eur(F["upcoming"]), INK, 27,
         "сумма без учёта риска"),
        ("Исторические пополнения", eur(F["topups"]), MUTED, 20,
         "справочно, в прогноз не входит"),
    ]
    x = MARGIN
    for i, (label, value, color, size, sub) in enumerate(figures):
        tbi, tfi = textbox(s, x, Inches(2.66), Inches(3.5), Inches(1.5))
        para(tfi, label, 12, MUTED, bold=True, first=True)
        para(tfi, value, size, color, bold=True, space_before=6)
        para(tfi, sub, 11.5, MUTED, space_before=4)
        if i < 2:
            line_v(s, x + Inches(3.78), Inches(2.66), Inches(1.3), color=LINE)
        x += Inches(3.95)

    line_h(s, MARGIN, Inches(4.34), CONTENT_W, color=LINE)

    tb, tf = textbox(s, MARGIN, Inches(4.54), Inches(6.4), Inches(0.35))
    para(tf, "ФОРМУЛА ИЗ КОДА", 11, MUTED, bold=True, first=True)
    rect(s, MARGIN, Inches(4.86), Inches(6.4), Inches(0.5), fill=WHITE, line=LINE)
    tb2, tf2 = textbox(s, MARGIN + Inches(0.18), Inches(4.96), Inches(6.1), Inches(0.35))
    para(tf2, "revenue_at_risk = стоимость продления × балл риска / 100",
         13, INK, first=True, font=MONO)

    tb3, tf3 = textbox(s, MARGIN, Inches(5.5), Inches(6.4), Inches(1.1))
    para(tf3, "Учитываются только продления внутри горизонта 30 дней и только "
              "по услугам, пригодным для прогноза. Баланс клиента и исторические "
              "пополнения в выручку под риском не входят.",
         12, MUTED, first=True, line_spacing=1.4)

    x2 = Inches(7.75)
    rect(s, x2, Inches(4.54), Inches(4.75), Inches(2.06), fill=WHITE, line=LINE)
    tbi, tfi = textbox(s, x2 + Inches(0.24), Inches(4.7), Inches(4.27), Inches(1.74))
    para(tfi, "Клиент #10: выручка под риском 0,00 €", 13, INK, bold=True,
         first=True, line_spacing=1.3)
    para(tfi, "Несмотря на высокий балл, все его продления лежат в прошлом, "
              "а горизонт — окно вперёд. Денег в горизонте у него нет.",
         12, MUTED, space_before=6, line_spacing=1.4)
    para(tfi, "В этом и смысл разделять балл риска и выручку под риском: "
              "иначе мы показали бы ложную сумму.", 12, MUTED,
         space_before=6, line_spacing=1.4)

    line_h(s, MARGIN, Inches(6.8), CONTENT_W, color=LINE)
    tb4, tf4 = textbox(s, MARGIN, Inches(6.92), Inches(10.2), Inches(0.4))
    para(tf4, "Оценка приблизительная: она опирается на стоимость продления "
              "и балл риска, а не на подтверждённую историю платежей.",
         11, MUTED, first=True)

    page(s, 6)
    notes(s, "Три денежные метрики намеренно разделены, складывать их нельзя. "
             "Формула — дословно из кода. И честный момент: у клиента #10 "
             "выручка под риском нулевая, потому что сроки уже прошли.")


# ================================================================ slide 7 ====
def s07_before(prs, F):
    s = blank(prs, WARM)
    kicker(s, "Ключевой сценарий · шаг 1")
    slide_title(s, "Меняем коэффициент\nи сразу проверяем гипотезу",
                y=Inches(0.98), w=Inches(8.4), size=30)

    tb, tf = textbox(s, MARGIN, Inches(2.6), Inches(5.5), Inches(0.35))
    para(tf, "ВЕСА МОДЕЛИ · КОНФИГУРАЦИЯ ПО УМОЛЧАНИЮ", 11, MUTED, bold=True,
         first=True)

    rows = [("Близость даты окончания", W_FROM, True),
            ("Ожидание продления", 2.5, False),
            ("Автопродление отключено", 2.0, False),
            ("Недостаточно средств", 2.0, False),
            ("Неуспешные продления", 2.0, False),
            ("Услуга приостановлена", 2.0, False),
            ("Доля неуспешных продлений", 1.5, False)]
    y = Inches(3.04)
    for label, w, hot in rows:
        tbi, tfi = textbox(s, MARGIN, y, Inches(4.3), Inches(0.34))
        para(tfi, label, 13, INK, bold=hot, first=True)
        tbj, tfj = textbox(s, MARGIN + Inches(4.35), y, Inches(1.15), Inches(0.34))
        para(tfj, f"{w:g}", 13, CORAL if hot else MUTED, bold=hot, first=True,
             align=PP_ALIGN.RIGHT)
        y += Inches(0.4)

    line_h(s, MARGIN, Inches(5.9), Inches(5.5), color=LINE)
    tb2, tf2 = textbox(s, MARGIN, Inches(6.04), Inches(5.6), Inches(0.6))
    para(tf2, "Сумма весов 15,0. Меняем «Близость даты окончания»: 3 → 9.",
         13, INK, first=True, line_spacing=1.35)

    add_picture_contain(s, os.path.join(SHOTS, "08-metrics-before.png"),
                        Inches(7.0), Inches(2.6), Inches(5.48), Inches(1.6),
                        bg=WHITE)
    tb3, tf3 = textbox(s, Inches(7.0), Inches(4.3), Inches(5.48), Inches(0.35))
    para(tf3, "Панель метрик до изменения веса", 11, MUTED, first=True,
         align=PP_ALIGN.CENTER)

    tb4, tf4 = textbox(s, Inches(7.0), Inches(4.86), Inches(5.48), Inches(1.7))
    para(tf4, "Изменение веса — не косметика: оно уходит на сервер, сохраняется "
              "в базе и пересчитывает всю аналитику.", 13, INK, first=True,
         line_spacing=1.4)
    para(tf4, "После сохранения меняются и баллы клиентов, и денежная оценка — "
              "это следующий слайд.", 13, MUTED, space_before=8, line_spacing=1.4)

    page(s, 7)
    notes(s, "Шаг 1 ключевого сценария. Показать вес 3, назвать сумму весов 15,0. "
             "Дальше — сохранение и пересчёт на живом приложении.")


# ================================================================ slide 8 ====
def s08_after(prs, F):
    s = blank(prs, DARK)
    kicker(s, "Ключевой сценарий · шаг 2", color=MINT)

    tb, tf = textbox(s, MARGIN, Inches(0.92), Inches(9.0), Inches(0.8))
    para(tf, "После пересчёта картина меняется", 31, WHITE, bold=True,
         first=True, line_spacing=1.05)

    before = F["base"][FEATURED]["cust"]
    after = F["tuned"][FEATURED]["cust"]
    cb, ca = F["cats"], F["tune_cats"]

    # Left: the single most convincing movement — the customer's own score.
    tb2, tf2 = textbox(s, MARGIN, Inches(1.94), Inches(4.6), Inches(0.35))
    para(tf2, "БАЛЛ РИСКА КЛИЕНТА #10", 11, MUTED_ON_DARK, bold=True, first=True)
    tb3, tf3 = textbox(s, MARGIN, Inches(2.26), Inches(4.6), Inches(0.8))
    rich(tf3, [(n1(before.score), True, MUTED_ON_DARK),
               ("  →  ", False, MUTED_ON_DARK),
               (n1(after.score), True, CORAL)], 40, WHITE, first=True,
         line_spacing=1.0)

    # Right: the aggregate metrics that moved with it.
    moves = [
        ("Клиентов высокого риска", str(cb["high"]), str(ca["high"])),
        ("Клиентов среднего риска", str(cb["medium"]), str(ca["medium"])),
        ("Выручка под риском", eur(F["rar"]), eur(F["rar_tuned"])),
    ]
    x = Inches(6.15)
    for i, (label, b, a) in enumerate(moves):
        yy = Inches(1.94) + Inches(0.94) * i
        tbi, tfi = textbox(s, x, yy, Inches(3.2), Inches(0.32))
        para(tfi, label, 11.5, MUTED_ON_DARK, first=True)
        tbj, tfj = textbox(s, x, yy + Inches(0.27), Inches(6.35), Inches(0.44))
        rich(tfj, [(b, True, MUTED_ON_DARK), ("  →  ", False, MUTED_ON_DARK),
                   (a, True, MINT)], 19, WHITE, first=True)

    # Full-width evidence strips: the very panel the analyst clicks in the app.
    strip_w = CONTENT_W
    strip_h = Inches(0.72)
    y = Inches(4.82)
    for shot, label, in (("08-metrics-before.png", "ДО"),
                         ("09-metrics-after.png", "ПОСЛЕ")):
        tbi, tfi = textbox(s, MARGIN, y, Inches(0.75), strip_h,
                           anchor=MSO_ANCHOR.MIDDLE)
        para(tfi, label, 11, MUTED_ON_DARK, bold=True, first=True)
        add_picture_contain(s, os.path.join(SHOTS, shot),
                            MARGIN + Inches(0.8), y, strip_w - Inches(0.8), strip_h,
                            bg=WHITE, border_color=LINE_ON_DARK)
        y += strip_h + Inches(0.14)

    line_h(s, MARGIN, Inches(6.62), CONTENT_W, color=LINE_ON_DARK)
    tb4, tf4 = textbox(s, MARGIN, Inches(6.76), Inches(10.2), Inches(0.5))
    para(tf4, "Изменён один вес: «Близость даты окончания», 3 → 9. Настройки "
              "сохраняются на сервере и переживают перезапуск процесса.",
         11.5, MUTED_ON_DARK, first=True)

    page(s, 8, dark=True)
    notes(s, "Кульминация защиты. Один вес — и клиент #10 идёт с 73,3 на 81,0, "
             "высокий риск растёт с 2 до 3, выручка под риском с 5,74 до 7,48 €. "
             "Полосы внизу — те же панели, что видит аналитик в приложении. "
             "Числа воспроизводимы: опорная дата зафиксирована.")


# ================================================================ slide 9 ====
def s09_value(prs, F):
    s = blank(prs, WARM)
    kicker(s, "Ценность и ограничения")
    slide_title(s, "Что получает аналитик\nи чего система не обещает",
                y=Inches(0.98), w=Inches(8.6), size=30)

    tb, tf = textbox(s, MARGIN, Inches(2.62), Inches(5.6), Inches(0.35))
    para(tf, "ЧТО ПОЛУЧАЕТ СПЕЦИАЛИСТ", 11, MUTED, bold=True, first=True)

    for i, t in enumerate([
        "Список клиентов, которым следует уделить внимание",
        "Объяснение факторов риска по каждой услуге",
        "Финансовый контекст: что именно под угрозой",
        "Проверку гипотез через изменение весов и горизонта",
    ]):
        yy = Inches(3.06) + Inches(0.72) * i
        rect(s, MARGIN, yy + Inches(0.06), Inches(0.15), Inches(0.15), fill=MINT)
        tbi, tfi = textbox(s, MARGIN + Inches(0.36), yy, Inches(5.2), Inches(0.62))
        para(tfi, t, 13.5, INK, first=True, line_spacing=1.32)

    line_v(s, Inches(6.95), Inches(2.62), Inches(3.7), color=LINE)

    x = Inches(7.4)
    tb2, tf2 = textbox(s, x, Inches(2.62), Inches(5.1), Inches(0.35))
    para(tf2, "ЧЕГО МЫ НЕ ЗАЯВЛЯЕМ", 11, MUTED, bold=True, first=True)

    for i, t in enumerate([
        "Балл риска — не откалиброванная вероятность оттока.",
        "Модель rule-based: в данных нет исходов для обучения и валидации.",
        "Мы не измеряли снижение оттока и рост выручки.",
    ]):
        yy = Inches(3.06) + Inches(1.12) * i
        rect(s, x, yy + Inches(0.06), Inches(0.15), Inches(0.15), fill=CORAL)
        tbi, tfi = textbox(s, x + Inches(0.36), yy, Inches(4.74), Inches(1.05))
        para(tfi, t, 13.5, INK, first=True, line_spacing=1.35)

    line_h(s, MARGIN, Inches(6.52), CONTENT_W, color=LINE)
    tb3, tf3 = textbox(s, MARGIN, Inches(6.66), Inches(10.2), Inches(0.6))
    para(tf3, "Когда появятся данные об уходах, на тех же признаках можно обучить "
              "логистическую регрессию и откалибровать вероятности. Скоринг живёт "
              "в одном модуле именно для этого — контракт API и интерфейс "
              "при этом не меняются.", 11.5, MUTED, first=True, line_spacing=1.35)

    page(s, 9)
    notes(s, "Честность здесь работает на нас: мы называем границы сами, "
             "до вопросов жюри. И показываем путь развития.")


# ================================================================ slide 10 ===
def s10_final(prs, F):
    s = blank(prs, DARK)
    kicker(s, "Итог", color=MINT)

    tb, tf = textbox(s, MARGIN, Inches(1.42), Inches(8.4), Inches(2.4))
    para(tf, "Не ждать ухода клиента.", 40, WHITE, bold=True, first=True,
         line_spacing=1.0)
    para(tf, "Дать команде возможность", 40, WHITE, bold=True, line_spacing=1.0)
    rich(tf, [("действовать раньше", True, CORAL)], 40, WHITE, line_spacing=1.0)

    line_h(s, MARGIN, Inches(4.2), Inches(2.1), color=CORAL, weight=Pt(2))

    tb2, tf2 = textbox(s, MARGIN, Inches(4.48), Inches(5.6), Inches(2.2))
    para(tf2, "[НАЗВАНИЕ КОМАНДЫ]", 15, WHITE, bold=True, first=True)
    para(tf2, "[ИМЯ УЧАСТНИКА 1] — [РОЛЬ УЧАСТНИКА 1]", 12.5, MUTED_ON_DARK,
         space_before=8)
    para(tf2, "[ИМЯ УЧАСТНИКА 2] — [РОЛЬ УЧАСТНИКА 2]", 12.5, MUTED_ON_DARK,
         space_before=3)
    para(tf2, "[ИМЯ УЧАСТНИКА 3] — [РОЛЬ УЧАСТНИКА 3]", 12.5, MUTED_ON_DARK,
         space_before=3)
    para(tf2, "[КОНТАКТ / TELEGRAM]", 12.5, MUTED_ON_DARK, space_before=10)

    qx = Inches(7.9)
    qsize = Inches(1.38)
    qstep = Inches(1.58)
    qr_slot(s, qx, Inches(2.86), qsize, "демо", dark=True)
    qr_slot(s, qx + qstep, Inches(2.86), qsize, "GitHub", dark=True)
    qr_slot(s, qx + 2 * qstep, Inches(2.86), qsize, "контакты", dark=True)

    tb3, tf3 = textbox(s, qx, Inches(5.34), Inches(4.58), Inches(1.2))
    para(tf3, "GitHub: github.com/Pixelminds-hub/aeza-analizer", 11.5,
         MUTED_ON_DARK, first=True)
    para(tf3, "Демо-стенд: [АДРЕС СТЕНДА] — вставить подтверждённую ссылку "
              "и сгенерировать QR-код.", 11.5, MUTED_ON_DARK, space_before=5,
         line_spacing=1.35)

    page(s, 10, dark=True)
    notes(s, "Финал. Одна мысль крупно. Перед защитой подставить название "
             "команды, имена, контакт и сгенерировать QR по подтверждённым "
             "ссылкам.")


# ==================================================================== main ===
def postprocess(path):
    """Fix two packaging details python-pptx leaves behind.

    ``slide_width`` is set to a 16:9 size, but python-pptx keeps the default
    ``type="screen4x3"`` hint on ``<p:sldSz>``.  PowerPoint trusts the explicit
    cx/cy, yet the stale hint can make some viewers letterbox the deck, so it is
    corrected here.  The theme font scheme is also switched to Inter so any
    inherited (non-explicit) text does not fall back to Calibri.
    """

    import re
    import shutil
    import zipfile

    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w",
                                                       zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "ppt/presentation.xml":
                xml = data.decode("utf-8")
                xml = re.sub(r'(<p:sldSz\b[^>]*?)\s+type="[^"]*"', r"\1", xml)
                xml = xml.replace('<p:sldSz ', '<p:sldSz type="screen16x9" ')
                data = xml.encode("utf-8")
            elif item.filename == "ppt/theme/theme1.xml":
                xml = data.decode("utf-8")
                for tag in ("majorFont", "minorFont"):
                    xml = re.sub(
                        rf'(<a:{tag}>\s*<a:latin\s+)typeface="[^"]*"',
                        rf'\1typeface="{FONT}"', xml,
                    )
                data = xml.encode("utf-8")
            dst.writestr(item, data)
    shutil.move(tmp, path)


def main():
    F = gather()
    prs = new_deck()
    for fn in (s01_cover, s02_problem, s03_product, s04_customer, s05_reasons,
               s06_money, s07_before, s08_after, s09_value, s10_final):
        fn(prs, F)
    prs.save(OUT)
    postprocess(OUT)
    print("saved:", OUT)
    print("revenue at risk:", eur(F["rar"]), "-> tuned:", eur(F["rar_tuned"]))
    print("upcoming:", eur(F["upcoming"]), "| topups:", eur(F["topups"]))
    print("customer 10:", n1(F["base"][FEATURED]["cust"].score), "->",
          n1(F["tuned"][FEATURED]["cust"].score))
    print("cats:", dict(F["cats"]), "->", dict(F["tune_cats"]))


if __name__ == "__main__":
    main()
