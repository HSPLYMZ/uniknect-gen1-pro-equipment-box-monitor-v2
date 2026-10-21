# Three.js 本地运行库

本目录随静态仪表盘分发 Three.js r186 所需的三个文件：

- `three.core.js`：核心模块，文件内 `REVISION` 为 `186`。
- `three.module.js`：网页渲染模块，通过相对路径引用核心模块。
- `OrbitControls.js`：相机交互模块，在本地版本中导入 `./three.module.js`。

来源为 [Three.js 官方仓库](https://github.com/mrdoob/three.js)。许可证为 MIT，完整文本见 [THREE-LICENSE.txt](THREE-LICENSE.txt)，仓库总说明见 [第三方来源与许可](../../../THIRD_PARTY_NOTICES.md)。

这些文件随网页本地托管，不依赖 CDN。更新库时应一并检查核心模块、渲染模块、相机控制模块与许可文本的兼容性，并重新运行 `web/test_*.mjs` 回归。更新源文件后还应同步 `version_manifest.json` 的交付文件哈希。
