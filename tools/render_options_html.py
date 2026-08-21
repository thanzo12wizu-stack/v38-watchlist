#!/usr/bin/env python3
"""options_positioning.json → 静的HTML（JS不要・inline SVG・スマホ縦1カラム）。

思想22/23に従い、主要な数値はHTML生成時に直接書く。JSが動かなくても
Call/Put GEX集中帯 / Gamma Flip推定 / Net GEX / 現値 が消えない。
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

REG = {"POSITIVE_GAMMA": ("安定側の推定", "pos"),
       "NEGATIVE_GAMMA": ("増幅側の推定", "neg"),
       "NEAR_FLIP": ("Flip近辺", "warn"), "UNKNOWN": ("判定不能", "mut")}


def _d(b, spot):
    if not b or b.get("px") is None:
        return "—", ""
    t = f"{b['pct']*100:+.1f}%"
    if b.get("atr") is not None:
        t += f" ・ {abs(b['atr']):.1f} ATR"
    return f"${b['px']:,.2f}", t


def _scenario(r):
    spot = r.get("spot")
    if spot is None:
        return "現在値を取得できず、価格順シナリオを作れない。"
    levels = []
    cw = (r.get("call_wall") or {}).get("px")
    pw = (r.get("put_wall") or {}).get("px")
    gf = (r.get("gamma_flip") or {}).get("px")
    if cw is not None and cw > spot:
        levels.append((cw, "上", "Call GEX集中・抵抗候補"))
    if pw is not None and pw < spot:
        levels.append((pw, "下", "Put GEX集中・支持候補。終値割れで候補から外す"))
    if gf is not None:
        if gf > spot:
            levels.append((gf, "上", "Gamma Flip推定。上抜けで安定側推定"))
        else:
            levels.append((gf, "下", "Gamma Flip推定。下抜けで増幅側に注意"))
    above = sorted((x for x in levels if x[1] == "上"), key=lambda x: x[0])
    below = sorted((x for x in levels if x[1] == "下"), key=lambda x: x[0], reverse=True)
    parts = [f"現在 ${spot:,.2f}"]
    parts += [f"上 ${px:,.2f} {label}" for px, _side, label in above]
    parts += [f"下 ${px:,.2f} {label}" for px, _side, label in below]
    return " ／ ".join(parts) + "。水準単独では入らず価格反応を確認。"


def card(r):
    reg_t, reg_c = REG.get(r.get("regime"), ("—", "mut"))
    ex = r.get("explain") or {}
    conf = r.get("confluence") or {}
    rows = ""
    for key, lab, cls in (("call_wall", "Call GEX", "neg"),
                          ("gamma_flip", "Gamma Flip", "warn"),
                          ("put_wall", "Put GEX", "pos")):
        px, dist = _d(r.get(key), r.get("spot"))
        cc = conf.get(key) or []
        ctxt = ("　重なり: " + " / ".join(f"{c['name']} ${c['px']:,.2f}" for c in cc)) if cc else ""
        rows += (f'<div class="row"><span class="lab {cls}">{lab}</span>'
                 f'<span class="px">{px}</span>'
                 f'<span class="dist">{dist}<span class="conf">{H.escape(ctxt)}</span></span></div>')
    # バーは常に出す。銘柄ごとに有無が変わると見比べられない。
    pos = r.get("range_pos")
    if pos is None:
        bar = ('<div class="bar off"><span style="left:4px">Put GEX</span>'
               '<span style="right:4px">Call GEX</span></div>'
               '<div class="foot">両側の集中帯が揃わず、レンジ位置を表示できない。</div>')
    else:
        bar = (f'<div class="bar"><i style="left:{pos:.1f}%"></i>'
               f'<span style="left:4px">Put GEX</span>'
               f'<span style="right:4px">Call GEX</span></div>'
               f'<div class="foot">Put/Call GEX集中帯の間で今 <b>{pos:.0f}%</b> の位置。'
               f'0%＝Put側、100%＝Call側。</div>')
    why = ""
    for k, t in (("regime", ""), ("put_wall", "Put GEX集中帯"), ("call_wall", "Call GEX集中帯"),
                 ("gamma_flip", "Gamma Flip推定"), ("net_gex", "Net GEX Proxy")):
        v = ex.get(k) or "算出できず。"
        why += f'<div class="why">{("<b>"+t+"</b>　") if t else ""}{H.escape(v)}</div>'
    if r.get("stale"):
        stale = '<div class="stale">⚠ 3日超の古いデータ。売買根拠には使用しない</div>'
    elif r.get("refresh_failed"):
        stale = '<div class="stale">⚠ 最新取得は失敗。3日以内の前回値を表示</div>'
    else:
        stale = ""
    conf = {"HIGH": "高", "MEDIUM": "中", "OK": "中", "LOW": "低"}.get(
        str(r.get("confidence") or "").upper(), "—"
    )
    quality = (f'<div class="foot">データ信頼度 {conf}（予測的中率ではない） ／ '
               'OI更新時刻は提供元非開示</div>')
    lowc = ('<div class="stale">⚠ データ量不足。オプション水準を売買根拠にしない</div>'
            if str(r.get("confidence") or "").upper() == "LOW" else "")
    return (f'<div class="card"><div class="hd"><span class="tk">{H.escape(r["ticker"])}</span>'
            f'<span class="reg {reg_c}">{reg_t}</span>'
            f'<span class="mut" style="font-size:10.5px">選択満期 {H.escape(str(r.get("selected_expiry") or r.get("nearest")))}'
            f'（{"スイング" if r.get("selection_basis") == "swing" else "短期参考"}）</span>'
            f'<span class="spot">${r["spot"]:,.2f}</span></div>'
            f'{stale}{lowc}<div class="lead">{H.escape(_scenario(r))}</div>'
            f'<div class="lad">{rows}</div>{bar}{quality}{why}</div>')


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    body = "".join(card(r) for r in d["tickers"].values())
    doc = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Options Positioning</title><style>{CSS}</style></head><body>"
           f"<div class='wrap'><h1>オプション需給の推定帯</h1>"
           f"<div class='note'>OI×Black-Scholes GammaからCall/Putの集中帯を推定したもの。"
           f"Callをプラス、Putをマイナスと置く簡易モデルで、実際のディーラーポジションではない。"
           f"支持・抵抗を保証する壁ではなく、<b>価格反応を確認する候補帯</b>として使う。"
           f"取得試行 {H.escape(d.get('asof',''))} / 出所 {H.escape(d.get('source',''))}。"
           f" 更新 {H.escape(str((d.get('quality') or {}).get('refreshed','—')))} / "
           f"{H.escape(str((d.get('quality') or {}).get('requested','—')))}銘柄。</div>"
           f"{body}</div></body></html>")
    open(OUT, "w", encoding="utf-8").write(doc)
    sys.stderr.write(f"[opt-html] wrote {OUT} ({len(doc)} bytes)\n")


if __name__ == "__main__":
    main()
