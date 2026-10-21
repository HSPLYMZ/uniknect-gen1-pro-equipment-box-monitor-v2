import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodePose, tiltFromGravity, TiltFilter } from './dist/pose-math.mjs';
const bytes = text => Uint8Array.from(text, c => c.charCodeAt(0));
const near = (a,b) => assert.ok(Math.abs(a-b)<1e-8, `${a} != ${b}`);

test('pose protocol handles signed values, view offset, invalid bits and independent sequence', () => {
  const b = bytes('xx020000FC2B000003D501yy');
  assert.deepEqual(decodePose(new DataView(b.buffer, 2, 20)), { seq:0, vector:[-9.81,0,9.81] });
  assert.equal(decodePose(bytes('02000700000000000000')).vector, null);
  for (const t of ['01000000000000000001', '02000000000000000003', '020000FFFF00007FFF01', 'broken']) {
    assert.throws(() => decodePose(bytes(t)));
  }
});

test('gravity tilt covers six faces, poles, diagonal tilt and free fall', () => {
  const g=9.81;
  for (const v of [[0,0,g],[0,0,-g],[0,g,0],[0,-g,0],[g,0,0],[-g,0,0],[g/Math.sqrt(2),0,g/Math.sqrt(2)]]) {
    const q=tiltFromGravity(v), {roll:r,pitch:p}=q;
    const y=Math.cos(r)*v[1]-Math.sin(r)*v[2], z=Math.sin(r)*v[1]+Math.cos(r)*v[2];
    near(y,0); near(Math.cos(p)*v[0]+Math.sin(p)*z,0);
    near(-Math.sin(p)*v[0]+Math.cos(p)*z,g);
  }
  assert.equal(tiltFromGravity([0,0,0]),null);
  assert.equal(tiltFromGravity([NaN,0,g]),null);
  assert.equal(tiltFromGravity([0,0,20]).disturbed,true);
  near(tiltFromGravity([g,0,0],1.4).roll,1.4);
});

test('filter stays continuous across roll wrap, snaps opposite faces, resets on invalid vectors', () => {
  const f=new TiltFilter(), rad=Math.PI/180;
  f.update([0,9.81*Math.sin(179*rad),9.81*Math.cos(179*rad)],1000);
  const q=f.update([0,9.81*Math.sin(-179*rad),9.81*Math.cos(-179*rad)],1200);
  assert.ok(Math.abs(q.roll-179*rad)<4*rad);
  f.reset(); f.update([0,0,9.81],2000);
  near(f.update([0,0,-9.81],2200).roll,Math.PI);
  assert.equal(f.update([0,0,0],2400),null);
  near(f.update([0,0,9.81],2600).roll,0);
});
