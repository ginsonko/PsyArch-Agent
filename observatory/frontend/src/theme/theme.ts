import { createTheme, rem } from '@mantine/core';

export const theme = createTheme({
  primaryColor: 'teal',
  fontFamily:
    'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
  headings: {
    fontFamily:
      'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
    fontWeight: '700',
  },
  defaultRadius: 'sm',
  radius: {
    xs: rem(3),
    sm: rem(6),
    md: rem(8),
    lg: rem(10),
    xl: rem(12),
  },
  components: {
    Button: {
      defaultProps: {
        radius: 'sm',
      },
    },
    Card: {
      defaultProps: {
        radius: 'sm',
        withBorder: true,
      },
    },
    Modal: {
      defaultProps: {
        radius: 'sm',
        overlayProps: { blur: 2 },
      },
    },
  },
});
