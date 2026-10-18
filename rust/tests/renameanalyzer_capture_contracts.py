#!/usr/bin/env python3
"""Fault checks for capture and reference admission without importing the runner.

All children below are doubles. No compiler, target binary or provider is run.
Set NZBGET_CAPTURE_SOURCE to a preserved runner to demonstrate the old failures.
"""
import ast
import base64
import contextlib
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import time
import types
import unittest
import zlib
from unittest.mock import patch


SOURCE = Path(os.environ.get("NZBGET_CAPTURE_SOURCE", Path(__file__).with_name("renameanalyzer_differential.py")))
if "NZBGET_EXPECT_OPTIMIZE" in os.environ and sys.flags.optimize != int(os.environ["NZBGET_EXPECT_OPTIMIZE"]):
    raise RuntimeError("effective interpreter optimization differs from the declared test mode")

# Exact Git blob 56ba7bfeebade4e0b322582fe248fa7e1cefdab3 from
# 02c80b7b98608226fa8daabcbe5fdaf3143ffbdf:daemon/queue/DirectRenamer.cpp.
# Keeping the public historical fixture here makes these tests offline.
REFERENCE_FIXTURE = zlib.decompress(base64.b85decode(
    b'c-rkeYjfMSvY+K&0qag&N|EK*_q2De{Ad+F5>FGy*K#J)>B)F#5wbX;NL_-oqqO<&XLs=+z?bZ#r}xY4bYc-$EEfA-0OU@8gY_A^'
    b'o`-_X!iY2YyY$nHB{LR(xxM4rkWDye2lFgjiqX!FYMdsEqah5X(Z|Vhm4<iojCsdBw)bN9zqa9@|7PPjNcoCgrmMR={*>GUmi+EE'
    b'zxyQ@JQYKc<mr^plJt%bW1bz=;@bNWaP9rXPIwHY9R&F27mEl@1Fc}0CU>d7z(vebpjsre?7>g@K3gR@oBA<Jc@T;$4R7-d)|xRt'
    b'4tA21Es`Ldtq2h`=5fGNmd!cKc)AeC3w(HW@t(cnF;D%7UFNq@IAw3bDUStbKFp0RV$K70D-q$4Go)gos9<LaVD_^xiT4=~p+9B!'
    b'zzBF|dwLRualn$4uy}rk#HTD-;=mqIyke1`6=R1@EGSkQurMa<^JEE&ngdQ)=0g}o?3Oc-#w?Epgae@2hx6;#@7`at@x^cK!}#iI'
    b'd~yBTK0s&l1bX>Bm$<^kG714TEG_lpYy~SI6mL(jj$gx=@yqi!=hwf%LfF~)^~LFA!p`1Zu`#<GUtOOczkf5nVwdl)F5gW~hm4dA'
    b'uo8wAM$brCz{`MVei#X}_}@Ul0tk!(Huvv22ztuHdmzteQ&6e(G9)a1l*D(mRDdqH3G|(VJtWzH32h8u3l9$u!@D>if(GwI5{uX&'
    b'v)I|#*!Yhyo<@1VSy!p+ylXWc2oMhUL4k{=FsW->_;I+jnz|<;EH1m^vA^IcVlBGfk&+0v@eJ&GvJx3zxb2sI3jYg<1KMYx_A_>J'
    b'J{iA!b9w_(I(~h6{HsL^IEFn~=q>&o&X3AH_)p50K9H9-bfb#_5ib0!24E5VNUb~uW8B!7M!pbCF7r5vGahH-*pF6UK=nt`+@@@t'
    b'X5lm{_iy~MA^S%go%=A&a*+0Y5(a=x@XYJ&mzu}RB~0o~fpr<R^uZ8jGoB8>a55J0n1&$eSqKhjPADY!bnd5p(5dXTFXp>Hee!zj'
    b'5753WPh+;Ynajp~_I0Ckn<Nne0@G0>F5pr&5?~22z)yH~9#jTUD~{M$rr|yKgi*5;JAh?xG<tjTBk}5U1}K2x>H${+(?OdE?_wXO'
    b';J=IT3r}XA9CtZB{`K_w=Jo0L<n*fdabHWRgZx?CfLHS;0M8ED3&3?e0mlP|RIJ}_Gn6Zqn8m~BnI8$hzwvdyMIohPNGky9u9V6Z'
    b'N}))Ge|4X&5S4+z*HO(FZ*dcY!y7RDSAxXR1uAd^!T>5evor)wuo6vg5+6dyz9pEBgt*9~XhKH*GM^O`i!2z8r168|Nz5)N5CPB7'
    b'2|Wa@e1)R!k1Yf6RkE*^qGHDDIgAc$zK9G$(^MM7B!e744)Gj!(`U&;jCOJH<@P+DC4I~i@JGd_uJV|yL@y0x56V38XZ%ev^&=EG'
    b'qV#NlnQH7gtjktQj+#J__draN9w>D>V#=BXjOdg|UEC0{`=tB?ROlMOyWpb{Hlq>0fw(CF@rf`q_|NA07Fr5M!$a9Th2Q)2P&`cy'
    b'6#PaqrOhDY0(>NPA+xn(u<c)w+mk}Ic~uhaX!LmQg4i9oMD`G%R%-eQ7t=JPh;r#qKk;ldx`s$EF#FKJXKAuP=<9^0^)@;k$(e!t'
    b'1uMp1uIXS4O}|L)xmQrtL9us~hjVCx)o*MNpDL^V235u7hco7>=j|ip+^2AP5{geB(lA5U{O6zS?nZ@E1E4yAQox`H1w8`VItJGz'
    b'a5Q_%h4AmVr~bl9KVk1c2k&SF;^os%$o!PZ4M;kI5}aqEJ76|(7bwYIuTXKb{yt=Ru7w}6m_L-+M3z{B+&)tF0YkK%)PRthB36qY'
    b'j73Nc66+l&kO*=}GErDtkZoCy;BV}44yZ7UL|Hh)hIW($AcCqRP8;)(!)SlXZ*D<Ry_eEA9PGZ>`^S;jeI}kwk)?>EW0M04o&lr0'
    b'9{Be0_3N9-Da4rZ^}DM9tB_+1s)usufXqqk6`CNjjq@x))M>KvvNY$lyeG9qE;cGQIZ#y9fJ4pXb!h~z0Cp`&$aQaNrvcnASfqGu'
    b'`<cSG&{|&Qej4!L1e75HsQ<}%4tciobjX}u@Hsd}Dnr@K0N5E!ET>;yZ~F-HsK8U&g#=jk$hNlFW}9td|2pH`*+Dw63=$dEIZy!o'
    b'FV0PFiPU}jNID9siw>#A`UY&v3Ivi-jRITe!cmshtVL(c6c~UBn<j;p_|WkRbhD1g)GDF&ioNbJl|4|NFkAu7x3^8jJUJ3e%C5`$'
    b'KbQBWamcR7;vX_2FRXX5;QLm8OTuw^LOxa+<hFFaz@?%{8jW81g0zC%uHm>bGYVZOqXQ{rlUbvd3~DmT32k&Bmj2NegE}Q$foU2!'
    b't9=mYUieGPC7z2(mOy0^SU&I;@`_K=|Cq4aFclN#H;9I29SRO4W8y9OZ$Uu3vmUj3bmPB8$6EG(0L=tngb~kQK$|TBsNI40JQzs@'
    b'eGKb6miW>4cIxsPSY~|=w02#npK4M$n~ff87);?FfyLB-!zJ=X8j5z{NG2|MKp3|HPBB2!Kb+pclo*Z>KtB;ZmKSnk-TJZUv2;yM'
    b'%gW;rOzUQur3dxp^ARg$#&7*kydG3WD3!9woDN`b<P-<B#ru(pdQ|(BCQ>lQjn+@vXMSzFO^fH%PTub|3?-SGoTD6;3j*b6?G?c`'
    b'9S7NGr8t7<q?eqjUyz0<B(mKv9tP|i)~l3jyj(^r)K*{bkzh@(y`54r6H%>f1~s&vRgeU^yDo?9X-t)SBz6nM0kwZp8$lc@Rlfv='
    b'=<tBy34?>km&+v0)LL=X$xP+XVi|=PJ+eeI4cegQh-gRGkJ;`|zrK{=$Kt$9BEm12T^t<(4C^z@9?>m2Bq;$2G<G534*_0z?E-XC'
    b'><3j?VDA-?ahLqVzNUOz?Vea}qDF$H4hJ<xiF%ecd+rn3Sw+XK+%zf?5m397VmIq&)-^u93jwYhC-HXC(red2l!((`Al^J=turg`'
    b'D>fd3l<!a{<kXRWR}@vv1eAnl<#8?Zl6S{yKHw1;TS<Lw&g=p|ws#5MgibjPX`P+z>b4$x?&4FeeK{M^T*7snr;yNOlYBY_dDdaB'
    b'fvC>obgrN74Ag}OEwfnwFd4>jR}OZ!nyyUK+faxyOdUzhw75ik1NJLO&qB;;aA8Rf(cPY*+KaR7TG({b)u1C#)RcO1;iP^~wPTe4'
    b'UvZHy&>S3VTyG9#dmw6Pd$wotPn$htb^xL)-cG3)nE3Zx!)VvkZ1Z&v)$D^e7^T`IuXm|}XJPOpN9tlka*uJ#2Fh?KGwaL6=DY!C'
    b'`HrN4B7O7p^{UZKjfJV5lDe(4<|Bsko|-)?&Xx-duNvuSl!>c6Mw_YIP=k0+TVxEdLimO?rci5{n2zVELOQBh9z`odIm9au<1v+L'
    b'RZf<6q!0l2d!4<g_gNT?MyHEqwwgc|-4I?OH$XG-n(es_kELCOi903E_cCFx_m^(al@?RkAgeN_c}uT`Id#B~V356yKr8s*hne)k'
    b'_Eu00?+R7{$oqJS4i1k)J?lWjac~x9<KzAc2iQb?Wg85)GO9~+^uzdfNP3|o$RpfX#_bM83snda9{sEeMF2$F4o0Ie<Efv)kYytD'
    b'!Nn|$gPU;XZIm`p3+vfFy5*2`p%ZNaz!TOUZNmQk(JL3C+E9<SET88H-F0%OpR?45$d{yHw(?{|Dq<{=e%MZlL9f)~!H+Y0mqJ>X'
    b'qa}{GEom5ucUn&;@J4|hDysUd%5=~SAWG?^s$M{Kfiy+gEKL@S`_nnKL1?S>^0rdfo`EQPr1LK8SnN1~`Dhi!7zS+1>?0$WYfs{q'
    b'c$pv*s#p_Ppxv$*R!RD_37R~!Wp5Ow*u>Ww^1GV$qi1&5r0-IoySPDL*Rf}$TJ`+9tXU&ycal)vOns3ZXuL<7+}+;rm6cx9px^r*'
    b'^m`@rdJ|)_Al}Lk_q2;Gf{)v8KkVAI!$ARKHCyHbg4-Peb0L8>e!>bWq<$)_lzES5%kEhNnWAhO+QG##KBY76o|ZMn&gqJnxHn|z'
    b'lB%XrwG7#Ud*ds3&@M0fj#bs^ezV*3^a^ctmrEvXXAO(B+?X@Kc3bj_l3FMH)T?xz*5g@Ruh{GK+Co(*u$|c>$&%(r@7kZoQ_wv@'
    b'RlIWY6vm!XzpN=>O8ss?DLndDt$0nTwB;<zPIka758Jo&=#TG8Pa7*HV^TB?#JTcDv2%d?^g3w3?D|h`F8!@1zzs{QjFiN-oZ;4V'
    b'+RHTJZ<D-zdib;|N>+IKstGBEI$)%m3E+CwodDWMP<N`Z`96u@X;)vIia8G?6{vpDbKx{tnJjLLTNs}oGK>22_!6%<f)N(s-jFmX'
    b'%`!kDkT>-ROY(g@KA8(UNRQYHr5=xU8xy-0()TK!g{04(=oR~b_B;(&El~CxwEbxmTqKqI9C;k9xz$0IRN`Oj4#Q5LF1`M8n}$$`'
    b'%aMY43!eG3>z~BYsz>*@LqDpCbu1^>8luCY_y{$;?7_>c>?GlI1}j%W_h#iV__Yu`x(7IR4Xyr^?t2lOJSoGAl!E4G4|8=<SkI0j'
    b'N}C<cbEU_Hv2Irr;Z^M^WxvwsFqMTWCj)Y6Z`v1lfqCJt7@nm<b1nfaM8nii^_u!S8)!bw25gzYqm6aIYK)LBjBb%mmuy+yKO<ZI'
    b'X76vGO2+)*f^J5&1qDn5T>^^}Tsa;ndYOk&aKRs-n^dwfEHvDmX^a-iQ&0>=Q(`UqpDlD<@w+@)N1G*<=Hn2#Ye_}7oCT92tRJb?'
    b'Zf2o-+2pmK25-U`FK@Z|*jbWJxwe{cW?rbkylkno5#KlfJ4u5`V!-|+b{F2T$O<b<i!h|%{%9EI+^kp@OP2OPkj~TeU7juT%)0mI'
    b'Ozif`=_`m(CzL8Qp5D3oQjaEyf(kWN67@=Pkw4p0KQCS2DsS)?tH7b78r1I5Oskhi6kW@AZ7-GYVETdyI3#`Htl5~9@YG2?z{(69'
    b'^ynCJU+`dBOGsq|zSMx;bm?bvyd9$vD}`=RQBrQX-S*bcrgNkM(p|4a!Jt{q&+p<Sr7-~29dxZj2{9V+G)>Z*X%cY8rzZQ~q^{54'
    b'zJyni?f@WrPpJ#kp(Fu!x_I4dDFcpTkqodSDFL)MUkJXq#qBSsh}7M`PK!=-igaIveN9_Q+o9(1qjq&C$ED$9lpo?Ar>Z;Lt1AFi'
    b'(R_QF8r3$g{|Pmf;+!Sab(;Gm-PPLLG57pID;DBTt{C;fzU3noT+>ojk3uDD_)~PsDWo1LVU>^I<qVf#GoF3pxPnyIjLsHc!*EMF'
    b'dKjsV(Hl+6TFIQE<tS!%tZRJJk^|6!8Ck-4v~&inFBv7rX^QcmqQHH`$;Z1CUk#BrV5?`66APfNEdQ!}9Kf5zQf8Tne1_Z|LTKb?'
    b';k|Tr<zqniYP*z(Tyf1gz6L%{;#rt3?CtsI&+W`iW#MY$&Fz7X#`LjN@cez*<M$WcE!kxI(an=H%GOG}A**aH(CahHN9-W9XP2#X'
    b'TB2(?{92o3wzKwc&NN#V{1;}MEHD{jt*{@T5(drr-kPP<;C}*gJK}yzl4yvl3$*Rl(U2yR!k65&t32m%##7?&I?ek31W^ao7E!b('
    b'iB<KQ6?vi|eobQ7fTX5O`?u$YtqS{Om0h15ZvIW_;lDQ}dkR~gl9m-aRmF~KjmadXlvdl|W3F$MvOA;JHkh5`wY?x!7|Bx;z3PPP'
    b'vb|~=r;jF@Qn~6olqRLC&k2e*d4T5^#OcPQ&W2XEcg^dDB@yUu=kgQlc2y>7PtkrW!%S~o!m!$kQ*|}tM^EG4(s1Rw7MsAI>0+r-'
    b'>l8=7UVvm5XU6)da`Uh<ty)`UK3GB@hUjz?XY&Qe84ZiAsqJ^~N`%%zRh0m_`Z&>Fwu#+tRM~>tC@?`SW%1Ue>XmIFO7BG%*>^c>'
    b'(yyhcv-vEgJN_A-GT`nwIcJg2X5nY|vjMV=G$loMW0uez0$ttm=L`7fjK}mLl0!Z8XB?VN=cy+f2JDC75BR1$zGlA6QuPj(f`$yD'
    b'z=7$6B~sIYv*QVFSL;QQh+6CRh>3W6R^pb|ISW>lpp_hYt-+9V;bD&4@@!ltGyn5X=QSjm0a0q=fa}+4bOj~Y!GRR|zIl`!E}kW^'
    b'JOf!p-VZN;hgRc*_n-6(Lo5u>U+fNH6?<Koa28w=L!r}!?_~+iM(Da-`O1?RP9yH8>ZPUU&m~Qk6`8ROZ|{_jA8YR%ffAeJA}m;7'
    b'2!5VsW?#IbBPoIF(w7_PlP*DspXA_B6yJhoF*@`jgy0tO{#(4V?gxOI!W++w6mHw7;P+g5dcv(2otejh_z-4u`;LU25-4-f=jvtW'
    b'hFcY;s;ZrR&z-&q_nLBa%3B6l8>aN^r3)bDD$1UHD+I<+Ca`I~7Bd=6q=XgAfU8aGvk^M?3(RtLURGLhaqYq=pZ+q)M!oJ?DN=P0'
    b'rsn(u9O4-`vLbn^fdPHDVMu=^n4g0S{vB}O*5E(~h>u{0wilV;yGRHzjsvs&(!_-)mN;V!L5Ncs+oN!n3Dr?q5r|5l@G2dxrs0(&'
    b'oVFMwlan;WvwVr6Hotz{JE1bSW+d^hd>=!GGRg~`LSx7(sW*L(%TMp{f|DX^#s1lSCjQw~3AhqNL1883F0Emss7zcfbMF`1Y<UYA'
    b'C}~+qj?Nr)9lgiiWw5xkhDk;3v3})!dl7h<*cTbiq$w!27D}wJY*3mfnxOicQq9YNXo~carPfyk?2iu(%~zT9M}^8C6#Cje;UhlZ'
    b'wD!FP5AUhoWIb!@1ExNKWPKG$OL4&$)8)$Uf!JD%9T);+*#b$qo&cyB)FEcu*7%-%LA-{vqr+Mh;NQKz`eM`D@vHOWe$VMY)Sq@)'
    b'(i_V+3;!;h>J?dEVbX56_*N6X`&suXD0hPGBYMq7zx=GVPp^fxvlmc2D9IY$5KoGiE*(zn>zhGlU~w<V(W3Xu0AFa)j4uZ0`7QoE'
    b'KSZtAcQ0JO%|U%`Ih*38(m;L%E=qt=f%_GNR$bKZx3(&r^ThzFsP;=HL7PNWB9cv-4`~6{=>6^rhs{d<1s-6NN&'
))


class DigestContracts(unittest.TestCase):
    """Removing a guard must fail even when the extracted code is optimized."""

    def exercise(self, path, limit, optimization, fault=None, include_bytes=False):
        node, = [n for n in ast.parse(SOURCE.read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name == "bounded_digest"]
        namespace = dict(os=os, stat=stat, hashlib=hashlib)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE),
                     "exec", optimize=optimization), namespace)
        opened = []
        real_open, real_read, real_fstat = os.open, os.read, os.fstat
        reads = 0
        stats = 0

        def opening(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def reading(fd, count):
            nonlocal reads
            reads += 1
            # A missing early-EOF check must fail, rather than hang the suite.
            if reads > 4:
                raise RuntimeError("digest read budget exhausted")
            if fault == "truncate" and reads == 1:
                path.write_bytes(b"")
            if fault == "read_error":
                raise OSError(errno.EIO, "injected read error")
            data = real_read(fd, count)
            if fault == "grow" and reads == 1:
                with path.open("ab") as stream:
                    stream.write(b"x")
            return data

        def stating(fd):
            nonlocal stats
            stats += 1
            if fault == "stat_error" and stats == 1:
                raise OSError(errno.EIO, "injected stat error")
            if fault == "mutate" and stats == 2:
                before = real_fstat(fd)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))
            return real_fstat(fd)

        try:
            with patch.object(os, "open", opening), patch.object(os, "read", reading), patch.object(os, "fstat", stating):
                kwargs = {"include_bytes": True} if include_bytes else {}
                return namespace["bounded_digest"](path, limit, **kwargs)
        finally:
            for fd in opened:
                with self.assertRaises(OSError) as closed:
                    real_fstat(fd)
                self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_valid_and_empty_digest_close_the_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "input"
            for optimization in (0, 1, 2):
                for data, digest in ((b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
                                     (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")):
                    with self.subTest(optimization=optimization, data=data):
                        p.write_bytes(data)
                        self.assertEqual(self.exercise(p, len(data), optimization),
                                         {"bytes": len(data), "sha256": digest})

    def test_invalid_or_changed_files_fail_closed_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = root / "input"
            link = root / "link"
            link.symlink_to(p)
            cases = (("oversize", 2, None, ValueError),
                     ("negative_limit", -1, None, ValueError),
                     ("nonregular", 3, None, ValueError),
                     ("symlink", 3, None, OSError),
                     ("truncate", 3, "truncate", ValueError),
                     ("grow", 3, "grow", ValueError),
                     ("mutate", 3, "mutate", ValueError),
                     ("read_error", 3, "read_error", OSError),
                     ("stat_error", 3, "stat_error", OSError))
            for optimization in (0, 1, 2):
                for name, limit, fault, error in cases:
                    with self.subTest(optimization=optimization, fault=name):
                        p.write_bytes(b"abc")
                        target = root if name == "nonregular" else link if name == "symlink" else p
                        with self.assertRaises(error):
                            self.exercise(target, limit, optimization, fault)

    def test_returned_bytes_are_the_hashed_descriptor_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "input"
            for optimization in (0, 1, 2):
                with self.subTest(optimization=optimization):
                    p.write_bytes(b"abc")
                    result = self.exercise(p, 3, optimization, include_bytes=True)
                    self.assertEqual(result, {"bytes": 3,
                        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                        "data": b"abc"})


class ReferenceContracts(unittest.TestCase):
    """Wrong reference bytes must never reach generation or a compiler/caller."""

    def admission(self, path, optimization, fault=None, git_source=None):
        tree = ast.parse(SOURCE.read_text())
        prefix = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "new_src" for t in node.targets):
                break
            if not (path is None and isinstance(node, ast.FunctionDef) and node.name == "checked"):
                prefix.append(node)
        else:
            self.fail("runner source admission boundary not found")
        namespace = {"__file__": str(SOURCE), "__name__": "reference_contract"}
        if path is None:
            def git_export(argv, cwd=None, output_text=False):
                self.assertEqual(argv, ["git", "show", "02c80b7b98608226fa8daabcbe5fdaf3143ffbdf:daemon/queue/DirectRenamer.cpp"])
                self.assertTrue(output_text)
                return git_source.decode("utf-8")
            namespace["checked"] = git_export
        real_read, real_fstat = os.read, os.fstat
        real_open, real_close = os.open, os.close
        reference_fd = None
        reads = 0
        stats = 0

        def opening(*args, **kwargs):
            nonlocal reference_fd
            reference_fd = real_open(*args, **kwargs)
            return reference_fd

        def closing(fd):
            real_close(fd)
            if fault == "replace_on_close" and fd == reference_fd:
                path.replace(path.with_name("original.cpp"))
                path.write_bytes(b"wrong replacement")

        def reading(fd, count):
            nonlocal reads
            reads += 1
            if reads > 4:
                raise RuntimeError("reference read budget exhausted")
            if fault == "truncate" and reads == 1:
                path.write_bytes(b"")
            data = real_read(fd, count)
            if fault == "grow" and reads == 1:
                with path.open("ab") as stream:
                    stream.write(b"x")
            return data

        def stating(fd):
            nonlocal stats
            stats += 1
            if fault == "mutate" and stats == 2:
                before = real_fstat(fd)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))
            return real_fstat(fd)

        def forbidden(*args, **kwargs):
            self.fail("reference admission launched a child process")

        argv = [str(SOURCE), "unused-build"] + (["--reference-source", str(path)] if path is not None else [])
        with patch.object(sys, "argv", argv), \
             patch.object(os, "read", reading), patch.object(os, "fstat", stating), \
             patch.object(os, "open", opening), patch.object(os, "close", closing), \
             patch.object(subprocess, "Popen", forbidden), patch.object(subprocess, "run", forbidden), \
             patch.object(subprocess, "check_output", forbidden):
            exec(compile(ast.Module(body=prefix, type_ignores=[]), str(SOURCE),
                         "exec", optimize=optimization), namespace)
        return namespace

    def test_git_export_requires_the_same_canonical_bytes(self):
        for optimization in (0, 1, 2):
            with self.subTest(optimization=optimization):
                result = self.admission(None, optimization, git_source=REFERENCE_FIXTURE)
                self.assertEqual(result["old_src"], REFERENCE_FIXTURE.decode("utf-8"))
                self.assertEqual(result["reference_binding"]["sha256"],
                                 "b79d880b560f738dffe1e4a1cb36337088768bdd11289ca3928be3ee332e6b10")
                with self.assertRaises(ValueError):
                    self.admission(None, optimization, git_source=b"x" + REFERENCE_FIXTURE[1:])

    def test_reference_path_replacement_does_not_change_consumed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "reference.cpp"
            for optimization in (0, 1, 2):
                with self.subTest(optimization=optimization):
                    p.write_bytes(REFERENCE_FIXTURE)
                    namespace = self.admission(p, optimization, "replace_on_close")
                    self.assertEqual(namespace["old_src"], REFERENCE_FIXTURE.decode("utf-8"))
                    self.assertEqual(p.read_bytes(), b"wrong replacement")

    def test_canonical_fixture_is_consumed_and_truthfully_bound(self):
        self.assertEqual(len(REFERENCE_FIXTURE), 20946)
        self.assertEqual(hashlib.sha256(REFERENCE_FIXTURE).hexdigest(),
                         "b79d880b560f738dffe1e4a1cb36337088768bdd11289ca3928be3ee332e6b10")
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "reference.cpp"
            p.write_bytes(REFERENCE_FIXTURE)
            for optimization in (0, 1, 2):
                with self.subTest(optimization=optimization):
                    namespace = self.admission(p, optimization)
                    self.assertEqual(namespace["old_src"], REFERENCE_FIXTURE.decode("utf-8"))
                    self.assertEqual(namespace["reference_binding"], {
                        "commit": "02c80b7b98608226fa8daabcbe5fdaf3143ffbdf",
                        "blob": "56ba7bfeebade4e0b322582fe248fa7e1cefdab3",
                        "bytes": 20946,
                        "sha256": "b79d880b560f738dffe1e4a1cb36337088768bdd11289ca3928be3ee332e6b10"})

    def test_wrong_reference_rejected_before_generation_and_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = root / "reference.cpp"
            link = root / "link.cpp"
            link.symlink_to(p)
            for optimization in (0, 1, 2):
                for case in ("mismatch", "short", "oversize", "symlink", "directory", "truncate", "grow", "mutate"):
                    with self.subTest(optimization=optimization, case=case):
                        data = (b"x" + REFERENCE_FIXTURE[1:] if case == "mismatch" else
                                REFERENCE_FIXTURE[:-1] if case == "short" else
                                REFERENCE_FIXTURE + b"x" if case == "oversize" else REFERENCE_FIXTURE)
                        p.write_bytes(data)
                        target = link if case == "symlink" else root if case == "directory" else p
                        error = OSError if case == "symlink" else ValueError
                        with self.assertRaises(error):
                            self.admission(target, optimization, case if case in ("truncate", "grow", "mutate") else None)


class Child:
    def __init__(self, stdout, exit_code):
        self.pid = 987654321
        self.stdout = stdout
        self.exit_code = exit_code
        self.returncode = None
        self.reaped = False
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.exit_code = -15

    def kill(self):
        self.terminated = True
        self.exit_code = -9

    def wait(self, timeout=None):
        self.stdout.write(b"retained child bytes\n")
        self.returncode = self.exit_code
        self.reaped = True
        return self.returncode


class CaptureContracts(unittest.TestCase):
    def exercise(self, fault=None, exit_code=0):
        node, = [n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "checked"]
        module = ast.Module(body=[node], type_ignores=[])
        children = []

        def popen(argv, **kwargs):
            child = Child(kwargs["stdout"], exit_code)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory(prefix="nzbget-capture-contract-") as directory:
            evidence = Path(directory)
            namespace = dict(evidence=evidence, process_number=0, Path=Path, json=json, os=os,
                             sys=sys, time=time, subprocess=types.SimpleNamespace(
                                 Popen=popen, TimeoutExpired=subprocess.TimeoutExpired,
                                 CalledProcessError=subprocess.CalledProcessError,
                                 CompletedProcess=subprocess.CompletedProcess))
            exec(compile(module, str(SOURCE), "exec"), namespace)
            original_write = Path.write_text

            def write(path, data, *args, **kwargs):
                if fault == "process_metadata" and path.name.endswith(".process.json"):
                    raise OSError(errno.ENOSPC, "injected process metadata failure")
                if fault == "all_status" and path.name.endswith("status.json"):
                    raise OSError(errno.ENOSPC, "injected terminal record failure")
                return original_write(path, data, *args, **kwargs)

            def sync(fd):
                if fault == "raw_sync":
                    raise OSError(errno.ENOSPC, "injected raw sync failure")

            error = None
            stderr = io.StringIO()
            with patch.object(Path, "write_text", write), patch.object(os, "fsync", sync), contextlib.redirect_stderr(stderr):
                try:
                    namespace["checked"](["diagnostic-child"])
                except BaseException as caught:
                    error = caught
            status_path = evidence / "process-01.status.json"
            status = json.loads(status_path.read_text()) if status_path.exists() else None
            waited_path = evidence / "process-01.wait-status.json"
            waited = json.loads(waited_path.read_text()) if waited_path.exists() else None
            return children, status, waited, error, stderr.getvalue()

    def test_metadata_failure_reaps_and_stops(self):
        children, status, waited, error, _ = self.exercise("process_metadata")
        self.assertIsNotNone(error)
        self.assertEqual(len(children), 1)
        self.assertTrue(children[0].reaped)
        self.assertTrue(children[0].terminated)
        self.assertTrue(status["reaped"])
        self.assertFalse(status["capture_complete"])
        self.assertEqual(status["exit"], -15)

    def test_raw_sync_failure_retains_known_nonzero_exit(self):
        children, status, waited, error, _ = self.exercise("raw_sync", 7)
        self.assertIsNotNone(error)
        self.assertTrue(children[0].reaped)
        self.assertIsNotNone(status)
        self.assertEqual(status["exit"], 7)
        self.assertTrue(status["reaped"])
        self.assertFalse(status["capture_complete"])
        self.assertEqual(waited["exit"], 7)

    def test_unwritable_terminal_reports_incomplete_known_exit(self):
        children, status, waited, error, stderr = self.exercise("all_status", 7)
        self.assertIsNotNone(error)
        self.assertTrue(children[0].reaped)
        self.assertIsNone(status)
        self.assertIn("INCOMPLETE CHILD CAPTURE ", stderr)
        terminal = json.loads(stderr.split("INCOMPLETE CHILD CAPTURE ", 1)[1])
        self.assertEqual(terminal["exit"], 7)
        self.assertTrue(terminal["reaped"])
        self.assertFalse(terminal["capture_complete"])

    def test_success_keeps_exit_and_reaping(self):
        children, status, waited, error, _ = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(len(children), 1)
        self.assertTrue(children[0].reaped)
        self.assertFalse(children[0].terminated)
        self.assertEqual(status["exit"], 0)
        self.assertTrue(status["reaped"])


if __name__ == "__main__":
    unittest.main()
