/* ================================================================
 *  orbit3d.js — 3D Orbit Scene (Earth + Satellite)
 *  Uses NASA Blue Marble textures + Day/Night shader
 * ================================================================ */

var Orbit3D = (function () {
  'use strict';

  var scene, camera, renderer, controls;
  var earthMesh, cloudsMesh, satellite, orbitLine, sunLight, sunGroup;
  var atmosMesh, earthMat;
  var container;
  var earthRotY = 0;
  var ready = false;

  var TEX_DAY   = 'https://unpkg.com/three-globe@2.31.1/example/img/earth-blue-marble.jpg';
  var TEX_NIGHT = 'https://unpkg.com/three-globe@2.31.1/example/img/earth-night.jpg';
  var TEX_BUMP  = 'https://unpkg.com/three-globe@2.31.1/example/img/earth-topology.png';

  /* ---- Noise (for procedural clouds) ---- */
  function _h(x, y) { var h = (x * 374761393 + y * 668265263) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
  function _s(x, y) { var ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy, sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy); return (_h(ix, iy) * (1 - sx) + _h(ix + 1, iy) * sx) * (1 - sy) + (_h(ix, iy + 1) * (1 - sx) + _h(ix + 1, iy + 1) * sx) * sy; }
  function _fbm(x, y, n) { var v = 0, a = 0.5, f = 1; for (var i = 0; i < n; i++) { v += _s(x * f, y * f) * a; a *= 0.5; f *= 2; } return v; }

  function makeCloudTexture() {
    var W = 1024, H = 512;
    var cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(W, H), d = img.data;
    for (var py = 0; py < H; py++) {
      var lat = (py / H - 0.5) * Math.PI;
      for (var px = 0; px < W; px++) {
        var i = (py * W + px) * 4;
        var n = _fbm(px / W * 14 + 100, py / H * 7 + 200, 6) + _fbm(px / W * 24 + 300, py / H * 12 + 400, 4) * 0.25;
        var cloud = Math.max(0, (n * (1.0 - Math.abs(lat) * 0.5) - 0.33) * 2.6);
        d[i] = d[i + 1] = d[i + 2] = 255;
        d[i + 3] = Math.min(200, Math.floor(cloud * 160));
      }
    }
    ctx.putImageData(img, 0, 0);
    var tex = new THREE.CanvasTexture(cv);
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }

  /* ---- Atmosphere ---- */
  function makeAtmosphere(radius) {
    var vs = [
      'varying vec3 vN;',
      'varying vec3 vP;',
      'void main(){',
      '  vN = normalize(normalMatrix * normal);',
      '  vP = vec3(modelViewMatrix * vec4(position, 1.0));',
      '  gl_Position = projectionMatrix * vec4(vP, 1.0);',
      '}'
    ].join('\n');
    var fs = [
      'varying vec3 vN;',
      'varying vec3 vP;',
      'uniform float intensity;',
      'void main(){',
      '  vec3 V = normalize(-vP);',
      '  float rim = 1.0 - max(dot(V, vN), 0.0);',
      '  vec3 col = vec3(0.22, 0.48, 1.0) * pow(rim, 2.8) * intensity;',
      '  col += vec3(0.55, 0.75, 1.0) * pow(rim, 5.5) * intensity * 0.25;',
      '  gl_FragColor = vec4(col, pow(rim, 2.4) * intensity * 0.55);',
      '}'
    ].join('\n');
    var mat = new THREE.ShaderMaterial({
      vertexShader: vs,
      fragmentShader: fs,
      uniforms: { intensity: { value: 1.1 } },
      side: THREE.BackSide,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    return new THREE.Mesh(new THREE.SphereGeometry(radius, 64, 64), mat);
  }

  /* ---- Stars ---- */
  function makeStars() {
    var N = 5000, pos = [], col = [];
    for (var i = 0; i < N; i++) {
      var r = 80 + Math.random() * 80, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      pos.push(r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), r * Math.cos(ph));
      var t = Math.random();
      if (t < 0.65)      col.push(0.92, 0.94, 1.0);
      else if (t < 0.80) col.push(0.72, 0.82, 1.0);
      else if (t < 0.92) col.push(1.0, 0.96, 0.82);
      else                col.push(1.0, 0.82, 0.65);
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    return new THREE.Points(g, new THREE.PointsMaterial({
      size: 0.13, vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false
    }));
  }

  /* ---- Small satellite model (orbit view) ---- */
  function makeSatModel() {
    var g = new THREE.Group();
    var busMat   = new THREE.MeshStandardMaterial({ color: 0xd0d0c8, metalness: 0.12, roughness: 0.6 });
    var goldMat  = new THREE.MeshStandardMaterial({ color: 0xc8a530, metalness: 0.72, roughness: 0.28 });
    var solarMat = new THREE.MeshStandardMaterial({ color: 0x0a0a2a, metalness: 0.42, roughness: 0.28 });
    var frameMat = new THREE.MeshStandardMaterial({ color: 0x909090, metalness: 0.6, roughness: 0.38 });
    var radMat   = new THREE.MeshStandardMaterial({ color: 0xe4e4ec, metalness: 0.08, roughness: 0.82 });
    var antMat   = new THREE.MeshStandardMaterial({ color: 0xb0b0b0, metalness: 0.55, roughness: 0.35 });

    // Bus
    var bus = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.10, 0.16), busMat);
    g.add(bus);
    var band = new THREE.Mesh(new THREE.BoxGeometry(0.145, 0.025, 0.165), goldMat);
    band.position.y = 0.018; g.add(band);

    // Solar panels
    [-1, 1].forEach(function(side) {
      var arm = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.007, 0.007), frameMat);
      arm.position.set(side * 0.10, 0, 0); g.add(arm);
      var p = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.003, 0.12), solarMat);
      p.position.set(side * 0.26, 0, 0); g.add(p);
      [-1, 1].forEach(function(fs) {
        var rail = new THREE.Mesh(new THREE.BoxGeometry(0.345, 0.005, 0.004), frameMat);
        rail.position.set(side * 0.26, 0, fs * 0.059); g.add(rail);
      });
    });

    // Radiators (white)
    [-1, 1].forEach(function(side) {
      var r = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.003, 0.10), radMat);
      r.position.set(side * 0.10, -0.055, 0); g.add(r);
    });

    // Antenna
    var antPole = new THREE.Mesh(new THREE.CylinderGeometry(0.003, 0.003, 0.07, 6), antMat);
    antPole.position.set(0, 0.085, 0); g.add(antPole);
    var dish = new THREE.Mesh(new THREE.SphereGeometry(0.022, 12, 8, 0, Math.PI * 2, 0, 1.4), antMat);
    dish.position.set(0, 0.13, 0); dish.rotation.x = Math.PI; g.add(dish);

    // LED
    var led = new THREE.Mesh(new THREE.SphereGeometry(0.006, 6, 6), new THREE.MeshBasicMaterial({ color: 0x33cc66 }));
    led.position.set(0, 0.055, 0.085); led.name = 'statusLED'; g.add(led);

    return g;
  }

  /* ---- Orbit ring ---- */
  function makeOrbitRing(radius) {
    var pts = [];
    for (var i = 0; i <= 256; i++) {
      var a = (i / 256) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
    }
    var line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineDashedMaterial({ color: 0x3388bb, transparent: true, opacity: 0.22, dashSize: 0.12, gapSize: 0.08 })
    );
    return line;
  }

  /* ---- Earth Day/Night Shader ---- */
  function makeEarthShader(dayTex, nightTex, bumpTex) {
    var vs = [
      'varying vec2 vUv;',
      'varying vec3 vNormal;',
      'varying vec3 vWorldPos;',
      'void main(){',
      '  vUv = uv;',
      '  vNormal = normalize((modelMatrix * vec4(normal, 0.0)).xyz);',
      '  vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;',
      '  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);',
      '}'
    ].join('\n');

    var fs = [
      'uniform sampler2D dayMap;',
      'uniform sampler2D nightMap;',
      'uniform sampler2D bumpMap;',
      'uniform vec3 sunDir;',
      'varying vec2 vUv;',
      'varying vec3 vNormal;',
      'varying vec3 vWorldPos;',
      'void main(){',
      '  vec3 day = texture2D(dayMap, vUv).rgb;',
      '  vec3 night = texture2D(nightMap, vUv).rgb;',
      '  vec3 N = normalize(vNormal);',
      '  float NdL = dot(N, sunDir);',
      '  float dayMix = smoothstep(-0.12, 0.2, NdL);',
      '  float diff = max(NdL, 0.0);',
      '  vec3 dayLit = day * (0.05 + 0.95 * diff);',
      '  vec3 nightLit = night * 1.8 * (1.0 - dayMix);',
      '  vec3 color = dayLit * dayMix + nightLit;',
      '  vec3 V = normalize(cameraPosition - vWorldPos);',
      '  vec3 H = normalize(sunDir + V);',
      '  float spec = pow(max(dot(N, H), 0.0), 100.0);',
      '  float elev = texture2D(bumpMap, vUv).r;',
      '  float water = 1.0 - smoothstep(0.0, 0.08, elev);',
      '  color += vec3(0.45, 0.55, 0.7) * spec * water * dayMix * 0.4;',
      '  float scatter = pow(max(1.0 - abs(NdL), 0.0), 5.0) * 0.07;',
      '  color += vec3(0.3, 0.5, 1.0) * scatter;',
      '  gl_FragColor = vec4(color, 1.0);',
      '}'
    ].join('\n');

    return new THREE.ShaderMaterial({
      uniforms: {
        dayMap:   { value: dayTex },
        nightMap: { value: nightTex },
        bumpMap:  { value: bumpTex },
        sunDir:   { value: new THREE.Vector3(-1, 0.3, 0.5).normalize() }
      },
      vertexShader: vs,
      fragmentShader: fs
    });
  }

  /* ========== init ========== */
  function init() {
    try {
      container = document.getElementById('orbit3dContainer');
      if (!container) { console.warn('Orbit3D: container not found'); return; }

      var w = container.clientWidth, h = container.clientHeight;
      if (w < 10 || h < 10) { console.warn('Orbit3D: container too small', w, h); }

      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(45, w / Math.max(h, 1), 0.1, 300);
      camera.position.set(-1.5, 3.5, 7.5);

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(w, h);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.1;
      renderer.domElement.style.display = 'block';
      container.appendChild(renderer.domElement);

      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.06;
      controls.minDistance = 3.5;
      controls.maxDistance = 18;
      controls.target.set(0, 0, 0);
      controls.enablePan = false;

      /* --- Earth --- */
      var loader = new THREE.TextureLoader();
      var dayTex = loader.load(TEX_DAY);
      var nightTex = loader.load(TEX_NIGHT);
      var bumpTex = loader.load(TEX_BUMP);

      earthMat = makeEarthShader(dayTex, nightTex, bumpTex);
      earthMesh = new THREE.Mesh(new THREE.SphereGeometry(2, 128, 64), earthMat);
      scene.add(earthMesh);

      /* --- Clouds --- */
      cloudsMesh = new THREE.Mesh(
        new THREE.SphereGeometry(2.018, 64, 32),
        new THREE.MeshStandardMaterial({ map: makeCloudTexture(), transparent: true, opacity: 0.32, depthWrite: false })
      );
      scene.add(cloudsMesh);

      /* --- Atmosphere --- */
      atmosMesh = makeAtmosphere(2.15);
      scene.add(atmosMesh);

      /* --- Orbit ring --- */
      orbitLine = makeOrbitRing(3.4);
      orbitLine.computeLineDistances();
      orbitLine.rotation.x = 7.6 * Math.PI / 180;
      scene.add(orbitLine);

      /* --- Satellite --- */
      satellite = makeSatModel();
      scene.add(satellite);

      /* --- Lighting --- */
      sunLight = new THREE.DirectionalLight(0xfff5e0, 2.2);
      sunLight.position.set(-15, 5, 8);
      scene.add(sunLight);
      scene.add(new THREE.AmbientLight(0x0a1530, 0.35));
      scene.add(new THREE.HemisphereLight(0x2244aa, 0x000510, 0.10));

      /* --- Sun visual --- */
      sunGroup = new THREE.Group();
      sunGroup.add(new THREE.Mesh(new THREE.SphereGeometry(0.42, 24, 24), new THREE.MeshBasicMaterial({ color: 0xfff5d0 })));
      var cc = document.createElement('canvas'); cc.width = 256; cc.height = 256;
      var cx = cc.getContext('2d');
      var cg = cx.createRadialGradient(128, 128, 0, 128, 128, 128);
      cg.addColorStop(0, 'rgba(255,250,220,0.85)');
      cg.addColorStop(0.12, 'rgba(255,210,80,0.35)');
      cg.addColorStop(0.4, 'rgba(255,160,40,0.06)');
      cg.addColorStop(1, 'rgba(255,100,0,0)');
      cx.fillStyle = cg; cx.fillRect(0, 0, 256, 256);
      var corona = new THREE.Sprite(new THREE.SpriteMaterial({
        map: new THREE.CanvasTexture(cc), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false
      }));
      corona.scale.set(3.2, 3.2, 1);
      sunGroup.add(corona);
      sunGroup.position.set(-15, 5, 8);
      scene.add(sunGroup);

      /* --- Stars --- */
      scene.add(makeStars());

      /* --- Info label --- */
      var ic = document.createElement('canvas'); ic.width = 512; ic.height = 64;
      var ictx = ic.getContext('2d');
      ictx.font = '18px Share Tech Mono, monospace';
      ictx.fillStyle = 'rgba(0,120,200,0.35)';
      ictx.textAlign = 'center';
      ictx.fillText('SSO 550km · T=95.7min · i=97.6°', 256, 38);
      var infoSp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(ic), transparent: true, depthWrite: false }));
      infoSp.scale.set(3.5, 0.44, 1);
      infoSp.position.set(0, -2.8, 0);
      scene.add(infoSp);

      ready = true;
      console.log('Orbit3D: initialized OK');
    } catch (e) {
      console.error('Orbit3D init error:', e);
    }
  }

  /* ========== update ========== */
  function update(eclipse) {
    if (!ready) return;
    try {
      var angle = getAngle(simTime);
      var R = 3.4, tilt = 7.6 * Math.PI / 180;

      // Satellite position (tilted orbit)
      var sx = Math.cos(angle) * R;
      var rz = Math.sin(angle) * R;
      satellite.position.set(sx, rz * Math.sin(tilt), rz * Math.cos(tilt));
      var na = angle + 0.02;
      satellite.lookAt(Math.cos(na) * R, Math.sin(na) * R * Math.sin(tilt), Math.sin(na) * R * Math.cos(tilt));

      // Earth rotation
      earthRotY += 0.0012;
      earthMesh.rotation.y = earthRotY;
      cloudsMesh.rotation.y = earthRotY * 1.06 + 0.3;

      // Sync shader sun direction
      if (earthMat && earthMat.uniforms && earthMat.uniforms.sunDir) {
        earthMat.uniforms.sunDir.value.copy(sunLight.position).normalize();
      }

      // Eclipse effects
      sunLight.intensity = eclipse ? 0.06 : 2.2;
      if (atmosMesh && atmosMesh.material && atmosMesh.material.uniforms) {
        atmosMesh.material.uniforms.intensity.value = eclipse ? 0.25 : 1.1;
      }
      var led = satellite.getObjectByName('statusLED');
      if (led) led.material.color.setHex(eclipse ? 0x3355aa : 0x33cc66);

      // Resize
      var w = container.clientWidth, h = container.clientHeight;
      if (w > 0 && h > 0) {
        var pr = renderer.getPixelRatio();
        if (Math.abs(renderer.domElement.width - w * pr) > 1 || Math.abs(renderer.domElement.height - h * pr) > 1) {
          renderer.setSize(w, h);
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
        }
      }
      controls.update();
      renderer.render(scene, camera);
    } catch (e) {
      console.error('Orbit3D update error:', e);
    }
  }

  function resize() {
    if (!ready) return;
    try {
      var w = container.clientWidth, h = container.clientHeight;
      if (w > 0 && h > 0) {
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      }
    } catch (e) { console.error('Orbit3D resize error:', e); }
  }

  return { init: init, update: update, resize: resize };
})();
