import { Card, Group, Text, ThemeIcon } from '@mantine/core';
import type { ReactNode } from 'react';

type MetricCardProps = {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  icon?: ReactNode;
  tone?: 'default' | 'ok' | 'warn' | 'danger';
};

const toneColor = {
  default: 'gray',
  ok: 'teal',
  warn: 'yellow',
  danger: 'red',
} as const;

export function MetricCard({ label, value, note, icon, tone = 'default' }: MetricCardProps) {
  return (
    <Card className="metric-card">
      <Group justify="space-between" align="flex-start" gap="sm">
        <div>
          <Text size="xs" c="dimmed" fw={700} tt="uppercase">
            {label}
          </Text>
          <Text className="metric-value">{value}</Text>
        </div>
        {icon ? (
          <ThemeIcon variant="light" color={toneColor[tone]} size="lg">
            {icon}
          </ThemeIcon>
        ) : null}
      </Group>
      {note ? (
        <Text size="xs" c="dimmed" mt={8}>
          {note}
        </Text>
      ) : null}
    </Card>
  );
}
