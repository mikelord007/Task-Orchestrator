import { Empty } from "@/components/ui";

/**
 * prompt.md, rendered. Headings and fenced code get structure; everything else
 * keeps the author's line breaks, because whitespace in a system prompt is
 * load-bearing.
 */
export default function PromptTab({ prompt }: { prompt: string }) {
  if (!prompt.trim()) {
    return (
      <Empty>
        This version has no prompt.md. Generating an agent writes one; the improver edits it when
        it picks the prompt lever.
      </Empty>
    );
  }

  const blocks: React.ReactNode[] = [];
  const lines = prompt.replace(/\r\n/g, "\n").split("\n");
  let buffer: string[] = [];

  const flush = (key: string) => {
    if (buffer.length === 0) return;
    const text = buffer.join("\n").replace(/\n+$/, "");
    if (text.trim())
      blocks.push(
        <pre key={key} className="whitespace-pre-wrap text-[12px] leading-[1.6] text-fg-dim">
          {text}
        </pre>,
      );
    buffer = [];
  };

  lines.forEach((line, i) => {
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      flush(`p${i}`);
      const level = heading[1].length;
      blocks.push(
        <h3
          key={`h${i}`}
          className={`mt-4 first:mt-0 text-fg ${level === 1 ? "text-[13px]" : "text-[12px]"}`}
        >
          {heading[2]}
        </h3>,
      );
      return;
    }
    buffer.push(line);
  });
  flush("tail");

  return (
    <div className="max-w-[76ch] border-l-2 border-ink-600 py-2 pl-4">
      {blocks}
    </div>
  );
}
