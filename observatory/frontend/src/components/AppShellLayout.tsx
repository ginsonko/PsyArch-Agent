import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  NavLink,
  NumberInput,
  Text,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconActivity,
  IconAdjustments,
  IconBrain,
  IconChartLine,
  IconDatabase,
  IconMessageCircle,
  IconMoon,
  IconRoute,
  IconSun,
} from '@tabler/icons-react';
import { useEffect, useState, type ReactNode } from 'react';
import { getRequestTimeoutMs, setRequestTimeoutMs } from '../lib/api';

export type AppPage = 'dashboard' | 'agent' | 'experiment' | 'rules' | 'inspector';

type LayoutProps = {
  page: AppPage;
  onPageChange: (page: AppPage) => void;
  children: ReactNode;
  statusText?: string;
};

const navItems = [
  { page: 'dashboard' as const, label: '实时观测', desc: 'Tick、状态池、HDB、行动', icon: IconActivity },
  { page: 'agent' as const, label: 'PA Agent', desc: '对话、想法、拟人接口', icon: IconMessageCircle },
  { page: 'experiment' as const, label: '长期实验', desc: '数据集、图表、调参', icon: IconChartLine },
  { page: 'rules' as const, label: '先天规则', desc: 'YAML、图编辑、模拟', icon: IconRoute },
  { page: 'inspector' as const, label: '检视器', desc: '结构、组、EM 查询', icon: IconDatabase },
];

export function AppShellLayout({ page, onPageChange, children, statusText }: LayoutProps) {
  const [opened, { toggle }] = useDisclosure();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const dark = colorScheme === 'dark';
  const [requestTimeoutMs, setRequestTimeoutMsState] = useState<number>(getRequestTimeoutMs());

  useEffect(() => {
    function syncTimeout(event?: Event) {
      const detailValue =
        event && 'detail' in event && typeof (event as CustomEvent<number>).detail === 'number'
          ? (event as CustomEvent<number>).detail
          : getRequestTimeoutMs();
      setRequestTimeoutMsState(Number(detailValue) || getRequestTimeoutMs());
    }
    window.addEventListener('ap-next-timeout-changed', syncTimeout as EventListener);
    return () => window.removeEventListener('ap-next-timeout-changed', syncTimeout as EventListener);
  }, []);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 290, breakpoint: 'md', collapsed: { mobile: !opened } }}
      padding={0}
    >
      <AppShell.Header className="topbar">
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="md" size="sm" />
            <div className="brand-mark">AP</div>
            <div>
              <Text fw={800} size="sm">
                AP / PA 研究仪表盘
              </Text>
              <Text size="xs" c="dimmed">
                Research Dashboard / Agent Lab
              </Text>
            </div>
          </Group>
          <Group gap="xs">
            {statusText ? (
              <Badge variant="light" color="teal">
                {statusText}
              </Badge>
            ) : null}
            <Tooltip label="全局请求超时（毫秒）。默认 60000；页面加载失败时也可以先在这里调高。">
              <NumberInput
                aria-label="请求超时毫秒"
                size="xs"
                hideControls
                value={requestTimeoutMs}
                min={5000}
                max={600000}
                step={5000}
                w={118}
                placeholder="超时 ms"
                onChange={(value) => {
                  const next = setRequestTimeoutMs(value === '' ? 60000 : Number(value) || 60000);
                  setRequestTimeoutMsState(next);
                }}
              />
            </Tooltip>
            <Tooltip label={dark ? '切换浅色' : '切换深色'}>
              <ActionIcon variant="subtle" onClick={() => setColorScheme(dark ? 'light' : 'dark')}>
                {dark ? <IconSun size={18} /> : <IconMoon size={18} />}
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className="sidebar-next" p="md">
        <div className="sidebar-title">
          <Text size="xs" c="dimmed" fw={800} tt="uppercase">
            Artificial PsyArch
          </Text>
          <Text fw={800} size="xl" className="sidebar-title-main">
            <IconBrain size={21} /> 观测与 Agent
          </Text>
        </div>
        <div className="nav-stack">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.page}
                active={page === item.page}
                label={item.label}
                description={item.desc}
                leftSection={<Icon size={18} />}
                onClick={() => onPageChange(item.page)}
              />
            );
          })}
        </div>
        <div className="sidebar-footer">
          <Group gap="xs">
            <IconAdjustments size={16} />
            <Text size="xs" c="dimmed">
              旧前端仍保留在 `/`，本页为 `/next/` 并行重构版。
            </Text>
          </Group>
        </div>
      </AppShell.Navbar>

      <AppShell.Main className="main-next">{children}</AppShell.Main>
    </AppShell>
  );
}
