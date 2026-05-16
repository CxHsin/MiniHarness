from pathlib import Path

from miniharness.tools.base import ToolContext, ToolResult, is_sensitive_path
from miniharness.tools.fs import ListDirTool, ReadFileTool, WriteFileTool


def test_tool_schema_conversion(fake_tool_context):
    tool = ListDirTool()

    schema = tool.to_openai_tool()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "list_dir"
    assert schema["function"]["parameters"]["type"] == "object"


def test_rejects_path_outside_cwd(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    context = ToolContext(cwd=tmp_path)

    result = ReadFileTool().execute({"path": str(outside)}, context)

    assert result.ok is False
    assert "outside" in result.error


def test_list_dir_formats_directories_before_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    context = ToolContext(cwd=tmp_path)

    result = ListDirTool().execute({"path": "."}, context)

    assert result.ok is True
    lines = result.output.splitlines()
    assert lines[0] == "[dir]  src/"
    assert lines[1].startswith("[file] pyproject.toml  ")
    assert lines[1].endswith(" bytes")


def test_list_dir_limits_large_directories(tmp_path):
    for index in range(505):
        (tmp_path / f"file_{index:03}.txt").write_text("x", encoding="utf-8")
    context = ToolContext(cwd=tmp_path)

    result = ListDirTool().execute({"path": "."}, context)

    assert result.ok is True
    assert len([line for line in result.output.splitlines() if line.startswith("[file]")]) == 500
    assert "5 entries omitted" in result.output


def test_read_file_line_window(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    context = ToolContext(cwd=tmp_path)

    result = ReadFileTool().execute(
        {"path": "sample.txt", "start_line": 2, "limit": 1},
        context,
    )

    assert result == ToolResult(ok=True, output="2: two", error=None, metadata={})


def test_read_file_rejects_binary_file(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\x00binary")
    context = ToolContext(cwd=tmp_path)

    result = ReadFileTool().execute({"path": "image.png"}, context)

    assert result.ok is False
    assert "Binary file" in result.error


def test_write_file_overwrites_and_creates_parent(tmp_path):
    context = ToolContext(cwd=tmp_path)

    result = WriteFileTool().execute(
        {"path": "nested/file.txt", "content": "hello"},
        context,
    )
    second = WriteFileTool().execute(
        {"path": "nested/file.txt", "content": "goodbye"},
        context,
    )

    assert result.ok is True
    assert second.ok is True
    assert (tmp_path / "nested" / "file.txt").read_text(encoding="utf-8") == "goodbye"


def test_allow_outside_cwd_opt_out(tmp_path):
    outside = tmp_path.parent / "outside-write.txt"
    context = ToolContext(cwd=tmp_path, allow_outside_cwd=True)

    result = WriteFileTool().execute(
        {"path": str(outside), "content": "allowed"},
        context,
    )

    assert result.ok is True
    assert outside.read_text(encoding="utf-8") == "allowed"
    outside.unlink()


def test_sensitive_path_detection_flags_credentials():
    assert is_sensitive_path(Path.home() / ".ssh" / "id_rsa") is True
    assert is_sensitive_path(Path("project") / "src" / "app.py") is False
