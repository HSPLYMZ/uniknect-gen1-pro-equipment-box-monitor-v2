// Render only while dirty or interpolating. Keep at most one pending frame.
export function createRenderLoop(draw, {
  request = requestAnimationFrame,
  cancel = cancelAnimationFrame,
  hidden = () => document.hidden,
  now = () => performance.now()
} = {}) {
  let frame = null, disposed = false, last = now();
  function invalidate() {
    if (disposed || hidden() || frame !== null) return;
    last = now();
    frame = request(tick);
  }
  function tick(at) {
    frame = null;
    if (disposed || hidden()) return;
    const dt = Math.max(0, Math.min(100, at - last));
    last = at;
    if (draw(dt) && !disposed && !hidden() && frame === null) frame = request(tick);
  }
  function pause() {
    if (frame !== null) cancel(frame);
    frame = null;
  }
  return { invalidate, pause, dispose() { disposed = true; pause(); } };
}
