import { Card, Group, Loader, Stack, Text } from '@mantine/core';

type LoadingPanelProps = {
  title?: string;
  description?: string;
  minHeight?: number;
};

export function LoadingPanel({
  title = '正在加载数据',
  description = '观测台正在拉取最新数据，请稍候。',
  minHeight = 220,
}: LoadingPanelProps) {
  return (
    <Card className="loading-panel-card">
      <Group className="loading-panel" style={{ minHeight }}>
        <Loader size="sm" />
        <Stack gap={4}>
          <Text fw={800}>{title}</Text>
          <Text size="sm" c="dimmed">
            {description}
          </Text>
        </Stack>
      </Group>
    </Card>
  );
}
