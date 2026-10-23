"use strict";

const GROUPS = [
  ["Shooting", ["Close Shot", "Midrange Shot", "3pt Shot", "Free Throws"]],
  ["Inside Scoring", ["Layup", "Dunk", "Post Offense"]],
  ["Playmaking", ["Ball Handling", "Passing"]],
  ["Defense", ["Post Defense", "Block", "Steal", "Defensive Awareness"]],
  ["Rebounding", ["Offensive Rebound", "Defensive Rebound"]],
  ["Athleticism", ["Speed", "Stamina", "Durability"]],
  ["Awareness", ["Offensive Awareness"]],
];
const SHORT = {
  "Close Shot": "CLS", "Midrange Shot": "MID", "3pt Shot": "3PT", "Free Throws": "FT", "Layup": "LAY", "Dunk": "DNK",
  "Ball Handling": "HND", "Passing": "PAS", "Post Offense": "POF", "Post Defense": "PDF", "Block": "BLK", "Steal": "STL",
  "Offensive Rebound": "ORB", "Defensive Rebound": "DRB", "Speed": "SPD", "Stamina": "STA", "Durability": "DUR",
  "Defensive Awareness": "DAW", "Offensive Awareness": "OAW",
};

let DB, ATTR_IDX, BY_ID = {}, BY_TEAM = {};
const app = document.getElementById("app");
const sortState = { key: "ovr", dir: -1 };
let rosterView = "overview";

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function band(v) {
  return v >= 90 ? "band-bright" : v >= 80 ? "band-green" : v >= 70 ? "band-yellow" : v >= 50 ? "band-orange" : "band-red";
}
const badge = (v, cls = "mini") => h("span", { class: `${cls} ${band(v)}` }, v);
const age = p => {
  const [y, m, d] = p.birth, now = new Date();
  let a = now.getFullYear() - y;
  if (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d)) a--;
  return a;
};
const inches = m => { const t = Math.round(m * 39.3701); return `${Math.floor(t / 12)}'${t % 12}"`; };
const lbs = kg => Math.round(kg * 2.20462);
const initials = p => (p.first[0] || "") + (p.last[0] || "");
const attr = (p, name) => p.a[ATTR_IDX[name]];
const fmt1 = v => (v == null ? "–" : v.toFixed(1));
const pct = v => (v == null ? "–" : v.toFixed(1));

function face(p, cls = "face") {
  if (!p.img) return h("div", { class: "face-fb" }, initials(p));
  const img = h("img", { class: cls, src: `img/p/${p.id}.webp`, alt: "", loading: "lazy" });
  img.addEventListener("error", () => img.replaceWith(h("div", { class: "face-fb" }, initials(p))));
  return img;
}
function logo(t, big) {
  const fallback = () => h("div", { class: "logo-fb" + (big ? " big" : "") }, t.short.slice(0, 3).toUpperCase());
  if (!t.logo) return fallback();
  const img = h("img", { class: "logo" + (big ? " big" : ""), src: t.logo, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
  img.addEventListener("error", () => img.replaceWith(fallback()));
  return img;
}

const teamAvg = t => Math.round(t.players.reduce((s, id) => s + BY_ID[id].ovr, 0) / t.players.length);

function viewHome(query) {
  const q = (query || "").trim().toLowerCase();
  const out = [];
  if (q) {
    const ps = DB.players.filter(p => `${p.first} ${p.last}`.toLowerCase().includes(q)).sort((a, b) => b.ovr - a.ovr);
    const ts = DB.teams.filter(t => `${t.name} ${t.short}`.toLowerCase().includes(q));
    out.push(h("h1", {}, `Search: ${query}`));
    if (ts.length) out.push(h("h2", {}, "Teams"), teamGrid(ts));
    out.push(h("h2", {}, "Players"), ps.length ? playerTable(ps, true) : h("div", { class: "empty" }, "No players found"));
    return out;
  }
  out.push(h("h1", {}, "Teams"), h("div", { class: "sub" }, `${DB.teams.length} teams · ${DB.players.length} players · season ${DB.season}`));
  out.push(teamGrid([...DB.teams].sort((a, b) => a.name.localeCompare(b.name))));
  out.push(h("h2", {}, "Top 15 by Overall"), playerTable([...DB.players].sort((a, b) => b.ovr - a.ovr).slice(0, 15), true));
  return out;
}

function teamGrid(teams) {
  return h("div", { class: "teams" }, teams.map(t => h("a", { class: "team-card", href: `#/team/${t.slug}` },
    logo(t),
    h("div", {}, h("div", { class: "nm" }, t.name), h("div", { class: "st" }, `${t.players.length} players · avg OVR ${teamAvg(t)}`)))));
}

function columns(view, showTeam) {
  const stat = k => p => (p.s ? p.s[k] : null);
  const base = [
    { label: "Player", key: "last", get: p => p.last.toLowerCase(), cell: p => h("div", { class: "pl" }, face(p), `${p.first} ${p.last}`), left: true },
    showTeam ? { label: "Team", key: "team", get: p => BY_TEAM[p.team].short.toLowerCase(), cell: p => BY_TEAM[p.team].short, left: true } : null,
    { label: "Pos", key: "pos", get: p => p.pos, cell: p => p.pos + (p.pos2 ? `/${p.pos2}` : ""), n: true },
    { label: "OVR", key: "ovr", get: p => p.ovr, cell: p => badge(p.ovr, "ovr"), n: true },
  ].filter(Boolean);
  if (view === "attributes") {
    return base.concat(DB.attributes.map(a => ({ label: SHORT[a], title: a, key: a, get: p => attr(p, a), cell: p => badge(attr(p, a)), n: true })));
  }
  return base.concat([
    { label: "Age", key: "age", get: age, cell: age, n: true },
    { label: "Ht", key: "h", get: p => p.h, cell: p => inches(p.h), n: true },
    { label: "MPG", key: "mpg", get: p => (p.s ? parseInt(p.s.mpg) * 60 + parseInt(p.s.mpg.split(":")[1]) : null), cell: p => (p.s ? p.s.mpg : "–"), n: true },
    { label: "PTS", key: "pts", get: stat("pts"), cell: p => fmt1(stat("pts")(p)), n: true },
    { label: "REB", key: "reb", get: stat("reb"), cell: p => fmt1(stat("reb")(p)), n: true },
    { label: "AST", key: "ast", get: stat("ast"), cell: p => fmt1(stat("ast")(p)), n: true },
    { label: "FG%", key: "fg", get: stat("fg"), cell: p => pct(stat("fg")(p)), n: true },
    { label: "3P%", key: "fg3", get: stat("fg3"), cell: p => pct(stat("fg3")(p)), n: true },
    { label: "FT%", key: "ft", get: stat("ft"), cell: p => pct(stat("ft")(p)), n: true },
  ]);
}

function playerTable(players, showTeam, tabs) {
  const holder = h("div");
  const draw = () => {
    const cols = columns(rosterView, showTeam);
    const col = cols.find(c => c.key === sortState.key) || cols.find(c => c.key === "ovr");
    const rows = [...players].sort((a, b) => {
      const x = col.get(a), y = col.get(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * sortState.dir || b.ovr - a.ovr;
    });
    const head = h("tr", {}, cols.map(c => h("th", {
      class: (c.n ? "n " : "") + (c === col ? "sorted" : ""), title: c.title,
      onclick: () => { sortState.dir = sortState.key === c.key ? -sortState.dir : (c.left ? 1 : -1); sortState.key = c.key; draw(); },
    }, c.label + (c === col ? (sortState.dir < 0 ? " ▼" : " ▲") : ""))));
    const body = rows.map(p => h("tr", { onclick: () => { location.hash = `#/player/${p.id}`; } },
      cols.map(c => h("td", { class: c.n ? "n" : "" }, c.cell(p)))));
    const tabBar = tabs ? h("div", { class: "tabs" }, [["overview", "Overview"], ["attributes", "Attributes"]].map(([k, label]) =>
      h("div", { class: "tab" + (rosterView === k ? " on" : ""), onclick: () => { rosterView = k; draw(); } }, label))) : null;
    holder.replaceChildren(...[tabBar, h("div", { class: "scroll" }, h("table", {}, h("thead", {}, head), h("tbody", {}, body)))].filter(Boolean));
  };
  draw();
  return holder;
}

function viewTeam(slug) {
  const t = BY_TEAM[slug];
  if (!t) return [h("div", { class: "empty" }, "Team not found")];
  const ps = t.players.map(id => BY_ID[id]);
  return [
    h("div", { class: "crumbs" }, h("a", { href: "#/" }, "Teams"), " › ", t.name),
    h("div", { class: "hero", style: "align-items:center;margin-bottom:18px" }, logo(t, true),
      h("div", {}, h("h1", {}, t.name), h("div", { class: "sub" }, `${ps.length} players · average OVR ${teamAvg(t)}`))),
    playerTable(ps, false, true),
  ];
}

function fact(k, v, small) {
  return h("div", { class: "fact" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v, small ? h("small", {}, small) : null));
}

function viewPlayer(id) {
  const p = BY_ID[id];
  if (!p) return [h("div", { class: "empty" }, "Player not found")];
  const t = BY_TEAM[p.team];
  const cardFace = p.img ? h("img", { src: `img/p/${p.id}.webp`, alt: `${p.first} ${p.last}` }) : h("div", { class: "face-fb" }, initials(p));
  if (p.img) cardFace.addEventListener("error", () => cardFace.replaceWith(h("div", { class: "face-fb" }, initials(p))));
  const attrGroup = ([title, names]) => h("div", { class: "grp" }, h("h3", {}, title),
    names.map(n => h("div", { class: "row" }, badge(attr(p, n)), n)));
  const left = [GROUPS[0], GROUPS[1], GROUPS[2]].map(attrGroup);
  const right = [GROUPS[3], GROUPS[4], GROUPS[5], GROUPS[6]].map(attrGroup);
  return [
    h("div", { class: "crumbs" }, h("a", { href: "#/" }, "Teams"), " › ", h("a", { href: `#/team/${t.slug}` }, t.name), " › ", `${p.first} ${p.last}`),
    h("div", { class: "hero" },
      h("div", { class: "card" }, badge(p.ovr, "ovr lg"), cardFace),
      h("div", { class: "info" },
        h("div", { class: "title" }, p.no != null ? h("span", { class: "no" }, `#${p.no}`) : null, h("h1", {}, `${p.first} ${p.last}`)),
        h("div", { class: "teamline" }, h("a", { href: `#/team/${t.slug}` }, t.name)),
        h("div", { class: "facts" },
          fact("Position", p.pos + (p.pos2 ? ` / ${p.pos2}` : "")),
          fact("Height", inches(p.h), `${Math.round(p.h * 100)} cm`),
          fact("Weight", `${lbs(p.w)} lbs`, `${Math.round(p.w)} kg`),
          fact("Age", age(p), `born ${String(p.birth[2]).padStart(2, "0")}.${String(p.birth[1]).padStart(2, "0")}.${p.birth[0]}`),
          fact("Team", t.short)))),
    h("h2", {}, "Attributes"),
    h("div", { class: "attrs" }, h("div", {}, left), h("div", {}, right)),
    h("h2", {}, "Stats"),
    statsBlock(p),
  ];
}

function statsBlock(p) {
  const s = p.s;
  if (!s) return h("div", { class: "empty" }, "No recorded games yet");
  const cells = [["MPG", s.mpg], ["PTS", fmt1(s.pts)], ["REB", fmt1(s.reb)], ["OREB", fmt1(s.oreb)], ["DREB", fmt1(s.dreb)], ["AST", fmt1(s.ast)],
    ["STL", fmt1(s.stl)], ["BLK", fmt1(s.blk)], ["TOV", fmt1(s.tov)], ["FG%", pct(s.fg)], ["3P%", pct(s.fg3)], ["FT%", pct(s.ft)]];
  const label = y => `${y}/${String((y + 1) % 100).padStart(2, "0")}`;
  return h("div", {},
    h("div", { class: "statgrid" }, cells.map(([k, v]) => h("div", { class: "stat" }, h("div", { class: "v" }, v), h("div", { class: "k" }, k)))),
    h("div", { class: "note" }, `Per game, pooled over ${s.g} games: `,
      s.seasons.map(([y, g, w]) => `${label(y)} (${g} G, weight ${w.toFixed(2)})`).join(" · "),
      ". Older seasons and seasons under 10 games count less."));
}

function route() {
  const search = document.getElementById("search");
  const [, kind, arg] = location.hash.split("/");
  let view;
  if (kind === "team") view = viewTeam(decodeURIComponent(arg || ""));
  else if (kind === "player") view = viewPlayer(Number(arg));
  else if (kind === "search") { view = viewHome(decodeURIComponent(arg || "")); }
  else view = viewHome("");
  if (kind !== "search") search.value = "";
  app.replaceChildren(...view);
  if (kind !== "search") window.scrollTo(0, 0);
}

async function init() {
  DB = await (await fetch("data/players.json")).json();
  ATTR_IDX = Object.fromEntries(DB.attributes.map((a, i) => [a, i]));
  DB.players.forEach(p => { BY_ID[p.id] = p; });
  DB.teams.forEach(t => { BY_TEAM[t.slug] = t; });
  document.getElementById("meta").textContent = `Season ${DB.season} · data built ${DB.generated}. `;
  document.getElementById("search").addEventListener("input", e => {
    const v = e.target.value.trim();
    history.replaceState(null, "", v ? `#/search/${encodeURIComponent(v)}` : "#/");
    route();
  });
  window.addEventListener("hashchange", route);
  route();
}

init().catch(err => { app.replaceChildren(h("div", { class: "empty" }, `Failed to load data: ${err.message}`)); });
