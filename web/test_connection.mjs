import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withTimeout, chooseDevice, NotificationWatchdog, restartNotifications } from './dist/connection.mjs';

test('GATT wait completes, preserves original errors, and times out a hung operation', async () => {
  assert.equal(await withTimeout(Promise.resolve(42), 10), 42);
  const failure = new DOMException('fixture', 'NetworkError');
  await assert.rejects(withTimeout(Promise.reject(failure), 10), error => error === failure);
  await assert.rejects(withTimeout(new Promise(() => {}), 5), error => error.name === 'TimeoutError');
});

test('reconnect reuses only one previously authorized matching device; otherwise keeps the chooser', async () => {
  const board = { name: 'UniKnect_V2' }; let prompts = 0;
  const bluetooth = { getDevices: async () => [board, { name: 'Other' }],
    requestDevice: async options => { prompts++; assert.equal(options.filters[0].name, 'UniKnect_V2'); return board; } };
  assert.equal(await chooseDevice(bluetooth, 'UniKnect_V2', 0xfff0), board);
  assert.equal(prompts, 0);
  bluetooth.getDevices = async () => [];
  await chooseDevice(bluetooth, 'UniKnect_V2', 0xfff0);
  bluetooth.getDevices = async () => [board, { name: 'UniKnect_V2' }];
  await chooseDevice(bluetooth, 'UniKnect_V2', 0xfff0);
  assert.equal(prompts, 2);
});

test('missing notifications recover twice per outage; channels and successful packets are independent', () => {
  const health = new NotificationWatchdog(8000, 2);
  health.watch('environment', 'env', 0); health.watch('pose', 'pose', 0);
  assert.equal(health.next(7999), null);
  health.received('environment', 7000);
  assert.equal(health.next(8000).name, 'pose');
  assert.equal(health.next(15000).name, 'environment');
  assert.equal(health.next(16000).name, 'pose');
  assert.match(health.issue('pose', 24000), /仍未收到/);
  assert.equal(health.next(24000).name, 'environment');
  assert.equal(health.next(32000), null);
  health.received('pose', 33000);
  assert.equal(health.issue('pose', 33000), '');
  assert.equal(health.next(41000).name, 'pose');
  health.reset(); assert.equal(health.next(100000), null);
});

test('recovery stops before restarting and cannot subscribe a cancelled connection', async () => {
  const events = [];
  const tx = { stopNotifications: async () => events.push('stop'),
    startNotifications: async () => events.push('start') };
  await restartNotifications(tx, () => {});
  assert.deepEqual(events, ['stop', 'start']);
  events.length = 0;
  let active = true;
  tx.stopNotifications = async () => { events.push('stop'); active = false; };
  await assert.rejects(restartNotifications(tx, () => {
    if (!active) throw new DOMException('Cancelled', 'AbortError');
  }), { name: 'AbortError' });
  assert.deepEqual(events, ['stop']);
});
