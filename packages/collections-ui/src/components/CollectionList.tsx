import { Link } from "react-router-dom";

import { useApi } from "../apiContext";
import { type CollectionMeta, resolveCollectionMeta } from "../collection";
import { useAsync } from "../hooks";
import { Avatar, ErrorBox, Loading, ReadOnlyBadge } from "./ui";

export function CollectionList() {
  const api = useApi();
  const { data, error, loading } = useAsync(async () => {
    const collections = await api.listCollections();
    // Read each collection's x-collection (icon/colour) from its schema.
    const metas = await Promise.all(
      collections.map((c) =>
        api
          .getSchema(c.name)
          .then(resolveCollectionMeta)
          .catch((): CollectionMeta => ({})),
      ),
    );
    return collections.map((info, i) => ({ info, meta: metas[i] }));
  }, []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const rows = data ?? [];

  return (
    <>
      <h1>Collections</h1>
      {rows.length === 0 ? (
        <p className="muted">No collections.</p>
      ) : (
        <div className="cards">
          {rows.map(({ info, meta }) => (
            <Link
              key={info.name}
              className="card"
              to={`/c/${encodeURIComponent(info.name)}`}
            >
              <Avatar name={info.name} icon={meta.icon} color={meta.color} />
              <div className="card-text">
                <div className="name">
                  {info.name} <ReadOnlyBadge show={!info.capabilities.supports_write} />
                </div>
                <div className="meta">
                  {info.item_count} item{info.item_count === 1 ? "" : "s"}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
