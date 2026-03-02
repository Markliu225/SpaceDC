/* ================================================================
 *  orbit3d.js — Three.js 3D Orbit Scene (Earth + Satellite + Sun)
 * ================================================================ */

const Orbit3D = (function () {
  let scene, camera, renderer, controls;
  let earth, clouds, satellite, orbitLine, sunLight, sunMesh;
  let starField, atmosGlow;
  let container;
  let earthRotY = 0;

  /* ---------- Simple value-noise for procedural textures ---------- */
  function _hash(x, y) {
    let h = (x * 374761393 + y * 668265263) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }
  function _smooth(x, y) {
    const ix = Math.floor(x), iy = Math.floor(y);
    const fx = x - ix, fy = y - iy;
    const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    return (_hash(ix, iy) * (1 - sx) + _hash(ix + 1, iy) * sx) * (1 - sy) +
           (_hash(ix, iy + 1) * (1 - sx) + _hash(ix + 1, iy + 1) * sx) * sy;
  }
  function _fbm(x, y, oct) {
    let v = 0, a = 0.5, f = 1;
    for (let i = 0; i < oct; i++) { v += _smooth(x * f, y * f) * a; a *= 0.5; f *= 2.0; }
    return v;
  }

  /* ---------- Procedural Earth texture ---------- */
  function createEarthTexture() {
    const W = 1024, H = 512;
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    const img = ctx.createImageData(W, H);
    const d = img.data;
    for (let py = 0; py < H; py++) {
      for (let px = 0; px < W; px++) {
        const i = (py * W + px) * 4;
        const u = px / W, v = py / H;
        const lat = (v - 0.5) * Math.PI;
        const lon = u * Math.PI * 2;
        const nx = Math.cos(lat) * Math.cos(lon);
        const ny = Math.sin(lat);
        const nz = Math.cos(lat) * Math.sin(lon);

        const elev = _fbm(nx * 3 + 10, nz * 3 + 20, 6) +
                     _fbm(ny * 2 + nx * 2 + 5, nz * 2 + ny + 8, 4) * 0.5;
        const seaLevel = 0.42;
        const isPolar = Math.abs(lat) > 1.15;
        const polarBlend = Math.max(0, (Math.abs(lat) - 1.15) / 0.42);
        let r, g, b;
        if (elev > seaLevel) {
          const h2 = (elev - seaLevel) / (1 - seaLevel);
          if (h2 < 0.3)      { r = 34 + h2 * 80;  g = 120 + h2 * 60; b = 45 + h2 * 30; }
          else if (h2 < 0.6) { r = 80 + h2 * 80;  g = 140 + h2 * 20; b = 55; }
          else                { r = 130 + h2 * 50; g = 115 + h2 * 30; b = 75 + h2 * 20; }
          if (Math.abs(lat) < 0.4 && elev < 0.55) {
            r = r * 0.6 + 180 * 0.4; g = g * 0.6 + 160 * 0.4; b = b * 0.6 + 100 * 0.4;
          }
        } else {
          const depth = (seaLevel - elev) / seaLevel;
          r = 10 + (1 - depth) * 25; g = 40 + (1 - depth) * 50; b = 100 + (1 - depth) * 70;
          if (depth < 0.3) { r += 15; g += 25; b += 20; }
        }
        if (isPolar) { r = r * (1 - polarBlend) + 230 * polarBlend; g = g * (1 - polarBlend) + 235 * polarBlend; b = b * (1 - polarBlend) + 245 * polarBlend; }
        if (elev > 0.72 && !isPolar) {
          const sn = (elev - 0.72) / 0.28;
          r = r * (1 - sn * 0.5) + 220 * sn * 0.5; g = g * (1 - sn * 0.5) + 225 * sn * 0.5; b = b * (1 - sn * 0.5) + 235 * sn * 0.5;
        }
        const jit = (_hash(px * 7, py * 7) - 0.5) * 12;
        d[i] = Math.max(0, Math.min(255, r + jit));
        d[i + 1] = Math.max(0, Math.min(255, g + jit));
        d[i + 2] = Math.max(0, Math.min(255, b + jit));
        d[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(cv);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }

  /* ---------- Cloud texture ---------- */
  function createCloudTexture() {
    const W = 512, H = 256;
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    const img = ctx.createImageData(W, H);
    const d = img.data;
    for (let py = 0; py < H; py++) {
      for (let px = 0; px < W; px++) {
        const i = (py * W + px) * 4;
        const n = _fbm(px * 0.018 + 100, py * 0.022 + 100, 5);
        const cloud = Math.max(0, (n - 0.38) * 3.2);
        d[i] = d[i + 1] = d[i + 2] = 255;
        d[i + 3] = Math.min(255, cloud * 170);
      }
    }
    ctx.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(cv);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }

  /* ---------- Atmosphere glow shader ---------- */
  function createAtmosphereMesh(radius) {
    const geo = new THREE.SphereGeometry(radius, 64, 64);
    const mat = new THREE.ShaderMaterial({
      vertexShader: `
        varying vec3 vNormal;
        varying vec3 vPosition;
        void main(){
          vNormal = normalize(normalMatrix * normal);
          vPosition = vec3(modelViewMatrix * vec4(position,1.0));
          gl_Position = projectionMatrix * vec4(vPosition,1.0);
        }`,
      fragmentShader: `
        varying vec3 vNormal;
        varying vec3 vPosition;
        uniform float intensity;
        uniform vec3 glowColor;
        void main(){
          vec3 viewDir = normalize(-vPosition);
          float rim = 1.0 - max(dot(viewDir, vNormal), 0.0);
          float glow = pow(rim, 3.0) * intensity;
          gl_FragColor = vec4(glowColor, glow * 0.75);
        }`,
      uniforms: {
        intensity: { value: 1.6 },
        glowColor: { value: new THREE.Color(0.3, 0.6, 1.0) }
      },
      side: THREE.BackSide,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    return new THREE.Mesh(geo, mat);
  }

  /* ---------- Star field ---------- */
  function createStars() {
    const geo = new THREE.BufferGeometry();
    const verts = [], colors = [];
    for (let i = 0; i < 3000; i++) {
      const r = 60 + Math.random() * 80;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      verts.push(r * Math.sin(phi) * Math.cos(theta), r * Math.sin(phi) * Math.sin(theta), r * Math.cos(phi));
      const c = 0.7 + Math.random() * 0.3;
      colors.push(c, c, 0.8 + Math.random() * 0.2);
    }
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    return new THREE.Points(geo, new THREE.PointsMaterial({
      size: 0.18, vertexColors: true, transparent: true, opacity: 0.85, depthWrite: false
    }));
  }

  /* ---------- Small satellite for orbit view ---------- */
  function createSatelliteModel() {
    const g = new THREE.Group();

    // Body — golden MLI
    const bodyGeo = new THREE.BoxGeometry(0.14, 0.10, 0.16);
    const bodyMat = new THREE.MeshStandardMaterial({
      color: 0xb8860b, metalness: 0.6, roughness: 0.35, emissive: 0x111100
    });
    g.add(new THREE.Mesh(bodyGeo, bodyMat));

    // Solar panels (2 wings, each side)
    const panelMat = new THREE.MeshStandardMaterial({
      color: 0x1a3060, metalness: 0.3, roughness: 0.5, emissive: 0x000a22
    });
    [-1, 1].forEach(side => {
      const pGeo = new THREE.BoxGeometry(0.32, 0.006, 0.12);
      const p = new THREE.Mesh(pGeo, panelMat);
      p.position.x = side * 0.25;
      g.add(p);
      // arm
      const aGeo = new THREE.BoxGeometry(0.08, 0.012, 0.012);
      const arm = new THREE.Mesh(aGeo, new THREE.MeshStandardMaterial({ color: 0x556677, metalness: 0.5, roughness: 0.4 }));
      arm.position.x = side * 0.11;
      g.add(arm);
    });

    // Radiator stubs (red)
    const radMat = new THREE.MeshStandardMaterial({ color: 0xcc3300, metalness: 0.2, roughness: 0.6, emissive: 0x220500 });
    [-1, 1].forEach(side => {
      const rGeo = new THREE.BoxGeometry(0.04, 0.006, 0.10);
      const r = new THREE.Mesh(rGeo, radMat);
      r.position.set(side * 0.10, -0.06, 0);
      g.add(r);
    });

    // Antenna
    const antMat = new THREE.MeshStandardMaterial({ color: 0x778899, metalness: 0.5, roughness: 0.4 });
    const antGeo = new THREE.CylinderGeometry(0.004, 0.004, 0.10, 8);
    const ant = new THREE.Mesh(antGeo, antMat);
    ant.position.y = 0.10;
    g.add(ant);
    const dishGeo = new THREE.ConeGeometry(0.03, 0.025, 12);
    const dish = new THREE.Mesh(dishGeo, antMat);
    dish.position.y = 0.16;
    dish.rotation.x = Math.PI;
    g.add(dish);

    // Status LED
    const ledGeo = new THREE.SphereGeometry(0.012, 8, 8);
    const ledMat = new THREE.MeshBasicMaterial({ color: 0x00ff88 });
    const led = new THREE.Mesh(ledGeo, ledMat);
    led.position.set(0, 0.06, 0.085);
    led.name = 'statusLED';
    g.add(led);

    return g;
  }

  /* ---------- Orbit ring ---------- */
  function createOrbitRing(radius) {
    const segs = 256;
    const pts = [];
    for (let i = 0; i <= segs; i++) {
      const a = (i / segs) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
    }
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    return new THREE.Line(geo, new THREE.LineDashedMaterial({
      color: 0x0088ff, transparent: true, opacity: 0.35,
      dashSize: 0.15, gapSize: 0.1
    }));
  }

  /* ========== PUBLIC: init ========== */
  function init() {
    container = document.getElementById('orbit3dContainer');
    if (!container) return;

    // Scene
    scene = new THREE.Scene();

    // Camera
    const aspect = container.clientWidth / Math.max(1, container.clientHeight);
    camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 300);
    camera.position.set(-1.5, 3.5, 7.5);
    camera.lookAt(0, 0, 0);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.domElement.style.display = 'block';
    container.appendChild(renderer.domElement);

    // Controls
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.minDistance = 3.5;
    controls.maxDistance = 18;
    controls.target.set(0, 0, 0);
    controls.enablePan = false;

    /* --- Earth --- */
    const earthGeo = new THREE.SphereGeometry(2, 64, 64);
    const earthTex = createEarthTexture();
    const earthMat = new THREE.MeshStandardMaterial({
      map: earthTex, metalness: 0.05, roughness: 0.8
    });
    earth = new THREE.Mesh(earthGeo, earthMat);
    scene.add(earth);

    /* --- Clouds --- */
    const cloudGeo = new THREE.SphereGeometry(2.025, 48, 48);
    const cloudTex = createCloudTexture();
    const cloudMat = new THREE.MeshStandardMaterial({
      map: cloudTex, transparent: true, opacity: 0.38, depthWrite: false
    });
    clouds = new THREE.Mesh(cloudGeo, cloudMat);
    scene.add(clouds);

    /* --- Atmosphere glow --- */
    atmosGlow = createAtmosphereMesh(2.28);
    scene.add(atmosGlow);

    // Inner rim (subtle)
    const innerRim = new THREE.Mesh(
      new THREE.SphereGeometry(2.06, 48, 48),
      new THREE.MeshBasicMaterial({ color: 0x4488ff, transparent: true, opacity: 0.08, side: THREE.BackSide })
    );
    scene.add(innerRim);

    /* --- "EARTH" label (sprite) --- */
    const labelCanvas = document.createElement('canvas');
    labelCanvas.width = 256; labelCanvas.height = 64;
    const lctx = labelCanvas.getContext('2d');
    lctx.font = 'bold 32px Orbitron, monospace';
    lctx.fillStyle = 'rgba(100,200,100,0.6)';
    lctx.textAlign = 'center';
    lctx.fillText('EARTH', 128, 40);
    const labelTex = new THREE.CanvasTexture(labelCanvas);
    const labelMat = new THREE.SpriteMaterial({ map: labelTex, transparent: true, depthWrite: false });
    const labelSprite = new THREE.Sprite(labelMat);
    labelSprite.scale.set(1.2, 0.3, 1);
    labelSprite.position.set(0, -0.15, 0);
    scene.add(labelSprite);

    /* --- Orbit ring --- */
    orbitLine = createOrbitRing(3.4);
    orbitLine.computeLineDistances();
    // Tilt orbit for SSO inclination (97.6° → slight tilt)
    orbitLine.rotation.x = THREE.MathUtils.degToRad(7.6);
    scene.add(orbitLine);

    /* --- Satellite --- */
    satellite = createSatelliteModel();
    scene.add(satellite);

    /* --- Sun directional light --- */
    sunLight = new THREE.DirectionalLight(0xfff8e0, 2.0);
    sunLight.position.set(-15, 5, 8);
    scene.add(sunLight);

    // Ambient
    scene.add(new THREE.AmbientLight(0x182244, 0.5));

    // Hemisphere light for subtle fill
    scene.add(new THREE.HemisphereLight(0x4488ff, 0x000822, 0.15));

    /* --- Sun visual (bright sphere + glow) --- */
    const sunGrp = new THREE.Group();
    const sunGeo = new THREE.SphereGeometry(0.5, 16, 16);
    const sunMat = new THREE.MeshBasicMaterial({ color: 0xfff8c8 });
    sunMesh = new THREE.Mesh(sunGeo, sunMat);
    sunGrp.add(sunMesh);

    // Sun corona glow sprite
    const coronaCanvas = document.createElement('canvas');
    coronaCanvas.width = 256; coronaCanvas.height = 256;
    const cctx = coronaCanvas.getContext('2d');
    const cg = cctx.createRadialGradient(128, 128, 0, 128, 128, 128);
    cg.addColorStop(0, 'rgba(255,248,200,0.9)');
    cg.addColorStop(0.15, 'rgba(255,200,50,0.5)');
    cg.addColorStop(0.5, 'rgba(255,130,0,0.12)');
    cg.addColorStop(1, 'rgba(255,80,0,0)');
    cctx.fillStyle = cg;
    cctx.fillRect(0, 0, 256, 256);
    const coronaTex = new THREE.CanvasTexture(coronaCanvas);
    const coronaMat = new THREE.SpriteMaterial({ map: coronaTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
    const corona = new THREE.Sprite(coronaMat);
    corona.scale.set(4, 4, 1);
    sunGrp.add(corona);

    sunGrp.position.copy(sunLight.position);
    scene.add(sunGrp);

    /* --- Stars --- */
    starField = createStars();
    scene.add(starField);

    /* --- Orbit info sprite --- */
    const infoCanvas = document.createElement('canvas');
    infoCanvas.width = 512; infoCanvas.height = 64;
    const ictx = infoCanvas.getContext('2d');
    ictx.font = '20px Share Tech Mono, monospace';
    ictx.fillStyle = 'rgba(0,140,220,0.5)';
    ictx.textAlign = 'center';
    ictx.fillText('SSO 550km · T=95.7min · i=97.6°', 256, 38);
    const infoTex = new THREE.CanvasTexture(infoCanvas);
    const infoMat = new THREE.SpriteMaterial({ map: infoTex, transparent: true, depthWrite: false });
    const infoSprite = new THREE.Sprite(infoMat);
    infoSprite.scale.set(3.5, 0.44, 1);
    infoSprite.position.set(0, -2.8, 0);
    scene.add(infoSprite);
  }

  /* ========== PUBLIC: update ========== */
  function update(eclipse) {
    if (!renderer) return;

    const angle = getAngle(simTime);
    const orbitRadius = 3.4;
    const tiltRad = THREE.MathUtils.degToRad(7.6);

    // Satellite position (tilted orbit)
    const sx = Math.cos(angle) * orbitRadius;
    const rawZ = Math.sin(angle) * orbitRadius;
    const sy = rawZ * Math.sin(tiltRad);
    const sz = rawZ * Math.cos(tiltRad);
    satellite.position.set(sx, sy, sz);

    // Satellite orientation: face direction of travel
    const nextAngle = angle + 0.02;
    const nx = Math.cos(nextAngle) * orbitRadius;
    const nRawZ = Math.sin(nextAngle) * orbitRadius;
    const ny = nRawZ * Math.sin(tiltRad);
    const nz = nRawZ * Math.cos(tiltRad);
    satellite.lookAt(nx, ny, nz);

    // Rotate Earth slowly
    earthRotY += 0.0015;
    earth.rotation.y = earthRotY;
    clouds.rotation.y = earthRotY * 1.12;

    // Eclipse effects
    if (eclipse) {
      sunLight.intensity = 0.12;
      atmosGlow.material.uniforms.intensity.value = 0.4;
      const led = satellite.getObjectByName('statusLED');
      if (led) led.material.color.setHex(0x6688ff);
    } else {
      sunLight.intensity = 2.0;
      atmosGlow.material.uniforms.intensity.value = 1.6;
      const led = satellite.getObjectByName('statusLED');
      if (led) led.material.color.setHex(0x00ff88);
    }

    // Resize check
    const w = container.clientWidth, h = container.clientHeight;
    if (w > 0 && h > 0) {
      const cw = renderer.domElement.width, ch = renderer.domElement.height;
      const pr = renderer.getPixelRatio();
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

  return { init, update, resize };
})();
