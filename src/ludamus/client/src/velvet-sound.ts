// Velvet — procedural UI sound, ported from the Velvet UI sound design system
// (velvet-ui-eight.vercel.app). There are no audio files: every sound is
// synthesised on the fly with the Web Audio API from the "velvet" voice preset
// (warm, soft, material) plus a small set of role definitions.
//
// Design principles carried over from the source: sound is a bonus layer, never
// the message. It is opt-in, off by default, and the preference persists across
// sessions in localStorage. Triggers jitter pitch, volume and timing so no two
// hits sound identical.

const STORAGE_KEY = "velvet-sound.enabled";

type Waveform = OscillatorType;
type FilterShape = "bandpass" | "lowpass";

interface Voice {
  attackMs: number;
  baseHz: number;
  bodyDropPct: number;
  bodyLp: number;
  click: number;
  clickHz?: number;
  clickMs?: number;
  decayMs: number;
  layerSpreadMs: number;
  ping: number;
  pingHz?: number;
  pitchVarPct: number;
  reverbWet: number;
  sub: number;
  transient: { amt: number; hz: number; ms: number; shape: FilterShape };
  volJitterPct: number;
  waveform: Waveform;
}

interface Hit {
  dt?: number;
  gain?: number;
  glide?: number;
  pitch?: number;
}

interface Role {
  decay?: number;
  hits: Hit[];
  reverb?: number;
  sub?: number;
  transient?: number;
}

// The "velvet" voice: low fundamental, long soft decay, heavy sub, generous
// reverb, no click/ping. (The source ships Signature and Crisp too; we only
// want Velvet here.)
const VELVET: Voice = {
  attackMs: 8,
  baseHz: 104,
  bodyDropPct: 7,
  bodyLp: 520,
  click: 0,
  decayMs: 72,
  layerSpreadMs: 10,
  ping: 0,
  pitchVarPct: 7,
  reverbWet: 0.42,
  sub: 0.57,
  transient: { amt: 0.12, hz: 260, ms: 18, shape: "lowpass" },
  volJitterPct: 12,
  waveform: "sine",
};

const ROLES: Record<string, Role> = {
  "action.send": {
    decay: 0.82,
    hits: [{ gain: 0.62, glide: 1.22, pitch: 1.1 }],
    sub: 0.3,
    transient: 0.6,
  },
  "state.error": {
    decay: 0.82,
    hits: [
      { gain: 0.56, glide: 0.86, pitch: 0.64 },
      { dt: 0.07, gain: 0.4, glide: 0.78, pitch: 0.46 },
    ],
    reverb: 0.16,
    sub: 0.72,
    transient: 0.14,
  },
  "toast.in": {
    decay: 1.34,
    hits: [
      { dt: 0.012, gain: 0.38, glide: 0.98, pitch: 1.24 },
      { dt: 0.078, gain: 0.25, glide: 0.9, pitch: 0.92 },
    ],
    reverb: 1.55,
    sub: 0.12,
    transient: 0.1,
  },
  "toggle.off": {
    decay: 0.32,
    hits: [{ gain: 0.48, glide: 0.97, pitch: 0.86 }],
    sub: 0.34,
    transient: 0.5,
  },
  "toggle.on": {
    decay: 0.3,
    hits: [{ gain: 0.5, glide: 1.03, pitch: 1.15 }],
    sub: 0.3,
    transient: 0.56,
  },
  "ui.confirm": {
    decay: 1.66,
    hits: [
      { gain: 0.58, glide: 1.03, pitch: 1.04 },
      { dt: 0.1, gain: 0.54, glide: 1.1, pitch: 1.64 },
    ],
    reverb: 0.9,
    sub: 0.32,
    transient: 0.5,
  },
  "ui.progress": {
    decay: 0.42,
    hits: [{ gain: 0.18, pitch: 0.92 }],
    reverb: 0.35,
    sub: 0.15,
    transient: 0.2,
  },
};

export type SoundRole = keyof typeof ROLES;

const isRole = (value: string): value is SoundRole => value in ROLES;

const rand = (min: number, max: number): number =>
  min + Math.random() * (max - min);

class VelvetEngine {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private reverb: ConvolverNode | null = null;
  private noise: AudioBuffer | null = null;

  private build(): void {
    if (this.ctx) return;
    const Ctor =
      globalThis.AudioContext ??
      (globalThis as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctor) return;

    const ctx = new Ctor();
    const compressor = ctx.createDynamicsCompressor();
    compressor.connect(ctx.destination);

    const master = ctx.createGain();
    master.gain.value = 1;
    master.connect(compressor);

    // Short, dark reverb tail from a decaying noise impulse.
    const tailLen = Math.floor(0.1 * ctx.sampleRate);
    const impulse = ctx.createBuffer(2, tailLen, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const data = impulse.getChannelData(ch);
      for (let i = 0; i < tailLen; i++) {
        data[i] = (2 * Math.random() - 1) * Math.pow(1 - i / tailLen, 3);
      }
    }
    const reverb = ctx.createConvolver();
    reverb.buffer = impulse;
    const reverbLp = ctx.createBiquadFilter();
    reverbLp.type = "lowpass";
    reverbLp.frequency.value = 2200;
    reverb.connect(reverbLp);
    reverbLp.connect(compressor);

    // White-noise buffer reused for transients and clicks.
    const noiseLen = Math.floor(0.2 * ctx.sampleRate);
    const noise = ctx.createBuffer(1, noiseLen, ctx.sampleRate);
    const noiseData = noise.getChannelData(0);
    for (let i = 0; i < noiseLen; i++) noiseData[i] = 2 * Math.random() - 1;

    this.ctx = ctx;
    this.master = master;
    this.reverb = reverb;
    this.noise = noise;
  }

  resume(): void {
    this.build();
    if (this.ctx?.state === "suspended") void this.ctx.resume();
  }

  play(role: SoundRole): void {
    this.build();
    const { ctx } = this;
    if (!ctx) return;
    const def = ROLES[role];
    if (!def) return;
    const t0 = ctx.currentTime + 0.002;
    for (const hit of def.hits) {
      this.scheduleHit(t0 + (hit.dt ?? 0), VELVET, def, hit);
    }
    globalThis.dispatchEvent(new CustomEvent("uisound", { detail: { role } }));
  }

  private scheduleHit(time: number, v: Voice, def: Role, hit: Hit): void {
    const { ctx, master, noise, reverb } = this;
    if (!ctx || !master || !reverb || !noise) return;

    const pitchVar = rand(-v.pitchVarPct, v.pitchVarPct) / 100;
    const freq = v.baseHz * (hit.pitch ?? 1) * (1 + pitchVar);
    const gain =
      0.8 * (hit.gain ?? 1) * (1 + rand(-v.volJitterPct, v.volJitterPct) / 100);
    const attack = Math.max(0.001, v.attackMs / 1000);
    const decay = (v.decayMs / 1000) * (def.decay ?? 1);
    const spread = Math.max(0, (v.layerSpreadMs + rand(-1, 1)) / 1000);
    const transientAmt = v.transient.amt * (def.transient ?? 1);
    const subAmt = v.sub * (def.sub ?? 1);
    const reverbWet = Math.min(0.6, v.reverbWet * (def.reverb ?? 1));

    const bus = ctx.createGain();
    bus.gain.value = 1;
    bus.connect(master);
    if (reverbWet > 0.001) {
      const send = ctx.createGain();
      send.gain.value = reverbWet;
      bus.connect(send);
      send.connect(reverb);
    }

    // Soft attack transient.
    if (transientAmt > 0.02) {
      const src = ctx.createBufferSource();
      src.buffer = noise;
      const filter = ctx.createBiquadFilter();
      filter.type = v.transient.shape;
      filter.frequency.value = v.transient.hz;
      filter.Q.value = v.transient.shape === "lowpass" ? 0.5 : 0.8;
      const env = ctx.createGain();
      env.gain.setValueAtTime(transientAmt * gain * 0.6, time);
      env.gain.exponentialRampToValueAtTime(1e-4, time + v.transient.ms / 1000);
      src.connect(filter);
      filter.connect(env);
      env.connect(bus);
      src.start(time);
      src.stop(time + 0.06);
    }

    // Body oscillator with a downward pitch glide.
    const bodyStart = time + spread;
    const osc = ctx.createOscillator();
    osc.type = v.waveform;
    osc.frequency.setValueAtTime(freq, bodyStart);
    const endFreq = hit.glide
      ? freq * hit.glide
      : Math.max(40, freq * (1 - v.bodyDropPct / 100));
    osc.frequency.exponentialRampToValueAtTime(
      endFreq,
      bodyStart + attack + 0.7 * decay,
    );
    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = v.bodyLp;
    lp.Q.value = 0.5;
    const bodyEnv = ctx.createGain();
    bodyEnv.gain.setValueAtTime(0, bodyStart);
    bodyEnv.gain.linearRampToValueAtTime(gain, bodyStart + attack);
    bodyEnv.gain.exponentialRampToValueAtTime(1e-4, bodyStart + attack + decay);
    osc.connect(lp);
    lp.connect(bodyEnv);
    bodyEnv.connect(bus);
    osc.start(bodyStart);
    osc.stop(bodyStart + attack + decay + 0.05);

    // Sub octave for warmth.
    if (subAmt > 0.01) {
      const subStart = time + 2 * spread;
      const sub = ctx.createOscillator();
      sub.type = "sine";
      sub.frequency.value = freq / 2;
      const subEnv = ctx.createGain();
      subEnv.gain.setValueAtTime(0, subStart);
      subEnv.gain.linearRampToValueAtTime(subAmt * gain, subStart + attack);
      subEnv.gain.exponentialRampToValueAtTime(1e-4, subStart + attack + decay);
      sub.connect(subEnv);
      subEnv.connect(bus);
      sub.start(subStart);
      sub.stop(subStart + attack + decay + 0.05);
    }
  }
}

const engine = new VelvetEngine();

const isEnabled = (): boolean => localStorage.getItem(STORAGE_KEY) === "1";

const setEnabled = (on: boolean): void => {
  localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  if (on) {
    engine.resume();
    engine.play("ui.confirm");
  }
  syncToggles();
};

const play = (role: SoundRole): void => {
  if (!isEnabled()) return;
  engine.play(role);
};

// Auditions a sound regardless of the global on/off — for explicit "play this"
// triggers such as the design-page showcase.
const preview = (role: SoundRole): void => {
  engine.resume();
  engine.play(role);
};

// --- Public API ------------------------------------------------------------

interface VelvetSoundApi {
  readonly enabled: boolean;
  play: (role: SoundRole) => void;
  preview: (role: SoundRole) => void;
  setEnabled: (on: boolean) => void;
  toggle: () => void;
}

const api: VelvetSoundApi = {
  get enabled() {
    return isEnabled();
  },
  play,
  preview,
  setEnabled,
  toggle: () => setEnabled(!isEnabled()),
};

(globalThis as unknown as { velvetSound: VelvetSoundApi }).velvetSound = api;

// --- Toggle control --------------------------------------------------------

const syncToggles = (): void => {
  const on = isEnabled();
  for (const el of document.querySelectorAll<HTMLElement>(
    "[data-velvet-toggle]",
  )) {
    el.setAttribute("aria-pressed", on ? "true" : "false");
  }
};

// --- Auto-wiring -----------------------------------------------------------

const SUBMIT_SELECTOR =
  'button[type="submit"], button:not([type]), [type="submit"]';
const CLICK_SELECTOR = 'a[href], button, [role="button"], summary';

const wire = (): void => {
  syncToggles();

  // The toggle button flips the persisted preference; data-velvet-play buttons
  // audition a specific sound (the design-page showcase).
  document.addEventListener("click", (event) => {
    const { target } = event;
    if (!(target instanceof Element)) return;
    if (target.closest("[data-velvet-toggle]")) {
      api.toggle();
      return;
    }
    const audition = target.closest<HTMLElement>("[data-velvet-play]");
    const role = audition?.dataset.velvetPlay;
    if (role && isRole(role)) preview(role);
  });

  // Soft tap on interactive controls. Submit controls are skipped here so the
  // submit handler plays the richer action.send instead of doubling up.
  document.addEventListener(
    "pointerdown",
    (event) => {
      const { target } = event;
      if (!(target instanceof Element)) return;
      if (
        target.closest(
          "[data-velvet-toggle], [data-velvet-play], [data-no-sound]",
        )
      )
        return;
      const control = target.closest(CLICK_SELECTOR);
      if (!control) return;
      if (control.closest("form") && control.matches(SUBMIT_SELECTOR)) return;
      play("toggle.on");
    },
    true,
  );

  // Form submissions get the action sound.
  document.addEventListener(
    "submit",
    (event) => {
      if (event.target instanceof HTMLFormElement) play("action.send");
    },
    true,
  );

  // Checkbox / switch flips.
  document.addEventListener("change", (event) => {
    const { target } = event;
    if (target instanceof HTMLInputElement && target.type === "checkbox") {
      play(target.checked ? "toggle.on" : "toggle.off");
    }
  });

  // Server-rendered flash messages announce themselves once on load.
  const alert = document.querySelector(".alert");
  if (alert) {
    if (alert.classList.contains("alert-danger")) play("state.error");
    else if (alert.classList.contains("alert-success")) play("ui.confirm");
    else play("toast.in");
  }

  // Cross-tab preference sync.
  globalThis.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) syncToggles();
  });
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}
