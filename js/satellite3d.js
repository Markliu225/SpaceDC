/* ================================================================
 *  satellite3d.js — 3D Satellite Detail View
 *  Realistic engineering-style spacecraft model
 * ================================================================ */

var Detail3D = (function () {
  'use strict';

  var scene, camera, renderer, controls;
  var satGroup;
  var container;
  var ready = false;

  /* ---- Materials ---- */
  function makeMats() {
    return {
      mli:    new THREE.MeshStandardMaterial({ color: 0xd8d8cc, metalness: 0.08, roughness: 0.65 }),
      gold:   new THREE.MeshStandardMaterial({ color: 0xc8a530, metalness: 0.72, roughness: 0.28 }),
      solar:  new THREE.MeshStandardMaterial({ color: 0x08082a, metalness: 0.42, roughness: 0.24 }),
      frame:  new THREE.MeshStandardMaterial({ color: 0x888888, metalness: 0.60, roughness: 0.35 }),
      rad:    new THREE.MeshStandardMaterial({ color: 0xe4e4ec, metalness: 0.05, roughness: 0.85 }),
      copper: new THREE.MeshStandardMaterial({ color: 0xb87333, metalness: 0.80, roughness: 0.32 }),
      dark:   new THREE.MeshStandardMaterial({ color: 0x222222, metalness: 0.50, roughness: 0.60 }),
      ant:    new THREE.MeshStandardMaterial({ color: 0xbbbbbb, metalness: 0.55, roughness: 0.35 }),
      lens:   new THREE.MeshStandardMaterial({ color: 0x0a0a15, metalness: 0.70, roughness: 0.12 }),
      nozzle: new THREE.MeshStandardMaterial({ color: 0x3a3a3c, metalness: 0.65, roughness: 0.40 }),
      led:    new THREE.MeshBasicMaterial({ color: 0x33cc66 })
    };
  }

  /* ---- Build satellite ---- */
  function buildSat(m) {
    var g = new THREE.Group();
    var wc = Math.max(1, typeof wingCount !== 'undefined' ? wingCount : 4);
    var wa = typeof wingArea !== 'undefined' ? wingArea : 6;
    var wpp = 3;
    var radC = Math.max(1, typeof radCount !== 'undefined' ? radCount : 4);
    var radA = typeof radArea !== 'undefined' ? radArea : 1.0;

    // Bus dimensions
    var bx = 1.6, by = 1.2, bz = 2.0;
    var bus = new THREE.Mesh(new THREE.BoxGeometry(bx, by, bz), m.mli);
    g.add(bus);

    // Gold MLI band
    var band = new THREE.Mesh(new THREE.BoxGeometry(bx + 0.01, 0.18, bz + 0.01), m.gold);
    band.position.y = 0.20;
    g.add(band);

    // Panel rails (decorative lines on bus)
    var edgeMat = new THREE.LineBasicMaterial({ color: 0x666666, transparent: true, opacity: 0.5 });
    [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(function(c) {
      var pts = [
        new THREE.Vector3(c[0] * bx / 2, -by / 2, c[1] * bz / 2),
        new THREE.Vector3(c[0] * bx / 2, by / 2, c[1] * bz / 2)
      ];
      g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), edgeMat));
    });

    // ── Solar wings ──
    // Map real area (m²) to visual size with a scale factor
    // wingArea is already per-wing area (e.g. 350 m²/wing)
    var wingScale = 0.018;
    var singleWingW = Math.sqrt(wa) * wingScale * 1.4;
    var singleWingH = Math.sqrt(wa) * wingScale * 1.0;
    singleWingW = Math.max(0.3, Math.min(singleWingW, 1.8));
    singleWingH = Math.max(0.25, Math.min(singleWingH, 1.2));

    var armLen = 0.25;
    var wingGap = 0.10;

    // Each side: arrange wings in a grid (rows along Z, columns along X)
    var leftWings  = Math.ceil(wc / 2);
    var rightWings = wc - leftWings;

    function layoutWingSide(count, side) {
      // Determine grid: prefer wide → max cols based on count
      var cols = (count <= 2) ? 1 : (count <= 6) ? 2 : 3;
      var rows = Math.ceil(count / cols);

      for (var idx = 0; idx < count; idx++) {
        var col = Math.floor(idx / rows);  // which column (outward from bus)
        var row = idx % rows;               // which row (along Z)
        var wingG = new THREE.Group();

        // Wing X offset: stacked outward from bus
        var colOffset = col * (singleWingW * wpp + wingGap);
        var wingStartX = bx / 2 + armLen + 0.02 + colOffset;
        var wingTotalW = singleWingW * wpp;

        // Arm (only for first column, or extend to reach)
        var fullArmLen = armLen + colOffset;
        var armMesh = new THREE.Mesh(new THREE.BoxGeometry(fullArmLen, 0.04, 0.04), m.frame);
        armMesh.position.x = side * (bx / 2 + fullArmLen / 2);
        wingG.add(armMesh);

        // Sub-panels
        for (var pi = 0; pi < wpp; pi++) {
          var panel = new THREE.Mesh(
            new THREE.BoxGeometry(singleWingW - 0.02, 0.02, singleWingH), m.solar
          );
          panel.position.set(
            side * (wingStartX + pi * singleWingW + singleWingW / 2), 0, 0
          );
          wingG.add(panel);

          // Cell grid lines
          var gridMat = new THREE.LineBasicMaterial({ color: 0x1a1a55, transparent: true, opacity: 0.35 });
          for (var li = 1; li < 4; li++) {
            var gy = (li / 4 - 0.5) * singleWingH;
            wingG.add(new THREE.Line(
              new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(side * (wingStartX + pi * singleWingW + 0.02), 0.012, gy),
                new THREE.Vector3(side * (wingStartX + (pi + 1) * singleWingW - 0.02), 0.012, gy)
              ]), gridMat
            ));
          }
        }

        // Frame rails
        [-1, 1].forEach(function(rs) {
          var rail = new THREE.Mesh(
            new THREE.BoxGeometry(wingTotalW + 0.04, 0.03, 0.025), m.frame
          );
          rail.position.set(side * (wingStartX + wingTotalW / 2), 0, rs * singleWingH / 2);
          wingG.add(rail);
        });

        // Position row along Z, centered
        var totalZSpan = rows * singleWingH + (rows - 1) * wingGap;
        var startZ = -totalZSpan / 2 + singleWingH / 2;
        wingG.position.z = startZ + row * (singleWingH + wingGap);

        g.add(wingG);
      }
    }

    layoutWingSide(leftWings, -1);
    layoutWingSide(rightWings, 1);

    // ── Radiator panels ──
    // Map real area to visual size (radArea is per-panel)
    var radScale = 0.032;
    var singleRadW = Math.sqrt(radA) * radScale * 1.2;
    var singleRadH = Math.sqrt(radA) * radScale * 0.9;
    singleRadW = Math.max(0.2, Math.min(singleRadW, 1.0));
    singleRadH = Math.max(0.18, Math.min(singleRadH, 0.8));
    var radGap = 0.08;
    var radYOff = -by / 2 - 0.08;

    var leftRads  = Math.ceil(radC / 2);
    var rightRads = radC - leftRads;

    function layoutRadSide(count, rSide) {
      var cols = (count <= 2) ? 1 : (count <= 6) ? 2 : 3;
      var rows = Math.ceil(count / cols);

      for (var idx = 0; idx < count; idx++) {
        var col = Math.floor(idx / rows);
        var row = idx % rows;

        var colOffset = col * (singleRadW + radGap);
        var rx = rSide * (bx / 2 + singleRadW / 2 + 0.06 + colOffset);

        var totalZSpan = rows * singleRadH + (rows - 1) * radGap;
        var startZ = -totalZSpan / 2 + singleRadH / 2;
        var rz = startZ + row * (singleRadH + radGap);

        var radPanel = new THREE.Mesh(new THREE.BoxGeometry(singleRadW, 0.015, singleRadH), m.rad);
        radPanel.position.set(rx, radYOff, rz);
        g.add(radPanel);

        // Heat pipes
        for (var hi = 0; hi < 3; hi++) {
          var pipe = new THREE.Mesh(
            new THREE.CylinderGeometry(0.012, 0.012, singleRadH - 0.04, 6), m.copper
          );
          pipe.rotation.x = Math.PI / 2;
          pipe.position.set(rx + (hi - 1) * singleRadW * 0.28, radYOff, rz);
          g.add(pipe);
        }
      }
    }

    layoutRadSide(leftRads, -1);
    layoutRadSide(rightRads, 1);

    // High-gain antenna
    var antPole = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.45, 8), m.ant);
    antPole.position.set(0, by / 2 + 0.22, -bz / 3);
    g.add(antPole);
    var dish = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 10, 0, Math.PI * 2, 0, 1.4), m.ant);
    dish.position.set(0, by / 2 + 0.50, -bz / 3);
    dish.rotation.x = Math.PI;
    g.add(dish);
    var feed = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.03, 0.12, 6), m.dark);
    feed.position.set(0, by / 2 + 0.43, -bz / 3);
    g.add(feed);

    // S-band antenna
    var sAnt = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.005, 0.14, 6), m.ant);
    sAnt.position.set(0.55, by / 2 + 0.07, bz / 3);
    g.add(sAnt);

    // Star trackers (2)
    [-1, 1].forEach(function(ss) {
      var st = new THREE.Mesh(new THREE.BoxGeometry(0.10, 0.08, 0.12), m.dark);
      st.position.set(ss * 0.50, by / 2 + 0.04, 0.55);
      g.add(st);
      var stLens = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.02, 8), m.lens);
      stLens.position.set(ss * 0.50, by / 2 + 0.085, 0.55);
      g.add(stLens);
    });

    // Thruster nozzles (4 corners)
    [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(function(c) {
      var nz = new THREE.Mesh(new THREE.ConeGeometry(0.04, 0.08, 8, 1, true), m.nozzle);
      nz.position.set(c[0] * (bx / 2 - 0.08), -by / 2 - 0.04, c[1] * (bz / 2 - 0.08));
      nz.rotation.x = Math.PI;
      g.add(nz);
    });

    // Docking ring
    var dr = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.025, 8, 24), m.frame);
    dr.position.set(0, 0, bz / 2 + 0.015);
    dr.rotation.x = Math.PI / 2;
    g.add(dr);

    // Status LEDs
    [
      { x: 0.55, y: 0.35, z: bz / 2 + 0.01 },
      { x: -0.55, y: 0.35, z: bz / 2 + 0.01 },
      { x: 0.55, y: -0.35, z: bz / 2 + 0.01 }
    ].forEach(function(p, i) {
      var led = new THREE.Mesh(new THREE.SphereGeometry(0.02, 6, 6), m.led.clone());
      led.position.set(p.x, p.y, p.z);
      led.name = 'led' + i;
      g.add(led);
    });

    // Sensor bar
    var sb = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.06, 0.10), m.dark);
    sb.position.set(0, -by / 2 - 0.03, bz / 2 - 0.20);
    g.add(sb);
    for (var si = 0; si < 5; si++) {
      var sLens = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.015, 8), m.lens);
      sLens.position.set((si - 2) * 0.20, -by / 2 - 0.065, bz / 2 - 0.20);
      sLens.rotation.x = Math.PI / 2;
      g.add(sLens);
    }

    return g;
  }

  /* ========== init ========== */
  function init() {
    try {
      container = document.getElementById('detail3dContainer');
      if (!container) { console.warn('Detail3D: container not found'); return; }

      var w = container.clientWidth, h = container.clientHeight;
      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(38, w / Math.max(h, 1), 0.1, 50);
      camera.position.set(3.2, 2.5, 4.5);

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(w, h);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.0;
      renderer.domElement.style.display = 'block';
      container.appendChild(renderer.domElement);

      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.07;
      controls.minDistance = 2;
      controls.maxDistance = 12;
      controls.target.set(0, 0, 0);

      /* --- Lighting --- */
      var sun = new THREE.DirectionalLight(0xfff5e0, 2.0);
      sun.position.set(5, 4, 6);
      scene.add(sun);

      var fill = new THREE.DirectionalLight(0x3366aa, 0.18);
      fill.position.set(3, -2, -4);
      scene.add(fill);

      scene.add(new THREE.AmbientLight(0x0a1530, 0.25));
      scene.add(new THREE.HemisphereLight(0x445588, 0x000510, 0.12));

      /* --- Stars --- */
      var sN = 1500, sPos = [];
      for (var si = 0; si < sN; si++) {
        var r = 25 + Math.random() * 25;
        var th = Math.random() * Math.PI * 2;
        var ph = Math.acos(2 * Math.random() - 1);
        sPos.push(r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), r * Math.cos(ph));
      }
      var sGeo = new THREE.BufferGeometry();
      sGeo.setAttribute('position', new THREE.Float32BufferAttribute(sPos, 3));
      scene.add(new THREE.Points(sGeo, new THREE.PointsMaterial({ color: 0xcccccc, size: 0.06, transparent: true, opacity: 0.7, depthWrite: false })));

      /* --- Satellite --- */
      var mats = makeMats();
      satGroup = buildSat(mats);
      scene.add(satGroup);

      ready = true;
      console.log('Detail3D: initialized OK');
    } catch (e) {
      console.error('Detail3D init error:', e);
    }
  }

  /* ========== update ========== */
  function update(eclipse) {
    if (!ready) return;
    try {
      // Gentle tumble
      if (satGroup) {
        satGroup.rotation.y += 0.0015;
        satGroup.rotation.x = Math.sin(Date.now() * 0.0003) * 0.06;
      }

      // Eclipse LED color
      satGroup.traverse(function (child) {
        if (child.name && child.name.indexOf('led') === 0) {
          child.material.color.setHex(eclipse ? 0x3355aa : 0x33cc66);
        }
      });

      // Auto resize
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
      console.error('Detail3D update error:', e);
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
    } catch (e) { console.error('Detail3D resize error:', e); }
  }

  /* ========== rebuild ========== */
  function rebuild() {
    if (!ready) return;
    try {
      // Remove old satellite
      if (satGroup) {
        scene.remove(satGroup);
        satGroup.traverse(function (child) {
          if (child.geometry) child.geometry.dispose();
          if (child.material) {
            if (child.material.map) child.material.map.dispose();
            child.material.dispose();
          }
        });
      }

      // Rebuild
      var mats = makeMats();
      satGroup = buildSat(mats);
      scene.add(satGroup);

      console.log('Detail3D: rebuild OK');
    } catch (e) {
      console.error('Detail3D rebuild error:', e);
    }
  }

  return { init: init, update: update, resize: resize, rebuild: rebuild };
})();
