"""MCP protocol and tool contract tests."""
from __future__ import annotations

from support import REPO_ROOT, SKILL_ROOT, check, skip

import json
import subprocess
import sys
import tempfile
from optional_deps import MissingDepError, require_pymupdf
from pathlib import Path
from shared import HTML_TEMPLATES, MARP_TEMPLATES


def test_mcp_server_stdio_protocol() -> None:
    """The server must speak newline-delimited JSON-RPC with nothing else on stdout."""
    script = SKILL_ROOT / "scripts" / "mcp_server.py"
    msgs = [
        {"jsonrpc": "2.0", "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": None, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "kami_templates", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "kami_doctor", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in msgs)
    result = subprocess.run(
        [sys.executable, str(script)],
        input=stdin, capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    )
    try:
        replies = {m.get("id"): m for m in map(json.loads, result.stdout.strip().splitlines())}
    except json.JSONDecodeError:
        check("mcp server stdout is newline-delimited JSON", False, result.stdout[:200])
        return
    init = replies.get(1, {}).get("result", {})
    check("mcp initialize echoes protocol version and names the server",
          init.get("protocolVersion") == "2025-03-26"
          and init.get("serverInfo", {}).get("name") == "kami",
          json.dumps(init)[:200])
    tools = [t["name"] for t in replies.get(2, {}).get("result", {}).get("tools", [])]
    check("mcp tools/list exposes the five kami tools",
          tools == ["kami_templates", "kami_doctor", "kami_render", "kami_check", "kami_screenshot"],
          str(tools))
    body = replies.get(3, {}).get("result", {}).get("content", [{}])[0].get("text", "{}")
    payload = json.loads(body)
    check("mcp kami_templates returns registries and schema types",
          set(payload.get("document_templates", {})) == set(HTML_TEMPLATES)
          and set(payload.get("pptx_templates", {})) == {"slides", "slides-en"}
          and set(payload.get("marp_templates", {})) == set(MARP_TEMPLATES)
          and payload.get("content_schema_types"),
          body[:200])
    doctor_body = replies.get(4, {}).get("result", {}).get("content", [{}])[0].get("text", "{}")
    doctor = json.loads(doctor_body)
    check("mcp kami_doctor reports dependencies, fonts, and capabilities",
          isinstance(doctor.get("ok"), bool)
          and len(doctor.get("dependencies", [])) >= 3
          and len(doctor.get("fonts", [])) >= 3
          and "pdf_visual_review" in doctor.get("capabilities", {})
          and "strict_math" in doctor.get("capabilities", {}),
          doctor_body[:300])
    check("mcp unknown tool returns a JSON-RPC error",
          "error" in replies.get(5, {}), json.dumps(replies.get(5, {}))[:200])
    check("mcp explicit null id remains a request",
          replies.get(None, {}).get("result") == {}, str(replies.get(None)))
    check("mcp notifications produced no reply", len(replies) == 6, str(sorted(
        ("null" if key is None else str(key)) for key in replies
    )))


def test_mcp_check_returns_stable_findings_and_coverage() -> None:
    from mcp_server import CHECK_REGISTRY, tool_check

    with tempfile.TemporaryDirectory() as d:
        clean = Path(d) / "clean.html"
        broken = Path(d) / "broken.html"
        math_broken = Path(d) / "math-broken.html"
        clean.write_text("<html><body><p>Ready</p></body></html>", encoding="utf-8")
        broken.write_text("<html><body><p>{{ missing }}</p></body></html>", encoding="utf-8")
        math_broken.write_text(
            r"<html><body><p>\(x^2\)</p></body></html>",
            encoding="utf-8",
        )
        invalid_content = Path(d) / "invalid-content.json"
        invalid_content.write_text(
            json.dumps({"type": "letter", "lang": "en", "content": {}}),
            encoding="utf-8",
        )
        valid_content = Path(d) / "valid-content.json"
        valid_content.write_text(json.dumps({
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
        }), encoding="utf-8")
        clean_result = tool_check({"path": str(clean)})
        broken_result = tool_check({"path": str(broken)})
        math_broken_result = tool_check({"path": str(math_broken)})
        invalid_content_result = tool_check({
            "path": str(clean), "content": str(invalid_content),
        })
        missing_coverage_result = tool_check({
            "path": str(clean), "content": str(valid_content),
        })

    check("MCP check registry carries unique stable rule IDs",
          CHECK_REGISTRY and clean_result["ruleset_version"] == 3
          and len(CHECK_REGISTRY) == len(set(CHECK_REGISTRY))
          and all({"scope", "severity", "required_engine", "explanation"} <= set(rule)
                  for rule in CHECK_REGISTRY.values()),
          str(CHECK_REGISTRY))
    check("MCP clean check returns coverage without findings",
          clean_result["ok"] is True
          and clean_result["degraded"] is False
          and clean_result["findings"] == []
          and [item["id"] for item in clean_result["coverage"]]
          == ["html.placeholders", "html.math", "html.markdown-residue"]
          and clean_result["report"],
          json.dumps(clean_result)[:500])
    check("MCP failed check returns a stable finding and legacy report",
          broken_result["ok"] is False
          and broken_result["findings"][0]["id"] == "html.placeholders"
          and broken_result["findings"][0]["status"] == "failed"
          and "placeholder" in broken_result["report"].lower(),
          json.dumps(broken_result)[:500])
    check("MCP HTML check rejects unrendered standard LaTeX",
          math_broken_result["ok"] is False
          and [finding["id"] for finding in math_broken_result["findings"]]
          == ["html.math"],
          json.dumps(math_broken_result)[:500])
    invalid_ids = [item["id"] for item in invalid_content_result["findings"]]
    invalid_coverage = {
        item["id"]: item for item in invalid_content_result["coverage"]
    }
    check("MCP labels invalid content IR as contract failure before coverage",
          "content.contract" in invalid_ids
          and "content.coverage" not in invalid_ids
          and invalid_coverage["content.coverage"]["status"] == "not_run"
          and invalid_coverage["content.coverage"]["blocked_by"]
          == "content.contract",
          json.dumps(invalid_content_result)[:800])
    missing_ids = [item["id"] for item in missing_coverage_result["findings"]]
    missing_statuses = {
        item["id"]: item["status"]
        for item in missing_coverage_result["coverage"]
    }
    check("MCP runs coverage once after a valid content contract",
          missing_ids == ["content.coverage"]
          and missing_statuses["content.contract"] == "passed"
          and missing_statuses["content.coverage"] == "failed",
          json.dumps(missing_coverage_result)[:800])


def test_mcp_server_rejects_bad_frames_without_exiting() -> None:
    """Wrong-shaped JSON-RPC frames return errors and do not kill the server."""
    script = SKILL_ROOT / "scripts" / "mcp_server.py"
    msgs = [
        [],
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": "bad"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "kami_templates", "arguments": ["bad"]}},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    result = subprocess.run(
        [sys.executable, str(script)],
        input="".join(json.dumps(m) + "\n" for m in msgs),
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60,
    )
    replies = [json.loads(line) for line in result.stdout.strip().splitlines()]
    by_id = {reply.get("id"): reply for reply in replies}
    check("mcp malformed frames keep the process alive",
          result.returncode == 0 and len(replies) == 4 and "result" in by_id.get(3, {}),
          (result.stdout + result.stderr)[:400])
    check("mcp wrong params and arguments return invalid-params errors",
          by_id.get(1, {}).get("error", {}).get("code") == -32602
          and by_id.get(2, {}).get("error", {}).get("code") == -32602,
          result.stdout[:400])


def test_mcp_all_tools_succeed_over_stdio() -> None:
    """Exercise render, check, and screenshot through the installed protocol path."""
    try:
        from optional_deps import require_pypdf_reader, require_weasyprint_html
        require_weasyprint_html()
        require_pypdf_reader()
        require_pymupdf()
    except MissingDepError as exc:
        skip("MCP all-tools stdio success path", str(exc), ci_required=True)
        return

    script = SKILL_ROOT / "scripts" / "mcp_server.py"
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        html = root / "source.html"
        pdf = root / "output.pdf"
        html.write_text(
            "<!doctype html><html><head><style>"
            "@page{size:A4;margin:20mm}body{font-family:serif}"
            "</style></head><body><h1>Kami MCP smoke</h1><p>Rendered.</p></body></html>",
            encoding="utf-8",
        )
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "kami_render", "arguments": {
                 "html": str(html), "out": str(pdf)}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "kami_check", "arguments": {"path": str(html)}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "kami_screenshot", "arguments": {"pdf": str(pdf)}}},
        ]
        result = subprocess.run(
            [sys.executable, str(script)],
            input="".join(json.dumps(m) + "\n" for m in msgs),
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
        )
        try:
            replies = {m.get("id"): m for m in map(json.loads, result.stdout.strip().splitlines())}
            payloads = {
                reply_id: json.loads(
                    replies[reply_id]["result"]["content"][0]["text"]
                )
                for reply_id in (2, 3, 4)
            }
        except (KeyError, json.JSONDecodeError) as exc:
            check("MCP all-tools success path returns JSON results", False,
                  f"{exc}: {(result.stdout + result.stderr)[:500]}")
            return

        render_result = payloads[2]
        check_result = payloads[3]
        screenshot_result = payloads[4]
        check("MCP render succeeds over stdio",
              result.returncode == 0 and render_result.get("pages") == 1 and pdf.is_file(),
              json.dumps(render_result)[:300])
        check("MCP check succeeds over stdio",
              check_result.get("ok") is True and check_result.get("exit_code") == 0,
              json.dumps(check_result)[:300])
        page_paths = [Path(path) for path in screenshot_result.get("pages", [])]
        check("MCP screenshot returns evidence without a false perceptual verdict",
              "ok" not in screenshot_result
              and screenshot_result.get("rasterized") is True
              and screenshot_result.get("review_pending") is True
              and screenshot_result.get("font_check", {}).get("ok") is True
              and len(page_paths) == 1 and all(path.is_file() for path in page_paths),
              json.dumps(screenshot_result)[:500])


def test_mcp_render_guards_source_and_output_types() -> None:
    from mcp_server import tool_render

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        html = root / "source.html"
        html.write_text("<html><body>safe source</body></html>", encoding="utf-8")
        original = html.read_bytes()
        hardlink = root / "hardlink.pdf"
        hardlink.hardlink_to(html)
        victim = root / "victim.txt"
        victim.write_bytes(b"do-not-overwrite")
        symlink = root / "symlink.pdf"
        symlink.symlink_to(victim)
        rejected = 0
        for out in (html, hardlink, symlink, root / "not-pdf.txt"):
            try:
                tool_render({"html": str(html), "out": str(out)})
            except ValueError:
                rejected += 1
        check("mcp render rejects source aliases and non-PDF outputs",
              rejected == 4 and html.read_bytes() == original
              and victim.read_bytes() == b"do-not-overwrite",
              f"rejected={rejected} source_changed={html.read_bytes() != original}")
