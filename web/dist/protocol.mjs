export const SERVICE = 0xfff0;
export const TELEMETRY = 0xfff1;
export const POSE = 0xfff2;
export const DEVICE_NAME = 'UniKnect_V2';

export function decodeFrame(input) {
  const bytes = input instanceof DataView
    ? new Uint8Array(input.buffer, input.byteOffset, input.byteLength)
    : input;
  if (!(bytes instanceof Uint8Array) || bytes.length !== 20) throw new Error('数据长度不正确');
  const text = String.fromCharCode(...bytes);
  if (!/^[0-9a-f]{20}$/i.test(text)) throw new Error('数据格式不正确');
  if (text.slice(0, 2) !== '01') throw new Error('设备协议版本不匹配');
  const n = (start, length = 4) => parseInt(text.slice(start, start + length), 16);
  const seq = n(2), rawT = n(6), rawH = n(10), rawL = n(14), flags = n(18, 2);
  const t = (rawT & 0x8000 ? rawT - 65536 : rawT) / 100;
  const h = rawH / 100;
  if ((flags & 1) && (t < -40 || t > 85)) throw new Error('温度数据超出范围');
  if ((flags & 2) && h > 100) throw new Error('湿度数据超出范围');
  return { seq, temperature: flags & 1 ? t : null, humidity: flags & 2 ? h : null,
    light: flags & 4 ? rawL : null, exposed: Boolean(flags & 8), tilted: Boolean(flags & 16),
    hot: Boolean(flags & 32), humid: Boolean(flags & 64), calibrated: Boolean(flags & 128) };
}

export function sequenceGap(previous, current) {
  if (previous === null) return { accept: true, missed: 0 };
  const distance = (current - previous + 65536) % 65536;
  return { accept: distance > 0 && distance < 32768, missed: distance > 0 && distance < 32768 ? distance - 1 : 0 };
}

export function freshness(connected, receivedAt, now = Date.now()) {
  if (!connected) return 'disconnected';
  if (!receivedAt) return 'waiting';
  return now - receivedAt > 3000 ? 'stale' : 'live';
}
