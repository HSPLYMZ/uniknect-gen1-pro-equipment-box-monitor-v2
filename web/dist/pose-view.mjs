import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { createRenderLoop } from './render-loop.mjs';

// Board/sensor frame: X long edge, Y short edge, Z front normal.
export function createPoseView(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 50);
  camera.position.set(5, 4.6, 6);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false; controls.minDistance = 4; controls.maxDistance = 13;
  controls.target.set(0, 0, 0); controls.update(); controls.saveState();
  scene.add(new THREE.HemisphereLight(0xe9fff8, 0x273139, 2.4));
  const light = new THREE.DirectionalLight(0xffffff, 2.2); light.position.set(3, 7, 5); scene.add(light);
  const grid = new THREE.GridHelper(9, 18, 0x45625f, 0x243a3b); grid.position.y = -1.9; scene.add(grid);
  const rig = new THREE.Group(); rig.rotation.x = -Math.PI / 2; scene.add(rig);
  const board = new THREE.Group(); rig.add(board);
  const colors = [0x46636b, 0x46636b, 0x46636b, 0x46636b, 0x75e2c3, 0x526b80];
  const materials = colors.map(color => new THREE.MeshStandardMaterial({ color, roughness: 0.65 }));
  const geometry = new THREE.BoxGeometry(3.8, 1.9, 0.24);
  board.add(new THREE.Mesh(geometry, materials));
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry),
    new THREE.LineBasicMaterial({ color: 0xc1eee0, transparent: true, opacity: 0.65 }));
  board.add(edges);
  const marker = new THREE.Mesh(new THREE.ConeGeometry(.15, .48, 3), new THREE.MeshStandardMaterial({ color: 0xf3b28a }));
  marker.rotation.z = -Math.PI / 2; marker.position.set(1.5, 0, .17); board.add(marker);
  for (const [dir, color] of [[[1,0,0],0xff8f87],[[0,1,0],0x75e2c3],[[0,0,1],0x8bc7f4]]) {
    board.add(new THREE.ArrowHelper(new THREE.Vector3(...dir), new THREE.Vector3(), 2.4, color, .22, .12));
  }
  const target = new THREE.Quaternion(), smoothed = new THREE.Quaternion();
  let hasPose = false, live = false;
  const loop = createRenderLoop(dt => {
    let moving = live && hasPose && smoothed.angleTo(target) > 0.00001;
    if (moving) {
      smoothed.slerp(target, 1 - Math.exp(-dt / 75));
      moving = smoothed.angleTo(target) > 0.00001;
      if (!moving) smoothed.copy(target);
    }
    board.quaternion.copy(smoothed);
    renderer.render(scene, camera);
    return moving;
  });
  const visibilityChanged = () => document.hidden ? loop.pause() : loop.invalidate();
  document.addEventListener('visibilitychange', visibilityChanged);
  controls.addEventListener('change', loop.invalidate);
  const observer = new ResizeObserver(() => {
    const { width, height } = canvas.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
    loop.invalidate();
  });
  observer.observe(canvas);
  loop.invalidate();
  return {
    setPose({ roll, pitch }) {
      // Ry(pitch) Rx(roll) maps the measured gravity vector into +Z, with yaw fixed.
      target.setFromEuler(new THREE.Euler(roll, pitch, 0, 'YXZ'));
      if (!hasPose) { smoothed.copy(target); hasPose = true; }
      loop.invalidate();
    },
    setLive(value) { if (live !== value) { live = value; loop.invalidate(); } canvas.dataset.live = String(value); },
    reset() { hasPose = false; smoothed.identity(); target.identity(); live = false; loop.invalidate(); },
    resetCamera() { controls.reset(); },
    dispose() {
      loop.dispose(); observer.disconnect();
      document.removeEventListener('visibilitychange', visibilityChanged);
      controls.removeEventListener('change', loop.invalidate); controls.dispose();
      scene.traverse(obj => { obj.geometry?.dispose();
        for (const material of Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : []) material.dispose(); });
      renderer.dispose();
    }
  };
}
