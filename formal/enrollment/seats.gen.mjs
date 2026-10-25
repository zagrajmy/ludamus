function word_to_u32(w) {
  let x = 0;
  for (let i = 0; w.$ === "WCon"; i++) {
    x |= Number(w.head) << i;
    w = w.tail;
  }
  return x >>> 0;
}

function u32_to_word(x) {
  let w = {$: "WNil"};
  for (let i = 31; i >= 0; i--) {
    w = {$: "WCon", head: ((x >>> i) & 1) === 1, tail: w};
  }
  return w;
}

function cmp_new(a, b) {
  return {$: a < b ? "LT"
    : a === b ? "EQ" : "GT"};
}

function nat_divmod(a, b) {
  return b === 0 ? {$: "Tuple", fst: 0, snd: a}
    : {$: "Tuple", fst: Math.trunc(a / b), snd: a % b};
}

function nat_chk(n) {
  if (n > 281474976710655) {
    throw "bend: a Nat past the largest immediate 2^48-1";
  }
  return n;
}

function nat_in(n) {
  return Number.isInteger(n) && n >= 0 && n <= 2 ** 53 ? n : nat_chk(1 / 0);
}

function f32_show(x) {
  if (x !== x) {
    return "nan";
  }
  if (!Number.isFinite(x) || Object.is(x, -0)) {
    return x < 0 ? "-inf"
      : x === 0 ? "-0" : "inf";
  }
  let s = "x";
  for (let p = 1; p <= 9 && f32_round(s) !== x; p += 1) {
    s = String(Number(x.toExponential(p - 1)));
  }
  return s;
}

function f32_bits(x) {
  return new Uint32Array(new Float32Array([x]).buffer)[0];
}

function f32_from_bits(u) {
  return new Float32Array(new Uint32Array([u]).buffer)[0];
}

function f32_read(s) {
  const re = /^[\t\n\v\f\r ]*[+-]?((\d+\.?\d*|\.\d+)(e[+-]?\d+)?|inf(inity)?|nan)$/i;
  const v = f32_round(s.replace(/inf\w*/i, "Infinity"));
  return re.test(s) ? {$: "Some", value: v} : {$: "None"};
}

const f32_round = function f32_round(s) {
  const d = Number(s);
  const a = Math.abs(d);
  const f = Math.fround(a);
  const g = 2 * a - Math.min(f, 2 ** 128);
  if (g === f || Math.fround(g) !== g || g === Infinity) {
    return Math.sign(d) * f;
  }
  let k = 0;
  while (a * 2 ** k % 1 !== 0) {
    k += 1;
  }
  const [, i, r, e] = /(\d*)\.?(\d*)(?:e([+-]?\d+))?$/i.exec(s);
  const n = Number(e ?? 0) - r.length;
  const x = BigInt(i + r) * 2n ** BigInt(k) * 10n ** BigInt(Math.max(n, 0));
  const y = BigInt(a * 2 ** k) * 10n ** BigInt(Math.max(-n, 0));
  return Math.sign(d) * (x === y || x > y !== g > f ? f : g);
};

function char_new(code) {
  if (code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF)) {
    throw "bend: " + code + " is not a Unicode scalar value";
  }
  return String.fromCodePoint(code);
}

// Array
// =====

function array_new(d, v) {
  if (d > 31) {
    throw "bend: an array past the deepest block class 31";
  }
  return Array(2 ** d).fill(v);
}

function array_node(a, b) {
  if (a.length !== b.length) {
    throw "bend: runtime fail-stop";
  }
  return a.concat(b);
}

function array_rmw(a, i, f) {
  const at = i % a.length;
  const old = a[at];
  a[at] = f(old);
  return {$: "Tuple", fst: a, snd: old};
}

// Run
// ===

function run_tail(f, x) {
  return {$: "$JMP", f: f.j?.f === f ? f.j : f, x};
}

function run_clo(j) {
  const f = (x) => run_loop(j(x));
  f.j = j;
  j.f = f;
  return f;
}

function run_loop(r) {
  while (r !== null && typeof r === "object" && r.$ === "$JMP") {
    r = r.f(r.x);
  }
  return r;
}

function run_lib(f, n) {
  return (...a) => a.length < n ? run_lib((...b) => f(...a, ...b), n - a.length)
    : run_loop(f(...a));
}

// Effect
// ======

const $0eff = Object.create(null);

function io_eff(k, run) {
  if (arguments.length > 2) {
    throw new Error("bend: " + k + " takes no need: an effect that waits parks itself");
  }
  if (k in $0eff) {
    throw new Error("bend: two effects register " + k);
  }
  $0eff[k] = run;
}
// Program
// =======

function $start$() {
  return {$: "Seats", "taken": 0, "held": {$: "None"}};
}

function $taken$(_s_0) {
  const _t_0 = _s_0["taken"];
  return _t_0;
}

function $fits$(_limit_0, _taken_0, _want_0) {
  return $Nat$is_le$(nat_chk(_taken_0 + _want_0), _limit_0);
}

function $reserve$(_ok_0, _taken_0, _want_0) {
  if (_ok_0) {
    return {$: "Seats", "taken": _taken_0, "held": {$: "Some", "value": _want_0}};
  } else {
    return {$: "Seats", "taken": _taken_0, "held": {$: "None"}};
  }
}

function $check$(_limit_0, _taken_0, _held_0, _want_0) {
  if (_held_0.$ === "None") {
    return $reserve$(($fits$(_limit_0, _taken_0, _want_0)), _taken_0, _want_0);
  } else {
    const _k_0 = _held_0["value"];
    return {$: "Seats", "taken": _taken_0, "held": {$: "Some", "value": _k_0}};
  }
}

function $commit$(_taken_0, _held_0) {
  if (_held_0.$ === "None") {
    return {$: "Seats", "taken": _taken_0, "held": {$: "None"}};
  } else {
    const _k_0 = _held_0["value"];
    return {$: "Seats", "taken": nat_chk(_taken_0 + _k_0), "held": {$: "None"}};
  }
}

function $free$(_taken_0, _held_0) {
  if (_taken_0 === 0) {
    return {$: "Seats", "taken": 0, "held": _held_0};
  } else {
    const _t_0 = (_taken_0 - 1);
    return {$: "Seats", "taken": _t_0, "held": _held_0};
  }
}

function $step$(_limit_0, _s_0, _e_0) {
  const _t_0 = _s_0["taken"];
  const _h_0 = _s_0["held"];
  if (_e_0.$ === "Check") {
    const _want_0 = _e_0["want"];
    return $check$(_limit_0, _t_0, _h_0, _want_0);
  } else if (_e_0.$ === "Commit") {
    return $commit$(_t_0, _h_0);
  } else if (_e_0.$ === "Free") {
    return $free$(_t_0, _h_0);
  } else if (_e_0.$ === "Claim") {
    return {$: "Seats", "taken": _t_0, "held": _h_0};
  } else {
    return {$: "Seats", "taken": _t_0, "held": _h_0};
  }
}

function $replay$($0, $1, $2) {
  for (;;) {
    {
      const _ops_0 = $0;
      const _limit_0 = $1;
      const _s_0 = $2;
      if (_ops_0.$ === "Nil") {
        return _s_0;
      } else {
        const _e_0 = _ops_0["head"];
        const _rest_0 = _ops_0["tail"];
        $0 = _rest_0;
        $1 = _limit_0;
        $2 = ($step$(_limit_0, _s_0, _e_0));
        continue;
      }
    }
  }
}

function $Nat$is_le$(_a_0, _b_0) {
  return $Cmp$is_le$(cmp_new(_a_0, _b_0));
}

function $Cmp$is_le$(_c_0) {
  if (_c_0.$ === "GT") {
    return false;
  } else {
    return true;
  }
}
export default {
  "start": run_lib(() => $start$(), 0),
  "taken": run_lib((a0) => $taken$(a0), 1),
  "fits": run_lib((a0,a1,a2) => $fits$(nat_in(a0),nat_in(a1),nat_in(a2)), 3),
  "reserve": run_lib((a0,a1,a2) => $reserve$(a0,nat_in(a1),nat_in(a2)), 3),
  "check": run_lib((a0,a1,a2,a3) => $check$(nat_in(a0),nat_in(a1),a2,nat_in(a3)), 4),
  "commit": run_lib((a0,a1) => $commit$(nat_in(a0),a1), 2),
  "free": run_lib((a0,a1) => $free$(nat_in(a0),a1), 2),
  "step": run_lib((a0,a1,a2) => $step$(nat_in(a0),a1,a2), 3),
  "replay": run_lib((a0,a1,a2) => $replay$(a0,nat_in(a1),a2), 3),
};
