// 3D view of the kitting cell, used by the replay page and the chat page (proposal, asked for by Mrs Johnson at
// Gate A). It draws with three.js (vendor/three.min.js, MIT licence, see vendor/three.LICENSE).
//
// It gets the same four drawing calls as the 2D view in viewer_page.html (drawStatic, drawParts, drawArm and
// drawFlag) with the same layout numbers, so one piece of code animates both views and they always show the same
// state. The units are those of the 2D drawing: x runs along the cell as in the 2D view, the height is TABLE minus
// the 2D y, and z points from the back of the table to the front.
//
// createCell3D returns null when three.js or WebGL is not available, and the pages then keep the 2D view.
function createCell3D(host, L) {
  "use strict";
  if (typeof THREE === "undefined") return null;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch (e) {
    return null;
  }
  if (!renderer.getContext()) return null;

  const ASPECT = 2.1;
  const wx = x => x - L.W / 2;
  const hy = y => L.TABLE - y;
  const BACK = -125;

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.setAttribute("role", "img");
  renderer.domElement.setAttribute("aria-label", "3D view of the kitting cell");
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.touchAction = "none";
  host.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, ASPECT, 10, 6000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a96a3, 0.8));
  const sun = new THREE.DirectionalLight(0xffffff, 0.7);
  sun.position.set(-260, 720, 520);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -L.W / 2 - 60, right: L.W / 2 + 60, top: 420, bottom: -420, near: 100, far: 2000 });
  sun.shadow.bias = -0.0008;
  sun.shadow.normalBias = 0.6;
  scene.add(sun);

  const staticGroup = new THREE.Group(), partGroup = new THREE.Group(), flagGroup = new THREE.Group();
  let armGroup = new THREE.Group();
  scene.add(staticGroup, partGroup, flagGroup, armGroup);

  // Colours come from the CSS colour tokens of the page, so the 3D view follows light and dark mode.
  const probe = document.createElement("canvas").getContext("2d");
  function cssColour(value) {
    probe.fillStyle = "#000";
    probe.fillStyle = value;
    return new THREE.Color(probe.fillStyle);
  }
  const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  const colour = name => cssColour(token(name));
  const solid = (c, extra) => new THREE.MeshStandardMaterial(Object.assign({ color: c, roughness: 0.7, metalness: 0.05 }, extra || {}));

  function box(w, h, d, material, x, y, z, shadows) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
    mesh.position.set(x, y, z);
    mesh.castShadow = shadows !== false;
    mesh.receiveShadow = true;
    return mesh;
  }

  function clear(group) {
    for (const child of [...group.children]) {
      group.remove(child);
      child.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        const materials = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
        for (const m of materials) { if (m.map) m.map.dispose(); m.dispose(); }
      });
    }
  }

  // Text as a texture: flat on the table for the names, or a sprite that always faces the camera.
  function textCanvas(text, size, cssValue, weight) {
    const scale = 4;
    const font = (weight || 600) + " " + size * scale + "px 'Segoe UI', system-ui, -apple-system, Roboto, Arial, sans-serif";
    const c = document.createElement("canvas");
    let g = c.getContext("2d");
    g.font = font;
    c.width = Math.ceil(g.measureText(text).width + 6 * scale);
    c.height = Math.ceil(size * scale * 1.5);
    g = c.getContext("2d");
    g.font = font;
    g.fillStyle = cssValue;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(text, c.width / 2, c.height / 2);
    const texture = new THREE.CanvasTexture(c);
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
    return { texture, w: c.width / scale, h: c.height / scale };
  }
  function flatText(text, size, cssValue, x, z, weight) {
    const t = textCanvas(text, size, cssValue, weight);
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(t.w, t.h),
      new THREE.MeshBasicMaterial({ map: t.texture, transparent: true, depthWrite: false }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(x, 0.6, z);
    return mesh;
  }
  function standingText(text, size, cssValue, x, y, z) {
    const t = textCanvas(text, size, cssValue, 400);
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(t.w, t.h),
      new THREE.MeshBasicMaterial({ map: t.texture, transparent: true, depthWrite: false }));
    mesh.position.set(x, y, z);
    return mesh;
  }
  function spriteText(text, size, cssValue, x, y, z) {
    const t = textCanvas(text, size, cssValue, 650);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: t.texture, depthWrite: false }));
    sprite.scale.set(t.w, t.h, 1);
    sprite.position.set(x, y, z);
    return sprite;
  }

  // An open box: floor, back and side walls, and a low front wall so the parts inside stay visible.
  function openBox(group, cx, width, height, depth, wallMat, floorMat, frontHeight) {
    const t = 3, floor = 6, x = wx(cx);
    // The floor sits inside the walls. A floor as wide as the box would share its outer faces with the walls,
    // and two faces in one plane flicker (z-fighting) when the view turns.
    group.add(box(width - 2 * t, floor, depth - 2 * t, floorMat, x, floor / 2, 0, false));
    group.add(box(width, height, t, wallMat, x, height / 2, -depth / 2 + t / 2));
    group.add(box(t, height, depth, wallMat, x - width / 2 + t / 2, height / 2, 0));
    group.add(box(t, height, depth, wallMat, x + width / 2 - t / 2, height / 2, 0));
    group.add(box(width, frontHeight, t, wallMat, x, frontHeight / 2, depth / 2 - t / 2));
  }

  function drawStatic() {
    clear(staticGroup);
    const ink = token("--ink"), muted = token("--muted");
    const steel = solid(colour("--steel"), { metalness: 0.35, roughness: 0.45 });
    const pocket = solid(colour("--pocket"));
    // The table and the tray get some of the steel colour, so they stand out from the page in light mode too.
    const dark = colour("--bg").getHSL({}).l < 0.5;
    const tray = solid(colour("--tray").lerp(colour("--steel"), dark ? 0.25 : 0.5));
    // Table
    staticGroup.add(box(L.W - 40, 14, 300, solid(colour("--table").lerp(colour("--steel"), dark ? 0.2 : 0.6), { roughness: 0.9 }),
      0, -7.8, 0, false));  // top just below 0, so the bins, tray and pad never share a face with it (no flicker)
    // Gantry: two posts at the back and the rail the arm runs on
    const postH = hy(L.RAIL - 20);
    staticGroup.add(box(14, postH, 14, steel, wx(31), postH / 2, BACK));
    staticGroup.add(box(14, postH, 14, steel, wx(L.W - 31), postH / 2, BACK));
    staticGroup.add(box(L.W - 62, 12, 14, steel, 0, hy(L.RAIL), BACK));
    // HOME
    staticGroup.add(box(60, 4, 60, steel, wx(L.X.HOME), 2, 0));
    staticGroup.add(flatText("HOME", 17, ink, wx(L.X.HOME), 76));
    // Bins
    for (const b of L.bins) {
      openBox(staticGroup, L.X[b], 84, L.BIN_H, 84, steel, pocket, 22);
      staticGroup.add(flatText(b, 17, ink, wx(L.X[b]), 76));
    }
    if (L.bins.length) {
      const mid = (L.X[L.bins[0]] + L.X[L.bins[L.bins.length - 1]]) / 2;
      staticGroup.add(flatText("P A R T   B I N S", 13, muted, wx(mid), 106, 400));
    }
    // Kit tray: a base, a back wall, dividers between the pockets and a low front lip
    const trayTop = hy(L.TABLE - L.POCKET_H - 10), floorTop = hy(L.TABLE - 8);
    const left = wx(L.trayLeft), right = wx(L.trayRight), depth = 96;
    staticGroup.add(box(right - left, floorTop, depth, tray, (left + right) / 2, floorTop / 2, 0, false));
    staticGroup.add(box(right - left, trayTop, 6, tray, (left + right) / 2, trayTop / 2, -depth / 2 + 3));
    staticGroup.add(box(right - left, 20, 6, tray, (left + right) / 2, 10, depth / 2 - 3));
    const walls = [L.trayLeft, ...L.slots.slice(0, -1).map(s => L.X[s] + 48), L.trayRight];
    walls.forEach((wallX, i) => {
      const w = i === 0 || i === walls.length - 1 ? 10 : 12;
      const cx = i === 0 ? wallX + 5 : i === walls.length - 1 ? wallX - 5 : wallX;
      staticGroup.add(box(w, trayTop, depth, tray, wx(cx), trayTop / 2, 0));
    });
    const levelY = hy(L.TABLE - 8 - L.LEVEL);
    for (const s of L.slots) {
      const x = wx(L.X[s]);
      const floor = new THREE.Mesh(new THREE.PlaneGeometry(84, 84), pocket);
      floor.rotation.x = -Math.PI / 2;
      floor.position.set(x, floorTop + 0.4, 0);
      floor.receiveShadow = true;
      staticGroup.add(floor);
      // The line between the base and the top level, on the back wall of the pocket
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x - 38, levelY, -41.5),
        new THREE.Vector3(x + 38, levelY, -41.5)]), new THREE.LineDashedMaterial({ color: colour("--steel"), dashSize: 4, gapSize: 4 }));
      line.computeLineDistances();
      staticGroup.add(line);
      staticGroup.add(flatText(s, 17, ink, x, 76));
      if (L.protectedSlots.has(s)) {
        const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(84, trayTop - floorTop + 4, 84)),
          new THREE.LineDashedMaterial({ color: colour("--protect"), dashSize: 7, gapSize: 5 }));
        frame.position.set(x, (trayTop + floorTop + 4) / 2, 0);
        frame.computeLineDistances();
        staticGroup.add(frame);
        const glow = new THREE.Mesh(new THREE.PlaneGeometry(84, 84),
          new THREE.MeshBasicMaterial({ color: colour("--protect"), transparent: true, opacity: 0.18, depthWrite: false }));
        glow.rotation.x = -Math.PI / 2;
        glow.position.set(x, floorTop + 0.8, 0);
        staticGroup.add(glow);
        staticGroup.add(spriteText("keep unchanged", 14, token("--protect"), x, trayTop + 34, 0));
      }
    }
    if (L.slots.length) {
      staticGroup.add(standingText("base", 12, muted, left - 16, floorTop + L.LEVEL / 2, 20));
      staticGroup.add(standingText("top", 12, muted, left - 16, levelY + L.LEVEL / 2, 20));
      staticGroup.add(flatText("K I T   T R A Y", 13, muted, (left + right) / 2, 106, 400));
    }
    // Return position
    openBox(staticGroup, L.X.RETURN, 80, L.BIN_H, 84, steel, pocket, 22);
    staticGroup.add(flatText("RETURN", 17, ink, wx(L.X.RETURN), 76));
    render();
  }

  // Parts: spacers are sleeves lying along the cell, the bolt stands with its hexagon head up.
  function partMesh(name) {
    const p = L.partInfo(name);
    const c = cssColour(p.color);
    const g = new THREE.Group();
    if (p.bolt) {
      const metal = solid(c, { metalness: 0.6, roughness: 0.35 });
      const head = new THREE.Mesh(new THREE.CylinderGeometry(p.w / 2, p.w / 2, 9, 6), metal);
      head.position.y = p.h / 2 - 4.5;
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(7, 7, p.h - 9, 20), metal);
      shaft.position.y = -4.5;
      g.add(head, shaft);
    } else {
      const sleeve = new THREE.Mesh(new THREE.CylinderGeometry(p.h / 2, p.h / 2, p.w, 32), solid(c, { roughness: 0.45, metalness: 0.1 }));
      sleeve.rotation.z = Math.PI / 2;
      const hole = new THREE.Mesh(new THREE.CylinderGeometry(p.h / 4, p.h / 4, p.w + 0.6, 20),
        new THREE.MeshBasicMaterial({ color: 0x1d232b }));
      hole.rotation.z = Math.PI / 2;
      g.add(sleeve, hole);
    }
    g.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    return g;
  }

  let lastState = null;
  function drawParts(state) {
    lastState = state;
    clear(partGroup);
    const put = (pos, list, step) => list.forEach((name, i) => {
      const p = L.partInfo(name);
      const mesh = partMesh(name);
      mesh.position.set(wx(L.X[pos]), hy(L.bottomOf(pos) - i * step - p.h / 2), 0);
      partGroup.add(mesh);
    });
    for (const b of L.bins) put(b, state.bins[b] || [], 26);
    for (const s of L.slots) put(s, state.slots[s] || [], L.LEVEL);
    put("RETURN", state.return || [], 26);
    render();
  }

  // The arm: a carriage on the rail, a beam to the front, a column and the gripper. drawArm only moves it.
  const arm = {};
  function buildArm() {
    clear(armGroup);
    const dark = solid(colour("--steel-dark"), { metalness: 0.4, roughness: 0.4 });
    const light = solid(colour("--steel"), { metalness: 0.45, roughness: 0.35 });
    arm.carriage = box(68, 32, 30, dark, 0, hy(L.RAIL), BACK + 20);
    arm.beam = box(16, 14, -BACK - 4, dark, 0, hy(L.RAIL) - 4, BACK / 2);
    arm.column = box(12, 1, 12, light, 0, 0, 0);
    arm.bar = box(60, 10, 26, dark, 0, 0, 0);
    arm.left = box(5, 18, 20, dark, 0, 0, 0);
    arm.right = box(5, 18, 20, dark, 0, 0, 0);
    armGroup.add(arm.carriage, arm.beam, arm.column, arm.bar, arm.left, arm.right);
    arm.held = null;
    arm.heldName = null;
  }
  let lastArm = null;
  function drawArm(ax, ay, holding) {
    lastArm = [ax, ay, holding];
    const x = wx(ax);
    const top = hy(L.RAIL) - 10, barTop = hy(ay - 12);
    arm.carriage.position.x = x;
    arm.beam.position.x = x;
    arm.column.scale.y = Math.max(1, top - barTop);
    arm.column.position.set(x, (top + barTop) / 2, 0);
    arm.bar.position.set(x, hy(ay - 7), 0);
    const open = holding ? L.partInfo(holding).w / 2 + 4 : 24;
    arm.left.position.set(x - open - 2.5, hy(ay + 5), 0);
    arm.right.position.set(x + open + 2.5, hy(ay + 5), 0);
    if (arm.heldName !== (holding || null)) {
      if (arm.held) { const old = new THREE.Group(); old.add(arm.held); clear(old); }
      arm.held = holding ? partMesh(holding) : null;
      arm.heldName = holding || null;
      if (arm.held) armGroup.add(arm.held);
    }
    if (arm.held) arm.held.position.set(x, hy(ay + 12 + L.partInfo(holding).h / 2), 0);
    render();
  }

  // The red (rejected) or amber (question) frame around a position
  function drawFlag(pos, kind) {
    clear(flagGroup);
    if (!pos || L.X[pos] === undefined) { render(); return; }
    const c = colour(kind === "reject" ? "--reject" : "--ask");
    const x = wx(L.X[pos]), y = 48, w = 100, h = 100, d = 106, t = 3;
    // WebGL draws lines one pixel wide, so the frame is made of thin bars that stay visible from any angle.
    const bar = new THREE.MeshBasicMaterial({ color: c });
    for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
      flagGroup.add(new THREE.Mesh(new THREE.BoxGeometry(w + t, t, t), bar).translateX(x).translateY(y + sy * h / 2).translateZ(sz * d / 2));
    }
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      flagGroup.add(new THREE.Mesh(new THREE.BoxGeometry(t, h + t, t), bar).translateX(x + sx * w / 2).translateY(y).translateZ(sz * d / 2));
    }
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
      flagGroup.add(new THREE.Mesh(new THREE.BoxGeometry(t, t, d + t), bar).translateX(x + sx * w / 2).translateY(y + sy * h / 2));
    }
    const fill = new THREE.Mesh(new THREE.BoxGeometry(w, h, d),
      new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.2, depthWrite: false }));
    fill.position.set(x, y, 0);
    flagGroup.add(fill);
    render();
  }

  // Camera: drag to turn, Ctrl + scroll to zoom, double-click to go back to the first view
  const target = new THREE.Vector3(0, 100, 10);
  const HOME_VIEW = { theta: -0.12, phi: 1.02, radius: L.W * 0.95 };
  const view = Object.assign({}, HOME_VIEW);
  function placeCamera() {
    const s = Math.sin(view.phi);
    camera.position.set(target.x + view.radius * s * Math.sin(view.theta), target.y + view.radius * Math.cos(view.phi),
      target.z + view.radius * s * Math.cos(view.theta));
    camera.lookAt(target);
    render();
  }
  const canvas = renderer.domElement;
  let drag = null;
  canvas.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", e => {
    if (!drag) return;
    view.theta -= (e.clientX - drag.x) * 0.006;
    view.phi = Math.min(1.45, Math.max(0.2, view.phi - (e.clientY - drag.y) * 0.006));
    drag = { x: e.clientX, y: e.clientY };
    placeCamera();
  });
  const endDrag = () => { drag = null; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("wheel", e => {
    if (!e.ctrlKey) return;  // a plain scroll keeps scrolling the page
    e.preventDefault();
    view.radius = Math.min(L.W * 2, Math.max(L.W * 0.4, view.radius * (e.deltaY > 0 ? 1.1 : 1 / 1.1)));
    placeCamera();
  }, { passive: false });
  canvas.addEventListener("dblclick", () => { Object.assign(view, HOME_VIEW); placeCamera(); });

  // Draw at most once per frame, and only when something changed
  let pending = false;
  function render() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; if (canvas.width) renderer.render(scene, camera); });
  }
  function resize() {
    const w = host.clientWidth;
    if (!w) return;
    const h = Math.max(240, Math.round(w / ASPECT));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    render();
  }
  if (typeof ResizeObserver === "function") new ResizeObserver(resize).observe(host);
  window.addEventListener("resize", resize);

  // Light or dark mode changed: draw everything again in the new colours
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      drawStatic();
      buildArm();
      if (lastState) drawParts(lastState);
      if (lastArm) drawArm(...lastArm);
    });
  }

  buildArm();
  placeCamera();
  resize();
  return { drawStatic, drawParts, drawArm, drawFlag, resize };
}
