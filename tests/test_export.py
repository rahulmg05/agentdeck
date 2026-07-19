from html.parser import HTMLParser
from pathlib import Path

from agentdeck.export import export_session

FIXTURES = Path(__file__).parent / "fixtures"


class _StrictValidator(HTMLParser):
    """Fails loudly on malformed markup instead of silently limping through
    it, which the stdlib parser does by default."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tag_stack = []

    def handle_starttag(self, tag, attrs):
        void_elements = {"meta", "br", "img", "hr", "input", "link"}
        if tag not in void_elements:
            self.tag_stack.append(tag)

    def handle_endtag(self, tag):
        assert self.tag_stack, f"unexpected closing tag </{tag}> with nothing open"
        assert self.tag_stack[-1] == tag, f"mismatched close: expected </{self.tag_stack[-1]}>, got </{tag}>"
        self.tag_stack.pop()


def test_export_produces_well_formed_html(tmp_path):
    output = export_session("multi_tool_session", sessions_dir=FIXTURES, output_path=tmp_path / "out.html")
    content = output.read_text()

    validator = _StrictValidator()
    validator.feed(content)
    assert validator.tag_stack == []  # every tag closed


def test_export_contains_session_id_and_event_names(tmp_path):
    output = export_session("multi_tool_session", sessions_dir=FIXTURES, output_path=tmp_path / "out.html")
    content = output.read_text()

    assert "multi_tool_session" in content
    assert "PreToolUse" in content
    assert "PostToolUse" in content
    assert content.count('class="row') == 7  # matches the fixture's line count


def test_export_escapes_html_special_characters(tmp_path):
    session_dir = tmp_path / "sess-xss"
    session_dir.mkdir()
    (session_dir / "main.jsonl").write_text(
        '{"ad_schema":1,"ad_ts":100.0,"ad_seq":0,"ad_host_pid":1,'
        '"event":{"session_id":"sess-xss","hook_event_name":"UserPromptSubmit",'
        '"prompt":"<script>alert(1)</script> & \\"quotes\\""}}\n'
    )

    output = export_session("sess-xss", sessions_dir=tmp_path, output_path=tmp_path / "out.html")
    content = output.read_text()

    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;" in content


def test_export_marks_failures_and_subagent_lanes(tmp_path):
    session_dir = tmp_path / "sess-1"
    session_dir.mkdir()
    (session_dir / "main.jsonl").write_text(
        '{"ad_schema":1,"ad_ts":100.0,"ad_seq":0,"ad_host_pid":1,'
        '"event":{"session_id":"sess-1","hook_event_name":"PostToolUseFailure","tool_name":"Bash"}}\n'
    )
    (session_dir / "agent-a1.jsonl").write_text(
        '{"ad_schema":1,"ad_ts":101.0,"ad_seq":0,"ad_host_pid":1,'
        '"event":{"session_id":"sess-1","agent_id":"a1","hook_event_name":"PreToolUse","tool_name":"Read"}}\n'
    )

    output = export_session("sess-1", sessions_dir=tmp_path, output_path=tmp_path / "out.html")
    content = output.read_text()

    assert 'class="row failure"' in content
    assert 'class="row subagent"' in content


def test_export_default_output_path_uses_session_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_dir = tmp_path / "sessions" / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "main.jsonl").write_text(
        '{"ad_schema":1,"ad_ts":100.0,"ad_seq":0,"ad_host_pid":1,'
        '"event":{"session_id":"sess-1","hook_event_name":"SessionStart"}}\n'
    )

    output = export_session("sess-1", sessions_dir=tmp_path / "sessions")
    assert output.name == "agentdeck-sess-1.html"
    assert output.exists()
