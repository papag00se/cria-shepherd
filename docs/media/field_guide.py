"""Original, self-contained editorial illustrations for the README assists.

All scenes are hand-authored SVG metaphors, not screenshots or observed outcomes.
No remote assets, image services, model calls, or production changes.
"""
from __future__ import annotations

from html import escape
import math
from pathlib import Path
import random

MEDIA = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1600, 840
OVERVIEW_NAME = "assists-overview"
OVERVIEW_HEIGHT = 1026
NAVY = "#132940"
CYAN = "#66d8d5"
GOLD = "#f5c566"
WHITE = "#fff7df"


def path(d, fill, stroke="none", width=1, extra=""):
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round" {extra}/>'


def ellipse(x, y, rx, ry, fill, extra=""):
    return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{fill}" {extra}/>'


def line(d, color, width=3, extra=""):
    return path(d, "none", color, width, extra)


def group(body, transform="", extra=""):
    return f'<g transform="{transform}" {extra}>{body}</g>'


def text(x, y, value, size=30, color=WHITE, weight=400, extra=""):
    return f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" {extra}>{escape(value)}</text>'


def tree(x, y, scale=1, color="#244956"):
    return group(line("M0 0V-180", color, 12) + path(
        "M-12-210L-68-114H-39L-94-39H-43L-117 30H117L43-39H94L39-114H68Z", color),
        f"translate({x} {y}) scale({scale})")


def rock(x, y, scale=1, color="#345b64"):
    body = path("M-75 15L-56-38L-5-67L51-39L88 17L24 41L-46 36Z", color)
    body += path("M-56-38L-5-67L4 3L-46 36Z", "#436b71")
    body += line("M-5-67L4 3L51-39M4 3L24 41", "#23454e", 3)
    return group(body, f"translate({x} {y}) scale({scale})")


def landscape():
    body = path("M0 0H1600V840H0Z", "url(#sky)")
    rng = random.Random(27)
    for _ in range(65):
        x, y, radius = rng.randrange(20, 1580), rng.randrange(35, 320), rng.choice([1, 1.5, 2])
        body += ellipse(x, y, radius, radius, "#abd4cf", 'opacity=".4"')
    body += ellipse(1300, 143, 58, 58, "#eddbab", 'opacity=".85"')
    body += path("M0 382L117 309L210 347L431 145L565 314L710 224L836 345L1035 161L1168 336L1396 253L1600 346V840H0Z", "#294951")
    body += path("M333 235L431 145L565 314L471 258L450 227L411 247L392 220Z M954 244L1035 161L1130 281L1056 245L1034 216L1017 242L991 222Z", "#80988b", extra='opacity=".7"')
    body += path("M0 456Q150 365 365 426T727 397T1120 431T1600 392V840H0Z", "#1e555b")
    body += path("M0 531Q189 463 359 509T712 496T1109 523T1600 480V840H0Z", "#173f4b")
    for x, y, s in [(60, 535, .48), (172, 499, .62), (244, 532, .4), (1055, 469, .36),
                    (1180, 504, .6), (1470, 490, .7), (1560, 545, .55)]:
        body += tree(x, y, s, "#245b60")
    body += path("M0 615Q240 574 466 624T970 602T1600 626V840H0Z", "#18323f")
    return body


def llama(x, y, scale=1, pack=False):
    body = ellipse(145, 315, 130, 18, "#071a29", 'opacity=".5"')
    body += path("M100 212L109 300L85 302L70 226M171 209L174 300L151 302L145 220", "#adc9c6", NAVY, 7)
    body += path("M58 204Q19 188 28 168Q32 163 39 168Q35 184 64 185", WHITE, NAVY, 7)
    body += path("M62 215C37 196 51 168 87 167C126 163 152 181 177 165L192 119C195 95 214 78 237 83L259 97C272 94 292 101 289 116L264 132L250 190C247 211 236 227 215 234L237 298L214 307L182 238C154 237 130 230 111 226L88 306L64 305L80 229Z", WHITE, NAVY, 8)
    body += path("M213 89Q185 70 192 40Q194 27 206 42L235 80M233 83Q211 49 221 30Q230 21 238 44L251 90", WHITE, NAVY, 7)
    body += line("M202 45L219 72M230 36L239 70", "#9bbab4", 5)
    body += ellipse(261, 110, 7, 8, NAVY)
    body += line("M277 125L265 125", NAVY, 3)
    body += line("M203 144L214 148M197 159L209 165M193 177L203 183M72 192L84 184", "#d8dfc9", 4)
    body += path("M83 288L64 305L88 306L92 290M213 290L214 307L237 298L232 284", "#698e92")
    if pack:
        body += line("M115 162Q127 194 157 214", "#644d37", 10)
        body += path("M62 117Q107 106 151 119L162 196Q105 223 56 194Z", "#266568", NAVY, 6)
        body += path("M56 139L151 137L159 158Q105 184 57 160Z", "#3f8b85", NAVY, 4)
        body += line("M77 127L81 195M133 130L137 199", "#bf975c", 8)
        body += path("M65 94L112 78L128 142L80 154Z", GOLD, NAVY, 4)
        body += line("M82 103L106 95M86 117L111 109M91 131L115 123", "#906943", 3)
        body += ellipse(111, 98, 13, 9, "#ffe4a0")
        body += path("M58 116L45 87L66 79L87 121", "#b1d1c3", NAVY, 3)
        body += ellipse(107, 170, 12, 12, GOLD)
        body += line("M101 170H113M107 164V176", "#286061", 3)
    return group(body, f"translate({x} {y}) scale({scale})")


def paper(x, y, scale=1, angle=0, gold=False):
    fill = GOLD if gold else "#c1d7ca"
    body = path("M0 0H83L105 23V126H0Z", fill, NAVY, 3)
    body += path("M83 0V23H105", "#eadcb2" if gold else "#ecede0", NAVY, 2)
    body += line("M17 38H76M17 55H87M17 73H66M17 91H79", "#8b7652" if gold else "#608c89", 4)
    return group(body, f"translate({x} {y}) rotate({angle}) scale({scale})")


def pack_scene():
    body = landscape()
    body += ellipse(1000, 399, 290, 245, "url(#tealGlow)")
    # Loose history is depicted as paper, never as fabricated prompts or code.
    for x, y, s, angle in [(845, 162, .7, -19), (984, 123, .64, 16), (1133, 226, .67, 34),
                            (747, 280, .55, -37), (1291, 347, .52, 49)]:
        body += paper(x, y, s, angle)
    body += line("M817 250Q981 187 1090 312T1070 460M744 361Q826 364 866 409", "#598f88", 3, 'stroke-dasharray="3 14"')
    body += llama(435, 223, 1.42, pack=True)
    # Open field pack: the task map has its own brass case; older notes become a tied roll.
    body += ellipse(1110, 602, 250, 28, "#081b2a", 'opacity=".65"')
    body += path("M924 346Q1003 295 1217 327L1301 519Q1216 630 978 607L904 427Z", "#245d63", NAVY, 9)
    body += path("M924 346Q1057 396 1230 351L1272 431Q1100 489 916 422Z", "#448c85", NAVY, 7)
    body += path("M978 459Q1034 442 1130 454L1171 580Q1106 616 1006 589Z", "#347a77", NAVY, 6)
    body += line("M961 403L1013 566M1205 392L1247 550", "#bc955d", 22)
    for x, y in [(1008, 541), (1239, 520)]:
        body += path(f"M{x-18} {y-16}H{x+18}V{y+20}H{x-18}Z", GOLD, "#71553d", 4)
    body += group(path("M0 0L139-24L171 128L24 157Z", "#b58748", NAVY, 6)
                  + path("M16 8L123-10L151 119L37 140Z", GOLD, "#f7df99", 3)
                  + line("M46 117Q29 77 76 74T105 17M54 31L78 51L113 35", "#936d46", 5)
                  + ellipse(76, 74, 8, 8, "#fff4cc"), "translate(1053 272) rotate(-5)")
    body += group(path("M0 0Q65-12 145 0L143 88Q66 99 0 87Z", "#d0dbc6", NAVY, 5)
                  + ellipse(0, 43, 20, 44, "#f2ebcf") + ellipse(145, 44, 19, 44, "#94b5a8")
                  + line("M49-4V91M91-3V94", "#437d78", 8)
                  + path("M61 37L91 28L95 66L64 72Z", "#6eb1a7", NAVY, 2), "translate(1123 269) rotate(22)")
    body += rock(310, 615, .65)
    body += line("M142 646Q330 590 479 641", "#38606a", 8)
    return body


def connector(x, y, scale=1, bent=False, angle=0):
    body = path("M0 0L112-18L181 36L68 59Z", "#f3c367", NAVY, 5)
    body += path("M0 0L68 59V130L0 68Z", "#94774d", NAVY, 5)
    body += path("M68 59L181 36V107L68 130Z", "#d6aa59", NAVY, 5)
    body += path("M22 24L103 10L155 43L74 60Z", "#327e7b", NAVY, 3)
    for i, color in enumerate(["#6adbd0", "#e8ae64", "#e58279"]):
        y0 = 61 + i * 19
        d = f"M181 {y0}L220 {y0+17}L240 {y0-10}" if bent and i == 1 else f"M181 {y0}L247 {y0+27}"
        body += line(d, color, 10)
    body += line("M20 42L-57 84Q-89 103-75 143", "#285460", 18)
    return group(body, f"translate({x} {y}) rotate({angle}) scale({scale})")


def repair_scene():
    body = path("M0 0H1600V840H0Z", "url(#workshop)")
    body += ellipse(780, 340, 540, 350, "url(#amberGlow)")
    body += path("M69 113L361 73L366 441L76 448Z", "#162f43", "#38626a", 8)
    body += line("M217 94V444M71 277L364 251", "#345361", 8)
    body += path("M88 347L164 279L218 322L297 230L351 310V427L90 434Z", "#32606a")
    body += ellipse(288, 155, 34, 34, "#d3ca9a", 'opacity=".6"')
    # Pegboard, hand tools and lamp establish a workshop rather than a UI diagram.
    for x in range(503, 1355, 45):
        for y in range(126, 307, 45):
            body += ellipse(x, y, 3, 3, "#52727a", 'opacity=".38"')
    body += line("M657 150L657 254M740 156L756 260M865 144L859 252", "#738e88", 8)
    body += path("M630 141L644 121L647 146L664 147L670 120L688 138L673 165H645Z", "#98b0a1", NAVY, 4)
    body += path("M721 139L744 131L751 170L733 179Z", "#aa8053", NAVY, 4)
    body += line("M803 138H844M825 137L819 178", "#d5bc81", 12)
    body += line("M1225 418L1192 180L1045 112", "#507b7c", 18)
    body += path("M973 132L1049 96L1115 189L947 230Z", "#4d7c78", NAVY, 6)
    body += ellipse(1030, 217, 71, 14, "#ffe1a0")
    body += path("M980 229L755 587H1289L1071 229Z", "#f5c566", extra='opacity=".07"')
    body += path("M100 507L1268 363L1527 521L356 694Z", "#a0754d", NAVY, 8)
    body += path("M100 507L356 694V748L100 558Z", "#644b40", NAVY, 7)
    body += path("M356 694L1527 521V579L356 748Z", "#755943", NAVY, 7)
    for y in [543, 573, 603]:
        body += line(f"M215 {y}L1309 {y-135}", "#bc9260", 3, 'opacity=".45"')
    body += line("M212 553L221 840M1384 578L1394 840", "#5c493d", 44)
    body += connector(435, 395, 1.05, bent=True, angle=-10)
    body += line("M442 474Q357 513 402 556T653 577", "#2f6168", 19)
    # A physical alignment jig; rejected bend remains visible, no fabricated before/after outcome.
    body += path("M816 444L1064 402L1198 466L949 518Z", "#446773", NAVY, 6)
    body += path("M816 444V486L949 559L1198 507V466L949 518Z", "#294959", NAVY, 6)
    body += connector(846, 371, .92)
    body += path("M1065 438L1127 420L1210 463L1140 482Z", "#234f5e", NAVY, 5)
    body += path("M1140 482V528L1210 507V463Z", "#193948", NAVY, 5)
    for i in range(3):
        body += ellipse(1158 + i * 16, 491 - i * 5, 6, 9, "#6bbbb2")
    # Caliper checks the connector; it is an illustration of constraint, not proof of universal repair.
    body += group(line("M0 0H175M28-18V58M122-18V58", "#d6d6b0", 11)
                  + line("M28 58H48M122 58H102", "#d6d6b0", 10), "translate(800 342) rotate(-12)")
    body += path("M572 577L742 551L794 589L626 618Z", "#e8d8a9", NAVY, 3)
    body += line("M613 583L695 570M627 595L748 577", "#7e988f", 3)
    # Narrow red wax marker marks an out-of-bounds cut, not a broad security barrier.
    body += line("M1182 551L1253 511M1250 548L1181 515", "#e18178", 8)
    body += path("M141 447L209 430L261 458L193 475Z", "#306d70", NAVY, 4)
    body += path("M193 475V507L261 489V458Z", "#204954", NAVY, 4)
    body += llama(56, 234, .65)
    return body


def footprint(x, y, angle=0, color="#be8664", scale=1):
    return group(ellipse(-5, -4, 4, 7, color) + ellipse(6, 6, 4, 7, color),
                 f"translate({x} {y}) rotate({angle}) scale({scale})")


def steering_scene():
    body = landscape()
    # A winding path, not a flowchart arrow. The loop is visible in the tracks beside it.
    body += path("M708 703Q705 600 856 538T1114 475T1043 386Q1008 330 1094 315", "none", "#5b8b85", 52)
    body += line("M708 703Q705 600 856 538T1114 475T1043 386Q1008 330 1094 315", "#86b3a2", 3)
    body += ellipse(489, 559, 150, 66, "none", 'stroke="#426e70" stroke-width="23"')
    for i in range(19):
        angle = i * 2 * math.pi / 19
        body += footprint(489 + 150 * math.cos(angle), 559 + 66 * math.sin(angle),
                          i * 360 / 19 + 90, scale=1.2)
    body += rock(488, 548, .9)
    for x, y, angle in [(667, 591, 20), (694, 625, 25), (761, 585, 50), (811, 563, 56),
                         (878, 533, 62), (950, 512, 65), (1044, 483, 50)]:
        body += footprint(x, y, angle, "#bfccad", 1.3)
    body += llama(460, 306, 1.1)
    # A shepherd with a field map and lantern: the route is grounded in observable landmarks.
    body += ellipse(939, 651, 100, 18, "#081a29", 'opacity=".6"')
    body += path("M925 469L895 625L1001 639L970 469Z", "#ad7951", NAVY, 6)
    body += path("M916 481L869 563L893 575L937 534M973 495L1043 511L1039 535L969 534", "#be8c5e", NAVY, 5)
    body += path("M917 624L912 659H939L947 631M968 630L970 660H998L994 636", "#223f4b", NAVY, 6)
    body += ellipse(949, 451, 26, 31, "#ccae83")
    body += path("M910 445Q918 402 955 413L978 439L987 450L906 455Z", "#456b65", NAVY, 5)
    body += path("M933 463Q946 483 966 464L967 487L945 507L925 487Z", "#e6d4ac")
    body += line("M1049 620V402Q1049 379 1070 379Q1090 379 1090 401", "#bb9760", 9)
    body += ellipse(1054, 538, 110, 100, "url(#amberGlow)")
    body += path("M1046 511H1080L1085 558H1041Z", "#f4c869", NAVY, 4)
    body += line("M1045 510Q1040 490 1062 490Q1085 490 1080 511", "#b8a978", 4)
    body += path("M863 522L916 502L927 549L877 568Z", GOLD, NAVY, 4)
    body += line("M877 536L903 528M883 548L917 536", "#7a6b51", 3)
    body += rock(1172, 613, .75)
    body += tree(1420, 664, 1.1, "#1b424e")
    return body


def bridge_scene():
    body = landscape()
    body += path("M0 449L220 387L499 439L562 521L463 591L478 840H0Z", "#385d65", NAVY, 5)
    body += path("M1600 407L1381 366L1175 417L1115 507L1213 557L1184 840H1600Z", "#385d65", NAVY, 5)
    body += path("M0 551L165 534L318 589L459 571L479 840H0Z", "#254551")
    body += path("M1211 557L1350 515L1468 533L1600 495V840H1184Z", "#284956")
    body += line("M610 619Q810 709 1078 603", "#284e5a", 7)
    body += path("M467 474L1128 423L1193 468L526 551Z", "#8a7357", NAVY, 5)
    for i in range(15):
        x = 484 + i * 43
        y = 473 - i * 3.4
        body += path(f"M{x} {y}L{x+35} {y-3}L{x+75} {y+57}L{x+36} {y+62}Z", "#b59868" if i % 2 else "#967c59", NAVY, 3)
    body += line("M451 442Q806 421 1150 391M524 518Q818 490 1209 456", "#9d9b76", 8)
    for x, y in [(467, 445), (648, 432), (834, 418), (1014, 404), (1141, 391)]:
        body += line(f"M{x} {y-71}V{y+34}", "#6f7b66", 9)
    body += line("M462 379Q802 357 1140 324M525 460Q842 424 1208 391", "#b8b18a", 5)
    body += line("M474 508L579 560L700 531L802 572L921 513L1031 527L1153 445", "#786e57", 4)
    body += llama(228, 305, .8, pack=True)
    # A barrier remains raised across the entrance; there is no fabricated passing stamp.
    body += line("M491 526V389M608 518V387", "#be9362", 12)
    body += line("M491 436L608 425", "#d58b72", 18)
    body += line("M517 433L530 430M559 429L572 427", "#eed2a1", 9)
    # Enlarged inspection lens is a pictorial cutaway of a plank, not a UI magnifier widget.
    body += ellipse(1268, 297, 176, 176, "#071c2a", 'opacity=".3"')
    body += '<g clip-path="url(#lensClip)">'
    body += path("M1079 99H1454V470H1079Z", "#78998d")
    body += path("M1088 205L1453 145V260L1089 326Z", "#c4a06a", NAVY, 6)
    body += path("M1089 326L1453 260V376L1089 440Z", "#a98c64", NAVY, 6)
    body += line("M1146 260L1228 239L1215 266L1304 247L1274 295L1351 282", "#533f38", 9)
    body += ellipse(1151, 220, 14, 14, "#637c74") + ellipse(1377, 194, 14, 14, "#637c74")
    body += line("M1141 220H1161M1367 194H1387", "#394f55", 3)
    body += '</g>'
    body += ellipse(1268, 297, 176, 176, "none", 'stroke="#a8c6b8" stroke-width="17"')
    body += ellipse(1268, 297, 159, 159, "none", 'stroke="#527c7e" stroke-width="4"')
    body += line("M1385 432L1505 573", "#263f50", 38)
    body += line("M1403 450L1505 573", "#557b7c", 22)
    body += path("M1140 219Q1124 292 1148 357", "none", "#e6edcf", 5, 'opacity=".4"')
    body += rock(210, 641, .7)
    body += tree(74, 646, .92, "#163845")
    return body


SCENES = (
    ("assist-context", "01 / CONTEXT", "Context shaping",
     "Keep the task in view as history grows.",
     "A white cria carries a field pack. A brass map case protects the task while loose notes become a tied roll. "
     "An illustrated metaphor for protected task context and validated, labeled compaction, not a session capture.", pack_scene),
    ("assist-tools", "02 / TOOLS", "Tool-call repair and mutation review",
     "Recover tool calls and review source changes.",
     "A lamplit workshop contains a bent connector, an alignment jig, a caliper and a matching socket. "
     "A red cut marker represents a proven boundary violation. This metaphor does not imply universal repair or a security sandbox.", repair_scene),
    ("assist-steering", "03 / STEERING", "Grounded steering",
     "Use workspace evidence to choose the next step.",
     "Footprints circle a boulder beside a winding mountain trail. A cria meets a shepherd holding a field map and lantern. "
     "The illustration represents evidence-grounded guidance, not a planner or a recorded successful task.", steering_scene),
    ("assist-checks", "04 / CHECKS", "Harness probes and completion review",
     "Request checks and review their results.",
     "A cria waits at a bridge entrance with a red barrier. A large inspection lens reveals a cracked plank and its fasteners. "
     "This metaphor represents harness-run checks and completion review, not proof of correctness or a passed task.", bridge_scene),
)


def definitions() -> str:
    return '''<defs>
<linearGradient id="sky" x2="0" y2="1"><stop stop-color="#12283d"/><stop offset="1" stop-color="#427571"/></linearGradient>
<linearGradient id="workshop" x2="1" y2="1"><stop stop-color="#142b40"/><stop offset="1" stop-color="#354749"/></linearGradient>
<linearGradient id="captionFade" x2="0" y2="1"><stop stop-color="#0b1b29" stop-opacity="0"/><stop offset=".5" stop-color="#0b1b29" stop-opacity=".92"/><stop offset="1" stop-color="#0b1b29"/></linearGradient>
<radialGradient id="tealGlow"><stop stop-color="#63cfc2" stop-opacity=".22"/><stop offset="1" stop-color="#63cfc2" stop-opacity="0"/></radialGradient>
<radialGradient id="amberGlow"><stop stop-color="#f2c779" stop-opacity=".28"/><stop offset="1" stop-color="#f2c779" stop-opacity="0"/></radialGradient>
<clipPath id="canvasClip"><rect width="1600" height="840" rx="22"/></clipPath>
<clipPath id="lensClip"><circle cx="1268" cy="297" r="164"/></clipPath>
<filter id="grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".7" numOctaves="3" seed="12"/><feColorMatrix type="saturate" values="0"/></filter>
</defs>'''


def render_overview(output: Path) -> None:
    gap, cell_width, header_height, art_height = 24, 764, 76, 401
    cell_height = header_height + art_height
    body = ''
    for i, (_, _, title, _, _, scene) in enumerate(SCENES):
        x = gap + (i % 2) * (cell_width + gap)
        y = gap + (i // 2) * (cell_height + gap)
        body += (f'<rect x="{x}" y="{y}" width="{cell_width}" height="{cell_height}" '
                 f'rx="18" fill="#122c3d"/>'
                 + text(x + 24, y + 50, title, 32, WHITE, 700))
        body += (f'<svg x="{x}" y="{y + header_height}" width="{cell_width}" height="{art_height}" '
                 f'viewBox="0 0 {WIDTH} {HEIGHT}">'
                 '<g clip-path="url(#canvasClip)">' + scene()
                 + '<rect width="1600" height="840" filter="url(#grain)" opacity=".055"/>'
                 '</g></svg>')
    desc = "Four illustrated assists: " + "; ".join(s[4] for s in SCENES)
    image = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{OVERVIEW_HEIGHT}" '
             f'viewBox="0 0 {WIDTH} {OVERVIEW_HEIGHT}" role="img" aria-labelledby="title desc">'
             '<title id="title">What cria does</title>'
             f'<desc id="desc">{escape(desc)}</desc>{definitions()}'
             f'<rect width="{WIDTH}" height="{OVERVIEW_HEIGHT}" rx="24" fill="#0b1b29"/>'
             f'<g font-family="DejaVu Sans, sans-serif">{body}</g></svg>')
    (output / f"{OVERVIEW_NAME}.svg").write_text(image)


def render(output: Path = MEDIA) -> None:
    output.mkdir(parents=True, exist_ok=True)
    defs = definitions()
    for name, chapter, title, caption, desc, scene in SCENES:
        body = scene()
        body += '<rect width="1600" height="840" filter="url(#grain)" opacity=".055"/>'
        body += '<path d="M0 602H1600V840H0Z" fill="url(#captionFade)"/>'
        body += text(64, 61, chapter, 24, "#a3d7c9", 600, 'letter-spacing="2"')
        body += text(64, 731, title, 49, WHITE, 700)
        body += text(64, 786, caption, 28, "#b9d0c7")
        image = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
                 f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">'
                 f'<title id="title">{escape(title)}</title><desc id="desc">{escape(desc)}</desc>{defs}'
                 f'<g clip-path="url(#canvasClip)" font-family="DejaVu Sans, sans-serif">{body}</g></svg>')
        (output / f"{name}.svg").write_text(image)
    render_overview(output)
    print("Rendered the four-cell assist overview and individual scene sources; no battery artifacts touched.")


if __name__ == "__main__":
    render()
