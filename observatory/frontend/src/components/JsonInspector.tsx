import { ActionIcon, Code, Group, ScrollArea, Text, Tooltip } from '@mantine/core';
import { IconCopy } from '@tabler/icons-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { jsonPretty } from '../lib/format';

type JsonInspectorProps = {
  value: unknown;
  title?: string;
  maxHeight?: number | string;
};

const MAX_JSON_PREVIEW_CHARS = 200_000;

export function JsonInspector({ value, title = 'JSON', maxHeight = 420 }: JsonInspectorProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [shouldRender, setShouldRender] = useState(false);

  useEffect(() => {
    const host = rootRef.current?.closest('details');
    if (!host) {
      setShouldRender(true);
      return undefined;
    }
    const sync = () => setShouldRender(Boolean(host.open));
    sync();
    host.addEventListener('toggle', sync);
    return () => host.removeEventListener('toggle', sync);
  }, []);

  const text = useMemo(() => {
    if (!shouldRender) return '';
    const pretty = jsonPretty(value);
    if (pretty.length <= MAX_JSON_PREVIEW_CHARS) return pretty;
    const head = pretty.slice(0, Math.max(0, MAX_JSON_PREVIEW_CHARS - 320));
    const tail = pretty.slice(-240);
    return `${head}\n\n/* JSON 过大，前端仅展示部分内容以避免页面卡死。总长度约 ${pretty.length.toLocaleString('zh-CN')} 字符。 */\n\n${tail}`;
  }, [shouldRender, value]);

  return (
    <div className="json-inspector" ref={rootRef}>
      <Group justify="space-between" mb="xs">
        <Text size="sm" fw={700}>
          {title}
        </Text>
        <Tooltip label="复制 JSON">
          <ActionIcon variant="subtle" onClick={() => navigator.clipboard?.writeText(text)} disabled={!shouldRender}>
            <IconCopy size={16} />
          </ActionIcon>
        </Tooltip>
      </Group>
      {!shouldRender ? (
        <Text size="xs" c="dimmed">
          展开此面板后再生成高级 JSON 预览，避免首屏一次性渲染过大的原始对象。
        </Text>
      ) : (
        <ScrollArea.Autosize mah={maxHeight}>
          <Code block className="json-code">
            {text}
          </Code>
        </ScrollArea.Autosize>
      )}
    </div>
  );
}
