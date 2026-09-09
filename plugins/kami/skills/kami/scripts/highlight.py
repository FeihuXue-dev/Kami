"""Shiki-based static syntax highlighting for Kami HTML templates.

Scans ``<pre><code class="language-*">`` blocks and delegates tokenization to
Shiki. The resulting HTML contains static token spans and needs no browser
JavaScript. Blocks without a language class, unsupported languages, and an
unavailable Shiki cache pass through unchanged.
"""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CODE_BLOCK_RE = re.compile(
    r'(?P<open><pre\b[^>]*>\s*<code\b[^>]*>)'
    r'(?P<code>.*?)'
    r'(?P<close></code\s*>\s*</pre\s*>)',
    re.DOTALL | re.IGNORECASE,
)
CLASS_ATTR_RE = re.compile(
    r'''(?:^|\s)class\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))''',
    re.IGNORECASE,
)
SCRIPT_DIR = Path(__file__).resolve().parent
SHIKI_RENDERER = SCRIPT_DIR / "shiki_highlight.mjs"
_WARNED_MISSING_SHIKI = False


def shiki_root() -> Path:
    """Return the stable Shiki cache root, honoring an explicit override."""
    explicit = os.environ.get("KAMI_SHIKI_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    # macOS uses a dedicated stable cache because other render setup can alter
    # XDG_CACHE_HOME for fontconfig during the current process.
    if sys.platform == "darwin":
        return Path.home() / ".cache" / "kami" / "shiki"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kami" / "shiki"


def shiki_available() -> bool:
    """Return whether Node can resolve Shiki from the configured cache."""
    try:
        probe = subprocess.run(
            ["node", "-", str(shiki_root())],
            input=(
                'const root = process.argv[2];\n'
                'try { require.resolve("shiki/package.json", { paths: [root] }); '
                'process.exit(0); } catch (_) { process.exit(1); }\n'
            ),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return probe.returncode == 0


def _warn_missing_shiki() -> None:
    global _WARNED_MISSING_SHIKI
    if _WARNED_MISSING_SHIKI:
        return
    print(
        "WARN: Shiki is not installed; language-tagged code blocks will render monochrome. "
        "Run `bash scripts/ensure_shiki.sh` to enable build-time syntax highlighting.",
        file=sys.stderr,
    )
    _WARNED_MISSING_SHIKI = True


def _language_from_open_tag(open_tag: str) -> str | None:
    """Return the first ``language-*`` class token from a code start tag."""
    code_tag = re.search(r"<code\b(?P<attrs>[^>]*)>", open_tag, re.IGNORECASE)
    if code_tag is None:
        return None
    class_attr = CLASS_ATTR_RE.search(code_tag.group("attrs"))
    if class_attr is None:
        return None
    class_value = next(value for value in class_attr.groups() if value is not None)
    for token in class_value.split():
        match = re.fullmatch(r"language-([\w+-]+)", token, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _render_with_shiki(blocks: list[dict[str, str]]) -> list[str | None] | None:
    """Return full highlighted ``<pre>`` fragments, or None on a tool failure."""
    if not SHIKI_RENDERER.exists() or not shiki_available():
        return None
    try:
        result = subprocess.run(
            ["node", str(SHIKI_RENDERER), str(shiki_root())],
            input=json.dumps(blocks, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode:
        print(
            "WARN: Shiki highlighting failed; language-tagged code blocks will render monochrome. "
            f"{result.stderr.strip() or 'Node renderer failed.'}",
            file=sys.stderr,
        )
        return None
    try:
        rendered = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(rendered, list) or len(rendered) != len(blocks):
        return None
    return [item if isinstance(item, str) else None for item in rendered]


def highlight_code_blocks(html_text: str) -> str:
    """Apply static Shiki highlighting to language-tagged code blocks.

    The function is idempotent: Shiki output has no ``language-*`` class on
    ``code`` and therefore is left untouched on a second render pass.
    """
    matches = list(CODE_BLOCK_RE.finditer(html_text))
    selected = [
        (match, _language_from_open_tag(match.group("open")))
        for match in matches
    ]
    selected = [(match, language) for match, language in selected if language]
    if not selected:
        return html_text

    blocks = [
        {"code": html_mod.unescape(match.group("code")), "language": language}
        for match, language in selected
    ]
    rendered = _render_with_shiki(blocks)
    if rendered is None:
        _warn_missing_shiki()
        return html_text

    replacements = iter(rendered)

    def replace(match: re.Match[str]) -> str:
        # The callback receives fresh match objects, so select by language
        # again instead of comparing match identities from the first scan.
        if _language_from_open_tag(match.group("open")) is None:
            return match.group(0)
        highlighted = next(replacements)
        return highlighted if highlighted is not None else match.group(0)

    return CODE_BLOCK_RE.sub(replace, html_text)
