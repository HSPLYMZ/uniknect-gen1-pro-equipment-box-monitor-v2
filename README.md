# UniKnect Gen1 Pro V2

版本：V2.2.0-cloud-window（2026-10-21）。本目录是可单独移动的完整应用项目。

## 体验报告与项目背景

本项目用于“移远产品体验官计划”，实现基于 UniKnect Gen1 Pro 的设备箱监测终端。

- [移远中文论坛体验帖](https://forumschinese.quectel.com/t/topic/15421?u=huangshengping2025)
- [UniKnect MicroPython 官方仓库](https://github.com/quectel-develop/uniknect-micropython)

准备上传 GitHub 时，请先阅读 [发布说明](PUBLISHING.md) 和 [第三方来源与许可](THIRD_PARTY_NOTICES.md)。原始本机目录保留了被忽略的私有配置、日志和备份，不能直接整体拖拽上传；网页上传应使用已排除这些文件的发布目录。

## 功能概览

支持 LCD 四页与按键、温湿度/光敏、姿态告警、GNSS、SD 日志、事件录音、BLE 环境与三轴双通道，以及浏览器 3D 倾斜/翻转展示。新增 EC200U/4G → 移远 IoT → 移联万物 APP 常驻连接，按限时窗口上报；使用板内私有配置启用。LBS 保持关闭。3D 按需绘制，静止/隐藏页面停止持续渲染。

## 目录

- `device/`：MicroPython 应用、配置模板、开机入口和屏幕资源。
- `host/`：PC 部署、回读校验、自启维护及只读观察工具。
- `tests/`：本地回归检查，不连接云账号、不消耗设备消息额度。
- `web/dist/`：完整静态网页，包含 3D 必需的 Three.js 运行库及许可证。
- `requirements.txt`：PC 串口依赖；板端库由指定固件提供。
- `version_manifest.json`：本目录全部交付文件的 SHA-256 清单。

公开交付清单不含旧版源码、历史测试文档/记录、官方示例仓库、固件安装包、缓存、虚拟环境或私有凭证。板端要求 NUCLEO-F413ZH + UniKnect 扩展板 + OYF034301 屏幕，以及已经验证的 UniKnect MicroPython F413ZH v1.6.0 Beta20260721 固件。PC 使用 Python 3.10 或更高版本。

2026-10-20 已通过独立探针完成实体 DK/SN `cabinet01` 的板端、平台及 APP 数据核对，随后在本版集成常驻云连接。物模型 ID2 温度、ID3 湿度、ID4 光敏 ADC、ID5 有效位合并发送。SDK 的 sendTsl 实测返回 None，日志 `CALLED` 表示调用返回，云端接收须结合平台记录确认。旧探针仅保留用于故障诊断，不能与常驻程序同时运行；它会中断当前应用并重新开始一次开机周期。

## 常驻云端与上传额度

本项目于 2026-10-20 在测试账号核实的套餐为 **1500 条/设备/天，上下行合计，每 512 bytes 向上取整**；当时补充包余额为 0。该测试账号超额后无法上传，次日恢复额度；协议心跳和上下线通知不计数，SIM 流量单独计费。这是本项目测试时的账号记录，其他账号、套餐和后续规则以各自控制台为准。

用户确认节奏：V2 启动后的前 5 分钟等待；在 **5–7、10–12、15–17、20–22、25–27 分钟**各每 10 秒发送一次；其余时间暂停，满 30 分钟结束。正常在线且预算充足时每次启动最多 60 次。30 分钟后仍保持 MQTT 在线，APP 保留最后读数；本地 LCD、采样、BLE/三轴、TF 与告警继续运行。

当前 Beta 固件的 SDK 曾在无业务数据约 180 秒后断开 MQTT，现每 60 秒调用原生 MQTT `PINGREQ` 保活；该协议消息不占平台业务消息额度，但有少量蜂窝流量。此兼容处理使用当前 SDK 的内部 MQTT 句柄；更换固件后须重新验证。

不补传离线历史、不因 None/False 密集重试、不上传三轴高频流或原始音频。上报窗口内的平台读取回复占用同一个发送机会；等待、暂停和结束期间不回业务数据。平台主动下发本身仍可能计费，避免反复点击刷新/查询。

防重启预算保存在 `/flash/cloud_budget.json`：初始容量 240 个保守单位，连续通电每天补充最多 600 单位，每次发送尝试预扣 2 单位，先持久化再调用 SDK。任意 24 小时管理上限为 840 单位，给平台下行与 SDK 其他业务预留空间；这不是实时平台余额，也不能限制其他客户端下发。断电不补额度，重启不清零；损坏/写入失败则停止业务发送，保留本地监测。升级不得删除该文件。

第四页按键顺序为 Logo → 作者 → 实时监测 → 网络/云端，显示 MQTT 状态、LTE RSRP（dBm）、SINR（dB）、阶段及倒计时、调用次数和剩余软件预算。`WAIT` 等待、`REPORT` 上报窗口、`PAUSE` 暂停、`ENDED` 结束、`OFFLINE` 当前窗口未连云、`QUOTA_HOLD` 预算不足。信号值 30 秒查询一次，失效或超过 90 秒显示 `--`。`CALLED` 不代表平台已经接收成功。

凭证放在私有 `device/cloud_private.json`，模板为 `device/cloud_private.example.json`，已排除交付清单；安装时显式指定：

```powershell
python -B -u host/resident_board.py update --port COM3 --cloud-config device/cloud_private.json
```

日常 `update` 保留板内私有配置和预算。没有有效私有配置时以本地模式启动。要停用云连接，可把私有文件的 `enabled` 改为 false 后用上述命令安装。原版启动入口升级时需使用已经审核的旧入口 SHA-256 参数，不能用未知摘要绕过入口检查。原始本地 BLE 源码快照保存在本机 `backups/local_ble_before_cloud_20261020/`，不属于公开交付内容。

## 部署与自启

在本目录打开 PowerShell（首次使用安装依赖）：

```powershell
python -m pip install -r requirements.txt
python -B -u host/resident_board.py update --port COM3
```

`python` 指已安装 pyserial 的 Python 3.10+。如使用独立安装的 Python 或 Thonny 内置解释器，可在 PowerShell 中以 `& '解释器完整路径'` 替换命令开头的 `python`，无需复制作者电脑上的目录结构。

`update` 自动进入未启用看门狗的维护窗口，备份待替换文件，上传当前应用并逐文件回读校验，最后安装 `/flash/main.py` 并复位，默认观察 95 秒并要求健康启动成功。原文件备份保存在本目录 `backups/`，按内容摘要命名，不覆盖不同版本。串口被 Thonny 等程序占用时先关闭连接。未知启动入口会被保留并中止，审核后才能通过 `--expected-launcher-sha256` 指定原入口摘要。默认串口为 COM3，可自行修改。

板子供电即可自启，不需要 PC 运行启动脚本。入口留 2 秒维护窗口，随后启用 15 秒看门狗；传感器/LCD/BLE 连续正常运行至少 60 秒后清除启动失败记录。连续三次启动失败时：已有板内 V1 则回退；新板无旧应用则停留维护 REPL。电脑上不需要 V1 项目。维护/文件更新期间不要断电；本工具逐文件校验，不提供整个版本的断电事务。

```powershell
# 校验全部运行文件和启动入口，再复位并确认健康
python -B -u host/resident_board.py verify --port COM3
# 只读观察，不中断监测
python -B -u host/observe_board.py --port COM3 --seconds 30
# 维护与恢复
python -B host/resident_board.py maintenance --port COM3
python -B -u host/resident_board.py resume --port COM3
# 仅已有板内 V1 时可使用
python -B -u host/resident_board.py rollback --port COM3
```

应用部署位置为 `/flash/cabinet_monitor_v2/`，启动源为 `device/startup_v2.py`。不要把 `device/main.py` 当作板根入口。`boot.py`、板内私有配置和 SD 历史数据保留。`deploy_board.py --upload` 只上传应用，使用前必须先进入维护，常规更新推荐上述 `update`。

`verify`、`resume`、`update` 都会复位并重新开始开机计时；完整窗口测试期间只运行 `observe_board.py`，不要用上述复位命令检查中途状态。预算文件始终保留。

## 网页与 3D

线上免登录仪表盘：https://uniknect-v2-dashboard-20261017-hsp.ablechick4096.chatgpt.site

本地运行：

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory web/dist
```

电脑 Chrome 打开 `http://localhost:8765`，或通过线上 HTTPS 地址，点击“连接设备”选择 **UniKnect_V2**。手机使用线上 HTTPS 地址。复位后需重新连接。3D 支持鼠标拖动、缩放与恢复视角；姿态数据超过 1.5 秒灰显，环境数据超过 3 秒提示过期。

传感器以重力估计横滚/俯仰，可跟随倾斜与翻转，不能测量航向旋转或空间位移；橙色 +X 为传感器坐标参考，未完成与实物板头的标定。倾斜/翻转已在 V2.1.0 现场确认；本次更新的真实断电上电、安卓与多天运行仍需现场验收。光敏规则：<=18000 红、>=24000 黑，中间保持状态；常驻姿态目标周期 200ms，受底层同步调用影响。此前 V2.1.1 蓝牙重连压测曾观察到姿态 Notify 底层超时约 5 秒、光敏最大间隔约 8.2 秒，随后自动恢复广播；不能保证蓝牙连接变化时的最坏响应延迟，这项仍需固件层排查。本版 LTE 并行观察值单独记录在验收结果中。

## 本版验证

2026-10-21 网页补丁 `notify-recovery`：BLE 实时接收与 MQTT 5～30 分钟窗口独立。环境和三轴通道分别监测通知，8 秒没有有效帧时重建订阅，每次连续失联最多两次，之后提示重新连接；不会把初始化值或旧值当成实时数据。只有一个已授权同名设备时优先复用，否则保留浏览器选择框。新增网页入口/模块版本参数，避免旧缓存混用。15 项网页回归通过，源码及检查位于 `web/`，运行 `node --test web/test_*.mjs`。实板在 MQTT ENDED 后另收到 20 帧环境和 80 帧三轴，证实 BLE 未被云端停止策略关闭；生产网页接收核对摘要见版本清单 `web_revision.production_verification`。

2026-10-21：17 个运行文件及启动/回退入口回读一致，健康启动通过；69 项本地回归通过。实板同一次启动完整周期五个窗口各 12 次，共 60 次调用，30 分钟后 ENDED，额外观察至少两次 MQTT 保活且仍在线，无业务补传或意外断连。BLE 并行收到环境 97 帧、三轴 388 帧，断开后恢复广播，通知错误为 0。

平台实收单独核对，详见版本清单 `resident_cloud.verification.platform`；SDK 返回 None 的 CALLED 记录不能代替平台收包。原始平台与串口证据保留于作者本地，不随公开仓库发布；本仓库提供验收摘要和可离线运行的回归检查。

## 当前边界与待修复问题

- 本项目受场地限制，未验证 GNSS 定位和扬声器播放；保留接口代码不代表对应硬件验收通过。
- 多天连续运行尚未验收。发布前代码审查额外复现：`device/qth_transport.py` 的启动等待条件在 `ticks_diff` 超过半周期后可能再次成立，进而跳过已连接状态下的 MQTT 保活和信号查询。应把 15 秒启动等待改为完成后锁存的状态，不能持续与开机时刻比较。
- Qth SDK 初始化阶段若出现异常，传输会停留在 `ERROR`，当前不会自动重新初始化。需要受控重启或后续实现有退避的恢复机制；初始化成功后的 MQTT 重连由 SDK 负责。
- 上述两项运行逻辑问题在本次 GitHub 发布整理中仅记录，未修改已部署固件应用；69 项现有 Python 与 15 项网页回归通过不代表这两项边界已修复。
- 本项目原创代码尚未单独选定开源许可证。第三方材料的许可与来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；在决定原创代码许可证前，请勿把整个仓库宣称为 MIT 或 Apache-2.0 授权。
