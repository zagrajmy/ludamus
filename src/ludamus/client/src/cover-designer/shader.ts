/**
 * The cover patterns as one fragment shader, written in WGSL and assembled with
 * TypeGPU. Each pattern is a function of the plane; the uniform picks one and
 * carries its palette, size, accent share, angle and layout number.
 */
import tgpu, { d, type TgpuUniform } from "typegpu";

export const Params = d.struct({
  accent: d.vec4f,
  accent2: d.vec4f,
  amount: d.f32,
  angle: d.f32,
  density: d.f32,
  ground: d.vec4f,
  ink: d.vec4f,
  light: d.vec4f,
  pad: d.f32,
  pattern: d.u32,
  res: d.vec2f,
  seed: d.f32,
  shape: d.vec4f,
  shape2: d.vec4f,
});

// NOTE: the WGSL stays in template strings because the client build has no
// unplugin-typegpu step; the shader is one module and its helpers are tgpu.fn
// externals so TypeGPU resolves names and dead code.
export const buildShader = (P: TgpuUniform<typeof Params>) => {
  const hash21 = tgpu.fn([d.vec2f], d.f32)`(p: vec2f) -> f32 {
    var q = fract(p * vec2f(123.34, 456.21));
    q = q + dot(q, q + vec2f(45.32));
    return fract(q.x * q.y);
  }`;
  const hash22 = tgpu.fn([d.vec2f], d.vec2f)`(p: vec2f) -> vec2f {
    let a = hash21(p);
    return vec2f(a, hash21(p + vec2f(a * 19.19, 7.31)));
  }`.$uses({ hash21 });
  const rot2 = tgpu.fn([d.f32], d.mat2x2f)`(a: f32) -> mat2x2f {
    let c = cos(a); let s = sin(a);
    return mat2x2f(c, s, -s, c);
  }`;
  // Superellipse: the squircle of the mark's table and chairs.
  const sdSq = tgpu.fn([d.vec2f, d.vec2f, d.f32], d.f32)`(p: vec2f, b: vec2f, n: f32) -> f32 {
    let q = max(abs(p) / b, vec2f(1e-4));
    let k = pow(pow(q.x, n) + pow(q.y, n), 1.0 / n);
    return (k - 1.0) * min(b.x, b.y);
  }`;
  const sdBox = tgpu.fn([d.vec2f, d.vec2f, d.f32], d.f32)`(p: vec2f, b: vec2f, r: f32) -> f32 {
    let q = abs(p) - b + vec2f(r);
    return length(max(q, vec2f(0.0))) + min(max(q.x, q.y), 0.0) - r;
  }`;
  const cover = tgpu.fn([d.f32, d.f32], d.f32)`(dist: f32, aa: f32) -> f32 {
    return clamp(0.5 - dist / aa, 0.0, 1.0);
  }`;
  const lum = tgpu.fn([d.vec3f], d.f32)`(c: vec3f) -> f32 {
    return dot(c, vec3f(0.2126, 0.7152, 0.0722));
  }`;
  const onColor = tgpu.fn([d.vec3f], d.vec3f)`(bg: vec3f) -> vec3f {
    let lb = lum(bg);
    return select(P.ink.rgb, P.light.rgb, abs(lum(P.light.rgb) - lb) > abs(lum(P.ink.rgb) - lb));
  }`.$uses({ lum, P });
  const vnoise = tgpu.fn([d.vec2f], d.f32)`(p: vec2f) -> f32 {
    let i = floor(p); let f = fract(p);
    let u = f * f * (3.0 - 2.0 * f);
    let a = hash21(i); let b = hash21(i + vec2f(1.0, 0.0));
    let c = hash21(i + vec2f(0.0, 1.0)); let e = hash21(i + vec2f(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, e, u.x), u.y);
  }`.$uses({ hash21 });
  const fbm = tgpu.fn([d.vec2f], d.f32)`(p: vec2f) -> f32 {
    var v = 0.0; var a = 0.5; var q = p;
    for (var i = 0; i < 5; i++) {
      v = v + a * vnoise(q);
      q = mat2x2f(0.8, 0.6, -0.6, 0.8) * q * 2.03 + vec2f(1.7, 9.2);
      a = a * 0.5;
    }
    return v;
  }`.$uses({ vnoise });

  // Three octaves only: contour lines over full fbm turn into scribbles.
  const relief = tgpu.fn([d.vec2f], d.f32)`(p: vec2f) -> f32 {
    var v = 0.0; var a = 0.5; var q = p;
    for (var i = 0; i < 3; i++) {
      v = v + a * vnoise(q);
      q = mat2x2f(0.8, 0.6, -0.6, 0.8) * q * 2.1 + vec2f(3.1, 5.7);
      a = a * 0.45;
    }
    return v / 0.8;
  }`.$uses({ vnoise });

  const base = { cover, fbm, hash21, hash22, lum, onColor, P, relief, rot2, sdBox, sdSq };

  // Dice: the mark's hover form. Squircle d6 seen from above, with a soft shadow.
  const patDice = tgpu.fn([d.vec2f, d.f32], d.vec3f)`(p: vec2f, aa: f32) -> vec3f {
    var col = P.ground.rgb;
    let s = vec2f(P.seed * 0.0173, P.seed * 0.0219);
    let id = floor(p);
    let f = fract(p) - 0.5;
    if (hash21(id + s) < 0.22) { return col; }
    let jit = (hash22(id + s + vec2f(5.1, 2.7)) - 0.5) * 0.14;
    let m = rot2((hash21(id + s + vec2f(1.1, 9.3)) - 0.5) * 1.3);
    let b = 0.22;
    let c = m * (f - jit);
    let sc = m * (f - jit - vec2f(0.022, -0.038));
    let shade = mix(P.ground.rgb, P.ink.rgb, 0.2);
    col = mix(col, shade, clamp(0.5 - sdSq(sc, vec2f(b), 5.0) / 0.06, 0.0, 1.0) * 0.65);
    let isAccent = hash21(id + s + vec2f(4.4, 4.9)) < P.amount;
    let body = select(P.shape.rgb, P.accent.rgb, isAccent);
    col = mix(col, body, cover(sdSq(c, vec2f(b), 5.0), aa));
    let face = i32(floor(hash21(id + s + vec2f(8.3, 0.6)) * 6.0)) + 1;
    let o = 0.105;
    var pd = 1e3;
    if (face % 2 == 1) { pd = min(pd, length(c)); }
    if (face >= 2) { pd = min(pd, min(length(c - vec2f(-o, o)), length(c - vec2f(o, -o)))); }
    if (face >= 4) { pd = min(pd, min(length(c - vec2f(o, o)), length(c - vec2f(-o, -o)))); }
    if (face == 6) { pd = min(pd, min(length(c - vec2f(-o, 0.0)), length(c - vec2f(o, 0.0)))); }
    col = mix(col, onColor(body), cover(pd - 0.04, aa));
    return col;
  }`.$uses(base);

  // Hex map: terrain from noise in three tones, tokens in the accent, one rare town.
  const patHexes = tgpu.fn([d.vec2f, d.f32], d.vec3f)`(p: vec2f, aa: f32) -> vec3f {
    var col = P.ground.rgb;
    let s = vec2f(P.seed * 0.0113, P.seed * 0.0157);
    let r = vec2f(1.0, 1.7320508);
    let hh = r * 0.5;
    let a = p - r * floor(p / r) - hh;
    let p2 = p - hh;
    let b = p2 - r * floor(p2 / r) - hh;
    var gv = b;
    if (dot(a, a) < dot(b, b)) { gv = a; }
    let id = p - gv;
    let hd = max(abs(gv.x), dot(abs(gv), vec2f(0.5, 0.8660254)));
    let n = fbm(id * 0.33 + s * 40.0);
    if (n < 0.41) {
      col = mix(col, P.shape2.rgb, cover(abs(hd - 0.5) - 0.012, aa) * 0.9);
      return col;
    }
    var land = P.shape2.rgb;
    if (n > 0.51) { land = P.shape.rgb; }
    if (n > 0.6) { land = mix(P.shape.rgb, P.ink.rgb, 0.35); }
    col = mix(col, land, cover(hd - 0.455, aa));
    let t = hash21(id + s + vec2f(3.3, 7.7));
    if (t < P.amount * 0.45) {
      col = mix(col, P.accent.rgb, cover(length(gv) - 0.17, aa));
      col = mix(col, onColor(P.accent.rgb), cover(length(gv) - 0.055, aa));
    } else if (t > 0.95) {
      col = mix(col, P.accent2.rgb, cover(sdSq(gv, vec2f(0.13), 5.0), aa));
    }
    return col;
  }`.$uses(base);

  // Trail map: contour lines with stepped elevation tints and a dashed route
  // between two squircle pins. The route lives in screen space so it always fits.
  const patTrail = tgpu.fn(
    [d.vec2f, d.vec2f, d.f32, d.f32],
    d.vec3f,
  )`(p: vec2f, q: vec2f, aa: f32, aaq: f32) -> vec3f {
    let s = vec2f(P.seed * 0.0131, P.seed * 0.0177) * 40.0;
    let sc = 0.3;
    let h = relief(p * sc + s);
    let e = 0.004;
    let hx = relief((p + vec2f(e, 0.0)) * sc + s);
    let hy = relief((p + vec2f(0.0, e)) * sc + s);
    let g = max(length(vec2f(hx - h, hy - h)) / e, 1e-4);
    let L = 14.0;
    let v = h * L;
    var col = mix(P.ground.rgb, P.shape2.rgb, cover((0.47 - h) / g, aa));
    col = mix(col, mix(P.shape2.rgb, P.shape.rgb, 0.55), cover((0.6 - h) / g, aa));
    let ld = abs(fract(v + 0.5) - 0.5) / (L * g);
    let isIndex = (abs(i32(round(v))) % 5) == 0;
    let lw = select(0.0012, 0.0024, isIndex) * P.density;
    let lineCol = mix(P.ground.rgb, onColor(P.ground.rgb), select(0.3, 0.55, isIndex));
    col = mix(col, lineCol, cover(ld - lw, aa) * smoothstep(0.02, 0.06, g));

    var pts = array<vec2f, 4>(vec2f(-0.6, -0.2), vec2f(-0.22, 0.16), vec2f(0.2, -0.13), vec2f(0.6, 0.18));
    for (var i = 0; i < 4; i++) {
      pts[i] = pts[i] + (hash22(s + vec2f(f32(i) * 3.3, 1.1)) - 0.5) * vec2f(0.12, 0.2);
    }
    var best = 1e3; var bestT = 0.0; var acc = 0.0;
    var prev = pts[0];
    for (var seg = 0; seg < 3; seg++) {
      let p0 = pts[max(seg - 1, 0)]; let p1 = pts[seg]; let p2 = pts[seg + 1]; let p3 = pts[min(seg + 2, 3)];
      for (var k = 1; k <= 12; k++) {
        let t = f32(k) / 12.0; let t2 = t * t; let t3 = t2 * t;
        let cur = 0.5 * ((2.0 * p1) + (p2 - p0) * t + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2 + (3.0 * p1 - p0 - 3.0 * p2 + p3) * t3);
        let pa = q - prev; let ba = cur - prev;
        let hs = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
        let ds = length(pa - ba * hs);
        let sl = length(ba);
        if (ds < best) { best = ds; bestT = acc + sl * hs; }
        acc = acc + sl;
        prev = cur;
      }
    }
    let dash = step(fract(bestT * 24.0), 0.58);
    col = mix(col, P.accent.rgb, cover(best - 0.0048, aaq) * dash);
    let pins = min(sdSq(q - pts[0], vec2f(0.03), 5.0), sdSq(q - pts[3], vec2f(0.03), 5.0));
    col = mix(col, P.accent.rgb, cover(pins, aaq));
    col = mix(col, onColor(P.accent.rgb), cover(pins + 0.019, aaq));
    return col;
  }`.$uses(base);

  // Paths: quarter-circle tiles that join into roads, two-tone regions, accent stops.
  const patPaths = tgpu.fn([d.vec2f, d.f32], d.vec3f)`(p: vec2f, aa: f32) -> vec3f {
    let s = vec2f(P.seed * 0.0141, P.seed * 0.0263);
    let id = floor(p);
    var f = fract(p) - 0.5;
    let flip = hash21(id + s) < 0.5;
    if (flip) { f.x = -f.x; }
    let d1 = length(f - vec2f(0.5));
    let d2 = length(f + vec2f(0.5));
    let inside = (d1 < 0.5) || (d2 < 0.5);
    let par = fract((id.x + id.y) * 0.5) > 0.25;
    let k = (inside != flip) != par;
    var col = select(P.ground.rgb, P.shape2.rgb, k);
    let road = min(abs(d1 - 0.5), abs(d2 - 0.5));
    col = mix(col, P.shape.rgb, cover(road - 0.075, aa));
    let mid = vec2f(0.5 - 0.35355339);
    var sd = 1e3;
    if (hash21(id + s + vec2f(1.7, 3.9)) < P.amount * 0.5) { sd = min(sd, length(f - mid)); }
    if (hash21(id + s + vec2f(6.1, 2.3)) < P.amount * 0.5) { sd = min(sd, length(f + mid)); }
    col = mix(col, P.accent.rgb, cover(sd - 0.1, aa));
    col = mix(col, onColor(P.accent.rgb), cover(sd - 0.035, aa));
    return col;
  }`.$uses(base);

  // Cards: overlapping cards with squircle pips, some face down.
  const patCards = tgpu.fn([d.vec2f, d.f32], d.vec3f)`(p: vec2f, aa: f32) -> vec3f {
    let s = vec2f(P.seed * 0.0157, P.seed * 0.0119);
    var col = P.ground.rgb;
    let base = floor(p);
    var zs: array<f32, 9>;
    var ids: array<vec2f, 9>;
    for (var i = 0; i < 9; i++) {
      let nid = base + vec2f(f32(i % 3) - 1.0, f32(i / 3) - 1.0);
      ids[i] = nid;
      zs[i] = hash21(nid + s + vec2f(2.9, 5.3));
    }
    let accOnLight = select(P.ground.rgb, P.accent.rgb, abs(lum(P.accent.rgb) - lum(P.light.rgb)) > 0.2);
    let edge = mix(P.light.rgb, P.ink.rgb, 0.22);
    let shade = mix(P.ground.rgb, P.ink.rgb, 0.22);
    var last = -1.0;
    for (var n = 0; n < 9; n++) {
      var bi = -1; var bz = 2.0;
      for (var i = 0; i < 9; i++) { if (zs[i] > last && zs[i] < bz) { bz = zs[i]; bi = i; } }
      if (bi < 0) { break; }
      last = bz;
      let nid = ids[bi];
      if (hash21(nid + s) < 0.2) { continue; }
      let ctr = nid + 0.5 + (hash22(nid + s + vec2f(7.3, 1.9)) - 0.5) * 0.5;
      let m = rot2((hash21(nid + s + vec2f(3.7, 8.1)) - 0.5) * 1.1);
      let lc = m * (p - ctr);
      let half = vec2f(0.24, 0.34);
      let sh = sdBox(m * (p - ctr - vec2f(0.02, -0.03)), half, 0.05);
      col = mix(col, shade, clamp(0.5 - sh / 0.07, 0.0, 1.0) * 0.6);
      var face = P.light.rgb;
      if (hash21(nid + s + vec2f(9.9, 0.4)) < 0.35) {
        let stripe = step(0.5, fract((lc.x + lc.y) * 9.0));
        let back = mix(P.shape.rgb, P.shape2.rgb, stripe * 0.6);
        face = mix(P.light.rgb, back, cover(sdBox(lc, half - vec2f(0.04), 0.03), aa));
      } else {
        face = mix(face, edge, cover(abs(sdBox(lc, half - vec2f(0.035), 0.025)) - 0.004, aa));
        let cnt = i32(floor(hash21(nid + s + vec2f(0.7, 6.6)) * 3.0)) + 1;
        let suit = select(P.ink.rgb, accOnLight, hash21(nid + s + vec2f(5.2, 3.3)) < max(P.amount, 0.12));
        var pd = 1e3;
        for (var k = 0; k < 3; k++) {
          if (k < cnt) {
            let y = (f32(k) - (f32(cnt) - 1.0) * 0.5) * 0.14;
            pd = min(pd, sdSq(lc - vec2f(0.0, y), vec2f(0.05), 5.0));
          }
        }
        face = mix(face, suit, cover(pd, aa));
      }
      col = mix(col, face, cover(sdBox(lc, half, 0.05), aa));
    }
    return col;
  }`.$uses(base);

  const vertex = tgpu.vertexFn({
    in: { vi: d.builtin.vertexIndex },
    out: { pos: d.builtin.position },
  })`{
    var corners = array<vec2f, 3>(vec2f(-1.0, -3.0), vec2f(3.0, 1.0), vec2f(-1.0, 1.0));
    return Out(vec4f(corners[in.vi], 0.0, 1.0));
  }`;

  const fragment = tgpu.fragmentFn({ in: { pos: d.builtin.position }, out: d.vec4f })`{
    let res = P.res;
    var q = (in.pos.xy - 0.5 * res) / res.y;
    q.y = -q.y;
    let aaq = 1.25 / res.y;
    let aa = aaq * P.density;
    let off = vec2f(fract(P.seed * 0.618) * 97.0, fract(P.seed * 0.414) * 89.0);
    let p = rot2(P.angle) * q * P.density + off;
    var col = P.ground.rgb;
    switch P.pattern {
      case 0u: { col = patDice(p, aa); }
      case 1u: { col = patHexes(p, aa); }
      case 2u: { col = patTrail(p, q, aa, aaq); }
      case 3u: { col = patPaths(p, aa); }
      case 4u: { col = patCards(p, aa); }
      default: { }
    }
    return vec4f(col, 1.0);
  }`.$uses({ P, patCards, patDice, patHexes, patPaths, patTrail, rot2 });

  return { fragment, vertex };
};
