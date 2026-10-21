import { DEVICE_NAME, SERVICE, TELEMETRY, POSE, decodeFrame, sequenceGap, freshness } from './protocol.mjs';
import { withTimeout, chooseDevice, NotificationWatchdog, restartNotifications } from './connection.mjs?v=20261021-notify';
import { createPosePanel } from './pose.mjs?v=20261021-notify';

const $ = id => document.getElementById(id);
const connectButton = $('connect'), disconnectButton = $('disconnect');
const posePanel = createPosePanel();
let poseCharacteristic = null, poseListener = null;
let device = null, characteristic = null, notificationListener = null, disconnectListener = null;
let generation = 0, connected = false, connecting = false, receivedAt = 0, previousSeq = null;
let received = 0, missed = 0, invalid = 0, history = [], latest = null, lastChartDraw = 0;
let stateOverride = '';
const notificationHealth = new NotificationWatchdog();
let settingUpNotifications = false, recoveringNotifications = false;
const windowMs = 300_000;
const timeText = time => new Date(time).toLocaleTimeString('zh-CN', { hour12: false });

function notice(text = '') { $('notice').textContent = text; $('notice').hidden = !text; }
function environmentIssue() {
  if (!window.isSecureContext) return '此页面需要通过 HTTPS 打开。电脑本机调试可使用 localhost；手机访问普通局域网 HTTP 地址无法连接蓝牙。';
  if (!navigator.bluetooth) return '当前浏览器不支持网页蓝牙。请复制页面地址，在安卓 Chrome 或带蓝牙的电脑 Chrome 中打开。';
  return '';
}

function updateStatus() {
  const state = connecting ? 'connecting' : freshness(connected, receivedAt);
  const names = { disconnected: receivedAt ? '已断开连接' : '未连接设备', connecting: '正在连接', waiting: '等待设备数据', stale: '数据已过期', live: '实时接收中' };
  $('statusPill').dataset.state = state;
  $('statusText').textContent = names[state];
  $('metrics').dataset.fresh = state === 'live';
  $('sessionDot').dataset.live = state === 'live';
  connectButton.disabled = connecting || connected || Boolean(environmentIssue());
  disconnectButton.disabled = !connecting && !connected;
  connectButton.querySelector('span').textContent = connecting ? '正在连接…' : '连接设备';
  $('updatedAt').textContent = receivedAt ? `${state === 'live' ? '更新于' : '最后更新'} ${timeText(receivedAt)}` : '等待第一条设备数据';
  if (connecting) $('connectionHint').textContent = '请在浏览器弹窗中选择 UniKnect_V2，保持设备在附近。';
  else if (connected) $('connectionHint').textContent = notificationHealth.issue('environment', Date.now()) || (state === 'waiting' ? '蓝牙已连接，正在等待第一条有效数据…' : state === 'stale' ? '已超过 3 秒没有新数据，请保持页面前台或断开后重连。' : '已订阅实时数据，温湿度与光敏约每秒更新。');
  else $('connectionHint').textContent = stateOverride || '使用安卓或电脑 Chrome，点击右侧按钮选择 UniKnect_V2。';
  $('packetInfo').textContent = `${received} 条有效数据${missed ? ` · 缺失 ${missed} 条` : ''}${invalid ? ` · 异常 ${invalid} 条` : ''}`;
  $('sessionText').textContent = state === 'live' ? '数据来自当前连接的开发板' : state === 'stale' ? '旧值已灰显，等待新数据' : state === 'waiting' ? '连接成功，等待采样' : receivedAt ? '已停止更新，保留最后一次读数' : '本次尚未接收数据';
}

function showValues(frame) {
  for (const key of ['temperature', 'humidity', 'light']) {
    const v = frame[key];
    $(key).textContent = v === null ? '—' : key === 'light' ? String(v) : v.toFixed(1);
  }
  $('temperatureState').textContent = frame.temperature === null ? '传感器无有效数据' : frame.hot ? '高温告警' : '读数正常';
  $('humidityState').textContent = frame.humidity === null ? '传感器无有效数据' : frame.humid ? '高湿告警' : '读数正常';
  $('lightState').textContent = frame.light === null ? '光敏无有效数据' : frame.exposed ? '暴露 · 红屏' : '遮挡 · 黑屏';
  $('lightState').dataset.exposed = frame.light === null ? 'unknown' : String(frame.exposed);
}

function receive(event, token) {
  if (token !== generation || !connected) return;
  try {
    const frame = decodeFrame(event.target.value);
    const order = sequenceGap(previousSeq, frame.seq);
    if (!order.accept) return;
    previousSeq = frame.seq;
    missed += order.missed;
    received++;
    receivedAt = Date.now();
    notificationHealth.received('environment', receivedAt);
    latest = frame;
    history.push({ ...frame, at: receivedAt, breakBefore: order.missed > 0 });
    history = history.filter(point => point.at >= receivedAt - windowMs).slice(-300);
    showValues(frame);
    notice();
    updateStatus();
    drawCharts();
  } catch {
    invalid++;
    notice('收到的数据暂时无法识别。请确认运行的是 UniKnect V2，重新连接后再试。');
    updateStatus();
  }
}

function release({ disconnect = true } = {}) {
  generation++;
  const oldDevice = device;
  if (characteristic && notificationListener) characteristic.removeEventListener('characteristicvaluechanged', notificationListener);
  if (poseCharacteristic && poseListener) poseCharacteristic.removeEventListener('characteristicvaluechanged', poseListener);
  poseCharacteristic = null; poseListener = null; posePanel.disconnect();
  if (oldDevice && disconnectListener) oldDevice.removeEventListener('gattserverdisconnected', disconnectListener);
  characteristic = null; notificationListener = null; disconnectListener = null; device = null;
  connected = false; connecting = false;
  notificationHealth.reset(); settingUpNotifications = false; recoveringNotifications = false;
  if (disconnect && oldDevice?.gatt?.connected) oldDevice.gatt.disconnect();
}

async function recoverNotifications() {
  if (!connected || connecting || settingUpNotifications || recoveringNotifications || document.visibilityState === 'hidden') return;
  const due = notificationHealth.next(Date.now());
  if (!due) return;
  const token = generation;
  const ensureCurrent = () => {
    if (token !== generation || !connected) throw new DOMException('Cancelled', 'AbortError');
  };
  recoveringNotifications = true;
  try { await restartNotifications(due.characteristic, ensureCurrent); }
  catch { /* Bounded retry; never display cached values as newly received data. */ }
  finally { if (token === generation) { recoveringNotifications = false; updateStatus(); } }
}

async function connect() {
  if (connecting || connected) return;
  const issue = environmentIssue();
  if (issue) { notice(issue); return; }
  release();
  const token = generation;
  connecting = true; stateOverride = ''; notice(); updateStatus();
  let selected = null;
  let stage = '选择设备';
  const closeSuperseded = () => {
    // A late completion for the same BLEDevice must not disconnect its new session.
    if (selected && selected !== device && selected.gatt?.connected) selected.gatt.disconnect();
  };
  const ensureCurrent = () => {
    if (token !== generation) { closeSuperseded(); throw new DOMException('Cancelled', 'AbortError'); }
  };
  const waitFor = async (pending, label) => {
    stage = label;
    pending.then(() => { if (token !== generation) closeSuperseded(); }, () => {});
    return withTimeout(pending);
  };
  try {
    selected = await chooseDevice(navigator.bluetooth, DEVICE_NAME, SERVICE);
    ensureCurrent();
    device = selected;
    disconnectListener = () => {
      if (token !== generation) return;
      release({ disconnect: false });
      stateOverride = '连接已断开。请保持设备供电，点击“连接设备”重新连接。';
      updateStatus(); drawCharts();
    };
    selected.addEventListener('gattserverdisconnected', disconnectListener);
    const server = await waitFor(selected.gatt.connect(), '建立蓝牙连接'); ensureCurrent();
    const service = await waitFor(server.getPrimaryService(SERVICE), '读取设备服务'); ensureCurrent();
    const tx = await waitFor(service.getCharacteristic(TELEMETRY), '读取数据通道'); ensureCurrent();
    // Every session starts fresh; old listeners and sequence numbers are discarded.
    receivedAt = 0; previousSeq = null; received = 0; missed = 0; invalid = 0; history = []; latest = null;
    showValues({ temperature: null, humidity: null, light: null });
    characteristic = tx;
    notificationListener = event => receive(event, token);
    tx.addEventListener('characteristicvaluechanged', notificationListener);
    connected = true;
    posePanel.connect();
    settingUpNotifications = true;
    await waitFor(tx.startNotifications(), '订阅实时数据'); ensureCurrent();
    notificationHealth.watch('environment', tx, Date.now());
    connecting = false;
    $('deviceName').textContent = selected.name || DEVICE_NAME;
    updateStatus(); drawCharts();
    // Optional on older V2 devices. A pose failure does not discard environment data.
    try {
      const poseTx = await waitFor(service.getCharacteristic(POSE), '读取姿态通道'); ensureCurrent();
      poseCharacteristic = poseTx;
      poseListener = event => {
        if (token === generation && connected && posePanel.receive(event)) notificationHealth.received('pose', Date.now());
      };
      poseTx.addEventListener('characteristicvaluechanged', poseListener);
      posePanel.available();
      await waitFor(poseTx.startNotifications(), '订阅姿态数据'); ensureCurrent();
      notificationHealth.watch('pose', poseTx, Date.now());
    } catch (error) {
      if (token !== generation) return;
      if (poseCharacteristic && poseListener) poseCharacteristic.removeEventListener('characteristicvaluechanged', poseListener);
      poseCharacteristic = null; poseListener = null;
      posePanel.unavailable(error.name === 'NotFoundError' ? undefined : '姿态通道订阅未完成，请重新连接；环境数据仍可使用');
    }
    settingUpNotifications = false;
  } catch (error) {
    if (token !== generation) return;
    release();
    if (error.name === 'TimeoutError') notice(`“${stage}”等待超时。请断开其他客户端并靠近开发板，再重新连接。`);
    else if (error.name === 'NotFoundError') notice(stage === '选择设备'
      ? '未选择到设备。请确认 V2 正在广播，并靠近开发板后重试。'
      : '设备缺少需要的蓝牙服务或数据通道。请确认板子运行 V2，清除旧配对后重试。');
    else if (error.name === 'SecurityError' || error.name === 'NotAllowedError') notice('蓝牙访问未获允许。请检查浏览器和系统的附近设备权限，在安卓 Chrome 中重新连接。');
    else if (error.name !== 'AbortError') notice(`连接未完成（${stage}）。请先断开其他蓝牙客户端，确认板子运行 V2，再重试。`);
    updateStatus();
  }
}

const chartConfigs = [
  ['temperature', '#f3b28a', [0, 40], '温度'],
  ['humidity', '#8bc7f4', [0, 100], '湿度'],
  ['light', '#e6cf8d', [0, 65535], '光敏原始值']
];
function drawCharts() {
  const now = Date.now(); lastChartDraw = now;
  for (const [key, color, fallback, label] of chartConfigs) {
    const canvas = $(`${key}Chart`), bounds = canvas.getBoundingClientRect();
    const width = bounds.width, height = bounds.height;
    if (!width || !height) continue;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
    const left = 36, right = width - 5, top = 8, bottom = height - 7;
    const points = history.filter(point => point.at >= now - windowMs);
    const valid = points.filter(point => point[key] !== null);
    const empty = canvas.parentElement.querySelector('.plot-empty');
    empty.hidden = valid.length > 0;
    empty.textContent = history.length ? '暂时没有有效读数' : '连接设备后开始记录';
    let [low, high] = fallback;
    if (valid.length && key === 'temperature') {
      const vals = valid.map(point => point[key]);
      low = Math.floor(Math.min(...vals) - 1); high = Math.ceil(Math.max(...vals) + 1);
    }
    ctx.lineWidth = 1; ctx.font = '9px "Segoe UI", sans-serif'; ctx.textAlign = 'right';
    for (let i = 0; i < 4; i++) {
      const y = top + (bottom - top) * i / 3, value = high - (high - low) * i / 3;
      ctx.strokeStyle = '#29383e'; ctx.setLineDash([2, 4]);
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
      ctx.fillStyle = '#79939e';
      ctx.fillText(key === 'light' ? `${Math.round(value / 1000)}k` : String(Math.round(value)), left - 7, y + 3);
    }
    ctx.setLineDash([]);
    if (!valid.length) { canvas.setAttribute('aria-label', `${label}曲线，尚无有效数据`); continue; }
    const x = at => left + (right - left) * (at - (now - windowMs)) / windowMs;
    const y = value => bottom - (bottom - top) * (value - low) / (high - low);
    ctx.save(); ctx.beginPath(); ctx.rect(left, top - 2, right - left + 1, bottom - top + 4); ctx.clip();
    ctx.beginPath(); let previous = null;
    for (const point of points) {
      if (point[key] === null) { previous = null; continue; }
      if (!previous || point.breakBefore || point.at - previous.at > 3000) ctx.moveTo(x(point.at), y(point[key]));
      else ctx.lineTo(x(point.at), y(point[key]));
      previous = point;
    }
    ctx.strokeStyle = color; ctx.lineWidth = 1.8; ctx.lineJoin = 'round'; ctx.stroke();
    const last = valid[valid.length - 1];
    ctx.beginPath(); ctx.arc(x(last.at), y(last[key]), 2.5, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
    ctx.restore();
    canvas.setAttribute('aria-label', `${label}最近五分钟曲线，${valid.length}个有效点，最后读数${last[key]}`);
  }
}

connectButton.addEventListener('click', connect);
disconnectButton.addEventListener('click', () => { release(); stateOverride = '已主动断开连接。板子继续监测，可随时重新连接。'; updateStatus(); drawCharts(); });
window.addEventListener('pagehide', () => release());
window.addEventListener('resize', drawCharts);
setInterval(() => {
  updateStatus(); posePanel.subscriptionIssue(notificationHealth.issue('pose', Date.now()));
  posePanel.tick(); void recoverNotifications();
  if (Date.now() - lastChartDraw >= 1000) drawCharts();
}, 250);
notice(environmentIssue()); updateStatus(); drawCharts();
