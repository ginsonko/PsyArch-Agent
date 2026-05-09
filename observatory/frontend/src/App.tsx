import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from 'react';
import { Alert, Center, Loader, Stack, Text } from '@mantine/core';
import { AppShellLayout, type AppPage } from './components/AppShellLayout';
import { DashboardPage } from './pages/DashboardPage';

const ExperimentPage = lazy(() => import('./pages/ExperimentPage').then((mod) => ({ default: mod.ExperimentPage })));
const RulesPage = lazy(() => import('./pages/RulesPage').then((mod) => ({ default: mod.RulesPage })));
const InspectorPage = lazy(() => import('./pages/InspectorPage').then((mod) => ({ default: mod.InspectorPage })));
const AgentPage = lazy(() => import('./pages/AgentPage').then((mod) => ({ default: mod.AgentPage })));

function PageLoading() {
  return (
    <Center h="60vh">
      <Stack align="center" gap="xs">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">
          页面模块加载中，请稍候…
        </Text>
      </Stack>
    </Center>
  );
}

type ErrorBoundaryProps = {
  resetKey: string;
  children: ReactNode;
};

type ErrorBoundaryState = {
  error: Error | null;
};

class PageErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <Center h="60vh" px="md">
          <Alert color="red" variant="light" title="前端渲染出错，已拦截黑屏">
            <Stack gap={6}>
              <Text size="sm">当前页面渲染时抛出了异常，所以我先把整页黑屏拦住了。</Text>
              <Text size="xs" c="dimmed">
                {this.state.error.message || String(this.state.error)}
              </Text>
            </Stack>
          </Alert>
        </Center>
      );
    }
    return this.props.children;
  }
}

export function App() {
  const isAgentStandalone = window.location.pathname.startsWith('/agent');
  const initialPage = (() => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'agent' || hash === 'experiment' || hash === 'rules' || hash === 'inspector') return hash as AppPage;
    if (isAgentStandalone) return 'agent';
    return 'dashboard';
  })();
  const [page, setPage] = useState<AppPage>(initialPage);
  const [status, setStatus] = useState('');

  useEffect(() => {
    document.title = isAgentStandalone || page === 'agent' ? 'PsyArch Agent' : 'AP 研究仪表盘';
  }, [isAgentStandalone, page]);

  function changePage(next: AppPage) {
    setPage(next);
    if (next === 'agent') {
      window.history.replaceState(null, '', '/agent/');
      return;
    }
    if (window.location.pathname.startsWith('/agent')) {
      window.history.replaceState(null, '', `/next/#${next}`);
      return;
    }
    window.history.replaceState(null, '', `#${next}`);
  }

  if (isAgentStandalone) {
    return (
      <PageErrorBoundary resetKey="agent-standalone">
        <Suspense fallback={<PageLoading />}>
          <AgentPage onStatusChange={setStatus} />
        </Suspense>
      </PageErrorBoundary>
    );
  }

  return (
    <AppShellLayout page={page} onPageChange={changePage} statusText={status}>
      <PageErrorBoundary resetKey={page}>
        {page === 'dashboard' ? <DashboardPage onStatusChange={setStatus} /> : null}
        <Suspense fallback={<PageLoading />}>
          {page === 'experiment' ? <ExperimentPage onStatusChange={setStatus} /> : null}
          {page === 'agent' ? <AgentPage onStatusChange={setStatus} /> : null}
          {page === 'rules' ? <RulesPage /> : null}
          {page === 'inspector' ? <InspectorPage /> : null}
        </Suspense>
      </PageErrorBoundary>
    </AppShellLayout>
  );
}
