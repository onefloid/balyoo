# collections-search-lunr (planned)

A pluggable `SearchProvider`. Search is swappable (none / Fuse.js / Lunr /
Meilisearch / Elasticsearch); the core only depends on the `SearchProvider`
interface. The filesystem provider ships a simple in-memory search so this is
optional. Not implemented in milestone 1.
