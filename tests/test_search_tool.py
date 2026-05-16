from miniharness.tools.search import SearchTextTool


def test_search_text_finds_regex_matches(tmp_path, fake_tool_context):
    (tmp_path / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = SearchTextTool().execute({"pattern": "alp.*", "path": "."}, fake_tool_context)

    assert result.ok is True
    assert "a.txt:1:alpha" in result.output


def test_search_text_respects_max_results(tmp_path, fake_tool_context):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("needle\n", encoding="utf-8")

    result = SearchTextTool().execute(
        {"pattern": "needle", "path": ".", "max_results": 2},
        fake_tool_context,
    )

    assert result.ok is True
    assert len([line for line in result.output.splitlines() if ":1:needle" in line]) == 2
    assert "matches omitted" in result.output


def test_search_text_skips_generated_directories(tmp_path, fake_tool_context):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "src.txt").write_text("needle\n", encoding="utf-8")

    result = SearchTextTool().execute({"pattern": "needle", "path": "."}, fake_tool_context)

    assert "src.txt:1:needle" in result.output
    assert "ignored.txt" not in result.output


def test_search_text_rejects_invalid_max_results(fake_tool_context):
    result = SearchTextTool().execute(
        {"pattern": "needle", "path": ".", "max_results": 0},
        fake_tool_context,
    )

    assert result.ok is False
    assert "max_results" in result.error


def test_search_text_skips_files_that_cannot_be_made_relative(
    monkeypatch, tmp_path, fake_tool_context
):
    outside = tmp_path.parent / "outside-search.txt"
    outside.write_text("needle\n", encoding="utf-8")
    local = tmp_path / "local.txt"
    local.write_text("needle\n", encoding="utf-8")

    monkeypatch.setattr(SearchTextTool, "_iter_files", lambda self, root: iter([outside, local]))

    result = SearchTextTool().execute({"pattern": "needle", "path": "."}, fake_tool_context)

    assert result.ok is True
    assert "local.txt:1:needle" in result.output
    assert "outside-search.txt" not in result.output
    outside.unlink()
