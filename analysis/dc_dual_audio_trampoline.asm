; Entry stored only in the expanded copy of stock PRG bank $18. The NMI
; dispatcher maps physical Mapper 194 bank $60 before reading this pointer.

    .base $99af

mapper_select = $8000
mapper_data   = $8001

dc_dual_audio_trampoline:
    lda #$87
    sta mapper_select
    lda #$64
    sta mapper_data
    jmp $b500

stock_restore_dispatch:
    lda #$87
    sta mapper_select
    lda #$19
    sta mapper_data
    bcc @return
    jmp $8020
@return:
    rts

dc_dual_audio_trampoline_end:
