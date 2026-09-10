# DC.nes FamiStudio 全量 RAM 与数据审计

- 输出 ROM SHA-256：`B7CF9A5843908E86ABB4283A6CE00E0194695567DDC5EA1DA874CA2213A129FE`
- 全 ROM 检查：64 个 PRG Bank、32 个 CHR Bank；头部和全部 CHR 未变化。
- 游戏数据白名单：除 5 个已确认的选曲绑定字节外，没有音频区域之外的变化。
- 剧情/关卡/地图/战斗数据：通过整个 ROM 逐字节比较覆盖；除 5 个明确的选曲绑定字节外全部未变。
- RAM：165 字节全部来自已删除旧驱动的原占用；146 字节常驻、8 字节调用临时、11 字节混音临时并逐帧入栈恢复。
- 已排除：栈页游戏缓冲、地图炮粒子区、DATA LOAD 缓冲、全部电池 SRAM。
- 地图炮期间不暂停、不重建音乐，粒子与音频可在同一帧运行。

## 有变化的 PRG Bank

- 0x00：8144 字节
- 0x01：6219 字节
- 0x06：2 字节
- 0x0A：1 字节
- 0x0D：6447 字节
- 0x15：6164 字节
- 0x17：6095 字节
- 0x18：3737 字节
- 0x2B：6709 字节
- 0x31：6754 字节
- 0x33：5403 字节

## 运行时回归

- 23 tracks and 56 SFX：`RESULT checks=39 failures=0 frames=519 pc=F873 bridge=512 init=30 music=27 sfx=56 apu=4890 mapper6=3841 mapper7=3811`
- 23 complete/long playback passes：`RESULT checks=23 failures=0 frames=71888 pc=F873 bridge=71881 apu=651892 suppressed=73`
- DATA LOAD -> data 0 + RAM monitor：`RESULT pass=true bridge=8992 apu=81088 normal_frames=7600 illegal=0 game_state_writes=0 min_stack=D5 frame=8999 pc=F874 state=9C77`
- first-stage map cannon：`RESULT pass=true particle_writes=53 first=14590 last=14711 apu_during_particle=14 bridge=20136 frame=19999 pc=F871 state=9CB9`
- title and new-game map：`RESULT pass=true title_command=268 title_loaded=269 map_command=681 map_loaded=682 apu_writes=8112 frame=899 pc=F981`
- CONTINUE map：`RESULT pass=true command=716 loaded=717 apu_writes=6147 wrong_alias=false frame=1399 pc=F981`
- Wisdom God battle：`RESULT pass=true wisdom=true command=2430 loaded=2431 apu_writes=15977 frame=4199 pc=F981`
