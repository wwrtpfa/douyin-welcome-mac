# 迎声 · Mac 直播欢迎助手

M 系列 Mac 上的原生 SwiftUI 应用：进房消息 → 昵称清理 / 去重 → 欢迎队列 → 本地语音 → 指定音频设备。

## 当前交付状态

- 已实现：原生界面、配置保存、录音导入、系统声音试听、模拟进房、队列合并/限长/过期、暂停恢复、音频设备选择、专用 Chrome 接入、退出清理。
- 已实现克隆接口：MLX Audio 0.5.7 + Qwen3-TTS 0.6B Base 4bit，独立可取消模型进程。
- 已验证：M2 / 16 GB 上 release 编译、系统语音实际播放、三个页面渲染、22 项测试、真实 Chrome 接收本地 WebSocket fixture 并触发欢迎、关闭浏览器。
- **尚未验证：克隆模型实际推理与音色效果、你的真实直播间进房事件、观众端听到声音。** 本次 Hugging Face 模型下载超时，hf-mirror.com 返回 403；未下载完成，不能宣称克隆功能已跑通。
- 这是本机测试版，`.app` 依赖本项目的 `.venv` 和本机 Python。不是可随意发给其他电脑的独立安装包；不要删除或移动项目环境。

## 打开

双击 `dist/迎声.app`。也可以：

```sh
open /Users/pengfanao/code/douyin-welcome-mac/dist/迎声.app
```

1. 在工作台点“试听欢迎语”，默认使用系统中文声音，不是假装你的克隆音色。
2. “我的声音”导入自己的 WAV / AIFF / M4A / MP3 原声（3～30 秒，推荐 10～20 秒），应用会在导入时自动转换成 24kHz 单声道 WAV，再填写录音逐字文字。
3. 选择“我的克隆声音”，保存并试听。首次需要模型下载；正式开播前先试听预热。
4. 填写 `https://live.douyin.com/数字房间号`。不支持手机短分享链接，请复制电脑网页版地址。
5. 保留软件打开的独立 Chrome 窗口；自行完成登录/验证码。窗口已静音，避免直播回声。
6. 在“播报与音频”选择输出设备，再用观众端实际检查声音。

默认：同一用户 10 分钟内只欢迎一次，两段音频间隔 8 秒，待播队列上限 5 人，最多合并 3 人，超过 30 秒跳过。
“停止播报”会清队列、停止音频并释放模型内存；恢复后重新加载模型。暂停期间收到的新事件直接跳过，不积压。
“断开”也清空待播队列。关闭应用会关闭专用 Chrome 和模型进程，不关闭你的日常 Chrome。

## 声音进入直播间

- 如果开播软件支持单应用音频采集，先验证它能否采到本应用输出。
- 否则单独安装 [BlackHole](https://existential.audio/blackhole/)，本应用输出选择 BlackHole；开播软件添加同一 BlackHole 作为音频输入。原麦克风保留为独立输入，不要被替换掉。
- 单一路径采集，避免系统音频和 BlackHole 同时进入直播形成重音。耳机监听避免声学回声。
- 输出设备断开会报错，不自动改用扬声器。此版本不能同时选择监听和直播两个输出，可用 macOS 多输出设备配置。
- 手机开播还需要硬件声卡或其他音频回传，不属于已验证链路。
- 本项目未安装 BlackHole、未修改系统默认音频设备。

## 准备模型 / 网络失败

```sh
cd /Users/pengfanao/code/douyin-welcome-mac
PYTHONPATH=backend .venv/bin/python scripts/prepare_model.py
```

先使用本地缓存；无完整缓存时访问 Hugging Face。下载失败会说明原因，停止不会损坏已完成的模型缓存。
可以在网络可用时重试。若使用备用源，只对这次命令设置 `HF_ENDPOINT`，不要改全局网络设置。

离线导入路径：

```text
~/Library/Application Support/DouyinWelcome/models/qwen3-tts-0.6b/
```

该目录应放置 `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit` 完整仓库文件，包含根目录权重、config/tokenizer 文件、speech_tokenizer 子目录权重。不能只放原版 PyTorch 权重，也不能用 CustomVoice 替代 Base。
重新打开应用后会优先使用该目录。模型来源：
https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit

## 开发与验证

需要 Swift 命令行工具、uv、Python 3.12、Google Chrome。无需完整 Xcode。

```sh
scripts/setup.sh
scripts/build.sh
.venv/bin/python -m pytest -q
PYTHONPATH=backend .venv/bin/python scripts/smoke_collector.py
```

`requirements.lock.txt` 记录本次验证的 Python 依赖版本；重建相同环境可 `uv pip sync --python .venv/bin/python requirements.lock.txt`。
SwiftUI 通过 stdin/stdout JSON lines 管理 Python 后台，不开放网络监听端口。测试脚本仅暂时监听本机回环地址。

配置、录音副本和独立浏览器会话位于 `~/Library/Application Support/DouyinWelcome/`。
欢迎音频播放后删除；界面运行记录仅保留当前会话最近 150 条，不持久化观众名单。
模型在 Hugging Face 默认缓存或上述离线目录；参考录音和昵称不上传给云端语音服务。

## 后续真实验收

需要你的原声、直播间链接和开播软件类型。至少检查：常见昵称读音、音色相似度、预热后延迟、直播同时运行的资源占用、断线重连、重复进房去重、观众端音量/回声。
非官方网页消息协议可能变化，也可能不推送所有进房；无法承诺 100% 欢迎每一位观众。详见 `docs/PROTOCOL.md`。

本项目没有内嵌第三方采集器源码或 BlackHole 驱动。分发前需审查实际依赖与模型许可证，并完成签名、公证和独立运行时打包。
