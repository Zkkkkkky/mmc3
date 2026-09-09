; Dual-engine dispatcher for the expanded Mapper 194 DC.nes.
;
; Stock songs and stock SFX remain on the original driver. Commands $9D-$9F
; select the three unbound FamiStudio songs. While one of those songs is
; active, commands $00-$37 use the migrated FamiStudio SFX set so that music
; and effects share one APU owner.
;
; Both engines reuse the stock driver's certified $0028-$005D/$0400-$046F
; RAM, but never update in the same frame. $004C-$0056 is saved around each
; FamiStudio update because it is both the game interface and the compact
; engine's transient APU output buffer.

music_command = $004c
music_state   = $004d
music_current = $0052
music_limit   = $0053

command_temp = $0028

bridge_magic_a = $0468
bridge_magic_b = $0469
bridge_magic_c = $046a
custom_state   = $046b

famistudio_sfx_ptr_hi = $045b

mapper_select = $8000
mapper_data   = $8001

custom_first = $9d
custom_count = 3
stock_low_bank = $60

engine_init     = $a000
engine_play     = $a003
engine_stop     = $a006
engine_update   = $a009
engine_sfx_init = $a00c
engine_sfx_play = $a00f
data_banks      = $a012
stock_restore_dispatch = $99bc
stock_handoff_dispatch = $99ec

dc_dual_audio_bridge:
    ; A direct custom selector always wins. The stock driver is allowed to
    ; overwrite the bridge bytes while inactive, so do not test magic first.
    lda music_command
    cmp #custom_first
    bcc @check_active
    cmp #custom_first + custom_count
    bcs @check_active
    sta command_temp
    lda #$ff
    sta music_command
    lda command_temp
    jsr @start_custom_song
    jmp @update

@check_active:
    lda bridge_magic_a
    cmp #$5a
    beq @magic_a_valid
    jmp @stock_update
@magic_a_valid:
    lda bridge_magic_b
    cmp #$a5
    beq @magic_b_valid
    jmp @stock_update
@magic_b_valid:
    lda bridge_magic_c
    cmp #$c3
    beq @magic_c_valid
    jmp @stock_update
@magic_c_valid:
    lda custom_state
    cmp #custom_first
    bcc @stock_update
    cmp #custom_first + custom_count
    bcs @stock_update

    lda music_command
    cmp #$ff
    beq @update
    sta command_temp
    lda #$ff
    sta music_command

    lda command_temp
    bmi @leave_with_stock_command
    cmp #$38
    bcs @update

    lda music_limit
    cmp command_temp
    bcc @update
    lda command_temp
    sta music_limit
    ldx #$00
    jsr engine_sfx_play

@update:
    jsr @map_song_bank

    ; Preserve the complete game-facing zero-page interface while the compact
    ; FamiStudio engine uses it as an 11-byte call-local output buffer.
    lda $4c
    pha
    lda $4d
    pha
    lda $4e
    pha
    lda $4f
    pha
    lda $50
    pha
    lda $51
    pha
    lda $52
    pha
    lda $53
    pha
    lda $54
    pha
    lda $55
    pha
    lda $56
    pha
    jsr engine_update
    pla
    sta $56
    pla
    sta $55
    pla
    sta $54
    pla
    sta $53
    pla
    sta $52
    pla
    sta $51
    pla
    sta $50
    pla
    sta $4f
    pla
    sta $4e
    pla
    sta $4d
    pla
    sta $4c

    ; FamiStudio clears ptr_hi when its only SFX stream finishes.
    lda famistudio_sfx_ptr_hi
    bne @return_to_game
    lda #$ff
    sta music_limit

@return_to_game:
    jsr @restore_stock_low_bank
    clc
    jmp stock_restore_dispatch

@stock_update:
    sec
    jmp stock_restore_dispatch

@leave_with_stock_command:
    ; The low-bank handoff maps the stock high bank, resets the old driver,
    ; then replays this command in the same NMI. A requested reset becomes the
    ; normal $FF update after the explicit reset call.
    lda command_temp
    cmp #$fe
    bne @handoff_command_ready
    lda #$ff
@handoff_command_ready:
    tax
    lda #$00
    sta bridge_magic_a
    sta bridge_magic_b
    sta bridge_magic_c
    sta custom_state
    jsr @restore_stock_low_bank
    txa
    jmp stock_handoff_dispatch

@start_custom_song:
    sta custom_state
    lda #$5a
    sta bridge_magic_a
    lda #$a5
    sta bridge_magic_b
    lda #$c3
    sta bridge_magic_c

    lda custom_state
    and #$1f
    sta music_current
    lda #$00
    sta music_state
    lda #$ff
    sta music_limit

    jsr @map_song_bank
    ldx #$00
    ldy #$80
    lda #$01
    jsr engine_init
    ldx #<sounds
    ldy #>sounds
    jsr engine_sfx_init
    lda #$00
    jsr engine_play
    rts

@map_song_bank:
    lda custom_state
    sec
    sbc #custom_first
    tax
    lda #$86
    sta mapper_select
    lda data_banks,x
    sta mapper_data
    rts

@restore_stock_low_bank:
    lda #$86
    sta mapper_select
    lda #stock_low_bank
    sta mapper_data
    rts

dc_dual_audio_bridge_end:
