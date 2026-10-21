import { decodePose, TiltFilter } from './pose-math.mjs';
import { sequenceGap } from './protocol.mjs';

export function createPosePanel() {
  const el = id => document.getElementById(id), filter = new TiltFilter();
  let view = null, disposed = false, connected = false, available = false;
  let receivedAt = 0, previous = null, latest = null, computed = null, received = 0, missed = 0, bad = 0;
  let message = '连接开发板后接收三轴姿态', renderError = '', subscriptionIssue = '';
  function status() {
    const fresh = connected && available && receivedAt > 0 && Date.now() - receivedAt <= 1500 && computed !== null;
    el('posePanel').dataset.fresh = String(fresh);
    view?.setLive(fresh);
    el('poseStatus').textContent = !connected ? receivedAt ? '已断开 · 保留最后姿态' : '等待连接'
      : !available ? message : subscriptionIssue && (!receivedAt || Date.now() - receivedAt > 1500) ? subscriptionIssue : !receivedAt ? '等待第一条姿态数据'
      : Date.now() - receivedAt > 1500 ? '姿态数据已过期'
      : !computed ? '当前姿态无效' : computed.disturbed ? '检测到动态加速度 · 姿态仅供参考' : '实时倾斜姿态';
    el('posePackets').textContent = `${received} 帧${missed ? ` · 缺失 ${missed}` : ''}${bad ? ` · 异常 ${bad}` : ''}`;
    el('poseAge').textContent = receivedAt ? `${((Date.now() - receivedAt) / 1000).toFixed(1)} 秒前` : '尚无采样';
    el('poseRenderHint').textContent = renderError || '拖动旋转观察 · 滚轮缩放 · 橙色标记为传感器 +X';
    el('poseReset').disabled = !view;
  }
  function renderNumbers() {
    ['X','Y','Z'].forEach((axis,i) => { el(`accel${axis}`).textContent = latest?.vector ? latest.vector[i].toFixed(2) : '—'; });
    el('poseRoll').textContent = computed ? `${(computed.roll * 180 / Math.PI).toFixed(1)}°` : '—';
    el('posePitch').textContent = computed ? `${(computed.pitch * 180 / Math.PI).toFixed(1)}°` : '—';
  }
  const panel = {
    connect() {
      filter.reset(); connected = true; available = false; receivedAt = 0; previous = null;
      latest = computed = null; received = missed = bad = 0; message = '正在检查姿态通道'; subscriptionIssue = '';
      view?.reset(); renderNumbers(); status();
    },
    available() { available = true; status(); },
    subscriptionIssue(text) { subscriptionIssue = text; },
    unavailable(text = '开发板未提供姿态通道，环境数据可继续使用') { available = false; message = text; status(); },
    disconnect() { connected = false; filter.reset(); status(); },
    tick: status,
    receive(event) {
      if (!connected || !available) return;
      try {
        const frame = decodePose(event.target.value), order = sequenceGap(previous, frame.seq);
        if (!order.accept) return;
        const now = Date.now();
        if (receivedAt && now - receivedAt > 1500) filter.reset();
        previous = frame.seq; missed += order.missed; received++; receivedAt = now; latest = frame;
        computed = frame.vector ? filter.update(frame.vector, now) : null;
        if (!frame.vector) filter.reset();
        renderNumbers(); if (computed) view?.setPose(computed);
      } catch { bad++; status(); return false; }
      status();
      return true;
    },
    dispose() { disposed = true; view?.dispose(); }
  };
  el('poseReset').addEventListener('click', () => view?.resetCamera());
  // The numeric panel also works without WebGL (including non-browser environments).
  if (typeof document.createElement === 'function') {
    import('./pose-view.mjs').then(({ createPoseView }) => {
      if (disposed) return;
      view = createPoseView(el('poseCanvas'));
      if (computed) view.setPose(computed);
      status();
    }).catch(() => { renderError = '3D 显示不可用，仍可查看三轴数值；请检查浏览器图形加速。'; status(); });
  }
  status();
  return panel;
}
