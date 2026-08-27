/**
 * Custom GLSL for the fallback Earth.
 *
 * EARTH — day-side / night-side blend driven by `uSunDir`, which is the
 * BROADCAST sun direction in display space (see sky.ts); the mesh itself is
 * spun by GMST, and lighting is done in world space so the terminator lands
 * where the sky frame says it does. We don't have CC0 8K textures in this
 * repo, so the surface look is fully procedural:
 *   - day color from latitude (cooler near poles, warm equator green)
 *   - night color from a faint city-light glow proxy (perlin-ish)
 *   - blend factor = smoothstep(dot(normal, sun))
 *
 * ATMOSPHERE — Fresnel emission. Bigger sphere, back-side rendered,
 * additive blend. Accent-blue tint, intensity 1.1.
 */

export const earthVert = /* glsl */`
  varying vec3 vNormalW;
  varying vec3 vPositionW;
  varying vec2 vUv;

  void main() {
    vUv = uv;
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vPositionW = worldPos.xyz;
    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`

export const earthFrag = /* glsl */`
  precision highp float;
  uniform vec3 uSunDir;
  uniform float uTime;
  // 1 once a real sun direction has been broadcast, 0 before that. At 0 the
  // globe is shown evenly lit: with no sky frame there is no terminator, and
  // inventing one is the exact bug this round exists to remove.
  uniform float uSunKnown;
  varying vec3 vNormalW;
  varying vec3 vPositionW;
  varying vec2 vUv;

  // Cheap hash + noise for the night-light proxy.
  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
  }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f*f*(3.0 - 2.0*f);
    float a = hash(i), b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }

  void main() {
    vec3 N = normalize(vNormalW);
    float ndl = dot(N, normalize(uSunDir));
    // Latitude band — equator green, poles white-ish.
    float lat = vUv.y; // 0..1
    vec3 ocean = vec3(0.05, 0.18, 0.40);
    vec3 land  = mix(vec3(0.20, 0.36, 0.18), vec3(0.50, 0.40, 0.20),
                     smoothstep(0.45, 0.85, abs(lat - 0.5) * 2.0));
    // Procedural continents.
    float n = noise(vUv * vec2(12.0, 6.0));
    float landMask = smoothstep(0.55, 0.65, n);
    vec3 dayCol = mix(ocean, land, landMask);
    // Polar ice caps.
    dayCol = mix(dayCol, vec3(0.92, 0.95, 1.0),
                 smoothstep(0.85, 1.0, abs(lat - 0.5) * 2.0));

    // Night side: faint city lights wherever landMask is high. A very small,
    // slow twinkle (±6 %) keeps them from reading as a static decal.
    float lights = landMask * step(0.55, noise(vUv * vec2(40.0, 22.0)));
    float twinkle = 0.94 + 0.06 * sin(uTime * 1.0 + (vUv.x + vUv.y) * 30.0);
    vec3 nightCol = vec3(1.0, 0.78, 0.45) * lights * twinkle * 0.55
                  + vec3(0.01, 0.02, 0.05);

    // Lambertian falloff + small ambient lift so terminator isn't a hard line.
    float dayK = smoothstep(-0.12, 0.18, ndl);
    vec3 lit = mix(nightCol, dayCol * (0.35 + 0.65 * max(0.0, ndl)), dayK);
    // Sun unknown -> flat daylight, no claimed day/night boundary.
    lit = mix(dayCol * 0.72, lit, clamp(uSunKnown, 0.0, 1.0));

    // Subtle blue-shift at the limb to suggest atmosphere scattering on top.
    float limb = pow(1.0 - clamp(dot(N, normalize(cameraPosition - vPositionW)), 0.0, 1.0), 2.5);
    lit += vec3(0.10, 0.22, 0.45) * limb * 0.55;

    gl_FragColor = vec4(lit, 1.0);
  }
`

export const atmoVert = /* glsl */`
  varying vec3 vNormalW;
  varying vec3 vPositionW;
  void main() {
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vPositionW = worldPos.xyz;
    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`

export const atmoFrag = /* glsl */`
  precision highp float;
  uniform vec3 uColor;
  uniform float uIntensity;
  varying vec3 vNormalW;
  varying vec3 vPositionW;

  void main() {
    vec3 N = normalize(vNormalW);
    vec3 V = normalize(cameraPosition - vPositionW);
    float fresnel = pow(1.0 - abs(dot(N, V)), 3.0);
    gl_FragColor = vec4(uColor * fresnel * uIntensity, fresnel);
  }
`

// Star points — vertex pushes the size, fragment fades to a soft disc.
export const starsVert = /* glsl */`
  attribute float aSeed;
  varying float vSeed;
  uniform float uTime;
  void main() {
    vSeed = aSeed;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float twinkle = 0.92 + 0.08 * sin(uTime * 0.8 + aSeed * 6.2831);
    gl_PointSize = (1.5 + 1.5 * aSeed) * twinkle * (300.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`

export const starsFrag = /* glsl */`
  precision mediump float;
  varying float vSeed;
  void main() {
    vec2 c = gl_PointCoord - vec2(0.5);
    float d = length(c);
    if (d > 0.5) discard;
    float a = smoothstep(0.5, 0.0, d);
    vec3 col = mix(vec3(0.65, 0.75, 1.0), vec3(1.0, 0.85, 0.65), vSeed);
    gl_FragColor = vec4(col, a * 0.85);
  }
`
