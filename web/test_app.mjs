import { test } from 'node:test';
import assert from 'node:assert/strict';

test('connection, real-frame rendering, stale/disconnected states and cleanup', async () => {
  class Element {
    constructor(id) { this.id = id; this.textContent = ''; this.dataset = {}; this.handlers = {}; this.hidden = false; this.child = null; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
    removeEventListener(name, fn) { if (this.handlers[name] === fn) delete this.handlers[name]; }
    querySelector() { return this.child ||= new Element('child'); }
    setAttribute(name, value) { this[name] = value; }
    getBoundingClientRect() { return { width: 300, height: 160 }; }
    getContext() { return new Proxy({}, { get: (obj, key) => obj[key] || (() => {}) }); }
    get parentElement() { return this.parent ||= new Element('parent'); }
  }
  const elements = new Map();
  const el = id => { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); };
  const tx = new Element('tx');
  const poseTx = new Element('poseTx'); poseTx.startNotifications = async () => {};
  poseTx.stopNotifications = async () => {};
  let supportsPose = false, failPose = false;
  const service = { getCharacteristic: async id => {
    if (id !== 0xfff2) return tx;
    if (!supportsPose) throw new DOMException('old firmware','NotFoundError');
    if (failPose) throw new Error('pose fixture');
    return poseTx;
  } };
  let failSubscription = false, pendingSelection = null, pendingConnect = null;
  let envStarts = 0, envStops = 0;
  tx.startNotifications = async () => { envStarts++; if (failSubscription) throw new Error('fixture'); };
  tx.stopNotifications = async () => { envStops++; };
  const device = new Element('board'); device.name = 'UniKnect_V2';
  device.gatt = { connected: false,
    connect: async () => { if (pendingConnect) return pendingConnect; device.gatt.connected = true; return { getPrimaryService: async () => service }; },
    disconnect: () => { device.gatt.connected = false; device.handlers.gattserverdisconnected?.(); }
  };
  const original = { window: globalThis.window, document: globalThis.document,
    navigator: Object.getOwnPropertyDescriptor(globalThis, 'navigator'), interval: globalThis.setInterval, now: Date.now };
  let tick = null, now = 100000;
  globalThis.window = { isSecureContext: true, devicePixelRatio: 1, addEventListener() {} };
  globalThis.document = { getElementById: el };
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { bluetooth: { requestDevice: () => pendingSelection || Promise.resolve(device) } } });
  globalThis.setInterval = fn => { tick = fn; };
  Date.now = () => now;
  const packet = text => {
    const data = Uint8Array.from(text, c => c.charCodeAt(0));
    tx.handlers.characteristicvaluechanged({ target: { value: new DataView(data.buffer) } });
  };
  try {
    await import('./dist/app.mjs');
    assert.equal(el('statusText').textContent, '未连接设备');
    assert.equal(el('packetInfo').textContent, '0 条有效数据');
    await el('connect').handlers.click();
    assert.equal(el('statusText').textContent, '等待设备数据');
    assert.equal(el('temperature').textContent, '—');
    assert.match(el('poseStatus').textContent, /未提供姿态通道/);
    now += 8001; tick();
    await new Promise(setImmediate);
    assert.equal(envStarts, 2);
    assert.equal(envStops, 1);
    assert.match(el('connectionHint').textContent, /自动恢复/);
    packet('01000009F6138832C88F');
    assert.equal(el('temperature').textContent, '25.5');
    assert.equal(el('humidity').textContent, '50.0');
    assert.equal(el('light').textContent, '13000');
    assert.equal(el('lightState').textContent, '暴露 · 红屏');
    assert.equal(el('statusText').textContent, '实时接收中');
    assert.doesNotMatch(el('connectionHint').textContent, /自动恢复/);
    packet('01000009F6138832C88F');
    assert.equal(el('packetInfo').textContent, '1 条有效数据');
    packet('01000209F61388947087');
    assert.equal(el('light').textContent, '38000');
    assert.equal(el('lightState').textContent, '遮挡 · 黑屏');
    assert.equal(el('packetInfo').textContent, '2 条有效数据 · 缺失 1 条');
    packet('corrupt');
    assert.equal(el('light').textContent, '38000');
    assert.equal(el('notice').hidden, false);
    now += 3001; tick();
    assert.equal(el('statusText').textContent, '数据已过期');
    assert.equal(el('metrics').dataset.fresh, false);
    el('disconnect').handlers.click();
    assert.equal(el('statusText').textContent, '已断开连接');
    assert.equal(tx.handlers.characteristicvaluechanged, undefined);
    supportsPose = true;
    await el('connect').handlers.click();
    assert.equal(el('packetInfo').textContent, '0 条有效数据');
    assert.equal(el('temperature').textContent, '—');
    const poseBytes=Uint8Array.from('0200010000000003D501',c=>c.charCodeAt(0));
    poseTx.handlers.characteristicvaluechanged({target:{value:new DataView(poseBytes.buffer)}});
    assert.equal(el('accelZ').textContent,'9.81');
    assert.equal(el('poseStatus').textContent,'实时倾斜姿态');
    now += 1600;
    packet('01000009F6138832C88F'); tick();
    assert.equal(el('statusText').textContent,'实时接收中');
    assert.equal(el('poseStatus').textContent,'姿态数据已过期');
    device.gatt.disconnect();
    assert.equal(poseTx.handlers.characteristicvaluechanged,undefined);
    assert.match(el('poseStatus').textContent,/已断开/);
    assert.equal(el('connect').disabled, false);
    failPose = true;
    await el('connect').handlers.click();
    assert.equal(device.gatt.connected,true);
    assert.match(el('poseStatus').textContent,/订阅未完成/);
    el('disconnect').handlers.click(); failPose = false;
    failSubscription = true;
    await el('connect').handlers.click();
    assert.equal(device.gatt.connected, false);
    assert.equal(tx.handlers.characteristicvaluechanged, undefined);
    assert.match(el('notice').textContent, /连接未完成/);
    failSubscription = false;
    let resolve;
    pendingSelection = new Promise(done => { resolve = done; });
    const selecting = el('connect').handlers.click();
    el('disconnect').handlers.click();
    resolve(device); await selecting;
    assert.equal(device.gatt.connected, false);
    assert.equal(el('connect').disabled, false);
    // A cancelled GATT connect may complete after a new session uses the same device.
    pendingSelection = null;
    let finishOldConnect;
    pendingConnect = new Promise(done => { finishOldConnect = done; });
    const oldConnecting = el('connect').handlers.click();
    await Promise.resolve(); await Promise.resolve();
    el('disconnect').handlers.click();
    pendingConnect = null;
    await el('connect').handlers.click();
    assert.equal(device.gatt.connected, true);
    finishOldConnect({ getPrimaryService: async () => service });
    await oldConnecting;
    assert.equal(device.gatt.connected, true);
    assert.equal(el('statusText').textContent, '等待设备数据');
    el('disconnect').handlers.click();
  } finally {
    globalThis.window = original.window; globalThis.document = original.document;
    if (original.navigator) Object.defineProperty(globalThis, 'navigator', original.navigator);
    else delete globalThis.navigator;
    globalThis.setInterval = original.interval; Date.now = original.now;
  }
});
