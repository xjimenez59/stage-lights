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
let tab = "jeu";
try { tab = localStorage.getItem("tab") || "jeu"; } catch (e) { /* stockage indisponible */ }
const hashTab = location.hash.slice(1);
if (["jeu", "couleurs", "sequences", "reglages"].includes(hashTab)) tab = hashTab;  // lien direct vers un onglet
let editMode = false;
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

const TABS = [["jeu", "Jeu"], ["couleurs", "Couleurs"], ["sequences", "Séquences"], ["reglages", "Réglages"]];

function renderTabs() {
  const nav = document.getElementById("tabs");
  nav.replaceChildren(...TABS.map(([id, label]) => h("button", {
    type: "button", role: "tab", class: id === tab ? "on" : "",
    onclick: () => {
      tab = id;
      try { localStorage.setItem("tab", id); } catch (e) { /* ignoré */ }
      render();
    },
  }, label)));
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

function renderJeu(view) {
  view.append(h("h2", {}, "Scènes", h("span", { class: "spacer" }),
    h("button", { class: "btn small", type: "button", onclick: () => { editMode = !editMode; render(); } },
      editMode ? "Terminé" : "✎ Modifier")));
  if (!S.scenes.length) view.append(h("p", { class: "hint" },
    "Aucune scène. Réglez les couleurs dans l'onglet « Couleurs » puis enregistrez-les comme scène."));
  const grid = h("div", { class: "grid" + (editMode ? " editing" : "") });
  for (const sc of S.scenes) {
    grid.append(h("button", {
      class: "scene", type: "button", "data-scene": sc.id,
      onclick: () => (editMode ? editScene(sc) : call("POST", `/api/scenes/${encodeURIComponent(sc.id)}/recall`)),
    }, h("span", { class: "sw", style: `background:${sceneSwatch(sc)}` }),
      h("span", { class: "name" }, sc.name),
      h("span", { class: "sub" }, sc.fade_s === null ? "fondu : défaut" : `fondu : ${sc.fade_s} s`)));
  }
  view.append(grid);

  if (S.sequences.length) {
    view.append(h("h2", {}, "Séquences"));
    for (const sq of S.sequences) {
      view.append(h("div", { class: "seq", "data-seq": sq.id },
        h("div", { class: "name" }, sq.name, h("div", { class: "sub" }, "")),
        h("button", { class: "btn small", type: "button", onclick: () => call("POST", "/api/sequence/prev") }, "◀"),
        h("button", { class: "btn small", type: "button", onclick: () => call("POST", "/api/sequence/next") }, "▶"),
        h("button", { class: "btn", type: "button", "data-toggle": "",
          onclick: () => call("POST", `/api/sequences/${encodeURIComponent(sq.id)}/toggle`) }, "▶ Lancer")));
    }
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

function editScene(sc) {
  const name = h("input", { type: "text", value: sc.name });
  const fade = h("input", { type: "number", min: "0", step: "0.1", value: sc.fade_s === null ? "" : sc.fade_s,
    placeholder: "défaut" });
  const body = h("div", {},
    h("label", { class: "field" }, h("span", {}, "Nom"), name),
    h("label", { class: "field" }, h("span", {}, "Temps de fondu (secondes, vide = défaut)"), fade));
  modal("Modifier la scène", body, [
    { label: "Supprimer", cls: "danger", run: async () => {
      if (!confirm(`Supprimer la scène « ${sc.name} » ?`)) return false;
      if (!(await call("DELETE", `/api/scenes/${encodeURIComponent(sc.id)}`))) return false;
    } },
    { label: "Remplacer par l'état actuel", run: async () => {
      if (!confirm("Remplacer le contenu de cette scène par les couleurs actuelles ?")) return false;
      if (!(await call("PUT", `/api/scenes/${encodeURIComponent(sc.id)}`,
        { name: name.value.trim() || sc.name, fade_s: fade.value === "" ? null : Number(fade.value), capture: "all" }))) return false;
    } },
    { label: "Annuler" },
    { label: "Enregistrer", cls: "primary", run: async () => {
      const ok = await call("PUT", `/api/scenes/${encodeURIComponent(sc.id)}`,
        { name: name.value.trim() || sc.name, fade_s: fade.value === "" ? null : Number(fade.value), states: sc.states });
      if (!ok) return false;
    } },
  ]);
}

// ---------------------------------------------------------------- onglet Couleurs

const selection = new Set();
let selectionInit = false;
let colorHS = { h: 0, s: 1 };  // dernière teinte / saturation choisies sur la roue
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
  }
  refreshChips();
  if (!pendingTimer) pendingTimer = setTimeout(flushFixtures, 70);
}

async function flushFixtures() {
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
    el.classList.toggle("on", selection.has(el.dataset.chip));
    el.querySelector(".sw").style.background = stateColor(S.current[el.dataset.chip]);
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

function renderCouleurs(view) {
  if (!S.fixtures.length) {
    view.append(h("p", { class: "hint" }, "Aucun projecteur dans le plan de feu."));
    return;
  }
  if (!selectionInit) { S.fixtures.forEach((f) => selection.add(f.id)); selectionInit = true; }
  for (const id of [...selection]) if (!S.fixtures.some((f) => f.id === id)) selection.delete(id);

  view.append(h("h2", {}, "Projecteurs", h("span", { class: "spacer" }),
    h("button", { class: "btn small", type: "button", onclick: () => { S.fixtures.forEach((f) => selection.add(f.id)); render(); } }, "Tous"),
    h("button", { class: "btn small", type: "button", onclick: () => { selection.clear(); render(); } }, "Aucun")));
  const chips = h("div", { class: "chips" });
  for (const f of S.fixtures) {
    chips.append(h("button", {
      class: "chip", type: "button", "data-chip": f.id,
      onclick: () => { selection.has(f.id) ? selection.delete(f.id) : selection.add(f.id); render(); },
    }, h("span", { class: "sw" }), h("span", {}, f.name)));
  }
  view.append(chips);

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
    (v) => pushFixtures(lightIfDark({ rgb: hsv2rgb(colorHS.h, colorHS.s, v) }))));
  mk("Blanc chaud", "white", "white");
  mk("Ambre", "amber", "amber");
  mk("Stroboscope", "strobe", "strobe");
  if (!selection.size) sliders.append(h("p", { class: "hint" }, "Sélectionnez au moins un projecteur."));
  const syncSliders = () => sliders.querySelectorAll("[data-slider]").forEach((s) => s.sync());
  view.append(h("div", { class: "picker" }, wheel, sliders),
    h("p", { class: "hint" }, "« Couleurs » et « Blanc chaud » se règlent séparément : mettez les couleurs à 0 % pour n'avoir que le blanc chaud."));

  view.append(h("h2", {}, "Couleurs rapides"));
  const pal = h("div", { class: "palette" });
  for (const [name, rgb] of PALETTE) {
    pal.append(h("button", { class: "swatch", type: "button", title: name, "aria-label": name,
      style: `background:rgb(${rgb.map((x) => Math.round(x * 255)).join(",")})`,
      onclick: () => preset({ rgb, white: 0, amber: 0 }, syncSliders) }));
  }
  pal.append(h("button", { class: "swatch wide", type: "button", style: "background:rgb(255,214,170)",
    onclick: () => preset({ rgb: [0, 0, 0], white: 1 }, syncSliders) }, "Blanc chaud"));
  view.append(pal);

  view.append(h("h2", {}, "Scène"), h("div", { class: "row" },
    h("button", { class: "btn primary", type: "button", disabled: !S.fixtures.length, onclick: saveSceneDialog },
      "Enregistrer comme scène…")));
  refreshChips();
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

function saveSceneDialog() {
  const name = h("input", { type: "text", placeholder: "Nom de la scène", maxlength: "40" });
  const target = h("select", {}, h("option", { value: "" }, "Nouvelle scène"),
    ...S.scenes.map((s) => h("option", { value: s.id }, "Remplacer : " + s.name)));
  const only = h("input", { type: "checkbox" });
  target.addEventListener("change", () => { const s = sceneById(target.value); if (s) name.value = s.name; });
  const body = h("div", {},
    h("label", { class: "field" }, h("span", {}, "Enregistrer dans"), target),
    h("label", { class: "field" }, h("span", {}, "Nom"), name),
    h("label", { class: "check" }, only, h("span", {}, "Seulement les projecteurs sélectionnés")),
    h("p", { class: "hint" }, "Les projecteurs absents d'une scène restent tels quels quand on la rappelle."));
  modal("Enregistrer la scène", body, [
    { label: "Annuler" },
    { label: "Enregistrer", cls: "primary", run: async () => {
      const capture = only.checked ? [...selection] : "all";
      const nm = name.value.trim();
      if (!target.value && !nm) { toast("Donnez un nom à la scène"); return false; }
      const res = target.value
        ? await call("PUT", `/api/scenes/${encodeURIComponent(target.value)}`, { name: nm || undefined, capture })
        : await call("POST", "/api/scenes", { name: nm, capture });
      if (!res) return false;
      toast(`Scène « ${res.name} » enregistrée`);
    } },
  ]);
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
  ({ jeu: renderJeu, couleurs: renderCouleurs, sequences: renderSequences, reglages: renderReglages }[tab] || renderJeu)(view);
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
