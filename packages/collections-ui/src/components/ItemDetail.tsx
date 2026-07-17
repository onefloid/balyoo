import { Fragment, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useApi } from "../apiContext";
import { useAsync } from "../hooks";
import { Breadcrumb, ErrorBox, formatCell, Loading } from "./ui";

export function ItemDetail() {
  const api = useApi();
  const navigate = useNavigate();
  const { name, id } = useParams() as { name: string; id: string };

  const { data, error, loading } = useAsync(
    () => Promise.all([api.getCollection(name), api.getItem(name, id)]),
    [name, id],
  );

  const [deleteError, setDeleteError] = useState<Error | null>(null);
  const [deleting, setDeleting] = useState(false);

  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const [info, item] = data;
  const caps = info.capabilities;

  async function onDelete() {
    if (!window.confirm(`Delete ${name}/${id}? This cannot be undone.`)) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteItem(name, id);
      navigate(`/c/${encodeURIComponent(name)}`);
    } catch (err) {
      setDeleteError(err as Error);
      setDeleting(false);
    }
  }

  return (
    <>
      <Breadcrumb
        parts={[
          { label: "Collections", to: "/" },
          { label: info.name, to: `/c/${encodeURIComponent(info.name)}` },
          { label: item.id },
        ]}
      />
      <h1>{item.id}</h1>

      {(caps.supports_write || caps.supports_delete) && (
        <div className="actions">
          {caps.supports_write && (
            <Link
              className="btn"
              to={`/c/${encodeURIComponent(info.name)}/${encodeURIComponent(item.id)}/edit`}
            >
              Edit
            </Link>
          )}
          {caps.supports_delete && (
            <button
              type="button"
              className="btn btn-danger"
              onClick={onDelete}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete"}
            </button>
          )}
        </div>
      )}
      {deleteError && <p className="notice">{deleteError.message}</p>}

      <dl className="detail">
        {Object.entries(item.data).map(([key, value]) => (
          <Fragment key={key}>
            <dt>{key}</dt>
            <dd>{formatCell(value)}</dd>
          </Fragment>
        ))}
      </dl>

      <h2>Raw JSON</h2>
      <pre>{JSON.stringify(item, null, 2)}</pre>
    </>
  );
}
