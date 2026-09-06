"""Public site facts, locale structure, and responsive source contracts."""
from __future__ import annotations

from support import SITE_ROOT, SKILL_ROOT, check, silently

import re
from shared import TEMPLATES
from site_facts import (
    FULL_PUBLIC_FACT_FILES,
    REDIRECT_SITE_FILE,
    check_site_facts,
    public_path,
    site_fact_issues,
    site_structure_issues,
)


def site_fact_file_map() -> dict[str, str]:
    rels = (*FULL_PUBLIC_FACT_FILES, REDIRECT_SITE_FILE)
    return {
        rel: public_path(rel).read_text(encoding="utf-8", errors="replace")
        for rel in rels
    }


def test_site_facts_repo_clean() -> None:
    rc = silently(check_site_facts, False)
    check("public site facts match shared constants and registries", rc == 0,
          f"check_site_facts returned {rc}")


def test_site_facts_flags_bad_diagram_count() -> None:
    files = site_fact_file_map()
    bad = files["index.html"]
    bad = bad.replace("18 inline SVG diagram types", "17 inline SVG diagram types")
    bad = bad.replace("Eighteen inline SVG diagram types", "Seventeen inline SVG diagram types")
    files["index.html"] = bad

    issues = site_fact_issues(files)
    check("public site facts flag stale diagram counts",
          any("index.html: missing diagram count 18" in issue for issue in issues),
          f"issues: {issues}")


def test_site_facts_cover_developer_install_docs() -> None:
    files = site_fact_file_map()
    command = "npx skills add tw93/kami -a claude-code codex cursor -g -y"
    files["developers.md"] = files["developers.md"].replace(command, "npx skills add stale/path")
    issues = site_fact_issues(files)
    check("public site facts flag stale developer install docs",
          any("developers.md: missing generic agent install command" in issue
              for issue in issues),
          f"issues: {issues}")


def test_site_structure_repo_clean() -> None:
    """Locale pages match index.html's DOM skeleton (redirect script exempt)."""
    issues = site_structure_issues()
    check("locale page structure matches index.html", not issues,
          f"issues: {issues}")


def test_site_structure_flags_locale_drift() -> None:
    files = site_fact_file_map()
    files["index-zh.html"] = files["index-zh.html"].replace(
        '<h2 class="section-title">', '<h3 class="section-title">', 1)

    issues = site_structure_issues(files)
    check("locale structure check flags a drifted heading",
          any("index-zh.html: DOM skeleton drifted" in issue for issue in issues),
          f"issues: {issues}")


def test_public_site_typography_contract_matches_templates() -> None:
    """Public prose must teach the one-serif contract templates actually ship."""
    pages = [
        SITE_ROOT / "index.html",
        SITE_ROOT / "index-zh.html",
        SITE_ROOT / "index-tw.html",
        SITE_ROOT / "index-ja.html",
        SITE_ROOT / "index-ko.html",
    ]
    stale = (
        "Chinese uses serif headlines and sans body",
        "中文标题用 serif、正文用 sans",
        "中文標題用 serif、正文用 sans",
        "중문은 제목에 세리프, 본문에 산세리프",
    )
    offenders = [
        path.name for path in pages
        if any(token in path.read_text(encoding="utf-8") for token in stale)
    ]
    design = (SKILL_ROOT / "references" / "design.md").read_text(encoding="utf-8")
    check("public typography contract matches one-serif templates",
          not offenders
          and "One serif family per page for headlines and body" in design,
          f"offenders: {', '.join(offenders)}")


def test_landing_page_ctas_stack_at_320px() -> None:
    """Localized double CTAs must fit the smallest supported viewport."""
    offenders = []
    for path in sorted(TEMPLATES.glob("landing-page*.html")):
        text = path.read_text(encoding="utf-8")
        if not (
            "@media (max-width: 360px)" in text
            and ".hero-cta { flex-direction: column; align-items: stretch" in text
            and ".btn-ghost { width: 100%; }" in text
        ):
            offenders.append(path.name)
    check("landing page CTAs stack at 320px",
          not offenders,
          f"offenders: {', '.join(offenders)}")


def test_public_site_og_dimensions_match_showcase_image() -> None:
    """Social metadata must describe the image bytes platforms will fetch."""
    image = (SITE_ROOT / "assets" / "showcase" / "kami-landing.png").read_bytes()
    valid_png = image[:8] == b"\x89PNG\r\n\x1a\n" and image[12:16] == b"IHDR"
    width = int.from_bytes(image[16:20], "big") if valid_png else 0
    height = int.from_bytes(image[20:24], "big") if valid_png else 0
    offenders = []
    for name in ("index.html", "index-zh.html", "index-tw.html", "index-ja.html", "index-ko.html"):
        text = (SITE_ROOT / name).read_text(encoding="utf-8")
        declared_width = re.search(r'og:image:width" content="(\d+)"', text)
        declared_height = re.search(r'og:image:height" content="(\d+)"', text)
        if not (
            declared_width and int(declared_width.group(1)) == width
            and declared_height and int(declared_height.group(1)) == height
        ):
            offenders.append(name)
    check("public OG dimensions match the showcase PNG",
          valid_png and not offenders,
          f"image={width}x{height} offenders={', '.join(offenders)}")


def test_public_site_teaches_registered_tints_and_exact_radii() -> None:
    """Visible examples must describe tokens, not obsolete alpha recipes."""
    pages = [
        SITE_ROOT / "index.html",
        SITE_ROOT / "index-zh.html",
        SITE_ROOT / "index-tw.html",
        SITE_ROOT / "index-ja.html",
        SITE_ROOT / "index-ko.html",
    ]
    stale_tint_labels = (
        'class="opacity">0.18',
        'class="tag calm">Light 0.08',
        'class="tag standard">Standard 0.18',
        'class="tag calm">极淡 0.08',
        'class="tag standard">标准 0.18',
        'class="tag calm">極淡 0.08',
        'class="tag standard">標準 0.18',
        "equivalent solid hex",
        "等效实色",
        "等效實色",
        "등가 솔리드 hex",
    )
    offenders: list[str] = []
    for path in pages:
        text = path.read_text(encoding="utf-8")
        for token in stale_tint_labels:
            if token in text:
                offenders.append(f"{path.name}: {token}")
        for radius in ("2", "4"):
            if f'class="box" style="border-radius:{radius}px"' in text:
                offenders.append(f"{path.name}: {radius}px print radius")
            if f'class="box" style="border-radius:{radius}pt"' not in text:
                offenders.append(f"{path.name}: missing {radius}pt print radius")

    check("public site teaches registered tints and exact print radii",
          not offenders,
          f"offenders: {', '.join(offenders)}")
