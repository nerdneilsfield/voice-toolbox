import { describe, expect, it } from "vitest";
import { parsePodcastScriptPreview } from "./podcastScript";

describe("podcast script preview parser", () => {
  it("parses speaker lines with pause overrides", () => {
    const parsed = parsePodcastScriptPreview("Alice: Hi [pause:800]\nBob: Yo", "speaker_colon", 350);

    expect(parsed.speakers.map((speaker) => speaker.name)).toEqual(["Alice", "Bob"]);
    expect(parsed.segments[0]).toMatchObject({ speakerName: "Alice", text: "Hi", pauseAfterMs: 800 });
  });

  it("reports invalid lines", () => {
    const parsed = parsePodcastScriptPreview("not valid", "speaker_colon", 350);

    expect(parsed.errors[0].line).toBe(1);
  });

  it("previews markdown and json scripts", () => {
    const markdown = parsePodcastScriptPreview("### Alice\nHi\n\n### Bob\nYo", "markdown", 350);
    const json = parsePodcastScriptPreview(
      '{"lines":[{"speaker":"Alice","text":"Hi","pause_after_ms":0}]}',
      "json",
      350,
    );
    const yaml = parsePodcastScriptPreview(
      "lines:\n  - speaker: Bob\n    text: Yo\n    pause_after_ms: 0",
      "yaml",
      350,
    );

    expect(markdown.segments.map((segment) => segment.speakerName)).toEqual(["Alice", "Bob"]);
    expect(json.segments[0]).toMatchObject({ speakerName: "Alice", pauseAfterMs: 0 });
    expect(yaml.segments[0]).toMatchObject({ speakerName: "Bob", pauseAfterMs: 0 });
  });

  it("auto-detects structured, markdown, and speaker line scripts", () => {
    expect(
      parsePodcastScriptPreview('{"lines":[{"speaker":"Alice","text":"Hi"}]}', "auto", 350).segments[0],
    ).toMatchObject({
      speakerName: "Alice",
    });
    expect(parsePodcastScriptPreview("lines:\n  - speaker: Bob\n    text: Yo", "auto", 350).segments[0]).toMatchObject({
      speakerName: "Bob",
    });
    expect(parsePodcastScriptPreview("### Carol\nHello", "auto", 350).segments[0]).toMatchObject({
      speakerName: "Carol",
    });
    expect(parsePodcastScriptPreview("Dan: Hey", "auto", 350).segments[0]).toMatchObject({
      speakerName: "Dan",
    });
  });
});
