/* Hinata Motion runtime - turns a project (JSON) into an animated stage.
   Every animation is a paused Web Animation, so the whole video is a pure
   function of time: seek(t) shows the exact frame for second t. The studio
   uses it for preview and scrubbing, the renderer for frame-perfect MP4. */
(function () {
  "use strict";

  const SIZES = { vertical: [1080, 1920], wide: [1920, 1080], square: [1080, 1080] };
  const DEFAULT_EASE = [0.22, 1, 0.36, 1];

  function bez(e) {
    const a = Array.isArray(e) && e.length === 4 ? e : DEFAULT_EASE;
    return `cubic-bezier(${a.map(v => Math.round(v * 1000) / 1000).join(",")})`;
  }

  // easing in JS (for counters) - same curve as CSS
  function bezierFn(p) {
    const [x1, y1, x2, y2] = Array.isArray(p) && p.length === 4 ? p : DEFAULT_EASE;
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const sx = t => ((ax * t + bx) * t + cx) * t, sy = t => ((ay * t + by) * t + cy) * t;
    const dx = t => (3 * ax * t + 2 * bx) * t + cx;
    return x => {
      if (x <= 0) return 0; if (x >= 1) return 1;
      let t = x;
      for (let i = 0; i < 8; i++) { const d = dx(t); if (Math.abs(d) < 1e-6) break; t -= (sx(t) - x) / d; }
      return sy(Math.min(1, Math.max(0, t)));
    };
  }

  function el(tag, cls, parent, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  // ------------------------------------------------------------------ mascots (original, drawn in code)

  const NS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function shade(hex, f) {
    const n = parseInt((hex || "#ff6b6b").replace("#", "").padEnd(6, "0").slice(0, 6), 16);
    let r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    const m = v => Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f)));
    return "#" + [m(r), m(g), m(b)].map(v => v.toString(16).padStart(2, "0")).join("");
  }

  const BODIES = {
    blob: c => `M100 28 C150 26 178 66 178 118 C178 172 146 200 100 200 C54 200 22 172 22 118 C22 66 50 30 100 28 Z`,
    drop: c => `M100 14 C122 52 176 92 176 140 C176 182 142 206 100 206 C58 206 24 182 24 140 C24 92 78 52 100 14 Z`,
    cloud: c => `M58 196 C30 196 16 176 18 154 C20 132 36 120 52 120 C50 88 72 64 102 64 C128 64 146 80 152 102 C176 100 190 120 188 146 C186 176 166 196 140 196 Z`,
    box: c => `M44 50 H156 Q180 50 180 74 V176 Q180 200 156 200 H44 Q20 200 20 176 V74 Q20 50 44 50 Z`,
    bot: c => `M50 60 H150 Q176 60 176 86 V170 Q176 196 150 196 H50 Q24 196 24 170 V86 Q24 60 50 60 Z`,
  };

  function mascot(kind, color, mood) {
    kind = BODIES[kind] ? kind : "blob";
    color = color || "#ff6b6b";
    const root = svg("svg", { viewBox: "0 0 200 230", class: "mascot" });
    const bob = svg("g", { class: "m-bob" }, root);
    svg("ellipse", { cx: 100, cy: 222, rx: 54, ry: 7, fill: "#000", opacity: 0.13, class: "m-shadow" }, root);
    // feet
    svg("ellipse", { cx: 76, cy: 204, rx: 16, ry: 9, fill: shade(color, -0.35) }, bob);
    svg("ellipse", { cx: 124, cy: 204, rx: 16, ry: 9, fill: shade(color, -0.35) }, bob);
    // arms
    const armL = svg("g", { class: "m-arm-l" }, bob);
    svg("rect", { x: 6, y: 120, width: 34, height: 18, rx: 9, fill: shade(color, -0.2) }, armL);
    const armR = svg("g", { class: "m-arm-r" }, bob);
    svg("rect", { x: 160, y: 120, width: 34, height: 18, rx: 9, fill: shade(color, -0.2) }, armR);
    if (kind === "bot") {
      svg("line", { x1: 100, y1: 60, x2: 100, y2: 30, stroke: shade(color, -0.4), "stroke-width": 6, "stroke-linecap": "round" }, bob);
      svg("circle", { cx: 100, cy: 26, r: 9, fill: "#ffd84d", class: "m-light" }, bob);
    }
    // body + belly shine
    svg("path", { d: BODIES[kind](), fill: color, stroke: shade(color, -0.3), "stroke-width": 4 }, bob);
    svg("ellipse", { cx: 70, cy: kind === "drop" ? 120 : 92, rx: 16, ry: 9, fill: "#fff", opacity: 0.35, transform: "rotate(-25 70 92)" }, bob);
    if (kind === "bot") svg("rect", { x: 46, y: 88, width: 108, height: 64, rx: 18, fill: "#1b1f2e" }, bob);
    // face
    const face = svg("g", { class: "m-face" }, bob);
    const ey = kind === "cloud" ? 132 : kind === "bot" ? 116 : 116;
    const eyes = svg("g", { class: "m-eyes" }, face);
    for (const ex of [78, 122]) {
      if (kind === "bot") {
        svg("rect", { x: ex - 10, y: ey - 12, width: 20, height: 24, rx: 8, fill: "#6fe3ff" }, eyes);
      } else {
        svg("ellipse", { cx: ex, cy: ey, rx: 13, ry: 16, fill: "#fff" }, eyes);
        svg("ellipse", { cx: ex + 2, cy: ey + 2, rx: 8, ry: 10, fill: "#1b1530" }, eyes);
        svg("circle", { cx: ex + 5, cy: ey - 3, r: 3.2, fill: "#fff" }, eyes);
      }
    }
    if (kind !== "bot") {
      svg("ellipse", { cx: 60, cy: ey + 22, rx: 9, ry: 5, fill: "#ff5a8a", opacity: 0.35 }, face);
      svg("ellipse", { cx: 140, cy: ey + 22, rx: 9, ry: 5, fill: "#ff5a8a", opacity: 0.35 }, face);
    }
    const mc = kind === "bot" ? "#6fe3ff" : "#1b1530";
    const my = ey + 26;
    if (mood === "wow") svg("ellipse", { cx: 100, cy: my + 2, rx: 8, ry: 10, fill: mc }, face);
    else if (mood === "think") {
      svg("path", { d: `M88 ${my} Q100 ${my - 3} 112 ${my + 2}`, stroke: mc, "stroke-width": 5, fill: "none", "stroke-linecap": "round" }, face);
      svg("path", { d: `M66 ${ey - 24} L88 ${ey - 28}`, stroke: shade(color, -0.5), "stroke-width": 5, "stroke-linecap": "round" }, face);
    } else svg("path", { d: `M84 ${my - 4} Q100 ${my + 12} 116 ${my - 4}`, stroke: mc, "stroke-width": 5, fill: "none", "stroke-linecap": "round" }, face);
    return root;
  }

  // ------------------------------------------------------------------ the builder

  function build(root, project) {
    const [W, H] = SIZES[project.size] || SIZES.vertical;
    const st = project.style || {};
    root.innerHTML = "";
    root.style.width = W + "px";
    root.style.height = H + "px";
    root.className = "hx-stage " + (H > W ? "vertical" : W > H ? "wide" : "square");
    root.style.setProperty("--u", Math.min(W, H) / 100 + "px");
    root.style.setProperty("--bg", st.bg || "#f6f1e7");
    root.style.setProperty("--fg", st.fg || "#17131f");
    root.style.setProperty("--accent", st.accent || "#c6f432");
    root.style.setProperty("--accent2", st.accent2 || "#7b5cff");
    root.style.setProperty("--font", (st.font ? `"${st.font}", ` : "") + '"Bahnschrift", "Segoe UI", system-ui, sans-serif');

    const anims = [], tickers = [];
    const speed = Math.max(0.25, Number(project.speed) || 1);
    const A = (node, frames, start, dur, opts = {}) => {
      const a = node.animate(frames, {
        delay: start * 1000 / speed, duration: Math.max(1, dur * 1000 / speed),
        easing: opts.easing || "linear", fill: opts.fill || "both",
        iterations: opts.iterations || 1, direction: opts.direction || "normal"
      });
      a.pause();
      anims.push(a);
      return a;
    };

    let t = 0;
    const scenes = project.scenes || [];
    scenes.forEach((s, i) => {
      const d = Math.max(1, Number(s.duration) || 3);
      const ease = bez(s.ease || project.ease);
      const sc = el("div", "scene scene-" + (s.type || "title"), root);
      sc.dataset.index = i;
      if (s.bg) sc.style.background = s.bg;
      decor(sc, i);
      const ctx = { A, ease, t0: t, d, s, sc, tickers, i, project };
      (LAYOUTS[s.type] || LAYOUTS.title)(ctx);
      // enter / exit
      const tr = s.transition || ["slide", "zoom", "wipe", "fade"][i % 4];
      const enterF = {
        fade: [{ opacity: 0 }, { opacity: 1 }],
        slide: [{ opacity: 0, transform: "translateY(6%)" }, { opacity: 1, transform: "none" }],
        zoom: [{ opacity: 0, transform: "scale(1.12)" }, { opacity: 1, transform: "none" }],
        wipe: [{ clipPath: "circle(0% at 50% 60%)", opacity: 1 }, { clipPath: "circle(150% at 50% 60%)", opacity: 1 }],
      }[tr] || [{ opacity: 0 }, { opacity: 1 }];
      A(sc, enterF, t, i === 0 ? 0.01 : 0.45, { easing: ease });
      if (i < scenes.length - 1) A(sc, [{ opacity: 1 }, { opacity: 0 }], t + d - 0.01, 0.35, { fill: "forwards" });
      t += d;
    });
    const total = t / speed;
    fit(root);
    return {
      fit: () => fit(root),
      duration: total, width: W, height: H,
      seek(sec) {
        const ms = Math.max(0, Math.min(total, sec)) * 1000;
        for (const a of anims) a.currentTime = ms;
        for (const k of tickers) k(sec * speed);
        root.querySelectorAll(".scene").forEach((sc, i) => {
          const s0 = scenes.slice(0, i).reduce((x, s) => x + Math.max(1, Number(s.duration) || 3), 0);
          const s1 = s0 + Math.max(1, Number(scenes[i].duration) || 3);
          sc.style.visibility = (sec * speed >= s0 - 0.01 && sec * speed < s1 + 0.4) || (i === scenes.length - 1 && sec * speed >= s0) ? "visible" : "hidden";
        });
      },
      sceneStarts() {
        let x = 0; return scenes.map(s => { const a = x / speed; x += Math.max(1, Number(s.duration) || 3); return a; });
      }
    };
  }

  // shrink any text that would spill out of its box (long words, long headlines)
  function fit(root) {
    root.classList.add("hx-measure");       // measure the settled layout, not mid-animation transforms
    try { fitNow(root); } finally { root.classList.remove("hx-measure"); }
  }
  function fitNow(root) {
    const W = root.clientWidth || parseFloat(root.style.width), H = root.clientHeight || parseFloat(root.style.height);
    const swap = [];
    root.querySelectorAll("[data-final]").forEach(n => { swap.push([n, n.textContent]); n.textContent = n.dataset.final; });
    root.querySelectorAll(".h1,.h2,.number,.sub,.speech,.cta,.itx,.bubble").forEach(n => {
      n.style.fontSize = "";
      let size = parseFloat(getComputedStyle(n).fontSize), guard = 0;
      const box = n.parentElement;
      const limit = Math.min(W * 0.94, box ? box.clientWidth + 2 : W);
      while (guard++ < 40 && size > 12 && (n.scrollWidth > n.clientWidth + 2 || n.getBoundingClientRect().width > limit)) {
        size *= 0.94; n.style.fontSize = size + "px";
      }
    });
    root.querySelectorAll(".center,.listbox,.split,.phone-wrap").forEach(b => {
      let guard = 0, sc = 1;
      b.style.zoom = "";
      while (guard++ < 20 && b.scrollHeight * sc > H * 0.9) { sc *= 0.94; b.style.zoom = sc; }
    });
    swap.forEach(([n, txt]) => { n.textContent = txt; });
  }

  function decor(sc, i) {
    const shapes = el("div", "decor", sc);
    for (let k = 0; k < 3; k++) el("i", "d" + ((i + k) % 5), shapes);
  }

  function words(parent, text, cls, ctx, at, stagger = 0.06) {
    const box = el("div", cls, parent);
    const parts = String(text || "").split(/(\[[^\]]+\]|\s+)/).filter(p => p && !/^\s+$/.test(p));
    parts.forEach((p, k) => {
      const hl = /^\[.*\]$/.test(p);
      const w = el("span", "w" + (hl ? " hl" : ""), box);
      if (hl) {
        const bg = el("span", "hl-bg", w);
        el("span", "hl-tx", w, p.slice(1, -1));
        ctx.A(bg, [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], at + 0.25 + k * stagger, 0.5, { easing: ctx.ease });
      } else w.textContent = p;
      ctx.A(w, [{ opacity: 0, transform: "translateY(0.7em) rotate(4deg)" }, { opacity: 1, transform: "none" }],
        at + k * stagger, 0.55, { easing: ctx.ease });
      box.appendChild(document.createTextNode(" "));
    });
    return box;
  }

  function placeMascot(parent, ctx, at, extraCls) {
    const s = ctx.s;
    if (!s.mascot || s.mascot === "none") return null;
    const wrap = el("div", "mascot-wrap " + (extraCls || ""), parent);
    const m = mascot(s.mascot, s.mascot_color, s.mood);
    wrap.appendChild(m);
    const sx = Number(s.mascot_scale) || 1;
    wrap.style.setProperty("--ms", sx);
    if (s.mascot_x != null) wrap.style.setProperty("--mx", s.mascot_x + "%");
    if (s.mascot_y != null) wrap.style.setProperty("--my", s.mascot_y + "%");
    ctx.A(wrap, [{ transform: "translateY(40%) scale(0.2) rotate(-12deg)", opacity: 0 },
      { transform: "translateY(-6%) scale(1.06) rotate(3deg)", opacity: 1, offset: 0.7 },
      { transform: "none", opacity: 1 }], at, 0.7, { easing: "cubic-bezier(.34,1.56,.64,1)" });
    const bob = m.querySelector(".m-bob");
    ctx.A(bob, [{ transform: "translateY(0)" }, { transform: "translateY(-5px)" }], at + 0.7, 0.9, { iterations: 40, direction: "alternate", easing: "ease-in-out" });
    ctx.A(m.querySelector(".m-eyes"), [{ transform: "scaleY(1)" }, { transform: "scaleY(1)", offset: 0.92 }, { transform: "scaleY(0.1)", offset: 0.96 }, { transform: "scaleY(1)" }],
      at, 2.6, { iterations: 40 });
    const arm = m.querySelector(".m-arm-r");
    if (s.mood === "wave" || ctx.s.type === "outro")
      ctx.A(arm, [{ transform: "rotate(0deg)" }, { transform: "rotate(-38deg)" }], at + 0.6, 0.32, { iterations: 30, direction: "alternate", easing: "ease-in-out" });
    else
      ctx.A(arm, [{ transform: "rotate(0deg)" }, { transform: "rotate(-14deg)" }], at + 0.6, 0.8, { iterations: 30, direction: "alternate", easing: "ease-in-out" });
    const light = m.querySelector(".m-light");
    if (light) ctx.A(light, [{ opacity: 1 }, { opacity: 0.3 }], at, 0.5, { iterations: 60, direction: "alternate" });
    return wrap;
  }

  function counter(node, s, ctx, at) {
    const target = parseFloat(String(s.number || "0").replace(/[^0-9.\-]/g, "")) || 0;
    const decimals = (String(s.number).split(".")[1] || "").replace(/\D/g, "").length;
    const f = bezierFn([0.16, 1, 0.3, 1]);
    const fmt = v => (s.prefix || "") + v.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + (s.suffix || "");
    ctx.tickers.push(sec => {
      const p = Math.max(0, Math.min(1, (sec - at) / 1.4));
      node.textContent = fmt(target * f(p));
    });
    node.textContent = fmt(0);
    node.dataset.final = fmt(target);
  }

  const LAYOUTS = {
    title(c) {
      const box = el("div", "center", c.sc);
      if (c.s.kicker) { const k = el("div", "kicker", box, c.s.kicker); c.A(k, [{ opacity: 0, letterSpacing: "0.6em" }, { opacity: 1, letterSpacing: "0.18em" }], c.t0 + 0.1, 0.7, { easing: c.ease }); }
      words(box, c.s.headline, "h1", c, c.t0 + 0.2);
      const bar = el("div", "bar", box);
      c.A(bar, [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], c.t0 + 0.5, 0.6, { easing: c.ease });
      if (c.s.sub) words(box, c.s.sub, "sub", c, c.t0 + 0.7, 0.03);
      placeMascot(c.sc, c, c.t0 + 0.6, "corner");
    },
    statement(c) {
      const box = el("div", "center", c.sc);
      words(box, c.s.headline, "h1 big", c, c.t0 + 0.15, 0.08);
      if (c.s.sub) words(box, c.s.sub, "sub", c, c.t0 + 0.9, 0.03);
      placeMascot(c.sc, c, c.t0 + 0.5, "corner");
    },
    big_number(c) {
      const box = el("div", "center", c.sc);
      if (c.s.headline) words(box, c.s.headline, "sub top", c, c.t0 + 0.1, 0.04);
      const n = el("div", "number", box);
      counter(n, c.s, c, c.t0 + 0.3);
      c.A(n, [{ transform: "scale(0.6)", opacity: 0 }, { transform: "scale(1.06)", opacity: 1, offset: 0.7 }, { transform: "none", opacity: 1 }], c.t0 + 0.2, 0.7, { easing: c.ease });
      const pill = el("div", "chip", box);
      c.A(pill, [{ transform: "scaleX(0)" }, { transform: "none" }], c.t0 + 0.9, 0.5, { easing: c.ease });
      if (c.s.sub) words(box, c.s.sub, "sub", c, c.t0 + 1.0, 0.03);
      placeMascot(c.sc, c, c.t0 + 0.5, "corner");
    },
    list(c) {
      const box = el("div", "listbox", c.sc);
      words(box, c.s.headline, "h2", c, c.t0 + 0.1, 0.05);
      (c.s.items || []).slice(0, 5).forEach((it, k) => {
        const row = el("div", "item", box);
        el("span", "badge", row, String(k + 1));
        el("span", "itx", row, it);
        c.A(row, [{ opacity: 0, transform: "translateX(-14%)" }, { opacity: 1, transform: "none" }], c.t0 + 0.5 + k * 0.32, 0.55, { easing: c.ease });
      });
      placeMascot(c.sc, c, c.t0 + 0.4, "corner");
    },
    phone(c) {
      const wrap = el("div", "phone-wrap", c.sc);
      if (c.s.headline) words(wrap, c.s.headline, "h2", c, c.t0 + 0.05, 0.05);
      const ph = el("div", "phone", wrap);
      c.A(ph, [{ transform: "translateY(30%) rotate(-6deg)", opacity: 0 }, { transform: "none", opacity: 1 }], c.t0 + 0.15, 0.7, { easing: c.ease });
      const head = el("div", "ph-head", ph);
      el("span", "ph-av", head);
      el("span", "ph-name", head, c.s.chat_name || "Chat");
      const body = el("div", "ph-body", ph);
      const msgs = (c.s.messages || []).slice(0, 5);
      const step = Math.max(0.45, (c.d - 1.3) / Math.max(1, msgs.length));
      msgs.forEach((m, k) => {
        const at = c.t0 + 0.8 + k * step;
        if (m.from !== "me") {
          const dots = el("div", "bubble them dots", body);
          el("i", "", dots); el("i", "", dots); el("i", "", dots);
          c.A(dots, [{ opacity: 0, maxHeight: "0px" }, { opacity: 1, maxHeight: "200px", offset: 0.15 }, { opacity: 1, maxHeight: "200px", offset: 0.85 }, { opacity: 0, maxHeight: "0px" }], at - 0.35, 0.4);
        }
        const b = el("div", "bubble " + (m.from === "me" ? "me" : "them"), body, m.text);
        c.A(b, [{ opacity: 0, transform: "scale(0.5)", maxHeight: "0px" }, { opacity: 1, transform: "none", maxHeight: "400px" }], at, 0.4, { easing: "cubic-bezier(.34,1.56,.64,1)" });
      });
      placeMascot(c.sc, c, c.t0 + 0.9, "corner");
    },
    split(c) {
      const box = el("div", "split", c.sc);
      const left = el("div", "split-text", box);
      words(left, c.s.headline, "h1", c, c.t0 + 0.15, 0.06);
      const right = el("div", "split-art", box);
      if (c.s.sub) {
        const bub = el("div", "speech", right, c.s.sub);
        c.A(bub, [{ opacity: 0, transform: "scale(0.3)" }, { opacity: 1, transform: "none" }], c.t0 + 1.0, 0.45, { easing: "cubic-bezier(.34,1.56,.64,1)" });
      }
      placeMascot(right, c, c.t0 + 0.4, "inline");
    },
    outro(c) {
      const box = el("div", "center", c.sc);
      const ring = el("div", "ring", c.sc);
      c.A(ring, [{ transform: "translate(-50%,-50%) scale(0.2)", opacity: 0.8 }, { transform: "translate(-50%,-50%) scale(1.4)", opacity: 0 }], c.t0 + 0.2, 1.6, { iterations: 6 });
      words(box, c.s.headline, "h1", c, c.t0 + 0.2, 0.07);
      if (c.s.sub) {
        const cta = el("div", "cta", box, c.s.sub);
        c.A(cta, [{ opacity: 0, transform: "translateY(40%)" }, { opacity: 1, transform: "none" }], c.t0 + 0.8, 0.5, { easing: c.ease });
        c.A(cta, [{ transform: "scale(1)" }, { transform: "scale(1.05)" }], c.t0 + 1.4, 0.6, { iterations: 20, direction: "alternate", easing: "ease-in-out" });
      }
      placeMascot(c.sc, c, c.t0 + 0.5, "bottom");
    },
  };

  window.HXMotion = { build, mascot, SIZES, bez, bezierFn, LAYOUTS: Object.keys(LAYOUTS), MASCOTS: Object.keys(BODIES) };
})();
