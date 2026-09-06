"""Content contracts and visible HTML evidence tests."""
from __future__ import annotations

from support import check, silently, write_temp_html

import contextlib
import io
import json
import tempfile
from pathlib import Path


def test_content_schemas_cover_all_public_doc_types() -> None:
    from shared import content_schema_types, public_document_template_kinds
    expected = public_document_template_kinds() | {"landing-page"}
    actual = set(content_schema_types())
    check("content schemas cover every public doc type plus landing-page",
          actual == expected,
          f"missing: {sorted(expected - actual)}, extra: {sorted(actual - expected)}")


def test_content_schemas_parse_and_are_objects() -> None:
    from shared import SCHEMAS_DIR, content_schema_types
    bad = []
    for name in content_schema_types():
        try:
            schema = json.loads((SCHEMAS_DIR / f"{name}.json").read_text(encoding="utf-8"))
            if schema.get("type") != "object" or "required" in schema and not schema["required"]:
                bad.append(name)
        except json.JSONDecodeError:
            bad.append(name)
    check("content schemas parse as object contracts", not bad, f"bad: {bad}")


def test_validate_node_flags_structural_defects() -> None:
    from content import validate_node
    schema = {
        "type": "object",
        "required": ["title", "metrics"],
        "properties": {
            "title": {"type": "string", "minLength": 2, "maxLength": 10},
            "metrics": {
                "type": "array", "minItems": 3, "maxItems": 4,
                "items": {"type": "object", "required": ["value"],
                          "properties": {"value": {"type": "string"}}},
            },
            "layout": {"type": "string", "enum": ["cover", "content"]},
        },
    }
    ok = validate_node({"title": "Hello", "metrics": [{"value": "1"}] * 3}, schema)
    check("validate_node passes a conforming object", ok == [])
    issues = validate_node(
        {"title": "way too long for the cap", "metrics": [{}], "layout": "hero"},
        schema,
    )
    text = "\n".join(issues)
    check("validate_node flags length, count, required, and enum defects",
          "too long" in text and "too few items" in text
          and "missing required field 'value'" in text and "'hero' not in" in text,
          text)
    numeric = validate_node(0, {"type": "integer", "minimum": 1, "maximum": 3}, "page")
    check("validate_node enforces numeric bounds",
          numeric == ["page: too small (0 < 1)"], str(numeric))


def test_coverage_issues_catch_dropped_values() -> None:
    from content import coverage_issues
    content = {
        "name": "Kami",
        "metric": "62%",
        "note": "p" * 120,
        "image": "shot.png",
        "cjk": "用户 2M 规模",
    }
    html_text = "Kami cut latency 62% at 用户2M规模 scale"
    issues, checked, skipped = coverage_issues(content, html_text)
    check("coverage passes present values, skips prose and images, normalizes CJK spacing",
          issues == [] and checked == 3 and skipped == 1,
          f"issues={issues} checked={checked} skipped={skipped}")
    issues, _, _ = coverage_issues({"metric": "$340K"}, html_text)
    check("coverage flags a dropped atomic value",
          len(issues) == 1 and "$340K" in issues[0], str(issues))


def test_check_content_cli_validates_and_covers() -> None:
    from content import check_content
    payload = {
        "type": "letter",
        "lang": "en",
        "content": {
            "sender": "Ada Lovelace, London",
            "date": "2026-07-13",
            "recipient": "Charles Babbage",
            "salutation": "Dear Charles,",
            "paragraphs": [
                "I write to state my purpose in one sentence: the engine deserves a program of its own.",
                "The evidence sits in the notes: fifty operations, one loop, and a table the machine can follow.",
                "My ask is specific: review the table this month so we can test it on the mill.",
            ],
            "signoff": "Sincerely,",
            "signature": "Ada",
        },
    }
    with tempfile.TemporaryDirectory() as d:
        content_path = Path(d) / "content.json"
        content_path.write_text(json.dumps(payload), encoding="utf-8")
        rc = silently(check_content, [str(content_path)])
        check("check_content accepts a valid letter IR", rc == 0)
        html = write_temp_html(
            "<html><body><p>Ada Lovelace, London 2026-07-13 Charles Babbage "
            "Dear Charles, My ask is specific: review the table this month so "
            "we can test it on the mill. Sincerely, Ada</p></body></html>"
        )
        try:
            rc = silently(check_content, [str(content_path), str(html)])
            check("check_content coverage passes when atomic values present", rc == 0)

            ambiguous_html = write_temp_html(
                html.read_text(encoding="utf-8").replace(
                    "<p>", '<p style="font-size:calc(1px - 1px)">',
                )
            )
            try:
                ambiguous_rc = silently(
                    check_content,
                    [str(content_path), str(ambiguous_html)],
                )
                check("check_content degrades indeterminate visibility evidence",
                      ambiguous_rc == 2)
            finally:
                ambiguous_html.unlink()

            missing_text_html = write_temp_html(
                html.read_text(encoding="utf-8")
                .replace("2026-07-13", "2026-07-14")
                .replace("</body>", '<img srcset="a.png 1x,b.png 2x"></body>')
            )
            try:
                missing_text_rc = silently(
                    check_content,
                    [str(content_path), str(missing_text_html)],
                )
                check("resource ambiguity cannot downgrade definite missing text",
                      missing_text_rc == 1)
            finally:
                missing_text_html.unlink()

            for style in (
                "clip-path:circle(50%)",
                "mask-image:url(#rounded)",
                "filter:url(#soften)",
            ):
                decorated_html = write_temp_html(
                    html.read_text(encoding="utf-8")
                    .replace("2026-07-13", "2026-07-14")
                    .replace(
                        "</body>",
                        f'<img style="{style}" src="decorative.svg"></body>',
                    )
                )
                try:
                    decorated_rc = silently(
                        check_content,
                        [str(content_path), str(decorated_html)],
                    )
                    check("decorative resource ambiguity cannot downgrade missing text",
                          decorated_rc == 1, style)
                finally:
                    decorated_html.unlink()

            for decoration in (
                '<svg><path filter="url(#shadow)"></path></svg>',
                '<svg><circle mask="url(#fade)"></circle></svg>',
                '<svg><g clip-path="url(#round)"></g></svg>',
                '<style>.decor { clip-path:circle(50%) }</style>'
                '<svg><path class="decor"></path></svg>',
            ):
                decorated_svg_html = write_temp_html(
                    html.read_text(encoding="utf-8")
                    .replace("2026-07-13", "2026-07-14")
                    .replace("</body>", f"{decoration}</body>")
                )
                try:
                    decorated_svg_rc = silently(
                        check_content,
                        [str(content_path), str(decorated_svg_html)],
                    )
                    check("decorative SVG ambiguity cannot downgrade missing text",
                          decorated_svg_rc == 1, decoration)
                finally:
                    decorated_svg_html.unlink()

            payload["brief"] = {
                "audience": "Technical collaborator",
                "job": "Secure review",
                "template": "letter-en",
                "formats": ["html", "pdf"],
                "page_target": 1,
                "required_assets": ["must-appear-logo.svg"],
                "acceptance_checks": ["required logo is embedded"],
            }
            content_path.write_text(json.dumps(payload), encoding="utf-8")
            missing_asset_rc = silently(check_content, [str(content_path), str(html)])
            check("check_content coverage rejects a missing required brief asset",
                  missing_asset_rc == 1)
            mixed_html = write_temp_html(
                html.read_text(encoding="utf-8")
                .replace("2026-07-13", "2026-07-14")
                .replace("</body>", '<img srcset="a.png 1x,b.png 2x"></body>')
            )
            try:
                mixed_report = io.StringIO()
                with contextlib.redirect_stdout(mixed_report):
                    mixed_rc = check_content(
                        [str(content_path), str(mixed_html)]
                    )
                report = mixed_report.getvalue()
                check("mixed coverage reports definite and indeterminate findings separately",
                      mixed_rc == 1
                      and "definitely missing" in report
                      and "NOTE:" in report
                      and report.index("content.date") < report.index("NOTE:")
                      and report.index("brief.required_assets") > report.index("NOTE:"),
                      report)
            finally:
                mixed_html.unlink()
            html.write_text(
                html.read_text(encoding="utf-8").replace(
                    "</body>", '<img src="must-appear-logo.svg" alt=""></body>'
                ),
                encoding="utf-8",
            )
            embedded_asset_rc = silently(check_content, [str(content_path), str(html)])
            check("check_content coverage accepts an embedded required brief asset",
                  embedded_asset_rc == 0)
        finally:
            html.unlink()
        del payload["content"]["signature"]
        content_path.write_text(json.dumps(payload), encoding="utf-8")
        rc = silently(check_content, [str(content_path)])
        check("check_content rejects a missing required field", rc == 1)
        rc = silently(check_content, [])
        check("check_content usage error returns 2", rc == 2)


def test_content_ir_rejects_invalid_envelope() -> None:
    from content import validate_content_file

    body = {
        "sender": "Ada Lovelace, London",
        "date": "2026-07-13",
        "recipient": "Charles Babbage",
        "salutation": "Dear Charles,",
        "paragraphs": [
            "I write to state my purpose in one sentence: the engine deserves a program of its own.",
            "The evidence sits in the notes: fifty operations, one loop, and a table the machine can follow.",
            "My ask is specific: review the table this month so we can test it on the mill.",
        ],
        "signoff": "Sincerely,",
        "signature": "Ada",
    }
    valid_type, valid_issues = validate_content_file({
        "type": "letter", "lang": "zh-TW", "content": body,
    })
    _, invalid_issues = validate_content_file({
        "type": "letter", "lang": "not_a_locale", "content": body,
        "unexpected": True,
    })
    check("content IR accepts a strict language-tagged envelope",
          valid_type == "letter" and valid_issues == [], str(valid_issues))
    check("content IR rejects invalid lang and unknown top-level fields",
          any("'lang'" in issue for issue in invalid_issues)
          and any("unknown field 'unexpected'" in issue for issue in invalid_issues),
          str(invalid_issues))


def test_content_ir_validates_optional_artifact_brief() -> None:
    from content import (
        BRIEF_SCHEMA,
        _brief_contract_issues,
        validate_content_file,
        validate_node,
    )

    body = {
        "sender": "Ada Lovelace, London",
        "date": "2026-07-13",
        "recipient": "Charles Babbage",
        "salutation": "Dear Charles,",
        "paragraphs": [
            "I write to state my purpose in one sentence: the engine deserves a program of its own.",
            "The evidence sits in the notes: fifty operations, one loop, and a table the machine can follow.",
            "My ask is specific: review the table this month so we can test it on the mill.",
        ],
        "signoff": "Sincerely,",
        "signature": "Ada",
    }
    brief = {
        "audience": "Technical collaborator",
        "job": "Secure a review of the program table",
        "template": "letter-en",
        "formats": ["html", "pdf"],
        "page_target": 1,
        "acceptance_checks": ["one page", "specific ask remains visible"],
        "target": {"surface": "letter body", "page": 1},
        "preserve": ["letterhead", "signature"],
        "evidence": ["rendered page 1"],
    }
    _, valid_issues = validate_content_file({
        "type": "letter", "lang": "en", "brief": brief, "content": body,
    })
    invalid = dict(brief)
    invalid["formats"] = ["docx"]
    invalid["page_target"] = 0
    invalid["mystery"] = True
    _, invalid_issues = validate_content_file({
        "type": "letter", "lang": "en", "brief": invalid, "content": body,
    })
    text = "\n".join(invalid_issues)
    check("content IR accepts a structured artifact brief", valid_issues == [], str(valid_issues))
    check("content IR rejects unknown brief fields, formats, and page bounds",
          "brief: unknown field 'mystery'" in text
          and "'docx' not in" in text
          and "brief.page_target: too small" in text,
          text)

    conflicting = dict(brief, template="one-pager", page_target=2)
    _, conflict_issues = validate_content_file({
        "type": "one-pager", "lang": "cn", "brief": conflicting,
        "content": {
            "title": "A concise product claim",
            "subtitle": "A subtitle long enough to explain the intended audience and outcome",
            "metrics": [
                {"value": "10x", "label": "faster"},
                {"value": "99%", "label": "coverage"},
                {"value": "2m", "label": "setup"},
            ],
            "argument": [
                "A focused paragraph that explains the user problem, the proposed change, and why it matters now in concrete terms."
            ],
            "evidence": ["Measured result", "Observed behavior", "Verified source"],
            "next_step": "Review the evidence and approve the next test.",
        },
    })
    check("content IR rejects a page target beyond the template ceiling",
          any("exceeds template 'one-pager' maximum 1" in issue for issue in conflict_issues),
          str(conflict_issues))
    one_page_resume_issues = _brief_contract_issues(
        {"template": "resume-en", "formats": ["html", "pdf"], "page_target": 1},
        "resume",
        "en",
    )
    check("brief contract enforces the two-page resume hard stop",
          any("require exactly 2 pages" in issue for issue in one_page_resume_issues),
          str(one_page_resume_issues))

    landing_issues = _brief_contract_issues(
        {"template": "landing-page", "page_target": 2}, "landing-page"
    )
    slides_issues = _brief_contract_issues(
        {"template": "slides", "page_target": 12}, "slides"
    )
    editable_slides_issues = _brief_contract_issues(
        {"template": "slides-en", "formats": ["pptx"], "page_target": 12}, "slides"
    )
    impossible_resume_issues = _brief_contract_issues(
        {"template": "resume", "formats": ["pptx"], "page_target": 2}, "resume"
    )
    wrong_language_issues = _brief_contract_issues(
        {"template": "resume-en", "formats": ["html", "pdf"], "page_target": 2},
        "resume",
        "ko",
    )
    korean_pptx_fallback_issues = _brief_contract_issues(
        {
            "template": "slides-en", "formats": ["pptx"],
            "page_target": 12,
        },
        "slides",
        "ko",
    )
    korean_mixed_fallback_issues = _brief_contract_issues(
        {
            "template": "slides-en", "formats": ["html", "pdf", "pptx"],
            "page_target": 12,
        },
        "slides",
        "ko",
    )
    korean_pdf_wrong_variant_issues = _brief_contract_issues(
        {"template": "slides-en", "formats": ["html", "pdf"], "page_target": 12},
        "slides",
        "ko",
    )
    check("brief contract accepts screen, generic slide, and editable PPTX keys",
          landing_issues == [] and slides_issues == [] and editable_slides_issues == [],
          f"landing={landing_issues} slides={slides_issues} "
          f"editable={editable_slides_issues}")
    check("brief contract rejects a format the selected template cannot produce",
          any("does not support pptx" in issue for issue in impossible_resume_issues),
          str(impossible_resume_issues))
    check("brief contract rejects a known language/template variant mismatch",
          any("does not match language 'ko'" in issue for issue in wrong_language_issues),
          str(wrong_language_issues))
    check("brief contract keeps the documented Korean editable-PPTX fallback",
          korean_pptx_fallback_issues == [], str(korean_pptx_fallback_issues))
    check("brief contract limits the Korean slides-en fallback to editable PPTX",
          any("does not match language 'ko'" in issue
              for issue in korean_pdf_wrong_variant_issues)
          and any("does not match language 'ko'" in issue
                  for issue in korean_mixed_fallback_issues),
          f"pdf={korean_pdf_wrong_variant_issues} mixed={korean_mixed_fallback_issues}")

    marp_brief = dict(
        brief,
        template="slides-marp-en",
        formats=["md", "pdf"],
        page_target=12,
    )
    marp_schema_issues = validate_node(marp_brief, BRIEF_SCHEMA, "brief")
    marp_contract_issues = _brief_contract_issues(marp_brief, "slides", "en")
    korean_marp_issues = _brief_contract_issues(
        dict(marp_brief, template="slides-marp"),
        "slides",
        "ko",
    )
    check("brief contract accepts the shipped Marp authoring path",
          marp_schema_issues == []
          and marp_contract_issues == []
          and korean_marp_issues == [],
          f"schema={marp_schema_issues} contract={marp_contract_issues} "
          f"korean={korean_marp_issues}")

    no_length_contract = dict(brief)
    no_length_contract.pop("page_target")
    target_issues = _brief_contract_issues(no_length_contract, "letter", "en")
    length_only_issues = _brief_contract_issues(
        dict(no_length_contract, length_target="600 to 800 words"),
        "letter",
        "en",
    )
    check("artifact brief requires a page or length target",
          any("page_target or length_target" in issue for issue in target_issues)
          and length_only_issues == [],
          f"missing={target_issues} length_only={length_only_issues}")

    _, legacy_issues = validate_content_file({
        "type": "letter", "lang": "en", "content": body,
    })
    check("content IR keeps pre-brief files valid", legacy_issues == [], str(legacy_issues))


def test_coverage_survives_split_markup_values() -> None:
    """Values split across sibling nodes ("62" + "%") must still count as present."""
    from content import coverage_issues
    issues, checked, _ = coverage_issues({"metric": "62%"}, "value:\n62\n%")
    check("coverage rejoins values split by markup",
          issues == [] and checked == 1, str(issues))


def test_coverage_rejects_substrings_and_hidden_text() -> None:
    """Changed facts and hidden-only copies must not satisfy coverage."""
    from content import coverage_issues
    from html_visibility import visible_html_evidence, visible_html_text

    cases = [
        ({"metric": "62%"}, "Revenue reached 162%"),
        ({"metric": "62"}, "Revenue reached 1962"),
        ({"metric": "12 34"}, "Revenue reached 1234"),
        ({"metric": 1.0}, "Revenue reached 1.5"),
    ]
    issues = [coverage_issues(content, text)[0] for content, text in cases]
    check("coverage rejects values embedded in larger or collapsed tokens",
          all(len(found) == 1 for found in issues), str(issues))

    hidden_html = (
        "<html><head><title>62%</title><style>.concealed { display: none }</style></head><body>"
        "<template>62%</template><p hidden>62%</p>"
        '<p aria-hidden="true">62%</p><p style="display: none">62%</p>'
        '<p class="concealed">62%</p>'
        "<p>Visible value is 61%.</p></body></html>"
    )
    text = visible_html_text(hidden_html)
    missing, _, _ = coverage_issues({"metric": "62%"}, text)
    check("coverage ignores head, template, hidden, and display-none text",
          len(missing) == 1, f"text={text!r} issues={missing}")

    malformed_hidden = (
        '<div hidden><img></img><p>SECRET-FACT</p></div>'
        '<p>VISIBLE-FACT</p>'
    )
    malformed_text = visible_html_text(malformed_hidden)
    malformed_missing, _, _ = coverage_issues(
        {"hidden": "SECRET-FACT", "visible": "VISIBLE-FACT"},
        malformed_text,
    )
    check("visible-text parser keeps hidden scope across a void closing tag",
          len(malformed_missing) == 1
          and "SECRET-FACT" in malformed_missing[0]
          and "VISIBLE-FACT" in malformed_text,
          f"text={malformed_text!r} issues={malformed_missing}")

    self_closing_hidden = (
        '<div hidden/><p>SELF-CLOSING-SECRET</p></div>'
        '<p>SELF-CLOSING-VISIBLE</p>'
    )
    self_closing_text = visible_html_text(self_closing_hidden)
    self_closing_missing, _, _ = coverage_issues(
        {
            "hidden": "SELF-CLOSING-SECRET",
            "visible": "SELF-CLOSING-VISIBLE",
        },
        self_closing_text,
    )
    check("visible-text parser follows HTML semantics for non-void self-closing tags",
          len(self_closing_missing) == 1
          and "SELF-CLOSING-SECRET" in self_closing_missing[0]
          and "SELF-CLOSING-VISIBLE" in self_closing_text,
          f"text={self_closing_text!r} issues={self_closing_missing}")

    benign_selector_text = visible_html_text(
        '<style>[hidden] { display: none } '
        '[aria-hidden="true"] { visibility: hidden } '
        ':root { --fallback-display: none }</style>'
        '<p hidden>HIDDEN-BY-ATTRIBUTE</p>'
        '<p aria-hidden="false">VISIBLE-ARIA-FALSE</p>'
        '<p>VISIBLE-AFTER-SELECTOR</p>'
    )
    check("visibility parser scopes attribute selectors and custom properties",
          "HIDDEN-BY-ATTRIBUTE" not in benign_selector_text
          and "VISIBLE-ARIA-FALSE" in benign_selector_text
          and "VISIBLE-AFTER-SELECTOR" in benign_selector_text,
          repr(benign_selector_text))

    important_hidden_text = visible_html_text(
        '<style>.important-secret {'
        'display: none !important; display: block'
        '}</style>'
        '<p class="important-secret">IMPORTANT-SECRET</p>',
        fail_closed=True,
    )
    inline_important_text = visible_html_text(
        '<p style="display:none!important;display:block">INLINE-IMPORTANT-SECRET</p>',
        fail_closed=True,
    )
    visible_var_fallback = visible_html_text(
        '<p style="display:var(--missing, block)">VISIBLE-VAR-FALLBACK</p>',
        fail_closed=True,
    )
    check("visibility parser honors important cascade and visible var fallback",
          "IMPORTANT-SECRET" not in important_hidden_text
          and "INLINE-IMPORTANT-SECRET" not in inline_important_text
          and "VISIBLE-VAR-FALLBACK" in visible_var_fallback,
          f"style={important_hidden_text!r} inline={inline_important_text!r} "
          f"fallback={visible_var_fallback!r}")

    hidden_equivalents = [
        'font-size:0%',
        'font-size:calc(0px)',
        'font-size:min(0px, 1px)',
        'transform:scale(0, 0)',
        'transform:matrix(0,0,0,0,0,0)',
        'width:0%;height:0%;overflow:hidden',
        'max-width:0;max-height:0;overflow:hidden',
        'position:absolute;left:-99999px',
        'text-indent:-99999px;overflow:hidden;white-space:nowrap',
        'clip:rect(0, 0, 0, 0)',
    ]
    equivalent_results = [
        visible_html_text(
            f'<p style="{style}">EQUIVALENT-HIDDEN</p>',
            fail_closed=True,
        )
        for style in hidden_equivalents
    ]
    check("visibility parser recognizes equivalent hidden CSS values",
          all("EQUIVALENT-HIDDEN" not in text for text in equivalent_results),
          str(equivalent_results))

    ordinary_layout_text = visible_html_text(
        '<p style="position:absolute;top:20px;left:20px">ABSOLUTE-VISIBLE</p>'
        '<p style="transform:translateX(10px)">TRANSLATED-VISIBLE</p>'
        '<p style="scale:.95">SCALED-VISIBLE</p>'
        '<p style="backdrop-filter:blur(8px)">FILTERED-VISIBLE</p>'
        '<p style="margin-top:-1px">MARGIN-VISIBLE</p>'
        '<p style="text-indent:1em">INDENTED-VISIBLE</p>',
        fail_closed=True,
    )
    check("ordinary positioned and transformed layouts remain visible",
          all(marker in ordinary_layout_text for marker in (
              "ABSOLUTE-VISIBLE", "TRANSLATED-VISIBLE", "SCALED-VISIBLE",
              "FILTERED-VISIBLE", "MARGIN-VISIBLE", "INDENTED-VISIBLE",
          )),
          repr(ordinary_layout_text))

    ambiguous_text, ambiguous_state = visible_html_evidence(
        '<p style="font-size:calc(1px - 1px)">AMBIGUOUS-VISIBILITY</p>',
        fail_closed=True,
    )
    check("unresolved functional visibility is excluded and marked ambiguous",
          ambiguous_state and "AMBIGUOUS-VISIBILITY" not in ambiguous_text,
          f"ambiguous={ambiguous_state} text={ambiguous_text!r}")

    non_rendered_html = visible_html_text(
        '<svg><title>SVG-TITLE</title><desc>SVG-DESC</desc></svg>'
        '<svg><defs><text>SVG-DEFS</text></defs>'
        '<symbol><text>SVG-SYMBOL</text></symbol>'
        '<metadata>SVG-METADATA</metadata>'
        '<clipPath><text>SVG-CLIP</text></clipPath>'
        '<mask><text>SVG-MASK</text></mask>'
        '<pattern><text>SVG-PATTERN</text></pattern>'
        '<text>SVG-RENDERED</text></svg>'
        '<noembed>NOEMBED-TEXT</noembed>'
        '<noframes>NOFRAMES-TEXT</noframes>'
        '<datalist><option>DATALIST-OPTION</option></datalist>'
        '<ruby>base<rp>RUBY-FALLBACK</rp><rt>annotation</rt></ruby>'
        '<p>RENDERED-TEXT</p>',
        fail_closed=True,
    )
    check("visible text skips non-rendered metadata and fallback containers",
          all(marker not in non_rendered_html for marker in (
              "SVG-TITLE", "SVG-DESC", "SVG-DEFS", "SVG-SYMBOL",
              "SVG-METADATA", "SVG-CLIP", "SVG-MASK", "SVG-PATTERN",
              "NOEMBED-TEXT", "NOFRAMES-TEXT", "DATALIST-OPTION",
              "RUBY-FALLBACK",
          ))
          and "SVG-RENDERED" not in non_rendered_html
          and "RENDERED-TEXT" in non_rendered_html,
          repr(non_rendered_html))

    hidden_svg_text = visible_html_text(
        '<svg><text display="none">DISPLAY-SECRET</text>'
        '<text visibility="hidden">VISIBILITY-SECRET</text>'
        '<text opacity="0">OPACITY-SECRET</text>'
        '<text>SVG-VISIBLE</text></svg>',
        fail_closed=True,
    )
    check("visible text respects SVG presentation attributes",
          all(marker not in hidden_svg_text for marker in (
              "DISPLAY-SECRET", "VISIBILITY-SECRET", "OPACITY-SECRET",
          ))
          and "SVG-VISIBLE" not in hidden_svg_text,
          repr(hidden_svg_text))

    off_viewport_svg_text = visible_html_text(
        '<svg viewBox="0 0 100 100">'
        '<text x="-99999" y="20">OFF-LEFT</text>'
        '<text x="10000" y="20">OFF-RIGHT</text>'
        '<text x="101" y="20">JUST-OFF-RIGHT</text>'
        '<text x="-99" y="20">JUST-OFF-LEFT</text>'
        '<text x="101%" y="20">PERCENT-OFF-RIGHT</text>'
        '<text x="99" y="20" dx="10">DELTA-OFF-RIGHT</text>'
        '<svg x="101" viewBox="0 0 10 10"><text x="0" y="5">NESTED-OFF</text></svg>'
        '<text x="20" y="20">SVG-IN-VIEW</text></svg>',
        fail_closed=True,
    )
    check("visible text rejects SVG coordinates outside the viewport",
          "OFF-LEFT" not in off_viewport_svg_text
          and "OFF-RIGHT" not in off_viewport_svg_text
          and "JUST-OFF-RIGHT" not in off_viewport_svg_text
          and "JUST-OFF-LEFT" not in off_viewport_svg_text
          and "PERCENT-OFF-RIGHT" not in off_viewport_svg_text
          and "DELTA-OFF-RIGHT" not in off_viewport_svg_text
          and "NESTED-OFF" not in off_viewport_svg_text
          and "SVG-IN-VIEW" not in off_viewport_svg_text,
          repr(off_viewport_svg_text))

    malformed_table = (
        '<div hidden><table></div>MALFORMED-SECRET</table></div>'
        '<p>MALFORMED-VISIBLE</p>'
    )
    malformed_coverage_text = visible_html_text(malformed_table, fail_closed=True)
    malformed_residue_text = visible_html_text(malformed_table)
    check("crossed HTML closes split coverage and residue conservatively",
          "MALFORMED-SECRET" not in malformed_coverage_text
          and "MALFORMED-SECRET" in malformed_residue_text,
          f"coverage={malformed_coverage_text!r} residue={malformed_residue_text!r}")

    optional_end_html = visible_html_text(
        '<p>PARAGRAPH-FIRST<div>PARAGRAPH-SECOND</div><p>PARAGRAPH-THIRD'
        '<ul><li>LIST-FIRST<li>LIST-SECOND</ul>'
        '<table><tr><td>CELL-FIRST<td>CELL-SECOND</tr></table>',
        fail_closed=True,
    )
    check("standard optional HTML end tags preserve visible content",
          all(marker in optional_end_html for marker in (
              "PARAGRAPH-FIRST", "PARAGRAPH-SECOND", "PARAGRAPH-THIRD",
              "LIST-FIRST", "LIST-SECOND", "CELL-FIRST", "CELL-SECOND",
          )),
          repr(optional_end_html))

    self_closing_svg_text, self_closing_svg_ambiguous = visible_html_evidence(
        '<svg viewBox="0 0 100 100"><path d="M0 0L10 10" /></svg>'
        '<p>VISIBLE-AFTER-SVG</p>',
        fail_closed=True,
    )
    check("SVG foreign-content self-closing tags close without tainting HTML",
          self_closing_svg_text.strip() == "VISIBLE-AFTER-SVG"
          and not self_closing_svg_ambiguous,
          f"text={self_closing_svg_text!r} "
          f"ambiguous={self_closing_svg_ambiguous}")


def test_coverage_checks_asset_attributes() -> None:
    from html_visibility import visible_html_text
    from content import (
        coverage_issues,
        html_resource_attributes,
        html_resource_evidence,
    )

    raw = (
        '<img src="./images/product-shot.png" alt="Product">'
        '<img src="images/product-shot@2x.webp" alt="Product at high density">'
        '<template><img src="hidden-shot.png"></template>'
        '<a href="linked-only.png">not embedded</a>'
    )
    attrs = html_resource_attributes(raw)
    present, checked, _ = coverage_issues(
        {"image": "product-shot.png", "images": ["product-shot@2x.webp"]}, "", attrs
    )
    missing, _, _ = coverage_issues({"image": "missing-shot.png"}, "", attrs)
    check("coverage accepts image paths present in src and srcset",
          present == [] and checked == 2, f"issues={present} attrs={attrs}")

    hidden_svg_attrs = html_resource_attributes(
        '<svg><defs><image href="hidden-def.png"></image></defs>'
        '<symbol><image href="hidden-symbol.png"></image></symbol>'
        '<image x="0" y="0" width="10" height="10" '
        'href="visible-svg.png"></image></svg>'
    )
    check("asset coverage skips SVG definition resources",
          hidden_svg_attrs == {"visible-svg.png"}, repr(hidden_svg_attrs))

    hidden_asset_cases = [
        '<svg><image display="none" href="required.svg"></image></svg>',
        '<svg><image visibility="hidden" href="required.svg"></image></svg>',
        '<svg><image opacity="0" href="required.svg"></image></svg>',
        '<img style="width:0;height:0" src="required.svg">',
        '<img width="0" height="0" src="required.svg">',
        '<svg width="0" height="0"><image href="required.svg"></image></svg>',
        '<img style="position:absolute;left:-99999px" src="required.svg">',
        '<img style="transform:matrix(0,0,0,0,0,0)" src="required.svg">',
        '<img style="width:calc(0px);height:calc(0px)" src="required.svg">',
        '<svg viewBox="0 0 100 100"><image x="-99999" href="required.svg"></image></svg>',
        '<svg viewBox="0 0 100 100"><image x="10000" href="required.svg"></image></svg>',
        '<svg viewBox="0 0 100 100"><image x="101" y="0" width="10" height="10" href="required.svg"></image></svg>',
        '<svg viewBox="0 0 100 100"><image x="101%" y="0" width="10" height="10" href="required.svg"></image></svg>',
        '<svg viewBox="0 0 100 100"><svg x="101"><image x="0" y="0" width="10" height="10" href="required.svg"></image></svg></svg>',
        '<svg viewBox="0 0 100 100"><defs><clipPath id="empty"></clipPath></defs>'
        '<image x="0" y="0" width="20" height="20" '
        'clip-path="url(#empty)" href="required.svg"></image></svg>',
        '<svg viewBox="0 0 100 100"><defs><mask id="empty"></mask></defs>'
        '<image x="0" y="0" width="20" height="20" '
        'mask="url(#empty)" href="required.svg"></image></svg>',
        '<svg viewBox="0 0 100 100"><defs><filter id="empty"></filter></defs>'
        '<image x="0" y="0" width="20" height="20" '
        'filter="url(#empty)" href="required.svg"></image></svg>',
    ]
    check("asset coverage rejects non-rendered CSS and presentation forms",
          all(not html_resource_attributes(case) for case in hidden_asset_cases),
          str([html_resource_attributes(case) for case in hidden_asset_cases]))

    deterministic_attrs, responsive_ambiguous = html_resource_evidence(
        '<img src="required.svg">'
        '<img srcset="a.png 1x,b.png 2x">'
    )
    check("responsive ambiguity preserves unrelated deterministic resources",
          deterministic_attrs == {"required.svg"} and responsive_ambiguous,
          f"attrs={deterministic_attrs} ambiguous={responsive_ambiguous}")
    hidden_responsive_attrs, hidden_responsive_ambiguous = html_resource_evidence(
        '<div hidden><img srcset="a.png 1x,b.png 2x"></div>'
    )
    check("hidden responsive resources do not degrade asset evidence",
          hidden_responsive_attrs == set() and not hidden_responsive_ambiguous,
          f"attrs={hidden_responsive_attrs} "
          f"ambiguous={hidden_responsive_ambiguous}")
    svg_then_asset, svg_then_asset_ambiguous = html_resource_evidence(
        '<svg viewBox="0 0 100 100"><path d="M0 0L10 10" /></svg>'
        '<img src="required.svg">'
    )
    check("self-closing SVG graphics preserve following resource evidence",
          svg_then_asset == {"required.svg"} and not svg_then_asset_ambiguous,
          f"attrs={svg_then_asset} ambiguous={svg_then_asset_ambiguous}")
    check("coverage rejects omitted image assets",
          len(missing) == 1 and "missing-shot.png" in missing[0], str(missing))
    hidden, _, _ = coverage_issues(
        {"images": ["hidden-shot.png", "linked-only.png"]}, "", attrs
    )
    check("coverage ignores assets in templates and plain links",
          len(hidden) == 2, f"issues={hidden} attrs={attrs}")
    wrong_origin, _, _ = coverage_issues(
        ["https://brand.example/logo.svg"],
        "",
        html_resource_attributes('<img src="https://other.example/logo.svg">'),
        root_path="brief.required_assets",
        force_assets=True,
    )
    same_origin, _, _ = coverage_issues(
        ["https://brand.example/logo.svg?v=approved"],
        "",
        html_resource_attributes('<img src="https://brand.example/logo.svg?v=cache">'),
        root_path="brief.required_assets",
        force_assets=True,
    )
    check("required absolute assets cannot be impersonated by the same path on another host",
          len(wrong_origin) == 1, str(wrong_origin))
    check("required absolute assets tolerate cache-query changes on the same origin and path",
          same_origin == [], str(same_origin))

    local_absolute_remote_copy, _, _ = coverage_issues(
        ["/approved/brand/logo.svg"],
        "",
        html_resource_attributes(
            '<img src="https://attacker.example/approved/brand/logo.svg">'
        ),
        root_path="brief.required_assets",
        force_assets=True,
    )
    local_absolute_exact, _, _ = coverage_issues(
        ["/approved/brand/logo.svg"],
        "",
        html_resource_attributes('<img src="/approved/brand/logo.svg">'),
        root_path="brief.required_assets",
        force_assets=True,
    )
    check("required local absolute assets reject remote path impersonation",
          len(local_absolute_remote_copy) == 1 and local_absolute_exact == [],
          f"remote={local_absolute_remote_copy} exact={local_absolute_exact}")

    malformed_hidden_attrs = html_resource_attributes(
        '<div hidden><img></img><img src="hidden-after-void.svg"></div>'
        '<img hidden src="hidden-void.svg">'
        '<img src="visible.svg">'
    )
    check("resource parser keeps hidden scope across a void closing tag",
          malformed_hidden_attrs == {"visible.svg"},
          str(sorted(malformed_hidden_attrs)))

    self_closing_hidden_attrs = html_resource_attributes(
        '<div hidden/><img src="hidden-self-closing.svg"></div>'
        '<img src="visible-after-self-closing.svg">'
    )
    check("resource parser follows HTML semantics for non-void self-closing tags",
          self_closing_hidden_attrs == {"visible-after-self-closing.svg"},
          str(sorted(self_closing_hidden_attrs)))

    css_hidden_attrs = html_resource_attributes(
        '<style>.concealed img { display: none } '
        '.escaped { d\\69splay: n\\6f ne } '
        '[hidden] { display: none } '
        ':root { --fallback-display: none }</style>'
        '<div class="concealed"><img src="hidden-by-selector.svg"></div>'
        '<img style="display/**/: none" src="hidden-by-inline-comment.svg">'
        '<img class="escaped" src="hidden-by-css-escape.svg">'
        '<img hidden src="hidden-by-attribute.svg">'
        '<img src="visible-after-css.svg">'
    )
    check("resource parser fails closed on compound and comment-split hidden CSS",
          css_hidden_attrs == {"visible-after-css.svg"},
          str(sorted(css_hidden_attrs)))

    ambiguous_css_cases = [
        (
            '<style>div:not(.show) img { display: none }</style>'
            '<div><img src="hidden-by-not.svg"></div>',
            "hidden-by-not.svg",
        ),
        (
            '<style>[data-state^="hid"] { display: none }</style>'
            '<p data-state="hidden">HIDDEN-BY-ATTR-OPERATOR</p>',
            "HIDDEN-BY-ATTR-OPERATOR",
        ),
        (
            '<style>.marker + p { display: none }</style>'
            '<span class="marker"></span><p>HIDDEN-BY-SIBLING</p>',
            "HIDDEN-BY-SIBLING",
        ),
        (
            '<style>.hidden-by-var { --hide: none; display: var(--hide) }</style>'
            '<img class="hidden-by-var" src="hidden-by-var.svg">',
            "hidden-by-var.svg",
        ),
        (
            '<style>.h\\69 dden { visibility: collapse }</style>'
            '<img class="hidden" src="hidden-by-selector-escape.svg">',
            "hidden-by-selector-escape.svg",
        ),
        (
            '<link rel="style&#115;heet" '
            'href="data:text/css,.x%7Bdisplay%3Anone%7D">'
            '<img class="x" src="hidden-by-encoded-stylesheet.svg">',
            "hidden-by-encoded-stylesheet.svg",
        ),
        (
            '<style>@\\69mport url("data:text/css,.x%7Bdisplay%3Anone%7D")</style>'
            '<img class="x" src="hidden-by-escaped-import.svg">',
            "hidden-by-escaped-import.svg",
        ),
    ]
    ambiguous_results = [
        (
            marker,
            visible_html_text(raw, fail_closed=True),
            html_resource_attributes(raw),
        )
        for raw, marker in ambiguous_css_cases
    ]
    check("unsupported hiding CSS fails closed instead of partially matching",
          all(
              marker not in text and marker not in attrs
              for marker, text, attrs in ambiguous_results
          ),
          str(ambiguous_results))

    responsive_attrs = html_resource_attributes(
        '<picture>'
        '<source media="(min-width:99999px)" srcset="never-selected.svg">'
        '<img src="actual.svg" srcset="candidate-1.svg 1x, candidate-2.svg 2x">'
        '</picture>'
    )
    check("resource parser excludes unresolved responsive candidates",
          responsive_attrs == set(),
          str(sorted(responsive_attrs)))
    picture_fallback_attrs = html_resource_attributes(
        '<picture>'
        '<source media="(min-width:1px)" srcset="actual.svg">'
        '<img src="required-fallback.svg">'
        '</picture>'
    )
    bare_source_attrs = html_resource_attributes(
        '<source srcset="bare-unrendered.svg">'
    )
    check("picture fallbacks and bare sources cannot prove required assets",
          picture_fallback_attrs == set() and bare_source_attrs == set(),
          f"picture={sorted(picture_fallback_attrs)} bare={sorted(bare_source_attrs)}")

    remote_base, _, _ = coverage_issues(
        ["approved/logo.svg"],
        "",
        html_resource_attributes(
            '<base href="https://attacker.example/">'
            '<img src="approved/logo.svg">'
        ),
        root_path="brief.required_assets",
        force_assets=True,
    )
    check("required local assets reject a remote base URL",
          len(remote_base) == 1,
          str(remote_base))


def test_coverage_caps_adversarial_reports() -> None:
    from content import MAX_COVERAGE_ISSUES, MAX_COVERAGE_VALUES, coverage_issues

    missing, _, _ = coverage_issues({"values": list(range(1000))}, "")
    oversized, _, _ = coverage_issues({"values": ["present"] * (MAX_COVERAGE_VALUES + 1)}, "present")
    check("coverage caps missing-value reports",
          len(missing) == MAX_COVERAGE_ISSUES + 1
          and "issue limit" in missing[-1], f"issues={len(missing)}")
    check("coverage caps the number of atomic values",
          len(oversized) == 1 and "too many atomic values" in oversized[0], str(oversized[-2:]))
