; Second FamiStudio music/SFX engine for the expanded dual-engine DC.nes.
; Logical CPU range: $A000-$BFFF, mapped as Mapper 194 PRG bank $64.

    .fillvalue $00
    .base $a000

dc_dual_init:
    jmp famistudio_init
dc_dual_play:
    jmp famistudio_music_play
dc_dual_stop:
    jmp famistudio_music_stop
dc_dual_update:
    jmp famistudio_update
dc_dual_sfx_init:
    jmp famistudio_sfx_init
dc_dual_sfx_play:
    jmp famistudio_sfx_play

; Commands $9D-$9F select these three banks. Each bank contains one song.
dc_dual_data_banks:
    db $61, $62, $63, "D"

FAMISTUDIO_CFG_EXTERNAL       = 1
FAMISTUDIO_CFG_NTSC_SUPPORT   = 1
FAMISTUDIO_CFG_DPCM_SUPPORT   = 0
FAMISTUDIO_CFG_SFX_SUPPORT    = 1
FAMISTUDIO_CFG_SFX_STREAMS    = 1
FAMISTUDIO_USE_VOLUME_TRACK   = 1
FAMISTUDIO_USE_PITCH_TRACK    = 1
FAMISTUDIO_CFG_SCATTERED_BSS  = 1
FAMISTUDIO_CFG_DC_COMPACT_BSS = 1
FAMISTUDIO_CFG_DC_FIXED_MUSIC_BASE = 1
FAMISTUDIO_CFG_DC_FIXED_SFX_TABLE  = 1

; Both engines reuse the stock driver's certified RAM, but never update in
; the same frame.  FamiStudio owns it only while a custom song is active;
; the stock engine is fully reset before a stock command is replayed.
FAMISTUDIO_ASM6_ZP_ENUM       = $0000
FAMISTUDIO_ASM6_BSS_ENUM      = $0500
FAMISTUDIO_ASM6_CODE_BASE     = $a020

    .dsb $0a, $00
    .include "famistudio_asm6_granzon.asm"

dc_dual_engine_end:

    .include "dc_stock_sfx.asm"

dc_dual_sfx_end:

    .org $b500
    .include "dc_dual_audio_bridge.asm"

dc_dual_bridge_end:
    .org $c000
