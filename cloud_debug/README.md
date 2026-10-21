# 独立物模型诊断

V2.2 已集成常驻云连接，日常使用直接给开发板供电。此目录仅供明确需要排查 SDK/平台链路时使用；运行探针会中断 LCD/BLE 完整应用，结束后恢复当前 V2，并重新开始一次开机周期。不要在正常运行期间反复执行。

产品为单品设备、蜂窝 MQTT、物模型，实体 DK/SN 为 `cabinet01`。只发送已定义的 ID2 温度、ID3 相对湿度、ID4 光敏 ADC、ID5 有效位；不伪造 ID1 lux，不上传坐标、录音或完整原始日志。有效位 bit0/1/2 分别代表三项，均有效为 7；缺失字段省略，0 是合法实测值。

`config_example.py` 是公开模板；复制为本机私有 `config_private.py`，填写自己的产品鉴权。不得把产品烧录码当作 DK。私有文件、原生日志和 `logs/` 不进入 Git 或公开清单。

在项目根目录执行：

```powershell
# 只检查配置和语法；不打开串口或连接云端
python -B cloud_debug/run_probe.py --check
# 会临时中断应用；结束后校验并恢复当前常驻 V2
python -B -u cloud_debug/run_probe.py --run --port COM3
```

需要先部署 V2.2 的 `cloud_policy.py`。诊断连接等待最多 120 秒，观察最多 120 秒，周期不少于 10 秒；每次诊断最多 12 次业务发送（读取回复也占次数）。所有发送共用板端 `/flash/cloud_budget.json`，先扣预算后调用 SDK；预算异常或不足时停止。诊断是手动操作，不使用正常开机的 5～30 分钟窗口；正常应用的策略见项目 README。旧 5 秒/600 秒排查参数已不再接受。

SDK 回调只缓存请求，诊断主循环从不超过 15 秒的缓存回答。当前固件 sendTsl/ackTsl 实测返回 None，日志中的返回未确认不能当成平台成功；以同一 DK 的平台上行记录及属性时间为准。工具实时保存显式 JSON 事件，不公开原生 AT/MQTT 输出。SDK 仍可能把鉴权保存在 `/flash/usr`，不是仅存在 RAM 中。

Beta20260721 的 SDK 无条件 mkdir(`/flash/usr`) 会触发 EEXIST；`storage_directory_compatibility` 仅兼容该目录已经存在，保留原序列化/加密并回读核验。常驻应用采用同样范围的兼容层。历史测试发现 SDK 保存配置的冷启动解码异常，因此每次从本机/板内私有配置重新设置产品鉴权；不依赖 SDK 的配置自动解码恢复。

若显示恢复未确认，释放 COM3 后执行：

```powershell
python -B -u host/resident_board.py resume --port COM3 --seconds 95
```

历史证据（2026-10-20）：最初 120 秒探针调用 24 次属性上报，平台实体 cabinet01 已核实24条成功上行；SDK 返回 None。后续临时600秒窗口用于 APP 验收，用户确认移联万物在线且数值更新。实体 SN 二维码内容为 `pk=p11zHt&sn=cabinet01&v=1`；虚拟设备 `VDU1559938895883561` 的在线/下行日志不能作为本板证据。这些高频参数仅属于已结束的排查，不是现版默认策略。
