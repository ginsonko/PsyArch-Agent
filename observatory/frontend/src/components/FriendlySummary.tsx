import { Badge, Card, Group, SimpleGrid, Stack, Text } from '@mantine/core';
import { asArray, formatCount, formatDuration, formatNumber, shortDisplayText, shortText } from '../lib/format';
import type { AnyRecord } from '../types/api';
import { JsonInspector } from './JsonInspector';

type SummaryItem = {
  label: string;
  value: unknown;
  note?: unknown;
};

type SummaryCardProps = {
  title: string;
  description?: string;
  items: SummaryItem[];
  raw?: unknown;
  rawTitle?: string;
};

function displayValue(value: unknown): string {
  if (typeof value === 'number') return formatNumber(value, 4);
  if (typeof value === 'boolean') return value ? '是 / 启用' : '否 / 关闭';
  if (value === null || value === undefined || value === '') return '-';
  return shortDisplayText(value, 90);
}

export function SummaryCard({ title, description, items, raw, rawTitle = '高级原始数据 JSON' }: SummaryCardProps) {
  const visibleItems = items.filter((item) => item.value !== undefined && item.value !== null && item.value !== '');
  return (
    <Card className="summary-card">
      <Group justify="space-between" align="flex-start" mb="xs">
        <div>
          <Text fw={800}>{title}</Text>
          {description ? (
            <Text size="xs" c="dimmed">
              {description}
            </Text>
          ) : null}
        </div>
        <Badge variant="light">{formatCount(visibleItems.length)}</Badge>
      </Group>
      {visibleItems.length ? (
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
          {visibleItems.map((item) => (
            <div key={item.label} className="friendly-detail-item">
              <Text size="xs" c="dimmed">
                {item.label}
              </Text>
              <Text fw={750}>{displayValue(item.value)}</Text>
              {item.note !== undefined && item.note !== null && item.note !== '' ? (
                <Text size="xs" c="dimmed">
                  {shortDisplayText(item.note, 110)}
                </Text>
              ) : null}
            </div>
          ))}
        </SimpleGrid>
      ) : (
        <Text size="sm" c="dimmed">
          暂无可汇总字段。运行一次 tick 或选择更具体的对象后，这里会显示摘要。
        </Text>
      )}
      {raw !== undefined ? (
        <details className="advanced-json-details">
          <summary>{rawTitle}</summary>
          <JsonInspector value={raw} title={rawTitle} maxHeight={240} />
        </details>
      ) : null}
    </Card>
  );
}

export function SensorRuntimeSummary({ value }: { value: AnyRecord | null | undefined }) {
  const root = (value || {}) as AnyRecord;
  return (
    <SummaryCard
      title="疲劳与残响摘要"
      description="观察文本感受器是否正在压低重复输入、回声或残响刺激。"
      items={[
        { label: '疲劳对象数', value: root.fatigue_item_count ?? root.item_count ?? root.active_item_count },
        { label: '疲劳均值', value: root.fatigue_mean ?? root.mean_fatigue },
        { label: '残响对象数', value: root.echo_item_count ?? root.echo_count },
        { label: '残响总量', value: root.echo_total ?? root.total_echo },
        { label: '最近更新', value: root.updated_count ?? root.decayed_count },
        { label: '剪枝数量', value: root.pruned_count ?? root.removed_count },
      ]}
      raw={root}
    />
  );
}

export function TimeRuntimeSummary({ value }: { value: AnyRecord | null | undefined }) {
  const root = (value || {}) as AnyRecord;
  return (
    <SummaryCard
      title="时间感受器运行态"
      description="时间桶、属性绑定和延迟赋能任务的当前状态。"
      items={[
        { label: '时间基准', value: root.time_basis },
        { label: '当前 tick', value: root.tick_index ?? root.current_tick },
        { label: '时间桶更新', value: asArray(root.bucket_updates).length },
        { label: '属性绑定', value: asArray(root.attribute_bindings).length },
        { label: '延迟任务', value: asArray(root.delayed_tasks).length || root.delayed_task_count },
        { label: '已执行任务', value: root.delayed_task_executed_count ?? root.executed_task_count },
      ]}
      raw={root}
    />
  );
}

export function MemoryRuntimeSummary({ value }: { value: AnyRecord | null | undefined }) {
  const root = (value || {}) as AnyRecord;
  return (
    <SummaryCard
      title="记忆维护/回馈摘要"
      description="观察记忆激活、回馈赋能和维护任务是否正常推进。"
      items={[
        { label: '应用回馈数', value: root.applied_count ?? root.feedback_applied_count },
        { label: '回馈 ER', value: root.total_feedback_er ?? root.feedback_er_total },
        { label: '回馈 EV', value: root.total_feedback_ev ?? root.feedback_ev_total },
        { label: '维护对象数', value: root.maintained_count ?? root.updated_count },
        { label: '跳过对象数', value: root.skipped_count },
        { label: '最近原因', value: root.reason ?? root.message },
      ]}
      raw={root}
    />
  );
}

export function EmotionRuntimeSummary({ value }: { value: AnyRecord | null | undefined }) {
  const root = (value || {}) as AnyRecord;
  const nt = root.nt_state_after || root.nt_state_snapshot || root.nt || {};
  const modulation = root.modulation || root;
  const ntText = Object.entries(nt)
    .slice(0, 8)
    .map(([key, val]) => `${key}:${formatNumber(val, 3)}`)
    .join(' / ');
  return (
    <SummaryCard
      title="情绪递质 NT 调制详情"
      description="NT 通道会影响行动阈值、注意力资源、聚焦/发散等运行系数。"
      items={[
        { label: '行动阈值倍率', value: modulation.action_threshold_multiplier ?? modulation.action_threshold_scale },
        { label: '注意力资源倍率', value: modulation.attention_budget_multiplier ?? modulation.attention_energy_budget_multiplier },
        { label: '注意力资源加成', value: modulation.attention_budget_delta ?? modulation.attention_energy_budget_delta },
        { label: '聚焦收窄', value: modulation.focus_narrowing ?? modulation.selection_narrowing },
        { label: 'NT 快照', value: ntText || '-' },
        { label: '更新来源', value: root.source || root.reason || root.stage },
      ]}
      raw={root}
    />
  );
}

export function TimingSummary({ timing, meta }: { timing?: AnyRecord | null; meta?: AnyRecord | null }) {
  const root = (timing || {}) as AnyRecord;
  const metaRoot = (meta || {}) as AnyRecord;
  const entries = Object.entries(root.steps_ms || root)
    .filter(([, value]) => Number.isFinite(Number(value)))
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 6);
  return (
    <Card className="summary-card">
      <Text fw={800}>循环耗时摘要</Text>
      <Text size="xs" c="dimmed" mb="xs">
        用于定位本轮最耗时的模块，避免只看原始 timing JSON。
      </Text>
      <Stack gap={6}>
        {entries.map(([key, value]) => (
          <Group key={key} justify="space-between" className="summary-row">
            <Text size="sm">{key}</Text>
            <Text size="sm" fw={750}>
              {formatDuration(value)}
            </Text>
          </Group>
        ))}
        {!entries.length ? <Text size="sm" c="dimmed">暂无耗时数据。</Text> : null}
      </Stack>
      <Text size="xs" c="dimmed" mt="sm">
        tick {metaRoot.tick_counter ?? metaRoot.tick_id ?? '-'}；trace {shortText(metaRoot.trace_id || metaRoot.run_id || '-', 42)}
      </Text>
      <details className="advanced-json-details">
        <summary>高级 timing/meta JSON</summary>
        <JsonInspector value={{ timing: root, meta: metaRoot }} title="高级 timing/meta JSON" maxHeight={240} />
      </details>
    </Card>
  );
}
