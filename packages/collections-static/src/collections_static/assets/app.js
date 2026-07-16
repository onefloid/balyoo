"use strict";

// The static API mirror lives next to this page, under ./api/. Resolving against
// document.baseURI makes the app work at a site root or a project sub-path
// (e.g. https://<user>.github.io/balyoo/).
const API_BASE = new URL("api/", document.baseURI);

const app = document.getElementById("app");

async function fetchJSON(path) {
  const res = await fetch(new URL(path, API_BASE));
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json();
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

function cell(value) {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function readOnlyBadge(capabilities) {
  return capabilities && capabilities.supports_write === false
    ? el("span", { class: "badge", title: "This deployment is read-only" }, "read-only")
    : "";
}

function render(children) {
  app.replaceChildren(...[].concat(children));
}

function renderError(err) {
  render(el("p", { class: "error" }, `Failed to load: ${err.message}`));
}

// -- routes -----------------------------------------------------------------
async function routeHome() {
  const collections = await fetchJSON("collections.json");
  const cards = collections.map((c) =>
    el("a", { class: "card", href: `#/c/${encodeURIComponent(c.name)}` }, [
      el("div", { class: "name" }, [c.name, " ", readOnlyBadge(c.capabilities)]),
      el("div", { class: "meta" }, `${c.item_count} item${c.item_count === 1 ? "" : "s"}`),
    ])
  );
  render([
    el("h1", {}, "Collections"),
    collections.length ? el("div", { class: "cards" }, cards) : el("p", {}, "No collections."),
  ]);
}

async function routeCollection(name) {
  const [info, schema, page] = await Promise.all([
    fetchJSON(`collections/${name}.json`),
    fetchJSON(`collections/${name}/schema.json`),
    fetchJSON(`collections/${name}/items.json`),
  ]);

  const columns = Object.keys(schema.properties || {});
  // Include any data keys not declared in the schema, for completeness.
  for (const item of page.items) {
    for (const key of Object.keys(item.data)) {
      if (!columns.includes(key)) columns.push(key);
    }
  }

  const search = el("input", {
    class: "search",
    type: "search",
    placeholder: `Search ${info.name}…`,
    "aria-label": "Search",
  });
  const tbody = el("tbody");
  const count = el("div", { class: "count" });

  function draw(query) {
    const needle = query.trim().toLowerCase();
    const rows = page.items.filter((item) =>
      !needle ||
      Object.values(item.data).some((v) => cell(v).toLowerCase().includes(needle))
    );
    tbody.replaceChildren(
      ...rows.map((item) =>
        el("tr", { class: "row", "data-id": item.id }, [
          el("td", {}, el("a", { href: `#/c/${encodeURIComponent(info.name)}/${encodeURIComponent(item.id)}` }, item.id)),
          ...columns.map((col) => el("td", {}, cell(item.data[col]))),
        ])
      )
    );
    count.textContent = `${rows.length} of ${page.total} shown`;
  }

  search.addEventListener("input", () => draw(search.value));
  draw("");

  render([
    breadcrumb([["Collections", "#/"], [info.name, null]]),
    el("h1", {}, [`${schema.title || info.name} `, readOnlyBadge(info.capabilities)]),
    el("div", { class: "toolbar" }, search),
    el("div", { class: "table-wrap" }, el("table", {}, [
      el("thead", {}, el("tr", {}, [el("th", {}, "id"), ...columns.map((c) => el("th", {}, c))])),
      tbody,
    ])),
    count,
  ]);
}

async function routeItem(name, id) {
  const [info, item] = await Promise.all([
    fetchJSON(`collections/${name}.json`),
    fetchJSON(`collections/${name}/items/${id}.json`),
  ]);
  const dl = el("dl", { class: "detail" });
  for (const [key, value] of Object.entries(item.data)) {
    dl.append(el("dt", {}, key), el("dd", {}, cell(value)));
  }
  render([
    breadcrumb([["Collections", "#/"], [info.name, `#/c/${encodeURIComponent(info.name)}`], [item.id, null]]),
    el("h1", {}, item.id),
    dl,
    el("h2", {}, "Raw JSON"),
    el("pre", {}, JSON.stringify(item, null, 2)),
  ]);
}

function breadcrumb(parts) {
  const nodes = [];
  parts.forEach(([label, href], i) => {
    if (i > 0) nodes.push(" / ");
    nodes.push(href ? el("a", { href }, label) : label);
  });
  return el("div", { class: "breadcrumb" }, nodes);
}

// -- router -----------------------------------------------------------------
async function route() {
  const hash = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const parts = hash.split("/").filter(Boolean); // ["c", name, id?]
  render(el("p", {}, "Loading…"));
  try {
    if (parts[0] === "c" && parts[2]) await routeItem(parts[1], parts[2]);
    else if (parts[0] === "c" && parts[1]) await routeCollection(parts[1]);
    else await routeHome();
  } catch (err) {
    renderError(err);
  }
}

window.addEventListener("hashchange", route);
route();
