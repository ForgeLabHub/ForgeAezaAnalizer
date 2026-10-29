#!/usr/bin/env python3
"""Сборка PDF из документации проекта (и проверка её полноты).

Один и тот же файл лежит во всех проектах ForgeLabHub: правки должны быть
синхронными, чтобы `make docs-pdf` вёл себя одинаково везде.

Что делает:

  python tools/docs_pdf.py            # собрать PDF (docs/pdf/<lang>/...)
  python tools/docs_pdf.py --check    # проверить, что у каждого документа есть
                                      # перевод и что весь Markdown собран в PDF
  python tools/docs_pdf.py --lang en  # только один язык

Правила раскладки, которые проверяются машиной:

  README.md, BUILD.md, CONTRIBUTING.md …   — основной язык репозитория
  docs/**/*.md                            — основной язык
  docs/en/**/*.md                         — английский перевод (для проектов,
                                            где основной язык русский)
  docs/ru/**/*.md                         — русский перевод (для проектов,
                                            где основной язык английский)

PDF кладётся в docs/pdf/<lang>/ по тому же относительному пути: у
docs/modules/auth.md появляется docs/pdf/ru/modules/auth.pdf.

Зависимости нужны только для сборки PDF (markdown + weasyprint); готовые PDF
лежат в репозитории, поэтому читателю они не нужны.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PDF_DIR = DOCS / "pdf"

# Документы в корне, которые считаются частью документации.
# Документы корня, которые входят в двуязычный набор. CONTRIBUTING/SECURITY/
# ARCHITECTURE держим в docs/ (в двух языках), в корне остаётся ссылка на них.
ROOT_DOCS = ["README.md", "BUILD.md"]

CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
  @bottom-center {
    content: counter(page) " / " counter(pages);
    font-family: "DejaVu Sans", sans-serif; font-size: 8pt; color: #666;
  }
}
@page :first { @bottom-center { content: none; } }
body {
  font-family: "DejaVu Sans", sans-serif;
  font-size: 9.6pt; line-height: 1.45; color: #1a1a1a;
  hyphens: auto;
}
h1 { font-size: 17pt; margin: 0 0 4mm 0; padding-bottom: 2mm;
     border-bottom: 1.2pt solid #2b5c8a; color: #17395c; page-break-after: avoid; }
h2 { font-size: 13pt; margin: 6mm 0 2mm 0; color: #17395c; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 4.5mm 0 1.5mm 0; page-break-after: avoid; }
h4 { font-size: 10pt; margin: 3.5mm 0 1mm 0; page-break-after: avoid; }
p, ul, ol, table, pre, blockquote { margin: 0 0 2.4mm 0; }
ul, ol { padding-left: 5.5mm; }
li { margin-bottom: 0.9mm; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.6pt;
       background: #f2f4f7; padding: 0 1px; border-radius: 2px; }
pre { background: #f6f8fa; border: 0.6pt solid #dfe3e8; border-radius: 2mm;
      padding: 2.2mm 2.6mm; white-space: pre-wrap; word-wrap: break-word;
      page-break-inside: avoid; }
pre code { background: none; font-size: 8.2pt; }
table { border-collapse: collapse; width: 100%; font-size: 8.8pt;
        page-break-inside: avoid; }
th, td { border: 0.6pt solid #c9d1d9; padding: 1.3mm 2mm; text-align: left;
         vertical-align: top; }
th { background: #eef2f6; font-weight: bold; }
blockquote { border-left: 2.4pt solid #b9c6d4; margin-left: 0; padding-left: 3mm;
             color: #40484f; }
a { color: #1f4f80; text-decoration: none; }
hr { border: none; border-top: 0.6pt solid #d7dde3; margin: 4mm 0; }
img { max-width: 100%; }
.meta { color: #666; font-size: 8.4pt; margin-bottom: 6mm; }
"""

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "toc", "attr_list", "md_in_html"]


# --- раскладка ---------------------------------------------------------------


def primary_lang() -> str:
    """Основной язык репозитория: русский, если docs/ru есть — иначе наоборот."""
    return "en" if (DOCS / "ru").is_dir() else "ru"


def translation_lang() -> str:
    return "en" if primary_lang() == "ru" else "ru"


def doc_files(lang: str) -> list[Path]:
    """Документы языка lang, для которых ожидается PDF."""
    main = primary_lang()
    files: list[Path] = []
    if lang == main:
        for name in ROOT_DOCS:
            p = ROOT / name
            if p.is_file():
                files.append(p)
        for p in sorted(DOCS.rglob("*.md")):
            rel = p.relative_to(DOCS)
            if rel.parts[0] in ("en", "ru", "pdf"):
                continue
            files.append(p)
    else:
        base = DOCS / lang
        if base.is_dir():
            for p in sorted(base.rglob("*.md")):
                files.append(p)
    return files


def doc_id(path: Path, lang: str) -> str:
    """Относительный путь без учёта языковой папки — ключ для сверки пар."""
    if path.parent == ROOT:
        return path.stem
    rel = path.relative_to(DOCS)
    parts = [p for p in rel.parts if p not in ("en", "ru")]
    return str(Path(*parts).with_suffix(""))


def counterpart(path: Path, lang: str) -> Path | None:
    """Файл-перевод того же документа в другом языке.

    Документы корня (README.md, BUILD.md …) переводятся в docs/<lang>/README.md:
    так у перевода один адрес независимо от того, что лежит в корне.
    """
    other = DOCS / ("en" if lang == "ru" else "ru")
    if path.parent == ROOT:
        cand = other / f"{path.stem}.md"
        return cand if cand.exists() else None
    rel = path.relative_to(DOCS)
    parts = [p for p in rel.parts if p not in ("en", "ru")]
    cand = other.joinpath(*parts)
    return cand if cand.exists() else None


def pdf_path(path: Path, lang: str) -> Path:
    if path.parent == ROOT:
        return PDF_DIR / lang / f"{path.stem}.pdf"
    rel = path.relative_to(DOCS)
    parts = [p for p in rel.parts if p not in ("en", "ru")]
    return PDF_DIR / lang / str(Path(*parts).with_suffix(".pdf"))


# --- рендеринг ---------------------------------------------------------------


def title_of(text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


def render_html(md_text: str, title: str, project: str, lang: str, source: str) -> str:
    import markdown

    body = markdown.markdown(md_text, extensions=MD_EXTENSIONS, output_format="html5")
    lang_attr = "ru" if lang == "ru" else "en"
    label = "Документ" if lang == "ru" else "Document"
    built = os.environ.get("SOURCE_DATE_EPOCH")
    stamp = (
        dt.datetime.fromtimestamp(int(built), dt.timezone.utc).strftime("%Y-%m-%d")
        if built
        else dt.date.today().isoformat()
    )
    meta = f'{label}: <code>{html.escape(source)}</code> · {project} · {stamp}'
    return f"""<!doctype html>
<html lang="{lang_attr}"><head><meta charset="utf-8">
<title>{html.escape(title)} — {html.escape(project)}</title>
<style>{CSS}</style></head>
<body><div class="meta">{meta}</div>
{body}
</body></html>"""


def write_pdf(html_text: str, out: Path) -> None:
    from weasyprint import HTML

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = HTML(string=html_text, base_url=str(ROOT)).render()
    doc.metadata.title = out.stem
    doc.write_pdf(str(out))


# --- команды -----------------------------------------------------------------


def build(langs: list[str]) -> int:
    project = ROOT.name
    total = 0
    for lang in langs:
        files = doc_files(lang)
        if not files:
            print(f"[{lang}] документов нет — пропуск")
            continue
        for f in files:
            text = f.read_text(encoding="utf-8")
            rel = f.relative_to(ROOT).as_posix()
            out = pdf_path(f, lang)
            write_pdf(render_html(text, title_of(text, f.stem), project, lang, rel), out)
            total += 1
        print(f"[{lang}] собрано PDF: {len(files)}")
    print(f"всего PDF: {total} -> {PDF_DIR.relative_to(ROOT)}")
    return 0


def check() -> int:
    problems: list[str] = []
    main = primary_lang()
    other = translation_lang()

    main_files = doc_files(main)
    other_files = doc_files(other)
    main_ids = {doc_id(p, main) for p in main_files}
    other_ids = {doc_id(p, other) for p in other_files}

    for missing in sorted(main_ids - other_ids):
        problems.append(f"нет перевода ({other}): {missing}")
    for extra in sorted(other_ids - main_ids):
        problems.append(f"перевод без оригинала ({main}): {extra}")

    # PDF: каждый документ, для которого есть исходник, должен иметь PDF.
    for lang in (main, other):
        for f in doc_files(lang):
            if not pdf_path(f, lang).is_file():
                problems.append(f"нет PDF ({lang}): {pdf_path(f, lang).relative_to(ROOT)}")

    # Ссылки внутри Markdown: [текст](путь) — проверяем только локальные.
    for f in main_files + other_files:
        text = f.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (f.parent / target).exists():
                problems.append(f"битая ссылка: {f.relative_to(ROOT)} -> {target}")

    if problems:
        print("docs-check: найдены замечания")
        for p in problems:
            print("  -", p)
        return 1
    print(f"docs-check: ok ({len(main_files)} документов, {len(main_files)} PDF на язык)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сборка PDF документации")
    ap.add_argument("--check", action="store_true", help="только проверить полноту")
    ap.add_argument("--lang", choices=["ru", "en"], help="собрать один язык")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    langs = [args.lang] if args.lang else [primary_lang(), translation_lang()]
    return build(langs)


if __name__ == "__main__":
    sys.exit(main())
