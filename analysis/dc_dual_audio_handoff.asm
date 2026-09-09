; Same-frame custom-to-stock handoff stored in the expanded copy of stock PRG
; bank $18. The source range $99EC-$9A7F is all zero and remains untouched in
; the original bank; only the expanded copy receives this code.

    .base $99ec

mapper_select = $8000
mapper_data   = $8001
music_command = $004c

stock_handoff_dispatch:
    pha
    lda #$87
    sta mapper_select
    lda #$19
    sta mapper_data
    lda #$fe
    sta music_command
    jsr $8020
    pla
    sta music_command
    jmp $8020

stock_handoff_dispatch_end:
