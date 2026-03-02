/* ================================================================
 *  satellite3d.js — Three.js 3D Satellite Detail View
 *  Responds to DT controls: wingCount, wingArea, radCount, radArea
 * ================================================================ */

const Detail3D = (function () {
  let scene, camera, renderer, controls;
  let satGroup, container;
  let autoRotate = true;
  let rotY = 0;

  /* ---------- Material palette ---------- */
  const MAT = {
    body:   () => new THREE.MeshStandardMaterial({ color: 0xb8860b, metalness: 0.65, roughness: 0.28, emissive: 0x0a0800 }),
    panel:  () => new THREE.MeshStandardMaterial({ color: 0x1a3060, metalness: 0.35, roughness: 0.45, emissive: 0x000a22 }),
    panelDark: () => new THREE.MeshStandardMaterial({ color: 0x0c1020, metalness: 0.2, roughness: 0.7, emissive: 0x000005 }),
    cell:   (bright) => new THREE.MeshStandardMaterial({
      color: new THREE.Color(0.14 + bright * 0.25, 0.30 + bright * 0.35, 0.09 + bright * 0.06),
      metalness: 0.25, roughness: 0.55
    }),
    arm:    () => new THREE.MeshStandardMaterial({ color: 0x556677, metalness: 0.55, roughness: 0.35 }),
    rad:    () => new THREE.MeshStandardMaterial({ color: 0xcc3300, metalness: 0.18, roughness: 0.55, emissive: 0x220500 }),
    radHot: () => new THREE.MeshStandardMaterial({ color: 0xff6600, metalness: 0.18, roughness: 0.55, emissive: 0x441000 }),
    pipe:   () => new THREE.MeshStandardMaterial({ color: 0x884422, metalness: 0.5, roughness: 0.4 }),
    ant:    () => new THREE.MeshStandardMaterial({ color: 0x778899, metalness: 0.55, roughness: 0.35 }),
    led:    (c) => new THREE.MeshBasicMaterial({ color: c }),
    mli:    () => new THREE.MeshStandardMaterial({ color: 0xd4a820, metalness: 0.75, roughness: 0.22, emissive: 0x0a0800 }),
  };

  /* ---------- Build a solar cell grid on a wing ---------- */
  function buildSolarCells(parent, wx, wy, wz, wW, wH, wD, cols, rows) {
    const cw = wW / cols, cd = wD / rows;
    for (let c = 0; c < cols; c++) {
      for (let r = 0; r < rows; r++) {
        const cGeo = new THREE.BoxGeometry(cw * 0.92, wH * 1.01, cd * 0.92);
        const bright = 0.3 + Math.random() * 0.7;
        const cell = new THREE.Mesh(cGeo, MAT.cell(bright));
        cell.position.set(
          wx + (c + 0.5) * cw - wW / 2,
          wy,
          wz + (r + 0.5) * cd - wD / 2
        );
        parent.add(cell);
      }
    }
  }

  /* ---------- Build full satellite model ---------- */
  function buildSatellite() {
    const g = new THREE.Group();

    // Dynamic sizing
    const bodyW = 0.5, bodyH = 0.35, bodyD = 0.6;
    const wingW = Math.max(0.8, Math.min(2.5, (wingArea / 350) * 1.6));
    const wingD = 0.35;
    const wingH = 0.012;
    const wingsPerSide = Math.ceil(wingCount / 2);
    const wingGap = 0.06;
    const armLen = 0.15;

    const radW = 0.22;
    const radD = Math.max(0.3, Math.min(1.0, (radArea / 143) * 0.6));
    const radH = 0.01;
    const radsPerSide = Math.ceil(radCount / 2);
    const radGap = 0.04;

    /* --- Spacecraft body --- */
    const bodyGeo = new THREE.BoxGeometry(bodyW, bodyH, bodyD);
    const body = new THREE.Mesh(bodyGeo, MAT.body());
    g.add(body);

    // Body panel lines (edges)
    const edges = new THREE.EdgesGeometry(bodyGeo);
    const edgeLine = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x00aadd, transparent: true, opacity: 0.3 }));
    g.add(edgeLine);

    // MLI gold foil detail: thin slightly larger box
    const mliGeo = new THREE.BoxGeometry(bodyW * 1.005, bodyH * 1.005, bodyD * 1.005);
    const mli = new THREE.Mesh(mliGeo, new THREE.MeshStandardMaterial({
      color: 0xd4a820, metalness: 0.8, roughness: 0.2, transparent: true, opacity: 0.25,
      side: THREE.FrontSide
    }));
    g.add(mli);

    /* --- Solar wings --- */
    for (const side of [-1, 1]) {
      const nThisSide = side > 0 ? Math.ceil(wingCount / 2) : Math.floor(wingCount / 2);
      if (nThisSide === 0) continue;

      // Arm
      const aGeo = new THREE.BoxGeometry(armLen, 0.03, 0.03);
      const arm = new THREE.Mesh(aGeo, MAT.arm());
      arm.position.x = side * (bodyW / 2 + armLen / 2);
      g.add(arm);

      for (let wi = 0; wi < nThisSide; wi++) {
        const stackH = nThisSide * wingD + (nThisSide - 1) * wingGap;
        const wz = -stackH / 2 + wi * (wingD + wingGap) + wingD / 2;

        // Wing base plate
        const wGeo = new THREE.BoxGeometry(wingW, wingH, wingD);
        const wing = new THREE.Mesh(wGeo, MAT.panel());
        wing.position.set(side * (bodyW / 2 + armLen + wingW / 2), 0, wz);
        g.add(wing);

        // Solar cells on wing
        const cols = Math.max(3, Math.min(8, Math.round(wingW / 0.22)));
        const rows = Math.max(2, Math.min(4, Math.round(wingD / 0.12)));
        buildSolarCells(g,
          side * (bodyW / 2 + armLen + wingW / 2), wingH / 2 + 0.002,
          wz, wingW, 0.004, wingD, cols, rows
        );

        // Wing edge highlight
        const wEdge = new THREE.EdgesGeometry(wGeo);
        const wLine = new THREE.LineSegments(wEdge, new THREE.LineBasicMaterial({ color: 0x4488cc, transparent: true, opacity: 0.3 }));
        wLine.position.copy(wing.position);
        g.add(wLine);
      }
    }

    /* --- Radiator panels --- */
    for (const side of [-1, 1]) {
      const nThisSide = side > 0 ? Math.ceil(radCount / 2) : Math.floor(radCount / 2);
      if (nThisSide === 0) continue;

      for (let ri = 0; ri < nThisSide; ri++) {
        const stackH = nThisSide * radD + (nThisSide - 1) * radGap;
        const rz = -stackH / 2 + ri * (radD + radGap) + radD / 2;

        // Radiator panel
        const rGeo = new THREE.BoxGeometry(radW, radH, radD);
        const radPanel = new THREE.Mesh(rGeo, MAT.rad());
        radPanel.position.set(side * (bodyW / 2 + radW / 2), -bodyH / 2 - 0.04, rz);
        g.add(radPanel);

        // Heat pipes on radiator
        const numPipes = Math.max(2, Math.min(5, Math.round(radD / 0.12)));
        for (let pi = 0; pi < numPipes; pi++) {
          const pipeZ = rz - radD / 2 + (pi + 1) * (radD / (numPipes + 1));
          const pGeo = new THREE.CylinderGeometry(0.006, 0.006, radW * 0.9, 6);
          const pipe = new THREE.Mesh(pGeo, MAT.pipe());
          pipe.rotation.z = Math.PI / 2;
          pipe.position.set(side * (bodyW / 2 + radW / 2), -bodyH / 2 - 0.04 + radH / 2 + 0.004, pipeZ);
          g.add(pipe);
        }

        // Radiator edge glow
        const rEdge = new THREE.EdgesGeometry(rGeo);
        const rLine = new THREE.LineSegments(rEdge, new THREE.LineBasicMaterial({ color: 0xff4400, transparent: true, opacity: 0.35 }));
        rLine.position.copy(radPanel.position);
        g.add(rLine);
      }
    }

    /* --- Antenna + dish --- */
    const antGeo = new THREE.CylinderGeometry(0.008, 0.008, 0.2, 8);
    const ant = new THREE.Mesh(antGeo, MAT.ant());
    ant.position.y = bodyH / 2 + 0.1;
    g.add(ant);

    const dishGeo = new THREE.ConeGeometry(0.06, 0.05, 16);
    const dish = new THREE.Mesh(dishGeo, MAT.ant());
    dish.position.y = bodyH / 2 + 0.23;
    dish.rotation.x = Math.PI;
    g.add(dish);

    // Small parabolic mesh (wireframe cone)
    const wireGeo = new THREE.ConeGeometry(0.058, 0.048, 16);
    const wireframe = new THREE.LineSegments(
      new THREE.EdgesGeometry(wireGeo),
      new THREE.LineBasicMaterial({ color: 0x667788, transparent: true, opacity: 0.4 })
    );
    wireframe.position.y = bodyH / 2 + 0.23;
    wireframe.rotation.x = Math.PI;
    g.add(wireframe);

    /* --- Status LEDs --- */
    [{ pos: [0, bodyH / 2 + 0.01, bodyD / 2 + 0.01], color: 0x00ff88, name: 'led_top' },
     { pos: [bodyW / 2 + 0.01, 0, 0], color: 0x0088ff, name: 'led_side' },
     { pos: [0, -bodyH / 2 - 0.01, 0], color: 0xff4400, name: 'led_bottom' }
    ].forEach(l => {
      const ledGeo = new THREE.SphereGeometry(0.015, 8, 8);
      const led = new THREE.Mesh(ledGeo, MAT.led(l.color));
      led.position.set(...l.pos);
      led.name = l.name;
      g.add(led);
    });

    /* --- Thruster nozzles --- */
    [-1, 1].forEach(side => {
      const nozzleGeo = new THREE.CylinderGeometry(0.015, 0.025, 0.04, 8);
      const nozzle = new THREE.Mesh(nozzleGeo, new THREE.MeshStandardMaterial({
        color: 0x445566, metalness: 0.7, roughness: 0.3
      }));
      nozzle.position.set(side * (bodyW / 2 - 0.04), 0, -bodyD / 2 - 0.02);
      nozzle.rotation.x = Math.PI / 2;
      g.add(nozzle);
    });

    return g;
  }

  /* ---------- Create annotation sprites ---------- */
  function createLabel(text, color, fontSize) {
    const cv = document.createElement('canvas');
    cv.width = 512; cv.height = 64;
    const ctx = cv.getContext('2d');
    ctx.font = `bold ${fontSize || 22}px Share Tech Mono, monospace`;
    ctx.fillStyle = color || 'rgba(0,212,255,0.8)';
    ctx.textAlign = 'center';
    ctx.fillText(text, 256, 40);
    const tex = new THREE.CanvasTexture(cv);
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
    const sp = new THREE.Sprite(mat);
    sp.scale.set(2, 0.25, 1);
    return sp;
  }

  /* ========== PUBLIC: init ========== */
  function init() {
    container = document.getElementById('detail3dContainer');
    if (!container) return;

    scene = new THREE.Scene();

    const aspect = container.clientWidth / Math.max(1, container.clientHeight);
    camera = new THREE.PerspectiveCamera(40, aspect, 0.01, 100);
    camera.position.set(1.8, 1.2, 2.8);
    camera.lookAt(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    renderer.domElement.style.display = 'block';
    container.appendChild(renderer.domElement);

    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.minDistance = 1.0;
    controls.maxDistance = 8;
    controls.target.set(0, 0, 0);
    controls.enablePan = false;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.2;

    /* --- Lighting --- */
    const mainLight = new THREE.DirectionalLight(0xfff8e0, 2.2);
    mainLight.position.set(-5, 4, 6);
    mainLight.name = 'mainLight';
    scene.add(mainLight);

    const fillLight = new THREE.DirectionalLight(0x4488ff, 0.3);
    fillLight.position.set(5, -2, -3);
    scene.add(fillLight);

    scene.add(new THREE.AmbientLight(0x182244, 0.4));
    scene.add(new THREE.HemisphereLight(0x4488ff, 0x110000, 0.15));

    /* --- Stars background --- */
    const stGeo = new THREE.BufferGeometry();
    const stVerts = [];
    for (let i = 0; i < 1500; i++) {
      const r = 30 + Math.random() * 30;
      const t = Math.random() * Math.PI * 2;
      const p = Math.acos(2 * Math.random() - 1);
      stVerts.push(r * Math.sin(p) * Math.cos(t), r * Math.sin(p) * Math.sin(t), r * Math.cos(p));
    }
    stGeo.setAttribute('position', new THREE.Float32BufferAttribute(stVerts, 3));
    scene.add(new THREE.Points(stGeo, new THREE.PointsMaterial({
      color: 0xccddff, size: 0.12, transparent: true, opacity: 0.7, depthWrite: false
    })));

    /* --- Build satellite --- */
    satGroup = buildSatellite();
    scene.add(satGroup);

    /* --- Labels --- */
    const titleLabel = createLabel('SPACECRAFT DETAIL · ORBITAL DC-1', 'rgba(0,180,255,0.6)', 20);
    titleLabel.position.set(0, 1.5, 0);
    scene.add(titleLabel);

    /* --- Annotation labels --- */
    rebuildLabels();
  }

  /* ---------- Rebuild annotation labels ---------- */
  function rebuildLabels() {
    // Remove old labels
    scene.children.filter(c => c.userData.isAnnotation).forEach(c => scene.remove(c));

    const bodyW = 0.5;
    const armLen = 0.15;
    const wingW = Math.max(0.8, Math.min(2.5, (wingArea / 350) * 1.6));
    const tech = CELL_TECHS[currentCellTech];

    // Solar wing label
    const solarLabel = createLabel(`◄ SOLAR · ${wingCount} wings · ${tech.name}`, 'rgba(255,220,50,0.85)', 18);
    solarLabel.position.set(-(bodyW / 2 + armLen + wingW / 2), 0.5, 0);
    solarLabel.userData.isAnnotation = true;
    scene.add(solarLabel);

    // Radiator label
    const cool = COOLANTS[currentCoolant];
    const radLabel = createLabel(`RADIATOR · ${radCount} panels · ${cool.name} ►`, 'rgba(255,80,0,0.85)', 18);
    radLabel.position.set(0.5, -0.6, 0);
    radLabel.userData.isAnnotation = true;
    scene.add(radLabel);
  }

  /* ========== PUBLIC: rebuild ========== */
  function rebuild() {
    if (!scene || !satGroup) return;
    scene.remove(satGroup);
    satGroup = buildSatellite();
    scene.add(satGroup);
    rebuildLabels();
  }

  /* ========== PUBLIC: update ========== */
  function update(eclipse) {
    if (!renderer) return;

    // Eclipse mode: dim lights
    const mainLight = scene.getObjectByName('mainLight');
    if (mainLight) {
      mainLight.intensity = eclipse ? 0.15 : 2.2;
    }

    // LED blink
    const t = performance.now() * 0.003;
    const ledTop = satGroup.getObjectByName('led_top');
    if (ledTop) ledTop.material.color.setHex(eclipse ? 0x6688ff : 0x00ff88);
    const ledSide = satGroup.getObjectByName('led_side');
    if (ledSide) ledSide.visible = Math.sin(t * 2) > 0;
    const ledBottom = satGroup.getObjectByName('led_bottom');
    if (ledBottom) {
      const glow = eclipse ? 0.1 : 0.5 + Math.sin(t) * 0.3;
      ledBottom.material.color.setRGB(1.0, glow * 0.3, 0);
    }

    // Resize
    const w = container.clientWidth, h = container.clientHeight;
    if (w > 0 && h > 0) {
      const pr = renderer.getPixelRatio();
      const cw = renderer.domElement.width, ch = renderer.domElement.height;
      if (Math.abs(cw - w * pr) > 1 || Math.abs(ch - h * pr) > 1) {
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      }
    }

    controls.update();
    renderer.render(scene, camera);
  }

  /* ========== PUBLIC: resize ========== */
  function resize() {
    if (!renderer || !container) return;
    const w = container.clientWidth, h = container.clientHeight;
    if (w > 0 && h > 0) {
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  }

  return { init, update, resize, rebuild };
})();
