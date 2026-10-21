# 回归验证

在项目根目录运行：

```powershell
python -B -m unittest discover -s tests -v
```

无需连接开发板或云账号。覆盖 30 分钟窗口边界与 60 次上限、离线不追补、None 返回不重试、持久化预算及损坏/写满/重启/计时回绕、信号单位与未知值、四页切换及屏幕恢复；同时保留 BLE 环境/三轴、传感器独立失效、告警迟滞、SD 短写和录音时长、启动回退的回归检查。

回归测试不等同于实际蜂窝信号、云端收包或 APP 接收验收；硬件结果另存于主工作区测试记录中。

完整板端周期需连续记录至 30 分钟结束后至少两次 MQTT 保活；观察期间不要复位。日志验收命令：

```powershell
python -B host/analyze_cloud_log.py verified_boot.log complete_cycle.log --out result.json --require-complete
```

仅合并同一次启动的日志。分析工具会拒绝缺少窗口、发送失败、重复/越界/结束后调用、多次启动、计时回退、保活错误及 BLE 通知错误；通过表示板端调度通过，平台实收仍需独立核对。
