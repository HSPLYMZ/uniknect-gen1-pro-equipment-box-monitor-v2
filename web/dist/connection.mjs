export async function chooseDevice(bluetooth, name, service) {
  if (typeof bluetooth.getDevices === 'function') {
    try {
      const known = (await withTimeout(bluetooth.getDevices())).filter(device => device.name === name);
      if (known.length === 1) return known[0];
    } catch { /* Fall back to the browser's ordinary device chooser. */ }
  }
  return bluetooth.requestDevice({ filters: [{ name }], optionalServices: [service] });
}

export async function withTimeout(pending, ms = 20000) {
  let timer;
  try {
    return await Promise.race([pending, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new DOMException('BLE operation timed out', 'TimeoutError')), ms);
    })]);
  } finally { clearTimeout(timer); }
}

// A successful startNotifications() is not proof that a packet has arrived.
export class NotificationWatchdog {
  constructor(waitMs = 8000, maxAttempts = 2) {
    this.waitMs = waitMs; this.maxAttempts = maxAttempts; this.reset();
  }
  reset() { this.channels = new Map(); }
  watch(name, characteristic, now) {
    this.channels.set(name, { characteristic, at: now, attempts: 0 });
  }
  received(name, now) {
    const channel = this.channels.get(name);
    if (channel) { channel.at = now; channel.attempts = 0; }
  }
  next(now) {
    for (const [name, channel] of this.channels) {
      if (now - channel.at >= this.waitMs && channel.attempts < this.maxAttempts) {
        channel.at = now; channel.attempts++;
        return { name, characteristic: channel.characteristic };
      }
    }
    return null;
  }
  issue(name, now) {
    const channel = this.channels.get(name);
    if (!channel?.attempts) return '';
    return channel.attempts >= this.maxAttempts && now - channel.at >= this.waitMs
      ? '通知订阅后仍未收到数据，请断开其他蓝牙客户端后重新连接。'
      : '暂未收到通知，正在自动恢复数据订阅…';
  }
}

export async function restartNotifications(characteristic, ensureCurrent, wait = withTimeout) {
  ensureCurrent();
  await wait(characteristic.stopNotifications()); ensureCurrent();
  await wait(characteristic.startNotifications()); ensureCurrent();
}
