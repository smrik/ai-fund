import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { startTransition, useMemo, useState } from "react";

import type { WatchlistRow } from "@/lib/types";
import { formatCurrency, formatPercent, formatText } from "@/lib/format";

const columns: ColumnDef<WatchlistRow>[] = [
  { accessorKey: "ticker", header: "Ticker", meta: { align: "left" } },
  { accessorKey: "company_name", header: "Company", meta: { align: "left" } },
  {
    accessorKey: "price",
    header: "Price",
    cell: ({ getValue }) => formatCurrency(getValue<number | null>()),
  },
  {
    accessorKey: "iv_base",
    header: "Base IV",
    cell: ({ getValue }) => formatCurrency(getValue<number | null>()),
  },
  {
    accessorKey: "iv_bear",
    header: "Bear",
    cell: ({ getValue }) => formatCurrency(getValue<number | null>()),
  },
  {
    accessorKey: "iv_bull",
    header: "Bull",
    cell: ({ getValue }) => formatCurrency(getValue<number | null>()),
  },
  {
    accessorKey: "expected_iv",
    header: "Wt. IV",
    cell: ({ getValue }) => formatCurrency(getValue<number | null>()),
  },
  {
    accessorKey: "expected_upside_pct",
    header: "Upside",
    cell: ({ getValue }) => {
      const val = getValue<number | null>();
      const cls = val != null ? (val >= 0 ? "val-positive" : "val-negative") : "";
      return <span className={cls}>{formatPercent(val)}</span>;
    },
  },
  {
    accessorKey: "analyst_target",
    header: "Target",
    cell: ({ getValue }) => formatCurrency(getValue<number | null>()),
  },
  {
    accessorKey: "latest_action",
    header: "Rating",
    cell: ({ getValue }) => {
      const val = getValue<string | null>();
      const action = val?.toLowerCase();
      const cls = action === "buy" ? "status-pill--buy" : action === "sell" ? "status-pill--sell" : "status-pill--watch";
      return <span className={`status-pill ${cls}`}>{formatText(val)}</span>;
    },
    meta: { align: "center" },
  },
  {
    accessorKey: "latest_conviction",
    header: "Conv.",
    cell: ({ getValue }) => formatText(getValue<string | null>()),
    meta: { align: "center" },
  },
  {
    accessorKey: "latest_snapshot_date",
    header: "Snap",
    cell: ({ getValue }) => formatText(getValue<string | null>()),
  },
];

export function WatchlistTable({
  rows,
  selectedTicker,
  onSelectTicker,
}: {
  rows: WatchlistRow[];
  selectedTicker?: string | null;
  onSelectTicker?: (ticker: string) => void;
}) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "expected_upside_pct", desc: true }]);

  const data = useMemo(() => rows, [rows]);
  const table = useReactTable({
    data,
    columns,
    state: { globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    enableMultiSort: false,
    enableSortingRemoval: false,
    globalFilterFn: (row, _columnId, value) => {
      const haystack = [
        row.original.ticker,
        row.original.company_name,
        row.original.latest_action,
        row.original.latest_conviction,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(String(value).toLowerCase());
    },
  });

  return (
    <section className="panel watchlist-table-panel">
      <div className="panel-toolbar">
        <div>
          <h2>Ranked Universe</h2>
          <p>Best-ranked names first. Select a row to compare it in the focus pane.</p>
        </div>
        <input
          className="search-input"
          type="search"
          placeholder="Filter ticker, company, action"
          value={globalFilter}
          onChange={(event) => startTransition(() => setGlobalFilter(event.target.value))}
        />
      </div>
      <div className="table-shell table-shell--watchlist">
        <table className="data-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={`row-clickable${selectedTicker === row.original.ticker ? " row-selected" : ""}`}
                onClick={() => onSelectTicker?.(row.original.ticker)}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
