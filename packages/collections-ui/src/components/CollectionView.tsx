import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useApi } from "../apiContext";
import { useAsync } from "../hooks";
import type { Item } from "../types";
import { Breadcrumb, ErrorBox, formatCell, Loading, ReadOnlyBadge } from "./ui";

type SortState = { field: string; dir: "asc" | "desc" };

function compare(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return formatCell(a).localeCompare(formatCell(b), undefined, { numeric: true });
}

export function CollectionView() {
  const api = useApi();
  const name = useParams().name!;

  const { data, error, loading } = useAsync(
    () =>
      Promise.all([
        api.getCollection(name),
        api.getSchema(name),
        api.listItems(name),
      ]),
    [name],
  );

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState | null>(null);

  const columns = useMemo(() => {
    if (!data) return [];
    const [, schema, page] = data;
    const props = (schema.properties as Record<string, unknown>) ?? {};
    const cols = Object.keys(props);
    for (const item of page.items) {
      for (const key of Object.keys(item.data)) {
        if (!cols.includes(key)) cols.push(key);
      }
    }
    return cols;
  }, [data]);

  const rows = useMemo(() => {
    if (!data) return [];
    const [, , page] = data;
    const needle = query.trim().toLowerCase();
    let result: Item[] = needle
      ? page.items.filter((item) =>
          Object.values(item.data).some((v) =>
            formatCell(v).toLowerCase().includes(needle),
          ),
        )
      : page.items;
    if (sort) {
      const { field, dir } = sort;
      result = [...result].sort((x, y) => {
        const c = compare(x.data[field], y.data[field]);
        return dir === "asc" ? c : -c;
      });
    }
    return result;
  }, [data, query, sort]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const [info, schema, page] = data;

  const toggleSort = (field: string) =>
    setSort((prev) =>
      prev?.field === field
        ? { field, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { field, dir: "asc" },
    );
  const sortMark = (field: string) =>
    sort?.field === field ? (sort.dir === "asc" ? " ▲" : " ▼") : "";

  return (
    <>
      <Breadcrumb parts={[{ label: "Collections", to: "/" }, { label: info.name }]} />
      <h1>
        {(schema.title as string) || info.name}{" "}
        <ReadOnlyBadge show={!info.capabilities.supports_write} />
      </h1>

      <div className="toolbar">
        <input
          className="search"
          type="search"
          placeholder={`Search ${info.name}…`}
          aria-label="Search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {info.capabilities.supports_write && (
          <Link className="btn btn-primary" to={`/c/${encodeURIComponent(info.name)}/new`}>
            New item
          </Link>
        )}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>id</th>
              {columns.map((col) => (
                <th
                  key={col}
                  className="sortable"
                  onClick={() => toggleSort(col)}
                  title="Sort by this column"
                >
                  {col}
                  {sortMark(col)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id}>
                <td>
                  <Link
                    to={`/c/${encodeURIComponent(info.name)}/${encodeURIComponent(item.id)}`}
                  >
                    {item.id}
                  </Link>
                </td>
                {columns.map((col) => (
                  <td key={col}>{formatCell(item.data[col])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="count">
        {rows.length} of {page.total} shown
      </div>
    </>
  );
}
