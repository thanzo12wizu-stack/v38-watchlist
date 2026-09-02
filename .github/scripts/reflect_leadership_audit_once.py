from pathlib import Path


PATH = Path("build_dashboard.py")
text = PATH.read_text(encoding="utf-8")
original = text


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 occurrence, found {count}")
    text = text.replace(old, new, 1)


# Leader Temperature: preserve calculation/zones, remove obsolete bottom-timing claim.
replace_once(
    "     ※先導株温度計は非対称: 左端(枯渇)のみNQ底に中央値18日先行(的中6割)/右端(過熱)は先取りせず。露出は動かさない。",
    "     ※先導株温度計は現状描写: 低位=Leadership Exhaustion、高位=現状の強さ。底/天井タイミング予測や露出変更には使わない。",
    "top doc leader temperature",
)
replace_once(
    "       予測でなく現状描写。非対称=左端(枯渇)のみNQ底に中央値18日先行(的中6割)/右端(過熱)は先取りせず。\"\"\"",
    "       予測でなく現状描写。低位=Leadership Exhaustion、高位=現状の強さ。底/天井タイミング予測には使わない。\"\"\"",
    "leader temperature docstring",
)
replace_once(
    '    zone = ("枯渇（反発予兆）" if cur < 10 else "過熱（現状の強さ）" if cur >= 82 else\n            "強（過熱手前）" if cur >= 65 else "並" if cur >= 30 else "やや枯渇")',
    '    zone = ("極端な枯渇（Exhaustion）" if cur < 10 else "強い（現状の強さ）" if cur >= 82 else\n            "強" if cur >= 65 else "並" if cur >= 30 else "枯渇寄り")',
    "leader temperature zone labels",
)
replace_once(
    '        f\'<details class="cxpl"><summary>読み方</summary><div class="cxpl-b">リーダー群（RS189上位10%）の勢いを過去分布の%タイルで表示・{span}</div></details>\'',
    '        f\'<details class="cxpl"><summary>読み方</summary><div class="cxpl-b">リーダー群（RS189上位10%）の勢いを過去分布の%タイルで表示・{span}。低位はExhaustion（主導株の枯渇）を示すが底打ち時期は予測しない。高位は現状の強さで、天井シグナルではない。</div></details>\'',
    "leader temperature explanation",
)

# Momentum Run is a decomposition of the same Fade information family as F2.
replace_once(
    '        health, hcol = "ラン細り（勢いが失われつつある・防御寄り）", "#fb923c"',
    '        health, hcol = "ラン細り（Fade優勢・内部劣化）", "#fb923c"',
    "momentum run health wording",
)
replace_once(
    '            f\'<details class="cxpl"><summary>読み方</summary><div class="cxpl-b">現リーダー（RS189上位{lr["n"]}）の63日RSの軌跡（42日前→現在）。<b class="mr-acc">加速</b>＝拡大／<b class="mr-cru">巡航</b>＝維持／<b class="mr-fad">失速</b>＝細り</div></details>\'',
    '            f\'<details class="cxpl"><summary>読み方</summary><div class="cxpl-b">現リーダー（RS189上位{lr["n"]}）の63日RSの軌跡（42日前→現在）。<b class="mr-acc">加速</b>＝拡大／<b class="mr-cru">巡航</b>＝維持／<b class="mr-fad">失速</b>＝細り。F2 Fadeと同じ情報群の銘柄別内訳で、別の警戒票として足し算しない。</div></details>\'',
    "momentum run explanation",
)
replace_once(
    '            f\'<div class="lbnote">数字＝63日RSパーセンタイル。失速は出口線を意識——執行は確定出口線で（予兆での自動売却はしない）。</div></div>\')',
    '            f\'<div class="lbnote">数字＝63日RSパーセンタイル。失速はF2 Fadeの内訳表示であり、単独の売買・出口トリガーには使わない。</div></div>\')',
    "momentum run footer",
)

# F1/F2/F3 visible role labels: same cards/layout, research-audited interpretation.
replace_once(
    'f\'<div class="reg-cell {c1}"><div class="reg-k">F1 リーダー脱落率 <span class="reg-kind kind-t">タイミング</span></div>\'',
    'f\'<div class="reg-cell {c1}"><div class="reg-k">F1 リーダー脱落率 <span class="reg-kind kind-t">Attrition</span></div>\'',
    "F1 badge",
)
replace_once(
    'f\'<div class="reg-role">最速の警報｜赤転換の中央48日前・19/22的中・誤報1.1/年</div>\'',
    'f\'<div class="reg-role">内部の脱落・入替を測る｜早めに出やすいが単独の売買・赤転換予測には使わない</div>\'',
    "F1 role",
)
replace_once(
    'f\'<div class="reg-cell {c2}"><div class="reg-k">F2 勢い細り率 <span class="reg-kind kind-t">タイミング</span></div>\'',
    'f\'<div class="reg-cell {c2}"><div class="reg-k">F2 勢い細り率 <span class="reg-kind kind-t">Fade</span></div>\'',
    "F2 badge",
)
replace_once(
    'f\'<div class="reg-role">確定が近い｜赤転換の中央32日前・12/22的中・誤報1.0/年</div>\'',
    'f\'<div class="reg-role">リーダーの中期RS劣化を測る｜Momentum Runの失速と同じ情報群</div>\'',
    "F2 role",
)
replace_once(
    'f\'<div class="reg-cell {c3}"><div class="reg-k">F3 キュー崩れ <span class="reg-kind kind-p">深さ</span></div>\'',
    'f\'<div class="reg-cell {c3}"><div class="reg-k">F3 キュー崩れ <span class="reg-kind kind-p">Damage</span></div>\'',
    "F3 badge",
)
replace_once(
    'f\'<div class="reg-role">下落の深さを見積もる｜60%超でDD10%確率が1.84倍（前半2.14x／後半1.63x）</div>\'',
    'f\'<div class="reg-role">リーダー損傷の広さ・深さを測る｜Breadthと重なるため単独予測には使わない</div>\'',
    "F3 role",
)

# Replace only the explanatory note inside build_regime_alerts; card/grid/CSS stays untouched.
fn_pos = text.index("def build_regime_alerts(m, st=None, collapsible=False, hist=None):")
note_start = text.index('            f\'<div class="note">\'', fn_pos)
old_tail = '            f\'<p class="mut">裏取りにはクレジット・VIX期間構造・売り抜け日・センチメントを併せて見る（単体では動かさない）。</p></div></div></div>\')'
note_end = text.index(old_tail, note_start) + len(old_tail)
new_note = '''            f'<div class="note">'
            f'<p><b>3灯は足し算しない。</b>F1=Attrition、F2=Fade、F3=Damage。厳格な追加検証でも静的な複合条件は独立シグナルとして残らなかった。</p>'
            f'<p><b>F1 リーダー脱落率</b>（≥30%）｜<b>Attrition</b><br>'
            f'20日前に上位{2*N_PORT}だった銘柄の脱落・適格外化を測る。内部の入替を早めに捉える文脈指標で、単独の赤転換予測や売買指示には使わない。</p>'
            f'<p><b>F2 勢い細り率</b>（≥40%・母数=上位{2*N_PORT}）｜<b>Fade</b><br>'
            f'上位{2*N_PORT}のうち63日RSが85未満の割合。Momentum Runの失速と同じ情報群なので二重カウントしない。</p>'
            f'<p><b>F3 キュー崩れ</b>（≥60%・母数{qn}）｜<b>Damage</b><br>'
            f'適格母集団（189日RS≥85＆200日線上）のうち「20日マイナス、または52週高値−15%超下」の割合。損傷の広さ・深さを説明するが、Breadth調整後の独立DD予測力は確認できなかった。</p>'
            f'<p><b>Leadership Regeneration v1（前向き観測のみ）</b>：過去40営業日以内にLeader Temperature≤15を経験 → F2が40%以上から40%未満へ改善 → NQSAR Blue/GreenかつStock 50MA Breadth≥50%で成立。売買・配分・Hard Gateには非連動。</p>'
            f'<p class="fver">※2026-09-02追加監査：Hard GateはNQSAR + Stock 50MA Breadthのまま。F1/F2/F3/Temperatureで枠数・保有・売買を変更しない。</p>'
            f'<p class="mut">表示目的は市場内部の状態把握。閾値の足し算や複合スコア化はしない。</p></div></div></div>')'''
text = text[:note_start] + new_note + text[note_end:]

# The old conditional "defense actions" contradicted the audited result. Keep the same conditional card shell,
# but make every item context-only and explicitly preserve the real Hard Gate.
start = text.index("def build_defense_checklist(st):")
end = text.index("\ndef build_transition_leaders", start)
new_defense = '''def build_defense_checklist(st):
    """F1/F2/F3の点灯を市場内部の状態として整理する。売買・配分は変更しない。"""
    if not st:
        return ""
    f1_on = st.get("c1") == "reg-bad"          # Attrition >=30%
    f2_on = st.get("c2") == "reg-bad"          # Fade >=40%
    f3_on = st.get("c3") == "reg-bad"          # Damage >=60%
    if not (f1_on or f2_on or f3_on):
        return ""
    lit = []
    if f1_on: lit.append("F1")
    if f2_on: lit.append("F2")
    if f3_on: lit.append("F3")
    items = ""
    if f1_on:
        items += ('<li><b>F1 Attrition</b>'
                  '<ul><li>リーダーの脱落・入替が増えている。早期の内部劣化として記録するが、単独では売買しない</li></ul></li>')
    if f2_on:
        items += ('<li><b>F2 Fade</b>'
                  '<ul><li>現リーダーの中期RS劣化が広がっている。Momentum Runはこの内訳であり別票として数えない</li></ul></li>')
    if f3_on:
        items += ('<li><b>F3 Damage</b>'
                  '<ul><li>リーダー群の損傷が広い。Breadthと重なるため、独立したDD予測や利確指示には使わない</li></ul></li>')
    return (f'<div class="card def-card"><h2>⚠ Leadership 状態チェック <span class="def-badge">{"・".join(lit)} 点灯</span></h2>'
            f'<div class="sub">点灯は内部状態の説明のみ。<b>Hard GateはNQSAR + Stock 50MA Breadthのまま</b>。</div>'
            f'<ul class="def-list">{items}</ul>'
            f'<div class="note">'
            f'<p>F1=Attrition、F2=Fade、F3=Damage。3灯は別の側面を説明するため<b>足し算しない</b>。</p>'
            f'<p>F1/F2/F3/Leader Temperatureを理由に、枠数削減・新規停止・利確・レバ変更は行わない。</p>'
            f'</div></div>')
'''
text = text[:start] + new_defense + text[end:]

replace_once(
    '_mkt_section("③ 崩れの兆し", "リーダー脱落・勢い・下落余地", en="Warning Signs")',
    '_mkt_section("③ 崩れの兆し", "Attrition・Fade・Damage", en="Warning Signs")',
    "warning section subtitle",
)

# Guard against accidentally retaining the disproven UI claims/actions.
for banned in (
    "赤転換の中央48日前・19/22的中",
    "赤転換の中央32日前・12/22的中",
    "DD10%確率が1.84倍",
    "NQ底に中央値18日先行(的中6割)",
    "新規サイズを絞る（0.75%リスク/件",
    "裁量スイングは+25%到達玉の⅓利確を確実に",
):
    if banned in text:
        raise SystemExit(f"obsolete dashboard wording remains: {banned}")

for required in (
    "Leadership Regeneration v1（前向き観測のみ）",
    "Hard GateはNQSAR + Stock 50MA Breadthのまま",
    "F2 Fadeと同じ情報群の銘柄別内訳",
    "低位はExhaustion（主導株の枯渇）を示すが底打ち時期は予測しない",
):
    if required not in text:
        raise SystemExit(f"required audited wording missing: {required}")

if text == original:
    raise SystemExit("no changes made")

PATH.write_text(text, encoding="utf-8")
print("Leadership audit dashboard wording patch applied")
