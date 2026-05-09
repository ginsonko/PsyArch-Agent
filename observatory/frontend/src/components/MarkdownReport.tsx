import { Fragment, type ReactNode } from 'react';

type MarkdownReportProps = {
  text?: string;
  emptyText?: string;
  className?: string;
};

type Block =
  | { type: 'heading'; level: number; text: string; key: string }
  | { type: 'paragraph'; lines: string[]; key: string }
  | { type: 'list'; items: string[]; key: string }
  | { type: 'table'; rows: string[][]; key: string }
  | { type: 'hr'; key: string };

function splitTableRow(line: string): string[] {
  let text = line.trim();
  if (text.startsWith('|')) text = text.slice(1);
  if (text.endsWith('|')) text = text.slice(0, -1);
  return text.split('|').map((cell) => cell.trim());
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isTableLine(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.includes('|');
}

function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const blocks: Block[] = [];
  let index = 0;
  let keyIndex = 0;
  const nextKey = (type: string) => `${type}-${keyIndex++}`;

  while (index < lines.length) {
    const trimmed = lines[index].trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      blocks.push({ type: 'hr', key: nextKey('hr') });
      index += 1;
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    if (heading) {
      blocks.push({
        type: 'heading',
        level: Math.min(4, heading[1].length),
        text: heading[2].trim(),
        key: nextKey('heading'),
      });
      index += 1;
      continue;
    }

    if (isTableLine(trimmed) && index + 1 < lines.length && isTableSeparator(lines[index + 1].trim())) {
      const rows: string[][] = [splitTableRow(trimmed)];
      index += 2;
      while (index < lines.length && isTableLine(lines[index].trim())) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push({ type: 'table', rows, key: nextKey('table') });
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, '').trim());
        index += 1;
      }
      blocks.push({ type: 'list', items, key: nextKey('list') });
      continue;
    }

    const paragraphLines: string[] = [trimmed];
    index += 1;
    while (index < lines.length) {
      const next = lines[index].trim();
      if (!next || /^---+$/.test(next) || /^(#{1,6})\s+/.test(next) || /^[-*]\s+/.test(next)) break;
      if (isTableLine(next) && index + 1 < lines.length && isTableSeparator(lines[index + 1].trim())) break;
      paragraphLines.push(next);
      index += 1;
    }
    blocks.push({ type: 'paragraph', lines: paragraphLines, key: nextKey('paragraph') });
  }

  return blocks;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith('`')) {
      nodes.push(<code key={`code-${match.index}`}>{token.slice(1, -1)}</code>);
    } else {
      nodes.push(<strong key={`strong-${match.index}`}>{token.slice(2, -2)}</strong>);
    }
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function renderParagraphLines(lines: string[]): ReactNode {
  return lines.map((line, index) => (
    <Fragment key={`${index}-${line.slice(0, 12)}`}>
      {index > 0 ? <br /> : null}
      {renderInline(line)}
    </Fragment>
  ));
}

export function MarkdownReport({ text = '', emptyText = '暂无报告。', className = '' }: MarkdownReportProps) {
  const content = String(text || '').trim();
  if (!content) {
    return <div className={`markdown-report markdown-report-empty ${className}`}>{emptyText}</div>;
  }
  const blocks = parseBlocks(content);
  return (
    <div className={`markdown-report ${className}`}>
      {blocks.map((block) => {
        if (block.type === 'heading') {
          if (block.level === 1) return <h1 key={block.key}>{renderInline(block.text)}</h1>;
          if (block.level === 2) return <h2 key={block.key}>{renderInline(block.text)}</h2>;
          if (block.level === 3) return <h3 key={block.key}>{renderInline(block.text)}</h3>;
          return <h4 key={block.key}>{renderInline(block.text)}</h4>;
        }
        if (block.type === 'list') {
          return (
            <ul key={block.key}>
              {block.items.map((item, index) => <li key={`${block.key}-${index}`}>{renderInline(item)}</li>)}
            </ul>
          );
        }
        if (block.type === 'table') {
          const [head, ...body] = block.rows;
          return (
            <div className="markdown-report-table-wrap" key={block.key}>
              <table>
                <thead>
                  <tr>{head.map((cell, index) => <th key={`${block.key}-h-${index}`}>{renderInline(cell)}</th>)}</tr>
                </thead>
                <tbody>
                  {body.map((row, rowIndex) => (
                    <tr key={`${block.key}-r-${rowIndex}`}>
                      {head.map((_, cellIndex) => (
                        <td key={`${block.key}-r-${rowIndex}-${cellIndex}`}>
                          {renderInline(row[cellIndex] || '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.type === 'hr') return <hr key={block.key} />;
        return <p key={block.key}>{renderParagraphLines(block.lines)}</p>;
      })}
    </div>
  );
}
