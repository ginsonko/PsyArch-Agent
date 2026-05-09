import { Alert } from '@mantine/core';

export type FeedbackState = {
  kind: 'info' | 'ok' | 'warn' | 'error';
  message: string;
};

type FeedbackAlertProps = {
  feedback: FeedbackState | null;
};

const colorByKind = {
  info: 'blue',
  ok: 'teal',
  warn: 'yellow',
  error: 'red',
} as const;

export function FeedbackAlert({ feedback }: FeedbackAlertProps) {
  if (!feedback) return null;
  return (
    <Alert color={colorByKind[feedback.kind]} variant="light" mt="sm">
      {feedback.message}
    </Alert>
  );
}
