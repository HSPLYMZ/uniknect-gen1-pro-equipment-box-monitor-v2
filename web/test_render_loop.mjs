import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRenderLoop } from './dist/render-loop.mjs';

function harness(draw) {
  let id = 0, at = 0, hidden = false;
  const pending = new Map();
  const loop = createRenderLoop(draw, {
    request(fn) { pending.set(++id, fn); return id; },
    cancel(id) { pending.delete(id); }, hidden: () => hidden, now: () => at
  });
  return { loop, pending, hide(value) { hidden = value; },
    step(ms = 16) { at += ms; const callbacks = [...pending.values()]; pending.clear(); callbacks.forEach(fn => fn(at)); }
  };
}

test('idle scene renders once, coalesces updates and stops after interpolation', () => {
  let remaining = 0, draws = 0;
  const h = harness(() => { draws++; return remaining-- > 0; });
  h.loop.invalidate(); h.loop.invalidate();
  assert.equal(h.pending.size, 1);
  h.step(); assert.equal(draws, 1); assert.equal(h.pending.size, 0);
  remaining = 2; h.loop.invalidate(); h.step(); h.step(); h.step();
  assert.equal(draws, 4); assert.equal(h.pending.size, 0);
  h.loop.invalidate(); h.step(); assert.equal(draws, 5);
});

test('hidden and disposed scenes schedule no frames and resuming bounds interpolation time', () => {
  const deltas = [], h = harness(dt => { deltas.push(dt); return true; });
  h.loop.invalidate(); h.loop.pause(); assert.equal(h.pending.size, 0);
  h.hide(true); h.loop.invalidate(); h.step(60000); assert.equal(deltas.length, 0);
  h.hide(false); h.loop.invalidate(); h.step(); assert.deepEqual(deltas, [16]);
  h.step(1000); assert.equal(deltas[1], 100);
  h.hide(true); h.step(); assert.equal(h.pending.size, 0);
  h.hide(false); h.loop.invalidate(); h.loop.dispose(); h.loop.invalidate();
  assert.equal(h.pending.size, 0);
});
