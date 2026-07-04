from __future__ import annotations

import pytest

from voice_toolbox.podcast.parser import PodcastParseError, parse_podcast_script


def test_parse_speaker_colon_preserves_speakers_and_pause() -> None:
    script = "Alice: Hello there [pause:800]\nBob: General Kenobi [pause:0]"

    parsed = parse_podcast_script(script, script_format="speaker_colon", default_pause_ms=350)

    assert [speaker.name for speaker in parsed.speakers] == ["Alice", "Bob"]
    assert [
        (segment.speaker_name, segment.text, segment.pause_after_ms) for segment in parsed.segments
    ] == [
        ("Alice", "Hello there", 800),
        ("Bob", "General Kenobi", 0),
    ]
    assert parsed.segments[0].source_line == 1


def test_parse_standalone_pause_applies_to_previous_segment() -> None:
    script = "Alice: Hello\n[pause:1200]\nBob: Next"

    parsed = parse_podcast_script(script, script_format="speaker_colon", default_pause_ms=350)

    assert [segment.pause_after_ms for segment in parsed.segments] == [1200, 350]


def test_parse_markdown_headings_split_paragraphs() -> None:
    script = "### Alice\nHello.\n\nSecond paragraph.\n### Bob\nReply."

    parsed = parse_podcast_script(script, script_format="markdown", default_pause_ms=250)

    assert [speaker.name for speaker in parsed.speakers] == ["Alice", "Bob"]
    assert [segment.text for segment in parsed.segments] == [
        "Hello.",
        "Second paragraph.",
        "Reply.",
    ]
    assert parsed.segments[2].speaker_name == "Bob"


def test_parse_json_and_yaml_lines() -> None:
    json_parsed = parse_podcast_script(
        '{"lines":[{"speaker":"Alice","text":"JSON line"}]}',
        script_format="json",
        default_pause_ms=200,
    )
    yaml_parsed = parse_podcast_script(
        "lines:\n  - speaker: Bob\n    text: YAML line\n",
        script_format="yaml",
        default_pause_ms=200,
    )

    assert json_parsed.segments[0].text == "JSON line"
    assert yaml_parsed.segments[0].speaker_name == "Bob"


def test_parse_auto_detects_structured_and_markdown() -> None:
    assert parse_podcast_script('{"lines":[{"speaker":"A","text":"x"}]}').source_format == "json"
    assert parse_podcast_script("lines:\n  - speaker: A\n    text: x").source_format == "yaml"
    assert parse_podcast_script("### A\nx").source_format == "markdown"
    assert parse_podcast_script("A: x").source_format == "speaker_colon"


def test_parse_rejects_more_than_max_segments() -> None:
    script = "\n".join(f"A: line {index}" for index in range(201))

    with pytest.raises(PodcastParseError, match="more than 200"):
        parse_podcast_script(script)


def test_parse_errors_include_line_number() -> None:
    with pytest.raises(PodcastParseError) as exc:
        parse_podcast_script("Alice: hello [pause:nope]", script_format="speaker_colon")

    assert exc.value.line == 1
    assert "pause" in str(exc.value)
