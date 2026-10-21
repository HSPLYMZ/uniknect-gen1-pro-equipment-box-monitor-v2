// Gravity-constrained tilt. This deliberately does not estimate heading or position.
export function decodePose(input) {
  const bytes = input instanceof DataView ? new Uint8Array(input.buffer, input.byteOffset, input.byteLength) : input;
  if (!(bytes instanceof Uint8Array) || bytes.length !== 20) throw new Error('姿态帧长度不正确');
  const text = String.fromCharCode(...bytes);
  if (!/^02[0-9a-f]{18}$/i.test(text)) throw new Error('姿态帧格式不正确');
  const seq = parseInt(text.slice(2, 6), 16), flags = parseInt(text.slice(18), 16);
  if (flags & ~1) throw new Error('姿态标记不正确');
  const vector = [6, 10, 14].map(offset => {
    const v = parseInt(text.slice(offset, offset + 4), 16);
    return (v & 0x8000 ? v - 65536 : v) / 100;
  });
  if (flags & 1 && vector.some(v => Math.abs(v) > 160)) throw new Error('加速度超出范围');
  return { seq, vector: flags & 1 ? vector : null };
}

export function tiltFromGravity(vector, previousRoll = 0) {
  if (!Array.isArray(vector) || vector.length !== 3 || vector.some(v => !Number.isFinite(v))) return null;
  const [x, y, z] = vector, norm = Math.hypot(x, y, z);
  if (norm < 1 || vector.some(v => Math.abs(v) > 160)) return null;
  const pitch = Math.atan2(-x, Math.hypot(y, z));
  // At the +/-X poles roll is unobservable; retain its last representative.
  let roll = Math.hypot(y, z) < 0.03 * norm ? previousRoll : Math.atan2(y, z);
  while (roll - previousRoll > Math.PI) roll -= Math.PI * 2;
  while (roll - previousRoll < -Math.PI) roll += Math.PI * 2;
  return { roll, pitch, norm, disturbed: Math.abs(norm - 9.80665) > 1.5 };
}

export class TiltFilter {
  constructor() { this.reset(); }
  reset() { this.vector = null; this.at = null; this.roll = 0; }
  update(vector, at) {
    const raw = tiltFromGravity(vector, this.roll);
    if (!raw) { this.reset(); return null; }
    const dt = this.at === null ? Infinity : Math.max(0, at - this.at);
    const alpha = 1 - Math.exp(-dt / 100);
    // Do not average two opposite faces through a near-zero vector.
    const dot = this.vector ? this.vector.reduce((s, v, i) => s + v * vector[i], 0) : 1;
    this.vector = !this.vector || dt > 1500 || dot < 0 ? vector.slice()
      : this.vector.map((v, i) => v + alpha * (vector[i] - v));
    this.at = at;
    const result = tiltFromGravity(this.vector, this.roll);
    if (result) this.roll = result.roll;
    return result ? { ...result, disturbed: raw.disturbed } : null;
  }
}
