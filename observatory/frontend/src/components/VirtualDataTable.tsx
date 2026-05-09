import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Box, Table, Text } from '@mantine/core';
import { useMemo, useRef } from 'react';

type VirtualDataTableProps<T extends object> = {
  data: T[];
  columns: ColumnDef<T, any>[];
  height?: number;
  emptyText?: string;
  onRowClick?: (row: T) => void;
  getRowKey?: (row: T, index: number) => string;
  selectedKey?: string;
  estimateRowHeight?: number;
};

export function VirtualDataTable<T extends object>({
  data,
  columns,
  height = 420,
  emptyText = '当前没有数据。',
  onRowClick,
  getRowKey,
  selectedKey,
  estimateRowHeight = 42,
}: VirtualDataTableProps<T>) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const stableData = useMemo(() => data || [], [data]);
  const table = useReactTable({
    data: stableData,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });
  const rows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimateRowHeight,
    measureElement: (element) => element?.getBoundingClientRect().height || estimateRowHeight,
    overscan: 12,
  });

  if (!rows.length) {
    return (
      <Box className="empty-box" h={height}>
        <Text c="dimmed">{emptyText}</Text>
      </Box>
    );
  }

  return (
    <Box className="virtual-table" ref={parentRef} h={height}>
      <Table stickyHeader striped highlightOnHover withTableBorder={false} withColumnBorders={false} miw={760}>
        <Table.Thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <Table.Tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <Table.Th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</Table.Th>
              ))}
            </Table.Tr>
          ))}
        </Table.Thead>
        <Table.Tbody style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const row = rows[virtualRow.index];
            const original = row.original;
            const rowKey = getRowKey?.(original, virtualRow.index) || row.id;
            const selected = selectedKey && selectedKey === rowKey;
            return (
              <Table.Tr
                key={row.id}
                className={selected ? 'virtual-row-selected' : undefined}
                onClick={onRowClick ? () => onRowClick(original) : undefined}
                ref={virtualizer.measureElement}
                data-index={virtualRow.index}
                style={{
                  position: 'absolute',
                  transform: `translateY(${virtualRow.start}px)`,
                  width: '100%',
                  display: 'table',
                  tableLayout: 'fixed',
                  cursor: onRowClick ? 'pointer' : undefined,
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <Table.Td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Table.Td>
                ))}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Box>
  );
}
