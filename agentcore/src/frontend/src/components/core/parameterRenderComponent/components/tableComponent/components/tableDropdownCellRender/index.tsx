import type { CustomCellRendererProps } from "ag-grid-react";

export default function TableDropdownCellRender({
  value,
  setValue,
  colDef,
}: CustomCellRendererProps) {
  const options: string[] = colDef?.cellRendererParams?.values ?? [];

  return (
    <div className="flex h-full w-full items-center">
      <select
        className="h-full w-full cursor-pointer bg-transparent text-sm outline-none"
        value={value ?? ""}
        onChange={(e) => setValue?.(e.target.value)}
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}
