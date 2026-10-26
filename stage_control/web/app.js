"use strict";
/* Interface tactile du contrôleur d'éclairage. Aucune dépendance (le boîtier n'a pas internet). */

// ---------------------------------------------------------------- utilitaires

const WARM_WHITE = [255, 214, 170];
const AMBER = [255, 140, 0];

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.style.cssText = v;
    else if (k === "value") el.value = v;
    else if (k === "checked" || k === "selected" || k === "disabled") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const clamp01 = (x) => Math.min(1, Math.max(0, x));

function hsv2rgb(hue, sat, val) {
  const c = val * sat;
  const hp = ((hue % 360) + 360) % 360 / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  const [r, g, b] = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][Math.floor(hp) % 6];
  const m = val - c;
  return [r + m, g + m, b + m];
}

function rgb2hs(r, g, b) {
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (max <= 0) return null;
  let hue = 0;
  if (d > 0) {
    if (max === r) hue = 60 * (((g - b) / d) % 6);
    else if (max === g) hue = 60 * ((b - r) / d + 2);
    else hue = 60 * ((r - g) / d + 4);
  }
  return { h: (hue + 360) % 360, s: d / max };
}

/** Couleur affichée d'un état de projecteur (approximation à l'écran). */
function stateColor(st, withIntensity = true) {
  if (!st) return "#000";
  const k = withIntensity ? st.intensity : 1;
  const ch = [0, 1, 2].map((i) => Math.min(255,
    st.rgb[i] * 255 + st.white * WARM_WHITE[i] + st.amber * AMBER[i]) * k);
  return `rgb(${ch.map(Math.round).join(",")})`;
}

function sceneSwatch(scene) {
  const sts = Object.values(scene.states);
  if (!sts.length) return "#222";
  const cols = sts.map((s) => stateColor(s, true));
  if (cols.length === 1) return cols[0];
  const step = 100 / cols.length;
  return `linear-gradient(90deg, ${cols.map((c, i) => `${c} ${i * step}% ${(i + 1) * step}%`).join(",")})`;
}

let toastTimer = null;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("boîtier injoignable");
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* corps vide */ }
  if (!res.ok) throw new Error(data.error || `erreur ${res.status}`);
  return data;
}

/** Appel d'API dont l'échec s'affiche en message ; renvoie null en cas d'échec. */
async function call(method, path, body) {
  try { return await api(method, path, body); } catch (e) { toast(e.message); return null; }
}

function modal(title, content, buttons, opts = {}) {
  const overlay = h("div", { class: "overlay", onclick: (e) => { if (e.target === overlay) close(); } });
  const close = () => overlay.remove();
  const actions = h("div", { class: "actions" });
  for (const b of buttons) {
    actions.append(h("button", {
      class: "btn " + (b.cls || ""), type: "button",
      onclick: async () => { if ((await b.run?.(close)) !== false && !b.keep) close(); },
    }, b.label));
  }
  overlay.append(h("div", { class: "modal" + (opts.wide ? " wide" : "") }, h("h3", {}, title), content, actions));
  document.body.append(overlay);
  return close;
}

// ---------------------------------------------------------------- état

const S = { fixtures: [], scenes: [], sequences: [], settings: null, status: null, current: {} };
const TAB_IDS = ["jeu", "scenes", "sequences", "projecteurs", "reglages"];
let tab = "jeu";
try { tab = localStorage.getItem("tab") || "jeu"; } catch (e) { /* stockage indisponible */ }
if (tab === "couleurs") tab = "scenes";  // ancien nom de l'onglet
if (!TAB_IDS.includes(tab)) tab = "jeu";
const hashTab = location.hash.slice(1);
if (TAB_IDS.includes(hashTab)) tab = hashTab;  // lien direct vers un onglet
let reorderMode = false;
let dragging = false;

const sceneById = (id) => S.scenes.find((s) => s.id === id);
const seqById = (id) => S.sequences.find((s) => s.id === id);

async function loadState() {
  const st = await call("GET", "/api/state");
  if (!st) return;
  Object.assign(S, st);
  if (!dragging) render();
  paintStatus();
}

// ---------------------------------------------------------------- barre du haut et onglets

const TABS = [["jeu", "Jeu"], ["scenes", "Scènes"], ["sequences", "Séquences"],
  ["projecteurs", "Projecteurs"], ["reglages", "Réglages"]];

function renderTabs() {
  const nav = document.getElementById("tabs");
  nav.replaceChildren(...TABS.map(([id, label]) => h("button", {
    type: "button", role: "tab", class: id === tab ? "on" : "",
    onclick: () => {
      tab = id;
      reorderMode = false;
      try { localStorage.setItem("tab", id); } catch (e) { /* ignoré */ }
      render();
    },
  }, label, id === "scenes" && sceneEdit ? " ●" : "")));  // ● : une scène est en cours d'édition
}

document.getElementById("blackout").addEventListener("click", () => call("POST", "/api/blackout"));

function paintStatus() {
  const st = S.status;
  if (!st) return;
  const bo = document.getElementById("blackout");
  bo.classList.toggle("on", st.blackout);
  bo.textContent = st.blackout ? "BLACKOUT ACTIF" : "BLACKOUT";
  document.querySelectorAll("[data-scene]").forEach((el) => {
    el.classList.toggle("active", el.dataset.scene === st.active);
    el.classList.toggle("flash", el.dataset.scene === st.flash);
  });
  document.querySelectorAll("[data-seq]").forEach((el) => {
    const running = el.dataset.seq === st.sequence;
    el.classList.toggle("running", running);
    const sub = el.querySelector(".sub");
    const seq = seqById(el.dataset.seq);
    if (sub && seq) sub.textContent = running ? `étape ${st.step + 1} / ${seq.steps.length}` : `${seq.steps.length} étapes${seq.loop ? ", boucle" : ""}`;
    const b = el.querySelector("[data-toggle]");
    if (b) b.textContent = running ? "■ Arrêter" : "▶ Lancer";
  });
  document.querySelectorAll("[data-bohint]").forEach((el) => { el.hidden = !st.blackout; });
  document.querySelectorAll("[data-pad]").forEach((el) => {
    const n = Number(el.dataset.pad);
    el.classList.toggle("lit", n === 7 ? st.leds.blackout : st.leds.slots[n - 1]);
  });
}

// ---------------------------------------------------------------- onglet Jeu

function pedalLabel(p) {
  const sc = p.target && sceneById(p.target);
  const sq = p.target && seqById(p.target);
  switch (p.type) {
    case "scene": return sc ? sc.name : "?";
    case "sequence": return "▶ " + (sq ? sq.name : "?");
    case "flash": return "⚡ " + (sc ? sc.name : "?");
    case "next": return "Étape suivante";
    case "prev": return "Étape précédente";
    default: return "—";
  }
}

/** Couleurs d'aperçu d'une scène, une par projecteur concerné. */
function sceneColors(scene) {
  return Object.values(scene.states).map((s) => stateColor(s, true));
}

function seqSwatch(seq) {
  const cols = seq.steps.map((st) => {
    const sc = sceneById(st.scene);
    return (sc && sceneColors(sc)[0]) || "#222";
  });
  const step = 100 / cols.length;
  return cols.length === 1 ? cols[0]
    : `linear-gradient(90deg, ${cols.map((c, i) => `${c} ${i * step}% ${(i + 1) * step}%`).join(",")})`;
}

async function moveScene(index, delta) {
  const ids = S.scenes.map((s) => s.id);
  const j = index + delta;
  if (j < 0 || j >= ids.length) return;
  [ids[index], ids[j]] = [ids[j], ids[index]];
  S.scenes = ids.map(sceneById);  // retour immédiat ; le serveur confirme par l'événement « config »
  render();
  await call("PUT", "/api/scene-order", { ids });
}

function renderJeu(view) {
  view.append(h("h2", {}, "Scènes", h("span", { class: "spacer" }),
    S.scenes.length > 1 ? h("button", { class: "btn small", type: "button",
      onclick: () => { reorderMode = !reorderMode; render(); } }, reorderMode ? "Terminé" : "↔ Réorganiser") : null));
  if (!S.scenes.length) view.append(h("p", { class: "hint" },
    "Aucune scène. Créez-en dans l'onglet « Scènes »."));
  if (reorderMode) view.append(h("p", { class: "hint" }, "Déplacez chaque scène avec les flèches : l'ordre est enregistré."));
  const grid = h("div", { class: "grid" });
  S.scenes.forEach((sc, i) => {
    const card = h("button", {
      class: "scene" + (reorderMode ? " moving" : ""), type: "button", "data-scene": sc.id,
      onclick: () => { if (!reorderMode) call("POST", `/api/scenes/${encodeURIComponent(sc.id)}/recall`); },
    }, h("span", { class: "sw", style: `background:${sceneSwatch(sc)}` }),
      h("span", { class: "name" }, sc.name),
      h("span", { class: "sub" }, sc.fade_s === null ? "fondu : défaut" : `fondu : ${sc.fade_s} s`));
    if (reorderMode) {
      const arrow = (label, delta, aria) => h("span", { class: "arrow", role: "button", "aria-label": aria,
        onclick: (e) => { e.stopPropagation(); moveScene(i, delta); } }, label);
      card.append(h("span", { class: "mover" },
        i > 0 ? arrow("◀", -1, "avancer") : h("span", {}), i < S.scenes.length - 1 ? arrow("▶", 1, "reculer") : h("span", {})));
    }
    grid.append(card);
  });
  view.append(grid);

  if (S.sequences.length) {
    view.append(h("h2", {}, "Séquences"));
    const sg = h("div", { class: "grid" });
    for (const sq of S.sequences) {
      const nav = (label, path, aria) => h("span", { class: "arrow nav", role: "button", "aria-label": aria,
        onclick: (e) => { e.stopPropagation(); call("POST", path); } }, label);
      sg.append(h("div", { class: "scene seqcard", role: "button", tabindex: "0", "data-seq": sq.id,
        onclick: () => call("POST", `/api/sequences/${encodeURIComponent(sq.id)}/toggle`) },
        h("span", { class: "sw", style: `background:${seqSwatch(sq)}` }),
        h("span", { class: "name" }, "▶ " + sq.name),
        h("span", { class: "sub" }, ""),
        h("span", { class: "seqnav" }, nav("◀", "/api/sequence/prev", "étape précédente"),
          nav("▶", "/api/sequence/next", "étape suivante"))));
    }
    view.append(sg);
  }

  view.append(h("h2", {}, "Pédalier"),
    h("p", { class: "hint" }, "Reproduit le pédalier : maintenez une case pour un flash. Les LED suivent l'état réel."));
  const pads = h("div", { class: "pads" });
  S.settings.pedals.forEach((p, i) => pads.append(pad(i + 1, pedalLabel(p))));
  pads.append(pad(7, "Blackout", "bo"));
  view.append(pads);
}

function pad(n, label, extra) {
  const el = h("div", { class: "pad " + (extra || ""), "data-pad": n, oncontextmenu: (e) => e.preventDefault() },
    h("span", { class: "led" }), h("span", {}, label), h("span", { class: "hint" }, "pédale " + n));
  let isDown = false;
  const send = (down) => call("POST", `/api/pedal/${n}`, { down });
  el.addEventListener("pointerdown", (e) => {
    if (isDown) return;
    isDown = true;
    el.setPointerCapture(e.pointerId);
    el.classList.add("down");
    send(true);
  });
  const up = () => {
    if (!isDown) return;
    isDown = false;
    el.classList.remove("down");
    send(false);
  };
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
  return el;
}

// ---------------------------------------------------------------- onglet Scènes

const selection = new Set();
let colorHS = null;  // dernière teinte / saturation choisies sur la roue (null : aucune, pas de repère)
let sceneEdit = null;  // scène en cours d'édition : { id, name, fade, included:Set, snapshot, isNew }
const PALETTE = [
  ["Rouge", [1, 0, 0]], ["Orange", [1, 0.35, 0]], ["Jaune", [1, 0.85, 0]], ["Vert", [0, 1, 0]],
  ["Cyan", [0, 1, 1]], ["Bleu", [0, 0, 1]], ["Violet", [0.5, 0, 1]], ["Magenta", [1, 0, 1]],
  ["Rose", [1, 0.2, 0.5]], ["Blanc", [1, 1, 1]],
];

let pending = null;
let pendingTimer = null;

/** Envoie les réglages au moteur, regroupés toutes les ~70 ms pour ne pas saturer le Pi. */
function pushFixtures(fields) {
  pending = Object.assign(pending || {}, fields);
  for (const id of selection) {  // retour visuel immédiat
    const cur = S.current[id];
    if (cur) Object.assign(cur, fields);
    if (sceneEdit) sceneEdit.included.add(id);  // un projecteur réglé fait partie de la scène
  }
  refreshChips();
  if (!pendingTimer) pendingTimer = setTimeout(flushFixtures, 70);
}

async function flushFixtures() {
  clearTimeout(pendingTimer);
  pendingTimer = null;
  const fields = pending;
  pending = null;
  if (!fields || !selection.size) return;
  const out = await call("POST", "/api/fixtures/state", { ids: [...selection], fields });
  if (out) Object.assign(S.current, out);
}

function firstSelected() {
  return S.fixtures.find((f) => selection.has(f.id));
}

function hasRole(role) {
  return S.fixtures.some((f) => selection.has(f.id) && f.roles.includes(role));
}

function refreshChips() {
  document.querySelectorAll("[data-chip]").forEach((el) => {
    const id = el.dataset.chip;
    el.classList.toggle("on", selection.has(id));
    const inc = sceneEdit ? sceneEdit.included.has(id) : true;
    el.classList.toggle("out", !inc);
    const t = el.querySelector(".chip-inc");
    if (t) { t.textContent = inc ? "✓" : "○"; t.setAttribute("aria-pressed", inc ? "true" : "false"); }
    el.querySelector(".sw").style.background = stateColor(S.current[id]);
  });
}

function slider(label, key, getter, onInput) {
  const out = h("output", {}, "");
  const input = h("input", { type: "range", min: "0", max: "100", step: "1", "aria-label": label });
  const set = (v) => { input.value = Math.round(v * 100); out.textContent = input.value + " %"; };
  set(getter());
  input.addEventListener("pointerdown", () => { dragging = true; });
  const end = () => { dragging = false; };
  input.addEventListener("pointerup", end);
  input.addEventListener("pointercancel", end);
  input.addEventListener("input", () => { out.textContent = input.value + " %"; onInput(input.value / 100); });
  const el = h("div", { class: "sl", "data-slider": key }, h("label", {}, h("span", {}, label), out), input);
  el.sync = () => set(getter());
  return el;
}

function renderScenes(view) {
  if (sceneEdit) return renderSceneEditor(view);
  view.append(h("h2", {}, "Scènes", h("span", { class: "spacer" }),
    h("button", { class: "btn small primary", type: "button", disabled: !S.fixtures.length,
      onclick: newSceneDialog }, "+ Nouvelle scène")));
  if (!S.fixtures.length) view.append(h("p", { class: "hint" }, "Ajoutez d'abord des projecteurs (onglet « Projecteurs »)."));
  else if (!S.scenes.length) view.append(h("p", { class: "hint" }, "Aucune scène pour l'instant."));
  else view.append(h("p", { class: "hint" }, "Touchez une scène pour la modifier. Pour la jouer, utilisez l'onglet « Jeu »."));
  const grid = h("div", { class: "grid" });
  for (const sc of S.scenes) {
    const n = Object.keys(sc.states).filter((id) => S.fixtures.some((f) => f.id === id)).length;
    grid.append(h("button", { class: "scene", type: "button", "data-edit": sc.id, onclick: () => startEdit(sc) },
      h("span", { class: "sw", style: `background:${sceneSwatch(sc)}` }),
      h("span", { class: "name" }, sc.name),
      h("span", { class: "sub" }, `${n} / ${S.fixtures.length} projecteurs`)));
  }
  view.append(grid);
}

function newSceneDialog() {
  const name = h("input", { type: "text", placeholder: "Nom de la scène", maxlength: "40" });
  const from = h("select", {}, h("option", { value: "current" }, "L'éclairage actuel"),
    h("option", { value: "off" }, "Tout éteint"),
    ...S.scenes.map((s) => h("option", { value: "scene:" + s.id }, "Copie de : " + s.name)));
  const body = h("div", {},
    h("label", { class: "field" }, h("span", {}, "Nom"), name),
    h("label", { class: "field" }, h("span", {}, "Point de départ"), from));
  modal("Nouvelle scène", body, [
    { label: "Annuler" },
    { label: "Créer", cls: "primary", run: async () => {
      const nm = name.value.trim();
      if (!nm) { toast("Donnez un nom à la scène"); return false; }
      await startEdit(null, { name: nm, from: from.value });
    } },
  ]);
}

async function startEdit(scene, fresh) {
  await loadState();  // S.current exact : c'est l'état qu'on rétablira à l'annulation
  const snapshot = JSON.parse(JSON.stringify(S.current));
  let states = {};
  let included;
  if (scene) {
    states = scene.states;
    included = new Set(Object.keys(scene.states).filter((id) => S.fixtures.some((f) => f.id === id)));
  } else if (fresh.from === "off") {
    S.fixtures.forEach((f) => { states[f.id] = { rgb: [0, 0, 0], white: 0, amber: 0, intensity: 0, strobe: 0 }; });
    included = new Set(S.fixtures.map((f) => f.id));
  } else if (fresh.from.startsWith("scene:")) {
    states = sceneById(fresh.from.slice(6)).states;
    included = new Set(Object.keys(states).filter((id) => S.fixtures.some((f) => f.id === id)));
  } else {
    included = new Set(S.fixtures.map((f) => f.id));  // l'éclairage actuel, tel quel
  }
  sceneEdit = { id: scene ? scene.id : null, name: scene ? scene.name : fresh.name,
    fade: scene && scene.fade_s !== null ? scene.fade_s : "", included, snapshot, isNew: !scene };
  colorHS = null;  // pas de repère sur la roue tant qu'une couleur n'a pas été choisie
  if (Object.keys(states).length) {  // aperçu immédiat sur les projecteurs
    const out = await call("POST", "/api/states", { states });
    if (out) Object.assign(S.current, out);
  }
  selection.clear();
  (included.size ? included : S.fixtures.map((f) => f.id)).forEach((id) => selection.add(id));
  tab = "scenes";
  render();
}

async function finishEdit(savedId) {
  if (pendingTimer) await flushFixtures();
  const edit = sceneEdit;
  sceneEdit = null;
  // La scène enregistrée est la scène jouée : on la rappelle pour voir son nouvel aspect.
  // Sinon on remet les projecteurs comme ils étaient avant l'édition.
  if (savedId && S.status && S.status.active === savedId) await call("POST", `/api/scenes/${encodeURIComponent(savedId)}/recall`);
  else await call("POST", "/api/states", { states: edit.snapshot });
  await loadState();
}

function renderSceneEditor(view) {
  const e = sceneEdit;
  view.append(h("div", { class: "banner" }, h("strong", {}, "Édition en direct : "),
    "les changements s'affichent sur scène jusqu'à « Enregistrer » ou « Annuler »."),
    h("div", { class: "banner warn", "data-bohint": "" }, "Blackout actif : la scène est invisible sur scène. ",
      h("button", { class: "btn small", type: "button", onclick: () => call("POST", "/api/blackout", { on: false }) },
        "Lever le blackout")));

  const name = h("input", { type: "text", value: e.name, maxlength: "40", "aria-label": "nom",
    oninput: (ev) => { e.name = ev.target.value; } });
  const fade = h("input", { type: "number", min: "0", step: "0.1", value: e.fade, placeholder: "défaut", "aria-label": "fondu",
    oninput: (ev) => { e.fade = ev.target.value === "" ? "" : Number(ev.target.value); } });
  view.append(h("h2", {}, e.isNew ? "Nouvelle scène" : "Modifier la scène"),
    h("div", { class: "row editor-head" },
      h("label", { class: "field grow" }, h("span", {}, "Nom"), name),
      h("label", { class: "field" }, h("span", {}, "Fondu (s, vide = défaut)"), fade)));

  view.append(h("h2", {}, "Projecteurs", h("span", { class: "spacer" }),
    h("button", { class: "btn small", type: "button", onclick: () => { S.fixtures.forEach((f) => selection.add(f.id)); render(); } }, "Tous"),
    h("button", { class: "btn small", type: "button", onclick: () => { selection.clear(); render(); } }, "Aucun")));
  const chips = h("div", { class: "chips" });
  for (const f of S.fixtures) {
    chips.append(h("div", { class: "chip", "data-chip": f.id },
      h("button", { class: "chip-sel", type: "button",
        onclick: () => { selection.has(f.id) ? selection.delete(f.id) : selection.add(f.id); render(); } },
      h("span", { class: "sw" }), h("span", {}, f.name)),
      h("button", { class: "chip-inc", type: "button", title: "Inclus dans la scène", "aria-label": "inclus dans la scène",
        onclick: () => { e.included.has(f.id) ? e.included.delete(f.id) : e.included.add(f.id); refreshChips(); } }, "✓")));
  }
  view.append(chips, h("p", { class: "hint" },
    "Touchez un projecteur pour le régler ; ✓ = inclus dans la scène. Un projecteur non inclus reste tel quel quand on joue la scène."));

  view.append(h("h2", {}, "Couleur"));
  const cur = () => (firstSelected() ? S.current[firstSelected().id] : null);
  // La teinte et la saturation choisies sont mémorisées à part : à 0 %, les couleurs sont
  // noires et la teinte ne se retrouverait plus dans les valeurs RVB.
  const known = cur() && rgb2hs(...cur().rgb);
  if (known) colorHS = known;
  const colorLevel = () => (cur() ? Math.max(...cur().rgb) : 0);
  const lightIfDark = (fields) => {  // une couleur choisie doit se voir
    const c = cur();
    if (c && c.intensity === 0) fields.intensity = 1;
    return fields;
  };
  const wheel = makeWheel(() => colorHS, (hue, sat) => {
    colorHS = { h: hue, s: sat };
    const level = colorLevel() > 0 ? colorLevel() : 1;  // roue touchée avec « Couleurs » à 0 : on remet 100 %
    pushFixtures(lightIfDark({ rgb: hsv2rgb(hue, sat, level) }));
    syncSliders();
  });
  const sliders = h("div", { class: "sliders" });
  const mk = (label, key, role) => {
    if (role && !hasRole(role)) return;
    sliders.append(slider(label, key, () => (cur() ? cur()[key] : 0), (v) => pushFixtures({ [key]: v })));
  };
  mk("Luminosité du projecteur", "intensity");
  sliders.append(slider("Couleurs", "color", colorLevel,
    (v) => { const hs = colorHS || { h: 0, s: 1 };  // aucune teinte choisie : rouge
      pushFixtures(lightIfDark({ rgb: hsv2rgb(hs.h, hs.s, v) })); }));
  mk("Blanc chaud", "white", "white");
  mk("Ambre", "amber", "amber");
  mk("Stroboscope", "strobe", "strobe");
  if (!selection.size) sliders.append(h("p", { class: "hint" }, "Sélectionnez au moins un projecteur."));
  const syncSliders = () => sliders.querySelectorAll("[data-slider]").forEach((s) => s.sync());
  view.append(h("div", { class: "picker" }, wheel, sliders),
    h("p", { class: "hint" }, "« Couleurs » et « Blanc chaud » se règlent séparément : mettez les couleurs à 0 % pour n'avoir que le blanc chaud."));

  view.append(h("h2", {}, "Couleurs rapides"));
  const pal = h("div", { class: "palette" });
  for (const [label, rgb] of PALETTE) {
    pal.append(h("button", { class: "swatch", type: "button", title: label, "aria-label": label,
      style: `background:rgb(${rgb.map((x) => Math.round(x * 255)).join(",")})`,
      onclick: () => preset({ rgb, white: 0, amber: 0 }, syncSliders) }));
  }
  pal.append(h("button", { class: "swatch wide", type: "button", style: "background:rgb(255,214,170)",
    onclick: () => preset({ rgb: [0, 0, 0], white: 1 }, syncSliders) }, "Blanc chaud"));
  view.append(pal);

  const actions = h("div", { class: "row editor-actions" },
    h("button", { class: "btn primary", type: "button", onclick: saveEdit }, "Enregistrer"),
    h("button", { class: "btn", type: "button", onclick: () => finishEdit(null) }, "Annuler"));
  if (!e.isNew) actions.append(h("span", { class: "spacer" }),
    h("button", { class: "btn danger", type: "button", onclick: deleteEdit }, "Supprimer la scène"));
  view.append(h("h2", {}, ""), actions);
  refreshChips();
}

async function saveEdit() {
  const e = sceneEdit;
  if (pendingTimer) await flushFixtures();
  const name = e.name.trim();
  if (!name) { toast("Donnez un nom à la scène"); return; }
  const ids = S.fixtures.map((f) => f.id).filter((id) => e.included.has(id));
  if (!ids.length) { toast("Incluez au moins un projecteur dans la scène (✓)"); return; }
  const states = {};
  ids.forEach((id) => { states[id] = S.current[id]; });
  const payload = { name, fade_s: e.fade === "" ? null : e.fade, states };
  const res = e.isNew ? await call("POST", "/api/scenes", payload)
                      : await call("PUT", `/api/scenes/${encodeURIComponent(e.id)}`, payload);
  if (!res) return;
  toast(`Scène « ${res.name} » enregistrée`);
  await finishEdit(res.id);
}

async function deleteEdit() {
  const e = sceneEdit;
  if (!confirm(`Supprimer la scène « ${e.name} » ?`)) return;
  if (!(await call("DELETE", `/api/scenes/${encodeURIComponent(e.id)}`))) return;
  await finishEdit(null);
}

function preset(fields, sync) {
  const c = firstSelected() && S.current[firstSelected().id];
  const f = Object.assign({}, fields);
  if (c && c.intensity === 0) f.intensity = 1;
  if (!hasRole("white")) delete f.white;
  if (!hasRole("amber")) delete f.amber;
  pushFixtures(f);
  const hs = rgb2hs(...fields.rgb);
  if (hs) colorHS = hs;  // « Blanc chaud » (rgb à 0) garde la dernière teinte choisie
  sync();
  const wheel = document.getElementById("wheel");
  if (wheel) wheel.draw?.();
}

function makeWheel(getHS, onPick) {
  const size = Math.min(300, Math.max(220, window.innerWidth - 40));
  const canvas = h("canvas", { id: "wheel", width: size, height: size, style: `width:${size}px;height:${size}px` });
  const ctx = canvas.getContext("2d");
  const radius = size / 2;

  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x - radius + 0.5, dy = y - radius + 0.5, d = Math.hypot(dx, dy);
      const i = (y * size + x) * 4;
      if (d > radius) { img.data[i + 3] = 0; continue; }
      const hue = (Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360;
      const [r, g, b] = hsv2rgb(hue, Math.min(1, d / radius), 1);
      img.data.set([r * 255, g * 255, b * 255, 255], i);
    }
  }
  const base = document.createElement("canvas");
  base.width = base.height = size;
  base.getContext("2d").putImageData(img, 0, 0);

  canvas.draw = () => {
    ctx.clearRect(0, 0, size, size);
    ctx.drawImage(base, 0, 0);
    const hs = getHS();
    if (hs) {
      const a = hs.h * Math.PI / 180, d = hs.s * radius;
      const x = radius + Math.cos(a) * d, y = radius + Math.sin(a) * d;
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#fff";
      ctx.beginPath(); ctx.arc(x, y, 12, 0, 7); ctx.stroke();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "#000";
      ctx.beginPath(); ctx.arc(x, y, 14, 0, 7); ctx.stroke();
    }
  };
  const pick = (e) => {
    const r = canvas.getBoundingClientRect();
    const dx = (e.clientX - r.left) * (size / r.width) - radius;
    const dy = (e.clientY - r.top) * (size / r.height) - radius;
    const sat = Math.min(1, Math.hypot(dx, dy) / radius);
    const hue = (Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360;
    onPick(hue, sat);
    canvas.draw();
  };
  canvas.addEventListener("pointerdown", (e) => { dragging = true; canvas.setPointerCapture(e.pointerId); pick(e); });
  canvas.addEventListener("pointermove", (e) => { if (dragging && canvas.hasPointerCapture(e.pointerId)) pick(e); });
  const end = () => { dragging = false; };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  canvas.draw();
  return canvas;
}

// ---------------------------------------------------------------- onglet Projecteurs

const ROLE_LABEL = {
  intensity: "Dimmer général", red: "Rouge", green: "Vert", blue: "Bleu", white: "Blanc chaud", amber: "Ambre",
  uv: "UV", strobe: "Stroboscope", macro: "Programmes automatiques", speed: "Vitesse / musique",
  other: "Autre", pan: "Pan", tilt: "Tilt",
};
const PILOTED_ROLES = ["intensity", "red", "green", "blue", "white", "amber", "strobe"];
const BAR_COLORS = ["#ffb02e", "#4aa8ff", "#5ad08a", "#d66bff", "#ff6b6b", "#43d3d3"];

function channelNote(c) {
  if (c.role === "strobe") return `piloté : 0 = aucun, de ${c.min} à ${c.max} = vitesse croissante`;
  if (PILOTED_ROLES.includes(c.role)) return "piloté (0 à 255)";
  return `non piloté, fixé à ${c.default}`;
}

function channelTable(channels, first) {
  return h("table", { class: "chan" },
    h("tr", {}, h("th", {}, first ? "DMX" : "n°"), h("th", {}, "Fonction"), h("th", {}, "Pilotage")),
    ...channels.map((c, i) => h("tr", {}, h("td", {}, first ? first + i : i + 1),
      h("td", {}, ROLE_LABEL[c.role] || c.role), h("td", {}, channelNote(c)))));
}

function renderProjecteurs(view) {
  view.append(h("h2", {}, "Plan de feu", h("span", { class: "spacer" }),
    h("button", { class: "btn small primary", type: "button", disabled: !Object.keys(S.profiles).length,
      onclick: () => editFixture(null) }, "+ Ajouter")));
  view.append(h("p", { class: "hint" }, `Canaux DMX utilisés : ${S.dmx.channels} / ${S.dmx.size}`));
  const bar = h("div", { class: "dmxbar", "aria-hidden": "true" });
  S.fixtures.forEach((f, i) => bar.append(h("span", {
    title: `${f.name} : canaux ${f.address} à ${f.end}`,
    style: `left:${(f.address - 1) / S.dmx.size * 100}%;width:${f.channels / S.dmx.size * 100}%;background:${BAR_COLORS[i % BAR_COLORS.length]}` })));
  view.append(bar);
  if (!S.fixtures.length) view.append(h("p", { class: "hint" }, "Aucun projecteur. Ajoutez-en un pour commencer."));
  for (const f of S.fixtures) {
    view.append(h("div", { class: "card fx" },
      h("div", { class: "fx-main" },
        h("strong", {}, f.name),
        h("div", { class: "sub" }, `${f.profile} · mode ${f.mode} · canaux ${f.address} à ${f.end} (${f.channels})`),
        h("div", { class: "hint" }, `À régler sur le projecteur : mode ${f.mode}, adresse ${f.address}`)),
      h("button", { class: "btn small", type: "button", onclick: () => editFixture(f) }, "Modifier")));
  }

  const fileInput = h("input", { type: "file", accept: ".json,application/json", hidden: true,
    onchange: async (e) => {
      const file = e.target.files[0];
      e.target.value = "";
      if (file) await importProfileFile(file);
    } });
  view.append(h("h2", {}, "Modèles de projecteurs", h("span", { class: "spacer" }),
    h("a", { class: "btn small", href: "/api/profiles/download-all", download: "modeles-projecteurs.zip" }, "↓ Tout (.zip)"),
    h("button", { class: "btn small", type: "button", onclick: () => fileInput.click() }, "↑ Importer un fichier"),
    h("button", { class: "btn small", type: "button", onclick: () => editProfile(null, PROFILE_TEMPLATE) }, "+ Nouveau"),
    fileInput));
  for (const [key, p] of Object.entries(S.profiles)) {
    const det = h("details", { class: "card", open: Object.keys(S.profiles).length === 1 },
      h("summary", {}, h("strong", {}, p.name), p.manufacturer ? ` · ${p.manufacturer}` : "",
        h("span", { class: "tag" + (p.origin === "custom" ? " custom" : "") },
          p.origin === "custom" ? "personnalisé" : "fourni")));
    for (const [mode, m] of Object.entries(p.modes)) {
      det.append(h("h3", { class: "mode" }, `Mode ${mode} — ${m.size} canaux`), channelTable(m.channels));
    }
    det.append(h("div", { class: "row model-actions" },
      h("a", { class: "btn small", href: `/api/profiles/${encodeURIComponent(key)}/download`,
        download: key + ".json" }, "↓ Télécharger"),
      h("button", { class: "btn small", type: "button", onclick: () => editProfile(key) }, "✎ Modifier le texte"),
      p.origin === "custom" ? h("button", { class: "btn small danger", type: "button", onclick: () => deleteProfile(key, p) },
        p.has_bundled ? "↺ Revenir à la version fournie" : "Supprimer le modèle") : null));
    view.append(det);
  }
  view.append(h("p", { class: "hint" },
    "Un modèle est un fichier JSON. On peut le télécharger, le corriger ailleurs puis le réimporter, ou le modifier ici : " +
    "il est toujours contrôlé avant d'être enregistré (un modèle modifié remplace celui fourni, sans toucher à l'original). " +
    "Les canaux « non pilotés » gardent la valeur indiquée."));
}

async function deleteProfile(key, p) {
  const msg = p.has_bundled
    ? `Abandonner vos modifications du modèle « ${p.name} » et revenir à la version fournie ?`
    : `Supprimer le modèle « ${p.name} » ? (aucun projecteur ne doit l'utiliser)`;
  if (!confirm(msg)) return;
  const res = await call("DELETE", `/api/profiles/${encodeURIComponent(key)}`);
  if (res) toast(res.reverted ? "Version fournie rétablie" : "Modèle supprimé");
}

const PROFILE_TEMPLATE = JSON.stringify({
  name: "Nouveau projecteur", manufacturer: "",
  modes: { "3ch": { channels: [{ role: "red" }, { role: "green" }, { role: "blue" }] } },
}, null, 2);
const ROLE_HELP = "Rôles : intensity, red, green, blue, white, amber, uv, strobe, macro, speed, other, pan, tilt. " +
  "Chaque canal : role, default (0-255), et pour un stroboscope min / max (plage active).";

function profileKeyFromFilename(name) {
  return name.replace(/\.[^.]*$/, "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "modele";
}

async function importProfileFile(file) {
  if (file.size > 60000) { toast("Fichier trop volumineux pour un modèle"); return; }
  const text = await file.text();
  let shown = text;
  try { shown = JSON.stringify(JSON.parse(text), null, 2); } catch (e) { /* le contrôle expliquera */ }
  editProfile(null, shown, profileKeyFromFilename(file.name), true);
}

async function editProfile(key, initialText, suggestedKey, autoCheck) {
  let text = initialText;
  if (key) {
    const raw = await call("GET", `/api/profiles/${encodeURIComponent(key)}/raw`);
    if (!raw) return;
    try { text = JSON.stringify(JSON.parse(raw.text), null, 2); } catch (e) { text = raw.text; }
  }
  const keyInput = h("input", { type: "text", value: key || suggestedKey || "nouveau-modele", disabled: !!key,
    maxlength: "60", "aria-label": "identifiant" });
  const area = h("textarea", { class: "code", rows: "16", spellcheck: "false", "aria-label": "texte du modèle" });
  area.value = text;
  const report = h("div", { class: "report" });
  let checkedText = null;  // texte (et identifiant) du dernier contrôle réussi

  const fileInput = h("input", { type: "file", accept: ".json,application/json", hidden: true,
    onchange: async (e) => {
      const f = e.target.files[0];
      e.target.value = "";
      if (!f) return;
      const t = await f.text();
      try { area.value = JSON.stringify(JSON.parse(t), null, 2); } catch (err) { area.value = t; }
      if (!key) keyInput.value = profileKeyFromFilename(f.name);
      checkedText = null;
      runCheck();
    } });

  const runCheck = async () => {
    checkedText = null;
    report.replaceChildren();
    let data;
    try { data = JSON.parse(area.value); } catch (e) {
      report.append(h("p", { class: "err" }, "Texte JSON invalide : " + e.message));
      return null;
    }
    const rep = await call("POST", `/api/profiles/${encodeURIComponent(keyInput.value.trim())}/check`, { profile: data });
    if (!rep) return null;
    const list = (cls, items) => items.length ? h("ul", { class: cls }, ...items.map((x) => h("li", {}, x))) : null;
    report.append(...[
      h("p", { class: rep.ok ? "okmsg" : "err" }, rep.ok
        ? (rep.exists ? "✓ Contrôle réussi : mise à jour du modèle existant." : "✓ Contrôle réussi : nouveau modèle.")
        : "✗ Le modèle n'est pas intégrable :"),
      list("err", rep.errors), list("warn", rep.warnings),
      rep.changes.length ? h("div", {}, h("strong", {}, "Changements"), list("", rep.changes)) : null,
      rep.impacted.length ? h("p", { class: "hint" }, "Projecteurs concernés : " + rep.impacted.join(", ") + ".") : null,
    ].filter(Boolean));  // Node.append(null) écrirait « null »
    if (rep.profile) {
      for (const [mode, m] of Object.entries(rep.profile.modes)) {
        report.append(h("details", {}, h("summary", {}, `Mode ${mode} — ${m.size} canaux`), channelTable(m.channels)));
      }
    }
    if (rep.ok) checkedText = keyInput.value.trim() + "\n" + area.value;
    return rep;
  };
  area.addEventListener("input", () => { checkedText = null; });
  keyInput.addEventListener("input", () => { checkedText = null; });

  const body = h("div", {},
    h("label", { class: "field" }, h("span", {}, key ? "Identifiant du modèle (fichier)" : "Identifiant du modèle (nom du fichier)"), keyInput),
    h("label", { class: "field" }, h("span", {}, "Texte du modèle (JSON)"), area),
    h("p", { class: "hint" }, ROLE_HELP),
    h("div", { class: "row" }, h("button", { class: "btn small", type: "button", onclick: () => fileInput.click() },
      "↑ Charger un fichier…"), fileInput),
    report);
  modal(key ? "Modifier le modèle" : "Ajouter un modèle", body, [
    { label: "Fermer" },
    { label: "Contrôler", keep: true, run: async () => { await runCheck(); return false; } },
    { label: "Enregistrer", cls: "primary", run: async () => {
      if (checkedText !== keyInput.value.trim() + "\n" + area.value) {  // contrôle obligatoire, et visible, avant d'enregistrer
        const rep = await runCheck();
        if (rep && rep.ok) toast("Contrôle réussi : vérifiez le résultat puis enregistrez");
        return false;
      }
      const res = await call("PUT", `/api/profiles/${encodeURIComponent(keyInput.value.trim())}`, { profile: JSON.parse(area.value) });
      if (!res) return false;
      toast("Modèle enregistré");
    } },
  ], { wide: true });
  if (autoCheck) runCheck();
}

function editFixture(f) {
  const keys = Object.keys(S.profiles);
  const last = S.fixtures[S.fixtures.length - 1];
  const name = h("input", { type: "text", value: f ? f.name : "", maxlength: "40", placeholder: "Ex. PAR gauche" });
  const model = h("select", {}, ...keys.map((k) => h("option", { value: k,
    selected: k === (f ? f.profile_key : (last ? last.profile_key : keys[0])) }, S.profiles[k].name)));
  const mode = h("select", {});
  const address = h("input", { type: "number", min: "1", max: String(S.dmx.size), step: "1", value: f ? f.address : "" });
  const preview = h("div", {});
  const hint = h("p", { class: "hint" });

  const fillModes = (preferred) => {
    const modes = S.profiles[model.value].modes;
    mode.replaceChildren(...Object.entries(modes).map(([k, m]) => h("option", { value: k,
      selected: k === preferred }, `${k} (${m.size} canaux)`)));
  };
  const refresh = (suggest) => {
    const m = S.profiles[model.value].modes[mode.value];
    const free = m.next_address;
    if (suggest && free) address.value = free;
    const start = Number(address.value) || free || 1;
    preview.replaceChildren(channelTable(m.channels, start));
    hint.textContent = free
      ? `Première adresse libre pour ce mode : ${free}.`
      : "Plus de place libre pour ce mode dans l'univers DMX.";
  };
  fillModes(f ? f.mode : (last && last.profile_key === model.value ? last.mode : null));
  model.addEventListener("change", () => { fillModes(null); refresh(!f); });
  mode.addEventListener("change", () => refresh(!f));
  address.addEventListener("input", () => refresh(false));
  refresh(!f);

  const body = h("div", {},
    h("label", { class: "field" }, h("span", {}, "Nom"), name),
    h("label", { class: "field" }, h("span", {}, "Modèle"), model),
    h("label", { class: "field" }, h("span", {}, "Mode DMX"), mode),
    h("label", { class: "field" }, h("span", {}, "Adresse DMX de départ"), address),
    hint, preview);

  const buttons = [];
  if (f) buttons.push({ label: "Retirer", cls: "danger", run: async () => {
    if (!confirm(`Retirer « ${f.name} » du plan de feu ? Les scènes gardent ses réglages, ignorés tant qu'il est absent.`)) return false;
    if (!(await call("DELETE", `/api/fixtures/${encodeURIComponent(f.id)}`))) return false;
  } });
  buttons.push({ label: "Annuler" }, { label: "Enregistrer", cls: "primary", run: async () => {
    const payload = { name: name.value.trim(), profile: model.value, mode: mode.value };
    if (address.value !== "") payload.address = Number(address.value);
    const res = f ? await call("PUT", `/api/fixtures/${encodeURIComponent(f.id)}`, payload)
                  : await call("POST", "/api/fixtures", payload);
    if (!res) return false;
    toast(`À régler sur le projecteur : mode ${res.mode}, adresse ${res.address}`);
  } });
  modal(f ? "Modifier le projecteur" : "Ajouter un projecteur", body, buttons, { wide: true });
}

// ---------------------------------------------------------------- onglet Séquences

function renderSequences(view) {
  view.append(h("h2", {}, "Séquences", h("span", { class: "spacer" }),
    h("button", { class: "btn small primary", type: "button", disabled: !S.scenes.length,
      onclick: () => editSequence(null) }, "+ Nouvelle")));
  if (!S.scenes.length) view.append(h("p", { class: "hint" }, "Créez d'abord des scènes."));
  if (S.scenes.length && !S.sequences.length) view.append(h("p", { class: "hint" },
    "Une séquence enchaîne des scènes, avec un délai ou un passage manuel à la pédale « étape suivante »."));
  for (const sq of S.sequences) {
    view.append(h("div", { class: "seq" },
      h("div", { class: "name" }, sq.name, h("div", { class: "sub" },
        `${sq.steps.length} étapes${sq.loop ? ", boucle" : ", s'arrête à la fin"}`)),
      h("button", { class: "btn small", type: "button", onclick: () => editSequence(sq) }, "Modifier")));
  }
}

function editSequence(sq) {
  const model = sq ? JSON.parse(JSON.stringify(sq)) : { name: "", loop: false, steps: [{ scene: S.scenes[0].id, fade_s: null, hold_s: 2 }] };
  const name = h("input", { type: "text", value: model.name, placeholder: "Nom de la séquence" });
  const loop = h("input", { type: "checkbox", checked: model.loop });
  const list = h("div", {});

  const drawSteps = () => {
    list.replaceChildren(...model.steps.map((st, i) => {
      const scene = h("select", { onchange: (e) => { st.scene = e.target.value; } },
        ...S.scenes.map((s) => h("option", { value: s.id, selected: s.id === st.scene }, s.name)));
      const fade = h("input", { type: "number", min: "0", step: "0.1", placeholder: "fondu (s)", "aria-label": "fondu",
        value: st.fade_s === null ? "" : st.fade_s,
        oninput: (e) => { st.fade_s = e.target.value === "" ? null : Number(e.target.value); } });
      const holdNum = h("input", { type: "number", min: "0", step: "0.1", "aria-label": "délai",
        value: st.hold_s === null ? 2 : st.hold_s, disabled: st.hold_s === null,
        oninput: (e) => { st.hold_s = Number(e.target.value); } });
      const mode = h("select", { "aria-label": "passage", onchange: (e) => {
        st.hold_s = e.target.value === "manual" ? null : Number(holdNum.value) || 2;
        drawSteps();
      } }, h("option", { value: "delay", selected: st.hold_s !== null }, "après un délai"),
        h("option", { value: "manual", selected: st.hold_s === null }, "à la pédale"));
      const move = (d) => { const j = i + d; if (j < 0 || j >= model.steps.length) return;
        [model.steps[i], model.steps[j]] = [model.steps[j], model.steps[i]]; drawSteps(); };
      // Ligne 1 : numéro et scène sur toute la largeur (le nom doit rester lisible) ; ligne 2 : réglages.
      return h("div", { class: "step" },
        h("div", { class: "step-head" }, h("strong", {}, `${i + 1}.`), scene),
        h("div", { class: "step-body" }, fade, mode, st.hold_s === null ? null : holdNum,
          h("div", { class: "mini" },
            h("button", { class: "btn small", type: "button", onclick: () => move(-1), "aria-label": "monter" }, "↑"),
            h("button", { class: "btn small", type: "button", onclick: () => move(1), "aria-label": "descendre" }, "↓"),
            h("button", { class: "btn small danger", type: "button", "aria-label": "retirer",
              onclick: () => { model.steps.splice(i, 1); drawSteps(); } }, "✕"))));
    }));
  };
  drawSteps();

  const body = h("div", {},
    h("label", { class: "field" }, h("span", {}, "Nom"), name),
    h("label", { class: "check" }, loop, h("span", {}, "Reprendre au début à la fin (boucle)")),
    h("p", { class: "hint" }, "Chaque étape : scène, temps de fondu (vide = celui de la scène), puis passage à l'étape suivante après un délai (compté à la fin du fondu) ou à la pédale."),
    list,
    h("button", { class: "btn small", type: "button", onclick: () => {
      model.steps.push({ scene: S.scenes[0].id, fade_s: null, hold_s: 2 }); drawSteps(); } }, "+ Ajouter une étape"));

  const buttons = [];
  if (sq) buttons.push({ label: "Supprimer", cls: "danger", run: async () => {
    if (!confirm(`Supprimer la séquence « ${sq.name} » ?`)) return false;
    if (!(await call("DELETE", `/api/sequences/${encodeURIComponent(sq.id)}`))) return false;
  } });
  buttons.push({ label: "Annuler" }, { label: "Enregistrer", cls: "primary", run: async () => {
    const payload = { name: name.value.trim(), loop: loop.checked,
      steps: model.steps.map((s) => ({ scene: s.scene, fade_s: s.fade_s, hold_s: s.hold_s })) };
    const res = sq ? await call("PUT", `/api/sequences/${encodeURIComponent(sq.id)}`, payload)
                   : await call("POST", "/api/sequences", payload);
    if (!res) return false;
  } });
  modal(sq ? "Modifier la séquence" : "Nouvelle séquence", body, buttons, { wide: true });
}

// ---------------------------------------------------------------- onglet Réglages

function renderReglages(view) {
  const s = S.settings;
  const master = slider("Intensité générale", "master", () => s.master, () => {});
  const masterInput = master.querySelector("input");
  masterInput.addEventListener("change", () => call("PUT", "/api/settings", { master: masterInput.value / 100 }));
  view.append(h("h2", {}, "Intensité générale"), h("div", { class: "card" }, master,
    h("p", { class: "hint" }, "À régler avant le concert : multiplie l'intensité de tous les projecteurs.")));

  const num = (key, label) => {
    const input = h("input", { type: "number", min: "0", step: "0.1", value: s[key] });
    input.addEventListener("change", async () => {
      const ok = await call("PUT", "/api/settings", { [key]: Number(input.value) });
      if (!ok) input.value = s[key];
    });
    return h("label", { class: "field" }, h("span", {}, label), input);
  };
  view.append(h("h2", {}, "Temps de fondu (secondes)"), h("div", { class: "card" },
    num("default_fade", "Entre scènes (par défaut)"), num("blackout_fade", "Blackout"), num("flash_fade", "Flash")));

  view.append(h("h2", {}, "Pédales"));
  const card = h("div", { class: "card" });
  const rows = s.pedals.map((p, i) => {
    const type = h("select", {}, ...[["none", "Aucune"], ["scene", "Scène"], ["sequence", "Séquence"], ["flash", "Flash (maintenu)"],
      ["next", "Étape suivante"], ["prev", "Étape précédente"]].map(([v, l]) => h("option", { value: v, selected: v === p.type }, l)));
    const target = h("select", {});
    const fill = () => {
      const list = type.value === "sequence" ? S.sequences : (["scene", "flash"].includes(type.value) ? S.scenes : []);
      target.replaceChildren(...list.map((x) => h("option", { value: x.id, selected: x.id === p.target }, x.name)));
      target.style.visibility = list.length ? "visible" : "hidden";
    };
    type.addEventListener("change", fill);
    fill();
    card.append(h("div", { class: "pedrow" }, h("strong", {}, "n° " + (i + 1)), type, target));
    return { type, target };
  });
  card.append(h("p", { class: "hint" }, "La 7ᵉ pédale est toujours le blackout."),
    h("button", { class: "btn primary", type: "button", onclick: async () => {
      const pedals = rows.map((r) => ({ type: r.type.value,
        target: ["scene", "sequence", "flash"].includes(r.type.value) ? r.target.value : null }));
      if (await call("PUT", "/api/settings", { pedals })) toast("Pédales enregistrées");
    } }, "Enregistrer les pédales"));
  view.append(card);
}

// ---------------------------------------------------------------- affichage

function render() {
  renderTabs();
  const view = document.getElementById("view");
  view.replaceChildren();
  if (!S.settings) return;
  ({ jeu: renderJeu, scenes: renderScenes, projecteurs: renderProjecteurs, sequences: renderSequences,
    reglages: renderReglages }[tab] || renderJeu)(view);
  paintStatus();
}

// ---------------------------------------------------------------- liaison temps réel

function connect() {
  const dot = document.getElementById("conn");
  const es = new EventSource("/api/events");
  es.addEventListener("status", (e) => {
    S.status = JSON.parse(e.data);
    paintStatus();
  });
  es.addEventListener("config", () => loadState());
  es.onopen = () => { dot.classList.add("ok"); loadState(); };
  es.onerror = () => dot.classList.remove("ok");
}

renderTabs();
loadState();
connect();
