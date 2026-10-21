# GitHub 发布说明

## 公开内容与私有内容

公开范围由 `version_manifest.json` 的 `files` 清单加清单文件本身组成，包含应用源码、测试、网页、依赖说明、配置示例及第三方许可。发布包不包含固件、作者云端鉴权或原始硬件日志。

本机原目录中下列内容仅用于开发，不能发布：

- `device/cloud_private.json`、`device/config.py`：板端私有配置。
- `cloud_debug/config_private.py`：诊断私有配置。
- `cloud_debug/logs/`：原始诊断记录。
- `backups/`：本地历史备份；今后的备份可能包含云配置。
- 缓存、虚拟环境、私钥及本地环境变量文件。

这些路径已经被 `.gitignore` 排除。GitHub 网页上传、本机复制和压缩操作不会自动遵守 Git 的忽略规则；请从干净发布目录上传文件，不要把本机开发目录整体拖拽上去。不要使用 `git add -f` 强制加入私有文件。若以后已经将密钥提交到远端，仅添加忽略规则不足以撤回泄漏，应立即撤销或轮换相关密钥，并按 GitHub 的说明处理历史。

## 发布方式

推荐使用本次生成的干净发布目录，将目录内的内容放到仓库根目录，使 `README.md` 直接可见。若使用压缩包，先解压再上传其中的源码；单独上传 ZIP 不会形成可浏览的源码仓库。

使用 Git 时，在干净发布目录中执行以下步骤；远端地址使用你自己创建的 GitHub 仓库地址：

```powershell
git init -b main
git add .
git status --short
git diff --cached --stat
```

检查暂存文件中没有私有配置、备份和原始日志后，再自行提交并连接远端。本文不填写不存在或未经确认的 GitHub 仓库地址。

`.gitattributes` 保留原文件字节，避免跨系统换行自动转换使 SHA-256 与板端回读校验不一致。此设置不会将文本内容从普通差异比较中排除；`.bin` 则明确按二进制处理。

## 离线验证

PC 使用 Python 3.10+，先安装 `requirements.txt`。网页回归需已安装支持 `node --test` 的 Node.js。下列检查不连接板卡或云端：

```powershell
python -B -m unittest discover -s tests -v
node --test web/test_*.mjs
```

板端依赖 `machine`、`quectel`、`Qth`、`ahtx0`、`lis2dh12`、`st7735` 等由指定 UniKnect 固件提供，不应通过 PC 的 pip 安装来替代固件接口。硬件、固件版本与部署方法见 README。

## 已知边界与许可

发布前审查保留了两项运行问题：Qth 长时间运行的开机等待判断，以及 SDK 初始化失败后不会自动重试。复现条件见 README 的“当前边界与待修复问题”。该仓库适合作为开发体验与原型参考，现有测试不等同于多天硬件验收。

GitHub 并不强制公开仓库选择开源许可证。本项目暂未给原创代码新增授权；已保留 Three.js MIT 文本，并补入所参考 UniKnect 官方代码/资源的 Apache-2.0 文本与来源说明。发布内容的完整来源见 `THIRD_PARTY_NOTICES.md`。

## 体验帖

[移远中文论坛体验帖](https://forumschinese.quectel.com/t/topic/15421?u=huangshengping2025)

## GitHub 官方参考

- [文件大小限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
- [密钥扫描](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning)
- [仓库许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
