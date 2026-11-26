// Landing page (index.html): scene transitions instead of page scroll, the
// rotating feature model, the fusion layer cycle, the preset archive wall and
// the ambient particle field. Static only — reads previews/presets.json, never the API.

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = window.matchMedia("(pointer: fine)").matches;

// The repo's full preset list by default. The GitHub Pages copy (docs/) points
// <body data-presets> at a trimmed manifest: { count, presets: [...] }.
const PRESETS_URL = document.body.dataset.presets || "previews/presets.json";
const SCENE_LOCK_MS = reduceMotion ? 450 : 1150;
const WHEEL_GESTURE_GAP_MS = 220; // quieter than this = a new wheel/trackpad gesture
const WHEEL_THRESHOLD = 28;
const SWIPE_THRESHOLD = 46;

const body = document.body;
const scenes = Array.from(document.querySelectorAll(".scene"));
const railButtons = Array.from(document.querySelectorAll(".lp-rail [data-go]"));
const readoutIdx = document.getElementById("lp-readout-idx");
const readoutName = document.getElementById("lp-readout-name");
const live = document.getElementById("lp-live");

let current = 0;
let locked = false;

/* ───────── Ambient particle field ───────── */

const field = (() => {
  const canvas = document.getElementById("lp-field");
  const ctx = canvas.getContext("2d");
  const colors = ["255,107,74", "78,197,241", "255,229,102", "155,123,255", "238,240,248", "238,240,248"];
  let w = 0;
  let h = 0;
  let dpr = 1;
  let stars = [];
  let speed = 1;
  let boost = 0;
  let direction = 1;
  let raf = 0;

  function spawn(star, far) {
    star.x = (Math.random() * 2 - 1) * w;
    star.y = (Math.random() * 2 - 1) * h;
    star.z = far ? 1 : Math.random() * 0.9 + 0.1;
    star.pz = star.z;
    star.c = colors[(Math.random() * colors.length) | 0];
    star.s = Math.random() * 1.1 + 0.35;
    return star;
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.round(Math.min(260, (w * h) / 6500));
    stars = Array.from({ length: count }, () => spawn({}, false));
    // Resizing clears the canvas; with reduced motion there's no loop to redraw it.
    if (reduceMotion) drawStill();
  }

  function drawStill() {
    frame();
    stop();
  }

  function frame() {
    raf = requestAnimationFrame(frame);
    boost *= 0.94;
    speed = 1 + boost;
    const cx = w / 2;
    const cy = h * 0.45;
    const f = Math.min(w, h) * 0.5;
    ctx.clearRect(0, 0, w, h);
    for (const s of stars) {
      s.pz = s.z;
      s.z -= 0.0007 * speed * direction;
      if (s.z <= 0.02 || s.z > 1) spawn(s, direction > 0);
      const x = cx + (s.x / s.z) * (f / w);
      const y = cy + (s.y / s.z) * (f / h);
      if (x < -50 || x > w + 50 || y < -50 || y > h + 50) {
        spawn(s, direction > 0);
        continue;
      }
      const alpha = Math.min(1, (1 - s.z) * 1.2) * 0.75;
      if (boost > 0.6) {
        const px = cx + (s.x / s.pz) * (f / w);
        const py = cy + (s.y / s.pz) * (f / h);
        ctx.strokeStyle = `rgba(${s.c},${alpha})`;
        ctx.lineWidth = s.s * (1.2 - s.z);
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(x, y);
        ctx.stroke();
      } else {
        ctx.fillStyle = `rgba(${s.c},${alpha})`;
        ctx.beginPath();
        ctx.arc(x, y, s.s * (1.25 - s.z), 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  function start() {
    if (!raf) frame();
  }

  function stop() {
    cancelAnimationFrame(raf);
    raf = 0;
  }

  resize();
  window.addEventListener("resize", resize);
  if (reduceMotion) {
    drawStill(); // one static frame
  } else {
    start();
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  }

  return {
    warp(dir) {
      if (reduceMotion) return;
      direction = dir;
      boost = 22;
      setTimeout(() => (direction = 1), 900);
    },
  };
})();

/* ───────── Scene machine ───────── */

function applySceneState(index) {
  scenes.forEach((scene, i) => {
    const active = i === index;
    scene.classList.toggle("is-active", active);
    scene.classList.toggle("is-past", i < index);
    scene.classList.toggle("is-future", i > index);
    scene.inert = !active;
    if (active) scene.removeAttribute("aria-hidden");
    else scene.setAttribute("aria-hidden", "true");
  });
  railButtons.forEach((btn) => {
    if (Number(btn.dataset.go) === index) btn.setAttribute("aria-current", "step");
    else btn.removeAttribute("aria-current");
  });
  body.dataset.scene = String(index);
  body.style.setProperty("--scene-i", String(index));
  const name = scenes[index].dataset.name || "";
  readoutIdx.textContent = String(index + 1).padStart(2, "0");
  readoutName.textContent = name;
  onSceneEnter(index);
}

function go(target, { force = false } = {}) {
  const next = Math.max(0, Math.min(scenes.length - 1, target));
  if (next === current || (locked && !force)) return;
  const dir = next > current ? 1 : -1;
  current = next;
  locked = true;
  field.warp(dir);
  scenes[next].scrollTop = 0;
  applySceneState(next);
  live.textContent = `Section ${next + 1} of ${scenes.length}: ${scenes[next].dataset.name}`;
  history.replaceState(null, "", `#${scenes[next].id}`);
  window.setTimeout(() => {
    locked = false;
  }, SCENE_LOCK_MS);
}

// A scene scrolls internally only when its real content (not floating
// decoration) is taller than the viewport — e.g. phones or tiny windows.
function measureScene(scene) {
  const inner = scene.querySelector(".scene__inner");
  if (!inner) return;
  const cs = getComputedStyle(scene);
  const needed = inner.offsetHeight + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
  const tall = needed > scene.clientHeight + 2;
  scene.classList.toggle("is-tall", tall);
  // Once it fits again the scene can't scroll, so don't leave it stuck part-way down.
  if (!tall && scene.scrollTop) scene.scrollTop = 0;
}

const sizeWatcher = new ResizeObserver(() => scenes.forEach(measureScene));
scenes.forEach((scene) => {
  const inner = scene.querySelector(".scene__inner");
  if (inner) sizeWatcher.observe(inner);
});
window.addEventListener("resize", () => scenes.forEach(measureScene));

// Let an over-tall scene scroll internally before we change scene.
function canScrollInside(scene, dir) {
  if (!scene.classList.contains("is-tall")) return false;
  if (scene.scrollHeight <= scene.clientHeight + 1) return false;
  if (dir > 0) return scene.scrollTop + scene.clientHeight < scene.scrollHeight - 1;
  return scene.scrollTop > 0;
}

// Wheel / trackpad: one scene per gesture; inertia tails are ignored.
let lastWheelAt = 0;
let gestureSpent = false;
let wheelAcc = 0;

window.addEventListener(
  "wheel",
  (e) => {
    if (e.ctrlKey) return; // pinch-zoom
    const dy = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : 0;
    const gap = e.timeStamp - lastWheelAt;
    lastWheelAt = e.timeStamp;
    if (gap > WHEEL_GESTURE_GAP_MS) {
      gestureSpent = false;
      wheelAcc = 0;
    }
    if (!dy) return;
    const scene = scenes[current];
    if (canScrollInside(scene, Math.sign(dy))) {
      gestureSpent = true; // the rest of this gesture belongs to the inner scroll
      return;
    }
    e.preventDefault();
    if (gestureSpent || locked) return;
    wheelAcc += e.deltaMode === 1 ? dy * 16 : dy;
    if (Math.abs(wheelAcc) >= WHEEL_THRESHOLD) {
      gestureSpent = true;
      go(current + Math.sign(wheelAcc));
      wheelAcc = 0;
    }
  },
  { passive: false },
);

// Touch: vertical swipe changes scene (unless the scene scrolled internally).
let touch = null;

window.addEventListener(
  "touchstart",
  (e) => {
    if (e.touches.length !== 1) {
      touch = null;
      return;
    }
    const t = e.touches[0];
    touch = { x: t.clientX, y: t.clientY, scroll: scenes[current].scrollTop };
  },
  { passive: true },
);

window.addEventListener(
  "touchend",
  (e) => {
    if (!touch) return;
    const t = e.changedTouches[0];
    const dy = touch.y - t.clientY;
    const dx = touch.x - t.clientX;
    const scene = scenes[current];
    const scrolled = Math.abs(scene.scrollTop - touch.scroll) > 2;
    touch = null;
    if (scrolled || Math.abs(dy) < SWIPE_THRESHOLD || Math.abs(dx) > Math.abs(dy)) return;
    if (canScrollInside(scene, Math.sign(dy))) return;
    go(current + Math.sign(dy));
  },
  { passive: true },
);

// Keyboard
window.addEventListener("keydown", (e) => {
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  const tag = e.target instanceof Element ? e.target.closest("input, textarea, select, [contenteditable]") : null;
  if (tag) return;
  const onControl = e.target instanceof Element && e.target.closest("a, button");
  const scene = scenes[current];
  let dir = 0;
  switch (e.key) {
    case "ArrowDown":
    case "PageDown":
      dir = 1;
      break;
    case "ArrowUp":
    case "PageUp":
      dir = -1;
      break;
    case " ":
      if (onControl) return; // Space activates the focused control
      dir = e.shiftKey ? -1 : 1;
      break;
    case "Home":
      e.preventDefault();
      go(0);
      return;
    case "End":
      e.preventDefault();
      go(scenes.length - 1);
      return;
    default:
      return;
  }
  e.preventDefault();
  if (canScrollInside(scene, dir)) {
    // Focus usually sits on <body>, so the browser wouldn't scroll the scene itself.
    scene.scrollBy({ top: dir * scene.clientHeight * 0.7, behavior: reduceMotion ? "auto" : "smooth" });
    return;
  }
  go(current + dir);
});

document.querySelectorAll("[data-go]").forEach((el) => {
  el.addEventListener("click", () => go(Number(el.dataset.go), { force: true }));
});

document.querySelector("[data-next]")?.addEventListener("click", () => go(current + 1, { force: true }));

window.addEventListener("hashchange", () => {
  const i = scenes.findIndex((s) => `#${s.id}` === location.hash);
  if (i >= 0) go(i, { force: true });
});

/* ───────── Pointer parallax ───────── */

if (finePointer && !reduceMotion) {
  let pending = false;
  let mx = 0;
  let my = 0;
  window.addEventListener("pointermove", (e) => {
    mx = (e.clientX / window.innerWidth) * 2 - 1;
    my = (e.clientY / window.innerHeight) * 2 - 1;
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      document.documentElement.style.setProperty("--mx", mx.toFixed(3));
      document.documentElement.style.setProperty("--my", my.toFixed(3));
      pending = false;
    });
  });
}

/* ───────── 01 · Rotating feature model ───────── */

const orbit = (() => {
  const host = document.querySelector(".orbit");
  const sceneEl = document.getElementById("orbit-scene");
  const ring = document.getElementById("orbit-ring");
  const cards = Array.from(ring.querySelectorAll(".fcard"));
  const n = cards.length;
  const step = 360 / n;
  let angle = -12;
  let velocity = 0;
  let dragging = false;
  let lastX = 0;
  let raf = 0;
  const idleSpeed = reduceMotion ? 0 : 0.11; // deg per frame

  function layout() {
    host.style.removeProperty("--cw"); // measure the stylesheet's card width first
    let width = ring.offsetWidth || 180;
    const spread = 0.5 / Math.tan(Math.PI / n) + 0.22; // ring radius per px of card width
    // The whole ring (radius + half a card seen side-on) must fit across the model's
    // box with a small margin; on narrow phones shrink the cards (and radius) to fit.
    const fit = (host.clientWidth / 2 - 12) / Math.hypot(spread, 0.5);
    if (fit > 0 && width > fit) {
      width = Math.floor(fit);
      host.style.setProperty("--cw", `${width}px`);
    }
    host.style.setProperty("--n", String(n));
    host.style.setProperty("--r", `${Math.round(width * spread)}px`);
  }

  function paint() {
    ring.style.setProperty("--spin", `${angle.toFixed(2)}deg`);
    for (let k = 0; k < n; k += 1) {
      const a = ((k * step + angle) * Math.PI) / 180;
      const face = Math.max(0, Math.cos(a));
      cards[k].style.setProperty("--face", face.toFixed(3));
    }
  }

  function tick() {
    raf = requestAnimationFrame(tick);
    if (!dragging) {
      velocity *= 0.95;
      angle -= idleSpeed + velocity;
    }
    paint();
  }

  sceneEl.addEventListener("pointerdown", (e) => {
    dragging = true;
    lastX = e.clientX;
    velocity = 0;
    sceneEl.classList.add("is-dragging");
    sceneEl.setPointerCapture(e.pointerId);
  });

  sceneEl.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX;
    lastX = e.clientX;
    angle += dx * 0.35;
    velocity = -dx * 0.35;
    if (reduceMotion) paint();
  });

  const release = (e) => {
    if (!dragging) return;
    dragging = false;
    sceneEl.classList.remove("is-dragging");
    if (sceneEl.hasPointerCapture(e.pointerId)) sceneEl.releasePointerCapture(e.pointerId);
  };
  sceneEl.addEventListener("pointerup", release);
  sceneEl.addEventListener("pointercancel", release);

  layout();
  paint();
  window.addEventListener("resize", layout);

  return {
    run(on) {
      if (on && !raf && !reduceMotion) tick();
      if (!on && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    },
  };
})();

/* ───────── 03 · Fusion layer cycle ───────── */

const fusion = (() => {
  const planes = Array.from(document.querySelectorAll("#stack-rig .plane"));
  const items = Array.from(document.querySelectorAll("#fusion-legend li"));
  let i = 0;
  let timer = 0;
  let loaded = false;

  function light(k) {
    planes.forEach((p, idx) => p.classList.toggle("is-lit", idx === k));
    items.forEach((li, idx) => li.classList.toggle("is-lit", idx === k));
  }

  function load() {
    if (loaded) return;
    loaded = true;
    planes.forEach((p) => {
      const img = p.querySelector("img[data-src]");
      if (img) img.src = img.dataset.src;
    });
  }

  items.forEach((li, idx) =>
    li.addEventListener("pointerenter", () => {
      i = idx;
      light(i);
    }),
  );

  return {
    load,
    run(on) {
      window.clearInterval(timer);
      timer = 0;
      if (!on) return;
      load();
      light(i);
      if (reduceMotion) return;
      timer = window.setInterval(() => {
        i = (i + 1) % planes.length;
        light(i);
      }, 1800);
    },
  };
})();

/* ───────── 04 · Preset archive wall ───────── */

const archive = (() => {
  const rows = Array.from(document.querySelectorAll(".archive__row"));
  let built = false;
  let presets = null;

  function shuffle(list) {
    const a = list.slice();
    for (let i = a.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function tile(src, delay) {
    const el = document.createElement("div");
    el.className = "tile";
    el.style.animationDelay = `${delay}s`;
    const img = document.createElement("img");
    img.alt = "";
    img.decoding = "async";
    img.addEventListener("load", () => img.classList.add("is-loaded"), { once: true });
    img.src = src;
    el.append(img);
    return el;
  }

  function build() {
    if (built || !presets) return;
    built = true;
    const perRow = window.innerWidth < 700 ? 4 : 6;
    const picks = shuffle(presets.filter((p) => typeof p.post_edit_image === "string")).slice(0, perRow * rows.length);
    rows.forEach((row, r) => {
      const set = picks.slice(r * perRow, (r + 1) * perRow).map((p) => p.post_edit_image);
      // Two copies so the marquee loops seamlessly at -50%.
      [...set, ...set].forEach((src, k) => row.append(tile(src, -((k * 1.3 + r) % 8))));
    });
  }

  return {
    setPresets(list) {
      presets = list;
      if (current >= 2) build();
    },
    build,
  };
})();

/* ───────── Preset count (static manifest) ───────── */

// An inline <script type="application/json" id="lp-presets"> wins over the fetch, so the
// page also works when opened straight from disk (file:// blocks fetch).
function loadPresets() {
  const inline = document.getElementById("lp-presets");
  if (inline) {
    try {
      return Promise.resolve(JSON.parse(inline.textContent));
    } catch {
      /* fall through to the network copy */
    }
  }
  return fetch(PRESETS_URL).then((res) =>
    res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)),
  );
}

loadPresets()
  .then((data) => {
    const list = Array.isArray(data) ? data : data?.presets;
    const count = Array.isArray(data) ? data.length : Number(data?.count);
    if (!Array.isArray(list) || !list.length) return;
    if (Number.isFinite(count) && count > 0) {
      document.querySelectorAll("[data-preset-count]").forEach((el) => {
        el.textContent = String(count);
      });
    }
    archive.setPresets(list);
  })
  .catch(() => {
    /* Opened without a server (file://) — keep the static fallback copy. */
  });

/* ───────── Scene hooks ───────── */

function onSceneEnter(index) {
  orbit.run(index === 0);
  fusion.run(index === 2);
  if (index >= 1) fusion.load(); // warm the next scene's images
  if (index >= 2) archive.build();
}

/* ───────── Boot ───────── */

const initial = Math.max(
  0,
  scenes.findIndex((s) => `#${s.id}` === location.hash),
);
current = initial;
applySceneState(initial);
