from __future__ import annotations

import base64
import zlib
from functools import lru_cache

from .text_table import TextTable


# Verified legacy DC glyph table (3328 entries), stored compressed so the
# standalone editor remains self-contained without depending on the old tool.
_DC_CODE_TABLE_B85 = (
    b"c-mFHSC8%37PfVd#E;+t1RrTv)e2=K3+%N#`N%m62>~};AR!@fgAmduA^ykiI;ZpLuAFnuIdnLkb3C2XIo)E6=N-0OH@(-"
    b"}yJ}58_Vl!$U4B<R=?$KYJju)PCr|R%PX76S?uq5mQO_g!#<B8P$Ma~u@wRfO=XoqY_`7m<+;b<tepk6yc<$yWKPvYJo_qQ9weoo"
    b"7xt~8QDHn`Co?qQ6myDm~=RYYA7{AE3*OiBiU*<R8Dp!m@$k#qlPK-ayZ(dOrU)As_r#g?2?LXHaE5koBk{?Bee`GX2TvmpEWGug"
    b"bLmB>&PQEy!4F5<sU)ofLf25Z$Y$?M(($AMZQ-"
    b"*(JJfD6|8UB$hfBK9v{3AuabFU2lNSU9XD#JfA$Z!6v4FAY5Ke=o3RSlnVs`Ds$^hv((S7rD|NAlfCW%%uX9<D0GKRTAr{;CZBXe"
    b"XZ*?<oAE-F*5V%J7f&@=eW$QTRvu`R?z^@Q;q??@uekKbqxN@qX}+7Ws_$M&TbV^NrX(_(uo%q>jfZ{G-"
    b"EseWT4+HGImc&ST`UC;60)-x&O3Bl+R$%J7ek=I4JX!#_5bFTAA;zkShc{5||*-"
    b"F#K&&lvn;z5GJ+bqxNoe!h394FA}8etfPB|CsUbDZ@Wj<ZE9m!#`H$N0H$l8|3?%Ut{o(4fCn<Hec27DW^Jj$ekzo%&W@qcSiCRo"
    b"lhP3JEQr%_E!h~&R9O9?d!nb>EtImzdP`Ey7^6H`0bl^SCrxJ^z(m95&X`0zNzWn0l$;wi;K$OckJ|kstkUo%#UAC2EQ}N4{wyg?"
    b"->4@ZM>?%Q%-g6lDkjxOD$(z@Vg`V%$YLy-O+quLK*z-SbnL~s|$YD@OPEL?{@PoogQ8AyS;q-3uW-"
    b"T{rvbFW%%t)KGfmr!r!&S|0iYmyG4Gb)4dCSx6E&kl;Q6V@?{<VF8tkLzB$w8s~SG#ROcSK_ar}jRvG@@NPeN^xCei4G~fD48UEf"
    b"_J}Lel{5|8pQii|R&380@5B^>+ztZX2gTL3$FLXS6@b|{^IUWBV{5?DVS{{4w+nXNGD#PC^^9P-tJ@|We`p+xF-"
    b"y7z)>utWO;Zsg^?vwjZ^1JVp;qQ;+HwVh__eb+9ovwZO`(yc29iKk@{Z4)y?+1UsoBs=n;P-p^!!OF<_xt&>@cZER$MdBa4*Y(W-"
    b")lAOgWoUm`E6zJ`(-|>-"
    b"QNe_23h!28T|e*zr1hbRSlkUs`EH`{7F8ivwIx;@sWI0r_VU}<D>cH56a+=kL9a#%HWT8@_DUx<KT~X^TX$r;UBlF|A)%(kN5KxT"
    b"@A+JA0N*T;_Klbx2vC~%Q*bwMgDY38UFDyUwcr7e|(T1?JL7SKFk-"
    b"7+k92Sr=04Xku$scYkM;IvyuEj%Si@*W~;xZQwD!Fmj7#t;Afru;Y(%kGrRfuUK#wXmmj{T41U(nS9Q2D@U!v!Ow%I+Kg;rCO^*!"
    b"xtjI64T4ms8Wxk_}TLykM$mevklYyTZ{;O@gs=-rEbuP%Z5tq7oE5I*C@^ww00{mh$|7SY;3-"
    b"Aj&{4XoRUv%<QU5pC&i*CN5i$ei_(aYy`Gf==^^z$QaUjctHo^R-"
    b"EFW@hXKmH#6!lwU=%J3IuKBt?*0{&u<PwR9j;4g;x%vGDOYWS2>olA20B;R>o8UAu4Kh|ng!fzXO@rg40<yd~J<5|LAcJc+SMkV}"
    b"ZH@}LnhrhIopRQIV{AE8s5nl;^Ii62xbt&O5vwT;_r-Z*O@~QZG_{%b%d`=nua*%K8bS>d8hxy9yZN94EQ%-"
    b"drkOxolecfyg;2+q{ueN6Z|6nwq*Uj<({=rzjsjJ}te%r{Y_<r~Y-F!{Qe*pi$R)3vt1NaC1d_KM&{=s-"
    b"Y8`}f_Aj?<d@8KU5`IowS4&Wcy&A-l%0sMnOey^*;0RF)+-~PGHS2cXfsm??4@JYU^tM?H8;Yhxt<!%W7(D?QKL->bd`H8M>L-"
    b">cC{8rmPgnwxK?<m7>8-1(udkFuqpRenD8p1!c<^MNj_=j1(w4e<Cu*m-(Mev7ZzNo9g5d7gFe<N_f9}e@2hc;f-"
    b";3=m%SLEtRey@AA3jAs$-+M_J{Ax7c*UeA`el?aqXgXBjSDpO)BW3WbZhoNYUV&fP=^q*Vs-"
    b"N#`dRO2Z#CB{C_*Ira=w7)3zbf)sEpHY4Rhe(<YEi*onfqvUuHdii>i3T}U)As_r#dHcdXishe<t{ot^S(63I1ePKe<_gKaJ&kx_"
    b"Tz~QzyUE{z>qsZvKHz*93p+<*VA>1b^!1)7oDN{xqJiuPMWyviv~XpWrvBdoA|~{#53>TAma9X^@|3`Xu<%Fu(t!%~v&i$|>>?7t"
    b"YN6FMn2c{><Eec~aT=GjspNX=Ufn%>DmmMaR!f{r?q3r_ap%7dDigJ~Q*5Jy3S~%*_AdSLK4yjs6AYlF_q#_6OwwqubGcP#!Y6-"
    b"THl`TrvD0-}pm0F}~gU{<Te4HFV0U&X}-Y5zp_Hp*QniIah|>%>PF8n15#Gzj3GxzM22sKa}A&^S}8`8GbYWcfL}F-"
    b"^_nuUKxHf|Lwmk!*Aw)8}A3dng8UaGW=%#cPGm5oB7Y4DZ_8(e=yzVs~SG#RA)>$GxI<CQ5k+S|3w`?%-?T_4i=Q*H}gMPQ-"
    b"<HnfA@W5_|5z;zE+0c%>PXL8}rZ1{MTPqhTqJ8;m^wOoB6LrhTqKp6U`sYKQr?`)qKJHGc*6QRb}|i{HJ%@d{x7zoa&4TXJ-CK;="
    b"%kgGygs9Kg>Tf^S{;p!2B~a{~66k%-?Sir>B(RH}l`q_F(>*oBxV3{AT_;pDM#|=D+f>GW=%#dw)`f-"
    b"^_n`QyG3U|AP;e;WzVNyH<wZ%ztvR%~v&i%Bjw%aAxMetMdu-"
    b"&&>Qk|C=)WX8y}MzL<Yz=D)e448NKGO1vNZZvL9zn7`jJAHAgvznTBc+sg2p`p?AI!*A-"
    b"pAKL@JssD}k59*(p`X79$48N)W!;CWgrv6v!ZN94EQ%-"
    b"e8g)>wCvpr?_P5qaamEkw_zt{PN`e&y88=8Npe`e~x^Sd(qrv9fIAN9{n{g*U9Q2)%;|8r&d?M-fOl;Jn^UyJvL-"
    b"_`#MW%y0~Pqe<E{+X%&8(QyB|IE~X;jYbBHGImc&Zux^>VNgTGW@3gci$?*Z|Z-d^#}FOO#Sb4^+5eIQ~!;3l;Jn^-"
    b"_`L#{WDYlvn^%#P5tMeQHI~t|Lz-Q_)Yz9Bg1cR`hP2eZ{|Ox>4f=bX8uz@DT8n3zwt>MuWIm=Q=L)a%*_AzWo7Wq{4aI-VE&nz|"
    b"EZ=I=AW7QAD=3NZ|1+C<qq@D%>3_OR|enI|3;@1>YthVuj_E3{+X%&M>?HR|IF0?4W0g|e`e~xcB>4(ssE}D2kP&FdGeYv{HFf1u"
    b"ebTChEF-w85Pb<{r4loZ|c9T<q`GIO#LrkREFQw|5}$1)IT%zU;jWEepCN>UG7l-"
    b"%+&ut%LD44nfhP<q71*O|F$mQsDEba|BjYB)IT%zKhxzF_0LTGFSY+r|IF0?=_|_coBBU}war&Ge9EcLxNv6bf2-"
    b"vP_0LTGPxXGNe`e}`rR4zi&rJPqb^LMv%-nxP#|QV%%>Cze`NI7(bN`hqW%$kg-"
    b"`C|G_s`7zm$ba#{+YS|s!ku=KQs4V)O^MLGjsoGEtj}|X72x>{fql&=KgPd)aI)iKIK$rT-Z0_Oy>*kpPBn_Yk9~0Gjso2-"
    b"LB#OnYsUwmLuFhGxxvN<sJ9W%>B1?{^0(Zx&M)tYurCG_dn78!TmFH|7BgSasSNRe@mA~+&?q-"
    b"zkX90esllH*k1U}{kPszhTq(O<%c$3)$l2&I^)8bx&L-"
    b"#_|5&#HGgn_KPaoZ{Nw(ax&M}yXWTzC_n+5tjQeNi{;S$wxPNBuf2#8t_s`7z=QW>j|IFO~NS6cLKQs4V*ZGb6XXgGp6Uy+L`)}<"
    b"l!*A|?s>=)RpSk<5xB04uPdU{Y7tY-"
    b"M=ak_$_dk9^8GdvBb6qZQ|IFNfTl~1cPtr}@F5~{0x&Qy92)?QR|EvhTng9Q$2)v2^|EdVPdH<wth4KE(y#Ie!1l_d%e^G?otpEQ"
    b"|1l*+m|7>$r4VQANGZLJc^Z#FpV4Lzk)nP&TGgJPjx@$xEGgJNrZ5qm-newmbv_$zcQ~p(*HYmTJt6MP~;HLa%TBcF{%#{B~r!mT"
    b"(neyLhx1#)+DgRSlHF5sToPSoAA)G%m=bzLvf%9kP{Bw`+sv1u*MZ|zJGyYATq!@o@#($`bD8`?e@o#7nV*HsI|Fjl;j6XBupIuU"
    b"h-i&`&_Y4?+X2!p!t;6^;GyX5MsABxSa^32r!1yyW{#zL*#-Ew-"
    b"uZkYy&&>FjbP>S#GdF(Sb7B0M8UM|fZN94EQ%-fpfHO1xRqbtzKQrS$l~ZB-nHm4G78Q&?Gvi;@(Zl#NGydbxl;JnypMF;velz}m"
    b"TM>K{{<Wvd;G6J&7jF-~3IBK6T?oG~<j3)L;G6JYNx=~Q%!L13N`&xdCj2)aw(+V4PdP=dP~gIZf9Fow@e33FwIyZ8FHHDP-"
    b"%)n_!i4`~QrYnfGya)hlpVh?<^TU)RCfHrl>gmrW#=zU`S(9lE*Rf#d4EtY8Q<2t=adJGU*t<~C=VIme%SlHa>e-"
    b"e<Bq>6C&ss*_D#0=s)kQF)fol$3&GTpGW@3eb3ZD>Z_0nLtPH;?|Iv;z{QkrKSCrv5<)6{^qx^*_|L(KO@SE~q#@EAd%76c=GW@3"
    b"eM-$5MoAPg;D#LHe|DO0z{=$@h`p?SnoAU2}-"
    b"{z|tKIK$r6u2<upVZf*{Dmq1%1_Gh+y7jgQik7@zy5moP5Ey>SBBq|e<m{gru>&5E5mQffAqXE{HFYu56bYH@-KX-"
    b"48JM=`IR#Kru@5_pD2G}%73Z(iSiew{CjV;`Ko4nl~bKj;KG!D?rmlGP5BqK|55(Jl>cF08Gcj#qYY*F?TePKmEkw#U-"
    b"(@aepCMKX=V6L`By(thToKbPy8r<VamUt{f+V$ru?^;%J7@=Z)?7w{Dmq1)Sr~$H|2l0Z1YtOpK_`*3S5}-"
    b"FX(uo{Dmq1wDvd3UzqYQX}+WUg(?5+oHG3W!+y<gl)o_L-_iD<{C=Z&srifY7pDB@Un#?H%73}448JM=uJ#YgUzqZ5#Mi@b%0D05"
    b"1HUQ%{jD<mru^5}ZN94EQ%-e8feTaqWt|Twe__ghrS%NuFHHH5-"
    b"c^R*lz&Ithw>Mu{8O6WD1Twff35k0@)xH3E62+4oAN)12j%x0=b3Y5_)YoGWBcGY<v;vX8Gcj#-Pj)ZP5C!8-%<X;lz-"
    b"*3Hec27DW^K)z=bLQtlkghFHHF_wVt5-g(?4}wg=@eO!*&lJW>9_l>c1k2g+ZV@-"
    b"Kg*48JM=oX!`NzcA(Bc}5w2Q~oop?<jv^%D?`dGW_<Y_g^Z*Z_dB3`HS-"
    b"x=KR<3{qURf&%WH|s~SG#RA(HxFy}wgdW`cI=KNpoDZ_8hfBlj&{O0^i^UCm>^IvH^oWC&VUz$~h-<*F@*C(96Fz26NQ-"
    b"<H1e`Z}7esliKLuL5Q`B!y3asI-b|Kvm&ejDUwOBsH1{)^)_U)As_r#j=ng*pG7wio9w%=y<fA94P|oPSB@JI-"
    b"I2^B?aj!*9;NtLrJwUzqbR>H3887yjdZtq(YVVa~s}sSLk4|B}u(oWC&V-"
    b"_h~L`3rOYsRL#B&G{E}zTy0ZIsdul7tUXp^Uv<L`KpFbIn@~lF3kBC{-O-"
    b"OIsf%jW%$kcPjq~7{=%I9ROchkUzqb>zNQSnIsd8V56)kh^I!d}48J-5rS>1rUzqdH>-"
    b"ggQg*pGO<_FGSnDfua`@wI{KNDXMzd8RGx<A4B3v>RtnKob5@F}M{<G?Q7d-{5uzcA;I>n+Y-"
    b"nDg&yJ;nJ8bN(frKRAD3&VQ%liSrlc{5$dY@SF2*$NRx=&cFPvGW_QJmzu9Qe__tQru~KU7yk497$1If{;za=asI-"
    b"b|0~^J;{1g<|IK!ruWI;|Q=M_(!km9e>l@BrnDcLFzTy17Q8zmNIDcWzf2r|t{=%GpTgM0IFU<KDG(OH>nDd|MdWG{B=KNRM|2Ti"
    b")&i|e={O0`gT3>Mf!kqs`_d7U$Va`9T^B?Cg%=zbjQ-<H1e{QSIS2cXfsm{1?Va~sx_s97QbN<)Fi}M%e{JUQ$!*9-"
    b"iqV*f+_k*<g@`}!2tiLepuQPkVw0}!?ba;PZ-hX(e%pNfDztReV`4?vX=emQ!{0lSx2kjx$zcBTmdS976VD3K|1ndEm|MRIfVbu^"
    b"Sr#j=qh1vg(?%2`)!t{SrXDIq#_)q-"
    b"bRAvvD{vSqW519UMzpf0w>Hod1$mqXM+coi^|Ap!QzU~mv|HAZtDz*oH)BpMSe)vuQH+4kN|HAZtEw&GS(|;xCP5#?#Rl}y7>WmB"
    b"*CjUy1oBAukZQ`#4wQ0W+%qIOx5S#KV!E3^=1g+`560EktN|2iBE5T`^uLPxOz7mX8FrxTH6^y}9JxWOl+bvS?q4q@zKE%FA!H3o"
    b"tDfp23A_X5xU!>qe=!+D5_<WIq51TJi@Zs`B3O-"
    b"EUmnS9oQt)B%MG8I~zDUDI4Ar9~zJ$$|Po6|_zVgXPB<Cxij7D<4^2t~v=PRFdA~|3Aq#Mck$|t=@&R0I^M=BU^JW|PcS)>8u6_J"
    b"LFS4OHBZxAUl-tZAa^(X}&w(3ik5_}`Uhnbfn!H1WZBf*E2mm|T4lb0jGhmn^f!H18RBf*D_mm|T4i<cw8hl!UX!H0*JBf*D-"
    b"mm|T4gO?-2M-0`Y6nxldIU0PpcR3n-n73b!l;9f;KCHVO4L+Q^91T8<yBrNZe7hVCK5V-"
    b"j4L)4E91T89yBrNZJi8nXJ}kQ&4L%&Z934Jls2-"
    b")@!#2yY;KQxUvEak3%dz0YtIM(A!>aw#s|4Rz@L|;DSn%P~<yi1x)8$z3;nL+;@L|&BSn%P|<yi1x(dAh1;n3yS@DW4xC<PxjS$2"
    b"XCcP=}@hdGy>;KQ5CPViyPWheM>=CTuf7_;AID8bhWK5V({1Rt(kc7hL6E<3@8CzqYz!;;HR@Zrd1XZVPrdX$0>TP(Z5hZ~pO;KP"
    b"i|Zt&s7WjFY+;<6ijIC0qxK8(2R1|L3Lc7qQa_FF0?_`1P|376gA!-LCi@L|DaH~4VivO9dlP(4b)hYgm!;KO~(UhrYQWiR;f-"
    b"m({bSZ~=2KAgAg1s}#+_JR-JEqlR-?UudZ!*$DE@L{@s`=|t8FZi(BvKM?fZrK|?VyGUa;KTOHe(>S8Wk2{Z+p-"
    b"^gcx~AaKCHIv2Omyb_Ja?jE&IWT&zAk*!)D8V@Zqv$Klm`&vLAeSY}pS!EY@$8mEh|SA2C#qQt)AO*4>H(-"
    b"+1t0uGZ^`1mAe@VXapBhy>qw@L{Z02#5sVc<^DX_Oy5;_{M_|Q?*BlBf&Qwd|0YIW*P~;@!=ze>QM?lY|Wlfiv(X5e3+>{y%Y()E"
    b"cmced$J`Gd|B{er1scDB>1x6!$$2#;*sFXf)5k5AD2dgFAF{_)PAHE3BGLjh@pCvf)5*W1yX{q2tLfy{;4(+d`0kKo%YXok>D$W5"
    b"973d;)w)b5q#LD>3<~nir~XEO${T#R|FrHY0?l0zGC=@p?Z{p58JZanMm-"
    b"J!G~G8?kT}n1|L>w%Wx$4%HYE&?G%p$Um1MZq)nel@Rh-bN!q4Gg0BodEV3+v4~Hzv;Uk9XQ3^g>svHC#?pO|j4|6OB!G|}NgW$s"
    b"&eS?(X8w4M|SPp^@TPz2`hbxwY;KLNlLGa;;<skU5#BvaPIAS>nJ`AxO3?DI6k5cgAOXV>5FvD^fe0X6w3_h%|90ngwSPp{^BP@r"
    b"(hY$MhSAuUCe7Ima3_eV-90ngASPp{^3oM7hhXa=3fC&dI!vSlC>QM?lY^e<YOZZ<I{+IB-GW;*$e`WYz!vD(fzl8sl;eQGLE5rX"
    b"1{#S<oCH$`p|4aB^8UB~>zcTzU;eTcLU&8;&@V|urmEnIiL-"
    b"i;HAGTD6|0Vpd4F5~`Um5<F@V_$rFX4Y>_+P^R%J9F0|CQl?3I8j@{}TRJhW{n}uMGc7_+J_Rm+-"
    b"$b{4e2uW%ysh|H|;cnxT4>;OjqeTN-#(d-AEW5e~eneS4#9j03M~pFgi`lmoA7FRdyY=fJDlH-"
    b"A?)(t%gCm)=u0)`3^G*O!!ycHmX*{XZ)gjBo#XxvN|<zWv+Hcgh3Cx3<z(%0tGtf4zNKxng{KV(D+niSg}m^*^=ws)kQF)p>+$|G"
    b"7F+hTjbF{556x%@H@mI|9F1;`V_u{N{<%FDk=trnviuGW`D2TkXFQ_{|nqc9h}wpWbdM!*9kobEyo!IpewZ=Lq~}jhko6@S8WTf2"
    b"0h*nd9Dmo3Cp4lvABY$>xvu>&oz(L7q%2!*Bod?nh<#{ekUYl;QWE-"
    b"X1H%Zzg#@sSLll<j!x(@cRSXo67K;Pfo}C!EZ)6730HiPC2dpH4493<-;e+@S9iOf2a(<ndRZ<ZN94EQ%-"
    b"drBb#6Deyt3@SG6^N#^5){T+;T8!Ecs%^R_blUey-"
    b"Q82o0MGur=S@SAIHX?~Bv?^SIbuQB+|H?QZE;Wy*F`BWKxbIzM@l;Jn)yb$jg{N|mXTq(nE=1JAN;j0=x<y7Ym+5B@YGW=$sbeS!"
    b"~Zw`8*?eD;E7D^Y{GW_PDhySlK{AQx7+MW*l_Du&LE5mO#`thkU{N|&xKP$s;M!KT&r31e?>8<v62Y$2C9qq3U{N|-"
    b"g+MgZx%}j6i+k92Sr=05CC7Yiv>3r_O??1i0R)*gk^;qL~;Wta&*80$e-#m5tRvCUX)t|Lqbm2Ew{aN$33%}Xw-nYu|+ncN$D#LH"
    b"adaU)a3%@z*;&aOIo3$P<D#LHyx)py9zjw9YYx7kNpK_{mkL(X@zn~1i8SI?qe-"
    b"D0h*yTHA_|0NZG+qyW^VmDBCq4MhWY^wRhTmLvMaQEDzuD~J_sZ~_&rWMT^x!w6y?aR+etXkpU0-_eo7L{c-@|WSyP@kv4}LS-rR"
    b"UmwRl}#8>f9%r-%e_K`|z9LPERPqZ;rdJ^QjNNS?+i5D8p}_`<>={AAU34U9IPR_|0{%=au0%+r1KhAAa-Q?H`okH{(5iQyG49-"
    b"d*wb;Wz7DdrKL98|2HsD8p~&JN;IhuWI;|Q=P}j=D%m!ALH<w0UzmlHV(fz@JVF&&4M4a9*x6q9(?eDGW=%3m&?lVn+u=D`@?TGe"
    b"5mt#9Deg*3J;dyHzVe=1}wvGPQ0e;^*H=y#XH(x<M5BiN0nHH-"
    b"^`dNt{c9p;Zsg^&dBD+C%Qgm@S7p?Spb&dH%DHJ48K|O`ie6A=E+yOK4$QnDIaP5%-}ayKG*r5!Ed&_rS&U=-"
    b"+cK%$0LK^jCoS)Wd^@F^G~|IWbm6cf3E9m2ETdpl=e>sznSyqFKxc6;Zsg^F37eKo0=~L{ASP;dMv|l4n3vu3;4~V@8j#?H;>-"
    b"a`BK1dCjFrMmjZrs=>^@N74Vx)&uYCc;5VN>*ZoofzZvy<ydV7L)bHy2Dd0D&p3?eS!0&DCzbeCTX1%f9=BpY$<y7aAY<_*J{aM0"
    b"qhJCO3QNnK<b^nDj{AStLn*SyI=Gl|?%J7?MUoI%aZ?3)ZtTOy&+ZS42OZd&VXLS5a_|3RK()~>dzd855*0&OVv+gsU?<M@^-"
    b"IKaMF5x%xzMXFKRSlnVs`G$s{ynAjW&poGv3;Qozd885*1rM#X5k;`_zmE<jl9+T8^CWSzNh&=fZtsFQrF7?{NC1%_k-"
    b"Vj{6W{V0sLm<7rMV4z;8~@&tfgZZ&p4p{sH{v<*V9X1NhC%&lcN!Rl}#8>O3TypHJy{4B<CJ-_ZFvgx?%}LC0?hzqhr2Qik6={V2"
    b"X3elztY?Y|-Xw$ZyW9{j^-tXPKMe0@L0hu@6-Lg(8MeslIk-"
    b"471oH*3GvdNYLIyq)&FW%#|Wec9%#8b0Mz=Zb9p{?D|YR`8p_?`wZo@SDRgX+5vtH;X^f{HfqKkH69VXa&ES{Kl8c@SDr;>v&i2o"
    b"6Vo<{-c85AKupeRt3Kq{Y-2R{O0rrT0blJ&Fa6@`d-2B4{z)KqJrPd{$jb!S2cXfsm_UPem|r6l;AhRU)TLcg5Ml}M(bCC-"
    b"z<Muya|5u{FC^5`2FE+UC$Ey=K6eelx6tM_9wO8CHT$vFSOn!_|5olb$v|m8`Q4O?*zYD|Guur34ZhbueDw#_|5!RZrglS!>61gk"
    b"Kn^z*WS2Oc7CsGZ?7pkzt^>wCzPGv>)O}*%Fge7?fF-go!<-F53|b7?}hEtmzAC03)@S7RxTLd?tgz)E*am}|Cf{pj9=tO-zpCo-"
    b"`4*Rl`F=#r+3el6XTozO}6=}hEF-w86WnG;@X@t{O13&zbnIU{=f4NW%$kiXTMg4-"
    b"~9jfHD&nC|M$O9hTlJ`?MNAZ^Z(Vil;Jo3KVDIW-wWGQ%J7^2uRWs-zxn^npOoP@|G)k~8GiHst!LYORl}#8>WmM2VSDvP8GiTw*"
    b"OlS7|GD#-GW_QM539=XoBuCtD#LI7f2{q1|9fHkU_%*x^Z%PGW%$ki590mdcmI#?hu{4FNc#i-_rmt-v@-nW{|lce!*Bk-@>-"
    b"j(YWS2>o$+BWY)}1F8GiHs1C59Odtv+VP#J#n|Em|3;kPfk{zw^q^Z!}RU;N(-+jk!;!*Bk7`-"
    b"(FB=KuG<DZ}rDZJnR^zZbUmzfy+Z{C`gK1^@TL_M+w&{_lnD!@V|N)$l2&I^)A$*xu0jh5vhDds5qn|9fGZrwuK`Z~i~8{ek~`Vf"
    b"$RiAOH8l_Jht3{NHby7vE8a-~4|fz8`+`|A|Xw_|5;<#gG4cVf#w+1ONBJ_PypW{_lnD3GHwE-wWFlb8Wt=;Zsg^#)rMIJu#yUzk"
    b"gPn)+_wq3){;V%J7^2uj%~8|Glt1@rE+|=Kr(W|M<Tbwl8m$;Wz(3)A@k^yF_fo`@?Vkzo`9z|9fG3U+W|O?}hD&9cB2<{~xs8;s"
    b"0LPUVUiuRSlnVsxv<9h3yG_J^t^7?K7?K_`esn_jG>Y|6bVM|3w*o^ZymiU;N(-+t-"
    b"?}_`esnpZQK1e)Io{GiCVwv)bbQ;Wz(((D{k~yHw3<zT*Gh*xrflh2Q*tPsbbo_r~_ZcWu6^;Zsg^#)rMJy`}3L{_l<LJFWltzc;"
    b"q8bv?xYy|I0->ka<zjqP*I7yREF+m~-E!*BjSzn~1i`M>`CaRmSO#x_rzT87{Je?jL9{_l<L#b1@-H~(LW48ILBr}Ym1_r~_-"
    b"BfhHPQ%-fphrO|VDn9(*8`~2H%J7^2Z|VAi|9fM5^$%tE&HoqT>*4pt_TQD^H~-&wUKxJ#|6|R6{NEefQ<_iszc;q0b-v^O-"
    b"q_y!n=<_7|FhpK!*BjStNDljdt-a+w>DqZ@F}M{<HO$A-"
    b"qZ2H|Glw&uJsQ8_r~^i{5|~U|JT~T_`f%{cjNEjH~+uT{>A^jv3;Wbh5vhFds^2|{NEef8z;)}oBwa?{K5adu|5A(8GiHs8?E>Fz"
    b"c;pbwEp7%-q>Dvrp;G1e9EcL_^@xpn$9o$-y7TKT5s@wZ)~4wKI8x1*q+q&7ytLh_Po|#{NEefi@LwV|GlxjDPH{F8`~RN-"
    b"|>HMY;Q(}-~4}D*Hir88{3DPANapFwim9I;Wz)^)%_Iy?~U#2tu|lP@F}M{<HO$A-q-yg{_l<LOT8cd?+4{%Ng00g|6T2W{NEef+"
    b"nSH~zc;oww4UStG`4kq;{V>*p3?ll|Glxjt^JGtdt-Y?#|QuS#`fm1GW_QM2bv%Fzc;p*-&Ka+{D1TBZN94EQ%-"
    b"fphrO|VqT_@Adt>`t>k<C%jqTm{l;Jo3-_`XS|My9{ulpPP-"
    b"y7R!x_;sRUfJH(`GWs@XZuR)1^(})?L}RW@qce^&ujkS|K8f()A7Xry|#U)`+xl3d)rg;4gBAW+Xn}2zN+C<PIbnIy}5lG8Giq?H"
    b"XUF5->cj6+Q0a}SGRY?hyQzZd;JGx_|5-Mbw1+%e$r0r`hfp?b$k1BW%$ki=d{1^f3I%u>i!b{_v-eI_Ba0T)$KD~AMk&#ZePcE@"
    b"OyRpq|H|~e9EcL_^_9^r}Xvszn8b?bbo>WdwF|R+k^jmd3#RhAO7#<?N#{#{_o}ONnPLZe=lz@>UiM)Uf!P2{WbpYi`azL6a3%H+"
    b"l!i?_`jF8XSM$0|6bm{)%uSAdwF|G`v?E`^7iC2ZN94EQ%-fphrPT#t?Lv1@8#_Y%{Tnt%iE_~-"
    b"|&AgZ*OY*@P99F&uRbT|6bmnkl*0{Uf!O5K^cDY|A`nMe)Inco$vU+x3_P!{rJBx>JwT&@PBV_PiQ^D|GmAvr29?$-`m>{(`~-"
    b"0;ZshLNAY2AZy#JLJHNNLC%;y9es6EzJ*Vva-ripNL)rPgy?wo{?EK!|o_<By`Mte88GrBm-rk-"
    b"&P%aqX{{8n2<&yF3{_jwE!1(s_zX#<Z<6C=sU%6uZK|cSwa$<b@_uuI@U)As_r#j=qeo>g5P=?>z+pEg(oBz+fstmvRzmCT!{_pM"
    b"Wt(TSIH~&9*Ng00g|A)_&;rE~aKcfu4`TzN!l;Jo3pSV_r-"
    b"~4|<y!gMjxA(tLhTr^uWkwl(^Z(uRHec27DW^K)!`|NB{)aOB=Kp&-9{9iC6r5_l;Q!v<UY}Ej-~9jb17-"
    b"Nl|DX9@8GiHsrT3NLH~(LY@!>cBKmJ7-e)Io>C1v={|7TxNhTr`E=tE`r&HpdnQHJ0A|8lO)S2cXfsm}N??d^GG_|5-"
    b"UzEOtX{Qv4>W%$ki?=^q$f4@n({fjdE=Kn`q%J7^2U;eHPzxn^)w14q`Z*SipE5q*})h>Sg-`m@FYs&DO|1WBO;s4&=-"
    b"qilU|Gm9EKhx%`8b0MzXMEV(+t<s=@SFeN#^1wl{y%f748QsRs^%;H@9pi~zbeCT{=d7Z48MKT@x3zq{()_g;Wz)^eoGmC^Z$i6m"
    b"Ekx4Klw}<e)Io@S!MXWy{+>R|M&Lx)C+CCs^L>kb;gIiy?w0p3jg=^_Jg($|M&Lxjn+f_-`m^wnh*HDx3_m9!*Bk-"
    b"r2UWodwcs(^9BF+_V$*xAOH88=o_6s_`kQeAH<9QdwYBPCuR7}|7Si@hTr^u;yq>f&HvZmZ}U|RpK_`*KJ4x78SQ`k-"
    b"`m^I>iFaT-rj!D`HcU2dwW~^2mkl>_NwML{_pMWskfEkH~*j3{Kfyhy?v<pg8zGadrjMm|9g9TP1gtf-=$(->mUB_?d=tv-"
    b"}t|`w|BJu;{V>>o?mbCRSlnVsxv<9?d|0+mEkx4KhyT$|K8p{6d(TY?d^NbZ~Wie+tWJ!_`kQePj&v{|K8r-"
    b")O^JMy}f;;^&kKD_V!-"
    b"<J^beX56>#YZ~nip{e}N~dwWgm7yj>(wf?R${O13w^KHJW;Zsg^#)rMVeXi>z{_pMWO<iB`e{XNk{aqP;^Z&~;W%$kiw>FgFH~&B"
    b"QP8ojl|G5Qa_|5+}zfy+Z{QrJO8GiHshZmLMH~-(#e8c~}z5Q^Z48QsR#H2F(=KmABZN94EQ%-"
    b"fphrPYMrt=5?_xARZ);Ij$+uQ59zTp4f-"
    b"k#O*#{a#&J*(r1|9g9TTKfb4_xASujWYb^|5M_}|GmAvAzu97+uKW8&+vb5Z|}zY!EgRQrTYo|-"
    b"`m?0d&=;e|4+Qy=BpY$<y2>U*d=^I_h<OOx3?#>z4*Vkw<ol}@qce`PuwZPZ~i}_`wjfx+uIXI%J7^2PuwcQZ~i}_^#}j=_V$FXF"
    b"ZjQ=w<mPG@qce`KYgkUzxn@3d_Vl=|NB~B@PBV_AHLM)s~SG#RA+qH+uN%;zWBelx97B8<Nv-"
    b"<hbPMLoBywB{l@>jy?w0tg8zGa`>ED*{NLN#*E+uVzqhv!bw1($-rio<`Go&_d;3`HAO7#{?bXQeoBuy(f8hV#-k#9<hyQzfd-"
    b"l6FU)As_r#j=q-rk<n`hx#^dwW9fkN<mndul})es6DYD#LFZxuW@m|9f})SiXS&dw2Ufz8`-"
    b"7`M>Tb@qh1bujzQ<|K8o+)BeK$y}Lc9<BR`$cY8(q8~^w2_KemS{NKCVw{Nuhs)kQF)fpf5?)I*}9{>05_J!sL{_oxGlb@C0H~-"
    b"(%@yGwYyM3wk694z^_N>ky{NE?-oYo`!-@Ds0x}M|z-re4a@!>cBKaKB)-"
    b"~4}7`xpQB?)HV|5B~4n?H%2(;{V>>KKP=|S2cXfsm}PY_qVTge&YY$;9k^vivN3udt2|1|9gvjLhBL!?>+8?Z<XOU|6kGlF#hjd?"
    b"i;NS_`kQgFLb={e?N&=b^hc3-srxR58(ga=|0nXhyQ!4drIpO{_nl+9nCNN-"
    b"<#bxmu<eP;Zsg^#)rM%eXaX7{NEeio4TIj|K9OF()Azz_m=mHuJ8E2_q;DZRfgaEe?{vT{_kDyMa>ud-"
    b"`n2P+FtzM``&Bf#s9tWJ*V>l|Mx|0UDtd3-&@}|x?bY{-uu4!RT+Ns|CysUU)As_r^sXYu=l^0o>g{!Z-"
    b"AeCqwM_N0iRn^c7AVxZ=EPRzxTk;|Do*s-UL6sQ+9suf-"
    b"j#bJHNNV4_;9&7~h`%`Bb@NeEVfJG2VdjZT^3#JY;;k|G81F7~g*Wf2o`p-"
    b"=6<@zRg!Pe9EcL_^>aErynW9Z~lKVrwqUO|GCD;|Gg!?eXI<>`Tz1?mEkx4pA#?s?_Kfb@0H;<|380Q8GiHs$ysIi&Hq=mKk<L>j"
    b"8C2`!*Bk78($B<`Tx;{GW_QM$H#5Hs^L>kb;gIiKYshVGW_QMH*YAz@BaUuGW_QM$2vavzxT-RSCrv5|DV<T!2i8VzVy2?{O12xZ"
    b"z;oX{=fK>GW_QMv%e_AZ~lK9Uk|_e|Jj5x{O141@&54puWEa%%~v&i%Bjxyu=mR^zEg(Z{QquU8GiHsgGpuh&HpdAmEpH9TK`oUe"
    b")Io{cz^iK|0kA};Wz(3(tOANy>Gs{uMEHW|M8E?@SFc%|DX)N`Typ<GW`DOZSN|>Z~ni&-{z|tKIK$reAxTvr+-t1-"
    b"~9hd^8^3)4*KO&W%$kimp@mA-~5064`ukx|F`1%;rCzFru~WkdmH`oO=bAa|L3%S@PBWluWNqe|K3U8JW__=KfO)-"
    b"_`mnkPjtTE|K3c${i)4YHGImc&iJtR)8{@=hTr^O&##T)|K3r*(RzXZdrST9eP#H~|L?Uu_`f&RucwvaH~(ML`h@>`Tm3@kKmPAG"
    b"kt?q%!*Bk7^pZ0C=KnWZukn9xt?%9{!*Bk7yrvAle_;Dso3Cp4lvADYVehX`{8<@(^ZyO)Z~Wgo?6X>b@PBWyAL;zY|GmdPHLnc6"
    b"`TwHMU;N*@?91AJ_`kQ=pT4LJzxn^Fc=3O4v@gA&48K4BzoQJl`Tya8GW_QMXPSTbzc<^jziabV4WDwVGd}G7_IYhD{_hR<%jcBg"
    b"H~)Y5Ss8xw|1E7l{_j2a2VHOQe{Z@UYChus-gTdUSs8xw{}WwL@PF^SA8P%?|Gn{ksQHiod*^*c*E{^*TkkhtD8p}qENMN)|GoKs"
    b"`(>N2YWS2>o$+Dszpv@~f&Y60e)?-"
    b"=`2Cl)X+6XLy#;@!{fqy55B^Z|1ON9X{BmUY&Hrb#e&GM!hM!+mhTlKEP4f}|_eT7J)&u<CJMrg-"
    b"%J7^2Pc16LZ~lMzl`{PP%i4Z!^HmL>a;h^v?EUzMca-5b|6ho|hu{5Q=L7!lE%|e;ANarb<R5gs#s9r2f3Niy|M#x^g4P54-"
    b"`n!%*UIpl|4(cF<Nw~6ztZ&t|M$-P<zJNHH~(K3AO7#X`RQkr;Wz)koNn_~4WDwVGd}DRdZ+Eh|GhzfuKPFq-"
    b"#heAH9r3DE&7{HW%$ki4|M&-|Gi1S^O`dJ=KmL3AMt;0(;sU-<Nw~LKi2l*|K6zI(fr5%y;HyWn=<_7|I4xc@cSpWYrf+D-"
    b"mG7LvCUUCe9EcL_^|iu4^NfhH~-(&{Tu%8QhuWQLHyra_B-1D_`mn;S2RBU?@jxMJ!SaK{|{n3_|5-!wVvVs-"
    b"nZWnFaGb1`zx*A_`i4Vr*uD#|9k8HTGt=^-+T9mTF>x*Z{ANHwfU-sPdU{YANKzJmevdW-"
    b"y8UAI)3<nbnq=fZ}xwtt2g%Vo4BLdi~V~K|5kS^*uOXNFLn2e{d*VxNUJ0E?``}^Z9Vqyef(vuHrT&6@>l<^487U^lFoMQ-"
    b"&^_n+I!f)_wsLlY|~W@opP!(Htg;EU9CRYzxVTxwK`+}-q4@Z-5>Vv9sM(nkNtZ~|3<SL`}dyyjLt^v-"
    b"w)ZQW()T3UHu1Ly|I69>(6Sn!T!CkzpT4g?B5&vm%7?v|K8cZ(Eh~!y|sTGe-FRe|H-"
    b"dyzN+C<PIbnHy}f^_t26fR{ryADPVC<s{13XD!v4L(e-;^jv;P&{4PyV^<3G{y!v4L<KclM?_U~Q(xd&zV4PsKq1N-"
    b"+r|5Cg^{QlGb*gp8p{<pPyV*lRipOt-K|K97L{7aj!YWS2>ov~qW_aEzS9{cxx|Gf4e_U{e<bzOb1fA9F8>Ud-S-txba9by08^WW"
    b"BLi2Zxhe^L7r`}eN@vE~!@?`{8ktyb8-_x*Qu_F?~iO7H7@!v4MUzo_Gf{d?<wTQ-"
    b"6Hd+&e#gEn8)@F}Or9k=13xBoA%l#PGr?f<1+W#b>x{{K|j_=n#9U-(to_=n#9UytuM{-L-3SH4v?{-L-"
    b"3CvTOFf9UQ1vmccU#<ySB^|Nxx_||^;LwUgXMYPL0ZvR7X|1bSTxng{q|4Yh=@$IJ{=WV{K;Zsg^9wFO*<}Q@sH~ZguNf~~#|Lqx"
    b"N_|5)TUQ~wP?0<4u8Gf_>+wYa(H~WA6Ps;F{{h$7(48Pg`?sLlUoBi*<rwqT@|Nh^U;WzuA-"
    b"B5<#?Em2dW%$khXLs9tRl}#8>O4wz`@dI)-"
    b"|T<>J7xIoe{TF;8Gf^WJ&oTPh2QLd>Qotiv;Sr7k5Tx|{@;038Gg6_2W9xp{!iXkhTrV}txaY4&Hk_7QHI~_fAV={_|5(|{-"
    b"F%N+5gsEo3Cp4lvAC@$Y%cw`^xZ}{p;!C&KUe=|EI4j!*BL~tob?yzkSj2jWYb+{{LDTezX5i;_Klz`#;g~8-"
    b"w5Me^dK=41Tl!k2U|s;5Yl<jPc<&```LT8Gf_>U7gQk@SFV~eB0)$8b0Mz=MLHIe@^e;f#2-"
    b"^vvp<o&HgVmpE~fH{a<{k48Pg`<)kwF{_ENz!*AcTJ+BPE*}vLEoeunF|67;J@SFW_zpM<u+5f}G%J7^0@4c%GzuEtnIzKz`oBba"
    b"zwE3!rPdU}OOE&vo)%n+j-|YWq@pa)h``=zwhTrUePRF+kzuEuhPs;F{{V!^Mb>TPrzkWp-"
    b"ezX5o?cXl^_9n;gE5mR0f1~-_h2KBBJ-#1)v;Wn2fB5}3wd?%v!f*CJ@qC-FYWS2>oqJ@r{}+_uH~XJ@Lm7Vm>A%MB!Eg3|tM#u3"
    b"zuEtp)~g=;X8#9T-+J(y{V!>M_TcxQ{>S^nZ}z|VR2hE%?DjX6;kP&4d`%gCv;Qrv-"
    b"#z&K_qFXQ!*BM#_HvuAYWS2>o%>|7|3w|oKKy3?$4AQWoBiKu{`TQF`+xRK8Gf_>LtT&h@SFY5{#hA*v;U`B|NHQp{U7W2^x-"
    b"%A|3>RoAAYm{#m|-D_n-"
    b"c2|MlTF``4#^bo%hyAbZ+Befa&e+ka{ERSlnVs`EJ6?Egg9<8k=S{`uX+mf<)1U)S*(hu`dfLD%zf`2DlnHQqS<X8%`OzsKP>`@a"
    b"#-"
    b"IQ(Y+Kk5204!_y|evA*l*}py=r!x+}|El(9l;Jn~|Lj9$_|5*8HDAWzH~WwKmEfxyKIK&BjBNJ5t@)S1Z}vZ><C(#4_J8=SGW=%$"
    b"hq}IH@SFYfyO%A)Z}$I&j&}yX+5ZQhD8p~|f1&Nm;5Yl9)cnfeH~U|R48K49ul<?9Z}xxxS7rFk{;#y&X7HQ+UoE%!s)kQF)wv+s"
    b"Mm*^F74Vz=FYErRfM1`WX9;?Jf}SPV&HRtGZwlDW{GZXar-"
    b"0qe|5R&d0lS(1Ge0Q9Zsz}tjzs~xng8Zz%CMXHAH}x8ZsxzQbEkma%>P_#eF3|f|2q$DwyI%MPIWHHX8z~8w<%#a^WW3CRl;r?HK"
    b"(~yLhn!h>)yA7-=F-~xm3b$=6|4j&k}w!|5dFeCH(rFJxkE*bM`F3uFu)C1i3zE&l24FoIOiW>vQ%j!K}~OYly0bNIBJcK-OpNS%"
    b"O!ewPy+1@chmI)<GQU0i^n@Jxg%vv-"
    b"T`Osn6Q81mhqW2QUtTaRB2W7zZ#8f^h)jAQ%TQ4uWw2;~*G=p?Z|`S!SIfX&8J%_=dqZgl`ypL->ZlH-"
    b"v8(d_(w#!8e3&7<@zchQT+4Zy0<-_=dqZgl`ypL->ZlH-"
    b"v8(d_(w#!$%C&qZE7<sS3UdzAE@C_^RNm;H!eKg0Bj`3cf1%D)_44tKh4GuY#`%z6!o7_$v6S;H%)Pg0F(F3cd=yYWRqudX$1Mky"
    b"7v__)_pC_)_pC_)_pC_)_pC_)_pC_)_pC_)_pC_)_pC_)_pC_)_pC_)_pC_)_pC_|otZL-"
    b"i<$uZw+p*Z$%QWheBm{p??qozc7Y7tbg=rFZRDu9cnByY^GhDLbim?avmJoz=Vc$KNYEt#|G3;`<B6x4X^1Dwm9JKWq9*dBFJgS!"
    b"+wmL&mqCHAb!&-+tEet8!v|d)EA*%~v&i%BjxSr(c3Lr<LJ1+uqUlW82=fpTAXx-"
    b"@EqOK5W~&_H)lG!*8}d`K&VhX4^YoE5mQLee!`a{ASy?C(7`fZ6EF`!*8~I`=&Dd{;d5Q%JBQM_FpQ)Z??U((&nogKIK$r?9;pUH"
    b"?zv{n{B_N@vv>b1z8Xuw(VW}TkU^rn_rH;rwqT@_CjR%&9=8cREFPe`v+zC&9?XA@8S1fj;`&;w!LeA`nxjxX4`u|DZ_8Jy&f5Uv"
    b"+a$uHec27DW^JPpWd}!TvmqPY<u!b8Gf_vnQxTgH`{*rvoielMaP;S*tU1=S9LtFZSUH@tNnp(d)NN_MP>NSw%0yWhTm*^M&|>z?"
    b"Oppz?GJ3*yY?H}U)VOk9DPa|ezWbR+csa-@F}M{W1rr&U)A}DZF|>#N#kSN-nF0FP=?=Z`(a%fezWc4d1d&`w%^r!#<u+ybuZoze"
    b"zWbBNoDxWwkO4pZF|@LcwZTQv+b=lW%$jux3nH%+upTbj|{)r_Q_eBuWI;|Q=PF-"
    b"@7nL^_+Z=KwO`i!#J0U_f3EqCZF|>#eMcF7v+Z-u2W;EB_KO$F@SANP>-b>X-"
    b"nC!;P8oiClZ~I1;Wyi!j_rZpZ2L~@8@BCT`_=e<_|3NGVtn|`w$Ikvd{x7zoa&5yde{C&=MT2+UHjvYl;QVZj{dna{ASx1hsyAqZ"
    b"J#bG!*8~I`GPY1X4_NR9&FpY_7_@zux;<!FB~hw@4p;f>npbH3bX!+GW=%SClAW-"
    b"n{BUsstmu`_TBewzN+C<PIbmUy=%Xw<Be_8wb%Z^w!Lfr?%T@nn{CfcD8p~Iy}hjrzuESRjt92wUHgl7mEkwrKGphwZF|>#?-"
    b"gbE&9?Wn{n)m5?XPuyVB6lczliOF-v&ATMHzmx?d`v{`KpFbIn^2a^sfEUsWSZjv-"
    b"Trp_|3MbwEkn;-nF07e8#rDYd`glGW`Bod)i)X+q?FMKPtm-w!N$K1Kakl{gu{NY}>o`XIk&DZSUG&X#Zf_-nF09@yE8kYrim~48"
    b"Pg->SCL(YWS2>ov}~v+D~bFv2E|#uWEh5w!Le=uk{w&_OAW$sxtg$+jBY}ux;<!FKWJG+jQ-"
    b"9KZR|3*M48uS8Ut6_Pe^?W82=fU(@=BZF|>#<t1hK&9*0X|AK9M*M3>+BeqS~{;JJaHGImc&KRg~#Nt1c;Wyi!)cnD=y=%Xt`x$)"
    b"OyY~Cy!MMF^fA+C5{ASz-"
    b"?<vD?#(k~r!MMF^Kfk36zZv(Acrb47+Mm6w48IxondS?|?Opqs*OlQn<G$DYz_`6@fA~e4uWI;|Q=Rcq@7f>zrVPJ#?RC5{Za*k{"
    b"x}IX(-nC!S@x!<?eWtx7=*_nmbu{s9Z`$8$b;q~8X@9HPfpL4&o?jDf8G8TS=uefQH|xHN(V#c)UeVFPyuE3^quGjkd(-}Kp-"
    b"opcbjqpDxT-hpkLQ%3H~-$#YKDP((|-L%8G3W@J6#R2aG#>*TD|dbZ`z-"
    b"}uMEGL_^z%VxVSg%S9Nv9#=U8OuCpB<_on^1?#?iBZ`vPgwZh50X+Ndeft7pHeo<F*yxg1i8%u4zs^L>kb;f1AX@8*A7C-"
    b"l<{fhP<hVD)Kb*(Nqx;O1tbhW|Ky=i}_<B6wx(|+mi%JBOyN!Rw{>fW^9)!h-c?oIn^t>*Z;H|>{oH-"
    b")i#(|$>37tZcY`)#exSi3jvcXf8*?KJIwX!BJKpK_`*uIo+v!?%>-H-CT7-5Lh(P5X7N-Z;EB?eFiD;Wvvv(%Fc|d(-"
    b"|*XBQ^#P5Z<6dic%d4`hqjyf0yMx|-ng-n8G*-4#afP5U$LPn_PH_6zsQ@SD}&YkuPO-n2iTX!BJKpK_`*F6>SF3vC~M?@jw-eLs"
    b"fpP5V2Ye>lE3?RRx`$MU^tzoDx;p6^ZjMIAp(-<$T!x;w@7y=i~0`GoCz(|%8@E57ed`$eth7{4#+OFAEMes9`8#QVW-"
    b")_=dL48M8*>^E(`s^L>kk$c#%H|?iCP<DQA+V8)l?EK!ezj;^L`Mqg>_lL6cd((d96=mo5rv1sfvh#b>{^B=f=cj4^hH}C9_N3kG"
    b"$|d95llGI!1ID)}?Y>nWGQK@&{iSln__qH2T{$tnH7)*V^HmL>a;h^n?3aYakCov!`+t~FhTrV}eoYyEv;XDamEkx0pE*&6-"
    b"|YWkK^cCt|J5mF_|5*$;_Kn}PuhP@8Gf_>lX!pl&HfMfmEkx0zmC6$-"
    b"|YWJ#}oVK_oN@T`KpFbIn@~(_NM*LUzOoE`@fh~hTs0@?WfA{oBgkRp$xy-|J{r-"
    b"{AT}`pDV*}_J1~~48Pg`j*buZ?@jy3e<;Im_J6MZf&F{a{%%znezX6D_<s1!{_l>J;WzugnQQY^4WDwVGdAo^`zwuy{d?1XRpVj*"
    b"-n75e@xuPSX@9$@48MKR>asHYX8-#-{@A}a?T@v;v43ycA3P|-"
    b"Z}z|NzB2q~|5G}i*gwA~{byzP&Hk6)R)*i~e?{jH_U}#myPw*8Rl}#8>WmG0(|-L~W%$khw_a6--"
    b"|T;LUKxI~|AQlC`29)yD`oi2{x=Vl;kR!((*DN&y=lK8e(c|y_8Zz>?BARAm)FYhyZvt~!*BL~6<-g(+5fTD8|>ek_V-"
    b"h5zN+C<PIbnHy=lLu^#%L)rv0Y&5BBd(`@NTy;Wzs~SW$-G?0-(j2m7aKulb1md(-|>^A-"
    b"E|ru~Z67wq3}q3@nohTrUe=T~L;&Hg9<qzu2=|E<<9?BARAi<&>!zc=l-"
    b"K5O$;4WDwVGdAo^`&F&)*uOXJFD{hfH~Zh!_G16uv_E}Q8Gf_>ceOvTe{b4fX??=}y=lL6uMEH0|MZqJ{AT}~F&_M8{}<Z-"
    b"*uN{qT#N_5+5e>Yv43ycZ)_;TZ}z{l)aI)iKIK$rY}lLjcbCfWoBgk9zGDC0wBNc_hTrV}PS+popQe3e_|5(|UQ>qO?0;G31NQGt"
    b"`vt8Z*uOXJ&%alO-|T-@>nrx}P5U#=SM1-L_Qx?E{5HtlsWSX#|HqqczN+C<PIbnHy=lMrgEIX7d(wYVhTrUeP4AEWd((bS>pS-E"
    b"P5VpD5A5HY_9t5JuzzpbPw9AJ|K7BpjrW7!?Eg^n7yI|7{jshm*uOXJmw!}--|T<mJ!SaK{`K?G9`^4|`?Iw+U)As_r#fT9-"
    b"n75h@xlJRX+I+#?BARA8`@s%-"
    b"<$T+T5qv`Z`wb+r3}B>|IMB<{AT~R+8*rRoA!sA@7TXL?RT_)uzzpbPwV(#|K7A;(fW)1d((bf=L7cdP5a9j4}P=%{a4$3Rl}#8>"
    b"WmG$f^X@3#Qwc$f2#eB{d?2?O52P5d((bi>j(DlP5T+0AK1S)?dM)lhTrUeS=)#Gd(-|v>jC!fP5Zldl;Jn~zxj(Y{AT~hx?W)a-"
    b"n75d{T}x3P5WhCpRs>$+He2b=BpY$<y2>Un5MmWv43ycuY9KrzirgjjWYaZ|1%#d!*BM#tNDumd(-"
    b"|(#|!`Wrv0||5B^Wn{;4wj=KlveU-"
    b"5r$+8^n9g8zHde(7sv_|5;1&y?Xe|3BCK!vDQ#zx8vQuWI;|Q=Rc)Z`$wZc;f%wwBOVA<Nw~YU(o#-{_jouQymZd-"
    b"w)EY?$_~uZ`v>FdWHXc)BZun1ONA?{fy=x{_jouW6gK`-"
    b"<$R~;=}*FX@4Oe{NJ1Q_qzYV|GjBHulb4pd((bpwar&Ge9EcL_^>zaXEh)3e{b5~>HYA3Z`vPdy}<vyX}_lVhyQ!ier87*et*_p*"
    b"FXH<C+&WW2fz9MMvMo)f6~6@FaGaM`(^nN{_jouJ>4JR|K7CU)cq~~?@jx;7!Q8)|Esw+U)As_r#j=q-"
    b"n75cc=*3J?bo%w;s4&WKhyi;|K7CU*Zmg$?@jwPZ6E&cP5Wuxui^jRwBOVHBL449`$hR6{_iL8@<+<>oB!YH`i%d3)BZ^37yj=}`"
    b"x#v?@qcgHPip_+|K7BpdbZ71HGImc&iJr5?Pqko!vDQ#f2!k&|9jJZOXK7J-n2i_dWHXc(|%3&qxio!?YG5;|9jK^K-W|J-"
    b"<$TQnh*HDH|-C^kN<nqen$6;_`fe|S6VOde{b5~#`nW-{y(kjC;snE`<w6Dd{x7zoFez}VQ<=Rf2-{L-"
    b"n75`M%nqjX@Bv7vh#b>e(_CZ=l7=l;jOasd((dHLuKdprv1@hl%3z3_N%Wd7mRQB|L-"
    b"f8jBoe9@qPowx9i{c%0tFC|DRQ^7~g*SH?5o)-"
    b"|qj;+I&^Rr=04H5Bs9H_nR{O=Kn``%J7^2A73lOZ~i~|mNNY2|BKo_{NJ1QYi}sSZ~lL~tqi~U|ILFk{O<op%JBPd+M7{^-"
    b"~4~+L>Yeb|I@FO;Wz)^{!AHu^Z%KxHec27DW^K)!``&NenA<2^Z(g*l;QVJ+K&vs`Tw<!FaGaM`}Mb#;Wz)E+E<3({C{Rn8GiHsl"
    b"lXi1&Hrb$Kk<KW+HdOk;Q!vV-_h~K|GjCyAKMSV`Tu0RKm6wZXY*~os^L>kb;gIiX@7sH48QsR<#)>PoBv;E`|y8n+Rtcy;QxM;u"
    b"(GENzxn@~wio~Rrv2%PGW_QMyHm>WoBz)qE5mR8fACZpe)IoX&3F9YoA!4xKK$nYM>=2de{b4feBS1(8b0MzXMEV3_7{uF@SFcnY"
    b"kd6QoA#$aD8q05zy7;2{QlGbPnF>}|6l$|8GiewEuBC3zc=mY-"
    b"&2O){Qu}zW%$kiS9SdHe{b6FZz#iW{y(APi~oDm{$A$`{_jouz0)>d)$l2&I^)CMv|rcz;s4&WUwTOye)Ip0kCfpz|38058Gipwd"
    b"zz2<zc=l-R+Zs5|3B0A;Quu3FO}i9H(AjB#s9r&Kl7t9{O14juPDQB{y(kxg8zHde&<{ne*aB-CvCo};Zsg^#)rLWe=?yAzxn_D*"
    b"UIpl|F390!~eZ$e-K{}zxn^Q#>4-"
    b";X+N#?0{{1>{h5vr{_joud##7~zc=l7;``w@|3B3Ef&cqW_2s5A{O12hTHo=1Z`$wwp$xzI|H?|6uWI;|Q=Rc)Z`$AJ_~8HEw7>n"
    b"cGW_QM6Phphzc=l#zf^|b{C`=;AOH8J{lbni{O12>SIY34|F7$K;{V>X-_!bu|9jJZ>qZ%V^Z$7rU;Lk@{fo-"
    b"*+aM>pe&GM!v|rh6^HmL>a;h^v>`nWvC1v={|EF|5;{V>XKhXJ$|9jJZQ|AZ%?@jwvt$+BxH|@6;l;QWE{_A|k|GjCyr~3)~-"
    b"<$U5n*aE}H|@`Le&GM!v|ozth2Q*tS?d@6?@jxs@&53e|1Zq7`KpFbIn@~-"
    b"_NKjl{@Ta?y=i}|^&kKDrv0_<SMYyt+V8%s48MQU{@;}0H~*hpQ-"
    b"<IC|3Q5Czc=j<G@tN)Z`z+~{l@>jX@9EwCH&u;_Vb$W_`f&pw{-"
    b"sE|K7B})%6Vj_on^abepeg_>@zf@nM(HbG;w_?@jwl?H~N#oAxWq%J7^2Uu(YM|K7B}h_8p={C`jL0sr@={h97}@PBXGudOS?Z~i"
    b"~2`xX4(oAxKV{^0-Kv|rWn#{a!(Kdtit|M#Z-q3(z9e{b3^?zQ=<hEF-"
    b"w86Wnh{jKH;{_jouwNI4cw~gA;^$!2{rv2T$GW_QMM_MoNe{b5~>;4)4_on@&`0#&k+MnwF8~^vF{kG;C{_jouU9Bhhzc=kSV|@7"
    b"i=l{C@#{a!(zxBE@{O12_$8El<;Zsg^#)rLWf3Nw5|9jJZPJH;kH|_6!R)*jF|4Q>0|M!ht(DB9py=%X!^%ej3uKl|17x91Z+8^q"
    b"C!2i8#Kd<u}|M#x_lJ2MRfA89VsQU^0-"
    b"@EqT#dz?W|8Hym<Nw~Zzy71mS2cXfsm}Ot8Bgc;vHvoj&hO*?WjvkV$NbB9I=_$im+^FdAL}pU>HI#<U&hn<eT=`1r}O*xei={a_"
    b"p$vlp3d*%`ei(w-^cXJcsjq2=a=zxejm#(<LUgGp?Z|`bax-"
    b"$E#v9@K6YQm)A@bezKo~y`<Q(hPv`gX`ZAu*?_>34Je}Xi>C1RJzmL(E@pOJ4pD*L-"
    b"{602c#?$$IT)vE_^ZS^58Bgc;@%S>H&hKOKWjvi<GgOaK@Zqy%Je}Xi-phD8zmL0@@pOJ4b1&oR{65}Z#?$$Iti6n<^ZPh^8Bgc;"
    b"G4?W^&hO*vWjvkV$JWbuI=_#rm+^FdA5$;m>HI#PUdGe;eJs6<r}Jxu>QRF4N&e(X{5cYTj>ey3@n<Lg?8cwH__H5>j>n%_{8_}G"
    b"W&AmaKZo&W6@SL~BQgF+j6V|NkHq*RG5$!5KN91Q#P}mI{z!~J6624=_#-"
    b"j?NQ^%c<B!DnqcQ$yj6WLVkH+|;G5%<bKN{nY#`vQ#{%DLp8sm?~_@gnt86%&CX0NLJ-_VPsj~jiGn;t&Vi;;XpFGllGy%@{K^rD"
    b"k@^rD-0^`e*e^rD~l^<q39*NZIA^ddHAEH-B>HfJn$$5`x+vDh7**d3kN9i7-6o!A|n*d3kN9i7-"
    b"6o!A|n*d3kN9i14z6XSPc{7#JDiSauzemBPN#`xVBzZ>IsWBhK6-"
    b";MFRF@873@5cDu7{43icVql+jNgs%yD@$*#_z@Wy%@h2<M(3xUX0(1@q00TFUIf1_`Mjv7vuM0{9cUTi}8Cgem}<V$N2pizaQiGW"
    b"Bh)M-;eS8F@8VB@5lK47{4Fm_hbBijNgy(`!T-Vs26%Ml9zg6pUt5cWBE`oI(elR-8|_<FaLM-qM!d$y%^8`J-"
    b"x{Ce_t<({6El(GXD?tVvzqwdNIuZW4);I|3oiR{-5%~Zk+!!y%@>=bG;bN{|mhs%l}Kg=;Z&EUUc*SS}%I}f1?-"
    b"u{J+(U@%+Eji!A@|^`glCRlO+nDZ=*3?(!$}Dt3?E*Yb(4_A2H7CNFG#{ulLPB!BvxUXAAex?aRlD&i;=ag>TUN<|!{B92lKN2!R"
    b"TRK!s#;wTld8ATi=yRG~mc~QnRDPx+HF-^+YfHF3qj14Gb1IpNdGB%)$4Jcy+%GiK1HlU0RC}RW4m?nc5e-PsjV*EjjKZx-MG5#R"
    b"NAH?{B7=IAs4`Td5j6aC+2QmI2#vjD^!x(=U;}2u}VT?bF@rN<~FvcIo_`?`~7~>CP{9%kgjPZvt{xHTL#`sl?U&Z)Uj9<n0Rg7Q"
    b"7_*INw#rRc>U&Z)Uj9<n0Rg7Q7_*INw#rSqV@-OMdNdE8W#c2LN=tXQoicPSaj(?&T*2mXePO%j!w!-"
    b"c&p04XvY)6XiNU<F$wj;%MaQE>41D{rR?E"
)


DC_CHAPTER_TITLES = (
    "伏击之战",
    "街上追击战",
    "进攻基地",
    "救出人质",
    "荒野再叛",
    "再攻要塞",
    "内战",
    "荒野谋略",
    "激战大扎姆",
    "燃烧都市",
    "幕后浮现",
    "激战大魔神",
    "白河愁的试炼",
)


DC_STOCK_MUSIC_LABELS = (
    "大卫主题曲",
    "盖塔主题曲",
    "加代主题曲",
    "古莲主题曲",
    "吉尔变身曲",
    "安东主题曲",
    "用途未确认 2（旧资料编号）",
    "地球·我方战斗曲",
    "地球·敌方战斗曲",
    "存档曲",
    "敌方增援曲 2",
    "游戏结束曲",
    "宇宙·我方战斗曲",
    "敌方增援曲 1",
    "升级曲",
    "吉尔主题曲",
    "瓦尔主题曲",
    "宇宙·敌方战斗曲",
    "用途未确认 1（旧资料编号）",
    "通关曲",
)


def dc_map_label(map_id: int) -> str:
    if 0 <= map_id < len(DC_CHAPTER_TITLES):
        return DC_CHAPTER_TITLES[map_id]
    if map_id < 0x20:
        return "未使用关卡槽位"
    if map_id < 0x64:
        return f"备用地图 {map_id - 0x1F}"
    return "超出已验证地图范围"


@lru_cache(maxsize=1)
def default_dc_text_table() -> TextTable:
    raw = zlib.decompress(base64.b85decode(_DC_CODE_TABLE_B85))
    mapping: dict[bytes, str] = {}
    for source_line in raw.decode("gbk").splitlines():
        parts = source_line.split("=", 2)
        if len(parts) != 3:
            continue
        _tile_address, code_text, value = parts
        if not code_text or not value:
            continue
        mapping[bytes.fromhex(code_text)] = value

    # The old editor rendered F2 as a backslash; in dialogue records it is the
    # confirmed visual line separator.  Keep the terminator visible so users
    # do not accidentally remove it while editing Unicode text.
    mapping[b"\xF2"] = "\n"
    mapping[b"\xFF"] = "⟦结束⟧"
    # Dialogue bytecode embeds numeric parameters among glyphs. The supplied
    # table intentionally leaves those byte values blank. Give every remaining
    # one-byte token an explicit, reversible representation instead of showing
    # an ambiguous raw ``<05>`` placeholder or inventing a semantic meaning.
    for value in range(0x100):
        mapping.setdefault(bytes((value,)), f"⟦原始字节 ${value:02X}⟧")
    return TextTable(mapping)


def decode_dc_text(raw: bytes) -> str:
    return default_dc_text_table().decode(raw)


def concise_dc_text(raw: bytes, limit: int = 36) -> str:
    text = decode_dc_text(raw).replace("\n", " ↵ ").replace("⟦结束⟧", "")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
