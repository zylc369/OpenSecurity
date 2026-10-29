#!/usr/bin/env python3
import base64
import hashlib
import pathlib
import struct
import sys
import zlib


ROOT = pathlib.Path(__file__).resolve().parent
CONTAINER = ROOT / "challenge" / "flag.flag"
RECOVERED = ROOT / "output" / "recovered.bin"
ORDER_B85 = b"c-jE~5dZIN^ezzO-k-leU~&^wYY?#E?gOY07G)3d?skArmM3qPU*xdI$Wr*7aUsKYFOl=rQ?!9Z#KP;0->jFX1|McJRUk}P)2g|ZEU%<E&a!wF+O4n8Z*n&EqbT8V@es1as=rJ_;rsQyQ6qN699i&JHwI;rVJtIF?swz|-Y_!DXjW{1fG!oOmey$HLsICIjzXfIfr>Eyql1M~ZBYJTch0dgy&a<{s5|sYGB86NsAP`aKBYqii0o%9j)|9|n%;lkXQA}yZ*S#;qJEJ<_NU(0sHD?lPTyJ)K$jfc3P;k$ut%#0W6r&HN*Fl?JP_5XqXpd@S1M@1$cl>03}ma`Im8`KJphm1;OtiHL}Gs0VmqQMyxz!?AIky$Ici$v$mu&}{et_!m9W{l66?(U40DDTB-B;mmGppzW(<M`&C_b%&cWDTPiZ!_%J<BA^dPWm-tyk|1T|ytvb2tT^+E<7jW_z8$eJ_oPK+JgznUACS~oH=c<q#er!mxRhnj40y`l-j_Ke+SjBOVorvjdwC{sVR=6n1oj$@{}vQ!h3o)#}gsNoUxcwy9AG@}Ep&%E8#7<9XqVH|+Jrnyg1&|4OXzlw#Om=e63WA;&n{xZ;x36X>P7X*e%a*ftwL1Q;IK(D#c*5#k_tO|u8f(XJli6(OQ)0U<}l)#EP4M}Ju5e3G7@K6&kr~>;T%jdo&r*&;#k9SinrC8$`G{TB}kU*5v=%QFksKJ?R>Qx4Nt6&cdl?0dev;2#p-n0Y)zhA4=rwe>3t_{~Z$hqUbC;Dn(o_YNfDMVxeE08i5&cxP&`_`po+G%agScgSLN8|5B?tAx3YKmrU+ZgL--K7qX@ztA3(Hege;e10t;U{&qF}VXFwYKR*2?0A++&3shUy(o)hp9CsVChMeL%IZRXf?v!3*?bVz*XrRg^A*M6?OLaH}h5!wm9G?Lwuih{hdfRDQ?}__>vCKC3>L*ttHgMudOZ3+6;PPDib|WlI;F<F9K18=xf-WeD_nXdH1@4i7{pWPv+!@xmD(#+J{6M$HNokL6*caHRD9+)ZhyGnIzMoxg+5zO(x^;s>}N;+Mx0|{z6<Iw$Io>%mVzU`LBu2hg8@KI8V!<h8swsqL2>@8zy2uhe1hg_4IDQJ|k^=PIvthBhp)x7~G^I84XJY9lMm<$!g%>zf0#bWzTJ3PMS{eZ&~Oajpv5X0qZO4#|HG(4FXL}eG)?3gNMK!gSTnY1y9?uO+9>vYJ-Me$zdJCDS~L(<&c&`#Sd7IOoIDD3|ClR&P*X2`)otIKeN?LH>JUx&TX#1FTd6VqjiM6g_GSPfLGbTkwD`N@MfSt$N~&KQvweNMGB0T7sYR1b1&c84j6)&IC+rCi5|PeBPa~f8ZDKmQxxe&6r4de7B~**QY-*cpRm{^li`1&+hq6M+&%o}B?2=gz?}gwn96uZB55NyAg$zcI=QD4g#!w;ckQ-rxnasa-!J&7#UimIJ9Hl?4Gxv%mxByW*gQl8LcG2xTX8ztLtg53^%>RYA}I8)G7S6)!fIUsCdKI|7TarxZs$<+NK0w6%U{AQ%QpE#Ci<x2ND)_FPP_{pcM^@H8caPy2SKY(ozI2Nzq5BU(W_sb=P!_7LF_k1s_BrGjVN;ywPWZ_koFZ{s+(3Jaq4}=1Ujosh@aMpRb>>0=Gb8O9hCI|fEI1trsqW+VN`*%0Z!q@g)KU^gdzA_mvZ|Va7%kdl6CUhJwdufy^v55l$?x2V+%H7`=+Y7!_RREqM7{YH)WNS)?ih*b^a#Ofv9AJ!P_zHG(!r9LD)LDzC$a3Sj;Wa1Ci>JAa*x;rSi2vJNu)kW+x4{vfVhjldHtS$a+%(&0Qljy>gLG_f`|(c}yt^3(7{dkDL{7vCw~pIniOdt{193P(ULS@+GF+0&yxpD4{{5U-s-;J2ZkKGqzA=ps`s!HI!iDS;gPpg&rFlY`N$Er=!{it!2^xT}iXm(<Tkd@|!QJfkDWrei=6q(iLz&8ieI@&H+}$K)%WJXMWa@nT9pb5_%@z(c<r>JbfLQYL$3~93JEDWgXJed^F<|CyM)$!z>4GQV*(RobP)luQr2zMts7p0&U{sh1Row)D5^*yJEypFPF6*g=v|XDL=O3I8JvHgRMiy#-l)bsND4o1i`}TCmVKZH3M&l6n_<Xlvu-Vg<%%h96#rW<@MFXk0h^lNLbolE%`g}jcu{TSb%;<uw-WQW6H>G`SCz_+JizVPRI_XOunVjIkeTLhZ(?hLvuTI^<SC#Cyjssp#ru&4rE%s`J_q~Q%kFyA0A!OYQ$V7H?Vo|-~~bEwR{-y34OH2SMQ}nO^)f=l(%zKk+^`Kb0E*!zG1M7iro}CNcrKl<8ye%?ArNwK~nvM2(nQu2=QQF0qDG9leRwEGRD;swGMl9F$*1dZH?V^1`dj;T~LnSo!5;y3rslmA6KL1y?Hj+FvagN@yS0D6$vPZ4a7p@0~K16x&-w5+@!SW;IF>`%CxV(v*WX~o-9P6MktUV9*6>j5|=vnK`kS`h><PK_cu)?ol>iU+dw@%*cuyQ-~jUG1V_UKr6|`A{K~}qL#6GhmcPgpYa_N@qmswyKp?+eM<pO)tGBn!2!8FhD`I33hH>y#|AIPe008`TyjB=TM}TwTv<HM7fXDZ8)IKx%;#nw+yR0^lou|nsTFRo2MmM?o#?*&x`4k+AZ{DjV-yCGbIH|P(iSNq?zTS+9yGFF8HxPp7SeB@KNjJZAZha&`o>_+5b>2ooeN3wwN&cA*scs+qMyw)6Tg3%oa0rj#Ju>AEL@T@mUB?)kndx90Ha#LK)OVO85zWSa^rq)4d^>VgEnA~Ued+P9U3|fj+#g;xYvXKk@vhWM9V-JT=q+Qe4~btO4|}WJigiB(KRJqXHG3(-z0v$@HX%c?dha=@O;6=!bRo^VCems>T~7tG)gR~byj%C@VU2u2F9T|mbwQgsDluG|G2@`dH{mcXo5~OE3LNb)u1>o|510FdQ26J%kt!6T0)(X{v}QY-7Jt$L_Y<Rre%n~dlU;yGc#o<6r<agVBG2d#jL=3f$g^kR2vj~vabMamU()hj`~y<UYVU7$+3xXT8Mt_IP@Tr$iXqSac5a&G^NU?Rmb)E@IWBH5k8HB&RLmpIvMo(#%^l_BkoHo4XRz7*Cb=lT-1oS&^giBT@%Ur+706qtrynW^BnLy)*xW9^kiBFbwaxaz1=4P4vt1RaWScC!J3defSHO9tL83=WvzGc9;!hZobkj&4$vDc|#m%j}2cEUB?Ovvq_-aHVKP9M@=<!0Vx2w7J#3_Pp5a9>{g6)A-6IW29efmm|tSn>LlH2;e^QhxP@l>#YP6$H3Szl030w<l6HMUi#0<usweGSH}QYU(|p<tmy$G}Vek%~cqmMkXV9(Um@PK~^fDGb!xv~`0k>6!Yp9n*;e0!1us3+!(BbV$>Ls;4YbnkB^K=Fvj{CPqySdQj#rRSvKZ-S&EHoxx&7%k(q@&Djm!j9>wo3T9|e@DMHK7hn>Uq^uQ8D^3H-+7%YAVe!Ag)gtW!ISf?_$n}cTG)7|7XtQDUdDIxdvTS2TKwGmGen7GyF{vqOC)W~!|2quGN|Qn8vQ4RDkK<^+4U=T!h$5TqfjgKbQnoKC#Qiu^hmci~0x8Mx7^hLg<aUwx<i;jkGfc3}gZP!y(6S5*&<nIuZAbUe<v1xKH^YTUaW>VpdcV6cNy#Q=q#cU>sh|0dPEn@bQI&_*b45f(H85?X9P94Wk2d9_?MBwiR~TSbkxwLK6<0JVo{-si5<hec<rrskLT;Xe;_3%lL?{k2t+)L~N?TCLAcQ!OYInQG=wf+W=y@kwpj76)Ux<T3^;I+#6N;>EE)Pnn>)q?y9&HCzGLP)N-hS<69Uj??>AV>6RtB420n-2VY=8mO{Js1=VH?C;I6ds@<C?&>uXLgYI}cl$s@G6~P6C9Ocb}oyyYkjgm7r@7B>S5FGF-7j2xB3vl6phxxN2}}NDd-CI-b0w4x%B0AwK?|0|bF|&E!Dd9_W<lQm1olKThb<HZH;-?DyI?I7zG^X;Lb8x5T7`^S;7?YPnCL0p7xG(+D$%Ou0z06A+rE(?_NG9_3!{FmlxP*{JmqY6Zt$*79fz(&bJ|w@5;rHT`VHntLk5dF^}5Pz);D$_+2D4vhjYtyI~LYlrHboZcimsX(d3E7$y{b)Jm%XI*FCH;8{gONHd%$=$of$ZfT+KrU`)CkqW``?q^w7|N2*Fh*7t%EyDx0ztl&M?IG+M+X8eU~H2!VBJ&Jr=D&wP?iqst4p7D_J4A1<})5rG^Jqzf|1Q&D19>HFQec|a_WpZyN+)2B4cN@`E^}Eg`TdVr}sGE{60pDTH2;oC=Yxxd0>|FBIl0AQ_*fGB$04cj0BrVH_-8999+nVSy+vujmW}PTsG7QR=87+*j3P%wFq~@GhECg{Md?3cd1ipM{t+Rn%au~iLE!A=A0R}*2)@ab1-hptAEpb#<F5<7SZOuS0UEsjW-z(LMZbm0j3aC5j%&I9Gt;xP%+DgD8^8Zp~%9-;R5&=SJlGKeyDN|^0^7ZC&Q}c{=J;?g5^ks4@CSU$b2aD`MXj0m)miVcMi~S(SVhrv);g$Wi4SFFfIE8SEk*Powmj5L_Y%g*P1bulnyPJF7~V~H~+pUM{D9L>3h|>Dg$qD(gKUO`e-}7@1+D;XSYW7=*Z!k7HC_Qc<-FmK#}H?sT+-feWv*|9dSp*brHuiTP8KX^4CDjXGmgRjvkwLD^sJ`Zcvbhh*WHG3o~GC3oMuI)P6)5P>P_g@y}g?u(q)7ql%3UeV@k!OZL&Z7KX2VCW82)XUBW)xw*=hrt%1BtHNujDqVqp3KQ%4Q^H($jrBQdz56V0H$2ptqjak%ukO%eI7knb{e@XPO$$bLvZMe+W<c_4W|fqC^GPoT*A;Wr`F5!kAb3K2nM`$cEeyC&_}A$57DK|TPId`=gy<Zr<o8%|V@DbFWZQPu{P=*DNG{xJo`$gw<mrDlB=k_FRi-Rx@kOhD6V&;SsttCQx}~j3WEFzHbxqZ_R#U&VG+`#j=FS$&G~8{*e=rropnhzlmAt|r+hm1Wl?`fUSYxpI?;N&IlOeISIHWw`LrfugTIh*<TJjtoo2g2+^JnDqALcja%I<n|$!g8?EMY}R^@DY_WUg`HIs$6%_P7>RA*Vf(f|9y&vr=fIkzJM!V@_$@4BX;WiM_bp?<5ZP)jbE$MYd73{R_w55jFzd7x^*"


def mix32(value):
    value &= 0xFFFFFFFF
    value = ((value ^ (value >> 16)) * 0x7FEB352D) & 0xFFFFFFFF
    value = ((value ^ (value >> 15)) * 0x846CA68B) & 0xFFFFFFFF
    return (value ^ (value >> 16)) & 0xFFFFFFFF


def build_field():
    field = []
    value = 1
    for _ in range(255):
        field.append(value)
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    return bytes(field)


FIELD = build_field()
LOG = [0] * 256
for exponent, value in enumerate(FIELD):
    LOG[value] = exponent


def gf_mul(left, right):
    if not left or not right:
        return 0
    return FIELD[(LOG[left] + LOG[right]) % 255]


def gf_pow(value, exponent):
    if exponent == 0:
        return 1
    if value == 0:
        return 0
    return FIELD[(LOG[value] * exponent) % 255]


def invert(matrix):
    size = len(matrix)
    augmented = [
        row[:] + [int(row_index == column) for column in range(size)]
        for row_index, row in enumerate(matrix)
    ]
    for column in range(size):
        pivot = next(row for row in range(column, size) if augmented[row][column])
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = FIELD[(255 - LOG[augmented[column][column]]) % 255]
        augmented[column] = [gf_mul(value, scale) for value in augmented[column]]
        for row in range(size):
            if row != column and augmented[row][column]:
                factor = augmented[row][column]
                augmented[row] = [
                    left ^ gf_mul(factor, right)
                    for left, right in zip(augmented[row], augmented[column])
                ]
    return [row[size:] for row in augmented]


def decode_container(blob):
    header = struct.unpack_from("<9I", blob)
    magic, output_size, mode, blocks, width, data_count, parity_count, seed, repeated = header
    if (magic, width, data_count, parity_count, seed, repeated) != (
        0xE70B1591,
        192,
        224,
        32,
        0xC1028A4D,
        blocks,
    ):
        raise ValueError("unexpected container parameters")
    if blocks > 4:
        raise ValueError("embedded shuffle table covers four blocks")

    order_blob = zlib.decompress(base64.b85decode(ORDER_B85))
    order = struct.unpack("<1024I", order_blob)
    metadata_end = 36 + blocks * 33
    metadata = blob[36:metadata_end]
    payload = blob[metadata_end:]
    expected_payload = blocks * 256 * width
    if len(payload) != expected_payload:
        raise ValueError("truncated shard payload")

    matrix = bytes(
        gf_pow(parity + 1, data)
        for parity in range(parity_count)
        for data in range(data_count)
    )
    result = bytearray()
    for block_index in range(blocks):
        meta = metadata[block_index * 33 : (block_index + 1) * 33]
        physical_erased = set(meta[1 : 1 + meta[0]])
        if len(physical_erased) != meta[0]:
            raise ValueError("invalid erasure list")

        start = block_index * 256 * width
        raw_block = payload[start : start + 256 * width]
        physical = [
            bytearray(raw_block[index * width : (index + 1) * width])
            for index in range(256)
        ]
        if not all(not any(physical[index]) for index in physical_erased):
            raise ValueError("erasure metadata does not match zeroed shards")

        permutation = sorted(
            range(256), key=lambda shard: (order[block_index * 256 + shard], shard)
        )
        shards = [None] * 256
        for physical_index, logical_index in enumerate(permutation):
            shards[logical_index] = physical[physical_index]
        erased = {permutation[index] for index in physical_erased}

        missing_data = sorted(index for index in erased if index < data_count)
        surviving_parity = [
            parity
            for parity in range(parity_count)
            if data_count + parity not in erased
        ]
        if len(missing_data) > len(surviving_parity):
            raise ValueError("not enough parity shards")
        selected_parity = surviving_parity[: len(missing_data)]
        coefficients = [
            [matrix[parity * data_count + data] for data in missing_data]
            for parity in selected_parity
        ]
        inverse = invert(coefficients) if coefficients else []

        residuals = []
        for parity in selected_parity:
            rhs = bytearray(shards[data_count + parity])
            for data in range(data_count):
                if data in erased:
                    continue
                coefficient = matrix[parity * data_count + data]
                if coefficient:
                    rhs = bytearray(
                        left ^ gf_mul(coefficient, right)
                        for left, right in zip(rhs, shards[data])
                    )
            residuals.append(rhs)

        for row, data in enumerate(missing_data):
            recovered = bytearray(width)
            for parity_index, coefficient in enumerate(inverse[row]):
                if coefficient:
                    recovered = bytearray(
                        left ^ gf_mul(coefficient, right)
                        for left, right in zip(recovered, residuals[parity_index])
                    )
            shards[data] = recovered
        result.extend(b"".join(shards[:data_count]))

    return bytes(result[:output_size])


def xor_stream(length):
    seed = mix32(0x5E17E11D ^ 0x50524144)
    state = mix32(seed ^ 0x9E3779B9)
    result = bytearray()
    while len(result) < length:
        state = mix32(len(result) + state + 0x6D2B79F5)
        result.extend(struct.pack("<I", state))
    return bytes(result[:length])


def unpack_records(stream):
    if stream[:4] != struct.pack("<I", 0x029D5011):
        raise ValueError("invalid materialization archive")
    offset = 4
    chunks = {}
    while offset < len(stream):
        if stream[offset : offset + 4] != struct.pack("<I", 0xF12C04A7):
            raise ValueError("invalid record marker")
        path_size, record_size = struct.unpack_from("<II", stream, offset + 4)
        record_start = offset + 12 + path_size
        record = stream[record_start : record_start + record_size]
        if len(record) < 13 or record[-5] > 128 or len(record) != record[-5] + 13:
            raise ValueError("invalid materialization record")
        index = (struct.unpack_from("<I", record, 4)[0] & 0xFFFF) ^ 0x06D0
        if index in chunks:
            raise ValueError("duplicate chunk index")
        chunks[index] = record[8 : 8 + record[-5]]
        offset = record_start + record_size

    if set(chunks) != set(range(len(chunks))):
        raise ValueError("non-contiguous chunks")
    encrypted = b"".join(chunks[index] for index in range(len(chunks)))
    return bytes(left ^ right for left, right in zip(encrypted, xor_stream(len(encrypted))))


def calculate_flag(filesystem):
    if len(filesystem) < 12:
        raise ValueError("truncated filesystem archive")
    count = struct.unpack_from("<I", filesystem, 8)[0]
    offset = 12
    rows = []
    for _ in range(count):
        kind = filesystem[offset]
        name_size = struct.unpack_from("<I", filesystem, offset + 1)[0]
        name_start = offset + 5
        name_end = name_start + name_size
        name_bytes = filesystem[name_start:name_end]
        name = name_bytes.decode("utf-8")
        offset = name_end
        body = b""
        if kind == 2:
            body_size = struct.unpack_from("<Q", filesystem, offset)[0]
            offset += 8
            body = filesystem[offset : offset + body_size]
            if len(body) != body_size:
                raise ValueError("truncated file body")
            offset += body_size
        elif kind != 1:
            raise ValueError("invalid filesystem entry type")
        if name != "flag.py":
            rows.append((b"D" if kind == 1 else b"F", name_bytes, body))

    digest = hashlib.sha3_512()
    for kind, name, body in sorted(rows, key=lambda row: row[1]):
        digest.update(kind)
        digest.update(struct.pack("<I", len(name)))
        digest.update(name)
        if kind == b"F":
            digest.update(struct.pack("<Q", len(body)))
            digest.update(body)
    return f"pwnsec{{{digest.hexdigest()}}}".encode("ascii")


def main():
    stream = decode_container(CONTAINER.read_bytes())
    filesystem = unpack_records(stream)
    RECOVERED.parent.mkdir(parents=True, exist_ok=True)
    RECOVERED.write_bytes(filesystem)
    sys.stdout.buffer.write(calculate_flag(filesystem))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"solve failed: {error}\n")
        raise SystemExit(1)
