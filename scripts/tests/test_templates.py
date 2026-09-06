"""Template lint, shared styles, and authoring guide contracts."""
from __future__ import annotations

from support import REPO_ROOT, SITE_ROOT, SKILL_ROOT, check, silently, write_temp_html

import contextlib
import io
import re
import tempfile
from checks import _markdown_residue_issues, check_markdown_residue, check_placeholders
from lint import (
    NEGATIVE_EXAMPLE_LINE,
    _blank_block,
    _documented_snippets,
    _emphasis_container_findings,
    _extract_root_vars,
    _off_palette_findings,
    _pair_names,
    _root_token_findings,
    _undefined_token_findings,
    check_all,
    check_cross_template_consistency,
    check_off_palette,
    scan_file,
    scan_text,
)
from pathlib import Path
from shared import HTML_TEMPLATES, SCREEN_TEMPLATES, TEMPLATES
from verify import RECOGNIZABLE_FALLBACK_FONT_MARKERS


def test_long_doc_templates_use_rendered_toc_pages_and_chapter_headers() -> None:
    """Long-doc TOCs must use WeasyPrint target-counter, and running headers
    must follow chapter h1 titles instead of getting stuck on the TOC h2.
    """
    sources = ("long-doc.html", "long-doc-en.html", "long-doc-ko.html")
    required_ids = {
        "#ch-executive-summary",
        "#ch-background",
        "#ch-methodology",
        "#ch-conclusions",
        "#ch-appendix",
    }
    offenders: list[str] = []
    for source in sources:
        text = (TEMPLATES / source).read_text(encoding="utf-8")
        if "target-counter(attr(href), page)" not in text:
            offenders.append(f"{source}: missing target-counter")
        if ".toc-page" in text:
            offenders.append(f"{source}: still has obsolete toc-page wiring")
        missing_ids = sorted(href for href in required_ids if f'href="{href}"' not in text or f'id="{href[1:]}"' not in text)
        if missing_ids:
            offenders.append(f"{source}: missing TOC href/id pairs {missing_ids}")
        h1_block = re.search(r"(?m)^  h1\s*\{(?P<body>.*?)^  \}", text, re.S)
        if not h1_block or "string-set: section-title content();" not in h1_block.group("body"):
            offenders.append(f"{source}: h1 does not set running header")
        h2_block = re.search(r"(?m)^  h2\s*\{(?P<body>.*?)^  \}", text, re.S)
        if h2_block and "string-set:" in h2_block.group("body"):
            offenders.append(f"{source}: h2 still sets running header")

    check("long-doc templates use rendered TOC pages and chapter headers",
          not offenders,
          "; ".join(offenders))


def test_chinese_html_templates_keep_single_serif_stack() -> None:
    """Chinese templates must keep --sans pinned to --serif for PDF glyph safety."""
    offenders: list[str] = []
    for name, spec in HTML_TEMPLATES.items():
        source = spec.source
        if name.endswith("-en"):
            continue
        text = (TEMPLATES / source).read_text(encoding="utf-8")
        if "--sans: var(--serif)" not in text and "--sans:  var(--serif)" not in text:
            offenders.append(source)

    check("Chinese HTML templates keep --sans: var(--serif)",
          not offenders,
          f"offenders: {', '.join(offenders)}")


def _ko_stack_offenders(text: str) -> list[str]:
    """Return CSS declarations that reference the bare `"Source Han Serif K"`
    family inside a multi-name fallback stack but omit the real OTF family
    name `"Source Han Serif KR"`.

    The bare name `"Source Han Serif K"` is legitimate on its own only as the
    `@font-face` declared alias (a single-name `font-family: "Source Han Serif K";`
    with no comma, which loads via the file/CDN `src`). Anywhere it appears as a
    fallback item in a comma-separated stack (`--serif`, `--mono`, `@page`
    margin boxes, `code`/`pre`, ...), `"Source Han Serif KR"` MUST sit alongside
    it, or an offline Linux skill install cannot resolve the
    ensure-fonts.sh-downloaded font by name.

    Detection: scan only `font-family` / `--serif` / `--sans` / `--mono`
    declaration values (up to the next `;`, never crossing `{`/`}`). The token
    `"Source Han Serif K"` (closing quote after `K`) never matches
    `"Source Han Serif KR"`, so a value that contains the bare token AND a comma
    (i.e. a fallback stack, not a bare `@font-face` alias) must also contain KR.
    """
    bare = '"Source Han Serif K"'
    kr = '"Source Han Serif KR"'
    decl_re = re.compile(r"(?:font-family|--serif|--sans|--mono)\s*:\s*([^;{}]*)", re.IGNORECASE)
    offenders: list[str] = []
    for m in decl_re.finditer(text):
        value = m.group(1)
        if bare in value and "," in value and kr not in value:
            offenders.append(" ".join(value.split()))
    return offenders


def test_korean_templates_carry_resolvable_serif_name() -> None:
    """Every KO fallback stack that names `Source Han Serif K` must also name
    `Source Han Serif KR` (the actual family of the bundled OTFs), so the font
    resolves by name on an offline Linux skill install. Checks per-declaration,
    not just per-file, so a complete `--serif` cannot mask an incomplete local
    stack (page-margin header/footer, code/pre, mono).
    """
    offenders: list[str] = []
    ko_sources = [spec.source for name, spec in HTML_TEMPLATES.items() if name.endswith("-ko")]
    ko_sources += [source for name, source in SCREEN_TEMPLATES.items() if name.endswith("-ko")]
    # Guard against vacuous green: with zero -ko templates the offender loop
    # never runs and the check below would pass while enforcing nothing.
    check("Korean template set is non-empty", bool(ko_sources),
          "no -ko templates found in the registries")
    for source in ko_sources:
        text = (TEMPLATES / source).read_text(encoding="utf-8")
        for bad in _ko_stack_offenders(text):
            offenders.append(f"{source}: {bad}")

    check("Korean fallback stacks all carry Source Han Serif KR",
          not offenders,
          f"offenders: {'; '.join(offenders)}")


_SIBLING_PARITY_SPECS = (
    ("resume*.html", r'class="proj-text">(\{\{.*?\}\})', 3),
    ("resume*.html", r'class="proj-role">(\{\{.*?\}\})', 1),
    ("resume*.html", r'class="conv-body">\s*(\{\{.*?\}\})', 1),
    ("resume*.html", r'class="os-desc">(\{\{.*?\}\})', 1),
    ("resume*.html", r'class="art-stats">(\{\{.*?\}\})', 1),
    ("portfolio*.html", r'class="project-block">\s*<h3>[^<]*</h3>\s*<p>(\{\{.*?\}\})</p>', 3),
    ("portfolio*.html", r'class="project-type">(\{\{.*?\}\})', 1),
    ("portfolio*.html", r'class="project-date">(\{\{.*?\}\})', 1),
    ("one-pager*.html", r'<li>(\{\{(?:短 bullet|Short bullet|짧은 bullet).*?\}\})</li>', 3),
    ("long-doc*.html", r'(\{\{(?:一段论述|A paragraph|한 단락 논술).*?\}\})', 1),
)


def test_sibling_placeholder_hints_stay_in_parity() -> None:
    """Same-structure sibling blocks must carry identical placeholder hints."""
    matched = 0
    offenders: list[str] = []
    for glob_pattern, regex, cycle in _SIBLING_PARITY_SPECS:
        rx = re.compile(regex, re.DOTALL)
        for path in sorted(TEMPLATES.glob(glob_pattern)):
            hits = rx.findall(path.read_text(encoding="utf-8"))
            if not hits:
                offenders.append(f"{path.name}: no match for {regex[:40]!r} (stale spec?)")
                continue
            matched += 1
            if len(hits) % cycle != 0:
                offenders.append(f"{path.name}: {len(hits)} hint(s) not divisible by cycle {cycle}")
                continue
            first = hits[:cycle]
            for start in range(cycle, len(hits), cycle):
                block = hits[start:start + cycle]
                if block != first:
                    offenders.append(
                        f"{path.name}: block {start // cycle + 1} diverges from block 1: "
                        f"{block} != {first}")
    check("sibling parity specs matched across template families", matched >= 30,
          f"only {matched} template/spec matches; spec table may be stale")
    check("repeated blocks carry identical placeholder hints", not offenders,
          "; ".join(offenders[:6]))


def test_font_fallback_markers_recognize_pt_serif() -> None:
    """macOS without Charter may render English fallbacks as PT Serif."""
    embedded = {"DROIWJ+PT-Serif", "ZBEAAE+JetBrains-Mono"}
    fallback_present = any(
        marker in font for font in embedded
        for marker in RECOGNIZABLE_FALLBACK_FONT_MARKERS
    )
    check("font fallback markers recognize PT-Serif",
          fallback_present,
          f"markers: {RECOGNIZABLE_FALLBACK_FONT_MARKERS}")


def test_print_surfaces_have_no_ornamental_brand_lines() -> None:
    """Print hierarchy comes from type, spacing, labels, and fill, not ticks."""
    patterns = {
        "brand side rule": re.compile(
            r"border-left:\s*[\d.]+(?:pt|px)\s+solid\s+var\(--brand\)"
        ),
        "eyebrow tick": re.compile(
            r"\.(?:eyebrow|ticker-eyebrow|cover-eyebrow)::before"
        ),
        "short cover or contact rule": re.compile(
            r"(?:class=[\"'](?:cover-line|contact-line)[\"']|"
            r"\.(?:cover-line|contact-line)\s*\{)"
        ),
    }
    offenders: list[str] = []
    sources = list(TEMPLATES.glob("*.html")) + list((SITE_ROOT / "assets" / "demos").glob("*.html"))
    for path in sorted(sources):
        text = path.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            if pattern.search(text):
                offenders.append(f"{path.name}: {label}")

    for name in ("slides.py", "slides-en.py"):
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        if "def add_line(" in text:
            offenders.append(f"{name}: generic decorative add_line helper")

    check("print surfaces contain no ornamental brand lines",
          not offenders,
          f"offenders: {', '.join(offenders)}")


def test_shipped_surfaces_keep_subtractive_defaults() -> None:
    """A default surface stays flat, small-radius, and free of filler motion."""
    offenders: list[str] = []

    print_sources = [
        path for path in TEMPLATES.glob("*.html")
        if not path.name.startswith("landing-page")
    ] + list((SITE_ROOT / "assets" / "demos").glob("*.html"))
    large_print_radius = re.compile(
        r"border-radius:\s*(?:[789]|[1-9][0-9])(?:\.[0-9]+)?pt"
    )
    for path in sorted(print_sources):
        if large_print_radius.search(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}: screen-sized print radius")

    landing_forbidden = (
        "filter: blur",
        "linear-gradient(",
        ".gallery-frame::after",
    )
    default_surface_selectors = (
        ".hero",
        ".section-head",
        ".demo-card",
        ".price-card",
        ".gallery-caption",
    )
    for path in sorted(TEMPLATES.glob("landing-page*.html")):
        text = path.read_text(encoding="utf-8")
        for token in landing_forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")
        for selector in default_surface_selectors:
            match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text, re.DOTALL)
            if match and "box-shadow" in match.group(1):
                offenders.append(f"{path.name}: {selector} shadow")

    public_pages = [
        SITE_ROOT / "index.html",
        SITE_ROOT / "index-zh.html",
        SITE_ROOT / "index-tw.html",
        SITE_ROOT / "index-ja.html",
        SITE_ROOT / "index-ko.html",
    ]
    public_forbidden = (
        "border-left: 1.4pt solid var(--brand)",
        "box-shadow: 0 4px 24px",
        'class="dash demo"',
        'class="tag brush"',
        'class="shadow-row"',
    )
    for path in public_pages:
        text = path.read_text(encoding="utf-8")
        for token in public_forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")

    site_css = (SITE_ROOT / "styles.css").read_text(encoding="utf-8")
    for token in ("@keyframes fadeIn", "ul.dash", ".tag.brush", ".shadow-row"):
        if token in site_css:
            offenders.append(f"styles.css: {token}")

    for selector in (".family", ".comp", ".chart-card", ".quote"):
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", site_css, re.DOTALL)
        block = match.group(1) if match else ""
        if "box-shadow" in block:
            offenders.append(f"styles.css: {selector} shadow")
        if selector in {".family", ".comp", ".chart-card"} and re.search(
                r"\bborder:\s*1px", block):
            offenders.append(f"styles.css: {selector} stacked border")
        if selector == ".quote" and "border-left" in block:
            offenders.append("styles.css: quote side rule")

    check("shipped surfaces keep subtractive visual defaults",
          not offenders,
          f"offenders: {', '.join(offenders)}")


def test_print_radius_guidance_matches_shipped_range() -> None:
    """The quick reference must describe the same restrained range as templates."""
    cheatsheet = (SKILL_ROOT / "CHEATSHEET.md").read_text(encoding="utf-8")
    design = (SKILL_ROOT / "references" / "design.md").read_text(encoding="utf-8")
    check("print radius guidance matches shipped 2-6pt range",
          "within `2-6pt`" in cheatsheet
          and "within 2-6pt" in design
          and "Do not invent intermediate steps" not in cheatsheet,
          "radius guidance drifted from shipped template values")


def test_reviewed_demo_details_keep_quiet_hierarchy() -> None:
    """Small editorial cues should not turn back into colored or framed UI."""
    def css_block(text: str, selector: str) -> str:
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text, re.DOTALL)
        return match.group(1) if match else ""

    offenders: list[str] = []
    resume_surfaces = [
        TEMPLATES / "resume.html",
        TEMPLATES / "resume-en.html",
        TEMPLATES / "resume-ko.html",
        SITE_ROOT / "assets" / "demos" / "demo-musk-resume.html",
        SITE_ROOT / "assets" / "demos" / "demo-resume-ko.html",
    ]
    for path in resume_surfaces:
        text = path.read_text(encoding="utf-8")
        highlight = css_block(text, ".os-highlight")
        label = css_block(text, ".os-highlight .tag")
        if "background: var(--ivory)" not in highlight:
            offenders.append(f"{path.name}: chromatic highlight fill")
        if "background: transparent" not in label or "color: var(--brand)" not in label:
            offenders.append(f"{path.name}: filled highlight label")

    print_demo = (SITE_ROOT / "assets" / "demos" / "demo-kami-print.html").read_text(
        encoding="utf-8"
    )
    command = css_block(print_demo, ".cmd")
    if re.search(r"(?:^|[;\n])\s*border\s*:", command):
        offenders.append("demo-kami-print.html: framed command block")
    if "border-radius: 4pt" not in command:
        offenders.append("demo-kami-print.html: command block radius")

    slides_demo = (SITE_ROOT / "assets" / "demos" / "demo-agent-slides.html").read_text(
        encoding="utf-8"
    )
    suffix = css_block(slides_demo, ".metric .metric-suffix")
    if '<span class="metric-suffix">×</span>' not in slides_demo:
        offenders.append("demo-agent-slides.html: multiplier markup")
    if "font-size: 0.58em" not in suffix or "vertical-align: 0.08em" not in suffix:
        offenders.append("demo-agent-slides.html: multiplier optics")

    check("reviewed demo details keep quiet hierarchy",
          not offenders,
          f"offenders: {', '.join(offenders)}")


def test_table_components_keep_one_quiet_rule_system() -> None:
    """Tables should read as content first, with rules acting as quiet guides."""
    def css_block(text: str, selector: str) -> str:
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text, re.DOTALL)
        return match.group(1) if match else ""

    def vertical_padding(block: str) -> float:
        match = re.search(r"padding:\s*([\d.]+)pt", block)
        return float(match.group(1)) if match else -1

    documents = []
    offenders: list[str] = []
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        if ".kami-table" not in text:
            continue
        documents.append(path)
        header = css_block(text, "table th, .kami-table th")
        body = css_block(text, "table td, .kami-table td")
        compact_header = css_block(text, "table.compact th, .kami-table.compact th")
        compact_body = css_block(text, "table.compact td, .kami-table.compact td")
        total = css_block(text, "table .total td, .kami-table .total td")

        if "border-bottom: 0.6pt solid var(--border)" not in header:
            offenders.append(f"{path.name}: header rule")
        if "border-bottom: 0.25pt solid var(--border)" not in body:
            offenders.append(f"{path.name}: body rule")
        if "border-top: 0.6pt solid var(--border)" not in total:
            offenders.append(f"{path.name}: total rule")
        if "var(--brand)" in "\n".join((header, body, total)):
            offenders.append(f"{path.name}: accent-colored rule")

        if path.name.startswith("one-pager"):
            header_floor, body_floor = 5.0, 4.0
        elif path.name.startswith("resume"):
            header_floor, body_floor = 5.0, 4.0
        else:
            header_floor, body_floor = 6.0, 5.0
        if vertical_padding(header) < header_floor:
            offenders.append(f"{path.name}: header padding")
        if vertical_padding(body) < body_floor:
            offenders.append(f"{path.name}: body padding")
        if vertical_padding(compact_header) < 3.0:
            offenders.append(f"{path.name}: compact header padding")
        if vertical_padding(compact_body) < 2.5:
            offenders.append(f"{path.name}: compact body padding")

    check("all document families ship the shared table component",
          len(documents) == 18,
          f"found {len(documents)}: {', '.join(path.name for path in documents)}")
    check("document tables use neutral hairlines and readable row padding",
          not offenders,
          f"offenders: {', '.join(offenders)}")

    slide_paths = [
        TEMPLATES / "slides-weasy.html",
        TEMPLATES / "slides-weasy-en.html",
        TEMPLATES / "slides-weasy-ko.html",
        TEMPLATES / "marp" / "slides-marp.css",
        TEMPLATES / "marp" / "slides-marp-en.css",
    ]
    slide_offenders = []
    for path in slide_paths:
        text = path.read_text(encoding="utf-8")
        body = css_block(text, "table.data td")
        first = css_block(text, "table.data td:first-child")
        if "border-bottom: 0.25pt solid var(--border)" not in body:
            slide_offenders.append(f"{path.name}: body rule")
        if "color: var(--dark-warm)" not in first or "var(--brand)" in first:
            slide_offenders.append(f"{path.name}: first-column color")
        if vertical_padding(body) < 8.0:
            slide_offenders.append(f"{path.name}: row padding")
    check("slide data tables use the same quiet neutral system",
          not slide_offenders,
          f"offenders: {', '.join(slide_offenders)}")

    default_stripes = []
    for path in sorted(TEMPLATES.glob("equity-report*.html")):
        text = path.read_text(encoding="utf-8")
        if re.search(r'<table[^>]*class="[^"]*striped', text):
            default_stripes.append(path.name)
    check("equity report tables do not enable striping by default",
          not default_stripes,
          f"offenders: {', '.join(default_stripes)}")


def test_documented_snippets_answer_to_template_rules() -> None:
    """A doc snippet is copied more readily than a template is read.

    CHEATSHEET.md shipped a `.card` recipe pairing a 0.5pt border with an 8pt
    radius (the double-ring pitfall templates are failed for) against
    `--border-cream`, a token that no longer exists anywhere. Both survived
    because nothing scanned the docs.
    """
    bad = """```css
.card {
  background: var(--ivory);
  border: 0.5pt solid var(--border-cream);
  border-radius: 8pt;
}
```
"""
    p = write_temp_html(bad, suffix=".md")
    try:
        rules = set()
        for line_offset, snippet in _documented_snippets(p.read_text(encoding="utf-8")):
            rules |= {f.rule for f in scan_text(snippet, p, line_offset)}
            rules |= {f.rule for f in _undefined_token_findings(p, snippet, line_offset, {"--ivory"})}
        check("doc snippet scan catches the thin-border-radius recipe",
              "thin-border-radius" in rules, f"rules: {rules or '(none)'}")
        check("doc snippet scan catches a var() with no definition",
              "undefined-token" in rules, f"rules: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_documented_snippets_skip_tagged_counter_examples() -> None:
    """Docs teach by contrast; the line tagged `/* avoid */` is the lesson."""
    contrast = """```css
/* avoid */ .tag { background: rgba(27, 54, 93, 0.18); }
/* use   */ .tag { background: var(--tag-bg); }
```
"""
    p = write_temp_html(contrast, suffix=".md")
    try:
        rules = set()
        for line_offset, raw in _documented_snippets(p.read_text(encoding="utf-8")):
            rules |= {f.rule for f in scan_text(_blank_block(raw, NEGATIVE_EXAMPLE_LINE), p, line_offset)}
        check("a line tagged as the wrong way is not reported as a violation",
              "rgba-background" not in rules, f"rules: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_inline_svg_text_uses_explicit_font_stacks() -> None:
    """WeasyPrint must not hand inline SVG labels to an arbitrary system font."""
    offenders = []
    for folder in (SKILL_ROOT / "assets" / "diagrams", SITE_ROOT / "assets" / "demos"):
        for path in sorted(folder.glob("*.html")):
            if re.search(r'<text\b[^>]*\bfont-family=["\']inherit["\']',
                         path.read_text(encoding="utf-8"), re.IGNORECASE):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
    check("inline SVG text uses an explicit font stack",
          offenders == [], str(offenders))


def test_emphasis_container_mix_counts_distinct_fills() -> None:
    """Drift is several emphasis languages on a page, not one used repeatedly.

    Templates reuse a single fill across several raised components, which must
    stay clean. A generated document that invents a white rounded card for one
    passage and a tinted rounded block for the next must fail.
    """
    one_fill = """<!doctype html>
<html><head><style>
:root { --ivory: #faf9f5; --brand: #1B365D; }
.callout { background: var(--ivory); border-radius: 3pt; padding: 10pt; }
.takeaway { background: #faf9f5; border-radius: 4pt; padding: 10pt; }
.role { background: #E4ECF5; border-radius: 2pt; padding: 1pt 5pt; float: right; }
</style></head><body></body></html>
"""
    two_fills = """<!doctype html>
<html><head><style>
:root { --ivory: #faf9f5; --tag-bg: #E4ECF5; }
.qa-card { background: var(--ivory); border-radius: 8pt; padding: 10pt 14pt; }
.boundary { background: var(--tag-bg); border-radius: 6pt; padding: 8pt 12pt; }
</style></head><body></body></html>
"""
    clean = write_temp_html(one_fill)
    drifted = write_temp_html(two_fills)
    try:
        check("one emphasis fill (plus an inline chip) is not drift",
              not _emphasis_container_findings(clean),
              f"findings: {[f.excerpt for f in _emphasis_container_findings(clean)]}")
        found = _emphasis_container_findings(drifted)
        check("two different emphasis fills are flagged",
              len(found) == 1 and found[0].rule == "emphasis-container-mix",
              f"findings: {[f.rule for f in found] or '(none)'}")
    finally:
        clean.unlink(missing_ok=True)
        drifted.unlink(missing_ok=True)


def test_chinese_slides_mono_has_cjk_fallback() -> None:
    """Slide labels may mix mono Latin and CJK; the mono stack needs CJK fallback."""
    text = (TEMPLATES / "slides-weasy.html").read_text(encoding="utf-8")
    check("slides-weasy mono stack includes TsangerJinKai02 fallback",
          '"TsangerJinKai02"' in text and '"Source Han Serif SC"' in text)


def test_scan_file_skip_bug() -> None:
    """Lines starting with '#' (CSS id selectors) must NOT be skipped."""
    fixture = """<!doctype html>
<html><head><style>
#card { background: rgba(0,0,0,0.5); }
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = scan_file(p)
        rules = {f.rule for f in findings}
        check("scan_file flags rgba on #id-prefixed CSS line",
              "rgba-background" in rules,
              f"rules found: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_scan_file_arrow_in_en() -> None:
    """`→` in -en.html body should trigger arrow-unicode-in-en."""
    fixture = """<!doctype html>
<html lang="en"><head><style>
.tag { color: #1B365D; }
</style></head><body>
<p>Step 1 → Step 2</p>
</body></html>
"""
    p = write_temp_html(fixture, suffix="-en.html")
    try:
        findings = scan_file(p)
        rules = {f.rule for f in findings}
        check("scan_file flags U+2192 arrow in -en.html",
              "arrow-unicode-in-en" in rules,
              f"rules found: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_scan_file_clean_template() -> None:
    """A clean template should produce zero findings."""
    fixture = """<!doctype html>
<html><head><style>
:root { --brand: #1B365D; }
.card { background: var(--ivory); }
.tag { background: #EEF2F7; color: var(--brand); }
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = scan_file(p)
        check("scan_file produces no findings on clean template",
              len(findings) == 0,
              f"got {len(findings)} finding(s): {[f.rule for f in findings]}")
    finally:
        p.unlink(missing_ok=True)


def test_scan_file_line_height_too_loose() -> None:
    """line-height >= 1.6 should trigger line-height-too-loose."""
    fixture = """<!doctype html>
<html><head><style>
p { line-height: 1.8; }
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = scan_file(p)
        rules = {f.rule for f in findings}
        check("scan_file flags line-height 1.8 (too loose)",
              "line-height-too-loose" in rules,
              f"rules found: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_scan_text_closes_multiline_css_false_greens() -> None:
    direct = ".tag {\n  background:\n    rgba(255, 0, 0, 0.5);\n}"
    direct_findings = scan_text(direct, Path("multiline.html"))
    check("scan_text flags a multiline rgba background",
          [(f.rule, f.line) for f in direct_findings] == [("rgba-background", 2)],
          str([(f.rule, f.line) for f in direct_findings]))

    variables = (
        ":root { --safe: rgba(0, 0, 0, 0.1); "
        "--unsafe: rgba(255, 0, 0, 0.5); }\n"
        ".tag { background: var(--unsafe); }"
    )
    variable_findings = scan_text(variables, Path("variables.html"))
    check("scan_text finds every rgba variable declared on one line",
          [(f.rule, f.line) for f in variable_findings] == [("rgba-background", 2)],
          str([(f.rule, f.line) for f in variable_findings]))


def test_scan_file_flags_integer_line_height() -> None:
    findings = scan_text("p { line-height: 2; }", Path("integer-line-height.html"))
    check("scan_file flags integer line-height above the ceiling",
          [f.rule for f in findings] == ["line-height-too-loose"],
          str([(f.rule, f.excerpt) for f in findings]))


def test_scan_file_cool_gray() -> None:
    """Cool-gray hex literals should be flagged."""
    fixture = """<!doctype html>
<html><head><style>
.muted { color: #888; }
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = scan_file(p)
        rules = {f.rule for f in findings}
        check("scan_file flags cool gray #888",
              "cool-gray" in rules,
              f"rules found: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_off_palette_flags_non_token_hex() -> None:
    """A non-token, non-cool-gray hex in a component rule is off-palette."""
    fixture = """<!doctype html>
<html><head><style>
.x { color: #ff00aa; }
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = _off_palette_findings(p, {"#1b365d"})
        rules = {f.rule for f in findings}
        check("_off_palette_findings flags non-token hex #ff00aa",
              "off-palette" in rules,
              f"rules found: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_off_palette_flags_eight_digit_hex() -> None:
    findings = _off_palette_findings(
        Path("alpha-color.html"),
        {"#1b365d"},
        raw=".alert { color: #ff000080; }",
    )
    check("_off_palette_findings flags eight-digit hex colors",
          len(findings) == 1
          and findings[0].rule == "off-palette"
          and "#ff000080" in findings[0].excerpt,
          str([(f.rule, f.excerpt) for f in findings]))
    p = write_temp_html(":root { --alert: #ff000080; }")
    try:
        root_findings = _root_token_findings(p, {"#1b365d"})
        check("_root_token_findings flags eight-digit hex tokens",
              len(root_findings) == 1
              and "#ff000080" in root_findings[0].excerpt,
              str([(f.rule, f.excerpt) for f in root_findings]))
    finally:
        p.unlink(missing_ok=True)


def test_off_palette_ignores_root_and_svg() -> None:
    """Hex inside :root token defs and inside <svg> blocks must be skipped."""
    fixture = """<!doctype html>
<html><head><style>
:root { --brand: #1B365D; --accent: #ff00aa; }
</style></head><body>
<svg viewBox="0 0 10 10"><rect fill="#ff0000" /></svg>
</body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = _off_palette_findings(p, {"#1b365d"})
        check("_off_palette_findings skips :root defs and <svg> fills",
              findings == [],
              f"unexpected findings: {[(f.line, f.excerpt) for f in findings]}")
    finally:
        p.unlink(missing_ok=True)


def test_root_token_findings_flags_off_palette_definition() -> None:
    """An off-palette hex *defined* in :root (never used as a literal property
    hex) escapes _off_palette_findings, which blanks :root. _root_token_findings
    closes that gap: a stray `--brand-deep: #a64f33` second accent is flagged,
    while a registered token and cool-gray (reported elsewhere) are not."""
    fixture = """<!doctype html>
<html><head><style>
:root {
  --brand: #1B365D;
  --brand-deep: #a64f33;
}
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = _root_token_findings(p, {"#1b365d"})
        rules = {f.rule for f in findings}
        excerpts = " ".join(f.excerpt for f in findings)
        check("_root_token_findings flags off-palette :root token #a64f33",
              "off-palette-token" in rules and "#a64f33" in excerpts,
              f"rules={rules or '(none)'} excerpts={excerpts or '(none)'}")
        check("_root_token_findings does not flag the registered --brand token",
              "#1b365d" not in excerpts,
              f"unexpectedly flagged brand token: {excerpts}")
    finally:
        p.unlink(missing_ok=True)


def test_off_palette_repo_clean() -> None:
    """The real editorial templates must carry no off-palette colors."""
    rc = silently(check_off_palette)
    check("check_off_palette passes on the real templates",
          rc == 0,
          f"check_off_palette returned {rc}")


def test_off_palette_scans_site_demos_and_rejects_empty_checkout_scope() -> None:
    """The repository scan must reach relocated demos and reject empty coverage."""
    import lint
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        templates = root / "skills" / "kami" / "assets" / "templates"
        demos = root / "site" / "assets" / "demos"
        templates.mkdir(parents=True)
        demos.mkdir(parents=True)
        (templates / "clean.html").write_text("<p>Clean template</p>", encoding="utf-8")
        demo = demos / "demo.html"
        demo.write_text("<style>.probe { color: #123456; }</style>", encoding="utf-8")
        with patch.object(lint, "ROOT", root / "skills" / "kami"), \
                patch.object(lint, "TEMPLATES", templates), \
                patch.object(lint, "SITE_ROOT", root / "site", create=True):
            report = io.StringIO()
            with contextlib.redirect_stdout(report):
                result = lint.check_off_palette(verbose=True)
            check("off-palette scan catches a relocated demo and reports its path",
                  result == 1 and "site/assets/demos/demo.html" in report.getvalue(),
                  report.getvalue())
            demo.write_text("<style>.probe { color: #1B365D; }</style>", encoding="utf-8")
            check("off-palette scan accepts a clean relocated demo",
                  silently(lint.check_off_palette) == 0)
            demo.unlink()
            check("off-palette scan rejects empty repository demo coverage",
                  silently(lint.check_off_palette) == 2)
            with patch.object(lint, "SITE_ROOT", None):
                check("installed skill does not require website demos",
                      silently(lint.check_off_palette) == 0)


def test_lint_repo_clean() -> None:
    """The full CSS lint (scan_file across every template) must pass. This is
    what `build.py --check` runs; covering it here means a rule violation such
    as thin-border-radius cannot reach main behind an otherwise green suite."""
    rc = silently(check_all, False)
    check("check_all (full CSS lint) passes on the real templates",
          rc == 0,
          f"check_all returned {rc}")


def test_scan_file_ignores_block_comment_rgba() -> None:
    """rgba() inside a /* ... */ CSS block comment must not trigger findings."""
    fixture = """<!doctype html>
<html><head><style>
/* historical note: we used to write
   background: rgba(0,0,0,0.5);
   here, but switched to solid hex. */
.card { background: #EEF2F7; }
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = scan_file(p)
        rules = {f.rule for f in findings}
        check("scan_file ignores rgba inside /* */ comment",
              "rgba-background" not in rules,
              f"rules found: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_scan_file_thin_border_with_radius() -> None:
    """Sub-1pt closed border in a block with border-radius should fire pitfall #2."""
    fixture = """<!doctype html>
<html><head><style>
.tag {
  border: 0.5pt solid #1B365D;
  border-radius: 3pt;
  background: #EEF2F7;
}
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        findings = scan_file(p)
        rules = {f.rule for f in findings}
        check("scan_file flags thin border with border-radius",
              "thin-border-radius" in rules,
              f"rules found: {rules or '(none)'}")
    finally:
        p.unlink(missing_ok=True)


def test_check_placeholders_flags_unfilled() -> None:
    """A doc with `{{ name }}` left over should fail the check."""
    p = write_temp_html("<html><body><h1>{{ name }}</h1><p>{{ role }}</p></body></html>")
    try:
        rc = silently(check_placeholders, [str(p)])
        check("check_placeholders fails on {{ name }}", rc == 1, f"rc={rc}")
    finally:
        p.unlink(missing_ok=True)


def test_check_placeholders_passes_clean() -> None:
    """A doc with no placeholder syntax should pass."""
    p = write_temp_html("<html><body><h1>Real Name</h1><p>Real role</p></body></html>")
    try:
        rc = silently(check_placeholders, [str(p)])
        check("check_placeholders passes clean file", rc == 0, f"rc={rc}")
    finally:
        p.unlink(missing_ok=True)


def test_markdown_residue_flags_raw_markers() -> None:
    issues = _markdown_residue_issues("Intro\n---\nThis has **raw bold** and `raw code`.")
    check("markdown residue flags thematic breaks",
          any("thematic break" in issue for issue in issues),
          f"issues={issues}")
    check("markdown residue flags raw bold markers",
          any("bold marker" in issue for issue in issues),
          f"issues={issues}")
    check("markdown residue flags raw inline-code markers",
          any("inline-code marker" in issue for issue in issues),
          f"issues={issues}")

    check("markdown residue ignores clean text",
          _markdown_residue_issues("Clean paragraph with converted emphasis.") == [])

    issues = _markdown_residue_issues("A claim\u2014with an em dash.\n中文\u2014\u2014双破折号。")
    check("markdown residue flags em dashes",
          sum("em dash" in issue for issue in issues) == 2,
          f"issues={issues}")
    check("markdown residue allows en dash and hyphen",
          _markdown_residue_issues("Ranges use 2019-2024 and 3–5 items.") == [])


def test_check_markdown_residue_skips_html_code_blocks() -> None:
    dirty = write_temp_html("<html><body><p>Visible **raw bold**</p></body></html>", suffix=".html")
    clean_code = write_temp_html(
        "<html><body><p>Visible text</p><pre><code>**example** `cmd`</code></pre></body></html>",
        suffix=".html",
    )
    ambiguous_css = write_temp_html(
        '<html><head><link rel="stylesheet" href="theme.css"></head>'
        '<body><p>Visible **raw despite CSS uncertainty**</p></body></html>',
        suffix=".html",
    )
    descendant_css = write_temp_html(
        '<style>.wrap img { display: none }</style>'
        '<div class="wrap"><p>**VISIBLE-DESCENDANT**</p></div>',
        suffix=".html",
    )
    overridden_css = write_temp_html(
        '<style>.x { display: none } .x { display: block }</style>'
        '<p class="x">**VISIBLE-OVERRIDE**</p>',
        suffix=".html",
    )
    aria_hidden = write_temp_html(
        '<p aria-hidden="true">**VISUALLY-PRESENT**</p>',
        suffix=".html",
    )
    try:
        rc = silently(check_markdown_residue, [str(dirty)])
        check("check_markdown_residue fails visible raw markdown", rc == 1, f"rc={rc}")
        rc = silently(check_markdown_residue, [str(clean_code)])
        check("check_markdown_residue skips code/pre blocks", rc == 0, f"rc={rc}")
        rc = silently(check_markdown_residue, [str(ambiguous_css)])
        check("markdown residue includes text under ambiguous CSS",
              rc == 1, f"rc={rc}")
        residue_results = [
            silently(check_markdown_residue, [str(path)])
            for path in (descendant_css, overridden_css, aria_hidden)
        ]
        check("markdown residue never hides visually possible stylesheet or aria text",
              residue_results == [1, 1, 1], str(residue_results))
    finally:
        for path in (
            dirty, clean_code, ambiguous_css, descendant_css,
            overridden_css, aria_hidden,
        ):
            path.unlink(missing_ok=True)


def test_pair_names_includes_known_pairs() -> None:
    captured = list(_pair_names())
    check("pair_names includes one-pager",
          ("one-pager", "one-pager-en") in captured,
          f"got {[v for b, v in captured if b == 'one-pager']!r}")
    check("pair_names includes landing-page (CN/EN)",
          ("landing-page", "landing-page-en") in captured,
          f"got {[v for b, v in captured if b == 'landing-page']!r}")
    check("pair_names omits lone -en entries",
          not any(name.endswith("-en") for name, _ in _pair_names()))


def test_pair_names_includes_ko_variants_when_present() -> None:
    """`_pair_names` must yield (base, base-ko) pairs in addition to (base, base-en)."""
    captured = list(_pair_names())
    # Sanity: existing CN/EN and CN/KO pairs still detected, so the sweep
    # below cannot pass vacuously on an empty or EN-only pair list.
    check("CN/EN pair still detected", ("one-pager", "one-pager-en") in captured)
    check("CN/KO pair still detected", ("one-pager", "one-pager-ko") in captured)
    # Any base whose `-ko` sibling is registered must appear as a (base, base-ko) pair.
    bases = {base for base, _ in captured}
    seen = set(HTML_TEMPLATES) | set(SCREEN_TEMPLATES)
    missing = [
        base for base in bases
        if f"{base}-ko" in seen and (base, f"{base}-ko") not in captured
    ]
    check("pair_names includes ko variants when present", not missing,
          f"unpaired KO bases: {missing}")


def test_cross_template_consistency_clean() -> None:
    """The current repo should pass cross-template consistency."""
    rc = silently(check_cross_template_consistency, False)
    check("cross-template returns 0 on current repo", rc == 0, f"rc={rc}")


def test_extract_root_vars_picks_up_definitions() -> None:
    fixture = """<!doctype html>
<html><head><style>
:root {
  --brand: #1B365D;
  --parchment: #F5F4ED;
  --serif: Charter, Georgia, serif;
}
</style></head><body></body></html>
"""
    p = write_temp_html(fixture)
    try:
        vars_ = _extract_root_vars(p)
        check("extract_root_vars finds --brand", vars_.get("--brand") == "#1B365D",
              f"got {vars_.get('--brand')!r}")
        check("extract_root_vars finds --parchment", vars_.get("--parchment") == "#F5F4ED",
              f"got {vars_.get('--parchment')!r}")
    finally:
        p.unlink(missing_ok=True)


def test_changelog_contract_requires_four_to_eight_changes() -> None:
    from content import validate_content_file

    def validate(version: dict) -> list[str]:
        _, issues = validate_content_file({
            "type": "changelog",
            "lang": "en",
            "content": {"product": "Kami", "versions": [version]},
        })
        return issues

    base = {"version": "V1.2.3", "date": "2026-08-23"}
    valid = validate({
        **base,
        "breaking": [{"change": "Changed command", "migration": "Use new command"}],
        "features": ["Added export", "Added preview"],
        "fixes": ["Fixed wrapping"],
    })
    missing = validate(base)
    too_few = validate({**base, "fixes": ["Fixed first", "Fixed second", "Fixed third"]})
    too_many = validate({
        **base,
        "features": [f"Added feature {index}" for index in range(8)],
        "fixes": ["Fixed overflow"],
    })
    empty_class = validate({**base, "features": []})

    check("changelog accepts four changes split across supported classes",
          valid == [], repr(valid))
    check("changelog requires at least one change class",
          any("requires at least one" in issue for issue in missing),
          repr(missing))
    check("changelog enforces the combined four-to-eight entry envelope",
          any("got 3" in issue for issue in too_few)
          and any("got 9" in issue for issue in too_many),
          f"few={too_few} many={too_many}")
    check("changelog rejects an explicitly empty change class",
          any("too few items" in issue for issue in empty_class),
          repr(empty_class))


def test_skill_routes_visual_repairs_and_generated_assets_without_losing_contracts() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    diagrams = (SKILL_ROOT / "references" / "diagrams.md").read_text(encoding="utf-8")
    for mode in ("New document", "Content-only", "Visual repair", "Generated asset"):
        check(f"SKILL work mode keeps {mode}", mode in skill)
    check("visual repair locks target, preserve, evidence, and artifact matrices",
          all(term in skill for term in (
              "`target`", "`preserve`", "PDF: target page", "Screen: 1280px",
              "PPTX: editable source", "Generated asset: target slot",
          )),
          "visual feedback contract incomplete")
    check("image generation routes from observed capability",
          "Route from observed capability" in skill
          and "Claude, Codex, most coding agents" not in skill,
          "host-name capability list still present")
    check("illustration brief keeps old visual system and adds semantic anchors",
          all(term in diagrams for term in (
              "1. Claim:", "2. Placement:", "3. Reference:", "4. Exclusions:",
              "5. Canvas:", "6. Accent:", "7. Strokes and icons:",
              "8. Labels:", "9. Content spec:",
          ))
          and "After two look-based rejections" in diagrams,
          "illustration brief lost a field")


def test_visibility_resolves_document_custom_properties() -> None:
    """Resolve only unconditional custom properties inherited from the root."""
    from html_visibility import visible_html_evidence
    from content import html_resource_evidence

    visible_text, visible_ambiguous = visible_html_evidence(
        "<style>:root { --ink: #504e49 } body { color: var(--ink) }</style>"
        "<body>VISIBLE</body>",
        fail_closed=True,
    )
    check("document custom property makes body text deterministic",
          "VISIBLE" in visible_text and not visible_ambiguous,
          f"text={visible_text!r} ambiguous={visible_ambiguous}")

    template_results = []
    for path in sorted(TEMPLATES.glob("*.html")):
        raw = path.read_text(encoding="utf-8")
        text, ambiguous = visible_html_evidence(raw, fail_closed=True)
        template_results.append((path.name, bool(text.strip()), ambiguous, "<svg" in raw.lower()))
    check("all shipped HTML templates expose visible text under fail-closed checks",
          bool(template_results) and all(result[1] for result in template_results),
          str([result for result in template_results if not result[1]]))
    check("templates without SVG have deterministic visible text",
          all(ambiguous is False for _, _, ambiguous, has_svg in template_results
              if not has_svg),
          str([result for result in template_results if not result[3] and result[2]]))

    ambiguous_cases = [
        '<style>:root{--ink:#000}.dark{--ink:transparent}p{color:var(--ink)}</style>'
        '<div class="dark"><p>SECRET</p></div>',
        '<style>:root{--ink:#000}@media print{:root{--ink:transparent}}'
        'p{color:var(--ink)}</style><p>SECRET</p>',
        '<style>@property --ink{syntax:"<color>";inherits:false;initial-value:transparent}'
        ':root{--ink:#000}p{color:var(--ink)}</style><p>SECRET</p>',
        '<style>:root{--ink:#000}p{color:var(--ink)}</style>'
        '<p style="--ink:transparent">SECRET</p>',
        '<style>:root{--ink:#000}p{color:var(--ink)}</style>'
        '<p style=--ink:transparent>SECRET</p>',
        '<style>:root{--ink:#000}p{color:var(--ink)}</style>'
        "<p style='--ink:transparent'>SECRET</p>",
        '<style>:root{--ink:#000}p{color:var(--ink)}</style>'
        '<p style="--ink:trans&#112;arent">SECRET</p>',
    ]
    ambiguous_results = [
        visible_html_evidence(raw, fail_closed=True) for raw in ambiguous_cases
    ]
    check("conflicting or registered custom properties remain fail-closed",
          all("SECRET" not in text and ambiguous
              for text, ambiguous in ambiguous_results),
          repr(ambiguous_results))

    scoped_cases = [
        '<style>.theme{--d:block}p{display:var(--d,none)}</style>'
        '<div class="theme"></div><p>SECRET</p>',
        '<style>@media screen{:root{--d:block}}p{display:var(--d,none)}</style>'
        '<p>SECRET</p>',
        '<style>p{display:var(--d,none)}</style>'
        '<div style="--d:block"></div><p>SECRET</p>',
        '<style>.noop{--payload:"x; --ink:#000"}'
        'p{color:var(--ink,transparent)}</style><p>SECRET</p>',
        '<style>:root{--d:block}.hide{--junk:{x};--d:none}'
        'p{display:var(--d)}</style><p class="hide">SECRET</p>',
        '<style>:root{--INK:#000}p{color:var(--ink,transparent)}</style>'
        '<p>SECRET</p>',
    ]
    scoped_results = [
        visible_html_evidence(raw, fail_closed=True) for raw in scoped_cases
    ]
    check("scoped and malformed custom properties cannot expose hidden text",
          all("SECRET" not in text for text, _ in scoped_results),
          repr(scoped_results))

    scoped_assets, _ = html_resource_evidence(
        '<style>.theme{--d:block}img{display:var(--d,none)}</style>'
        '<div class="theme"></div><img src="required.svg">'
    )
    check("scoped custom properties cannot expose hidden resources",
          "required.svg" not in scoped_assets, repr(scoped_assets))

    hidden_cases = [
        '<style>:root{--ink:transparent}p{color:var(--ink)}</style><p>SECRET</p>',
        '<style>:root{--d:none}p{display:var(--d, block)}</style><p>SECRET</p>',
        '<p style=\'display:none;--x:";display:block"\'>SECRET</p>',
        '<p style="--HIDE:none;--hide:block;display:var(--HIDE)">SECRET</p>',
    ]
    hidden_results = [
        visible_html_evidence(raw, fail_closed=True) for raw in hidden_cases
    ]
    check("resolved hiding custom properties exclude their text deterministically",
          all("SECRET" not in text and not ambiguous
              for text, ambiguous in hidden_results),
          repr(hidden_results))

    benign_cases = [
        '<style>:root{--ink:#000}html{--ink:#000}p{color:var(--ink)}</style>'
        '<p>SHOWN</p>',
        '<style>:root{--base:#111;--ink:var(--base)}p{color:var(--ink)}</style>'
        '<p>SHOWN</p>',
        '<style>:root{--ink:#111}</style><p style="color:var(--ink)">SHOWN</p>',
    ]
    benign_results = [
        visible_html_evidence(raw, fail_closed=True) for raw in benign_cases
    ]
    check("identical and nested custom properties remain visible",
          all("SHOWN" in text and not ambiguous
              for text, ambiguous in benign_results),
          repr(benign_results))
