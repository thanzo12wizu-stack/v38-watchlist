#!/usr/bin/env python3
"""options_positioning.json → 静的HTML（JS不要・inline SVG・スマホ縦1カラム）。

思想22/23に従い、主要な数値はHTML生成時に直接書く。JSが動かなくても
Call Wall / Put Wall / Gamma Flip / Net GEX / 現値 が消えない。
"""
import json, os, sys, html as H

SRC = os.environ.get("V38_OPT_JSON", "options_positioning.json")
OUT = os.environ.get("V38_OPT_HTML", "options-positioning.html")

CSS = """
:root{--bg:#0b0f17;--pan:#121824;--ln:#243044;--tx:#e6edf3;--mut:#8b949e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
 font:14px -apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}
.wrap{max-width:520px;margin:0 auto;padding:14px}
h1{font-size:18px;margin:0 0 4px}
.note{color:var(--mut);font-size:11px;line-height:1.6;margin-bottom:14px}
.card{background:var(--pan);border:1px solid var(--ln);border-radius:14px;
 padding:14px;margin-bottom:14px}
.hd{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.tk{font-size:19px;font-weight:800}
.spot{font-size:15px;font-weight:700;margin-left:auto}
.reg{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:999px;border:1px solid var(--ln)}
.pos{color:#7ee2b8}.neg{color:#ff8080}.warn{color:#f2b263}.mut{color:var(--mut)}
.lead{font-size:12px;line-height:1.7;margin:9px 0 4px}
.lad{margin:10px 0 6px}
.row{display:flex;align-items:center;gap:8px;padding:6px 0;
 border-top:1px solid rgba(255,255,255,.06);font-variant-numeric:tabular-nums}
.row:first-child{border-top:0}
.lab{font-size:11px;font-weight:700;width:74px;flex:none}
.px{font-size:14px;font-weight:700;width:82px;flex:none;text-align:right}
.dist{font-size:11px;color:var(--mut);flex:1}
.conf{font-size:10px;color:#8fb3ff}
.why{font-size:11px;color:var(--mut);line-height:1.7;margin-top:4px;
 padding-left:8px;border-left:2px solid rgba(255,255,255,.10)}
.bar{position:relative;height:26px;margin:10px 0 2px;border-radius:6px;
 background:linear-gradient(90deg,#ff808022,#ffffff10,#7ee2b822);border:1px solid var(--ln)}
.bar i{position:absolute;top:-3px;width:2px;height:32px;background:#fff}
.bar span{position:absolute;top:6px;font-size:9.5px;color:var(--mut)}
.bar.off{opacity:.35}
.stale{font-size:10px;color:#f2b263}
.foot{color:var(--mut);font-size:10.5px;line-height:1.7;margin-top:6px}
"""

REG = {"POSITIVE_GAMMA": ("落ち着きやすい", "pos"),
       "NEGATIVE_GAMMA": ("荒れやすい", "neg"),
       "NEAR_FLIP": ("境目", "warn"), "UNKNOWN": ("判定不能", "mut")}


def _d(b, spot):
    if not b or b.get("px") is None:
        return "—", ""
    t = f"{b['pct']*100:+.1f}%"
    if b.get("atr") is not None:
        t += f" ・ 値動き{abs(b['atr']):.1f}日分"
    return f"${b['px']:,.2f}", t


def card(r):
    reg_t, reg_c = REG.get(r.get("regime"), ("—", "mut"))
    ex = r.get("explain") or {}
    conf = r.get("confluence") or {}
    rows = ""
    for key, lab, cls in (("call_wall", "上値の壁", "neg"),
                          ("gamma_flip", "性質の境目", "warn"),
                          ("put_wall", "下値の支え", "pos")):
        px, dist = _d(r.get(key), r.get("spot"))
        cc = conf.get(key) or []
        ctxt = ("　重なり: " + " / ".join(f"{c['name']} ${c['px']:,.2f}" for c in cc)) if cc else ""
        rows += (f'<div class="row"><span class="lab {cls}">{lab}</span>'
                 f'<span class="px">{px}</span>'
                 f'<span class="dist">{dist}<span class="conf">{H.escape(ctxt)}</span></span></div>')
    # バーは常に出す。銘柄ごとに有無が変わると見比べられない。
    pos = r.get("range_pos")
    if pos is None:
        bar = ('<div class="bar off"><span style="left:4px">支え</span>'
               '<span style="right:4px">壁</span></div>'
               '<div class="foot">支えまたは壁が算出できず、位置を表示できない。</div>')
    else:
        bar = (f'<div class="bar"><i style="left:{pos:.1f}%"></i>'
               f'<span style="left:4px">支え</span>'
               f'<span style="right:4px">壁</span></div>'
               f'<div class="foot">支えと壁の間で今 <b>{pos:.0f}%</b> の位置。'
               f'0%＝下値の支え、100%＝上値の壁。</div>')
    why = ""
    for k, t in (("regime", ""), ("put_wall", "下値の支え"), ("call_wall", "上値の壁"),
                 ("gamma_flip", "性質の境目"), ("net_gex", "全体の力")):
        v = ex.get(k) or "算出できず。"
        why += f'<div class="why">{("<b>"+t+"</b>　") if t else ""}{H.escape(v)}</div>'
    stale = '<div class="stale">⚠ 取得に失敗したため前回値を表示</div>' if r.get("stale") else ""
    lowc = ('<div class="stale">⚠ 建玉が薄く信頼度が低い</div>'
            if r.get("confidence") == "LOW" else "")
    return (f'<div class="card"><div class="hd"><span class="tk">{H.escape(r["ticker"])}</span>'
            f'<span class="reg {reg_c}">{reg_t}</span>'
            f'<span class="mut" style="font-size:10.5px">満期 {H.escape(str(r.get("nearest")))}</span>'
            f'<span class="spot">${r["spot"]:,.2f}</span></div>'
            f'{stale}{lowc}<div class="lad">{rows}</div>{bar}{why}</div>')


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    body = "".join(card(r) for r in d["tickers"].values())
    doc = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Options Positioning</title><style>{CSS}</style></head><body>"
           f"<div class='wrap'><h1>オプションの壁</h1>"
           f"<div class='note'>建玉（未決済のオプション）が積み上がっている価格帯を出したもの。"
           f"そこに実際の売買が集まりやすいため、支持・抵抗になりやすい。"
           f"ディーラーの実ポジションを観測したものではなく建玉からの推定なので、"
           f"当たる指標としてではなく<b>価格帯の目安</b>として使う。"
           f"取得 {H.escape(d.get('asof',''))} / 出所 {H.escape(d.get('source',''))}。</div>"
           f"{body}</div></body></html>")
    open(OUT, "w", encoding="utf-8").write(doc)
    sys.stderr.write(f"[opt-html] wrote {OUT} ({len(doc)} bytes)\n")


if __name__ == "__main__":
    main()
