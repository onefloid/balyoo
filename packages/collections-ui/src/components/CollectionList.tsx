import { Link } from "react-router-dom";

import { useApi } from "../apiContext";
import { useAsync } from "../hooks";
import { ErrorBox, Loading, ReadOnlyBadge } from "./ui";

export function CollectionList() {
  const api = useApi();
  const { data, error, loading } = useAsync(() => api.listCollections(), []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const collections = data ?? [];

  return (
    <>
      <h1>Collections</h1>
      {collections.length === 0 ? (
        <p className="muted">No collections.</p>
      ) : (
        <div className="cards">
          {collections.map((c) => (
            <Link key={c.name} className="card" to={`/c/${encodeURIComponent(c.name)}`}>
              <div className="name">
                {c.name} <ReadOnlyBadge show={!c.capabilities.supports_write} />
              </div>
              <div className="meta">
                {c.item_count} item{c.item_count === 1 ? "" : "s"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
