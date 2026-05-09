import { Badge, Button, Card, Group, JsonInput, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import type { AnyRecord } from '../types/api';
import { shortText } from '../lib/format';

type ConfigMiniEditorProps = {
  bundle: AnyRecord | null;
  onSave: (moduleName: string, values: AnyRecord) => Promise<void>;
};

function primitiveDraft(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function parseDraft(value: string, original: unknown): unknown {
  if (typeof original === 'boolean') return value === 'true';
  if (typeof original === 'number') {
    const n = Number(value);
    return Number.isFinite(n) ? n : original;
  }
  if (original && typeof original === 'object') {
    try {
      return JSON.parse(value);
    } catch {
      return original;
    }
  }
  return value;
}

function displayLabel(field: AnyRecord, key: string): string {
  const note = String(field?.comment_text || '').trim();
  const firstLine = note.split(/\r?\n/).map((line) => line.trim()).find(Boolean);
  if (firstLine && firstLine.length <= 28) return firstLine;
  return key;
}

function sectionStats(section: AnyRecord): { count: number; overrideCount: number } {
  const rows = Array.isArray(section?.fields) ? section.fields : [];
  return {
    count: rows.length,
    overrideCount: rows.filter((item: AnyRecord) => item?.has_override).length,
  };
}

export function ConfigMiniEditor({ bundle, onSave }: ConfigMiniEditorProps) {
  const modules = useMemo(() => Object.keys(bundle || {}).sort(), [bundle]);
  const [moduleName, setModuleName] = useState('');
  const [draft, setDraft] = useState<Record<string, string>>({});
  const current = moduleName ? bundle?.[moduleName] : null;
  const effective = (current?.effective || current?.file_values || current?.defaults || {}) as AnyRecord;
  const sections = useMemo(() => (Array.isArray(current?.sections) ? current.sections : []), [current]);
  const fields = useMemo(() => Object.keys(effective || {}).slice(0, 200), [effective]);

  useEffect(() => {
    if (!moduleName && modules.length) setModuleName(modules[0]);
  }, [moduleName, modules]);

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const key of fields) next[key] = primitiveDraft(effective[key]);
    setDraft(next);
  }, [moduleName, fields.join('|')]);

  async function saveChanged() {
    const values: AnyRecord = {};
    for (const key of fields) {
      const parsed = parseDraft(draft[key], effective[key]);
      if (JSON.stringify(parsed) !== JSON.stringify(effective[key])) values[key] = parsed;
    }
    await onSave(moduleName, values);
  }

  return (
    <Card>
      <Group justify="space-between" align="flex-end" mb="md">
        <div>
          <Text fw={800}>配置编辑</Text>
          <Text size="xs" c="dimmed">
            按模块与分组查看生效值。这里的“推荐值”默认指仓库默认值，也就是最稳妥的理论起点；若你已经针对某个数据集建立了专门运行时覆盖，应优先参考那套实验口径。
          </Text>
        </div>
        <Select
          searchable
          label="模块"
          value={moduleName}
          onChange={(value) => setModuleName(value || '')}
          data={modules.map((key) => ({ value: key, label: bundle?.[key]?.title || key }))}
          w={280}
        />
      </Group>

      <Card mb="md" className="soft-note-card">
        <Text fw={800} mb="xs">操作提醒</Text>
        <Stack gap={6}>
          <Text size="sm">
            1. 手工改参数时，请同时检查对应的 AutoTuner 规则、参数边界和长期目标，否则运行中可能很快被调参器拉回另一套范围。
          </Text>
          <Text size="sm">
            2. `默认值` 是默认起点，`文件值` 是当前配置文件写死的值，`运行时覆盖` 则表示当前实验过程中已经被临时改过。
          </Text>
          <Text size="sm">
            3. 复杂对象仍可用 JSON 编辑，但建议先看注释再改，避免把多个联动阈值拆散。
          </Text>
        </Stack>
      </Card>

      <Stack gap="md">
        {sections.map((section: AnyRecord) => {
          const rows = Array.isArray(section?.fields) ? section.fields : [];
          const stats = sectionStats(section);
          return (
            <Card key={String(section?.title || 'section')} className="soft-note-card">
              <Group justify="space-between" align="flex-start" mb="sm">
                <div>
                  <Text fw={800}>{String(section?.title || '未分组')}</Text>
                  <Text size="xs" c="dimmed">
                    本组 {stats.count} 项{stats.overrideCount ? `，其中 ${stats.overrideCount} 项存在运行时覆盖` : ''}。
                  </Text>
                </div>
                <Badge variant="light">{stats.count}</Badge>
              </Group>
              <Stack gap="xs" className="config-mini-grid">
                {rows.map((meta: AnyRecord) => {
                  const key = String(meta?.key || '');
                  const original = effective[key];
                  const value = draft[key] ?? '';
                  const note = String(meta?.comment_text || '').trim();
                  const label = displayLabel(meta, key);
                  const defaultText = primitiveDraft(meta?.default_value);
                  const fileText = primitiveDraft(meta?.file_value);
                  const effectiveText = primitiveDraft(meta?.effective_value);
                  const overrideText = meta?.has_override ? primitiveDraft(meta?.override_value) : '';
                  const footer = `推荐起点 ${defaultText || '-'} / 文件值 ${fileText || '-'} / 当前生效 ${effectiveText || '-'}${meta?.has_override ? ` / 运行时覆盖 ${overrideText || '-'}` : ''}`;
                  if (typeof original === 'boolean') {
                    return (
                      <Card key={key} className="soft-note-card">
                        <Switch
                          label={label}
                          checked={value === 'true'}
                          onChange={(event) => setDraft((prev) => ({ ...prev, [key]: String(event.currentTarget.checked) }))}
                        />
                        <Text size="xs" c="dimmed" mt={4}>
                          技术键：{key}
                        </Text>
                        {note ? (
                          <Text size="xs" c="dimmed" mt={6}>
                            {shortText(note, 280)}
                          </Text>
                        ) : null}
                        <Text size="xs" c="dimmed" mt={4}>
                          {footer}
                        </Text>
                      </Card>
                    );
                  }
                  if (original && typeof original === 'object') {
                    return (
                      <Card key={key} className="soft-note-card">
                        <JsonInput
                          label={label}
                          value={value}
                          onChange={(next) => setDraft((prev) => ({ ...prev, [key]: next }))}
                          autosize
                          minRows={2}
                          maxRows={6}
                          validationError="JSON 格式不正确"
                        />
                        <Text size="xs" c="dimmed" mt={4}>
                          技术键：{key}
                        </Text>
                        {note ? (
                          <Text size="xs" c="dimmed" mt={6}>
                            {shortText(note, 280)}
                          </Text>
                        ) : null}
                        <Text size="xs" c="dimmed" mt={4}>
                          {footer}
                        </Text>
                      </Card>
                    );
                  }
                  return (
                    <Card key={key} className="soft-note-card">
                      <TextInput
                        label={label}
                        value={value}
                        onChange={(event) => setDraft((prev) => ({ ...prev, [key]: event.currentTarget.value }))}
                      />
                      <Text size="xs" c="dimmed" mt={4}>
                        技术键：{key}
                      </Text>
                      {note ? (
                        <Text size="xs" c="dimmed" mt={6}>
                          {shortText(note, 280)}
                        </Text>
                      ) : null}
                      <Text size="xs" c="dimmed" mt={4}>
                        {footer}
                      </Text>
                    </Card>
                  );
                })}
              </Stack>
            </Card>
          );
        })}
      </Stack>

      <Group mt="md">
        <Button onClick={saveChanged} disabled={!moduleName}>
          保存改动
        </Button>
        <Text size="xs" c="dimmed">
          只提交发生变化的字段；推荐先从默认值附近小步调整，再结合 AutoTuner 的边界与规则一起校验。
        </Text>
      </Group>
    </Card>
  );
}
