import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeFrame, sequenceGap, freshness } from './dist/protocol.mjs';
const bytes = text => Uint8Array.from(text, c => c.charCodeAt(0));
test('negative temperature, zero humidity and full-scale ADC', () => {
  const frame = decodeFrame(bytes('010000FB2E0000FFFF9F'));
  assert.equal(frame.temperature, -12.34); assert.equal(frame.humidity, 0);
  assert.equal(frame.light, 65535); assert.equal(frame.exposed, true);
});
test('DataView respects offset and length', () => {
  const raw = bytes('xxxx01000100000000000000yyyy');
  const frame = decodeFrame(new DataView(raw.buffer, 4, 20));
  assert.equal(frame.seq, 1); assert.equal(frame.temperature, null);
  assert.equal(frame.humidity, null); assert.equal(frame.light, null);
});
test('reject corrupt, unknown-version and impossible sensor frames', () => {
  for (const s of ['1234', 'ZZ000100000000000000', '02000100000000000000', '01000000002711000002'])
    assert.throws(() => decodeFrame(bytes(s)), s);
});
test('sequence wrap, duplicates, out-of-order and missing frames', () => {
  assert.deepEqual(sequenceGap(65535, 0), { accept: true, missed: 0 });
  assert.deepEqual(sequenceGap(10, 13), { accept: true, missed: 2 });
  assert.equal(sequenceGap(10, 10).accept, false);
  assert.equal(sequenceGap(10, 9).accept, false);
  assert.equal(sequenceGap(null, 0).accept, true);
});
test('no data, disconnection and stale values never count as live', () => {
  assert.equal(freshness(false, 1000, 2000), 'disconnected');
  assert.equal(freshness(true, 0, 2000), 'waiting');
  assert.equal(freshness(true, 1000, 4000), 'live');
  assert.equal(freshness(true, 1000, 4001), 'stale');
});
