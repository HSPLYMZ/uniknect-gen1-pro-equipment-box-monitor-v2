# 第三方来源与许可

本文件记录随仓库分发的第三方文件及本项目参考来源。它不替代各组件原有许可证，也不为本项目原创代码自动指定开源许可证。

## UniKnect MicroPython

- 官方来源：<https://github.com/quectel-develop/uniknect-micropython>
- 本地参考来源：官方仓库的温湿度、LCD、BLE 示例及文档。
- 相关文件：`device/sensors.py`、`device/display.py`、`device/ble_telemetry.py` 等应用模块采用官方公开接口与示例流程；`device/assets/logo_160x20.bin` 是从官方 LCD 示例资源转换得到的 RGB565 数据，加载器为 `device/logo_asset.py`。
- 官方仓库根许可证：Apache License 2.0；本项目随附文本保存在 [`licenses/UniKnect-Apache-2.0.txt`](licenses/UniKnect-Apache-2.0.txt)。
- 本项目另外实现了监测调度、告警、局部显示更新、BLE 帧协议及云上报策略，并不表示这些应用模块整体都是官方作品。

Quectel 名称与标识归相应权利人所有。保留官方标识用于本套件演示，不构成对商标权的授权声明。固件、硬件手册及整个官方仓库未打包分发，使用者应从官方入口获取并遵守其各自条款。

## Three.js

- 官方来源：<https://github.com/mrdoob/three.js>
- 本地版本：`three.core.js` 中的 `REVISION` 为 `186`。
- 随附文件：`web/dist/vendor/three.core.js`、`three.module.js`、`OrbitControls.js`。
- 许可证：MIT；完整文本保存在 [`web/dist/vendor/THREE-LICENSE.txt`](web/dist/vendor/THREE-LICENSE.txt)。原有文件头的版权与许可标记予以保留。
- `OrbitControls.js` 在此分发版本通过相对路径导入 `./three.module.js`，支持离线静态页面使用。

## PC 依赖与固件接口

`requirements.txt` 固定 PC 端依赖 `pyserial==3.5`，仓库不随附该依赖源码。MicroPython、Quectel 专用接口和传感器/显示驱动由指定固件提供，未在本项目中重新分发。以上依赖的名称不构成对其源代码的额外授权。
