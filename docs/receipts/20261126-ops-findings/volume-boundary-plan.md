# 音量边界值测试方案（由现有知识综合，2026-11-26）

## 判定口径
三处标记互补，不可只看一个：
- volume（开机当前值，只出现一次）
- volumeSet（mini player set vol，0-100，每条音量命令后出现）
- volumeLevel（refresh config volume，配置档位 0-4）
三者同采才能区分"命令生效"与"仅播放器音量变化"。
反例：只抓 volume 会漏掉命令期间全部变化，误判音量命令无响应。
来源：kb-knowledge-1e05d7a0e8f6（active）

## 项目参数
唤醒时长 20s；音量档位 4；默认音量 3；
最小音量边界提示 TONE_ID_5 / 音量已最小；最大音量边界提示 TONE_ID_4 / 音量已最大；
协议串口 UART1/9600；日志串口 UART0/115200；唤醒词与音量掉电保存均为否。
来源：sources/repos/mars-moon/references/masr-pillar.md 2.2 基础配置要求

## 测试项
1. 默认音量：清配置+烧录后首次启动，volume/volumeLevel 等于需求值
2. 上边界：连续调大至无法再增，档位到顶 + TONE_ID_4 + 值不再增长
3. 下边界：连续调小至无法再减，档位到底 + TONE_ID_5 + 值不再下降
4. 边界幂等：已在最大再调大 / 已在最小再调小，值不变且不崩溃
5. 越界命令：超出 0-100 或 0-4，应拒绝或钳制，不得崩溃
6. 掉电保存：需求为否时，改音量后断电重启应回默认值
7. 协议方向：A5 FA 由设备发出（protoRx），A5 FB 为测试端下发（protoTx）

## 必抓标记（奥普001 CSK3022 已验证）
intent wakeMode algoMode playId playStop
volume volumeSet volumeLevel protoRx cmdNotFound
端口：COM6(A/AP日志) COM3(C/协议) COM5(control/上下电回执)，均 115200

## 已知缺陷
40 -> 30 出现音量调整提示音后 Boot Reason: CRASH 0x30，重启后 Volume: 30
30 -> 20 同样 CRASH 0x30，重启后 Volume: 20
这不是"已到最小音量"的正常响应，是固件在低音量调节/提示音路径崩溃。
规避：interaction.min_volume=40，启动音量不高于 40 时跳过降音量命令。
来源：sources/repos/cskflashtest/references/verification.md > 低音量边界与 CRASH

## 用例编号约定
@case_id:CFG-VOL-001  @module:volume-level  @formal
来源：sources/repos/Trisolaris/cucumber_test/02_gherkin_model/gherkin_case_model.md
