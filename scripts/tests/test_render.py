"""Rendering, font evidence, PDF geometry, and artifact preservation tests."""
from __future__ import annotations

from support import check, silently, skip, write_temp_html

import contextlib
import highlight as highlight_mod
import io
import subprocess
import tempfile
import verify as verify_mod
import zipfile
from checks import (
    _BG_B,
    _BG_G,
    _BG_R,
    _density_bucket,
    _last_content_y,
    _orphan_last_line,
    _parse_slide_sequence,
    _resume_balance_issues,
    _rhythm_issues,
    check_markdown_residue,
    scan_density,
)
from highlight import highlight_code_blocks
from optional_deps import MissingDepError, require_pymupdf
from pathlib import Path
from shared import PARCHMENT_RGB, TEMPLATES, load_checks_thresholds
from verify import _classify_cjk_font, _font_family_key


def test_font_recovery_repairs_truncated_repository_copies() -> None:
    import os
    import shutil
    from support import SKILL_ROOT

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        script = root / "skills/kami/scripts/ensure-fonts.sh"
        script.parent.mkdir(parents=True)
        shutil.copyfile(SKILL_ROOT / "scripts/ensure-fonts.sh", script)
        source = root / "assets/fonts"
        target = root / "skills/kami/assets/fonts"
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        names = {"TsangerJinKai02-W04.ttf": 10000000,
                 "TsangerJinKai02-W05.ttf": 10000000,
                 "SourceHanSerifKR-Regular.otf": 6500000,
                 "SourceHanSerifKR-Medium.otf": 6500000}
        for name, size in names.items():
            with (source / name).open("wb") as f:
                f.truncate(size)
        broken = target / "TsangerJinKai02-W04.ttf"
        broken.write_bytes(b"x")
        healthy = target / "SourceHanSerifKR-Regular.otf"
        shutil.copyfile(source / healthy.name, healthy)
        before = healthy.stat().st_mtime_ns
        # A bad source must never replace a valid local copy.
        (source / healthy.name).write_bytes(b"x")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name in ("curl", "fc-cache"):
            stub = bin_dir / name
            stub.write_text("#!/bin/sh\nexit 99\n")
            stub.chmod(0o755)
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                                     "KAMI_FONT_DIR": str(root / "user-fonts")})
        check("font recovery repairs truncated copy without downloading",
              result.returncode == 0 and broken.stat().st_size == names[broken.name],
              result.stdout + result.stderr)
        check("font recovery restores all missing copies",
              all((target / name).is_file() and (target / name).stat().st_size >= size
                  for name, size in names.items()))
        check("font recovery preserves healthy copy despite invalid source",
              healthy.stat().st_mtime_ns == before)


def test_font_probe_rejects_empty_and_truncated_bundles() -> None:
    import optional_deps as optional_deps_mod

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        font_dir = root / "assets" / "fonts"
        font_dir.mkdir(parents=True)
        (font_dir / "Empty.ttf").write_bytes(b"")
        (font_dir / "Truncated.otf").write_bytes(
            b"OTTO\x00\x01\x00\x00\x00\x00\x00\x00"
        )

        original_root = optional_deps_mod.ROOT
        original_which = optional_deps_mod.shutil.which
        try:
            optional_deps_mod.ROOT = root
            optional_deps_mod.shutil.which = lambda _name: None
            report = optional_deps_mod._probe_font(
                "Broken Font",
                ("Empty.ttf", "Truncated.otf"),
                "negative-control font",
            )
        finally:
            optional_deps_mod.ROOT = original_root
            optional_deps_mod.shutil.which = original_which

    check("font probe rejects empty and truncated bundled files",
          report["status"] == "degraded"
          and report["bundled"] == []
          and "Empty.ttf" in report["detail"]
          and "Truncated.otf" in report["detail"],
          str(report))


def test_font_family_key_collapses_weight_variants() -> None:
    """One family at two weights must not read as two typefaces.

    Bold CJK body text is a separate BaseFont entry (TsangerJinKai02 plus
    TsangerJinKai02-Medium, or the W04/W05 pair). Without collapsing, the
    mixed-family rule would fail every correctly rendered bilingual document.
    """
    pairs = [
        ("TsangerJinKai02", "TsangerJinKai02-Medium"),
        ("TsangerJinKai02-W04", "TsangerJinKai02-W05"),
        ("Source-Han-Serif-K", "Source-Han-Serif-K-Mediu"),
        ("NotoSerifCJKsc-Regular", "NotoSerifCJKsc-Bold"),
    ]
    offenders = [f"{a} != {b}" for a, b in pairs if _font_family_key(a) != _font_family_key(b)]
    check("font family key collapses weight variants",
          not offenders,
          f"offenders: {', '.join(offenders)}")
    check("font family key still separates real families",
          _font_family_key("Songti-SC") != _font_family_key("Hiragino-Mincho-ProN-Lig"))


def test_classify_cjk_font_separates_serif_from_the_rest() -> None:
    """The gate exists because a sans substitution shows no fallback boxes.

    A missing CJK serif is invisible to an eyeball pass: the page still reads,
    just with the wrong stroke density against metrics tuned for serif. The
    classifier is what turns that into a failure.
    """
    cases = {
        "ABCDEF+TsangerJinKai02-W04": "primary",
        "Songti-SC": "serif",
        "NotoSerifCJKsc-Regular": "serif",
        "Noto Serif CJK SC": "serif",
        "PingFang-SC": "other",
        "NotoSansCJKsc-Regular": "other",
        "SourceHanSansSC-Regular": "other",
    }
    offenders = [
        f"{name} -> {_classify_cjk_font(name)} (want {want})"
        for name, want in cases.items()
        if _classify_cjk_font(name) != want
    ]
    check("CJK font classifier separates primary and serif from everything else",
          not offenders,
          f"offenders: {', '.join(offenders)}")


def test_density_scans_the_only_page_of_a_single_page_pdf() -> None:
    """Page 1 is cover-exempt, which left one-page documents wholly unscanned.

    one-pager and letter render to a single page, so the cover exemption meant
    the only layout gate that reads a rendered page never looked at them.

    The fixture is built here rather than read from assets/examples, which is
    gitignored build output: pointing a test at it passes locally and fails on
    a fresh checkout. Synthesising the page also pins the expected verdict,
    since the emptiness ratio is chosen rather than inherited from whatever the
    template currently renders.
    """
    try:
        fitz = require_pymupdf()
    except MissingDepError as exc:
        skip("single-page density regression", str(exc), ci_required=True)
        return

    with tempfile.TemporaryDirectory() as tmp:
        single = Path(tmp) / "one-page.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)  # A4 in points
        parchment = tuple(channel / 255 for channel in PARCHMENT_RGB)
        page.draw_rect(fitz.Rect(0, 0, 595, 842), color=parchment, fill=parchment)
        # Ink across the top third only, leaving ~64% trailing whitespace: past
        # the sparse threshold, so a scanned page must be reported.
        page.draw_rect(fitz.Rect(50, 50, 545, 300), color=(0.1, 0.1, 0.1), fill=(0.1, 0.1, 0.1))
        doc.save(str(single))
        doc.close()

        default_scan = silently(scan_density, [str(single)])
        explicit_scan = silently(scan_density, [str(single)], scan_single_page=True)

    if default_scan is None or explicit_scan is None:
        return
    check("single-page PDF is exempt in the repo-wide sweep",
          sum(default_scan[:2]) == 0,
          f"scan: {default_scan}")
    check("single-page PDF is scanned when passed explicitly",
          sum(explicit_scan[:2]) > 0,
          f"scan: {explicit_scan} (fixture leaves ~64% of the page empty)")


def test_parse_slide_sequence_empty() -> None:
    fixture = """def main():
    pass
"""
    p = write_temp_html(fixture, suffix=".py")
    try:
        seq = _parse_slide_sequence(p)
        check("_parse_slide_sequence returns [] for empty main()",
              seq == [], f"got {seq}")
    finally:
        p.unlink(missing_ok=True)


def test_parse_slide_sequence_basic() -> None:
    fixture = """def main():
    cover_slide()
    content_slide()
    content_slide()
    chapter_slide()
    metrics_slide()

def helper():
    other_call()
"""
    p = write_temp_html(fixture, suffix=".py")
    try:
        seq = _parse_slide_sequence(p)
        expected = ["cover_slide", "content_slide", "content_slide", "chapter_slide", "metrics_slide"]
        check("_parse_slide_sequence parses ordered slide calls",
              seq == expected, f"got {seq}")
    finally:
        p.unlink(missing_ok=True)


def test_pdf_markdown_residue_skips_monospace_code() -> None:
    """Semantic code blocks remain exempt after HTML is flattened into PDF text."""
    try:
        from render import render_pdf
        import weasyprint  # noqa: F401
        import pypdf  # noqa: F401
    except ImportError:
        skip("PDF code residue exemption", "render dependencies unavailable", ci_required=True)
        return

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        html = root / "code.html"
        pdf = root / "code.pdf"
        html.write_text(
            '<style>code { font-family: monospace }</style>'
            '<p>Visible prose is clean.</p><pre><code>const msg = `hello`;</code></pre>',
            encoding="utf-8",
        )
        render_pdf(html, pdf)
        rc = silently(check_markdown_residue, [str(pdf)])
        check("PDF markdown residue skips monospace code", rc == 0, f"rc={rc}")


def _make_samples(rows_with_content: int, w: int, h: int, n: int = 3) -> bytes:
    """Build a flat RGB buffer: parchment everywhere, ink in the top N rows.

    Returns bytes matching the layout PyMuPDF's Pixmap uses, so we can drive
    _last_content_y without depending on a real PDF or numpy.
    """
    parchment_row = bytes((_BG_R, _BG_G, _BG_B)) * w
    ink_row = bytes((27, 54, 93)) * w
    out = bytearray()
    for y in range(h):
        out.extend(ink_row if y < rows_with_content else parchment_row)
    return bytes(out)


def test_last_content_y_dense_page() -> None:
    """Page with content all the way to the bottom: returns h-1."""
    w, h, n = 80, 100, 3
    samples = _make_samples(rows_with_content=h, w=w, h=h, n=n)
    y = _last_content_y(samples, w, h, w * n, n)
    check("_last_content_y dense page returns last row", y == h - 1, f"got {y}")


def test_last_content_y_sparse_page() -> None:
    """Page with content only in top 10 rows: returns 9."""
    w, h, n = 80, 100, 3
    samples = _make_samples(rows_with_content=10, w=w, h=h, n=n)
    y = _last_content_y(samples, w, h, w * n, n)
    check("_last_content_y sparse page returns last content row",
          y == 9, f"got {y}")


def test_last_content_y_blank_page() -> None:
    """Page with no content at all: returns 0."""
    w, h, n = 80, 100, 3
    samples = _make_samples(rows_with_content=0, w=w, h=h, n=n)
    y = _last_content_y(samples, w, h, w * n, n)
    check("_last_content_y blank page returns 0", y == 0, f"got {y}")


def test_density_threshold_buckets() -> None:
    """Drive the real `_density_bucket` seam so the SPARSE (>50%) / WARN (>25%)
    / OK categorization is asserted against production logic, not a reimplemented
    copy. A `>`->`>=` slip or a warn/sparse swap in checks.py fails here."""
    density_cfg = load_checks_thresholds()["density"]
    warn_pct = float(density_cfg["warn_pct"])
    sparse_pct = float(density_cfg["sparse_pct"])
    cases = [
        (0.0,        "OK"),      # full page
        (warn_pct,   "OK"),      # exactly at warn threshold -> not yet WARN (strict >)
        (0.30,       "WARN"),    # 30% trailing
        (sparse_pct, "WARN"),    # exactly at sparse threshold -> still WARN (strict >)
        (0.51,       "SPARSE"),  # 51% trailing
        (1.0,        "SPARSE"),  # blank page
    ]
    for empty, expected_bucket in cases:
        bucket = _density_bucket(empty, warn_pct, sparse_pct)
        check(
            f"_density_bucket empty={empty:.2f} -> {expected_bucket}",
            bucket == expected_bucket,
            f"got {bucket}",
        )


def test_rhythm_issues_rules() -> None:
    """Drive the three monotony rules in `_rhythm_issues` directly, without
    rendering a deck. Covers content-run limit, missing divider, and missing
    density-variation slide, plus the clean case."""
    max_run, min_deck = 4, 8

    healthy = [
        "title_slide", "content_slide", "content_slide", "quote_slide",
        "chapter_slide", "content_slide", "metrics_slide", "closing_slide",
    ]
    check("rhythm: balanced deck has no issues",
          _rhythm_issues(healthy, max_run, min_deck) == [],
          f"got {_rhythm_issues(healthy, max_run, min_deck)}")

    long_run = ["quote_slide"] + ["content_slide"] * (max_run + 1)
    issues = _rhythm_issues(long_run, max_run, min_deck)
    check("rhythm: over-long content run flagged",
          any("content_slide run" in i for i in issues), f"got {issues}")

    no_divider = ["title_slide"] + ["content_slide", "quote_slide"] * 5
    issues = _rhythm_issues(no_divider, max_run, min_deck)
    check("rhythm: large deck without divider flagged",
          any("no chapter_slide divider" in i for i in issues), f"got {issues}")

    no_variation = ["title_slide", "content_slide", "chapter_slide", "content_slide"]
    issues = _rhythm_issues(no_variation, max_run, min_deck)
    check("rhythm: deck without quote/metrics flagged",
          any("density variation" in i for i in issues), f"got {issues}")


def test_orphan_last_line_predicate() -> None:
    """Drive `_orphan_last_line`: a short trailing line on a multi-line block
    is an orphan; single-line blocks and long trailing lines are not."""
    max_words, max_chars = 3, 30

    orphan = "This is a full sentence that wraps\nword"
    check("orphan: short trailing line detected",
          _orphan_last_line(orphan, max_words, max_chars) == "word",
          f"got {_orphan_last_line(orphan, max_words, max_chars)!r}")

    single = "Only one line here"
    check("orphan: single-line block is not an orphan",
          _orphan_last_line(single, max_words, max_chars) is None,
          "single line flagged")

    long_tail = "First line of the block\n" + "x" * (max_chars + 5)
    check("orphan: long trailing line is not an orphan",
          _orphan_last_line(long_tail, max_words, max_chars) is None,
          "long tail flagged")

    many_words = "First line here\none two three four five"
    check("orphan: wordy trailing line is not an orphan",
          _orphan_last_line(many_words, max_words, max_chars) is None,
          "wordy tail flagged")


def test_resume_balance_issues() -> None:
    min_fill, max_fill, max_gap = 0.83, 0.95, 0.12
    check("resume balance accepts two filled pages",
          _resume_balance_issues([0.88, 0.92], 2, min_fill, max_fill, max_gap) == [])

    issues = _resume_balance_issues([0.92, 0.74], 2, min_fill, max_fill, max_gap)
    check("resume balance flags low second page",
          any("p2 fill" in issue for issue in issues),
          f"issues={issues}")
    check("resume balance flags page gap",
          any("gap" in issue for issue in issues),
          f"issues={issues}")

    issues = _resume_balance_issues([0.90, 0.89, 0.50], 3, min_fill, max_fill, max_gap)
    check("resume balance requires two pages",
          any("expected 2" in issue for issue in issues),
          f"issues={issues}")


def test_verify_target_requires_exactly_two_resume_pages() -> None:
    original_render = verify_mod.render_pdf
    original_fonts = verify_mod._pdf_font_names
    try:
        verify_mod._pdf_font_names = lambda _: {"ABCDEF+TsangerJinKai02-W04"}
        results = {}
        for page_count in (1, 2, 3):
            verify_mod.render_pdf = lambda _src, _out, n=page_count: n
            results[page_count] = verify_mod.verify_target(
                "resume", "resume.html", 2, TEMPLATES
            )
    finally:
        verify_mod.render_pdf = original_render
        verify_mod._pdf_font_names = original_fonts

    check("verify_target accepts a two-page resume",
          results[2] == [], repr(results[2]))
    check("verify_target rejects one- and three-page resumes as exact-count failures",
          all(
              any("expected 2" in issue for issue in results[count])
              for count in (1, 3)
          ),
          repr(results))


def test_highlight_with_language() -> None:
    html = '<pre><code class="language-python">def foo():\n    pass</code></pre>'
    out = highlight_code_blocks(html)
    if not highlight_mod.shiki_available():
        check("highlight skips styled output when Shiki is absent",
              out == html,
              f"out differs: {out[:200]}")
        return

    check("Shiki adds token spans to language-tagged block",
          "<span" in out and "style=" in out and "shiki-rendered" in out,
          f"out: {out[:200]}")
    check("Shiki avoids synthetic bold",
          "font-weight" not in out.lower(),
          f"out: {out[:200]}")
    check("Shiki preserves a pre/code wrapper",
          "<pre" in out and "</code>" in out)
    check("Shiki highlighting is idempotent",
          highlight_code_blocks(out) == out,
          f"out: {out[:200]}")


def test_highlight_without_language() -> None:
    html = '<pre><code>def foo():\n    pass</code></pre>'
    out = highlight_code_blocks(html)
    check("highlight does not modify plain code block",
          out == html,
          f"out differs: {out[:200]}")


def test_highlight_accepts_valid_class_attribute_variants() -> None:
    if not highlight_mod.shiki_available():
        skip("highlight class attribute variants", "Shiki unavailable", ci_required=True)
        return

    cases = [
        "<pre><code class='language-python'>print(1)</code></pre>",
        '<pre><code id="sample" class="language-python">print(1)</code></pre>',
        '<pre><code class="language-python extra">print(1)</code></pre>',
        '<PRE><CODE CLASS="extra language-python">print(1)</CODE></PRE>',
    ]
    outputs = [highlight_code_blocks(html) for html in cases]
    check("Shiki accepts quotes, attribute order, multiple classes, and tag case",
          all("<span" in output and "shiki-rendered" in output for output in outputs),
          str(outputs))


def test_highlight_without_shiki_dependency() -> None:
    html = '<pre><code class="language-python">def foo():\n    pass</code></pre>'
    original_available = highlight_mod.shiki_available
    original_warned = highlight_mod._WARNED_MISSING_SHIKI

    try:
        highlight_mod.shiki_available = lambda: False
        highlight_mod._WARNED_MISSING_SHIKI = False
        warning = io.StringIO()
        with contextlib.redirect_stderr(warning):
            out = highlight_code_blocks(html)
    finally:
        highlight_mod.shiki_available = original_available
        highlight_mod._WARNED_MISSING_SHIKI = original_warned

    check("highlight falls back unchanged without Shiki",
          out == html,
          f"out differs: {out[:200]}")
    check("highlight warns when Shiki is missing",
          "WARN: Shiki is not installed" in warning.getvalue(),
          f"warning: {warning.getvalue()}")


def test_render_pdf_preserves_last_good_output_on_post_render_failure() -> None:
    """A failed metadata/page validation must not replace the prior PDF."""
    import render as render_mod

    class FakeHTML:
        def __init__(self, **_kwargs):
            pass

        def write_pdf(self, path: str) -> None:
            Path(path).write_bytes(b"new-candidate")

    original_html = render_mod.require_weasyprint_html
    original_reader = render_mod.require_pypdf_reader
    original_metadata = render_mod.set_pdf_metadata
    try:
        render_mod.require_weasyprint_html = lambda: FakeHTML
        render_mod.require_pypdf_reader = lambda: object

        def fail_metadata(*_args, **_kwargs) -> None:
            raise RuntimeError("injected metadata failure")

        render_mod.set_pdf_metadata = fail_metadata
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "source.html"
            out = root / "output.pdf"
            src.write_text("<html><body>candidate</body></html>", encoding="utf-8")
            out.write_bytes(b"last-good")
            try:
                render_mod.render_pdf(src, out)
            except RuntimeError as exc:
                failed = "metadata failure" in str(exc)
            else:
                failed = False
            staged = list(root.glob(".output.pdf-*"))
            check("render failure preserves the last good PDF",
                  failed and out.read_bytes() == b"last-good",
                  f"failed={failed} bytes={out.read_bytes()!r}")
            check("render failure cleans staged candidates", staged == [], str(staged))
    finally:
        render_mod.require_weasyprint_html = original_html
        render_mod.require_pypdf_reader = original_reader
        render_mod.set_pdf_metadata = original_metadata


def test_pdf_metadata_preserves_document_navigation_and_language() -> None:
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import NameObject, RectangleObject, TextStringObject
        from render import set_pdf_metadata
    except ImportError as exc:
        skip("PDF metadata structure preservation", str(exc), ci_required=True)
        return

    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "structured.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_outline_item("Chapter", 0)
        writer.add_named_destination("chapter", 0)
        writer.add_uri(
            0,
            "https://example.com",
            RectangleObject([0, 0, 20, 20]),
        )
        writer.root_object.update({
            NameObject("/Lang"): TextStringObject("en-US"),
        })
        writer.add_metadata({"/Author": "{{AUTHOR}}", "/Title": "Structured"})
        writer.write(str(pdf))

        set_pdf_metadata(pdf, author="Ada Lovelace")
        reader = PdfReader(str(pdf))
        root = reader.trailer["/Root"]
        annotation_count = len(reader.pages[0].get("/Annots", []))
        metadata = dict(reader.metadata or {})
        structure = {
            "pages": len(reader.pages),
            "outline": len(reader.outline),
            "names": sorted(reader.named_destinations),
            "lang": str(root.get("/Lang")),
            "annotations": annotation_count,
        }

    check("PDF metadata update preserves catalog navigation and annotations",
          structure == {
              "pages": 1,
              "outline": 1,
              "names": ["chapter"],
              "lang": "en-US",
              "annotations": 1,
          },
          str(structure))
    check("PDF metadata update changes only placeholder author and Kami stamps",
          metadata.get("/Author") == "Ada Lovelace"
          and metadata.get("/Title") == "Structured"
          and metadata.get("/Producer") == "Kami"
          and metadata.get("/Creator") == "Kami",
          str(metadata))


def test_build_slides_requires_a_fresh_valid_pptx() -> None:
    import render as render_mod

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        templates = root / "templates"
        examples = root / "examples"
        templates.mkdir()
        examples.mkdir()
        (templates / "slides.py").write_text("# fixture", encoding="utf-8")
        out = examples / "slides.pptx"
        out.write_bytes(b"last-good")

        original_templates = render_mod.TEMPLATES
        original_examples = render_mod.EXAMPLES
        original_targets = render_mod.pptx_targets
        original_run = render_mod.subprocess.run
        mode = "missing"

        def fake_run(command, **_kwargs):
            candidate = Path(command[-1])
            if mode == "invalid":
                candidate.write_bytes(b"not-a-pptx")
            elif mode == "valid":
                with zipfile.ZipFile(candidate, "w") as archive:
                    for entry in render_mod._PPTX_REQUIRED_ENTRIES:
                        archive.writestr(entry, b"fixture")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        try:
            render_mod.TEMPLATES = templates
            render_mod.EXAMPLES = examples
            render_mod.pptx_targets = lambda: {"slides": "slides.py"}
            render_mod.subprocess.run = fake_run

            missing_ok = silently(render_mod.build_slides, "slides")
            missing_preserved = out.read_bytes() == b"last-good"
            mode = "invalid"
            invalid_ok = silently(render_mod.build_slides, "slides")
            invalid_preserved = out.read_bytes() == b"last-good"
            mode = "valid"
            valid_ok = silently(render_mod.build_slides, "slides")
            valid_issue = render_mod._pptx_issue(out)
        finally:
            render_mod.TEMPLATES = original_templates
            render_mod.EXAMPLES = original_examples
            render_mod.pptx_targets = original_targets
            render_mod.subprocess.run = original_run

        leftovers = list(examples.glob(".slides.pptx-*"))

    check("PPTX build rejects missing and invalid candidates without replacement",
          not missing_ok and missing_preserved and not invalid_ok and invalid_preserved,
          f"missing={missing_ok}/{missing_preserved} invalid={invalid_ok}/{invalid_preserved}")
    check("PPTX build atomically accepts a fresh valid package",
          valid_ok and valid_issue is None and leftovers == [],
          f"valid={valid_ok} issue={valid_issue} leftovers={leftovers}")


def test_visual_checklist_and_output_dir() -> None:
    from visual import REVIEW_CHECKLIST, visual_output_dir
    check("visual checklist has stable size and no em dash",
          len(REVIEW_CHECKLIST) == 10 and all("\u2014" not in line for line in REVIEW_CHECKLIST))
    out = visual_output_dir(Path("/tmp/docs/report.pdf"))
    check("visual output dir sits next to the pdf",
          out == Path("/tmp/docs/report-visual"), str(out))


def test_visual_clears_stale_page_images() -> None:
    """A re-render with fewer pages must not leave prior page PNGs behind."""
    from visual import _clear_page_images
    with tempfile.TemporaryDirectory() as d:
        target = Path(d)
        for name in ("page-01.png", "page-07.png", "notes.txt"):
            (target / name).write_bytes(b"x")
        _clear_page_images(target)
        left = sorted(p.name for p in target.iterdir())
        check("stale page PNGs removed, unrelated files kept",
              left == ["notes.txt"], str(left))


def test_visual_rejects_empty_pdf_and_bad_dpi() -> None:
    try:
        from pypdf import PdfWriter
        from visual import render_pages
    except ImportError:
        skip("visual empty-PDF guard", "pypdf unavailable", ci_required=True)
        return

    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "empty.pdf"
        evidence = Path(d) / "empty-visual"
        evidence.mkdir()
        old_page = evidence / "page-01.png"
        old_page.write_bytes(b"last-good-run")
        writer = PdfWriter()
        writer.write(str(pdf))
        errors = 0
        for dpi in (1, -1, 301):
            try:
                render_pages(pdf, dpi=dpi)
            except ValueError:
                errors += 1
        try:
            render_pages(pdf, dpi=110)
        except ValueError as exc:
            empty_error = "no pages" in str(exc)
        else:
            empty_error = False
        check("visual rejects empty PDFs and out-of-range DPI",
              empty_error and errors == 3,
              f"empty_error={empty_error} dpi_errors={errors}")
        check("failed visual render preserves last good evidence",
              old_page.read_bytes() == b"last-good-run")

        symlink_target = Path(d) / "elsewhere"
        symlink_target.mkdir()
        symlink_output = Path(d) / "linked-visual"
        symlink_output.symlink_to(symlink_target, target_is_directory=True)
        try:
            render_pages(pdf, out_dir=symlink_output, dpi=110)
        except ValueError as exc:
            symlink_rejected = "symbolic link" in str(exc)
        else:
            symlink_rejected = False
        check("visual rejects a symbolic-link evidence directory", symlink_rejected)

        huge_pdf = Path(d) / "huge.pdf"
        huge_writer = PdfWriter()
        huge_writer.add_blank_page(width=5000, height=5000)
        huge_writer.write(str(huge_pdf))
        try:
            render_pages(huge_pdf, dpi=300)
        except ValueError as exc:
            huge_rejected = "pixels" in str(exc)
        else:
            huge_rejected = False
        check("visual rejects an oversized raster page before rendering", huge_rejected)


def test_document_checks_reject_empty_pdf() -> None:
    """A readable PDF with zero pages is not a successfully checked artifact."""
    try:
        from pypdf import PdfWriter
        from checks import check_density, check_orphans
        from mcp_server import tool_check
    except ImportError:
        skip("empty-PDF document checks", "render dependencies unavailable", ci_required=True)
        return

    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "empty.pdf"
        PdfWriter().write(str(pdf))
        results = [
            silently(check_markdown_residue, [str(pdf)]),
            silently(check_orphans, [str(pdf)]),
            silently(check_density, [str(pdf)]),
        ]
        mcp_result = tool_check({"path": str(pdf)})
        check("PDF checks reject zero-page artifacts",
              results == [2, 2, 2], str(results))
        check("MCP check rejects zero-page artifacts",
              not mcp_result["ok"]
              and all(rule["status"] == "degraded" for rule in mcp_result["coverage"]),
              str(mcp_result))
