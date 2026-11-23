import { Fragment, type ReactNode } from "react";

/** Tiny, safe renderer for the agent's light markdown: **bold**, *italic*, bullets, line breaks.
 * Builds React nodes (never sets innerHTML), so model output can't inject HTML. */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = (k: number) => {
    if (list.length) {
      blocks.push(
        <ul key={`ul-${k}`}>
          {list.map((li, j) => (
            <li key={j}>{inline(li, `li-${k}-${j}`)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  lines.forEach((raw, k) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      list.push(bullet[1]);
      return;
    }
    flush(k);
    if (!line.trim()) return;
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    blocks.push(
      heading ? (
        <p key={k} className="md-heading">
          {inline(heading[1], `h-${k}`)}
        </p>
      ) : (
        <p key={k}>{inline(line, `p-${k}`)}</p>
      ),
    );
  });
  flush(lines.length);
  return <Fragment>{blocks}</Fragment>;
}
