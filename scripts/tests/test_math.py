"""Strict LaTeX rendering and locked MathJax runtime tests."""
from __future__ import annotations

from support import REPO_ROOT, SKILL_ROOT, check, skip

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path


def test_math_render_finds_standard_delimiters_only_in_text() -> None:
    from math_render import _latex_spans

    source = (
        r'<p data-formula="\(attribute\)">'
        r'Inline \(x^2\), display \[E = mc^2\], '
        r'escaped \\(literal\\).</p>'
        r'<code>\(code\)</code><pre>\[pre\]</pre>'
        r'<script>const formula = "\(script\)";</script>'
    )
    spans, issues = _latex_spans(source)
    check("math parser accepts standard inline and display delimiters",
          [(span.tex, span.display) for span in spans]
          == [("x^2", False), ("E = mc^2", True)],
          f"spans={spans} issues={issues}")
    check("math parser ignores attributes, escaped delimiters, code, pre, and script",
          not issues, str(issues))


def test_math_parser_offsets_follow_htmlparser_newlines() -> None:
    import math_render as math_mod
    from math_render import _latex_spans, check_latex_html

    for separator in ("\u2028", "\u2029", "\u0085", "\r", "\r\n", "\n"):
        source = f"<p>alpha{separator}beta</p>\n" + r"<p>\(x\)</p>"
        spans, issues = _latex_spans(source)
        check(f"math offsets preserve formula after {separator!r}",
              not issues and len(spans) == 1
              and source[spans[0].start:spans[0].end] == r"\(x\)"
              and spans[0].tex == "x", repr(spans))
        check(f"math checker catches raw formula after {separator!r}",
              bool(check_latex_html(source)))
        original_renderer = math_mod._render_svg
        try:
            math_mod._render_svg = lambda formulas: ["<svg></svg>" for _ in formulas]
            rendered = math_mod.render_latex_in_html(source)
        finally:
            math_mod._render_svg = original_renderer
        check(f"math replacement preserves surrounding HTML after {separator!r}",
              rendered.startswith(f"<p>alpha{separator}beta</p>\n<p>")
              and rendered.endswith("</p>") and "latex-inline-svg" in rendered
              and r"\(x\)" not in rendered, repr(rendered))


def test_math_check_rejects_raw_unmatched_and_legacy_sources() -> None:
    from math_render import check_latex_html

    cases = [
        r"<p>\(x^2\)</p>",
        r"<p>\[x^2</p>",
        r"<p>x^2\)</p>",
        '<span class="latex-inline" data-latex="x^2"></span>',
        '<span class="math latex-display extra" data-latex="x^2"></span>',
    ]
    findings = [check_latex_html(case) for case in cases]
    rendered = (
        '<span class="latex-inline-svg"><mjx-container>'
        '<svg><text>done</text></svg></mjx-container></span>'
    )
    check("math check rejects raw, unmatched, and legacy formula sources",
          all(findings), repr(findings))
    check("math check accepts rendered MathJax SVG",
          check_latex_html(rendered) == [],
          str(check_latex_html(rendered)))


def test_math_render_replaces_delimiters_and_preserves_other_html() -> None:
    import math_render as math_mod

    source = r'<p>Before \(x &lt; y\) after.</p><code>\(code\)</code>'
    original_renderer = math_mod._render_svg
    seen = []
    try:
        def fake_renderer(formulas):
            seen.extend(formulas)
            return [
                '<mjx-container><svg role="img"><path d="M0 0"/></svg></mjx-container>'
                for _ in formulas
            ]
        math_mod._render_svg = fake_renderer
        rendered = math_mod.render_latex_in_html(source)
    finally:
        math_mod._render_svg = original_renderer
    check("math render decodes entities and sends the standard delimiter source",
          seen == [{"tex": "x < y", "display": False}], repr(seen))
    check("math render replaces only the formula text node",
          "latex-inline-svg" in rendered
          and r"\(x &lt; y\)" not in rendered
          and r"<code>\(code\)</code>" in rendered
          and rendered.startswith("<p>Before "),
          rendered[:500])


def test_math_parser_decodes_entity_delimiters_and_ignores_metadata() -> None:
    from math_render import _latex_spans, check_latex_html

    source = (
        r"<title>Analysis \(x^2\)</title>"
        r"<p>&#92;(x^2&#92;)</p>"
    )
    spans, issues = _latex_spans(source)
    check("math parser decodes HTML entities before delimiter scanning",
          [(span.tex, span.display) for span in spans] == [("x^2", False)]
          and source[spans[0].start:spans[0].end] == "&#92;(x^2&#92;)",
          f"spans={spans} issues={issues}")
    check("math parser treats title metadata as literal text",
          not issues and not check_latex_html(r"<title>Analysis \(x^2\)</title>"),
          str(issues))


def test_math_parser_fails_closed_on_malformed_ignored_regions() -> None:
    from math_render import check_latex_html

    malformed = [
        r"<pre>literal </code> \(x^2\)</pre>",
        r'<script/>const formula = "\(x^2\)";',
        r"<pre>literal <p>Formula: \(x^2\)</p>",
    ]
    legacy_example = (
        '<pre><code>class="latex-inline"</code></pre>'
        '<!-- class="latex-display" -->'
    )
    check("math parser rejects ambiguous ignored-tag structure",
          all(check_latex_html(source) for source in malformed),
          repr([check_latex_html(source) for source in malformed]))
    check("legacy placeholder examples inside literal regions stay literal",
          check_latex_html(legacy_example) == [],
          str(check_latex_html(legacy_example)))


def test_math_parser_accepts_optional_option_end_tags() -> None:
    from math_render import _latex_spans

    source = (
        r"<select><option>A<option>B</select>"
        r"<datalist><option>C<option>D</datalist>"
        r"<p>\(x^2\)</p>"
    )
    spans, issues = _latex_spans(source)
    check("math parser follows optional HTML option end-tag rules",
          [(span.tex, span.display) for span in spans] == [("x^2", False)]
          and not issues,
          f"spans={spans} issues={issues}")


def test_math_render_real_runtime_is_strict_and_safe() -> None:
    from math_render import MathRenderError, probe_mathjax, render_latex_in_html

    status = probe_mathjax()
    if status["status"] != "available":
        skip("MathJax strict and safe end-to-end render",
             status.get("detail", "locked runtime unavailable"),
             ci_required=True)
        return

    rendered = render_latex_in_html(
        r"<p>Inline \(x^2 + \frac{1}{2}\).</p><p>\[E = mc^2\]</p>"
    )
    safe_words = render_latex_in_html(
        r"<p>\(\text{src = x, href=1}, x &lt; y\)</p>"
    )
    rejected = 0
    for source in (
        r"<p>\(\frac{1\)</p>",
        r"<p>\(\href{javascript:alert(1)}{x}\)</p>",
        r"<p>\(\class{evil}{x}\)</p>",
        r"<p>\(\color{red}{x}\)</p>",
    ):
        try:
            render_latex_in_html(source)
        except MathRenderError:
            rejected += 1
    check("locked MathJax renders valid inline and display formulas end to end",
          rendered.count("<mjx-container") == 2
          and "latex-inline-svg" in rendered
          and "latex-display-svg" in rendered,
          rendered[:500])
    check("invalid TeX and author-controlled markup or color fail closed",
          rejected == 4, f"rejected={rejected}")
    check("rendered SVG contains no active link, source, script, or event attribute",
          not re.search(
              r"<\s*(?:script|foreignObject)\b|(?:href|src|on[a-z]+)\s*=",
              rendered,
              re.IGNORECASE,
          ),
          rendered[:500])
    check("SVG safety scan parses attributes rather than formula text substrings",
          "<mjx-container" in safe_words,
          safe_words[:500])


def test_math_svg_safety_parser_rejects_malformed_structure() -> None:
    from math_render import _SvgSafetyParser

    parser = _SvgSafetyParser()
    parser.feed("<mjx-container><svg></mjx-container>")
    parser.close()
    check("SVG safety scan rejects mismatched or unclosed renderer markup",
          parser.malformed or bool(parser._stack),
          f"malformed={parser.malformed} stack={parser._stack}")


def test_math_cli_failure_preserves_source_and_success_is_atomic() -> None:
    from math_render import probe_mathjax

    status = probe_mathjax()
    if status["status"] != "available":
        skip("MathJax in-place atomic CLI",
             status.get("detail", "locked runtime unavailable"),
             ci_required=True)
        return
    script = SKILL_ROOT / "scripts" / "math_render.py"
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "filled.html"
        invalid = b"<p>\\(\\frac{1\\)</p>"
        path.write_bytes(invalid)
        path.chmod(0o640)
        failed = subprocess.run(
            [sys.executable, str(script), "--in-place", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        unchanged = path.read_bytes() == invalid
        path.write_text(r"<p>Energy: \(E = mc^2\).</p>", encoding="utf-8")
        path.chmod(0o640)
        succeeded = subprocess.run(
            [sys.executable, str(script), "--in-place", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        checked = subprocess.run(
            [sys.executable, str(script), "--check", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = path.read_text(encoding="utf-8")
        mode = stat.S_IMODE(path.stat().st_mode)
    check("failed strict in-place render preserves the original source bytes",
          failed.returncode == 1 and unchanged,
          (failed.stdout + failed.stderr)[:500])
    check("successful in-place render is check-clean and preserves file mode",
          succeeded.returncode == 0
          and checked.returncode == 0
          and "<mjx-container" in output
          and mode == 0o640,
          (succeeded.stdout + checked.stdout + checked.stderr)[:500])


def test_math_render_enforces_formula_count_limit_before_node() -> None:
    from math_render import MathRenderError, _latex_spans, render_latex_in_html

    source = "<p>" + r"\(x\)" * 50_000 + "</p>"
    tracemalloc.start()
    try:
        render_latex_in_html(source)
    except MathRenderError as exc:
        rejected = "formula safety limit" in str(exc)
    else:
        rejected = False
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    check("math renderer bounds formula count before allocating every span",
          rejected and peak < 5 * 1024 * 1024,
          f"rejected={rejected} peak={peak} bytes")

    fragmented = r"<p>x\)</p>" * 10_000
    tracemalloc.start()
    try:
        _latex_spans(fragmented)
    except MathRenderError as exc:
        fragmented_rejected = "TeX delimiters exceed" in str(exc)
    else:
        fragmented_rejected = False
    _current, fragmented_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    check("math renderer shares the delimiter budget across text nodes",
          fragmented_rejected and fragmented_peak < 8 * 1024 * 1024,
          f"rejected={fragmented_rejected} peak={fragmented_peak} bytes")


def test_math_delimiter_scan_is_linear_for_long_backslash_runs() -> None:
    from math_render import _latex_spans

    source = "<p>" + "\\" * 200_000 + "literal</p>"
    started = time.monotonic()
    spans, issues = _latex_spans(source)
    elapsed = time.monotonic() - started
    check("math delimiter scan stays linear on adversarial backslash runs",
          not spans and not issues and elapsed < 1.0,
          f"elapsed={elapsed:.3f}s spans={len(spans)} issues={issues[:2]}")


def test_math_no_formula_text_avoids_boundary_map_allocation() -> None:
    from math_render import _latex_spans

    source = "<p>" + "ordinary text " * 100_000 + "</p>"
    tracemalloc.start()
    spans, issues = _latex_spans(source)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    check("math parser avoids per-character boundary maps without delimiters",
          not spans and not issues and peak < 8 * 1024 * 1024,
          f"peak={peak} bytes spans={len(spans)} issues={issues[:2]}")

    source = "<p>" + "a" * 1_000_000 + r"\(x^2\)</p>"
    tracemalloc.start()
    spans, issues = _latex_spans(source)
    _current, tail_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    check("math parser maps only formula boundaries in long text nodes",
          [(span.tex, span.display) for span in spans] == [("x^2", False)]
          and not issues
          and tail_peak < 8 * 1024 * 1024,
          f"peak={tail_peak} bytes spans={len(spans)} issues={issues[:2]}")


def test_mathjax_probe_and_install_ignore_polluted_node_options() -> None:
    from math_render import probe_mathjax

    status = probe_mathjax()
    if status["status"] != "available":
        skip("MathJax polluted NODE_OPTIONS handling",
             status.get("detail", "locked runtime unavailable"),
             ci_required=True)
        return
    original = os.environ.get("NODE_OPTIONS")
    try:
        os.environ["NODE_OPTIONS"] = "--definitely-invalid-kami-option"
        polluted_probe = probe_mathjax()
        environment = os.environ.copy()
        installed = subprocess.run(
            ["bash", str(SKILL_ROOT / "scripts" / "ensure_mathjax.sh")],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        if original is None:
            os.environ.pop("NODE_OPTIONS", None)
        else:
            os.environ["NODE_OPTIONS"] = original
    check("doctor probe and installer ignore inherited NODE_OPTIONS",
          polluted_probe["status"] == "available" and installed.returncode == 0,
          f"probe={polluted_probe} install={(installed.stdout + installed.stderr)[:300]}")


def test_mathjax_runtime_rejects_unsupported_node_21() -> None:
    import math_render as math_mod

    manifest = json.loads(
        (SKILL_ROOT / "scripts" / "mathjax-runtime" / "package.json")
        .read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory() as d:
        fake_bin = Path(d) / "bin"
        fake_bin.mkdir()
        node = fake_bin / "node"
        npm = fake_bin / "npm"
        node.write_text("#!/bin/sh\nprintf '21\\n'\n", encoding="utf-8")
        npm.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        node.chmod(0o755)
        npm.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:/usr/bin:/bin"
        result = subprocess.run(
            ["bash", str(SKILL_ROOT / "scripts" / "ensure_mathjax.sh")],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        original_path = os.environ.get("PATH")
        try:
            os.environ["PATH"] = environment["PATH"]
            math_mod._validated_node.cache_clear()
            probe = math_mod.probe_mathjax()
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path
            math_mod._validated_node.cache_clear()
    check("MathJax runtime manifest and installer reject unsupported Node 21",
          manifest.get("engines", {}).get("node") == "20 || >=22"
          and result.returncode == 1
          and "Node.js 20 or Node.js 22+" in result.stderr
          and probe.get("status") == "missing"
          and "Node.js 20 or Node.js 22+" in probe.get("detail", ""),
          f"manifest={manifest.get('engines')} result={result.returncode} "
          f"stderr={result.stderr[:300]} probe={probe}")


def test_mathjax_installer_reclaims_dead_owner_lock() -> None:
    with tempfile.TemporaryDirectory() as d:
        temp_root = Path(d)
        fake_bin = temp_root / "bin"
        fake_bin.mkdir()
        node = fake_bin / "node"
        npm = fake_bin / "npm"
        node.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-p\" ]; then\n"
            "  case \"$2\" in *process.versions*) printf '22\\n' ;; *) printf '4.1.3\\n' ;; esac\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = \"-\" ]; then exit 0; fi\n"
            "case \"$*\" in\n"
            "  *--probe*) test -d \"$HOME/.cache/kami/mathjax/4.1.3/node_modules\" ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        npm.write_text(
            "#!/bin/sh\nmkdir -p node_modules\n",
            encoding="utf-8",
        )
        node.chmod(0o755)
        npm.chmod(0o755)
        math_parent = temp_root / ".cache" / "kami" / "mathjax"
        lock = math_parent / ".install-4.1.3.lock"
        stale = math_parent / ".install-4.1.3-stale"
        lock.mkdir(parents=True)
        stale.mkdir()
        (stale / "partial").write_text("partial", encoding="utf-8")
        (lock / "pid").write_text("99999999\n", encoding="utf-8")
        (lock / "staging").write_text(f"{stale}\n", encoding="utf-8")
        environment = os.environ.copy()
        environment["HOME"] = str(temp_root)
        environment["PATH"] = f"{fake_bin}:/usr/bin:/bin"
        environment.pop("XDG_CACHE_HOME", None)
        result = subprocess.run(
            ["bash", str(SKILL_ROOT / "scripts" / "ensure_mathjax.sh")],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        target = math_parent / "4.1.3" / "node_modules"
        recovered = (
            result.returncode == 0
            and target.is_dir()
            and not lock.exists()
            and not stale.exists()
        )
        truncated_results = []
        for owner_text in ("", "99999999"):
            shutil.rmtree(math_parent / "4.1.3")
            lock.mkdir()
            (lock / "pid").write_text(owner_text, encoding="utf-8")
            truncated = subprocess.run(
                ["bash", str(SKILL_ROOT / "scripts" / "ensure_mathjax.sh")],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            truncated_results.append(
                truncated.returncode == 0
                and target.is_dir()
                and not lock.exists()
            )
        recovered = recovered and all(truncated_results)
    check("MathJax installer reclaims a dead owner's lock and controlled staging",
          recovered,
          f"initial={(result.stdout + result.stderr)[:300]} "
          f"truncated={truncated_results}")


def test_mathjax_cache_survives_weasyprint_runtime_configuration() -> None:
    from math_render import probe_mathjax

    status = probe_mathjax()
    if status["status"] != "available":
        skip("MathJax cache after WeasyPrint configuration",
             status.get("detail", "locked runtime unavailable"),
             ci_required=True)
        return
    environment = os.environ.copy()
    environment.pop("XDG_CACHE_HOME", None)
    environment.pop("NODE_OPTIONS", None)
    code = (
        "import json, sys;"
        "sys.path.insert(0, 'skills/kami/scripts');"
        "from optional_deps import require_weasyprint_html;"
        "from math_render import probe_mathjax;"
        "require_weasyprint_html();"
        "print(json.dumps(probe_mathjax()))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        configured = json.loads(result.stdout)
    except json.JSONDecodeError:
        configured = {}
    check("WeasyPrint initialization does not redirect the MathJax cache",
          result.returncode == 0 and configured.get("status") == "available",
          (result.stdout + result.stderr)[:500])
