#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Command Center — dashboard builder (ピックアップ安定版 2026-07-11)
  A. 個別スリーブ(70%): N=12, 189日RS上位 × 50日SMA>200日SMA × 出来高金額$10M/日 × 株価$5以上,
     各1/12均等(テーマ上限なし)。継続=50>200日SMA&189日RS上位24(2N)。週足SARはアブレーションで撤廃・クールダウンなし。
     選定除外: 189日RS≥85&200MA上のリーダーから、63日RS<85(中期の勢い落ち)・小型創薬(サブテーマ=臨床段階・中小型バイオ)を外す(大手バイオ/製薬/GLP-1/手術ロボは対象)。出遅れ(業種内−20%)は買う(タグのみ)。
              ※ユニバース段階でも時価総額<$100億のヘルスケアは除外済み(二重の網)。除外株はRS順に表示だけ残す(強さ確認用・買わない)。
     急落局面(20日安値割れ or 5日−15%)のセリングクライマックス解禁は裁量メモ(未検証・NQ赤ゲートと役割重複のため機械選定には非連動)。
     急落局面フラグは情報バッジのみ（選定・配分・株数には非連動）。見送りは裁量判断。
     出口: 初期ストップ=建値×0.75(ワイド)→ピーク×0.70トレール(黄も0.70=B2)。二層出口(タイト初期+3R)は不採用。
       層2=ワイドトレール ピーク×0.70(黄も0.70・締めなし)。実効ストップ=両者の高い方(初期はハード,伸びたらワイドが引き継ぐ)。
       ※統合ブック検証: 位置不問で12枠を埋めワイドトレールが最強(+7.7%/Sharpe0.48)。エントリー厳選は充填率の壁で全敗。
     期中退出の空き枠は再投下せず現金で持ち隔週(月曜)トゥルーアップで吸収。銘柄入替は定例月曜＋赤明けは青/緑復帰の翌寄りに即再構築。
  B. レバスリーブ(30%): TQQQ:SOXL=50:50, SOXX MA50<100でSOXL→TQQQ, NQ4色ゲート。配分=個別70/レバ30/現金0。
  C. NQ 4色ゲート(即応・確認日数ゼロ): 個別 青100/緑100/黄=新規停止・保有はワイドトレール0.70継続(締めなし)/赤0(撤退), レバ 青100/緑50/黄0/赤0。執行は翌寄り。
  D. 地合いスコア=4本柱（トレンド30・広がり30・ボラ20・信用20）の合成(raw 0-100)。先導株の強さ温度計/センチメント/レバ環境も
     ※先導株温度計は非対称: 左端(枯渇)のみNQ底に中央値18日先行(的中6割)/右端(過熱)は先取りせず。露出は動かさない。
  E. 8 tabs (マーケット/ピックアップ/ポートフォリオ/配分/RS比較/セクターローテ/業種RS/ルール) + 今日の運用ヘッダ + 隔週リバランス点検（月曜）。RS比較は63/126/189日Top10、1日・1週・1か月のIN/OUT、RS189 Top24の継続性を表示。
  F. 非常口ルール: equity.csvの口座NAV DDとQQQ円建て12ヶ月相対を自動判定。DD≤−28%かつ相対≤−12%でレバ半減、DD>−20%かつ相対>−8%で解除。状態はstate.jsonへ永続化。
  ※全数字はグロス・生存バイアス上限。信頼区間は対指数の相対優位。NQは手動(TradingView)が真。

Data: live yfinance (CI) or cached prices.pkl for local preview.
Run:  python3 build_dashboard.py            -> render HTML + selftest
      python3 build_dashboard.py --diag     -> print computed numbers, no HTML
      python3 build_dashboard.py --selftest -> オフライン固定fixture(env)で render + assert（毎回同じ結果）
      python3 build_dashboard.py --integration-test -> 実ファイル/実FRED/実yfinanceに接続して検証
"""
import math
import html as _html
# =============================================================================
#  修正方針メモ（内部用・HTMLには出ない。改修時に同じ指示を繰り返さないための記録）
#  ── なぜこの構造にしたか。以降の改修はこの原則を踏襲すること。
# -----------------------------------------------------------------------------
#  【大原則】
#   ・データは絶対に削除しない。重複を削る＋構成変更で「見やすく」する（バラバラにはしない）。
#   ・成果物は毎回 present_files で提示する（ファイルをコピーしただけでは不可）。
#   ・過剰実装を避ける。新指標の乱造はしない。結論先行・簡潔。自分用ツール前提
#     （他人向けアドバイスではないので過剰な但し書き不要。技術用語は知識層向けに残す）。
#
#  【タブ構成：10タブ・アクション優先順】(docstring E行は旧8タブ表記で古い。こちらが正)
#   Daily → Positions → Core 12 → Setups → Rotation → Movers → RS → Weekly → Publish → Rules
#   理由: 今日の対応→実保有リスク→システム選定→新規候補→資金の流れ→値動き→相対強さ→
#         週次レビュー→SNS共有→ルール、という「行動の順番」。
#   ・重複は Publish(Overview) 以外は禁止。各カードはホームタブ1箇所のみ。
#     Weekly からは MRI/パフォーマンス/RRG/ヒートマップ/銘柄入替/資産曲線を撤去し各ホームへ一本化。
#   ・集約: Industry→Rotation / W30→Setups / Equity→Positions / Overview1+2→Publish(2セクション)。
#   ・Setups タブ内順序: 検索(最上部)→速報(liq/ema)→①重なり→②単独→③圧縮ベース→
#     ④底打ち(構造ピボット)→⑤W30→⑥リーダー母集団。絞り込み強度順＋参照プールを最後に。
#
#  【Core 12 と 裁量スイングの分離（最重要）】
#   ・Core 12 = システム機械選定(RS順12銘柄・隔週・出口=ピーク×0.70 または 建値×0.75・途中利確なし)。
#     track_holdings は最大12でキャップ。タブ名/カード名は "Core 12"。
#   ・裁量スイング = Positions の実保有(2分割・+25%で1/3利確・21EMA割れ撤退)。
#   ・保有記録(localStorage v38_holdings)に strat フィールド(core/swing)を持たせ、出口ルールを戦略別表示。
#   ・実保有は Core 12 に限定されない（両方を含む）。Rules は "Core 12 Rules" と明示。
#
#  【OVと出典タブの整合】OVの銘柄系(RSマルチTF・期間別先導株)は rs_pool でフィルタし
#   RSタブと母集団を一致させる（フィルタなしの全mだと別銘柄が出て食い違う）。チャート系は同一mkt系列。
#
#  【コントラスト/ライト変換(lightpass)】単色hex背景はライト変換される(薄地+濃文字化)。
#   linear-gradient背景は変換されない→バッジは必ず「単色hex背景+淡色文字」にする
#   (gradient+白文字だと濃地に濃文字化して読めない。ステージバッジで発生し修正済)。rgba背景はLIGHT_FIXでCSS上書き。
#
#  【スパークライン統一】全マクロ/金利系 _spark はメインチャートと線を揃える
#   (viewBox幅680・stroke 2・グラデ塗り0.28)。高さのみ34px固定(compact。モバイルで線の太さが一致)。
#   縦幅を大きくしない（ユーザー判断：線の種類だけ揃えれば十分）。
#
#  【底打ち構造ピボット】oratnekの記事のLL→HL(安値切り上げ)構造がベース。
#   フィボナッチ(0.618)は不使用＝構造のみで判定(ユーザー判断)。出来高減(HL付近<LL付近=売り枯れ)を最優先表示。
#   RS期間は rs63 が主軸(rs21は速すぎて誤検出多・rs189は底では低いのが当然なので高filterは不適)、rs189は文脈。
#
#  【確定パラメータ】ALLOC=(70,30,0) / N_PORT=12 / DVOL_FLOOR=$10M/日 / LEADER_RS=85(63日RS≥85&200MA上)。
#  【ビルド/検証】uv run --python 3.11、末尾 "SELFTEST OK" を必ず確認。NQ色は手動(TradingView)が真。
# =============================================================================

import sys, os, json, csv, pickle, warnings, time, datetime as dt
import io as _io
# #11 全warningを無条件で消さず、既知のノイズ(pandas/numpyの将来警告・分割由来)だけ個別抑制する。
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*invalid value encountered.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*Mean of empty slice.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*All-NaN slice.*")
import numpy as np, pandas as pd

# ---- #1 pickle任意コード実行(RCE)対策: 価格cacheは制限付きUnpicklerで読む。 -------------------
#   pickleは __reduce__ 経由で os.system 等を呼べる。unpickle時に許可クラス以外の global 参照を拒否し、
#   攻撃pickleを「実行前に」失敗させる。許可するのは価格データに必要な pandas/numpy/組込型のみ。
_PICKLE_ALLOWED = {
    ("builtins", "dict"), ("builtins", "list"), ("builtins", "tuple"), ("builtins", "set"),
    ("builtins", "frozenset"), ("builtins", "str"), ("builtins", "bytes"), ("builtins", "bytearray"),
    ("builtins", "int"), ("builtins", "float"), ("builtins", "bool"), ("builtins", "complex"),
    ("builtins", "object"), ("builtins", "slice"),
    ("collections", "OrderedDict"), ("collections", "defaultdict"),
    ("datetime", "datetime"), ("datetime", "date"), ("datetime", "time"),
    ("datetime", "timedelta"), ("datetime", "timezone"),
    ("pandas.core.frame", "DataFrame"), ("pandas.core.series", "Series"),
    ("pandas.core.indexes.base", "Index"), ("pandas.core.indexes.base", "_new_Index"),
    ("pandas.core.indexes.range", "RangeIndex"),
    ("pandas.core.indexes.datetimes", "DatetimeIndex"), ("pandas.core.indexes.datetimes", "_new_DatetimeIndex"),
    ("pandas.core.indexes.numeric", "Int64Index"), ("pandas.core.indexes.numeric", "Float64Index"),
    ("pandas.core.indexes.multi", "MultiIndex"),
    ("pandas.core.internals.managers", "BlockManager"), ("pandas.core.internals.managers", "SingleBlockManager"),
    ("pandas.core.internals.blocks", "new_block"), ("pandas.core.internals.blocks", "Block"),
    ("pandas._libs.internals", "_unpickle_block"),
    ("pandas.core.arrays.datetimes", "DatetimeArray"),
    ("pandas.core.dtypes.dtypes", "DatetimeTZDtype"),
    ("pandas._libs.tslibs.timestamps", "_unpickle_timestamp"), ("pandas._libs.tslibs.timestamps", "Timestamp"),
    ("pandas", "Timestamp"), ("pandas", "Timedelta"), ("pandas", "Period"),
    ("numpy", "ndarray"), ("numpy", "dtype"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy.core.multiarray", "scalar"),
    ("numpy", "int64"), ("numpy", "int32"), ("numpy", "float64"), ("numpy", "float32"), ("numpy", "bool_"),
    ("numpy.core.numeric", "_frombuffer"), ("numpy._core.numeric", "_frombuffer"),   # numpy1.x/2.x両パス
    # DatetimeIndexがfreqを持つ実cache用（BusinessDay/Day等の頻度記述子。inertなデータクラス・コード実行なし）
    ("pandas._libs.tslibs.offsets", "BusinessDay"), ("pandas._libs.tslibs.offsets", "Day"),
    ("pandas._libs.tslibs.offsets", "Week"), ("pandas._libs.tslibs.offsets", "Hour"),
    ("pandas._libs.tslibs.offsets", "Minute"), ("pandas._libs.tslibs.offsets", "Second"),
    ("pandas._libs.tslibs.offsets", "MonthBegin"), ("pandas._libs.tslibs.offsets", "MonthEnd"),
    ("pandas._libs.tslibs.offsets", "BMonthBegin"), ("pandas._libs.tslibs.offsets", "BMonthEnd"),
    ("pandas._libs.tslibs.offsets", "YearBegin"), ("pandas._libs.tslibs.offsets", "YearEnd"),
    ("pandas._libs.tslibs.offsets", "QuarterBegin"), ("pandas._libs.tslibs.offsets", "QuarterEnd"),
    ("pandas._libs.tslibs.offsets", "CustomBusinessDay"), ("pandas._libs.tslibs.offsets", "BDay"),
    ("pandas.tseries.offsets", "BusinessDay"), ("pandas.tseries.offsets", "Day"),
}
class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) in _PICKLE_ALLOWED:
            return super().find_class(module, name)
        # numpy dtype系は版差でパスが揺れるので接頭辞許可（クラスのみ・関数実行はしない）
        if (module.startswith("numpy") and
                name in ("dtype", "ndarray", "_reconstruct", "scalar", "_frombuffer")):
            return super().find_class(module, name)
        # pandas頻度記述子(offsets)は inert なデータクラス。版差に強く、freq付きDatetimeIndexの実cacheに必要。
        if module.startswith("pandas") and (module.endswith("offsets")) and name and name[0].isupper():
            return super().find_class(module, name)
        if module.startswith("pandas") and (name.endswith("Index") or name.startswith("_unpickle")
                                             or name.startswith("__pyx_unpickle_") or name in ("new_block",)):
            return super().find_class(module, name)
        raise pickle.UnpicklingError("blocked global for pickle safety: %s.%s" % (module, name))

def _safe_pickle_load(path):
    with open(path, "rb") as _f:
        return _SafeUnpickler(_f).load()

def _pickle_trusted_root():
    """信頼済みcacheルート。V38_CACHE(=検査対象)からは作らない。明示のV38_TRUSTED_CACHE_ROOT優先、
       無ければスクリプト自身のディレクトリ配下 bt/ を既定にする（#1）。"""
    r = os.environ.get("V38_TRUSTED_CACHE_ROOT")
    if r:
        return os.path.realpath(r)
    try:
        return os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bt"))
    except Exception:
        return os.path.realpath("bt")

def _path_within(child, root):
    try:
        return os.path.commonpath([os.path.realpath(child), root]) == root
    except Exception:
        return False

CACHE        = os.environ.get("V38_CACHE",        "/home/claude/bt/prices.pkl")
UNIVERSE_CSV = os.environ.get("V38_UNIVERSE_CSV", "/mnt/project/universe.csv")
SECTOR_JSON  = os.environ.get("V38_SECTOR_JSON",  "/mnt/project/sector_snapshot.json")
OUT_HTML     = os.environ.get("V38_OUT_HTML",     "/mnt/user-data/outputs/V38_Command_Center.html")

N_PORT = 12
CORE_BRAND = "Core 12"          # ブランド名（表示固定）。計算上の保有数=N_PORT とは分離しておく。
CONTINUE_TOP_N = 2 * N_PORT     # 継続境界（189日RS上位）＝2N。ポート数に連動。
# #16 新規参入判定の順位閾値。OUT=3N（ポート数連動）。IN=30は実測(2017-2026)由来の緩衝帯で、
#     ポート数には連動しない独立値（36位線またぎだけだと今日の新規63%が5日以内に出戻る→30に絞ると44%に改善）。
NEW_ENTRY_OUT_RANK = 3 * N_PORT
NEW_ENTRY_IN_RANK = 30          # 実測由来・N非連動（定数名で意図を明示）
RS_CONTINUITY_TOP_N = CONTINUE_TOP_N
# リーダー・ブレッドスの基準はバックテストで確定した独立ルール（N_PORT非連動）。定数名で残骸でなく意図的固定と明示。
LEADER_BREADTH_BASE_N     = 24   # 起点の上位N（20日前に上位24だったRS銘柄）
LEADER_BREADTH_DROP_RANK  = 36   # 脱落判定ランク（現在36位圏外）
# F1(リーダー脱落)/F2(勢い細り)/F3(キュー崩れ)のゲート色閾値(yellow/red)とリーダー幅テキスト閾値。全て実計算で参照。
F1_WARN                 = 0.20   # F1 yellow
LEADER_DROPOUT_CAUTION  = 0.15   # 脱落率 注意
LEADER_DROPOUT_WARN     = 0.30   # 脱落率 警戒 / F1 red
LEADER_FADE_CAUTION     = 0.25   # 勢い細り 注意 / F2 yellow
LEADER_FADE_WARN        = 0.40   # 勢い細り 警戒 / F2 red
LEADER_FADE_SEVERE      = 0.60   # 勢い細り 深刻
QUEUE_BREAK_WARN        = 0.40   # キュー崩れ F3 yellow
QUEUE_BREAK_SEVERE      = 0.60   # キュー崩れ F3 red
LEADER_BREADTH_DROPOUT_WARN = LEADER_DROPOUT_WARN   # 表示用エイリアス（後方互換）
LEADER_BREADTH_FADE_WARN    = LEADER_FADE_WARN

# --selftest（--integration-test なし）時は False にして二次ネットワーク取得(FRED/ETF extras/時価総額/NQ推定)を止める。
# 完全オフラインには別途 価格キャッシュ(V38_CACHE) と FREDキャッシュ(V38_FRED_CACHE) の固定fixtureが必要。
_ALLOW_NETWORK = True
def _net_ok():
    return _ALLOW_NETWORK
# #8 分析用の唯一の基準日と、日数計算に使う実取引セッションindex（価格Closeのindex）。build開始時None、compute後に設定。
_ANALYSIS_ASOF = None       # datetime.date
_SESSION_INDEX = None       # pd.DatetimeIndex（実際の米国取引日。祝日/臨時休場も反映）
def _session_days(entry_date, asof=None):
    """entry_date〜分析基準日の間の実取引セッション数。価格indexから数える（祝日除外・#8）。
       indexが無ければ平日カウントにフォールバック。"""
    global _SESSION_INDEX, _ANALYSIS_ASOF
    try:
        _asof = asof or _ANALYSIS_ASOF
        _ed = pd.Timestamp(entry_date).normalize()
        if _SESSION_INDEX is not None and len(_SESSION_INDEX) and _asof is not None:
            _a = pd.Timestamp(_asof).normalize()
            return int(((_SESSION_INDEX >= _ed) & (_SESSION_INDEX <= _a)).sum())
    except Exception:
        pass
    try:
        import numpy as _np
        _a = pd.Timestamp(asof or _ANALYSIS_ASOF or pd.Timestamp("today")).date()
        return int(_np.busday_count(pd.Timestamp(entry_date).date(), _a)) + 1
    except Exception:
        return 0
# テスト(--selftest/--integration-test)時は False。mcap/earnings/FRED等のキャッシュfixtureをテストが書き換えない。
_PERSIST_CACHES = True
def _persist_ok():
    return _PERSIST_CACHES
# #6: 計算中はキャッシュを即書きせず保留し、selftest成功→HTML出力成功の後(commit段)でまとめて書く。
_PENDING_CACHE_WRITES = {}
def _reset_build_globals():
    """同一プロセスでmain()を複数回呼んでも、前回ビルドの蓄積状態を持ち越さない（#17）。
       各build開始時に呼ぶ。ネット/キャッシュ許可はデフォルト(True)へ戻し、フラグで再設定させる。"""
    global _ALLOW_NETWORK, _PERSIST_CACHES, _LAST_ONIMINE_SERIES
    global _SPARK_SEQ
    global _ANALYSIS_ASOF, _SESSION_INDEX
    _ALLOW_NETWORK = True
    _PERSIST_CACHES = True
    _LAST_ONIMINE_SERIES = None
    _SPARK_SEQ = 0     # #14 スパークラインのgidを毎ビルド0起点に（同一プロセス2回で出力を一致させる）
    _ANALYSIS_ASOF = None
    _SESSION_INDEX = None
    try: _PENDING_CACHE_WRITES.clear()
    except Exception: pass
    try: _OV_INJECT_MISSES.clear()
    except Exception: pass
    try:                       # 前ビルドで読んだ赤旗を持ち越さず、静的な既知フラグへ戻す
        RISK_FLAGS.clear(); RISK_FLAGS.update({k: dict(v) for k, v in _RISK_FLAGS_BASE.items()})
    except Exception: pass
def _defer_cache_write(path, obj, is_json=True):
    """キャッシュ書き込みを保留（selftest後にflush）。同一pathは後勝ち。"""
    if path:
        _PENDING_CACHE_WRITES[path] = (obj, is_json)
def _flush_pending_caches():
    """保留したキャッシュ書き込みをatomicに反映（commit段でproduction_run・critical成功時のみ）。
       ファイルごとの結果dictを返す。失敗したものはpendingに残す（消さない）＝一部だけ保存で終えない（#8）。"""
    result = {}
    _done = []
    for _p, (_o, _isj) in list(_PENDING_CACHE_WRITES.items()):
        _name = os.path.basename(_p)
        try:
            if _isj: atomic_write_json(_p, _o)
            else: atomic_write_text(_p, _o)
            result[_name] = "ok"; _done.append(_p)
        except Exception as _e:
            result[_name] = "failed: " + repr(_e)[:60]
            sys.stderr.write("[cache] flush failed %s: %r\n" % (_p, repr(_e)[:80]))
    for _p in _done:                 # 成功したものだけpendingから外す（失敗は保持）
        _PENDING_CACHE_WRITES.pop(_p, None)
    return result
def _json_for_script(obj_or_str, sort_keys=True):
    """<script>内に埋め込むJSONを安全化。文字列/オブジェクトどちらも可。
       </script>や<!--でのbreak out、U+2028/2029による構文破壊を防ぐ（#19）。
       sort_keys=True: dictのキー順を決定的にし、同一入力で同一出力にする（#13）。"""
    s = obj_or_str if isinstance(obj_or_str, str) else json.dumps(obj_or_str, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys, allow_nan=False)
    return (s.replace("<", "\\u003c").replace(">", "\\u003e")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
def _h(v):
    """HTML本文/属性へ外部文字列(テーマ名/社名/業種名/外部ラベル)を入れる直前のエスケープ。
       データ本体は生のまま保持し、描画時だけ通す（#4 XSS対策）。script用は_json_for_scriptを使う。"""
    return _html.escape(str(v if v is not None else ""), quote=True)
def _finite(v):
    try: return v is not None and np.isfinite(float(v))
    except Exception: return False

from pathlib import Path as _Path
def atomic_write_text(path, text):
    """一時ファイルへ書いてfsync→os.replaceで原子的に差し替え。途中終了で空/半端ファイルを残さない。"""
    p = _Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        d = str(p.parent)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise

def atomic_write_json(path, obj):
    # #2 NaN/Infinityは正式なJSONでないため書かない（allow_nan=False）。混入時は例外で気づける。
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, allow_nan=False))

_VALID_GATES = {"Blue", "Green", "Yellow", "Red"}
_STATE_SCHEMA_MAX = 2   # 対応するstate schema_versionの上限（未来schemaは拒否）

def _is_iso_date(s):
    """完全なISO日付(YYYY-MM-DD)のみTrue。'2026-07-20garbage'等の末尾ゴミを弾く（#1）。"""
    if not isinstance(s, str):
        return False
    try:
        import datetime as _dt
        return _dt.date.fromisoformat(s).isoformat() == s
    except Exception:
        return False

def _all_finite(obj, depth=0):
    """入れ子のfloatにNaN/Infが無いか（allow_nan=Falseで保存する前提の健全性）。
       深すぎる入れ子(>40)は異常とみなしFalse（打ち切りでNaNを見逃さない・#1）。"""
    if depth > 40:
        return False
    if isinstance(obj, float):
        return obj == obj and obj not in (float("inf"), float("-inf"))
    if isinstance(obj, dict):
        return all(_all_finite(v, depth + 1) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(_all_finite(v, depth + 1) for v in obj)
    return True

def _num_finite_pos(v, allow_zero=False):
    """有限かつ正（allow_zeroならゼロ可）の数値のみTrue。'NaN'/'Infinity'等の文字列やbool、inf/nanは全て拒否（#4）。"""
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False                                   # 数値文字列 "NaN"/"1.0" 等は数値でないので拒否
    try:
        f = float(v)
    except Exception:
        return False
    if f != f or f in (float("inf"), float("-inf")):
        return False
    return (f >= 0) if allow_zero else (f > 0)

def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)

# state内部生成値のallowlist（外部が別値を入れて描画/計算を汚さないよう固定・#3）
_VALID_TURNOVER = {"拡大", "縮小", "横ばい"}
_VALID_SOXL_BAND = {"投入帯", "帯外", "待機"}
_VALID_UPDOWN = {"accum", "distrib"}
_STATE_LABEL_MAX = 120                                   # bear_lit/senti_flagsラベルの最大長

def _is_iso_or_none(v):
    return v is None or _is_iso_date(str(v))

def _finite_or_none(v):
    if v is None:
        return True
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    f = float(v)
    return not (f != f or f in (float("inf"), float("-inf")))

def _label_list_ok(v):
    """bear_lit/senti_flags: 文字列配列・各要素は長さ上限内かつHTML特殊文字(<>)を含まない
       （内部生成の固定ラベルなので<を含むことはない。注入ペイロードをschema段階で弾く）。"""
    if not _is_str_list(v):
        return False
    if len(v) > 64:
        return False
    return all(len(x) <= _STATE_LABEL_MAX and not any(c in x for c in '<>') for x in v)

def _validate_emergency(em):
    """emergency構造の検証（#3）。dictまたはnull。active/available=bool、mult/dd/rel12等=有限数orNull、
       start/end/triggered_on=完全ISO日付orNull、reason=文字列。"""
    if em is None:
        return True
    if not isinstance(em, dict):
        return False
    for _b in ("active", "available"):
        if em.get(_b) is not None and not isinstance(em.get(_b), bool):
            return False
    for _n in ("mult", "dd", "rel12"):
        if not _finite_or_none(em.get(_n)):
            return False
    for _d in ("start", "end", "triggered_on"):
        if not _is_iso_or_none(em.get(_d)):
            return False
    if em.get("reason") is not None and not isinstance(em.get("reason"), str):
        return False
    if em.get("event") is not None and not isinstance(em.get("event"), str):
        return False
    return True

def _validate_state_common(obj, allow_nested=True):
    """トップstateとprevdayサマリで共通のフィールド検証（#3）。allow_nested=Falseで再帰(prevday中のprevday)を止める。"""
    if not isinstance(obj, dict):
        return False
    if not obj:
        return True
    if "date" in obj and obj["date"] is not None and not _is_iso_date(obj["date"]):
        return False
    if "gate" in obj and obj["gate"] is not None and obj["gate"] not in _VALID_GATES:
        return False
    if not _finite_or_none(obj.get("mri")):
        return False                                     # mri=有限数orNull（"bad"文字列を弾く）
    if not _is_iso_or_none(obj.get("rebal_anchor")):
        return False                                     # rebal_anchor=完全ISO日付orNull（位相ズレ防止）
    # turnover/soxl_band/updown等の内部生成ラベル: 文字列・短い・HTML特殊文字を含まない。
    #   XSSはrender時エスケープで無害化済みなので、ここは注入(<等)と極端に長い値を弾きつつ、
    #   正規値の追加(横ばい/待機/distrib等)でビルドが止まらないよう厳密allowlistにはしない（#3）。
    for _sf in ("soxl_band", "turnover", "updown", "event"):
        _sv2 = obj.get(_sf)
        if _sv2 is not None:
            if not isinstance(_sv2, str) or len(_sv2) > 30 or any(c in _sv2 for c in '<>"\''):
                return False
    for _lf in ("bear_lit", "senti_flags"):
        if _lf in obj and obj[_lf] is not None and not _label_list_ok(obj[_lf]):
            return False
    if "emergency" in obj and not _validate_emergency(obj.get("emergency")):
        return False
    if allow_nested and "prevday" in obj and obj.get("prevday") is not None:
        if not _validate_state_common(obj.get("prevday"), allow_nested=False):
            return False
    return True

def _validate_state_schema(obj):
    """state.jsonの構造検証。実際の保存構造に厳密一致させる（#2-3/#4）。
       hold は dict 専用（実処理 prev_hold.get(t) が dict 前提。list を通すと TypeError）。
       hold値フィールド: ed/sell_due_date=ISO, ep/peak/istop=有限正数, peak>=ep, sell_due=bool。
       picks=有効ティッカー配列, bear_lit/senti_flags=文字列配列。数値文字列'NaN'/'Infinity'は拒否。"""
    if not isinstance(obj, dict):
        return False
    if not obj:
        return True
    sv = obj.get("schema_version")
    if sv is not None and not (isinstance(sv, int) and 1 <= sv <= _STATE_SCHEMA_MAX):
        return False                                   # 不明な将来schemaは拒否
    if "date" in obj and obj["date"] is not None and not _is_iso_date(obj["date"]):
        return False
    if "gate" in obj and obj["gate"] is not None and obj["gate"] not in _VALID_GATES:
        return False                                   # gate=Purple等を弾く
    # picks: 各要素は有効ティッカー文字列（<script>...等の保存型XSSを弾く・#2-3）
    if "picks" in obj and obj["picks"] is not None:
        if not isinstance(obj["picks"], list):
            return False
        for _p in obj["picks"]:
            if not (isinstance(_p, str) and _valid_ticker(_p)):
                return False
    # bear_lit / senti_flags: 長さ上限つき文字列配列（極端に長い注入ペイロードも弾く・#3）
    for _lf in ("bear_lit", "senti_flags"):
        if _lf in obj and obj[_lf] is not None and not _label_list_ok(obj[_lf]):
            return False
    # prevday/emergency/mri/rebal_anchor/soxl_band/turnover/updown の型・allowlist検証（#3）
    #   これらが不正型だと後段の .get() 等が AttributeError/TypeError でビルドを落とす。
    if not _validate_state_common(obj, allow_nested=True):
        return False
    # hold: dict 専用。値は実フィールドで検証。
    _hold = obj.get("hold")
    if _hold is not None:
        if not isinstance(_hold, dict):               # #4 list は不可（実処理が dict 前提）
            return False
        for _hk, _hh in _hold.items():
            if not isinstance(_hh, dict):             # hold値は必ずdict
                return False
            if not (isinstance(_hk, str) and _hk and _valid_ticker(_hk)):
                return False                          # holdキーは非空の有効ティッカーのみ（""や非文字列を拒否・#3）
            # 日付フィールド（存在すれば完全ISO）
            for _df in ("ed", "sell_due_date", "date"):
                if _hh.get(_df) is not None and not _is_iso_date(str(_hh.get(_df))):
                    return False
            # 価格フィールド（存在すれば有限正数。'NaN'文字列/inf/nan/boolを拒否）
            for _pf in ("ep", "peak", "istop", "stop", "entry"):
                if _hh.get(_pf) is not None and not _num_finite_pos(_hh.get(_pf)):
                    return False
            # peak >= ep（存在する場合）
            if _hh.get("peak") is not None and _hh.get("ep") is not None:
                try:
                    if float(_hh["peak"]) < float(_hh["ep"]):
                        return False
                except Exception:
                    return False
            # sell_due は bool
            if _hh.get("sell_due") is not None and not isinstance(_hh.get("sell_due"), bool):
                return False
    if not _all_finite(obj):                           # NaN/Infを含むstateは不正
        return False
    return True

def _validate_trend_schema(obj):
    """trend_history.jsonの構造検証（#4/#6）。list・全件[ISO日付, 有効色]・日付昇順・全件検査。"""
    if not isinstance(obj, list):
        return False
    _prev = None
    for it in obj:                                     # 全件検査（201件目以降の破損も見逃さない）
        if not (isinstance(it, (list, tuple)) and len(it) == 2):
            return False                               # 余分な列（3要素以上）を拒否（#4）
        _d, _c = it[0], it[1]
        if not _is_iso_date(_d):
            return False
        if _c not in _VALID_GATES:                     # 色はnull不可・有効色のみ（Purple/None等を弾く・#4）
            return False
        if _prev is not None and _d <= _prev:          # 昇順かつ同一日重複を禁止（決定的・#1）
            return False
        _prev = _d
    return True

def _sanitize_trend_history(hist, asof=None):
    """trend_historyを『拒否』でなく『修復』する（本番の実履歴を落とさない）。
       各エントリから先頭2要素[date,color]を取り、ISO日付かつ有効色のものだけ残す。
       未来日(> asof)は除外、同一日は後勝ちで重複排除、昇順ソート。返り値=クリーンなlist。"""
    if not isinstance(hist, list):
        return []
    _today = str(asof) if asof is not None else None
    seen = {}
    for it in hist:
        if not isinstance(it, (list, tuple)) or len(it) < 2:
            continue
        d, c = it[0], it[1]
        if not (isinstance(d, str) and _is_iso_date(d)):
            continue
        if c not in _VALID_GATES:
            continue
        if _today is not None and d > _today:
            continue                                    # 未来日は捨てる
        seen[d] = c                                      # 同一日は後勝ち
    return [[d, seen[d]] for d in sorted(seen)]

def _sanitize_state(obj):
    """state.jsonを『拒否』でなく『修復』する（本番の実stateを落とさない）。
       不正フィールドは捨て/無効化し、有効な部分だけ残したdictを返す。壊れていれば{}。"""
    if not isinstance(obj, dict):
        return {}
    out = {}
    sv = obj.get("schema_version")
    if isinstance(sv, int) and 1 <= sv <= _STATE_SCHEMA_MAX:
        out["schema_version"] = sv
    if isinstance(obj.get("date"), str) and _is_iso_date(obj["date"]):
        out["date"] = obj["date"]
    if obj.get("gate") in _VALID_GATES:
        out["gate"] = obj["gate"]
    if _finite_or_none(obj.get("mri")) and obj.get("mri") is not None:
        out["mri"] = obj["mri"]
    if isinstance(obj.get("senti"), (int, float)) and _finite_or_none(obj.get("senti")):
        out["senti"] = obj["senti"]
    if isinstance(obj.get("rebal_anchor"), str) and _is_iso_date(obj["rebal_anchor"]):
        out["rebal_anchor"] = obj["rebal_anchor"]
    for _sf in ("soxl_band", "turnover", "updown", "event"):
        _v = obj.get(_sf)
        if isinstance(_v, str) and len(_v) <= 30 and not any(ch in _v for ch in '<>"\''):
            out[_sf] = _v
    for _lf in ("bear_lit", "senti_flags"):
        _v = obj.get(_lf)
        if isinstance(_v, list):
            out[_lf] = [x for x in _v if isinstance(x, str) and len(x) <= _STATE_LABEL_MAX
                        and not any(ch in x for ch in '<>')][:64]
    # picks: 有効ティッカーのみ
    _pk = obj.get("picks")
    if isinstance(_pk, list):
        out["picks"] = [p for p in _pk if isinstance(p, str) and _valid_ticker(p)]
    # hold: 有効なticker→dictのみ、フィールドも健全なものだけ
    _hold = obj.get("hold")
    if isinstance(_hold, dict):
        clean_hold = {}
        for k, v in _hold.items():
            if not (isinstance(k, str) and k and _valid_ticker(k) and isinstance(v, dict)):
                continue
            ok = True
            for _df in ("ed", "sell_due_date", "date"):
                if v.get(_df) is not None and not _is_iso_date(str(v.get(_df))):
                    ok = False; break
            if ok:
                for _pf in ("ep", "peak", "istop", "stop", "entry"):
                    if v.get(_pf) is not None and not _num_finite_pos(v.get(_pf)):
                        ok = False; break
            if ok and v.get("peak") is not None and v.get("ep") is not None:
                try:
                    if float(v["peak"]) < float(v["ep"]):
                        ok = False
                except Exception:
                    ok = False
            if ok and v.get("sell_due") is not None and not isinstance(v.get("sell_due"), bool):
                ok = False
            if ok:
                clean_hold[k] = v
        out["hold"] = clean_hold
    # emergency: 健全なら残す、壊れていれば落とす
    if _validate_emergency(obj.get("emergency")) and obj.get("emergency") is not None:
        out["emergency"] = obj["emergency"]
    # prevday: dictなら再帰修復
    if isinstance(obj.get("prevday"), dict):
        _pd = _sanitize_state(obj["prevday"])
        if _pd:
            out["prevday"] = _pd
    # NaN/Infを含む残余は除去（念のため全体をfinite化チェック）
    if not _all_finite(out):
        # finiteでない値を持つキーを個別に落とす
        for k in list(out.keys()):
            if not _all_finite({k: out[k]}):
                del out[k]
    return out

def _load_json_raw(path):
    """JSONを寛容に読む。パース不能や存在しないときはNone（例外を投げない）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _load_json_safe(path, fallback=None, label="json", fail_closed=False, validator=None):
    """JSONを読む。破損/スキーマ不一致時: fail_closed=Trueなら .prev を試し、無ければ例外(本番停止)。Falseならfallback。"""
    def _read_and_check(pth):
        with open(pth, encoding="utf-8") as f:
            obj = json.load(f)
        if validator is not None and not validator(obj):
            raise ValueError("schema validation failed for %s" % pth)
        return obj
    try:
        return _read_and_check(path)
    except FileNotFoundError:
        return fallback
    except Exception as e:
        prev = str(path) + ".prev"
        if os.path.exists(prev):
            try:
                _o = _read_and_check(prev)
                sys.stderr.write("[state] %s corrupt/invalid; restored from .prev (%s)\n" % (label, path))
                return _o
            except Exception:
                pass
        if fail_closed:
            raise SystemExit("[FATAL] %s が破損またはスキーマ不一致です（自動リセットは危険）: %s (%r)\n"
                             "  前世代 %s も読めません。手動で復旧してください。" % (label, path, repr(e)[:80], prev))
        sys.stderr.write("[state] %s corrupt/invalid; using fallback (%s)\n" % (label, path))
        return fallback

def _sanitize_price_body(W, min_coverage=0.20, min_tickers=1):
    """本番の大規模ユニバース(数千銘柄)ではyfinance由来の局所異常(上場前の0/負値/Inf/OHLC不整合)が
       一部銘柄・一部日付に必ず混じる。これらを「そのセルだけNaN化(=欠測扱い)」して隔離し、残りで続行する。
       ・非正/非有限の価格セル → NaN
       ・OHLC不整合(High<Low等)の行 → その行の価格4本をNaN
       ・出来高の負/Inf → NaN（0は正当なので許容）
       ・上記の結果、全欠測 or 充足率が閾値未満になった銘柄 → 列ごと除外
       返り値: (clean_W, report)。壊滅的なとき(有効銘柄0など)はreportに fatal を入れる。"""
    req = ["Open", "High", "Low", "Close", "Volume"]
    if not isinstance(W, dict) or any(not hasattr(W.get(k), "shape") for k in req):
        return W, {}
    O, H, L, C, V = W["Open"], W["High"], W["Low"], W["Close"], W["Volume"]
    def _fin_pos(df):                       # 有限かつ>0のセルだけ残し、他はNaN
        return df.where(np.isfinite(df) & (df > 0))
    O2, H2, L2, C2 = _fin_pos(O), _fin_pos(H), _fin_pos(L), _fin_pos(C)
    V2 = V.where(np.isfinite(V) & (V >= 0))  # Volume=0は取引なしで正当
    n_bad_price = int(((~(np.isfinite(O) & (O > 0)) & O.notna()).sum().sum()
                       + (~(np.isfinite(H) & (H > 0)) & H.notna()).sum().sum()
                       + (~(np.isfinite(L) & (L > 0)) & L.notna()).sum().sum()
                       + (~(np.isfinite(C) & (C > 0)) & C.notna()).sum().sum()))
    # OHLC不整合の行(セル)をNaN化。NaN混じりの比較はFalse扱い(fillna)。
    incoh = ((H2 < L2) | (H2 < O2) | (H2 < C2) | (L2 > O2) | (L2 > C2)).fillna(False)
    n_incoh = int(incoh.to_numpy().sum())
    if n_incoh:
        O2, H2, L2, C2 = O2.mask(incoh), H2.mask(incoh), L2.mask(incoh), C2.mask(incoh)
    # 全欠測 or 充足率不足の銘柄を列ごと除外（Closeで判定）
    cov = C2.notna().mean(axis=0)
    keep = [c for c in C2.columns if float(cov.get(c, 0)) >= min_coverage]
    dropped = [c for c in C2.columns if c not in keep]
    if dropped:
        O2, H2, L2, C2, V2 = (df[keep] for df in (O2, H2, L2, C2, V2))
    clean = {"Open": O2, "High": H2, "Low": L2, "Close": C2, "Volume": V2}
    report = dict(bad_price_cells=n_bad_price, incoherent_cells=n_incoh,
                  dropped_tickers=dropped, kept=len(keep))
    if len(keep) < min_tickers:
        report["fatal"] = "有効銘柄が残りません（データ全体が劣化）"
    elif len(C2.index) and bool(C2.iloc[-1].isna().all()):
        report["fatal"] = "最終営業日に有効なCloseが1銘柄もありません"
    return clean, report

def _validate_price_body(W, min_rows=2):
    """OHLCV価格本体の『構造的・壊滅的』健全性のみを検証し、問題点リストを返す（#5・本番運用向けに緩和）。
       局所的な異常セル(0/負/Inf/OHLC不整合)は _sanitize_price_body が隔離するため、ここでは扱わない。
       ここでFATALにするのは: 列欠落/非DataFrame・空・DatetimeIndexでない・非昇順・index/columns不一致・
       系列間の軸ズレ・全銘柄で最終行が欠測 など、少数銘柄では直せない構造問題だけ。"""
    probs = []
    if not isinstance(W, dict):
        return ["price body is not a dict"]
    req = ["Open", "High", "Low", "Close", "Volume"]
    for k in req:
        v = W.get(k)
        if v is None or not hasattr(v, "shape"):
            probs.append(f"{k}: missing/not a DataFrame"); continue
        if v.shape[0] < min_rows or v.shape[1] < 1:
            probs.append(f"{k}: empty/too few rows ({getattr(v,'shape',None)})")
        try:
            if not isinstance(v.index, pd.DatetimeIndex):
                probs.append(f"{k}: index is not DatetimeIndex")
            elif not v.index.is_monotonic_increasing:
                probs.append(f"{k}: index not ascending")
            if v.index.has_duplicates:
                probs.append(f"{k}: duplicate index")
            if v.columns.has_duplicates:
                probs.append(f"{k}: duplicate columns")
        except Exception as _e:
            probs.append(f"{k}: index/columns check error {repr(_e)[:40]}")
    if probs:
        return probs
    # index/columns 一致（全系列が同じ日付・銘柄軸か）
    base_idx, base_cols = W["Close"].index, set(W["Close"].columns)
    for k in req:
        v = W[k]
        if len(v.index) != len(base_idx) or not (v.index == base_idx).all():
            probs.append(f"{k}: index mismatch vs Close")
        if set(v.columns) != base_cols:
            probs.append(f"{k}: columns mismatch vs Close")
    if probs:
        return probs
    # 壊滅的な欠測のみFATAL: 最終行が全銘柄で欠測(=当日データ無し)・全銘柄で欠測の行。
    #   個別銘柄の薄さ/欠測/異常は sanitize が隔離済みなのでここでは全体崩壊だけ見る。
    try:
        C = W["Close"]
        if len(C.index) and bool(C.iloc[-1].isna().all()):
            probs.append("Close: last row is entirely NaN across all tickers")
        if bool(C.isna().all(axis=1).any()):
            probs.append("Close: a date with no data across all tickers")
        if C.shape[1] < 1:
            probs.append("Close: no tickers remain")
    except Exception as _e:
        probs.append(f"catastrophic-coverage check error {repr(_e)[:40]}")
    return probs

def normalize_timeseries(df, fail_closed=False, label="series"):
    """OHLCV/マクロ系列を正規化: indexをdatetime化しtz除去、NaT行除去、元行番号タイブレークで安定昇順ソート、
       重複indexはkeep=last。tz-aware・降順・重複日付の入力でも後段が同じ結果になるよう保証する（#5）。
       失敗時: fail_closed=True(価格本体等の重要系列)は例外送出、Falseは空DataFrame＋警告を返し、
       正規化に失敗した元データ（降順/tz-aware/重複のまま）を後段に流さない（#14）。"""
    try:
        if df is None or not hasattr(df, "index") or len(df) == 0:
            return df
        idx = pd.to_datetime(df.index, errors="coerce", utc=True)
        try:
            idx = idx.tz_convert(None)
        except (TypeError, AttributeError):
            try: idx = idx.tz_localize(None)
            except Exception: pass
        x = df.copy()
        x.index = idx
        x = x.loc[x.index.notna()]
        if len(x) == 0:
            return x
        order = np.argsort(x.index.values, kind="mergesort")   # 安定ソート（同一時刻は元行順）
        x = x.iloc[order]
        x = x.loc[~x.index.duplicated(keep="last")]            # 同一時刻はファイル上の最後を採用
        return x
    except Exception as _e:
        sys.stderr.write("[normalize] failed (%s): %r\n" % (label, repr(_e)[:120]))
        if fail_closed:
            raise RuntimeError("normalize_timeseries failed for critical series '%s': %r" % (label, _e))
        try:
            return df.iloc[0:0]     # 非重要系列: 空を返し、正規化できていない元データは使わせない
        except Exception:
            return None
# #14 検証成績(19/22・+28.8%・勝率・DD・FSM等)が算出された時点のロジック版と検証データ期間。
#   ロジックを変えたら手動で更新し、表示注記もこの値から生成する（成績と現行ロジックの乖離を明示）。
LOGIC_VERSION = "v38.26"
BACKTEST_THROUGH = "2026-06"
def _compute_logic_hash():
    """このスクリプト自身の内容からロジック識別ハッシュを算出。LOGIC_VERSIONの手動更新漏れを補い、
       ビルドされたロジックの同一性を機械的に示す（表示注記・DIAGで使用）。"""
    try:
        with open(__file__, "rb") as _f:
            import hashlib as _hl
            return _hl.sha256(_f.read()).hexdigest()[:10]
    except Exception:
        return "unknown"
LOGIC_HASH = _compute_logic_hash()
# #12 表示している検証成績と、それが算出されたロジック版・データ期間・サンプル数を機械可読に束ねる。
#   commit時に backtest_manifest.json として出力し、成績とロジックの対応をトレース可能にする。
BACKTEST_MANIFEST = {
    "logic_version": LOGIC_VERSION,
    "backtest_through": BACKTEST_THROUGH,
    "round_trip_cost": 0.002,
    "statistics": {
        "f1_precision": "19/22",          # 赤転換の中央48日前・誤報1.1/年
        "f1_lead_days_median": 48,
        "f1_false_alarms_per_year": 1.1,
        "f3_dd10_odds_ratio": 1.84,       # 60%超でDD10%が1.84倍（前半2.14/後半1.63）
        "f3_dd10_first_half": 2.14,
        "f3_dd10_second_half": 1.63,
        "leader_recovery_pct": 28.8,      # 転換時にリーダー群が+28.8%で回帰
    },
    "note": "UI文言変更でもlogic_hashは変わる。成績を変える改修時はlogic_version/backtest_throughを更新すること。",
}
# テーマ上限は撤廃（リーダーを189日RS上位から純粋に採用・同一テーマに偏り得る）
CHIP_CAP = 8                   # max chips shown per setup/state list (rest folded to +N件)
RS_LB = 189                    # ranking lookback (trading days) ≒9ヶ月モメンタム (研究で確定の最適)
CHART_LB = 504                 # 全トレンドグラフの表示期間を統一（≒2年・エクイティは別）
DVOL_FLOOR = 10e6              # 出来高金額フロア: 20日平均$vol≥$10M (取れる中型+/小型蜃気楼を除外・確定値)

# 会計・ガバナンス等の赤旗（キュレーション式・実データ由来でない/履歴含む）。
#   type: 粉飾実績 / 会計 / 調査 / 上場廃止 / 中国ADR / 希薄化 / 訴訟。
#   sev: crit（確定した粉飾実績＝最上位）/ high / med。
#   V38_RISK_JSON か risk_flags.json で追記・上書き可（{"TICKER":{"type":..,"sev":..,"note":..}}）。
RISK_FLAGS = {
    "SMCI": {"type": "粉飾実績", "sev": "crit",
             "note": "2020年にSECが会計違反（2014-17年の売上前倒し・費用過少計上）で摘発、課徴金$17.5Mで和解（元CEOも個人和解）＝確定した粉飾実績。さらに2024年に監査法人EY辞任・提出遅延・Nasdaq上場廃止警告（後に提出し回避／新監査法人BDO）＝再燃。会計・ガバナンスの常習性に留意。"},
}
_RISK_FLAGS_BASE = {k: dict(v) for k, v in RISK_FLAGS.items()}   # #17 静的な既知フラグ。build毎にこの状態へ戻す（ファイル読込分のみ揮発）。
# #2 ティッカー許可文字。英数字＋. ^ = - のみ（yfの-変換済み・指数^・為替=に対応）。
#   引用符/< >/空白/制御文字/バックスラッシュ等（HTML属性・inline JS注入に使える文字）を一切通さない。
import re as _re_tk
TICKER_RE = _re_tk.compile(r'^[A-Z0-9.^=-]{1,20}$')
def _valid_ticker(t):
    return bool(TICKER_RE.match(str(t or "").upper().strip()))

# 中国ADR（VIE構造・米中規制・HFCAA上場廃止リスク）＝自動フラグ用の既知リスト。追加可。
CHINA_ADR = {
    "BABA", "JD", "PDD", "BIDU", "NIO", "LI", "XPEV", "TCEHY", "NTES", "BILI",
    "TME", "IQ", "VIPS", "BEKE", "TAL", "EDU", "ZTO", "FUTU", "TIGR", "GDS",
    "YMM", "DADA", "TCOM", "HTHT", "ATHM", "WB", "DOYU", "HUYA", "ZH", "QFIN",
    "LU", "DIDIY", "NIU", "API", "GOTU", "MOMO", "JOBS", "EH", "CAAS", "RLX",
}

def load_risk_flags(strict=False):
    """risk_flags.json があれば読み込み RISK_FLAGS にマージ（ユーザーが追記・上書き可能）。
       strict=True（offline selftest）: 環境変数V38_RISK_JSONで明示された時のみ読む。"""
    import json as _j
    if strict:
        _ep = os.environ.get("V38_RISK_JSON")
        paths = [_ep] if _ep else []
    else:
        paths = [os.environ.get("V38_RISK_JSON"), "/mnt/project/risk_flags.json",
                 os.path.join(os.path.dirname(CACHE or "."), "risk_flags.json"), "risk_flags.json"]
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        try:
            data = _j.load(open(p, encoding="utf-8"))
            for k, v in (data or {}).items():
                if isinstance(v, dict) and not str(k).startswith("_"):
                    RISK_FLAGS[str(k).upper().strip()] = v
        except Exception as e:
            sys.stderr.write("[risk_flags] load failed: %r\n" % repr(e)[:100])
        break
    return RISK_FLAGS

def risk_flags_for(t, close=None):
    """銘柄の赤旗リスト。キュレーション（会計/調査/希薄化等）＋自動（中国ADR/低位）を合成。"""
    t = str(t).upper().strip()
    out = []
    cur = RISK_FLAGS.get(t)
    if cur:
        out.append(cur)
    if t in CHINA_ADR and not any(f.get("type") == "中国ADR" for f in out):
        out.append({"type": "中国ADR", "sev": "med",
                    "note": "中国ADR＝VIE構造・米中規制・HFCAA上場廃止リスク。当局方針で急変しうる（自動判定）。"})
    try:
        if close is not None and close == close and float(close) < 3.0 and not any(f.get("type") == "低位" for f in out):
            out.append({"type": "低位", "sev": "med",
                        "note": f"株価が低位（${float(close):.2f}）。$1割れが続くと上場廃止基準に抵触するゾーン（自動判定）。"})
    except Exception:
        pass
    return out

def risk_flag_of(t):
    """後方互換: 主フラグ1つ（バッジ・旧呼び出し用）。"""
    fl = risk_flags_for(t)
    return fl[0] if fl else None

def _risk_flag_badge(t, close=None):
    """赤旗バッジ（会計/調査/中国ADR/低位等）。深刻度の高い順に最大2つ表示。タップ詳細で全文。"""
    fl = risk_flags_for(t, close)
    if not fl:
        return ""
    fl = sorted(fl, key=lambda f: {"crit": 0, "high": 1}.get(f.get("sev"), 2))
    out = ""
    for f in fl[:2]:
        cls = "rf-crit" if f.get("sev") == "crit" else "rf-hi" if f.get("sev") == "high" else "rf-md"
        note = _html.escape(str(f.get("note", "") or ""), quote=True)
        ftype = _html.escape(str(f.get("type", "赤旗") or "赤旗"), quote=True)
        out += f'<span class="rflag {cls}" title="{note}">⚠{ftype}</span>'
    return out
ALLOC = (70, 30, 0)            # 個別 / レバ / 現金 (確定 2026-07-02)
REBAL_ANCHOR_ENV = os.environ.get("V38_REBAL_ANCHOR", "").strip()  # 隔週サイクルの基準月曜（未指定時はstateへ初期化）
# industries excluded from sector-RS (binary-event noise); editable blacklist
SECTOR_BLACKLIST_KEYS = ("biotech", "pharmaceutic", "drug")

# ----------------------------------------------------------------------------- inputs
def load_inputs(use_cache=True):
    # BOM除去(utf-8-sig)＋列名ゆらぎ吸収: Ticker/Symbol/ticker/symbol いずれでも読む
    rows = list(csv.DictReader(open(UNIVERSE_CSV, encoding="utf-8-sig")))
    if not rows:
        raise SystemExit(f"[FATAL] universe CSV が空です: {UNIVERSE_CSV}")
    cols0 = {c.lower().strip(): c for c in rows[0].keys()}
    # 英語列名 + TradingView日本語エクスポート(シンボル/名称)の両対応
    tcol = (cols0.get("ticker") or cols0.get("symbol") or cols0.get("yf_ticker")
            or cols0.get("シンボル") or cols0.get("ティッカー") or cols0.get("銘柄"))
    ncol = (cols0.get("name") or cols0.get("company") or cols0.get("description")
            or cols0.get("名称") or cols0.get("銘柄名"))
    if not tcol:
        raise SystemExit(f"[FATAL] universe CSV にティッカー列(Ticker/Symbol/シンボル)が見つかりません。実際の列={list(rows[0].keys())}")
    names = {}
    order = []
    _seen = set()
    _dup_same, _dup_conflict, _invalid_tk = [], [], []
    for r in rows:
        b = (r.get(tcol) or "").strip().upper()
        if not b:
            continue
        if not _valid_ticker(b):                       # #2 不正文字を含むティッカーは通さない（HTML属性/JS注入対策）
            _invalid_tk.append(b[:30]); continue
        _nm = (r.get(ncol) or "").strip() if ncol else ""
        if b in _seen:                                 # #3 重複ティッカー
            if names.get(b, "") == _nm:
                _dup_same.append(b)                    #   同名→除去＋警告
            else:
                _dup_conflict.append((b, names.get(b, ""), _nm))   # 別名→本番停止候補
            continue
        _seen.add(b)
        names[b] = _nm
        order.append(b)
    if _invalid_tk:
        sys.stderr.write("[universe] 不正ティッカーを除外(%d件): %s\n" % (len(_invalid_tk), ", ".join(_invalid_tk[:8])))
    if _dup_same:
        sys.stderr.write("[universe] 重複ティッカー(同名)を除去(%d件): %s\n" % (len(_dup_same), ", ".join(sorted(set(_dup_same))[:8])))
    if _dup_conflict:
        # 同一ティッカーに別社名＝データ矛盾。本番は停止（テスト/診断時は先勝ちで継続）。
        _msg = "[universe] 同一ティッカーに異なる社名(%d件): %s" % (
            len(_dup_conflict), "; ".join(f"{t}: '{a}' vs '{c}'" for t, a, c in _dup_conflict[:5]))
        if ("--selftest" in sys.argv) or ("--integration-test" in sys.argv) or ("--diag" in sys.argv):
            sys.stderr.write(_msg + " (テスト継続)\n")
        else:
            raise SystemExit("[FATAL] " + _msg)
    _UNIVERSE_DUP_N = len(_dup_same) + len(_dup_conflict)
    globals()["_UNIVERSE_DUP_N"] = _UNIVERSE_DUP_N
    globals()["_UNIVERSE_INVALID_N"] = len(_invalid_tk)
    if not order:
        raise SystemExit(f"[FATAL] universe から銘柄を1つも読めませんでした(列={list(rows[0].keys())}, 行数={len(rows)})")
    # --- ユニバース整形: TradingViewエクスポートの不適格銘柄を除去 ---
    #   ① 優先株/特殊記号(JPM/PM等・yfinance非対応)  ② 優先株/ワラント/権利/ユニット(名称)
    #   ③ 重複クラス株は既知ペアだけ明示除去（時価総額一致だけでは削除しない）
    #   ※ADR(TSM/ASML)とDepository ADR単体は残す。BRK.B等の'.'はyfで'-'変換済み。
    import re as _re, math as _math
    ccol = cols0.get("時価総額") or cols0.get("market cap") or cols0.get("mktcap")
    vcol = cols0.get("出来高, 1日") or cols0.get("出来高") or cols0.get("volume")
    pcol = cols0.get("価格") or cols0.get("price") or cols0.get("close")
    scol = cols0.get("セクター") or cols0.get("sector")
    def _num(r, c):
        try: return float(r.get(c, "") or "nan")
        except Exception: return float("nan")
    row_by_t = {}
    for r in rows:
        tt = (r.get(tcol) or "").strip()
        if tt: row_by_t[tt] = r
    _pfd = _re.compile(r"\bPfd\b|Preferred|Warrant|\bRight(s)?\b|\bUnit(s)?\b|Subordinated Notes", _re.I)
    # 小型バイオ除外: ヘルスケア系セクター かつ 時価総額<$100億 = 投機的小型創薬/バイオ。
    #   大手ヘルスケア(LLY/JNJ/ISRG/VRTX等 $100億超)は残す(モメンタムで来れば拾う)。思想: テック主導の順張り。
    _HC = ("ヘルスケアテクノロジー", "ヘルスケアサービス")
    _BIO_CAP = 10e9
    d_bio = 0
    survivors = []
    for b in order:
        if "/" in b or " " in b:        # 優先株・特殊記号
            continue
        r = row_by_t.get(b, {})
        nm = (r.get(ncol) or "") if ncol else ""
        if nm and _pfd.search(nm):      # 優先株/ワラント/権利/ユニット
            continue
        if scol:                        # 小型バイオ除外
            sec = (r.get(scol) or "").strip()
            mc_ = _num(r, ccol)
            if sec in _HC and not _math.isnan(mc_) and mc_ < _BIO_CAP:
                d_bio += 1; continue
        survivors.append(b)
    # 重複クラス株: 既知ペアのみ明示除去（keep側を残しdiscard側を落とす）。時価総額一致除去は撤廃（監査4）
    _CLASS_PAIRS = [("GOOGL", "GOOG"), ("FOXA", "FOX"), ("NWSA", "NWS"), ("UA", "UAA"), ("LILAK", "LILA"), ("HEI.A", "HEI")]
    _have = set(survivors)
    _drop = {discard for keep, discard in _CLASS_PAIRS if keep in _have and discard in _have}
    survivors = [t for t in survivors if t not in _drop]     # ccolの有無に依らず実行
    dropped_n = len(order) - len(survivors)
    order = survivors
    names = {b: names.get(b, "") for b in order}
    sys.stderr.write(f"[universe] 整形: {dropped_n}除外 → {len(order)}銘柄(優先株/特殊記号/重複クラス株/小型バイオ{d_bio}を除去)\n")
    sj = json.load(open(SECTOR_JSON))
    # #4/#10 sector JSONのschema検証。本番の大規模ユニバースでは一部エントリが不正型のことがあるため、
    #   『不正エントリだけスキップして継続』する（1つの不正で全2794銘柄のビルドを止めない）。
    #   トップlevelが壊れている(dictでない)場合のみFATAL。値の不正セルはNaN扱いに近い挙動で除外する。
    if not isinstance(sj, dict):
        raise SystemExit(f"[FATAL] sector JSON がdictではありません: {SECTOR_JSON}")
    for _k in ("s2i", "s2t", "e2j"):
        if _k in sj and not isinstance(sj[_k], dict):
            raise SystemExit(f"[FATAL] sector JSON の '{_k}' がdictではありません（{type(sj[_k]).__name__}）: {SECTOR_JSON}")
    _sec_skipped = 0
    # s2i: key=ticker, value=業種文字列。不正valueはスキップ。
    s2i = {}
    for _kk, _vv in (sj.get("s2i") or {}).items():
        if isinstance(_kk, str) and isinstance(_vv, str):
            s2i[_kk] = _vv
        else:
            _sec_skipped += 1
    # s2t: key=ticker, value=文字列 または 1〜2要素の文字列配列。不正はスキップ。
    s2t = {}
    for _kk, _vv in (sj.get("s2t") or {}).items():
        if not isinstance(_kk, str):
            _sec_skipped += 1; continue
        if isinstance(_vv, str):
            s2t[_kk] = _vv
        elif isinstance(_vv, list) and (1 <= len(_vv) <= 2) and all(isinstance(x, str) for x in _vv):
            s2t[_kk] = _vv
        else:
            _sec_skipped += 1
    # e2j: key/valueとも文字列。不正はスキップ。
    e2j = {}
    for _kk, _vv in (sj.get("e2j") or {}).items():
        if isinstance(_kk, str) and isinstance(_vv, str):
            e2j[_kk] = _vv
        else:
            _sec_skipped += 1
    if _sec_skipped:
        sys.stderr.write(f"[sector] 不正エントリ {_sec_skipped}件をスキップして継続: {SECTOR_JSON}\n")
    if use_cache and os.path.exists(CACHE):
        # #1 price cacheは制限付きUnpicklerで読む（__reduce__経由のRCEを実行前に拒否）。
        #   加えて、信頼済みルート配下（V38_TRUSTED_CACHE_ROOT or スクリプト同梱bt/）でなければ拒否。
        #   ※許可ルートを検査対象CACHE自身から作らない（それでは常に通過して無意味）。
        _root = _pickle_trusted_root()
        _strict_root = os.environ.get("V38_CACHE_ROOT_STRICT", "1") != "0"
        if _strict_root and not _path_within(CACHE, _root):
            # V38_CACHE_ROOT_STRICT=1(既定)は信頼ルート配下でなければ拒否する（名前どおりstrict）。
            # テストfixtureは V38_CACHE_ROOT_STRICT=0 で明示的に緩める。
            raise SystemExit("[FATAL] price cache is outside the trusted root %s: %s "
                             "（V38_CACHE_ROOT_STRICT=0 で許可、または V38_TRUSTED_CACHE_ROOT を設定）" % (_root, CACHE))
        try:
            pk = _safe_pickle_load(CACHE)
        except pickle.UnpicklingError as _pe:
            # find_class由来(=許可外クラス)は "blocked global for pickle safety" を含む。それ以外は破損(切り詰め等)。
            if "blocked global for pickle safety" in str(_pe):
                raise SystemExit("[FATAL] price cache のpickleに許可されないクラスが含まれます（RCE防止のため中止）: %r" % (repr(_pe)[:120],))
            raise SystemExit("[FATAL] price cache を安全に読めません（破損/切り詰めの可能性）: %r" % (repr(_pe)[:120],))
        except (EOFError, ValueError, AttributeError, ImportError, IndexError, KeyError, MemoryError) as _pe2:
            # #5 途中で切れた/破損したpickleの生traceback(EOFError: Ran out of input等)を、明確なFATALにする。
            #    危険なunsafe pickle.load()へは絶対に戻さない。
            raise SystemExit("[FATAL] price cache を安全に読めません（破損の可能性）: %r" % (repr(_pe2)[:120],))
    else:
        pk = fetch_live(order)          # CI path: no pre-existing cache
    # #10 price cacheのschema検証: dict・Wがdict・OHLCV存在・macroがdict。
    if not isinstance(pk, dict):
        raise SystemExit("[FATAL] price cache がdictではありません")
    if not isinstance(pk.get("W"), dict):
        raise SystemExit("[FATAL] price cache の 'W' がdictではありません")
    _miss = [c for c in ("Open", "High", "Low", "Close", "Volume") if c not in pk["W"]]
    if _miss:
        raise SystemExit(f"[FATAL] price cache の W にOHLCV列が不足: {_miss}")
    if not isinstance(pk.get("macro"), dict):
        raise SystemExit("[FATAL] price cache の 'macro' がdictではありません")
    # #5 asof欠落時は KeyError で落とさず、実価格Closeの最終indexから補完する。
    _cache_asof = pk.get("asof")
    if _cache_asof is None:
        try:
            _cache_asof = str(pd.Timestamp(pk["W"]["Close"].index[-1]))
        except Exception:
            raise SystemExit("[FATAL] price cache に 'asof' が無く、価格indexからも復元できません")
    # 価格/マクロ系列を正規化(tz除去・昇順・重複解消)。tz-aware/降順/重複日付のfixtureでも同結果に（#5）。
    _W = pk["W"]
    # 価格本体は正規化失敗を握り潰さない（fail_closedの例外をそのまま上げ、未正規化データで続行しない・#5）。
    if isinstance(_W, dict):
        _W = {k: normalize_timeseries(v, fail_closed=True, label="price:"+str(k)) for k, v in _W.items()}
    _macro = pk["macro"]
    # macroは系列ごとに独立処理。1系列の正規化失敗で他系列や未正規化データを巻き込まない（#4）。
    if isinstance(_macro, dict):
        _mn = {}
        for _mk, _mv in _macro.items():
            try:
                _mn[_mk] = normalize_timeseries(_mv, fail_closed=False, label="macro:" + str(_mk))
            except Exception as _e:
                sys.stderr.write("[normalize] macro:%s failed, dropping: %r\n" % (_mk, repr(_e)[:80]))
                _mn[_mk] = None
        _macro = {k: v for k, v in _mn.items() if v is not None and hasattr(v, "index") and len(v) > 0}
    return names, order, s2i, s2t, e2j, _W, _macro, _cache_asof

# ----------------------------------------------------------------------------- live fetch (CI)
MACRO_TICKERS = ["^VIX", "^VIX3M", "^VVIX", "^VXN", "QQQ", "QQQE", "SPY", "HYG", "LQD", "IEI", "JPY=X",
                 "RSP", "IWM", "^TNX", "^FVX", "^TYX",
                 "TLT", "^MOVE", "DX-Y.NYB",   # 債券ボラ(MOVE)/その代替(TLT)/ドル(DXYフォールバック)
                 # equal-weight sector ETFs (Invesco) for market-representative sector RS
                 "RSPN", "RSPT", "RSPF", "RSPM", "RSPU", "RSPD",
                 "RSPH", "RSPR", "RSPS", "RSPG", "RSPC",
                 # sentiment sleeve: tail-hedge index + 3x lever pairs (crowd heat)
                 "^SKEW", "TQQQ", "SQQQ", "SOXL", "SOXS",
                 # leverage-sleeve env: semis index (trend/vol) + semis ETF (RRG)
                 "SOXX", "SMH"]

def _extract(df, tickers, minbars=30):
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    multi = isinstance(df.columns, pd.MultiIndex)
    need = ["Open", "High", "Low", "Close", "Volume"]
    for t in tickers:
        try:
            sub = df[t] if multi else df
            if sub is None or sub.dropna(how="all").empty:
                continue
            if not all(c in sub.columns for c in need):
                continue
            s = sub[need].dropna(how="all")
            if len(s) < minbars:
                continue
            out[t] = s
        except Exception:
            continue
    return out

def fetch_live(order, period="3y", chunk=100, retries=3):
    """Fetch the full universe + macro live (GitHub Actions path, no cache).
    Mirrors the resumable fetch but in one process. Universe is keyed by base
    ticker; '/' tickers are skipped (yfinance chokes on them)."""
    import yfinance as yf
    # order(load_inputsで列名・BOM吸収済み)をそのまま使う。CSV再読込はしない。
    # yfinance対応: '.'→'-'(BRK.B→BRK-B)、'/'含みはスキップ。
    pairs = []                                   # (base, yf_symbol)
    for b in order:
        b = (b or "").strip()
        if not b or "/" in b:
            continue
        y = b.replace(".", "-")
        pairs.append((b, y))
    y2b = {y: b for b, y in pairs}   # yf_symbol(-) -> base(.)
    yfs = [y for _, y in pairs]
    sys.stderr.write("[fetch_live] universe=%d, fetching in chunks of %d...\n" % (len(pairs), chunk))

    store = {}
    for i in range(0, len(yfs), chunk):
        ch = yfs[i:i + chunk]
        for attempt in range(retries):
            try:
                df = yf.download(ch, period=period, progress=False, auto_adjust=True,
                                 group_by="ticker", threads=True)
                got = _extract(df, ch)
                store.update(got)
                missing = [t for t in ch if t not in store]
                # one retry pass only for the still-missing names (handles partial 429s)
                if missing and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                break
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))      # exponential-ish backoff
                    continue
                sys.stderr.write("  chunk err (gave up): %s\n" % repr(e)[:80])
        sys.stderr.write("  %d/%d  have=%d\n" % (min(i + chunk, len(yfs)), len(yfs), len(store)))

    def wide(field):
        cols = {y2b.get(y, y): df[field] for y, df in store.items()}
        return pd.DataFrame(cols).sort_index()
    W = {f: wide(f) for f in ["Open", "High", "Low", "Close", "Volume"]}

    sys.stderr.write("[fetch_live] fetching macro...\n")
    macro = {}
    try:
        md = yf.download(MACRO_TICKERS, period=period, progress=False,
                         auto_adjust=True, group_by="ticker", threads=True)
        macro = _extract(md, MACRO_TICKERS, minbars=20)
    except Exception:
        pass
    for m in [x for x in MACRO_TICKERS if x not in macro]:   # per-ticker fallback
        try:
            macro.update(_extract(yf.download([m], period=period, progress=False,
                                              auto_adjust=True), [m], minbars=20))
        except Exception:
            pass
    sys.stderr.write("[fetch_live] universe cols=%d  macro=%d/%d (VVIX=%s VIX3M=%s)\n" % (
        W["Close"].shape[1], len(macro), len(MACRO_TICKERS),
        "^VVIX" in macro, "^VIX3M" in macro))
    return {"W": W, "macro": macro, "asof": str(pd.Timestamp.now("UTC"))}

def theme_of(t, s2t):
    v = s2t.get(t)
    if isinstance(v, list) and v:
        return v[0]
    if isinstance(v, str) and v.strip():
        return v.strip()
    return "その他"

def subtheme_of(t, s2t, fallback="その他"):
    """Specific sub-theme (量子/メモリ/AI GPU等). Falls back to `fallback` when absent."""
    v = s2t.get(t)
    if isinstance(v, list) and len(v) >= 2 and v[1] and v[1] not in ("?", ""):
        return v[1]
    return fallback

# ----------------------------------------------------------------------------- per-ticker metrics
def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _drop_unconfirmed_week(w, last_daily_ts):
    """#3: W-FRI週足から未確定の当該週（最終日足が金曜より前＝週の途中）を落とす。
       日足は確定営業日で切っていても、当該週の週足バーは未完成なので週次指標には使わない。"""
    try:
        if last_daily_ts is not None and pd.Timestamp(last_daily_ts).weekday() < 4 and len(w) > 1:
            return w.iloc[:-1]
    except Exception:
        pass
    return w


def weekly_sar_bullish(h, l, c):
    """Wilder Parabolic SAR on W-FRI weekly bars. Return True if current bar bullish."""
    df = pd.DataFrame({"High": h, "Low": l, "Close": c}).dropna()
    if len(df) < 15:
        return np.nan
    w = df.resample("W-FRI").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()
    w = _drop_unconfirmed_week(w, df.index[-1] if len(df) else None)
    if len(w) < 10:
        return np.nan
    H = w["High"].values; L = w["Low"].values
    af0, step, afmax = 0.02, 0.02, 0.20
    up = w["Close"].values[1] >= w["Close"].values[0]
    sar = L[0] if up else H[0]
    ep = H[0] if up else L[0]
    af = af0
    for i in range(1, len(w)):
        prev = sar
        sar = prev + af * (ep - prev)
        if up:
            sar = min(sar, L[i-1], L[i-2] if i >= 2 else L[i-1])
            if H[i] > ep:
                ep = H[i]; af = min(af + step, afmax)
            if L[i] < sar:
                up = False; sar = ep; ep = L[i]; af = af0
        else:
            sar = max(sar, H[i-1], H[i-2] if i >= 2 else H[i-1])
            if L[i] < ep:
                ep = L[i]; af = min(af + step, afmax)
            if H[i] > sar:
                up = True; sar = ep; ep = H[i]; af = af0
    return bool(up)

def weinstein_stage(c):
    """週足×30週MAのステージ判定（1=底固め/移行、2=上昇、3=天井圏、4=下降）。
    判定: 価格が30週MAの上か下 × 30週MAの向き（4週前比）。
    ステージ2内は「ベース数」を概算（高値から8%以上・4週以上の調整→新高値で1本消化）。"""
    try:
        w = c.resample("W-FRI").last().dropna()
        w = _drop_unconfirmed_week(w, c.index[-1] if len(c) else None)
    except Exception:
        return None
    if len(w) < 36:
        return None
    ma = w.rolling(30).mean()
    n = len(w)
    st = [0] * n
    for i in range(n):
        mi = ma.iloc[i]
        if i < 30 or mi != mi:
            continue
        rising = mi >= float(ma.iloc[i - 4]) if i >= 34 else True
        above = float(w.iloc[i]) > float(mi)
        st[i] = 2 if (above and rising) else 1 if above else 3 if rising else 4
    cur = st[-1]
    if cur == 0:
        return None
    k = 0
    for i in range(n - 1, -1, -1):
        if st[i] == cur:
            k += 1
        else:
            break
    base, forming = None, False
    if cur == 2:
        i0 = n - k
        peak = float(w.iloc[i0]); base = 0; inb = False; bw = 0
        for i in range(i0, n):
            px = float(w.iloc[i])
            if px >= peak:
                if inb and bw >= 4:
                    base += 1
                inb, bw, peak = False, 0, px
            else:
                if px / peak - 1 <= -0.08:
                    inb = True
                if inb:
                    bw += 1
        forming = bool(inb and bw >= 4)
    return dict(wst=int(cur), wstw=int(k), wsb=(int(base) if base is not None else None), wsbf=forming)


# ═══════════════════════════════════════════════════════════════════
# W30ブレイク（30週線ブレイク）判定  — 全期間検証 2016-06〜2026-07
# 判定は週足(W-FRI)。クロス週に勢い/クリア幅/位置で4グレード分類。
# ═══════════════════════════════════════════════════════════════════
W30X = dict(wret_min=0.06, ext_min=0.05, lo52_mult=1.50, ext_weak=0.01, px_min=5.0, recent_weeks=13)
W30X_SCORE = dict(turnaround_dist52h=-0.30, wret_boost=0.10, ext_boost=0.10, s_min=3, a_min=1)
W30X_PB = dict(pb_advance=1.05, pb_touch=1.03)                       # 健全押し目: +5%上昇後にMA×1.03タッチ・終値MA上
W30X_RESUME_STAR = dict(adv_min=0.09, res_wret_min=0.07, d52h_max=-0.15)  # ★: 47.3%/+13.4%(N=148)
W30X_ENTRY = dict(exec_next_open=True, chase_ok_if_alive=True, stage1_stop=-0.10)
W30X_EXIT = dict(under_sig_low_weeks=4, stop_close=-0.10, time_stop_weeks=8, time_stop_minprog=0.05)
W30X_STATS = {
    "FULL":  dict(w30=43.6, w50=24.6, dbl=19.5, fake=54, n=1136),
    "POS":   dict(w30=43.0, w50=20.5, dbl=14.6, fake=66, n=630),    # 位置本格級・勢い不足(52wL×1.5+ & ext>=3%)・年次9/11
    "PARTP": dict(w30=30.7, w50=14.8, dbl=10.4, fake=53, n=1044),   # PART+ 位置ニア(52wL×1.30+)
    "PARTM": dict(w30=20.2, w50=6.6,  dbl=3.6,  fake=57, n=786),    # PART- 位置遠い(監視外)
    "WEAK":  dict(w30=23.5, w50=8.9,  dbl=5.9,  fake=81, n=3487),
    "CROSS": dict(w30=21.8, w50=7.4,  dbl=4.6,  fake=71, n=6016),   # POS切り出し後の残り
}

def w30_breakout(c, low=None, p=W30X, high=None):
    """W30ブレイク判定(週足W-FRI)。lowに日足Low、highに日足HighのSeriesを渡すと
       押し目タッチ(Low)・最大含み益(High)の判定が正確になる。生存/失効はCloseで判定。"""
    out = dict(w30x_grade=None, w30x_wk_ago=None, w30x_wret=np.nan,
               w30x_ext=np.nan, w30x_vslo52=np.nan, w30x_dist52h=np.nan,
               w30x_score=None, w30x_tier=None, w30x_status=None, w30x_prog=np.nan,
               w30x_res_star=False, w30x_promoted=False,
               w30x_confirmed=True, w30x_alive=True)
    try:
        w = c.resample("W-FRI").last().dropna()
        w = _drop_unconfirmed_week(w, c.index[-1] if len(c) else None)   # #3: 未確定週を計算に含めない
        wl = (low.resample("W-FRI").min().reindex(w.index) if low is not None else w)
        wh = (high.resample("W-FRI").max().reindex(w.index) if high is not None else w)   # #33: 最大含み益用の週足High
    except Exception:
        return out
    if len(w) < 55:
        return out
    ma = w.rolling(30).mean(); lo52 = w.rolling(52).min(); hi52 = w.rolling(52).max()
    above = (w > ma)
    cross = above & (~above.shift(1, fill_value=False))
    n = len(w)
    for k in range(p["recent_weeks"] + 1):
        i = n - 1 - k
        if i < 52 or not bool(cross.iloc[i]):
            continue
        px = float(w.iloc[i]); mai, loi = float(ma.iloc[i]), float(lo52.iloc[i])
        if not (px == px and mai == mai and loi == loi) or px < p["px_min"] or loi <= 0:
            continue
        wret = px / float(w.iloc[i - 1]) - 1
        ext = px / mai - 1
        vslo = px / loi
        hii = float(hi52.iloc[i])
        d52h = px / hii - 1 if hii == hii and hii > 0 else np.nan
        if ext < p["ext_weak"]:
            g = "WEAK"
        elif wret >= p["wret_min"] and ext >= p["ext_min"]:
            g = "FULL" if vslo >= p["lo52_mult"] else ("PARTP" if vslo >= 1.30 else "PARTM")
        elif vslo >= p["lo52_mult"] and ext >= 0.03:
            g = "POS"          # 位置本格級・勢い不足: 伸びFULL並み43.0%・騙し66%
        else:
            g = "CROSS"
        # -- シグナル後の状態マシン(E1/E2/E3・押し目・再始動・昇格) --
        entry, siglow = px, float(wl.iloc[i])
        status, posthigh, pb_seen = "NEW", entry, False
        prog = float(w.iloc[-1]) / entry - 1
        maxprog, adv_pb, res_star, promoted = 0.0, None, False, False
        for kk in range(1, k + 1):
            jj = i + kk
            cl, lo_, m_ = float(w.iloc[jj]), float(wl.iloc[jj]), float(ma.iloc[jj])
            if (kk <= 4 and cl < siglow) or cl <= entry * 0.90:
                status = "DEAD"; break                       # E1/E2 失効
            maxprog = max(maxprog, float(wh.iloc[jj]) / entry - 1)   # #33: 週中の最大到達(High)で含み益
            if g in ("PARTP", "PARTM", "CROSS") and not promoted:
                lo_now = float(lo52.iloc[jj])
                if lo_now > 0 and cl >= lo_now * p["lo52_mult"]:
                    promoted = True                          # 昇格up: 到達時点から34.6%/+8.5%
            if pb_seen and cl > posthigh:
                status = "RESUME"                            # 二次エントリー
                q = W30X_RESUME_STAR
                rw = cl / float(w.iloc[jj - 1]) - 1
                res_star = (adv_pb is not None and adv_pb >= q["adv_min"]
                            and rw >= q["res_wret_min"] and d52h == d52h and d52h <= q["d52h_max"])
            elif posthigh >= entry * W30X_PB["pb_advance"] and lo_ <= m_ * W30X_PB["pb_touch"] and cl >= m_:
                if not pb_seen: adv_pb = posthigh / entry - 1
                pb_seen = True
                if status != "RESUME": status = "PB"         # 押し目形成中
            posthigh = max(posthigh, cl)
        if status != "DEAD":
            if k >= W30X_EXIT["time_stop_weeks"] and maxprog < W30X_EXIT["time_stop_minprog"]:
                status = "STALL"                             # E3
            elif status == "NEW" and k > 4:
                status = "ADV"
        sc, tier = None, None
        if g == "FULL":
            q = W30X_SCORE
            sc = (2 * int(d52h == d52h and d52h <= q["turnaround_dist52h"])
                  + int(wret >= q["wret_boost"]) + int(ext >= q["ext_boost"]))
            tier = "S" if sc >= q["s_min"] else "A" if sc >= q["a_min"] else "B"
        confirmed = True   # #3: 未確定週を除外済みなので、扱う週は全て確定週
        alive = bool(w.iloc[-1] > ma.iloc[-1]) if ma.iloc[-1] == ma.iloc[-1] else True
        out.update(w30x_grade=g, w30x_wk_ago=k, w30x_wret=wret, w30x_ext=ext,
                   w30x_vslo52=vslo, w30x_dist52h=d52h, w30x_score=sc, w30x_tier=tier,
                   w30x_status=status, w30x_prog=prog, w30x_res_star=res_star,
                   w30x_promoted=promoted, w30x_confirmed=confirmed, w30x_alive=alive)
        return out
    return out


_W30_LAB = {"FULL": "◎", "POS": "◉", "PARTP": "○+", "PARTM": "○−", "WEAK": "△", "CROSS": "・"}
_W30_CLS = {"FULL": "w30b w30b-full", "POS": "w30b w30b-full", "PARTP": "w30b w30b-part", "PARTM": "w30b", "WEAK": "w30b w30b-weak", "CROSS": "w30b"}

def _w30x_badge(r):
    g = r.get("w30x_grade")
    if not (isinstance(g, str) and g in W30X_STATS):
        return ""
    s = W30X_STATS[g]
    try:
        k = int(r.get("w30x_wk_ago") or 0)
    except Exception:
        k = 0
    wk = "今週" if k == 0 else f"{k}週前"
    pend = "" if r.get("w30x_confirmed", True) else "（週中・仮判定）"
    desc = {"FULL": "本格: 週足+6%以上・30WMAを5%以上クリア・52週安値から+50%以上",
            "POS": "位置本格級（52wL×1.5+・ext3%+）だが勢い不足: 伸びFULL並み・騙し66%",
            "PARTP": "勢いあり・位置ニア（52wL×1.30+）",
            "PARTM": "勢いあり・位置遠い: 実質監視外（+30%到達20.2%）",
            "WEAK": "ギリ抜け（クリア幅1%未満）: 騙し率81%の要警戒",
            "CROSS": "素の30週線上抜け（追加条件未達）"}[g]
    _ST = {"NEW": "新規", "ADV": "進行", "PB": "押し目", "RESUME": "再始動", "STALL": "停滞(E3)", "DEAD": "失効(E1/E2)"}
    st = r.get("w30x_status")
    star = "★" if r.get("w30x_res_star") else ""
    up = "↑" if r.get("w30x_promoted") else ""
    stbadge = f'<span class="w30s w30s-{str(st).lower()}">{star}{_ST.get(st, "")}{up}</span>' if st else ""
    tier = r.get("w30x_tier")
    # ◎(FULL)内の格付けS/A/Bは、成績(SほどP高)に応じて独立の色バッジで表示
    _tier_stat = {"S": "+30%到達66%・2倍41%", "A": "+30%到達42%・2倍19%", "B": "+30%到達35%・2倍10%"}
    tbadge = ""
    if g == "FULL" and tier in ("S", "A", "B"):
        tbadge = f'<span class="w30t w30t-{tier.lower()}" title="◎本格の格付け {tier}：{_tier_stat[tier]}">{tier}</span>'
    wk_lab = '<span class="w30new">初</span>' if k == 0 else f'<span class="w30wk">{k}w</span>'
    return (f'<span class="{_W30_CLS[g]}" title="W30ブレイク {wk}{pend} — {desc}。'
            f'全期間実測(2016-26,N={s["n"]}): +30%到達{s["w30"]}% / +50% {s["w50"]}% / '
            f'52週2倍{s["dbl"]}% / 騙し(12週内30WMA割れ){s["fake"]}%">'
            f'{_W30_LAB[g]}</span>{tbadge}{stbadge}{wk_lab}')

def _w30_disp_ok(r):
    """W30表示要件（他タブ共通の適格性）: 時価総額$1B・株価$5・20日平均売買代金$10M・非サスペクト・小型創薬除外。
       ※時価総額≥$1Bはピックアップ/買い候補(RS63≥85…時価総額≥$1B…)と同一フロア。mcap欠損は他タブ同様フェイル扱い。"""
    try:
        c = r.get("close"); dv = r.get("dvol"); mc = r.get("mcap")
        if mc is None or mc != mc or float(mc) < 1e9:      # 時価総額≥$1B（他タブ共通・欠損は除外）
            return False
        if c is None or c != c or float(c) < 5:
            return False
        if dv is None or dv != dv or float(dv) < DVOL_FLOOR:
            return False
        if bool(r.get("split_suspect")) or bool(r.get("excluded_theme")):
            return False
        return True
    except Exception:
        return False

def _w30_cohort_card(m, e2j=None):
    _ok = m.apply(_w30_disp_ok, axis=1) if len(m) else pd.Series(dtype=bool)
    m = m[_ok] if len(m) else m
    core = m[m["w30x_grade"].isin(["FULL", "POS", "PARTP"])
             & ~m["w30x_status"].isin(["DEAD", "STALL"])]
    if len(core) == 0:
        return '<div class="card"><h2>コホート分析</h2><div class="mut">有効シグナルなし</div></div>'
    cm = []
    full = core[core["w30x_grade"] == "FULL"]
    tc = full["w30x_tier"].value_counts()
    s_n, a_n = int(tc.get("S", 0)), int(tc.get("A", 0))
    cm.append(f'Sティア{s_n}件・A{a_n}件が監視主軸。' if s_n else f'Sティアなし。監視主軸はA{a_n}件。')
    posn = int((core["w30x_grade"] == "POS").sum())
    if posn: cm.append(f'◉POSが{posn}件。伸びFULL並みだが騙し66%——サイズ半分等の調整が現実的。')
    pbn = int((core["w30x_status"] == "PB").sum()); rsn = int((core["w30x_status"] == "RESUME").sum())
    stn = int(core["w30x_res_star"].fillna(False).sum())
    if pbn or rsn: cm.append(f'押し目形成中{pbn}件・再始動{rsn}件' + (f'（うち★{stn}件＝最優先）' if stn else '') + '。')
    prn = int((m["w30x_promoted"].fillna(False) & m["w30x_grade"].isin(["PARTP", "PARTM"])).sum())
    if prn: cm.append(f'PART勢の昇格↑が{prn}件（到達時点から34.6%）。')
    if "ind" in core:
        ic = core["ind"].dropna().value_counts()
        if len(ic) and ic.iloc[0] >= max(3, 0.15 * len(core)):
            ja = (e2j or {}).get(ic.index[0], ic.index[0])
            cm.append(f'業種は「{ja}」に集中（{ic.iloc[0]}/{len(core)}件）＝セクター主導。分散は業種単位で。')
        elif len(ic) >= 8:
            cm.append(f'業種{len(ic)}種に分散、個別物色の局面。')
    if "tier_lab" in m:
        szc = core["tier_lab"].dropna().value_counts()
        if len(szc) and szc.iloc[0] / max(len(core), 1) >= 0.5:
            cm.append(f'サイズは{szc.index[0]}が過半（{szc.iloc[0]}/{len(core)}件）。予測力はないため補足まで。')
    dh = core["w30x_dist52h"].median()
    if dh == dh:
        cm.append(f'52週高値から中央{100*dh:.0f}%——' + ('深押し回復型が主体。E1/E2順守が前提。' if dh <= -0.25 else '高値圏型が主体。騙し少なめ・伸び限定的。' if dh >= -0.10 else '回復途上型が中心。'))
    body = ''.join(f'<div class="w30coh">・{x}</div>' for x in cm)
    return f'<div class="card"><h2>コホート分析 <span class="h2en">Cohort</span></h2><div class="sub">有効◎◉○+ {len(core)}件・自動生成</div>{body}</div>'


def build_w30_breakouts(m, cap=12, e2j=None):
    rk = {"FULL": 0, "POS": 1, "PARTP": 2}
    st_rk = {"RESUME": 0, "NEW": 1, "PB": 2, "ADV": 3}
    _valid = {"FULL", "POS", "PARTP", "WEAK"}
    rows, warns, partm_list, dead_list = [], [], [], []
    cross_n = 0
    for t, r in m.iterrows():
        if not _w30_disp_ok(r):
            continue
        g = r.get("w30x_grade")
        if not (isinstance(g, str) and g in W30X_STATS):
            continue
        stt = r.get("w30x_status")
        if g == "CROSS":
            cross_n += 1; continue
        if g == "PARTM":
            if stt not in ("DEAD", "STALL"):
                partm_list.append(t)
            continue
        if g == "WEAK":
            warns.append((t, r)); continue
        if stt in ("DEAD", "STALL"):
            dead_list.append((t, "失効" if stt == "DEAD" else "停滞")); continue
        _tr = {"S": 0, "A": 1, "B": 2}.get(r.get("w30x_tier"), 3)
        rows.append((rk.get(g, 9), _tr, st_rk.get(stt, 9), -float(r.get("w30x_ext") or 0), t, r))
    rows.sort()

    def _line(t, r):
        s52 = f'52週安値×{r["w30x_vslo52"]:.2f}'
        d52 = r.get("w30x_dist52h")
        turn = f'・高値−{abs(d52)*100:.0f}%' if (d52 == d52 and d52 is not None) else ""
        prog = r.get("w30x_prog")
        pg = f'・現在{100*prog:+.0f}%' if (prog == prog and prog is not None) else ""
        return (f'<div class="w30row" data-tkone="{t}"><div class="w30row-h"><b>{t}</b>{_w30x_badge(r)}</div>'
                f'<div class="w30row-m">週足 {100*r["w30x_wret"]:+.1f}%・30WMA +{100*r["w30x_ext"]:.1f}%・{s52}{turn}{pg}</div></div>')
    body = "".join(_line(t, r) for _, _, _, _, t, r in rows[:cap]) or '<div class="mut">直近13週の有効シグナルなし</div>'
    warn = "".join(f'<div class="w30row"><div class="w30row-h"><b>{t}</b>{_w30x_badge(r)}</div></div>' for t, r in warns[:cap])
    warn_html = (f'<div class="mut" style="font-size:10.5px;font-weight:800;margin:10px 0 5px;color:#fca5a5">ギリ抜け（騙し率81%・原則見送り）</div>{warn}') if warn else ""
    tail = []
    if partm_list:
        tail.append(f'○− PART−（監視外・{len(partm_list)}件）: ' + "・".join(partm_list[:20]))
    if cross_n:
        tail.append(f'・CROSS（素の上抜け）: {cross_n}件')
    if dead_list:
        tail.append('失効・停滞: ' + "・".join(f'{t}({lab})' for t, lab in dead_list[:20]))
    tail_html = "".join(f'<div class="mut" style="font-size:10.5px;margin-top:6px">{x}</div>' for x in tail)
    signal_card = (f'<div class="card"><div class="hdr"><h2>ブレイク一覧 <span class="h2en">Signals</span></h2>{_cp([t for _,_,_,_,t,_ in rows[:cap]])}</div>'
            f'<div class="sub">直近13週・E1/E2/E3非発動。◎→◉→○+の順。表示要件: 時価総額$1B・株価$5・売買代金$10M/日・小型創薬除外（他タブ共通）。</div>'
            f'{body}{warn_html}{tail_html}</div>')

    _TIER_STATS = {"S": dict(w30=66.4, w50=49.0, dbl=41.3, fake=46),
                   "A": dict(w30=42.2, w50=22.9, dbl=18.9, fake=52),
                   "B": dict(w30=35.2, w50=16.5, dbl=9.9,  fake=62)}
    def _trow(badge, cond, st, hi=False):
        cls = "w30hi" if hi else ""
        return (f'<tr class="{cls}"><td class="l">{badge}</td><td class="l" style="font-size:11px;color:#94a3b8">{cond}</td>'
                f'<td>{st["w30"]:.1f}%</td><td>{st["w50"]:.1f}%</td>'
                f'<td>{st["dbl"]:.1f}%</td><td class="neg">{st["fake"]}%</td></tr>')
    _b = lambda cls, txt: f'<span class="{cls}">{txt}</span>'
    legend_card = ('<div class="card"><h2>定義・グレード・格付け <span class="h2en">Grades</span></h2>'
            '<div class="sub">クロス＝週足終値が30WMA上抜け。[1]勢い: 週足リターン≥+6% ／ [2]クリア幅: ≥30WMA×1.05 ／ [3]位置: ≥52週安値×1.50</div>'
            '<table><tr><th class="l">区分</th><th class="l">条件</th><th>+30%</th><th>+50%</th><th>2倍</th><th>騙し</th></tr>'
            + _trow(_b("w30t w30t-s", "S") + _b("w30b w30b-full", "◎"), "FULL＋スコア3-4", _TIER_STATS["S"], hi=True)
            + _trow(_b("w30t w30t-a", "A") + _b("w30b w30b-full", "◎"), "FULL＋スコア1-2", _TIER_STATS["A"])
            + _trow(_b("w30t w30t-b", "B") + _b("w30b w30b-full", "◎"), "FULL＋スコア0", _TIER_STATS["B"])
            + _trow(_b("w30b w30b-full", "◉ POS"), "[3]＋ext≥3%（勢い不足）", W30X_STATS["POS"])
            + _trow(_b("w30b w30b-part", "○+ PART+"), "[1][2]＋52wL×1.30+", W30X_STATS["PARTP"])
            + _trow(_b("w30b", "○− PART−"), "[1][2]のみ・位置遠い", W30X_STATS["PARTM"])
            + _trow(_b("w30b", "・CROSS"), "素の上抜け（残り）", W30X_STATS["CROSS"])
            + _trow(_b("w30b w30b-weak", "△ WEAK"), "クリア幅<1%", W30X_STATS["WEAK"])
            + '</table>'
            '<div class="sub" style="margin-top:8px">スコア: 52週高値から−30%超下＝+2点（ターンアラウンド位置）／ 週足リターン≥+10%＝+1 ／ クリア幅≥+10%＝+1。'
            'スコア0→4で+30%到達35→58〜79%の単調性を全期間で確認済み。'
            '◉POSは年次一貫性9/11。騙し66%だがE4により騙しは執行に影響しない。↑昇格＝ウォッチ中に52wL×1.5到達（到達時点から34.6%・中央3週目）。</div></div>')

    rule_card = ('<div class="card"><h2>運用ルール（確定版） <span class="h2en">Playbook</span></h2>'
        '<div class="w30exit"><span class="w30exit-t">1</span><span class="w30exit-b">入るのはSとAだけ。金曜確定→翌週寄り成行（ギャップ中央+0.0〜0.2%）。POS・PART+は表示のみ</span></div>'
        '<div class="w30exit"><span class="w30exit-t">2</span><span class="w30exit-b">出遅れ追撃は4週以内・進捗プラスなら可（+10%超でもS/Aで到達58%）。0〜+5%停滞だけ追わない</span></div>'
        '<div class="w30exit"><span class="w30exit-t">3</span><span class="w30exit-b">降りはE1/E2/E3のみ。30WMA再割れでは降りない</span></div>'
        '<div class="w30exit"><span class="w30exit-t">4</span><span class="w30exit-b">二次エントリーは★再始動のみ（未保有銘柄限定）</span></div>'
        '<div class="w30exit"><span class="w30exit-t">5</span><span class="w30exit-b">サイズ・流動性・出来高・押し目待ちは見ない（売買代金五分位で到達率フラット、全て検証で棄却済み）。※統計上の話。表示リストには他タブ共通の適格要件（$5・$10M・小型創薬除外）を適用</span></div>'
        '<div class="sub">頻度実測: S年14件・A年72件。S即入り分解: 勝率74%・中央+31.6%・平均+46.5%・下位25% −1.9%</div></div>')

    status_card = ('<div class="card"><h2>状態の凡例 <span class="h2en">Status</span></h2>'
        '<div class="w30exit"><span class="w30exit-t">新規</span><span class="w30exit-b">≤4週・一次エントリーの窓</span></div>'
        '<div class="w30exit"><span class="w30exit-t">進行</span><span class="w30exit-b">5週+・追いかけない</span></div>'
        '<div class="w30exit"><span class="w30exit-t">押し目</span><span class="w30exit-b">+5%上昇後にMA×1.03タッチ・終値MA上＝二次待ち</span></div>'
        '<div class="w30exit"><span class="w30exit-t">★再始動</span><span class="w30exit-b">押し目後に終値新値。★=47.3%/+13.4%</span></div>'
        '<div class="w30exit"><span class="w30exit-t">停滞</span><span class="w30exit-b">E3（8週で最大進捗+5%未満）</span></div>'
        '<div class="w30exit"><span class="w30exit-t">失効</span><span class="w30exit-b">E1/E2（安値割れ・−10%）</span></div></div>')

    q = W30X_EXIT
    _e1w = q["under_sig_low_weeks"]; _e2p = int(q["stop_close"] * 100)
    _e3w = q["time_stop_weeks"]; _e3p = int(q["time_stop_minprog"] * 100)
    def _exit(tag, txt):
        return f'<div class="w30exit"><span class="w30exit-t">{tag}</span><span class="w30exit-b">{txt}</span></div>'
    entry_card = ('<div class="card"><h2>入り方 <span class="h2en">Entries</span></h2>'
        + _exit("N1 執行", "金曜クローズ確定→翌週寄り成行。ギャップ中央+0.0〜0.2%で無視できる")
        + _exit("N2 即入り", "S/Aは即入り一択。押し目待ちの1シグナルEVはS +5.0% vs 即入り+46.5%、勝者の77〜94%を取り逃す")
        + _exit("N3 追撃", "生存中なら+10%超プレミアムでも可（S/Aで58.1%・r26中央+17.4%）。停滞0〜+5%帯（22.0%）だけ追わない")
        + _exit("N4 先回り", "上級: 10WMA上抜け・30WMA未満・52wL×1.4+ → 48.8%/+12.7%だが−10%被弾33.2%。E2厳守が絶対条件")
        + '</div>')
    exit_card = ('<div class="card"><h2>手仕舞いの目安 <span class="h2en">Exits</span></h2>'
        '<div class="sub">全期間実測 N=13,169（26週完全データ）。</div>'
        + _exit("E1 即降り", f"{_e1w}週以内にシグナル週安値を週足終値で割れ → 到達15.3%（守れば残り32.3%）")
        + _exit("E2 損切り", f"シグナル週終値から{_e2p}% → −12%超群は中央−10.0%")
        + _exit("E3 タイム", f"{_e3w}週で最大進捗+{_e3p}%未満 → 伸びず（+5〜10%帯は半分が降り）")
        + _exit("E4 保持", "30WMA再割れでは降りない：残余は中央+4.0%（◎は+9.0%）・勝率57%")
        + '</div>')
    cohort_card = _w30_cohort_card(m, e2j=e2j)
    return signal_card + rule_card + legend_card + status_card + cohort_card + entry_card + exit_card

def last_completed_session(now=None):
    """最後に「引けまで完了した」米国市場の営業日(日付)を返す。
       ザラ場中実行では当日を確定足とみなさない。祝日カレンダーは持たないが、
       `index <= cut` で切るだけなので祝日は自然に無視される（直前の実バーが残る）。"""
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except Exception:
        et = None
    now = now or dt.datetime.now(dt.timezone.utc)
    n = now.astimezone(et) if et is not None else (now - dt.timedelta(hours=5))
    d = n.date()
    # 16:15 ET(引け+15分)を確定線とする。それ未満なら当日は未確定。
    if (n.hour, n.minute) < (16, 15):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:                       # 土日は営業日でない
        d -= dt.timedelta(days=1)
    return pd.Timestamp(d)

def cut_to_completed(W, macro):
    """A5-2: 株式(W)とマクロ(macro)を「同一の最終確定営業日」で切り揃える。
       カバレッジ判定(guard_last_bar)はザラ場中に全銘柄が部分足を持つとすり抜けるため、
       出来高系(売り抜け日/FTD/PP/出来高急増)の誤判定を日付で構造的に防ぐ。"""
    cut = last_completed_session()
    # 主要フィード（個別株Close・QQQ・SPY）の最終有効日を確認し、遅い方に合わせて共通日を保証する。
    # 例: 個別株が7/10まで・QQQが7/9までなら、cut=7/9 に揃える（日付ズレのまま計算しない）。
    feeds = []
    c0 = W.get("Close")
    if c0 is not None and len(c0):
        feeds.append(c0.index[c0.notna().any(axis=1)].max())
    for k in ("QQQ", "SPY"):
        d = macro.get(k)
        if d is not None and len(d):
            feeds.append(d.dropna(subset=["Close"]).index.max())
    if feeds:
        cut = min(cut, min(feeds))                # 全主要フィードが確定している最新日
    def _c(v):
        if hasattr(v, "index") and isinstance(getattr(v, "index", None), pd.DatetimeIndex):
            return v[v.index <= cut]
        return v
    nW = {k: _c(v) for k, v in W.items()}
    nM = {k: _c(v) for k, v in macro.items()}
    try:
        c0 = W.get("Close")
        if c0 is not None and len(c0) and len(nW["Close"]) < len(c0):
            sys.stderr.write("[cut] 未確定足を除外: %s → 確定日 %s\n"
                             % (str(c0.index[-1].date()), str(cut.date())))
    except Exception:
        pass
    return nW, nM, cut

def guard_last_bar(W):
    """A5/当日部分バー対策: 直近バーの銘柄数が「20日中央値の50%未満」なら最終バーを捨てて前日で計算。
       取得途中の部分バー(6/18事故)やザラ場中実行での未確定足がclose/RS/SAR/21EMAに混入するのを構造的に防ぐ。"""
    C = W.get("Close")
    if C is None or getattr(C, "shape", (0,))[0] < 25:
        return W
    try:
        cnt = C.notna().sum(axis=1)
        med = float(cnt.iloc[-21:-1].median())
        if med > 0 and float(cnt.iloc[-1]) < 0.5 * med:
            sys.stderr.write("[guard] 最終バー %s は銘柄数 %d < 50%%×中央値 %.0f → 除外し前日で計算\n"
                             % (str(C.index[-1].date()), int(cnt.iloc[-1]), med))
            return {k: (v.iloc[:-1] if hasattr(v, "iloc") else v) for k, v in W.items()}
    except Exception as e:
        sys.stderr.write("[guard] last-bar check failed: %r\n" % repr(e)[:80])
    return W


def _swing_points(series, order=3):
    """Confirmed local swing highs/lows. The last `order` bars are excluded."""
    s = pd.Series(series).dropna()
    if len(s) < order * 2 + 5:
        return [], []
    a = s.to_numpy(dtype=float)
    highs, lows = [], []
    for i in range(order, len(a) - order):
        w = a[i - order:i + order + 1]
        if np.isfinite(a[i]) and a[i] >= np.nanmax(w):
            highs.append((i, float(a[i])))
        if np.isfinite(a[i]) and a[i] <= np.nanmin(w):
            lows.append((i, float(a[i])))
    return highs, lows


def _structure_pivot(close, low, high, v=None, lookback=140, order=3):
    """底打ち構造ピボット（構造のみ・フィボ不使用）。ローソク足ベースで計算する。
       ピボット安値＝Low、反発高値(P2)＝LL〜HL間のHigh最大値、上放れ判定＝Close。
       返り値 dict: ll, hl, p2, stage, hl_age, vdry, rh_dist, ll_px, hl_px, p2_px, hl_gain
       stage: 'base'(HL成立・反発高値未突破) / 'confirm'(Close≥反発高値=上放れ確認)"""
    try:
        ls = pd.Series(low).dropna()
        s = ls.tail(lookback)
        if len(s) < 35:
            return None
        a = s.to_numpy(dtype=float)                                   # Low（ピボット安値用）
        hs = pd.Series(high).reindex(ls.index).tail(lookback).to_numpy(dtype=float)   # High
        cse = pd.Series(close).reindex(ls.index).tail(lookback).to_numpy(dtype=float)  # Close
        va = pd.Series(v).reindex(ls.index).tail(lookback).to_numpy(dtype=float) if v is not None else None
        highs, lows = _swing_points(s, order=order)                   # Low系列からピボット安値
        if len(lows) < 2:
            return None
        cur = float(cse[-1])                                          # 現在の終値
        for k in range(len(lows) - 1, 0, -1):
            hl_i, hl_v = lows[k]        # HL候補（直近のピボット安値=Low）
            ll_i, ll_v = lows[k - 1]    # その前のピボット安値=Low（LL）
            if not (hl_v > ll_v * 1.01):
                continue
            if len(a) - 1 - hl_i > 45:
                continue
            seg = hs[ll_i + 1:hl_i]                                   # LL〜HL間の【High】最大値＝反発高値
            if len(seg) < 1:
                continue
            p2 = float(np.nanmax(seg))
            if not (p2 > hl_v * 1.02):
                continue
            pre = a[max(0, ll_i - 30):ll_i]                           # LLの前に実質的な下落
            if len(pre) < 8 or float(np.nanmax(pre)) / ll_v - 1 < 0.10:
                continue
            if hl_v > p2 * 0.99:
                continue
            if cur < hl_v * 0.985:                                    # 終値がHLを割っていない（構造維持）
                continue
            vdry = False
            if va is not None:
                try:
                    w = 3
                    vll = float(np.nanmean(va[max(0, ll_i - w):ll_i + w + 1]))
                    vhl = float(np.nanmean(va[max(0, hl_i - w):hl_i + w + 1]))
                    if np.isfinite(vll) and np.isfinite(vhl) and vll > 0:
                        vdry = bool(vhl < vll * 0.85)
                except Exception:
                    vdry = False
            crossed = bool(np.nanmax(cse[hl_i + 1:]) >= p2)   # HL以降にP2を一度でも突破したか
            if crossed and cur < p2:
                stage = 'retest'                              # 突破後にP2下へ押し戻し（＝底固めに逆戻りと誤認しない）
            elif crossed:
                stage = 'confirm'                             # 上放れ確認（P2上を維持）
            else:
                stage = 'base'                                # 底固め（P2未突破）
            return {'ll': float(ll_v), 'hl': float(hl_v), 'p2': p2, 'stage': stage,
                    'hl_age': int(len(a) - 1 - hl_i), 'vdry': vdry,
                    'rh_dist': float((cur / p2 - 1) * 100),
                    'll_px': float(ll_v), 'hl_px': float(hl_v), 'p2_px': p2,
                    'hl_gain': float((hl_v / ll_v - 1) * 100)}
        return None
    except Exception:
        return None


def _trend_change_confirmed(c, lookback=120, order=3):
    """Dow-style confirmation: reaction high -> higher low -> close crosses the reaction high."""
    s = pd.Series(c).dropna().tail(lookback)
    if len(s) < 35:
        return False, np.nan, np.nan
    highs, lows = _swing_points(s, order=order)
    if not highs or len(lows) < 2:
        return False, np.nan, np.nan
    a = s.to_numpy(dtype=float)
    cur, prev = float(a[-1]), float(a[-2])
    for hi_i, hi_v in reversed(highs):
        if len(a) - 1 - hi_i > 65:
            continue
        lb = [(i, v) for i, v in lows if i < hi_i]
        la = [(i, v) for i, v in lows if hi_i < i < len(a) - 1]
        if not lb or not la:
            continue
        l1_i, l1_v = lb[-1]
        l2_i, l2_v = la[-1]
        if l2_i <= hi_i or l2_i - hi_i > 40:
            continue
        # It must come after a real decline, not from an ordinary pause in an established uptrend.
        pre = a[max(0, l1_i - 30):l1_i]
        if len(pre) < 8 or float(np.nanmax(pre)) / l1_v - 1 < 0.10:
            continue
        if hi_v / l1_v - 1 < 0.06:
            continue
        # Higher low must be meaningful and remain below the reaction high.
        if l2_v < l1_v * 1.01 or l2_v > hi_v * 0.97:
            continue
        if prev <= hi_v * 1.003 and cur > hi_v * 1.003:
            return True, float(hi_v), float(l2_v)
    return False, np.nan, np.nan


def _recent_breakout_stats(c, h, l, v, lookback=25, pivot_lb=40):
    """Most recent close-through of a prior pivot and whether it came from a sound high-level base."""
    c = pd.Series(c).dropna(); h = pd.Series(h).reindex(c.index); l = pd.Series(l).reindex(c.index); v = pd.Series(v).reindex(c.index)
    n = len(c)
    empty = (None, np.nan, np.nan, np.nan, False, np.nan, np.nan)
    if n < max(105, pivot_lb + 65):
        return empty
    start = max(pivot_lb + 1, n - lookback)
    for i in range(n - 1, start - 1, -1):
        pwin = h.iloc[i - pivot_lb:i].dropna()
        lwin = l.iloc[i - pivot_lb:i].dropna()
        vv = v.iloc[max(0, i - 50):i].dropna()
        if pwin.empty or lwin.empty or len(vv) < 20 or not np.isfinite(v.iloc[i]):
            continue
        pivot = float(pwin.max())
        rv = float(v.iloc[i] / vv.mean()) if float(vv.mean()) > 0 else np.nan
        crossed = float(c.iloc[i]) > pivot and float(c.iloc[i - 1]) <= pivot
        if not crossed or not np.isfinite(rv) or rv < 1.20:
            continue
        depth = 1.0 - float(lwin.min()) / pivot if pivot > 0 else np.nan
        prior_i = i - pivot_lb
        pre_i = max(0, prior_i - 60)
        prior_run = float(c.iloc[prior_i] / c.iloc[pre_i] - 1) if prior_i > pre_i and float(c.iloc[pre_i]) > 0 else np.nan
        hh52 = h.iloc[max(0, i - 252):i].dropna()
        near52 = bool(not hh52.empty and pivot >= float(hh52.max()) * 0.90)
        day_rng = float(h.iloc[i] - l.iloc[i])
        close_pos = float((c.iloc[i] - l.iloc[i]) / day_rng) if day_rng > 0 else np.nan
        quality = bool(near52 and np.isfinite(depth) and 0.05 <= depth <= 0.35
                       and np.isfinite(prior_run) and prior_run >= 0.15
                       and np.isfinite(close_pos) and close_pos >= 0.60)
        days = n - 1 - i
        return int(days), pivot, float(c.iloc[-1] / pivot - 1), rv, quality, depth, prior_run
    return empty


def _cup_handle_metrics(c, h, l, v):
    """Conservative cup-with-handle approximation. It finds the left rim, bottom and a dry upper-half handle."""
    c = pd.Series(c).dropna(); h = pd.Series(h).reindex(c.index); l = pd.Series(l).reindex(c.index); v = pd.Series(v).reindex(c.index)
    out = dict(cup_ready=False, cup_breakout=False, cup_pivot=np.nan, cup_depth=np.nan,
               handle_depth=np.nan, handle_vdry=np.nan, cup_days=None)
    if len(c) < 90:
        return out
    n = min(190, len(c))
    hs = h.iloc[-n:-12].dropna()
    if len(hs) < 45:
        return out
    left_label = hs.idxmax(); left_i = c.index.get_loc(left_label)
    if left_i >= len(c) - 35:
        return out
    left = float(h.loc[left_label])
    mid_l = l.iloc[left_i + 1:-12].dropna()
    if mid_l.empty or left <= 0:
        return out
    bottom_label = mid_l.idxmin(); bottom_i = c.index.get_loc(bottom_label); bottom = float(l.loc[bottom_label])
    if bottom_i <= left_i:
        return out
    depth = 1.0 - bottom / left
    hwin = h.iloc[-12:-1].dropna(); lwin = l.iloc[-12:-1].dropna()
    if hwin.empty or lwin.empty:
        return out
    hhi, hlo = float(hwin.max()), float(lwin.min())
    hdepth = 1.0 - hlo / hhi if hhi > 0 else np.nan
    oldv = v.iloc[-62:-12].dropna(); handlev = v.iloc[-11:-1].dropna()
    hvdry = float(handlev.mean() / oldv.mean()) if len(oldv) >= 20 and len(handlev) >= 5 and float(oldv.mean()) > 0 else np.nan
    midpoint = bottom + (left - bottom) * 0.50
    near_rim = -0.06 <= float(c.iloc[-1] / left - 1) <= 0.035
    duration = len(c) - 1 - left_i
    base_ok = (30 <= duration <= 190 and 0.12 <= depth <= 0.38 and hdepth == hdepth and hdepth <= 0.12
               and hlo > midpoint and hhi >= left * 0.90 and hvdry == hvdry and hvdry <= 0.95)
    ready = bool(base_ok and near_rim)
    vv = v.iloc[-51:-1].dropna()
    rv = float(v.iloc[-1] / vv.mean()) if len(vv) >= 20 and float(vv.mean()) > 0 else np.nan
    breakout = bool(base_ok and float(c.iloc[-2]) <= left and float(c.iloc[-1]) > left and rv == rv and rv >= 1.35)
    out.update(cup_ready=ready, cup_breakout=breakout, cup_pivot=left, cup_depth=depth,
               handle_depth=hdepth, handle_vdry=hvdry, cup_days=int(duration))
    return out

def compute_metrics(W, order, s2i=None, macro=None):
    C, O, H, L, V = W["Close"], W["Open"], W["High"], W["Low"], W["Volume"]
    idx = C.index
    qqq_close = None
    try:
        _q = (macro or {}).get("QQQ")
        if _q is not None and "Close" in _q:
            qqq_close = _q["Close"].dropna()
    except Exception:
        qqq_close = None
    recs = []
    for t in order:
        if t not in C.columns:
            continue
        c = C[t].dropna()
        if len(c) < 60:
            continue
        o = O[t].reindex(c.index); h = H[t].reindex(c.index); l = L[t].reindex(c.index); v = V[t].reindex(c.index)
        close = c.iloc[-1]; prev = c.iloc[-2] if len(c) >= 2 else np.nan
        sma50  = c.rolling(50).mean().iloc[-1]  if len(c) >= 50  else np.nan
        sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else np.nan
        sma21  = c.iloc[-21:].mean()
        ema21  = ema(c, 21).iloc[-1]
        sma10  = c.rolling(10).mean().iloc[-1] if len(c) >= 10 else np.nan   # 撤退ライン候補②
        try:                                                                   # 撤退ライン候補①: 21EMA(安値)
            _ld = l.dropna()
            ema21l = float(ema(_ld, 21).iloc[-1]) if len(_ld) >= 21 else np.nan
        except Exception:
            ema21l = np.nan
        ret63  = close / c.iloc[-64] - 1 if len(c) >= 64 else np.nan
        ret63_d1 = c.iloc[-2] / c.iloc[-65] - 1 if len(c) >= 65 else np.nan     # 63d momentum as of 前営業日（Top10 IN/OUT用）
        ret126 = close / c.iloc[-127] - 1 if len(c) >= 127 else np.nan        # 126d(半年)モメンタム — 押し目質スコア用
        ret126_d1 = c.iloc[-2] / c.iloc[-128] - 1 if len(c) >= 128 else np.nan  # 126d momentum as of 前営業日（Top10 IN/OUT用）
        ret126_l5 = c.iloc[-6] / c.iloc[-132] - 1 if len(c) >= 132 else np.nan  # 126d momentum as of ~5営業日前（RS比較タブの順位変化用）
        ret126_l21 = c.iloc[-22] / c.iloc[-148] - 1 if len(c) >= 148 else np.nan # 126d momentum as of ~21営業日前（Top10 IN/OUT用）
        ret189 = close / c.iloc[-190] - 1 if len(c) >= 190 else np.nan         # 189d(≒9mo) momentum — PRIMARY 選定指標
        ret189_l5 = c.iloc[-6] / c.iloc[-195] - 1 if len(c) >= 195 else np.nan   # 189d momentum as of ~5営業日前 (RSランクΔ用)
        ret189_l1 = c.iloc[-2] / c.iloc[-191] - 1 if len(c) >= 191 else np.nan   # 189d momentum as of 前日 (新規参入・今日判定用)
        ret189_l21 = c.iloc[-22] / c.iloc[-211] - 1 if len(c) >= 211 else np.nan # 189d momentum as of ~21営業日前（Top10 IN/OUT用）
        ret189_l10 = c.iloc[-11] / c.iloc[-200] - 1 if len(c) >= 200 else np.nan  # ~10営業日前(2週前・RRG期間切替用)
        ret189_l15 = c.iloc[-16] / c.iloc[-205] - 1 if len(c) >= 205 else np.nan  # ~15営業日前(RRGの5日等間隔用)
        ret189_l25 = c.iloc[-26] / c.iloc[-215] - 1 if len(c) >= 215 else np.nan  # ~25営業日前(RRGの5日等間隔用)
        ret189_l20 = c.iloc[-21] / c.iloc[-210] - 1 if len(c) >= 210 else np.nan  # 189d momentum as of ~20営業日前 (F1脱落率用)
        ret189_l30 = c.iloc[-31] / c.iloc[-220] - 1 if len(c) >= 220 else np.nan  # ~30営業日前(先月RRGの勢い基準)
        ret63_l1 = c.iloc[-22] / c.iloc[-85] - 1 if len(c) >= 85 else np.nan   # 63d RS as of ~21d ago(1ヶ月前)
        ret63_l2 = c.iloc[-43] / c.iloc[-106] - 1 if len(c) >= 106 else np.nan # 63d RS as of ~42d ago
        ret63_w1 = c.iloc[-6] / c.iloc[-69] - 1 if len(c) >= 69 else np.nan    # 63d RS as of ~5d ago(先週)
        ret63_w2 = c.iloc[-11] / c.iloc[-74] - 1 if len(c) >= 74 else np.nan   # 63d RS as of ~10d ago(2週間前)
        ret21  = close / c.iloc[-22] - 1 if len(c) >= 22 else np.nan
        ret20  = close / c.iloc[-21] - 1 if len(c) >= 21 else np.nan
        ret5   = close / c.iloc[-6]  - 1 if len(c) >= 6  else np.nan
        ret1   = close / c.iloc[-2]  - 1 if len(c) >= 2  else np.nan   # 前日比（Moversタブ用）
        # --- ポケットピボット(10D) : Kacher/Morales ---
        #   上げ日 かつ 出来高が「直近10営業日の下げ日の最大出来高」を上回る。
        #   建設的な文脈のみ有効とするため 10日線上 かつ 50日線上 を条件に加える。
        #   pp_days = 直近10営業日で最後にPPが出てから何営業日前か（当日=0、無ければNone）。
        pp_days = None; pp_ratio = np.nan
        try:
            if len(c) >= 23 and v.notna().sum() >= 23:
                sma10s = c.rolling(10).mean()
                up = c > c.shift(1)
                for back in range(0, 10):                       # 0=当日, 1=前日 ...
                    i = -1 - back
                    if not bool(up.iloc[i]):
                        continue
                    # 終値は11本取る: 先頭は前日比の基準専用。→ 直前10営業日すべてを下落日判定できる
                    win_c = c.iloc[i - 11:i]                    # 11本
                    win_v = v.iloc[i - 10:i]                    # 対応する10本
                    dn_mask = (win_c.diff() < 0).to_numpy()[1:] # 10本ぶんの下落日フラグ
                    dn = win_v[dn_mask]
                    if len(dn) == 0 or not np.isfinite(v.iloc[i]):
                        continue
                    dn_max = float(dn.max())
                    if dn_max <= 0:
                        continue
                    ok_ctx = (np.isfinite(sma10s.iloc[i]) and c.iloc[i] > sma10s.iloc[i])
                    if len(c) >= 50:
                        ok_ctx = ok_ctx and c.iloc[i] > c.rolling(50).mean().iloc[i]
                    if float(v.iloc[i]) > dn_max and ok_ctx:
                        pp_days = back
                        pp_ratio = float(v.iloc[i]) / dn_max
                        break
        except Exception:
            pp_days = None; pp_ratio = np.nan
        lo20d  = float(c.iloc[-21:-1].min()) if len(c) >= 21 else np.nan   # 前日までの20日安値（当日除く）
        lo20_break = bool(close <= lo20d) if lo20d == lo20d else False     # 急落局面: 20日安値割れ
        lo10   = float(c.iloc[-10:].min()) if len(c) >= 10 else np.nan     # 10日安値（トレール用・終値ベース）
        lo10_prev = float(c.iloc[-20:-10].min()) if len(c) >= 20 else np.nan  # その前の10日安値（10日安値切上げ判定）
        ema21_10ago = float(ema(c, 21).iloc[-11]) if len(c) >= 32 else np.nan  # 10日前の21EMA（傾き用）
        # アンダーカット&ラリー: 直近3日で「その前の20日安値」を割り込み→今日その安値を回復＆上げ（振るい落とし反転）
        ucr = False
        if len(c) >= 24:
            lo20_prior = float(c.iloc[-24:-3].min()); recent_min = float(c.iloc[-3:].min())
            ucr = bool(recent_min < lo20_prior and close > lo20_prior and close > float(c.iloc[-2]))
        # 3タイトクローズ: 直近3終値の高安幅（ショートストローク=1%以内 / タイト=1.5%以内）
        tc3 = np.nan
        if len(c) >= 3:
            c3 = c.iloc[-3:]; tc3 = float(c3.max() / c3.min() - 1) if float(c3.min()) > 0 else np.nan
        # セリングクライマックス(投げ)= 直近5日にRVOL≥2.5 かつ 日足-5%超 → 売り手枯渇で解禁
        capit5 = False
        try:
            if len(c) >= 55:
                r1_5 = c.pct_change(fill_method=None).iloc[-5:]
                vr_5 = (v.reindex(c.index) / v.reindex(c.index).rolling(50).mean()).iloc[-5:]
                capit5 = bool(((r1_5 < -0.05) & (vr_5 >= 2.5)).any())
        except Exception:
            capit5 = False
        # --- structure / base / breakout metrics ---
        hi40 = float(h.iloc[-40:].max()) if len(h) >= 40 else float(h.max())
        pivot40 = float(h.iloc[-41:-1].max()) if len(h) >= 41 else np.nan   # current bar excluded
        pivot20 = float(h.iloc[-21:-1].max()) if len(h) >= 21 else np.nan
        pb = close / hi40 - 1 if hi40 and np.isfinite(hi40) else np.nan
        adr = float((h.iloc[-20:] / l.iloc[-20:] - 1).mean())
        maxabs1d = float(c.pct_change(fill_method=None).iloc[-200:].abs().max()) if len(c) >= 2 else np.nan
        # #4/#5: 52週高値/安値は「過去252営業日のHigh/Low最大最小」に統一。252本未満はNaN
        #   （上場浅い銘柄を52週高値扱いしない／終値と日中高値の定義混在も解消）
        if len(h) >= 252:
            hi52 = float(h.iloc[-252:].max()); lo52 = float(l.iloc[-252:].min())
            dist52 = close / hi52 - 1 if hi52 > 0 else np.nan
            hi52_prev = float(h.iloc[-253:-1].max()) if len(h) >= 253 else np.nan
            pos52 = (close - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else np.nan
        else:
            hi52 = np.nan; lo52 = np.nan; dist52 = np.nan; hi52_prev = np.nan; pos52 = np.nan
        vol = float(v.iloc[-1]) if np.isfinite(v.iloc[-1]) else np.nan
        vol20 = v.rolling(20).mean().iloc[-1] if len(v) >= 20 else np.nan
        vol50 = v.iloc[-50:].mean() if len(v) >= 50 else np.nan
        vol50_pre = v.iloc[-51:-1].mean() if len(v) >= 51 else np.nan
        rvol = float(vol / vol50) if np.isfinite(vol) and vol50 and np.isfinite(vol50) and vol50 > 0 else np.nan
        rvol_pre = float(vol / vol50_pre) if np.isfinite(vol) and vol50_pre and np.isfinite(vol50_pre) and vol50_pre > 0 else np.nan
        vol10 = v.iloc[-10:].mean() if len(v) >= 10 else np.nan
        vol10_pre = v.iloc[-11:-1].mean() if len(v) >= 11 else np.nan
        vdry = float(vol10 / vol50) if (vol50 and vol50 > 0 and np.isfinite(vol50) and np.isfinite(vol10)) else np.nan
        vdry_pre = float(vol10_pre / vol50_pre) if (vol50_pre and vol50_pre > 0 and np.isfinite(vol50_pre) and np.isfinite(vol10_pre)) else np.nan
        dvol = close * (vol20 if np.isfinite(vol20) else vol)
        # #1: 主要ラグ時点(5日/20日前)の適格判定用に、その時点の終値・20日$出来高・異常値を捕捉。
        #   過去RSをその過去時点のプールで順位付けするために使う（新規参入・F1・ローテの精度）。
        def _lag_pool_vals(k):
            if len(c) < k + 21 or len(v) < k + 20:
                return (np.nan, np.nan, np.nan)
            cl = float(c.iloc[-1 - k])
            v20l = float(v.iloc[-(k + 20):-k].mean())
            dv = cl * v20l if (np.isfinite(cl) and np.isfinite(v20l)) else np.nan
            mx = float(c.pct_change(fill_method=None).iloc[-(k + 200):-k].abs().max()) if len(c) >= k + 3 else np.nan
            return (cl, dv, mx)
        close_l1, dvol_l1, maxabs_l1 = _lag_pool_vals(1)
        close_l5, dvol_l5, maxabs_l5 = _lag_pool_vals(5)
        close_l10, dvol_l10, maxabs_l10 = _lag_pool_vals(10)
        close_l20, dvol_l20, maxabs_l20 = _lag_pool_vals(20)
        close_l21, dvol_l21, maxabs_l21 = _lag_pool_vals(21)
        close_l42, dvol_l42, maxabs_l42 = _lag_pool_vals(42)
        # Volume quality inside the base: up-day volume / down-day volume.
        uvdv20 = np.nan
        try:
            _rr = c.pct_change(fill_method=None).iloc[-21:-1]   # #16: 前日までの20日（ブレイク当日を含めない）
            _vv = v.reindex(_rr.index)
            _upv, _dnv = _vv[_rr > 0].mean(), _vv[_rr < 0].mean()
            if np.isfinite(_upv) and np.isfinite(_dnv) and _dnv > 0:
                uvdv20 = float(_upv / _dnv)
        except Exception:
            pass
        # Daily range contraction. Windows exclude the current bar, so breakout volume/range does not pollute the base.
        def _rng(n):
            if len(h) < n + 1:
                return np.nan
            hh = float(h.iloc[-n-1:-1].max()); ll = float(l.iloc[-n-1:-1].min())
            return hh / ll - 1 if ll > 0 else np.nan
        range40, range20, range10, range5 = _rng(40), _rng(20), _rng(10), _rng(5)
        contract_20_10 = bool(np.isfinite(range20) and np.isfinite(range10) and range10 <= range20 * 0.80)
        contract_10_5 = bool(np.isfinite(range10) and np.isfinite(range5) and range5 <= range10 * 0.80)
        contractions = int(contract_20_10) + int(contract_10_5)
        hl10 = bool(len(l) >= 21 and float(l.iloc[-11:-1].min()) > float(l.iloc[-21:-11].min()) * 1.002)
        hl5 = bool(len(l) >= 11 and float(l.iloc[-6:-1].min()) > float(l.iloc[-11:-6].min()) * 1.002)
        higher_lows = bool(hl10 and hl5)
        pivot_touches = 0
        if np.isfinite(pivot40) and len(h) >= 21:
            pivot_touches = int(((h.iloc[-21:-1] >= pivot40 * 0.985) & (h.iloc[-21:-1] <= pivot40 * 1.005)).sum())
        base_depth40 = (1.0 - float(l.iloc[-41:-1].min()) / pivot40) if len(l) >= 41 and np.isfinite(pivot40) and pivot40 > 0 else np.nan
        base_depth25 = (1.0 - float(l.iloc[-26:-1].min()) / float(h.iloc[-26:-1].max())) if len(l) >= 26 and float(h.iloc[-26:-1].max()) > 0 else np.nan
        pivot_dist = close / pivot40 - 1 if np.isfinite(pivot40) and pivot40 > 0 else np.nan
        # ATR contraction is more robust than Bollinger width alone.
        pc = c.shift(1)
        tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr20 = float(tr.iloc[-21:-1].mean()) if len(tr) >= 21 else np.nan
        atr5 = float(tr.iloc[-6:-1].mean()) if len(tr) >= 6 else np.nan
        atr_contract = atr5 / atr20 if np.isfinite(atr5) and np.isfinite(atr20) and atr20 > 0 else np.nan
        sma50_10ago = float(c.rolling(50).mean().iloc[-11]) if len(c) >= 61 else np.nan
        sma200_20ago = float(c.rolling(200).mean().iloc[-21]) if len(c) >= 220 else np.nan
        sma50_up = bool(np.isfinite(sma50_10ago) and np.isfinite(sma50) and sma50 > sma50_10ago)
        sma200_up = bool(np.isfinite(sma200_20ago) and np.isfinite(sma200) and sma200 >= sma200_20ago)
        stage2 = bool(np.isfinite(sma50) and np.isfinite(sma200) and close > sma50 > sma200 and sma50_up and sma200_up)
        wsx = weinstein_stage(c) or {}
        weekly_stage2 = bool(wsx.get("wst") == 2)
        day_range = float(h.iloc[-1] - l.iloc[-1]) if np.isfinite(h.iloc[-1]) and np.isfinite(l.iloc[-1]) else np.nan
        close_pos = float((close - l.iloc[-1]) / day_range) if np.isfinite(day_range) and day_range > 0 else np.nan
        breakout40 = bool(np.isfinite(pivot40) and prev <= pivot40 and close > pivot40)
        breakout52 = bool(np.isfinite(hi52_prev) and prev <= hi52_prev and close > hi52_prev)
        # A true continuation breakout needs a prior advance, a high-level base and constructive volume.
        prebase_ret = float(c.iloc[-41] / c.iloc[-101] - 1) if len(c) >= 101 and float(c.iloc[-101]) > 0 else np.nan
        near52 = bool(np.isfinite(dist52) and dist52 >= -0.10)
        cup = _cup_handle_metrics(c, h, l, v)
        shape_ok = bool(contractions >= 1 or higher_lows or pivot_touches >= 2 or cup.get("cup_breakout"))
        volume_ok = bool((np.isfinite(vdry_pre) and vdry_pre <= 1.00)
                         or (np.isfinite(uvdv20) and uvdv20 >= 1.05)
                         or (pp_days is not None and pp_days <= 10))
        true_breakout = bool(stage2 and (breakout40 or breakout52 or cup.get("cup_breakout"))
                             and np.isfinite(rvol_pre) and rvol_pre >= 1.40
                             and np.isfinite(close_pos) and close_pos >= 0.60
                             and np.isfinite(base_depth40) and 0.05 <= base_depth40 <= 0.35
                             and np.isfinite(prebase_ret) and prebase_ret >= 0.15
                             and near52 and shape_ok and volume_ok)
        triangle_ready = bool(stage2 and np.isfinite(pivot_dist) and -0.08 <= pivot_dist <= 0.01
                              and pivot_touches >= 2 and higher_lows
                              and np.isfinite(vdry_pre) and vdry_pre <= 0.95)
        trend_change, trend_pivot, trend_hl = _trend_change_confirmed(c)
        brk_days, brk_pivot, brk_ret, brk_rvol, brk_quality, brk_depth, brk_prior_run = _recent_breakout_stats(c, h, l, v)
        power20_4 = bool(brk_quality and brk_days is not None and brk_days <= 20
                         and np.isfinite(brk_ret) and brk_ret >= 0.20)
        breakout_failure = bool(brk_days is not None and brk_days <= 10 and np.isfinite(brk_ret) and brk_ret <= -0.03)
        # Relative-strength line versus QQQ. A new high before price often precedes a clean breakout.
        rsline_newhigh = False; rsline_dist = np.nan
        try:
            if qqq_close is not None:
                q = qqq_close.reindex(c.index).ffill()
                rel = (c / q).replace([np.inf, -np.inf], np.nan).dropna()
                if len(rel) >= 80:
                    rh = float(rel.iloc[-253:-1].max())
                    rsline_dist = float(rel.iloc[-1] / rh - 1) if rh > 0 else np.nan
                    rsline_newhigh = bool(np.isfinite(rsline_dist) and rsline_dist >= 0)
        except Exception:
            pass
        # bollinger width (20) + its 126d percentile
        m20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
        bbw_series = (4 * sd20) / m20
        bbw = bbw_series.iloc[-1]
        tailbw = bbw_series.dropna().iloc[-126:]
        bbw_pct = (tailbw < bbw).mean() * 100 if len(tailbw) >= 20 else np.nan
        sar_bull = weekly_sar_bullish(h, l, c)
        _w30 = w30_breakout(c, low=l, high=h)
        recs.append(dict(
            **_w30,
            t=t, close=close, prev=prev,
            pchg=(close/prev - 1) if prev and not np.isnan(prev) else np.nan,
            sma50=sma50, sma200=sma200, ema21=ema21, sma21=sma21, sma10=sma10, ema21l=ema21l,
            vs50=(close/sma50 - 1) if sma50 and not np.isnan(sma50) else np.nan,
            vs200=(close/sma200 - 1) if sma200 and not np.isnan(sma200) else np.nan,
            dma21=(close/sma21 - 1) if sma21 and not np.isnan(sma21) else np.nan,
            dma50=(close/sma50 - 1) if sma50 and not np.isnan(sma50) else np.nan,
            hi40=hi40, pivot40=pivot40, pivot20=pivot20, pivot_dist=pivot_dist,
            pb=pb, adr=adr, ret5=ret5, ret20=ret20, ret1=ret1, rvol=rvol, rvol_pre=rvol_pre,
            vdry=vdry, vdry_pre=vdry_pre, uvdv20=uvdv20, lo20_break=lo20_break, capit5=capit5,
            range40=range40, range20=range20, range10=range10, range5=range5,
            contractions=contractions, higher_lows=higher_lows, hl10=hl10, hl5=hl5,
            pivot_touches=pivot_touches, base_depth40=base_depth40, base_depth25=base_depth25,
            atr_contract=atr_contract, sma50_up=sma50_up, sma200_up=sma200_up, stage2=stage2, weekly_stage2=weekly_stage2,
            prebase_ret=prebase_ret, near52=near52, shape_ok=shape_ok, volume_ok=volume_ok,
            close_pos=close_pos, breakout40=breakout40, breakout52=breakout52, true_breakout=true_breakout,
            triangle_ready=triangle_ready, trend_change=trend_change, trend_pivot=trend_pivot, trend_hl=trend_hl,
            sp=_structure_pivot(c, L[t], H[t], V[t]),
            brk_days=brk_days, brk_pivot=brk_pivot, brk_ret=brk_ret, brk_rvol=brk_rvol,
            brk_quality=brk_quality, brk_depth=brk_depth, brk_prior_run=brk_prior_run,
            power20_4=power20_4, breakout_failure=breakout_failure,
            cup_ready=cup.get("cup_ready"), cup_breakout=cup.get("cup_breakout"), cup_pivot=cup.get("cup_pivot"),
            cup_depth=cup.get("cup_depth"), handle_depth=cup.get("handle_depth"), handle_vdry=cup.get("handle_vdry"), cup_days=cup.get("cup_days"),
            rsline_newhigh=rsline_newhigh, rsline_dist=rsline_dist,
            maxabs1d=maxabs1d, lo10=lo10, lo10_prev=lo10_prev, ema21_10ago=ema21_10ago,
            ret126=ret126, ret126_d1=ret126_d1, ret126_l5=ret126_l5, ret126_l21=ret126_l21, ucr=ucr, tc3=tc3,
            ret63=ret63, ret63_d1=ret63_d1, ret189=ret189, ret189_l1=ret189_l1, ret189_l5=ret189_l5, ret189_l21=ret189_l21, ret189_l10=ret189_l10, ret189_l15=ret189_l15, ret189_l20=ret189_l20, ret189_l25=ret189_l25, ret189_l30=ret189_l30, ret21=ret21, hi52=hi52, dist52=dist52, pos52=pos52,
            pp_days=pp_days, pp_ratio=pp_ratio,
            ret63_l1=ret63_l1, ret63_l2=ret63_l2, ret63_w1=ret63_w1, ret63_w2=ret63_w2,
            vol=vol, vol20=vol20, dvol=dvol,
            close_l1=close_l1, dvol_l1=dvol_l1, maxabs_l1=maxabs_l1,
            close_l5=close_l5, dvol_l5=dvol_l5, maxabs_l5=maxabs_l5,
            close_l10=close_l10, dvol_l10=dvol_l10, maxabs_l10=maxabs_l10,
            close_l20=close_l20, dvol_l20=dvol_l20, maxabs_l20=maxabs_l20,
            close_l21=close_l21, dvol_l21=dvol_l21, maxabs_l21=maxabs_l21,
            close_l42=close_l42, dvol_l42=dvol_l42, maxabs_l42=maxabs_l42,
            volx=(vol/vol20) if vol20 and not np.isnan(vol20) and vol20 > 0 else np.nan,
            bbw=bbw, bbw_pct=bbw_pct, sar_bull=sar_bull,
            wst=wsx.get("wst"), wstw=wsx.get("wstw"),
            wsb=wsx.get("wsb"), wsbf=(1 if wsx.get("wsbf") else 0),
        ))
    df = pd.DataFrame(recs).set_index("t")
    # A1 分割アーティファクト・ガード: 直近200日の単日変化率>150%はスプリット/データ異常のゴースト
    #   （CHRD +80,376% 等）。RSランキングから除外＝RS=NaNで選定・リーダー判定から自然脱落。
    df["split_suspect"] = (df["maxabs1d"] > 1.50).fillna(False)
    # A2 プール内RS: RSは「非サスペクト × 株価≥$5 × 20日$出来高≥$10M」内の順位で付ける。
    #   RS85 の意味が微小株で希釈されるのを解消＝リーダー判定/選定の母集団を統一（バグ⑤も解消）。
    #   プール外は RS=NaN → 選定・リーダーから自然脱落。順位の相対順は保たれるので採用12の並びは不変。
    _pool = (~df["split_suspect"]) & (df["close"] >= 5) & (df["dvol"] >= DVOL_FLOOR)
    df["rs_pool"] = _pool
    def _rk(col):                                         # トレーダブル母集団内でのみ百分位付け
        return df[col].where(_pool).rank(pct=True) * 100
    # #1: 過去RSは「その過去時点のプール」で順位付け（現在プール流用を解消）。
    #   主要ラグ(5日/20日)のプールを当時の終値・$出来高・異常値から構成。列が無い銘柄はNaN=自然脱落。
    def _pool_lag(clc, dvc, mxc):
        if clc in df and dvc in df and mxc in df:
            return (df[mxc].fillna(0) <= 1.50) & (df[clc] >= 5) & (df[dvc] >= DVOL_FLOOR)
        return _pool
    _pool_l1 = _pool_lag("close_l1", "dvol_l1", "maxabs_l1")
    _pool_l5 = _pool_lag("close_l5", "dvol_l5", "maxabs_l5")
    _pool_l10 = _pool_lag("close_l10", "dvol_l10", "maxabs_l10")
    _pool_l20 = _pool_lag("close_l20", "dvol_l20", "maxabs_l20")
    _pool_l21 = _pool_lag("close_l21", "dvol_l21", "maxabs_l21")
    _pool_l42 = _pool_lag("close_l42", "dvol_l42", "maxabs_l42")
    def _rk_at(col, pool):
        return (df[col].where(pool).rank(pct=True) * 100) if col in df else np.nan
    def _r_at(col, pool):                                 # 0-1ランク（concat用）
        return df[col].where(pool).rank(pct=True) if col in df else pd.Series(np.nan, index=df.index)
    # RS percentile from 63d return (0-100), instantaneous for monitoring + 短期スキャナー
    df["rs"] = _rk("ret63")
    # 189d RS percentile (0-100) — PRIMARY selection metric (研究で確定: 9ヶ月モメンタムが最適)
    df["rs189"] = _rk("ret189")
    df["rs189_l20"] = _rk_at("ret189_l20", _pool_l20)   # 20d前の189RS(F1)＝当時プール
    df["rs189_l5"] = _rk_at("ret189_l5", _pool_l5)       # 5d前の189RS(新規参入)＝当時プール
    df["rs189_l1"] = _rk_at("ret189_l1", _pool_l1)       # 1d前の189RS(新規参入)＝当時プール
    # RSランクΔ: 約1週間前の189日RSランクとの差（ローテーション初動の検知・表示のみ）＝当時プール
    df["rs189_d"] = df["rs189"] - _rk_at("ret189_l5", _pool_l5)
    # smoothed 63d RS = mean of 3 RS-percentile snapshots (今/~21d前/~42d前) — 参考表示のみ(選定には未使用)
    r0 = df["ret63"].where(_pool).rank(pct=True)
    df["rs63"] = r0 * 100          # 63日RS百分位（単一スナップ）— 勢い落ち除外の基準
    r1 = _r_at("ret63_l1", _pool_l21)      # ~21d前＝当時プール
    r2 = _r_at("ret63_l2", _pool_l42)      # ~42d前＝当時プール（#7）
    _rsm = pd.concat([r0, r1, r2], axis=1)
    df["rs_smooth_n"] = _rsm.notna().sum(axis=1)
    df["rs_smooth"] = (_rsm.mean(axis=1) * 100).where(df["rs_smooth_n"] == 3)
    df["rs_l1"] = r1 * 100          # 約21日前(1ヶ月前)の63日RSランク
    df["rs_l2"] = r2 * 100          # 約42日前(2ヶ月前)の63日RSランク（DD入口のリーダー保存用）
    df["rs63_d1"] = _rk_at("ret63_d1", _pool_l1)                        # 前営業日の63日RS（Top10 IN/OUT用）＝当時プール
    df["rs_w1"] = _rk_at("ret63_w1", _pool_l5) if "ret63_w1" in df else df["rs_l1"]  # 先週(~5d前)＝当時プール
    df["rs_w2"] = _rk_at("ret63_w2", _pool_l10) if "ret63_w2" in df else df["rs_l1"] # 2週間前(~10d前)＝当時プール
    df["rs63_m1"] = df["rs_l1"]                                           # 約21営業日前の63日RS（Top10 IN/OUT用）
    df["rs21"] = _rk("ret20") if "ret20" in df else df["rs"]            # 21日RS（短期の勢い）
    df["rs126"] = _rk("ret126") if "ret126" in df else df["rs"]         # 126日RS（半年）— 押し目質スコア用
    df["rs126_d1"] = _rk_at("ret126_d1", _pool_l1)                      # 前営業日の126日RS（Top10 IN/OUT用）＝当時プール
    df["rs126_l5"] = _rk_at("ret126_l5", _pool_l5)                      # 約5営業日前の126日RS＝当時プール
    df["rs126_m1"] = _rk_at("ret126_l21", _pool_l21)                    # 約21営業日前の126日RS（Top10 IN/OUT用）＝当時プール
    df["rs189_m1"] = _rk_at("ret189_l21", _pool_l21)                    # 約21営業日前の189日RS（Top10 IN/OUT用）＝当時プール
    df["rs126_d"] = df["rs126"] - df["rs126_l5"]                       # 126日RSの約1週間変化
    df["rs63_d"] = df["rs"] - df["rs_w1"]                               # 63日RSの1週間変化
    # Technical structure quality. These scores rank the technical tab only; portfolio selection remains RS189-based.
    _b = lambda col: df[col].fillna(False).astype(bool) if col in df else pd.Series(False, index=df.index)
    _num = lambda col: pd.to_numeric(df[col], errors="coerce") if col in df else pd.Series(np.nan, index=df.index)
    _stage = _b("stage2")
    _contr = _num("contractions").fillna(0).clip(0, 2)
    _pdist = _num("pivot_dist")
    _vd = _num("vdry_pre")
    _atr = _num("atr_contract")
    _bd = _num("base_depth40")
    _cp = _num("close_pos")
    _rv = _num("rvol_pre")
    df["vcp_score"] = (
        _stage.astype(int) * 15
        + _contr * 10
        + _b("higher_lows").astype(int) * 15
        + (_vd <= 0.85).fillna(False).astype(int) * 10
        + (_atr <= 0.75).fillna(False).astype(int) * 10
        + ((_pdist >= -0.08) & (_pdist <= 0.01)).fillna(False).astype(int) * 10
        + (df["rs189"] >= 85).fillna(False).astype(int) * 5
        + _b("rsline_newhigh").astype(int) * 5
        + (_num("uvdv20") >= 1.05).fillna(False).astype(int) * 5
        + _b("weekly_stage2").astype(int) * 5
    ).clip(0, 100)
    _recent_break = (_num("brk_days").notna() & (_num("brk_days") <= 20)).fillna(False)
    df["vcp_ready"] = (_stage & (df["vcp_score"] >= 65)
                       & (_pdist >= -0.12) & (_pdist <= 0.02)
                       & (_bd >= 0.05) & (_bd <= 0.35)
                       & (~_recent_break) & (~_b("breakout_failure")) & (~_b("cup_breakout"))).fillna(False)
    df["breakout_score"] = (
        _stage.astype(int) * 15
        + _b("weekly_stage2").astype(int) * 5
        + (df["rs189"] >= 90).fillna(False).astype(int) * 15
        + (_rv >= 1.40).fillna(False).astype(int) * 20
        + (_cp >= 0.60).fillna(False).astype(int) * 10
        + ((_bd >= 0.05) & (_bd <= 0.35)).fillna(False).astype(int) * 10
        + (_num("prebase_ret") >= 0.15).fillna(False).astype(int) * 10
        + _b("near52").astype(int) * 5
        + _b("shape_ok").astype(int) * 5
        + _b("rsline_newhigh").astype(int) * 5
    ).clip(0, 100)
    df["true_breakout"] = (_b("true_breakout") & (df["breakout_score"] >= 70)).fillna(False)
    # 業種内相対: 銘柄の63日リターン − 自業種(適格銘柄)の63日リターン平均。
    # <−0.20(自業種より20%以上出遅れ)=「出遅れ株」→選定除外(検証: 図の相場サイクル理論に整合・検問5/6通過)。
    df["sec_rel"] = np.nan
    try:
        if s2i:
            elig = (df["sma50"] > df["sma200"]) & (df["dvol"] >= DVOL_FLOOR) & (df["close"] >= 5)
            ind = pd.Series({t: s2i.get(t, "NA") for t in df.index}).reindex(df.index)
            r63v = df["ret63"].where(elig)
            sec_med = r63v.groupby(ind).transform("median")   # #19: 平均は急騰株に引かれるため中央値
            df["sec_rel"] = (1 + df["ret63"]) / (1 + sec_med) - 1   # #19: 単純差でなく比率ベースの相対リターン
    except Exception as e:
        print("[warn] sec_rel calc failed:", e)
        df["sec_rel"] = np.nan
    return df, idx[-1]

# ----------------------------------------------------------------------------- market-cap tiers
def cap_tier(mc):
    """Return (key, label, rank). <1B=極小(板薄), 1-3B=小型, 3-10B=中型, 10-100B=大型, >100B=超大型."""
    if mc is None or (isinstance(mc, float) and np.isnan(mc)) or mc <= 0:
        return ("none", "—", -1)
    b = mc / 1e9
    if b < 1:   return ("micro", "極小", 0)
    if b < 3:   return ("small", "小型", 1)
    if b < 10:  return ("mid",   "中型", 2)
    if b < 100: return ("large", "大型", 3)
    return ("mega", "超大型", 4)

def fmt_cap(mc):
    if mc is None or (isinstance(mc, float) and np.isnan(mc)) or mc <= 0:
        return "—"
    b = mc / 1e9
    if b >= 1000: return f"${b/1000:.2f}T"
    if b >= 1:    return f"${b:.1f}B"
    return f"${mc/1e6:.0f}M"

def _valid_mcap(v):
    try:
        return v is not None and np.isfinite(float(v)) and float(v) > 0
    except Exception:
        return False

def _mcap_value(rec):
    """mktcapレコード(旧: 数値 / 新: {value,checked_at,status})から時価総額の数値を取り出す。"""
    if isinstance(rec, dict):
        return rec.get("value")
    return rec

MCAP_TTL_DAYS = 30   # 有効値でもこの日数を超えたら再取得（増資/自社株買い/株式数変更を反映・#7）

def _mcap_needs_fetch(rec, today):
    v = _mcap_value(rec)
    if not _valid_mcap(v):
        return True                                  # null/欠損/不正
    if isinstance(rec, dict):
        ca = rec.get("checked_at")
        if not ca:
            return True                              # 取得日不明→段階的に更新
        try:
            return (today - pd.Timestamp(ca)).days >= MCAP_TTL_DAYS
        except Exception:
            return True
    return True                                       # 旧形式の素の数値=取得日不明→TTL移行のため再取得

def load_market_caps(valid, live, strict=False):
    """Read committed mktcap.json → {ticker: marketCap値}. In live mode, refresh
    missing/invalid/期限切れ entries (bounded per run) and write back. strict=True: 明示env以外読まない。
    保存は新形式 {value, checked_at, status}。旧形式(素の数値)も読める。返り値は数値のみ(消費側不変)。"""
    import json
    env_p = os.environ.get("V38_MKTCAP_JSON")
    if strict:
        paths = [env_p] if env_p else []
    else:
        paths = [env_p, os.path.join(os.path.dirname(CACHE), "mktcap.json"),
                 "/mnt/project/mktcap.json", "mktcap.json"]
    path = next((p for p in paths if p and os.path.exists(p)), None)
    cache = {}
    if path:
        try: cache = json.load(open(path))
        except Exception: cache = {}
        if not isinstance(cache, dict):
            # #6 mktcapは再取得可能。strictで明示fixtureが不正なら停止、通常運用は警告して{}へ。
            if strict:
                raise SystemExit(f"[FATAL] mktcap fixture must be a dict: {path}")
            sys.stderr.write(f"[mktcap] {path} is not a dict; resetting to empty\n")
            cache = {}
    if live:
        try:
            import yfinance as yf, time
            _today = pd.Timestamp.today().normalize()
            _tday = str(_today.date())
            todo = [t for t in valid if _mcap_needs_fetch(cache.get(t), _today)][:400]   # 欠損/不正/TTL経過を再取得（#3/#7）
            t0 = time.time()
            for t in todo:
                if time.time() - t0 > 240:
                    break
                try:
                    mc = yf.Ticker(t).info.get("marketCap")
                    if isinstance(mc, (int, float)) and mc == mc and mc > 0:
                        cache[t] = {"value": float(mc), "checked_at": _tday, "status": "ok"}
                    else:
                        cache[t] = {"value": None, "checked_at": _tday, "status": "no_value"}
                except Exception:
                    cache[t] = {"value": None, "checked_at": _tday, "status": "error"}
            outp = path or os.environ.get("V38_MKTCAP_JSON") or os.path.join(os.path.dirname(CACHE), "mktcap.json")
            _defer_cache_write(outp, cache)   # #6 保留→selftest後にflush
        except Exception:
            pass
    return {t: _mcap_value(cache.get(t)) for t in valid}

# ----------------------------------------------------------------------------- Market-status engine (C)
# Market Health v2: highly correlated raw indicators are compressed inside four pillars.
# The score measures trend health, participation, volatility stress and credit conditions.
STATUS_DEF = [
    # key, pillar weight, lo, hi, group
    ("trend",   30, 0.0, 1.0, "market"),
    ("breadth", 30, 0.0, 1.0, "market"),
    ("risk",     20, 0.0, 1.0, "market"),
    ("credit",   20, 0.0, 1.0, "market"),
]
# Pillar weights: trend 30 / breadth 30 / risk 20 / credit 20 = 100


def clamp01(x):
    return np.clip(x, 0.0, 1.0)


VOL_WIN, VOL_MINP = 252, 120


def _series_blend(parts, min_cov=0.0):
    """Row-wise weighted mean that renormalizes over the components available that day.
       #13: min_cov>0 のとき、その日の有効ウェイト比が min_cov 未満なら NaN
       （構成要素の欠損で値が跳ねる／別物になるのを防ぐ）。"""
    num = None
    den = None
    total_w = 0.0
    for ser, weight in parts:
        total_w += float(weight)
        if ser is None:
            continue
        ser = pd.Series(ser, dtype=float)
        valid = ser.notna().astype(float) * float(weight)
        term = ser.fillna(0.0) * float(weight)
        num = term if num is None else num.add(term, fill_value=0.0)
        den = valid if den is None else den.add(valid, fill_value=0.0)
    if num is None:
        return pd.Series(dtype=float)
    out = num / den.replace(0.0, np.nan)
    if min_cov > 0 and total_w > 0 and den is not None:
        out = out.where((den / total_w) >= min_cov)
    return out


def _linear_score(s, lo, hi):
    s = pd.Series(s, dtype=float)
    return clamp01((s - lo) / (hi - lo))


def _vol_percentile_score(s):
    """Low trailing-percentile volatility = 1, high-percentile volatility = 0."""
    s = pd.Series(s, dtype=float)
    q_bear = s.rolling(VOL_WIN, min_periods=VOL_MINP).quantile(0.85)
    q_bull = s.rolling(VOL_WIN, min_periods=VOL_MINP).quantile(0.15)
    z = (s - q_bear) / (q_bull - q_bear)
    return clamp01(z)


def _universe_breadth(W, index):
    """Daily breadth from the actual stock universe: above 50/200MA and 20-day advance ratio."""
    out = pd.DataFrame(index=index)
    if not W or "Close" not in W:
        return out
    try:
        C = W["Close"].sort_index().reindex(index)
        if C.empty or C.shape[1] < 5:
            return out
        nobs = C.notna().sum(axis=1)
        floor = max(5, min(30, int(max(1, C.shape[1]) * 0.20)))

        ma50 = C.rolling(50, min_periods=50).mean()
        v50 = ma50.notna().sum(axis=1)
        pa50 = (C.gt(ma50).sum(axis=1) / v50.replace(0, np.nan) * 100.0)
        out["uni_pa50"] = pa50.where(v50 >= np.maximum(floor, nobs * 0.45))

        ma200 = C.rolling(200, min_periods=200).mean()
        v200 = ma200.notna().sum(axis=1)
        pa200 = (C.gt(ma200).sum(axis=1) / v200.replace(0, np.nan) * 100.0)
        out["uni_pa200"] = pa200.where(v200 >= np.maximum(floor, nobs * 0.45))

        rets = C.pct_change(fill_method=None)
        den = rets.notna().sum(axis=1)
        adv = rets.gt(0).sum(axis=1) / den.replace(0, np.nan) * 100.0
        out["uni_ad20"] = adv.rolling(20, min_periods=10).mean()
    except Exception as e:
        print("[warn] universe breadth for market score failed:", e)
    return out


def mri_frame(macro, W=None):
    cl = lambda k: macro[k]["Close"] if k in macro else None
    base = pd.DataFrame({k: cl(k) for k in ["QQQ", "QQQE", "SPY", "HYG", "LQD", "RSP", "IWM"] if cl(k) is not None})
    if cl("^VIX") is not None:   base["VIX"] = cl("^VIX")
    if cl("^VIX3M") is not None: base["VIX3M"] = cl("^VIX3M")
    if cl("^VVIX") is not None:  base["VVIX"] = cl("^VVIX")
    base = base.sort_index().ffill().dropna(subset=[x for x in ("QQQ", "SPY", "HYG", "LQD", "RSP", "IWM", "VIX") if x in base.columns])
    if base.empty or "QQQ" not in base or "SPY" not in base:
        raise ValueError("market score needs QQQ/SPY history")

    qqq, spy = base["QQQ"], base["SPY"]
    hyglqd = base["HYG"] / base["LQD"] if "HYG" in base and "LQD" in base else pd.Series(np.nan, index=base.index)
    rspspy = base["RSP"] / base["SPY"] if "RSP" in base else pd.Series(np.nan, index=base.index)
    iwmspy = base["IWM"] / base["SPY"] if "IWM" in base else pd.Series(np.nan, index=base.index)

    vals = pd.DataFrame(index=base.index)
    vals["qqq_50"] = qqq / qqq.rolling(50).mean() - 1
    vals["qqq_200"] = qqq / qqq.rolling(200).mean() - 1
    vals["spy_50"] = spy / spy.rolling(50).mean() - 1
    vals["spy_200"] = spy / spy.rolling(200).mean() - 1
    vals["vix"] = base["VIX"] if "VIX" in base else np.nan
    vals["vix_ratio"] = (base["VIX"] / base["VIX3M"]) if "VIX3M" in base else np.nan
    vals["vvix"] = base["VVIX"] if "VVIX" in base else np.nan
    vals["hyglqd_20"] = hyglqd / hyglqd.rolling(20).mean()
    vals["hyglqd_5d"] = hyglqd / hyglqd.shift(5) - 1
    vals["rsp_spy_20"] = rspspy / rspspy.rolling(20).mean()
    vals["iwm_spy_20"] = iwmspy / iwmspy.rolling(20).mean()

    if "QQQE" in base:
        qqqe = base["QQQE"]
        vals["qqqe_50"] = qqqe / qqqe.rolling(50).mean() - 1
        qqqeqqq = qqqe / base["QQQ"]
        vals["qqqe_qqq_20"] = qqqeqqq / qqqeqqq.rolling(20).mean()
    else:
        vals["qqqe_50"] = np.nan
        vals["qqqe_qqq_20"] = np.nan
    if "RSP" in base:
        rsp = base["RSP"]
        vals["rsp_50"] = rsp / rsp.rolling(50).mean() - 1
        vals["rsp_200"] = rsp / rsp.rolling(200).mean() - 1
    else:
        vals["rsp_50"] = np.nan
        vals["rsp_200"] = np.nan

    ub = _universe_breadth(W, vals.index)
    for col in ("uni_pa50", "uni_pa200", "uni_ad20"):
        vals[col] = ub[col] if col in ub else np.nan

    # 1) Trend: compress cap-weighted and equal-weighted trends before applying the pillar weight.
    cap_trend = _series_blend([
        (_linear_score(vals["qqq_50"], -0.03, 0.10), 0.40),
        (_linear_score(vals["qqq_200"], -0.05, 0.10), 0.35),
        (_linear_score(vals["spy_200"], -0.05, 0.10), 0.25),
    ], min_cov=0.5)
    broad_trend = _series_blend([
        (_linear_score(vals["rsp_50"], -0.03, 0.07), 0.40),
        (_linear_score(vals["rsp_200"], -0.05, 0.10), 0.35),
        (_linear_score(vals["qqqe_50"], -0.03, 0.09), 0.25),
    ], min_cov=0.5)
    vals["pillar_trend"] = _series_blend([(cap_trend, 0.50), (broad_trend, 0.50)])

    # 2) Breadth: use the actual stock universe first, ETF relative breadth second.
    uni_breadth = _series_blend([
        (_linear_score(vals["uni_pa50"], 30.0, 75.0), 0.40),
        (_linear_score(vals["uni_pa200"], 30.0, 75.0), 0.40),
        (_linear_score(vals["uni_ad20"], 45.0, 55.0), 0.20),
    ], min_cov=0.5)
    relative_breadth = _series_blend([
        (_linear_score(vals["rsp_spy_20"], 0.98, 1.02), 1.0),
        (_linear_score(vals["qqqe_qqq_20"], 0.98, 1.02), 1.0),
        (_linear_score(vals["iwm_spy_20"], 0.98, 1.02), 1.0),
    ])
    vals["pillar_breadth"] = _series_blend([(uni_breadth, 0.70), (relative_breadth, 0.30)])

    # 3) Risk: volatility level, curve and vol-of-vol stay inside one capped pillar.
    vals["pillar_risk"] = _series_blend([
        (_vol_percentile_score(vals["vix"]), 0.45),
        (_linear_score(vals["vix_ratio"], 1.05, 0.95), 0.35),
        (_vol_percentile_score(vals["vvix"]), 0.20),
    ], min_cov=0.5)

    # 4) Credit: structural level plus short-term direction.
    vals["pillar_credit"] = _series_blend([
        (_linear_score(vals["hyglqd_20"], 0.98, 1.02), 0.65),
        (_linear_score(vals["hyglqd_5d"], -0.02, 0.02), 0.35),
    ])

    pillar_map = {
        "trend": vals["pillar_trend"],
        "breadth": vals["pillar_breadth"],
        "risk": vals["pillar_risk"],
        "credit": vals["pillar_credit"],
    }
    weights = {k: w for k, w, *_ in STATUS_DEF}
    active, dropped = [], []
    parts = []
    for key, w, lo, hi, grp in STATUS_DEF:
        ser = pillar_map[key]
        if ser.dropna().empty:
            dropped.append(key)
        else:
            active.append((key, w, lo, hi, grp))
            parts.append((ser, w))
    mri = (_series_blend(parts) * 100.0).dropna()
    if mri.empty:
        raise ValueError("market score has no valid observations")

    breakdown = []
    for key, w, lo, hi, grp in active:
        sc = pillar_map[key].reindex(mri.index).iloc[-1]
        sc01 = float(sc) if pd.notna(sc) else 0.5
        breakdown.append(dict(key=key, w=w, group=grp, raw=sc01 * 100.0,
                              pts=w * sc01, ptsmax=w, frac=sc01))
    return mri, breakdown, dropped, active, vals


def mri_auxiliary(mri, vals, metrics):
    cur = float(mri.iloc[-1])
    ma10 = mri.rolling(10).mean()
    slope_dir = "→"
    if len(ma10.dropna()) >= 3:
        d = ma10.iloc[-1] - ma10.iloc[-3]
        slope_dir = "↑" if d > 0.4 else ("↓" if d < -0.4 else "→")
    last = vals.iloc[-1]

    # One warning per pillar. This avoids one market event inflating the warning count through correlated inputs.
    bvals = [
        ("トレンド", last.get("pillar_trend", np.nan) < 0.40),
        ("広がり", last.get("pillar_breadth", np.nan) < 0.40),
        ("ボラ", last.get("pillar_risk", np.nan) < 0.40),
        ("信用", last.get("pillar_credit", np.nan) < 0.40),
    ]
    bear_flags = [(lab, bool(v == True)) for lab, v in bvals]
    bear_n = int(sum(1 for _, v in bear_flags if v))

    hl = float(mri.tail(3).mean()) if len(mri) >= 1 else cur
    hi20 = mri.iloc[-20:].max() if len(mri) >= 5 else cur
    drop = hi20 - cur
    if drop < 3:    peak = "通常"
    elif drop < 7:  peak = "注意"
    elif drop < 12: peak = "減速"
    else:           peak = "深押し"
    return dict(cur=cur, hl=hl, slope=slope_dir, bear_n=bear_n, bear_flags=bear_flags,
                peak=peak, drop=drop, hi20=hi20)


def mri_band(v):
    if v >= 70: return ("強気", "bull")
    if v >= 55: return ("やや強気", "bull")
    if v >= 40: return ("中立", "neu")
    if v >= 25: return ("弱含み", "weak")
    return ("弱気", "bear")

# ----------------------------------------------------------------------------- NQ-SAR signal (leverage sleeve; logic hidden, only color+判定 shown)
# Authoritative source = sar_state.txt (committed by the TradingView->Pipedream
# workflow after every completed NQ session; color flips may also trigger an immediate update). Falls back to the OniMine state embedded
# in a local NQ export, then to a safe default.
# 推奨フォーマット: 2026-07-10,Blue  または {"asof":"2026-07-10","color":"Blue"}
SAR_STATE_PATH = os.environ.get("V38_SAR_STATE", "sar_state.txt")
NQ_EXPORT_CANDIDATES = [
    os.environ.get("V38_NQ_EXPORT", ""),
    "/mnt/project/CME_MINI_DL_NQ1___1D_3.csv",
    "/mnt/project/CME_MINI_DL_NQ1___1D.csv",
]
# color -> (color label, trend judgment, sub descriptor, css class) — public-facing, logic hidden
# Severity (strong bull -> strong bear): Blue > Green > Yellow > Red
#   2軸FSM: close vs PSAR(0.02/0.02/0.08) = 強気/弱気側。緑黄=移行・青赤=確定。
#   昇格(緑→青/黄→赤)= RSI閾値 + SAR転換から2バー以上 + 反スパイク。降格= 21EMA即時。
SAR_JUDGMENT = {
    "Blue":   ("Blue",   "強い上昇", "継続",     "sar-blue"),
    "Green":  ("Green",  "上昇(中位)", "中立",     "sar-green"),
    "Yellow": ("Yellow", "弱含み",   "警戒",     "sar-yellow"),
    "Red":    ("Red",    "下落",     "回避",     "sar-red"),
}
_SAR_ID2COLOR = {1: "Blue", 2: "Yellow", 3: "Red", 4: "Green"}

def _norm_color(s):
    if not s:
        return None
    s = str(s).strip()
    s = s[:1].upper() + s[1:].lower()
    return s if s in SAR_JUDGMENT else None

def _nq_stable_color_series(df, scol_name, ts, cut):
    """NQ export DFから色系列を返す。仕様: ts昇順に並べ、同一時刻はCSV上の最終行を正式値とする(keep=last)。
       日付の降順/昇順には依存しないが、同一時刻に別の状態IDが競合する場合は元ファイルの行順を優先する
       （完全な行順非依存にするには別途どの状態を優先するかの正式ルールが必要）。競合があれば警告する。"""
    tmp = pd.DataFrame({"ts": ts, "sid": pd.to_numeric(df[scol_name], errors="coerce"),
                        "_row": np.arange(len(df))})
    tmp = tmp.dropna(subset=["ts", "sid"])
    if cut is not None:
        tmp = tmp.loc[tmp["ts"] <= cut]
    try:
        if tmp.groupby("ts")["sid"].nunique().gt(1).any():
            sys.stderr.write("[nq] same timestamp has conflicting state IDs; using last row per timestamp\n")
    except Exception:
        pass
    tmp = tmp.sort_values(["ts", "_row"], kind="mergesort").drop_duplicates("ts", keep="last")
    return [c for c in (_SAR_ID2COLOR.get(int(v)) for v in tmp["sid"]) if c]

def _nq_export_paths(strict=False):
    """NQ export CSVの探索パス。strict=True（offline selftest）はV38_NQ_EXPORT明示時のみ。"""
    env_p = os.environ.get("V38_NQ_EXPORT", "")
    if strict:
        return [env_p] if env_p else []
    return [env_p, "/mnt/project/CME_MINI_DL_NQ1___1D_3.csv", "/mnt/project/CME_MINI_DL_NQ1___1D.csv"]

def _sar_from_nq(asof_date=None, strict=False):
    """Deep fallback: latest OniMine EXP_STATE_ID from a local NQ export (if present).
       asof_date を渡すと壁時計でなくその日までで切る。strict=True は明示env以外読まない（#1）。"""
    _cut = (pd.Timestamp(asof_date).tz_localize(None).normalize() if asof_date is not None
            else pd.Timestamp(last_completed_session()).tz_localize(None).normalize())
    for p in _nq_export_paths(strict):
        if p and os.path.exists(p):
            try:
                df = pd.read_csv(p)
                col = [c for c in df.columns if "EXP_STATE_ID" in c]
                if not col:
                    continue
                tcol = [c for c in df.columns if str(c).lower() in ("time", "date", "datetime") or "time" in str(c).lower()]
                if not tcol:
                    print(f"[warn] NQ export has no date column; skip unsafe last-row read: {p}")
                    continue
                try:
                    _ts = pd.to_datetime(df[tcol[0]], errors="coerce", utc=True).dt.tz_localize(None)
                    _series = _nq_stable_color_series(df, col[0], _ts, _cut)   # 安定ソート・重複解決を共通化
                except Exception as _e:
                    print("[warn] _sar_from_nq date-cut failed; skip export:", _e)
                    continue
                if not _series:
                    continue
                return _series[-1]                                            # 昇順末尾=最新
            except Exception:
                continue
    return None

def _sar_series_from_nq_export(asof_date=None, strict=False):
    """ローカルNQ export の EXP_STATE_ID 全履歴を色系列(list[str])で返す。
       asof_date で切り、strict=True は明示env以外読まない（#1）。yfinance到達不可でもCSVがあれば復元。失敗時None。"""
    try:
        _cut = (pd.Timestamp(asof_date, tz="UTC") if asof_date is not None
                else pd.Timestamp(last_completed_session(), tz="UTC"))
    except Exception:
        _cut = None
    for p in _nq_export_paths(strict):
        if not p or not os.path.exists(p):
            continue
        try:
            df = pd.read_csv(p)
            scol = [c for c in df.columns if "EXP_STATE_ID" in str(c)]
            tcol = [c for c in df.columns if str(c).lower() in ("time", "date", "datetime") or "time" in str(c).lower()]
            if not scol or not tcol:
                continue
            _ts = pd.to_datetime(df[tcol[0]], errors="coerce", utc=True)
            # 安定ソート・同一時刻重複の決定的解決を共通ヘルパーに統一（降順CSVでも末尾=最新）
            series = _nq_stable_color_series(df, scol[0], _ts, _cut)
            if len(series) >= 2:
                return series
        except Exception:
            continue
    return None

def _psar(h, l, c, step=0.02, mx=0.20):
    """Wilder Parabolic SAR (AF 0.02 step, 0.20 max)."""
    n = len(c); sar = np.zeros(n); bull = True; af = step; ep = l[0]; sar[0] = l[0]
    for i in range(1, n):
        sar[i] = sar[i-1] + af*(ep - sar[i-1])
        if bull:
            if l[i] < sar[i]:
                bull = False; sar[i] = ep; ep = l[i]; af = step
            elif h[i] > ep:
                ep = h[i]; af = min(af+step, mx)
        else:
            if h[i] > sar[i]:
                bull = True; sar[i] = ep; ep = h[i]; af = step
            elif l[i] < ep:
                ep = l[i]; af = min(af+step, mx)
    return sar

_LAST_ONIMINE_SERIES = None
def _onimine_state(C, sar, ema21, rsi):
    """復元したOniMine 4色FSMを系列に適用し最終色を返す（OOS≈96%）。
    2軸: close vs PSAR=強気側(青/緑)/弱気側(黄/赤)。緑黄=移行・青赤=確定。
    昇格= RSI閾値 かつ SAR転換から2バー以上 かつ 反スパイク。降格=21EMA割れ/超えで即時。
    日次の色系列は _LAST_ONIMINE_SERIES に退避（レジーム分布/連続日数/日次バーの算出に再利用）。"""
    global _LAST_ONIMINE_SERIES
    n = len(C)
    above = C > sar
    state = "Green" if above[0] else "Yellow"     # ウォームアップ種（1年分で自己補正）
    bsu = bsd = 99                                 # bars since SAR flip up / down
    prev_rsi = None
    series = []
    for i in range(n):
        bsu = 0 if (i > 0 and above[i] and not above[i-1]) else bsu + 1
        bsd = 0 if (i > 0 and (not above[i]) and above[i-1]) else bsd + 1
        drsi = (rsi[i] - prev_rsi) if prev_rsi is not None else 0.0
        if above[i]:                               # 強気側: 青/緑
            if state == "Blue":
                state = "Green" if C[i] < ema21[i] else "Blue"            # 降格(21EMA割れ)
            else:
                state = "Blue" if (rsi[i] > 52 and bsu >= 2 and drsi <= 3.0) else "Green"
        else:                                      # 弱気側: 黄/赤
            if state == "Red":
                state = "Yellow" if rsi[i] > 50 else "Red"               # 降格: RSI>50 (Pine準拠)
            else:
                state = "Red" if (rsi[i] < 47 and bsd >= 2 and drsi >= -3.0) else "Yellow"
        prev_rsi = rsi[i]
        series.append(state)
    try:
        _LAST_ONIMINE_SERIES = list(series)
    except Exception:
        _LAST_ONIMINE_SERIES = None
    return state
def _regime_color_stats(series, window=60):
    """日次色系列から分布と連続日数を返す。
       streak_exact = 履歴末尾の正確色(Blue/Green/Yellow/Red)がそのまま何日続くか。
       streak_side  = 強気側(Blue+Green)/Yellow/Red のいずれかが何日続くか。
       last_history_color = 履歴末尾の正確色（現在色と食い違う場合の明示用）。
       ※「N日連続Blue」表示にはstreak_exactを使う。強気側の継続はstreak_sideを別ラベルで。"""
    try:
        if not series:
            return None
        raw = list(series)
        def _simp(c):
            return "g" if c in ("Green", "Blue") else ("y" if c == "Yellow" else "r")
        simp = [_simp(c) for c in raw]
        tail = simp[-window:]
        g = tail.count("g"); y = tail.count("y"); r = tail.count("r")
        # 正確色の連続日数（末尾の正確色がそのまま何日続くか）
        last_exact = raw[-1]; streak_exact = 0
        for c in reversed(raw):
            if c == last_exact:
                streak_exact += 1
            else:
                break
        # 強気側(簡略色)の連続日数
        last_side = simp[-1]; streak_side = 0
        for c in reversed(simp):
            if c == last_side:
                streak_side += 1
            else:
                break
        return {"g60": g, "y60": y, "r60": r,
                "streak": streak_exact,            # 後方互換: streak=正確色連続
                "streak_exact": streak_exact,
                "streak_side": streak_side,
                "last_history_color": last_exact,
                "days": simp[-40:]}
    except Exception:
        return None

def _estimate_sar_from_live(asof_date=None):
    """ライブNQ=Fから復元FSMでOniMine色を推定（PSAR方向×確信度・OOS≈96%）。失敗時None。
    PSAR(0.02/0.02/0.08)・RSI Wilder14・21EMAの3本でFSMを駆動。--selftest(オフライン)時はNone。
    #7 asof_date指定時はそこまでで切り、過去as-of分析に現在のライブ足を混ぜない。"""
    if not _net_ok():
        return None
    try:
        import yfinance as yf
        _cut = None
        try:
            _cut = pd.Timestamp(asof_date) if asof_date is not None else last_completed_session()
        except Exception:
            pass
        df = yf.download("NQ=F", period="1y", interval="1d",
                         auto_adjust=False, progress=False)
        if _cut is not None:
            try:
                df = df[df.index.tz_localize(None) <= pd.Timestamp(_cut)] if getattr(df.index,'tz',None) is not None else df[df.index <= pd.Timestamp(_cut)]   # 形成中の当日足を除外(監査2)/as-of切り(#7)
            except Exception as _e:
                print('[warn] live cut failed:', _e)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 60:
            return None
        H, L, C = df["High"].values, df["Low"].values, df["Close"].values
        sar = _psar(H, L, C, step=0.02, mx=0.08)                  # OniMineと同じSAR
        ema21 = df["Close"].ewm(span=21, adjust=False).mean().values
        d = df["Close"].diff()
        up = d.clip(lower=0); dn = -d.clip(upper=0)
        ru = up.ewm(alpha=1/14, adjust=False).mean()              # Wilder RSI14
        rd = dn.ewm(alpha=1/14, adjust=False).mean()
        rsi = (100 - 100/(1 + ru/rd)).values
        return _onimine_state(C, sar, ema21, rsi)
    except Exception:
        return None

def _parse_sar_state_text(raw):
    """Return (color, asof_date|None) from JSON / CSV-ish / plain text."""
    import re as _re
    raw = (raw or "").strip()
    if not raw:
        return None, None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            c = _norm_color(obj.get("color") or obj.get("state") or obj.get("sar"))
            ds = obj.get("asof") or obj.get("date") or obj.get("session")
            d = pd.Timestamp(ds).date() if ds else None
            return c, d
    except Exception:
        pass
    dm = _re.search(r"([0-9]{4}-[0-9]{2}-[0-9]{2})", raw)
    d = None
    if dm:
        try:
            d = pd.Timestamp(dm.group(1)).date()
        except Exception:
            d = None
    cm = _re.search(r"\b(Blue|Green|Yellow|Red)\b", raw, _re.I)
    c = _norm_color(cm.group(1)) if cm else None
    return c, d


def read_sar_state(asof_date=None, strict=False):
    """Return (color, source). dated file -> completed NQ CSV -> completed live estimate -> none.

    asof_date を渡すと、鮮度判定の基準を「実行日の壁時計(last_completed_session)」ではなく
    「価格データのas-of日」にする。過去fixture/再現時に、同日のSARファイルがstale扱いされない（#8）。
    strict=True（offline selftest）: 環境変数V38_SAR_STATEで明示されたファイルのみ読む。
    """
    _sess = None
    try:
        _sess = pd.Timestamp(asof_date).date() if asof_date is not None else pd.Timestamp(last_completed_session()).date()
    except Exception:
        pass
    allow_undated = os.environ.get("V38_ALLOW_UNDATED_SAR", "0") == "1"
    _paths, _seen = [], set()
    if strict:
        _cand = [os.environ.get("V38_SAR_STATE")]
    else:
        _cand = [SAR_STATE_PATH, "/mnt/project/sar_state.txt",
                 os.path.join(os.path.dirname(CACHE), "sar_state.txt")]
    for _p in _cand:
        if _p and _p not in _seen:
            _seen.add(_p); _paths.append(_p)
    for p in _paths:
        if not os.path.exists(p):
            continue
        try:
            _raw = open(p, encoding="utf-8").read()
            c, obs = _parse_sar_state_text(_raw)
            if not c:
                continue
            if obs is None and not allow_undated:
                print(f"[warn] sar_state has no embedded date; skip untrusted file: {p}")
                continue
            if _sess is not None and obs is not None:
                if obs > _sess:
                    print(f"[warn] sar_state is future-dated({obs}>{_sess}); skip: {p}")
                    continue
                if obs < _sess:
                    print(f"[warn] sar_state is stale({obs}<{_sess}); fall back to completed NQ data")
                    continue
            return c, "file"
        except Exception as e:
            print("[warn] sar_state read failed:", e)
    try:
        c = _sar_from_nq(asof_date=asof_date, strict=strict)
        if c:
            return c, "nq_csv"
    except Exception as e:
        print("[warn] _sar_from_nq failed:", e)
    c = _estimate_sar_from_live(asof_date=asof_date)
    if c:
        return c, "estimate"
    return None, "none"

# ----------------------------------------------------------------------------- sentiment (群衆温度計・表示専用)
# 原則: センチメントは「極値でのみ」逆張りシグナル。中間帯はノイズ。MRIと同じ思想で
# 固定閾値でなくトレーリング分位でスコア化し、合成0-100を「群衆温度計」として表示する。
# ゲート・銘柄選定には一切関与しない（D柱と同じ表示専用）。II/AAIIは手動参照。
def _roll_pct(s, win=504, minp=120):
    """系列の各時点値の、トレーリングwin内パーセンタイル(0-100)。既定は約2年
    （データがある範囲で自動的に最長化・min_periods到達後から算出）。"""
    s = pd.Series(s).dropna()
    if len(s) < max(minp, 20):
        return pd.Series(dtype=float)
    try:
        return s.rolling(win, min_periods=minp).rank(pct=True) * 100
    except Exception:                                   # 古いpandasフォールバック
        return s.rolling(win, min_periods=minp).apply(
            lambda a: float((a[:-1] <= a[-1]).mean()) * 100, raw=True)

def fetch_fng():
    """CNN Fear & Greed（合成7要素・0-100）＋equity Put/Call の履歴。失敗時{}。--selftest(オフライン)時は{}。"""
    if not _net_ok():
        return {}
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0 (v38-dashboard)"})
        d = json.loads(urllib.request.urlopen(req, timeout=12).read())
        def ts(key):
            out = []
            for p in (d.get(key) or {}).get("data", []):
                try:
                    out.append((pd.Timestamp(int(p["x"]), unit="ms").normalize(),
                                float(p["y"])))
                except Exception:
                    continue
            return out
        return {"fng": ts("fear_and_greed_historical"), "pc": ts("put_call_options")}
    except Exception as e:
        sys.stderr.write("[senti] CNN F&G fetch failed: %r\n" % repr(e)[:90])
        return {}

def fetch_naaim():
    """NAAIM Exposure Index（週次・実弾エクスポージャー -200..+200）。CSVリンクをページから発見。失敗時[]。--selftest(オフライン)時は[]。"""
    if not _net_ok():
        return []
    try:
        import urllib.request, re as _re
        req = urllib.request.Request("https://naaim.org/programs/naaim-exposure-index/",
                                     headers={"User-Agent": "Mozilla/5.0 (v38-dashboard)"})
        page = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
        mm = _re.search(r'href="([^"]+\.csv[^"]*)"', page, _re.I)
        if not mm:
            return []
        url = mm.group(1)
        if url.startswith("/"):
            url = "https://naaim.org" + url
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=12).read()
        rows = []
        for ln in raw.decode("utf-8", "ignore").splitlines()[1:]:
            parts = [x.strip() for x in ln.split(",")]
            if len(parts) < 2:
                continue
            try:
                rows.append((pd.Timestamp(parts[0]).normalize(), float(parts[1])))
            except Exception:
                continue
        rows.sort()
        return rows
    except Exception as e:
        sys.stderr.write("[senti] NAAIM fetch failed: %r\n" % repr(e)[:90])
        return []

def build_sentiment(macro, W, live=True, asof_date=None):
    """群衆温度計: レバETF資金熱・パラボリック銘柄率(自前) + F&G・P/C(CNN) + NAAIM。
    各指標をトレーリング分位0-100(高=強欲)に正規化し、利用可能なものの平均を合成。"""
    parts = {}          # key -> 日次percentile系列(0-100)
    rows = []           # 表示行 (label, rawtxt, pct, in_composite, note)
    flags = []          # (label, on) 双方向の極値フラグ
    avail = []

    # ライブ時はセンチメント銘柄だけ5年ヒストリーを追加取得（分位の基準期間を長期化）
    macro = dict(macro)
    _scut = pd.Timestamp(asof_date) if asof_date is not None else None
    if live and _net_ok():
        try:
            import yfinance as yf
            _st = ["TQQQ", "SQQQ", "SOXL", "SOXS", "^SKEW"]
            hist = yf.download(_st, period="5y", progress=False,
                               auto_adjust=True, group_by="ticker", threads=True)
            for _t in _st:
                try:
                    _df = hist[_t].dropna()
                    if _scut is not None:                       # #7 as-ofより後の足を落とす（過去再現に現在値を混ぜない）
                        try: _df = _df[pd.to_datetime(_df.index) <= _scut]
                        except Exception: pass
                    _cur = macro.get(_t)
                    if len(_df) > (len(_cur) if _cur is not None else 0):
                        macro[_t] = _df
                except Exception:
                    continue
        except Exception:
            pass

    def dv(k):
        d = macro.get(k)
        if d is None or "Volume" not in d:
            return None
        s = (d["Close"] * d["Volume"]).dropna()
        return s if len(s) > 60 else None

    # 1) レバETF資金熱: ブル3x売買代金 / (ブル+ベア3x) の5日平均 → 分位
    try:
        bulls = [x for x in (dv("TQQQ"), dv("SOXL")) if x is not None]
        bears = [x for x in (dv("SQQQ"), dv("SOXS")) if x is not None]
        if bulls and bears:
            b = pd.concat(bulls, axis=1).sum(axis=1)
            s = pd.concat(bears, axis=1).sum(axis=1)
            ratio = (b / (b + s)).rolling(5).mean().dropna()
            p = _roll_pct(ratio)
            if len(p.dropna()):
                parts["lever"] = p
                cur_r, cur_p = float(ratio.iloc[-1]), float(p.dropna().iloc[-1])
                rows.append(("レバETF資金熱", f"ブル比率 {cur_r*100:.0f}%", cur_p, True,
                             "TQQQ+SOXL÷(ブル+ベア3x)売買代金・5日平均"))
                flags.append(("レバ熱 過熱", cur_p >= 90))
                flags.append(("レバ資金 退避", cur_p <= 10))
                avail.append("レバ熱")
    except Exception:
        pass

    # 2) パラボリック銘柄率: 200日線+45%超の銘柄割合（ユニバース） → 分位
    try:
        C = W["Close"]
        ma200 = C.rolling(200, min_periods=200).mean()
        ok = ma200.notna()
        denom = ok.sum(axis=1).replace(0, np.nan)
        par = (((C >= ma200 * 1.45) & ok).sum(axis=1) / denom * 100).dropna()
        p = _roll_pct(par, win=756, minp=60)
        if len(p.dropna()):
            parts["parab"] = p
            cur_r, cur_p = float(par.iloc[-1]), float(p.dropna().iloc[-1])
            rows.append(("パラボリック銘柄率", f"{cur_r:.1f}%", cur_p, True,
                         "200日線から+45%超で走る銘柄の割合（ユニバース）"))
            flags.append(("パラボ乱舞", cur_p >= 90))
            avail.append("パラボ率")
    except Exception:
        pass

    ext = fetch_fng() if live else {}
    # 3) CNN Fear & Greed（それ自体が0-100の強欲スケール）
    fng = ext.get("fng") or []
    if len(fng) >= 30:
        s = pd.Series({d: v for d, v in fng}).sort_index()
        if _scut is not None:                          # #7 as-ofより後のCNN値を落とす（過去再現に現在値を混ぜない）
            try: s = s[pd.to_datetime(s.index).tz_localize(None) <= pd.Timestamp(_scut).tz_localize(None)]
            except Exception:
                try: s = s[pd.to_datetime(s.index) <= pd.Timestamp(_scut)]
                except Exception: pass
        if len(s) >= 30:                               # 切った後に必要本数を再判定（過去as-ofで本数不足になり得る）
            p = _roll_pct(s)                # #31: 合成には自身のトレーリング分位（P/C・NAAIMと尺度統一）
            parts["fng"] = p
            cur = float(s.iloc[-1])         # 生値はラベル表示に使う（as-of切り後の最終値）
            cur_p = float(p.dropna().iloc[-1]) if len(p.dropna()) else cur
            lab = ("Extreme Greed" if cur >= 75 else "Greed" if cur >= 55 else
                   "Neutral" if cur >= 45 else "Fear" if cur >= 25 else "Extreme Fear")
            rows.append(("CNN Fear & Greed", f"{cur:.0f}（{lab}）", cur_p, True, "7要素合成・CNN公表値を分位化"))
            flags.append(("F&G 極端な強欲", cur >= 75))
            flags.append(("F&G 極端な恐怖", cur <= 25))
            avail.append("F&G")

    # 4) Put/Call（equity）: 低いほど強欲 → 分位を反転
    pc = ext.get("pc") or []
    if len(pc) >= 60:
        s = pd.Series({d: v for d, v in pc}).sort_index()
        if _scut is not None:                          # #7 as-ofより後のPut/Call値を落とす
            try: s = s[pd.to_datetime(s.index).tz_localize(None) <= pd.Timestamp(_scut).tz_localize(None)]
            except Exception:
                try: s = s[pd.to_datetime(s.index) <= pd.Timestamp(_scut)]
                except Exception: pass
        s = s.rolling(10).mean().dropna()
        if len(s) >= 60:                               # 切った後に必要本数を再判定
            p = _roll_pct(s)
            if len(p.dropna()):
                parts["pc"] = 100 - p
                cur_r, cur_p = float(s.iloc[-1]), float(100 - p.dropna().iloc[-1])
                rows.append(("Put/Call（10日平均）", f"{cur_r:.2f}", cur_p, True,
                             "低いほどコール偏重＝強欲（分位反転）"))
                flags.append(("コール偏重 極端", cur_p >= 90))
                avail.append("P/C")

    # 5) NAAIM（実弾。95超=全力ロング常態 / 30割れ=投げ）
    naaim = fetch_naaim() if live else []
    if len(naaim) >= 52:
        s = pd.Series({d: v for d, v in naaim}).sort_index()
        if _scut is not None:                          # #7 as-ofより後のNAAIM週次を落とす
            try: s = s[pd.to_datetime(s.index) <= _scut]
            except Exception: pass
        if len(s) >= 52:
            p = _roll_pct(s, win=260, minp=52)          # 週次≒5年分位
            if len(p.dropna()):
                parts["naaim"] = p
                cur_r, cur_p = float(s.iloc[-1]), float(p.dropna().iloc[-1])
                rows.append(("NAAIM エクスポージャー", f"{cur_r:.0f}", cur_p, True,
                             "アクティブ運用者の実際の株式露出（週次）"))
                flags.append(("NAAIM 全力(≥95)", cur_r >= 95))
                flags.append(("NAAIM 投げ(≤30)", cur_r <= 30))
                avail.append("NAAIM")

    # 6) SKEW（参考・合成外）: テールヘッジ需要
    try:
        sk = macro.get("^SKEW")
        if sk is not None:
            s = sk["Close"].dropna()
            p = _roll_pct(s)
            if len(p.dropna()):
                rows.append(("SKEW", f"{float(s.iloc[-1]):.0f}", float(p.dropna().iloc[-1]),
                             False, "テールリスクの保険需要・解釈が割れるため合成外"))
    except Exception:
        pass

    if not parts:
        return None
    # 合成: 日次に整列してffill→平均
    base_idx = None
    for k in ("parab", "lever"):
        if k in parts:
            base_idx = parts[k].dropna().index
            break
    if base_idx is None:
        base_idx = sorted(set().union(*[set(p.dropna().index) for p in parts.values()]))
        base_idx = pd.DatetimeIndex(base_idx)
    aligned = pd.DataFrame({k: p.reindex(base_idx).ffill() for k, p in parts.items()})
    comp = aligned.mean(axis=1, skipna=True).dropna()
    if not len(comp):
        return None
    cur = float(comp.iloc[-1])
    flags.insert(0, ("群衆 過熱（合成≥85）", cur >= 85))
    flags.insert(1, ("群衆 総悲観（合成≤15）", cur <= 15))
    band = ("過熱🔥" if cur >= 85 else "強欲寄り" if cur >= 65 else
            "中立" if cur >= 35 else "弱気寄り" if cur > 15 else "総悲観🧊")
    ts = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in comp.iloc[-CHART_LB:].items()]
    return dict(cur=cur, band=band, rows=rows, flags=flags, ts=ts, avail=avail)

def _svg_senti(ts):
    """センチメント推移: マーケットステータス推移と同じ幾何・ゾーン塗り（0-100固定・極値のみ着色）。"""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; n = len(ys)
    Wd, Ht, pad = 680, 180, 6
    def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
    def Y(v): return pad + (1 - v/100) * (Ht - 2*pad)
    zones = [(0,15,"#38bdf8"),(15,35,"#22c55e"),(35,65,"#64748b"),(65,85,"#f59e0b"),(85,100,"#ef4444")]
    zr = "".join(f'<rect x="{pad}" y="{Y(z1):.1f}" width="{Wd-2*pad}" '
                 f'height="{max(0.0,Y(z0)-Y(z1)):.1f}" fill="{zc}" opacity="0.07"/>' for z0,z1,zc in zones)
    gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="#1c2533" stroke-width="1"/>'
                 f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g}</text>'
                 for g in (15,50,85))
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i,v in enumerate(ys))
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">{zr}{gl}'
            f'<polyline points="{pts}" fill="none" stroke="#f472b6" stroke-width="2"/>'
            f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="#f472b6"/></svg>')

def _sentiment_card(senti):
    if not senti:
        return ('<div class="card"><h2>センチメント（群衆温度計）</h2>'
                '<div class="sub">データ取得不可（レバETF・CNN F&amp;G・NAAIMのいずれも利用できず）。'
                'II/AAIIは手動参照。</div></div>')
    cur = senti["cur"]
    col = "#fca5a5" if cur >= 85 else "#fdba74" if cur >= 65 else "#9fb0c5" if cur >= 35 else "#7dd3fc" if cur > 15 else "#7ff0a8"
    comp_rows = []
    for lab, raw, pct, in_comp, note in senti["rows"]:
        tag = ""
        comp_rows.append(
            f'<div class="mrow"><span class="mk2">{lab}{tag}</span>'
            f'<span class="mraw">{raw}</span>'
            f'<span class="mbar"><i style="width:{max(0,min(100,pct)):.0f}%;background:#f472b6"></i></span>'
            f'<span class="mpts">{pct:.0f}</span></div>'
            f'<div class="sn-note">{note}</div>')
    lit = [l for l, on in senti["flags"] if on]
    off = [l for l, on in senti["flags"] if not on]
    chips = ("".join(f'<span class="bfl on">{l}</span>' for l in lit)
             + "".join(f'<span class="bfl off">{l}</span>' for l in off))
    return (
        f'<div class="card"><div class="chd"><h2>センチメント（群衆温度計）</h2>'
        f'<div class="chd-now" style="color:{col}"><b>{cur:.0f}</b><span>{senti["band"]}</span></div></div>'
        f'<div class="sub">利用ソース: {", ".join(senti["avail"])}・各指標を<b>トレーリング約2年（NAAIMは約5年）</b>の分位0-100（高=強欲）に正規化して平均。'
        f'<b>逆張りが効くのは極値のみ</b>（過熱≥85／総悲観≤15）・中間帯はノイズ</div>'
        + "".join(comp_rows)
        + f'<div class="bflags" style="margin-top:8px">{chips}</div>'
        + f'<div class="chart">{_svg_senti(senti["ts"])}'
        + (f'{_date_axis(senti["ts"])}' if senti.get("ts") else "")
        + '</div>'
        f'<div class="note">過熱＝即売りではない（強いトレンド中の過熱は正常）。実用は2つだけ: '
        f'<b>総悲観×FTD点灯＝仕込み</b>／<b>過熱×売り抜け日の積み上がり＝新規を絞る</b>。</div></div>')

# ----------------------------------------------------------------------------- equity curve (口座の21EMAルール)
# 「自分のエクイティカーブにMAを引け」: EC<21EMAは システム×相場 の相性悪化シグナル。
# 新規を止めサイズを落とす根拠にする（Minervini/系統トレーダーの定番・表示専用）。
def load_equity(strict=False):
    """equity.csv: date,equity[,us_pct]。us_pct(米株比率%)は任意列・無い行はNaN。
       strict=True（offline selftest）: 環境変数V38_EQUITY_CSVで明示された時のみ読む。"""
    env_p = os.environ.get("V38_EQUITY_CSV")
    if strict:
        paths = [env_p] if env_p else []
    else:
        paths = [env_p, "/mnt/project/equity.csv",
                 os.path.join(os.path.dirname(CACHE), "equity.csv"), "equity.csv"]
    p = next((x for x in paths if x and os.path.exists(x)), None)
    if not p:
        return None
    rows = []
    import re as _re_eq
    _n_comma = 0; _n_space = 0
    try:
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            # カンマ／タブ／空白 いずれの区切りでも読む（貼り付け時の体裁ズレを吸収）
            parts = [x for x in _re_eq.split(r"[,\t\s]+", ln) if x != ""]
            if len(parts) < 2:
                continue
            if parts[0].lower() in ("date", "日付"):   # ヘッダ行はスキップ
                continue
            # 既存ファイルが使っている区切りを集計（コピー時に合わせる用）
            if "," in ln:
                _n_comma += 1
            elif ("\t" in ln) or (" " in ln):
                _n_space += 1
            try:
                d = pd.Timestamp(parts[0]).normalize()
                v = float(parts[1].replace("¥", "").replace("$", "").replace("_", "").replace(",", ""))
            except Exception:
                continue
            up = np.nan
            if len(parts) >= 3 and parts[2] != "":
                try:
                    up = float(parts[2].replace("%", ""))
                except Exception:
                    up = np.nan
            rows.append((d, v, up))
    except Exception:
        return None
    if len(rows) < 5:
        return None
    s = pd.Series({d: v for d, v, _ in rows}).sort_index()
    s.attrs["us_pct"] = pd.Series({d: u for d, v, u in rows}).sort_index()
    # 既存の主流な区切り（多数決・同数/空はカンマ）→ コピーボタンがこれに合わせる
    s.attrs["delim"] = " " if _n_space > _n_comma else ","
    return s

def build_equity_view(s):
    if s is None or len(s) < 5:
        return None
    # 営業日ベースのEMA: 記録を営業日グリッドに載せ替え、抜けた平日は前値で埋める。
    # これで span=21 が名実ともに「21営業日EMA」になる（土日は除外・記録の飛びは前値維持）。
    try:
        s_raw = s
        bidx = pd.bdate_range(s.index.min(), s.index.max())
        s_bd = s.reindex(s.index.union(bidx)).ffill().reindex(bidx)
        ema21_bd = s_bd.ewm(span=21, adjust=False).mean()
        # 表示は実記録点に戻す（グラフが埋め値だらけにならないよう、記録がある営業日だけ拾う）
        ema_at_rec = ema21_bd.reindex(s.index, method="ffill")
        s = s_raw
        ema21 = ema_at_rec
    except Exception:
        ema21 = s.ewm(span=21, adjust=False).mean()
    last, e = float(s.iloc[-1]), float(ema21.iloc[-1])
    above = last >= e
    below_n = 0
    for v, m in zip(s.values[::-1], ema21.values[::-1]):
        if v < m:
            below_n += 1
        else:
            break
    peak = float(s.cummax().iloc[-1])
    dd = last / peak - 1
    n = min(len(s), 130)
    ts = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.iloc[-n:].items()]
    ets = [float(v) for v in ema21.iloc[-n:].values]
    # 露出（米株比率%）: 任意3列目。記録がある点だけ (index位置, 値) で持つ
    ups = []
    up_s = s.attrs.get("us_pct")
    if up_s is not None:
        tail = up_s.iloc[-n:]
        ups = [(i, float(v)) for i, v in enumerate(tail.values) if v == v]
    r20 = last / float(s.iloc[-min(len(s), 21)]) - 1
    return dict(last=last, ema=e, above=above, below_n=below_n, dd=dd, peak=peak,
                gap=last / e - 1, ts=ts, ets=ets, ups=ups, r20=r20, n=len(s),
                delim=s.attrs.get("delim", ","), ema_lab="21日EMA",
                d0=str(s.index[0].date()), d1=str(s.index[-1].date()))


# ----------------------------------------------------------------------------- emergency brake (NAV DD × relative performance)
EM_DD_ON, EM_REL_ON = -0.28, -0.12
EM_DD_OFF, EM_REL_OFF = -0.20, -0.08

def _series_asof(s, d):
    """Return the last finite observation on/before d."""
    if s is None or len(s) == 0:
        return None
    try:
        x = pd.to_numeric(s, errors="coerce").dropna().sort_index()
        x = x[x.index <= pd.Timestamp(d)]
        return float(x.iloc[-1]) if len(x) else None
    except Exception:
        return None

def build_emergency_brake(eq_s, macro, prev_state=None, asof=None):
    """Automate the leverage emergency brake with hysteresis.

    Trigger: account NAV drawdown <= -28% AND 12-month relative return vs QQQ in JPY <= -12%.
    Release: drawdown > -20% AND relative return > -8%.
    If the brake was already active and fresh data becomes unavailable, keep it active (fail-safe).
    """
    prev_em = ((prev_state or {}).get("emergency") or {})
    was_active = bool(prev_em.get("active"))
    base = dict(
        available=False, active=was_active, mult=(0.5 if was_active else 1.0),
        dd=None, rel12=None, nav12=None, bench12=None,
        start=None, end=None, triggered_on=prev_em.get("triggered_on"),
        event="継続" if was_active else "待機", benchmark="QQQ×USD/JPY（円建て）",
        reason="equity.csvまたはQQQ円建てベンチマークが不足",
        thresholds=dict(dd_on=EM_DD_ON, rel_on=EM_REL_ON, dd_off=EM_DD_OFF, rel_off=EM_REL_OFF),
    )
    if eq_s is None or len(eq_s) < 5:
        if was_active:
            base["reason"] = "データ不足のため安全側で非常口の発動状態を維持"
        return base
    q = (macro or {}).get("QQQ")
    fx = (macro or {}).get("JPY=X")
    if q is None or fx is None or "Close" not in q or "Close" not in fx:
        if was_active:
            base["reason"] = "QQQ円建てベンチマーク不足のため安全側で発動状態を維持"
        else:
            base["reason"] = "JPY=X不足のため非常口は自動判定不可（為替未補正では作動させない）"
        return base
    try:
        eq = pd.to_numeric(eq_s, errors="coerce").dropna().sort_index()
        qc = pd.to_numeric(q["Close"], errors="coerce").dropna().sort_index()
        fc = pd.to_numeric(fx["Close"], errors="coerce").dropna().sort_index()
        if asof is not None:
            cut = pd.Timestamp(asof)
            if getattr(cut, "tzinfo", None) is not None:
                cut = cut.tz_localize(None)
            eq = eq[eq.index <= cut]; qc = qc[qc.index <= cut]; fc = fc[fc.index <= cut]
        if len(eq) < 5 or len(qc) < 200 or len(fc) < 200:
            raise ValueError("履歴不足")
        # QQQ and USDJPY are both quoted as JPY per USD multiplier: QQQ_USD × JPY_per_USD.
        bench = pd.concat([qc.rename("q"), fc.rename("fx")], axis=1).sort_index().ffill().dropna()
        bench = bench["q"] * bench["fx"]
        end = min(eq.index[-1], bench.index[-1])
        eq = eq[eq.index <= end]
        if len(eq) < 5:
            raise ValueError("NAV履歴不足")
        target = end - pd.Timedelta(days=365)
        # 1年前【以前】の最終記録を使う（nearestだと目標日より後の記録を選び得るため pad に固定）
        loc = int(eq.index.get_indexer([target], method="pad")[0])
        if loc < 0:
            loc = 0
        start = eq.index[loc]
        if (end - start).days < 330:
            raise ValueError("12ヶ月履歴不足")
        nav0, nav1 = float(eq.loc[start]), float(eq.iloc[-1])
        b0, b1 = _series_asof(bench, start), _series_asof(bench, end)
        if not all(v is not None and np.isfinite(v) and v > 0 for v in (nav0, nav1, b0, b1)):
            raise ValueError("基準値不足")
        peak = float(eq.cummax().iloc[-1])
        dd = nav1 / peak - 1.0
        nav12 = nav1 / nav0 - 1.0
        bench12 = b1 / b0 - 1.0
        rel12 = (1.0 + nav12) / (1.0 + bench12) - 1.0
        trigger = (dd <= EM_DD_ON and rel12 <= EM_REL_ON)
        recover = (dd > EM_DD_OFF and rel12 > EM_REL_OFF)
        if was_active:
            active = not recover
            event = "解除" if recover else "継続"
        else:
            active = trigger
            event = "発動" if trigger else "待機"
        trig_on = prev_em.get("triggered_on")
        if active and not was_active:
            trig_on = str(pd.Timestamp(end).date())
        if not active:
            trig_on = None
        return dict(
            available=True, active=bool(active), mult=(0.5 if active else 1.0),
            dd=float(dd), rel12=float(rel12), nav12=float(nav12), bench12=float(bench12),
            start=str(pd.Timestamp(start).date()), end=str(pd.Timestamp(end).date()),
            triggered_on=trig_on, event=event, benchmark="QQQ×USD/JPY（円建て）",
            reason=("DDと対QQQ相対が同時に発動条件へ到達" if event == "発動" else
                    "DDと相対の両方が解除条件まで回復" if event == "解除" else
                    "発動条件未成立" if not active else "解除条件までレバ半減を維持"),
            thresholds=dict(dd_on=EM_DD_ON, rel_on=EM_REL_ON, dd_off=EM_DD_OFF, rel_off=EM_REL_OFF),
        )
    except Exception as e:
        base["reason"] = ("データ不足のため安全側で非常口の発動状態を維持" if was_active
                          else f"非常口判定不可: {str(e)[:40]}")
        return base

def _emergency_card(em):
    em = em or {}
    avail = bool(em.get("available")); active = bool(em.get("active"))
    if active:
        cls, title, mult = "em-on", "非常口 発動中", "レバ ×0.50"
    elif avail:
        cls, title, mult = "em-off", "非常口 待機", "レバ ×1.00"
    else:
        cls, title, mult = "em-na", "非常口 判定不可", ("レバ ×0.50を維持" if active else "レバ変更なし")
    def pct(v):
        return "—" if v is None or not np.isfinite(v) else f"{float(v)*100:+.1f}%"
    dd = em.get("dd"); rel = em.get("rel12")
    ddcls = "neg" if dd is not None and dd <= EM_DD_ON else "pos" if dd is not None and dd > EM_DD_OFF else ""
    rcls = "neg" if rel is not None and rel <= EM_REL_ON else "pos" if rel is not None and rel > EM_REL_OFF else ""
    dates = f'{_h(str(em.get("start")))} → {_h(str(em.get("end")))}' if em.get("start") and em.get("end") else "12ヶ月履歴待ち"
    trig = f'・発動 {_h(str(em.get("triggered_on")))}' if em.get("triggered_on") else ""
    return (
        f'<div class="card emergency {cls}"><div class="hdr"><h2>{title}</h2><span class="em-mult">{mult}</span></div>'
        f'<div class="sub">口座NAVの高値からのDDと、QQQ円建てに対する12ヶ月相対を同時判定。発動後は両方が回復するまでレバ枠だけ半減。</div>'
        f'<div class="em-grid"><div><span>NAV DD</span><b class="{ddcls}">{pct(dd)}</b><small>発動 ≤−28% ／ 解除 &gt;−20%</small></div>'
        f'<div><span>対QQQ 12M</span><b class="{rcls}">{pct(rel)}</b><small>発動 ≤−12% ／ 解除 &gt;−8%</small></div></div>'
        f'<div class="em-foot"><span>{_h(str(em.get("reason") or "—"))}</span><span>{dates}{trig}</span></div></div>'
    )

def _svg_two(ys1, ys2, accent="#7ff0a8", accent2="#fbbf24", gid="eq"):
    n = len(ys1)
    Wd, Ht, pad = 680, 200, 6
    allv = list(ys1) + list(ys2)
    lo, hi = min(allv), max(allv)
    rng_ = (hi - lo) or 1
    lo -= rng_ * 0.06; hi += rng_ * 0.06; rng_ = hi - lo
    def X(i): return pad + i * (Wd - 2 * pad) / max(1, n - 1)
    def Y(v): return pad + (1 - (v - lo) / rng_) * (Ht - 2 * pad)
    p1 = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys1))
    p2 = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys2))
    area = (f"M{X(0):.1f},{Y(ys1[0]):.1f} "
            + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys1))
            + f" L{X(n-1):.1f},{Ht-pad:.1f} L{X(0):.1f},{Ht-pad:.1f} Z")
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{accent}" stop-opacity="0.30"/>'
            f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/></linearGradient></defs>'
            f'<path d="{area}" fill="url(#{gid})"/>'
            f'<polyline points="{p2}" fill="none" stroke="{accent2}" stroke-width="2" stroke-dasharray="5,4"/>'
            f'<polyline points="{p1}" fill="none" stroke="{accent}" stroke-width="2.2"/>'
            f'<circle cx="{X(n-1):.1f}" cy="{Y(ys1[-1]):.1f}" r="3.5" fill="{accent}"/></svg>')

def build_equity_attrib(s, macro):
    """下げの要因分解: 記録区間ごとに 実際 = 露出×市場(QQQ円建て) + 残差 に分解。
    市場代理=QQQ×USDJPY(円建て・記録日asof)。露出=us_pct(直前既知値をcarry)。"""
    if s is None or len(s) < 5:
        return None
    up = s.attrs.get("us_pct")
    if up is None or up.dropna().empty:
        return None
    q = macro.get("QQQ")
    if q is None:
        return None
    qc = q["Close"].dropna()
    fx = None
    # まず既に取得済み・正規化済みの macro["JPY=X"] を使う（別途fetchするとtz/asofがズレる・offline時に走る）
    _fxm = macro.get("JPY=X")
    if isinstance(_fxm, pd.DataFrame) and "Close" in _fxm:
        _fc = _fxm["Close"].dropna()
        if len(_fc) > 20:
            fx = _fc
    if fx is None and _net_ok():           # macroに無い時だけライブ取得（--selftestオフラインでは走らない）
        try:
            import yfinance as yf
            fdf = yf.download("JPY=X", period="6mo", progress=False, auto_adjust=True)
            fc = fdf["Close"].dropna()
            if isinstance(fc, pd.DataFrame):
                fc = fc.iloc[:, 0]
            if len(fc) > 20:
                fx = normalize_timeseries(fc.to_frame("Close"))["Close"]
        except Exception:
            fx = None
    bench = qc.copy()
    if fx is not None:
        b = pd.concat([qc.rename("q"), fx.rename("f")], axis=1).sort_index().ffill().dropna()
        bench = b["q"] * b["f"]
    bench = bench.sort_index()
    def bench_at(d):
        sub = bench[bench.index <= d]
        return float(sub.iloc[-1]) if len(sub) else None
    w_ff = up.ffill()
    dates = list(s.index)
    def window(dates_w):
        wa = wm = wf = 1.0; wsum = 0.0; n = 0; nskip = 0   # #7: リターンは加算不可→資産倍率で連鎖
        for a, b_ in zip(dates_w[:-1], dates_w[1:]):
            e0, e1 = float(s[a]), float(s[b_])
            r_act = e1 / e0 - 1
            w = w_ff.get(a, np.nan)
            b0, b1 = bench_at(a), bench_at(b_)
            if b0 is None or b1 is None or not (w == w):
                nskip += 1
                continue
            r_b = b1 / b0 - 1
            wa *= 1 + r_act; wm *= 1 + (w / 100.0) * r_b; wf *= 1 + r_b
            wsum += w; n += 1
        if n == 0:
            return None
        act = wa - 1; mkt = wm - 1; full = wf - 1
        return dict(act=act, mkt=mkt, full100=full, saved=mkt - full,
                    resid=act - mkt, w_avg=wsum / n, n=n, nskip=nskip)
    peak_d = s.idxmax()
    peak_i = dates.index(peak_d)
    out = dict(full=window(dates), fx_ok=fx is not None,
               peak_date=str(peak_d.date()))
    out["peak"] = window(dates[peak_i:]) if peak_i < len(dates) - 1 else None
    return out

def _attrib_html(at):
    if not at or not at.get("peak"):
        return ""
    p = at["peak"]
    def pct(x): return f"{x*100:+.1f}%"
    def cls(x): return "pos" if x >= 0 else "neg"
    fxn = "" if at["fx_ok"] else "（為替取得不可・USD建て近似）"
    return (
        f'<div class="attrib"><div class="attrib-h">下げの要因分解（ピーク {at["peak_date"]} 以降・QQQ円建て代理{fxn}）</div>'
        f'<div class="attrib-g">'
        f'<span class="atk">実際</span><b class="{cls(p["act"])}">{pct(p["act"])}</b>'
        f'<span class="atk">＝ 市場<span class="atsub">露出{p["w_avg"]:.0f}%加味</span></span><b class="{cls(p["mkt"])}">{pct(p["mkt"])}</b>'
        f'<span class="atk">＋ 銘柄・その他</span><b class="{cls(p["resid"])}">{pct(p["resid"])}</b></div>'
        f'<div class="attrib-g"><span class="atk">常時100%なら</span><b class="{cls(p["full100"])}">{pct(p["full100"])}</b>'
        f'<span class="atk">→ 露出調整の効果</span><b class="{cls(p["saved"])}">{pct(p["saved"])}</b></div>'
        f'<div class="mut" style="font-size:10.5px;margin-top:3px">記録日ベースの近似。市場=各区間の露出×QQQ円建てリターンの積上げ。'
        f'残差=銘柄選択・レバ・為替タイミング等。露出調整の効果プラス＝薄くして回避できた分。</div></div>')

def _svg_expo(ups, n):
    """露出バンド: 米株比率%(0-100)の棒。記録がある点のみ描画。"""
    if not ups:
        return ""
    Wd, Ht, pad = 680, 64, 6
    def X(i): return pad + i * (Wd - 2 * pad) / max(1, n - 1)
    bw = max(3.0, (Wd - 2 * pad) / max(1, n - 1) * 0.55)
    bars = ""
    for i, v in ups:
        h = max(1.5, v / 100 * (Ht - 14))
        col = "#38bdf8" if v >= 60 else "#7dd3fc" if v >= 25 else "#334155"
        bars += f'<rect x="{X(i)-bw/2:.1f}" y="{Ht-6-h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="1.5" fill="{col}"/>'
    grid = (f'<line x1="{pad}" y1="{Ht-6}" x2="{Wd-pad}" y2="{Ht-6}" stroke="#233046" stroke-width="1"/>'
            f'<line x1="{pad}" y1="{Ht-6-(Ht-14)}" x2="{Wd-pad}" y2="{Ht-6-(Ht-14)}" stroke="#1b2536" stroke-width="1" stroke-dasharray="3,4"/>'
            f'<text x="{Wd-pad-2}" y="{Ht-6-(Ht-14)+10}" fill="#5b6b82" font-size="10" text-anchor="end">100%</text>'
            f'<text x="{Wd-pad-2}" y="{Ht-9}" fill="#5b6b82" font-size="10" text-anchor="end">0%</text>')
    return f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none" style="display:block;margin-top:2px">{grid}{bars}</svg>'

def _equity_card(eq, at=None):
    setup = (
        '<div class="card"><h2>エクイティカーブ×21EMA（未設定）</h2>'
        '<div class="sub">口座資産の推移に21EMAを引き、割れたら新規停止・サイズ半減の判断材料にする。</div>'
        '<div class="note">有効化: リポジトリに <b>equity.csv</b> を置く。記録は<b onclick="goTab(\'t-alloc\')" style="cursor:pointer;text-decoration:underline">Positions「記録」</b>の📋ボタンで1行コピー→貼り付け。'
        '形式は1行1記録の「date,equity」または「date,equity,米株比率%」（カンマ区切り推奨・空白区切りも可）。新しい行は<b>末尾</b>に足す（並び順は自動整列するので前後しても可）。週1記録でも機能する。<br>'
        '<span class="mut">例:<br>date,equity<br>2026-06-30,10250000<br>2026-07-01,10180000</span></div></div>')
    if not eq:
        return setup
    if eq["above"]:
        _L = eq.get("ema_lab", "21日EMA")
        st_txt, st_cls = f"{_L}上 ・ 通常運転", "st-good"
        rule = f"エクイティカーブは{_L}の上。システムと相場の相性は正常。ルール通り継続。"
    else:
        _L = eq.get("ema_lab", "21日EMA")
        st_txt, st_cls = f"⚠ {_L}割れ（連続{eq['below_n']}記録）", "st-bad"
        rule = (f"<b>エクイティカーブが{_L}を下回っている（連続{eq['below_n']}記録・乖離{eq['gap']*100:+.1f}%）。</b>"
                "システムと今の相場の相性が悪化しているサイン。新規エントリー見送り・サイズ半減を検討し、"
                f"カーブが{_L}を回復するまで守りを優先（出血を止める）。")
    ys = [v for _, v in eq["ts"]]
    svg = _svg_two(ys, eq["ets"])
    expo = _svg_expo(eq.get("ups") or [], len(ys))
    expo_html = ""
    if expo:
        lastu = eq["ups"][-1][1]
        expo_html = (f'{expo}<div class="cap"><span class="mut">米株比率（青=高露出・空欄の日は非表示）</span>'
                     f'<span style="color:#7dd3fc;font-weight:700">直近 {lastu:.0f}%</span></div>')
    return (
        f'<div class="card"><h2>エクイティカーブ×{eq.get("ema_lab","21日EMA")}</h2>'
        f'<div class="sub">口座資産（equity.csv・{eq["n"]}記録）と、その{eq.get("ema_lab","21日EMA")}（記録点ベース）。追記は<b onclick="goTab(\'t-alloc\')" style="cursor:pointer;text-decoration:underline">Positions「記録」</b>から。'
        f'カーブ自体をトレードする: <b>EC&lt;{eq.get("ema_lab","21日EMA")}＝守り、EC&gt;{eq.get("ema_lab","21日EMA")}＝通常</b></div>'
        f'<div class="eqrow"><span class="dd"><span class="st {st_cls}">{st_txt}</span></span>'
        f'<span class="eqkv">乖離 <b class="{"pos" if eq["gap"]>=0 else "neg"}">{eq["gap"]*100:+.1f}%</b></span>'
        f'<span class="eqkv">高値からDD <b class="{"pos" if eq["dd"]>=-0.001 else "neg"}">{eq["dd"]*100:+.1f}%</b></span>'
        f'<span class="eqkv">直近21記録 <b class="{"pos" if eq["r20"]>=0 else "neg"}">{eq["r20"]*100:+.1f}%</b></span></div>'
        f'<div class="chart">{svg}'
        f'<div class="cap"><span>{eq["ts"][0][0]}</span>'
        f'<span style="color:#7ff0a8;font-weight:700">実線=口座 ・ 破線={eq.get("ema_lab","21日EMA")}</span>'
        f'<span>{eq["ts"][-1][0]}</span></div>'
        f'{expo_html}</div>'
        f'{_attrib_html(at)}'
        f'<div class="note">{rule} 露出バンドが高いまま資産が下がっていれば相場要因、露出が低いのに下がっていれば為替・記録タイミング要因の切り分けに使える。</div></div>')

# ----------------------------------------------------------------------------- state persistence + changelog + holdings trail
def load_state(strict=False, fail_closed=False):
    """strict=True（offline selftest）: 環境変数V38_STATE_JSONで明示されたファイルのみ読む。
       未指定ならデフォルト/mnt/project等へフォールバックせず{}を返す（fixtureの再現性確保）。
       fail_closed=True（本番）: 破損時は .prev 復元、無ければ停止（空stateでの自動上書きを防ぐ）。"""
    env_p = os.environ.get("V38_STATE_JSON")
    if strict:
        if env_p and os.path.exists(env_p):
            # 明示fixture(テスト)は破損/schema不一致なら停止する（再現性のため）。空フォールバックはテスト条件を変える。
            return _load_json_safe(env_p, {}, "state.json", fail_closed=True, validator=_validate_state_schema)
        return {}
    # 本番: 実stateは『拒否』でなく『修復』する。旧schemaで書かれた正当なファイルを落とさない（自動リセットもしない）。
    paths = [env_p, os.path.join(os.path.dirname(CACHE), "state.json"),
             "/mnt/project/state.json", "state.json"]
    p = next((x for x in paths if x and os.path.exists(x)), None)
    raw = None
    if p:
        raw = _load_json_raw(p)
        if raw is None:                                 # パース不能なら .prev を試す
            raw = _load_json_raw(p + ".prev")
            if raw is not None:
                sys.stderr.write("[state] %s parse失敗; .prev から復元\n" % p)
    else:
        for _base in [env_p, os.path.join(os.path.dirname(CACHE), "state.json")]:
            if _base and os.path.exists(_base + ".prev"):
                raw = _load_json_raw(_base + ".prev")
                if raw is not None:
                    sys.stderr.write("[state] 主stateなし; .prev から復元 (%s)\n" % (_base + ".prev"))
                break
    if raw is None:
        return {}
    clean = _sanitize_state(raw)
    if not _validate_state_schema(clean):               # 修復後も通らなければ空（壊滅）だが、通常はここに来ない
        sys.stderr.write("[state] 修復後もschema不一致; 空stateで継続（再生成されます）\n")
        return {}
    if isinstance(raw, dict) and len(clean) < len([k for k in raw if raw.get(k) is not None]):
        sys.stderr.write("[state] 一部の不正フィールドを除去して継続\n")
    return clean

def _atomic_write_json_with_prev(path, obj):
    """新JSONをtmpに書き切ってから、旧ファイルを.prevへ退避し、最後にtmpを本番へ置換。
       書き込み失敗時も旧ファイル/.prevのどちらかは必ず残る（空stateでの自動上書きを防ぐ・#5）。失敗時は例外。"""
    p = _Path(path)
    tmp = _Path(str(path) + ".tmp")
    prev = _Path(str(path) + ".prev")
    prev_tmp = _Path(str(path) + ".prev.tmp")
    d = str(p.parent)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:      # まず新版をtmpへ完全に書く（NaN/Infは弾く・#4）
        f.write(json.dumps(obj, ensure_ascii=False, allow_nan=False)); f.flush(); os.fsync(f.fileno())
    if p.exists():                                    # 旧版を .prev へ（コピー→置換で.prevも壊さない）
        import shutil as _sh
        _sh.copy2(str(p), str(prev_tmp))
        os.replace(str(prev_tmp), str(prev))
    os.replace(str(tmp), str(p))                      # 最後に本番を差し替え

def save_state(st):
    if os.environ.get("V38_FORCE_COMMIT_FAIL") == "state":
        raise IOError("forced state write failure (test hook)")
    outp = (os.environ.get("V38_STATE_JSON")
            or os.path.join(os.path.dirname(CACHE), "state.json"))
    _atomic_write_json_with_prev(outp, st)            # 失敗は呼び出し側(commit)で本番失敗扱いにする

def resolve_rebal_anchor(prev, asof_date):
    """隔週月曜サイクルの基準日。環境変数→state→当週月曜の順で固定する。"""
    for raw in (REBAL_ANCHOR_ENV, (prev or {}).get("rebal_anchor")):
        if raw:
            try:
                d = pd.Timestamp(raw).date()
                return d - dt.timedelta(days=d.weekday())
            except Exception:
                pass
    d = pd.Timestamp(asof_date).date()
    # 初回は「今日が月曜なら今日、それ以外は次の月曜」を第1回にする。
    # 旧版の初回表示と同じ挙動にし、その後はstateへ固定する。
    return d + dt.timedelta(days=(-d.weekday()) % 7)

def _nyse_holidays(year):
    """当年のNYSE休場日(観測日ルール込み)を返す。祝日が土曜→前金曜、日曜→翌月曜に振替。
       固定祝日＋MLK/Presidents/Memorial/Labor/Thanksgiving（第n曜日）＋Good Friday。"""
    import datetime as _dt
    def _obs(d):
        if d.weekday() == 5: return d - _dt.timedelta(days=1)
        if d.weekday() == 6: return d + _dt.timedelta(days=1)
        return d
    def _nth_weekday(y, m, weekday, n):
        d = _dt.date(y, m, 1)
        d += _dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + _dt.timedelta(weeks=n - 1)
    def _last_weekday(y, m, weekday):
        d = (_dt.date(y, m + 1, 1) - _dt.timedelta(days=1)) if m < 12 else _dt.date(y, 12, 31)
        while d.weekday() != weekday: d -= _dt.timedelta(days=1)
        return d
    def _easter(y):
        a = y % 19; b = y // 100; c = y % 100; d = b // 4; e = b % 4
        f = (b + 8) // 25; g = (b - f + 1) // 3; h = (19 * a + b - d - g + 15) % 30
        i = c // 4; k = c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7
        mth = (h + l - 7 * ((a + 11 * h + 22 * l) // 451) + 114) // 31
        day = ((h + l - 7 * ((a + 11 * h + 22 * l) // 451) + 114) % 31) + 1
        return _dt.date(y, mth, day)
    hols = set()
    hols.add(_obs(_dt.date(year, 1, 1)))                  # New Year
    hols.add(_nth_weekday(year, 1, 0, 3))                 # MLK (3rd Mon Jan)
    hols.add(_nth_weekday(year, 2, 0, 3))                 # Presidents (3rd Mon Feb)
    hols.add(_easter(year) - dt.timedelta(days=2))        # Good Friday
    hols.add(_last_weekday(year, 5, 0))                   # Memorial (last Mon May)
    if year >= 2022: hols.add(_obs(_dt.date(year, 6, 19)))  # Juneteenth
    hols.add(_obs(_dt.date(year, 7, 4)))                  # Independence Day
    hols.add(_nth_weekday(year, 9, 0, 1))                 # Labor (1st Mon Sep)
    hols.add(_nth_weekday(year, 11, 3, 4))               # Thanksgiving (4th Thu Nov)
    hols.add(_obs(_dt.date(year, 12, 25)))               # Christmas
    return hols

def _next_us_trading_day(d, include_today=True):
    """d以降(include_today=Falseなら翌日以降)で、最初の米国取引日(平日かつNYSE非休場)を返す。"""
    import datetime as _dt
    cur = pd.Timestamp(d).date()
    if not include_today:
        cur += _dt.timedelta(days=1)
    for _ in range(370):
        if cur.weekday() < 5 and cur not in _nyse_holidays(cur.year):
            return cur
        cur += _dt.timedelta(days=1)
    return cur

def is_rebalance_date(d, anchor):
    """d が隔週リバランスの「実施セッション」か。基準は anchor から14日毎の月曜だが、
       その月曜が米国休場なら振替後の最初の取引日を実施日とする（火曜通知漏れを防ぐ・#11）。"""
    d = pd.Timestamp(d).date(); anchor = pd.Timestamp(anchor).date()
    delta = (d - anchor).days
    if delta < 0:
        return False
    k = delta // 14
    import datetime as _dt
    for kk in (k - 1, k, k + 1):
        if kk < 0:
            continue
        cycle_mon = anchor + _dt.timedelta(days=14 * kk)
        if _next_us_trading_day(cycle_mon, include_today=True) == d:
            return True
    return False

def next_rebalance_date(d, anchor, include_today=False):
    d, anchor = pd.Timestamp(d).date(), pd.Timestamp(anchor).date()
    cur = d if include_today else d + dt.timedelta(days=1)
    cur += dt.timedelta(days=(-cur.weekday()) % 7)
    while (cur - anchor).days < 0 or (cur - anchor).days % 14:
        cur += dt.timedelta(days=7)
    # #11 対象月曜が米国休場なら、その日以降の最初の取引セッションをリバランス日とする
    return _next_us_trading_day(cur, include_today=True)

def _summ(st):
    return dict(date=st.get("date"), gate=st.get("gate"), mri=st.get("mri"),
                bear_lit=st.get("bear_lit", []), senti_flags=st.get("senti_flags", []),
                picks=st.get("picks", []),
                soxl_band=st.get("soxl_band"), turnover=st.get("turnover"), updown=st.get("updown"),
                emergency=st.get("emergency"))

def core_continuation_rank(m):
    """#2 継続順位の唯一の定義。Core 12の【選定母集団 cand と同一】＝
       sma50>sma200・売買代金≥DVOL_FLOOR・株価≥5・189日RS≥85 の中で rs189 降順ランク。
       継続判定は rank <= 2*N_PORT。track_holdings・F1(脱落率)・ポート表の継続境界(floor)が
       すべて同じ母集団を使うことで、タブ間・実ポジション判定でズレないようにする。プール外は NaN。
       列が欠けている文脈では、存在する条件だけで母集団を作る（過度に厳しくしない）。"""
    try:
        if m is None or getattr(m, "columns", None) is None or "rs189" not in m.columns:
            return pd.Series(np.nan, index=getattr(m, "index", []))
        elig = m["rs189"].notna() & (m["rs189"] >= 85)   # 189日RS≥85（cand と一致）
        if "sma50" in m.columns and "sma200" in m.columns:
            elig = elig & m["sma50"].notna() & m["sma200"].notna() & (m["sma50"] > m["sma200"])
        if "dvol" in m.columns:
            elig = elig & (m["dvol"] >= DVOL_FLOOR)
        if "close" in m.columns:
            elig = elig & (m["close"] >= 5)
        rank = pd.Series(np.nan, index=m.index)
        if bool(elig.any()):
            rank.loc[elig] = m.loc[elig, "rs189"].rank(ascending=False, method="min")
        return rank
    except Exception:
        return pd.Series(np.nan, index=getattr(m, "index", []))


def track_holdings(prev, picks, color, asof_date, m=None, rebal_anchor=None, closes=None):
    """建値・ピーク・正式出口を継承し、継続割れを次の隔週月曜まで追跡する。
       #3: closes(終値DataFrame)を渡すと、ピークはエントリー日以降の終値履歴の最大から再計算
       （ダッシュボード未実行日を含めて取りこぼさない）。asof日で切った履歴を渡すこと。"""
    today = str(asof_date)
    tf = 0.70
    prev_hold = (prev or {}).get("hold", {}) or {}
    hold, hv, losses, carry = {}, {}, [], []
    anchor = rebal_anchor or resolve_rebal_anchor(prev, asof_date)
    # #1/#2: 実保有は「リバランス日・赤→青緑復帰・初回」だけ現在のCore 12を取り込む。
    #   非リバランス日/黄は前回保有を継続（新規を自動追加しない）、赤は撤退（保有ゼロ）。
    try:
        _is_rebal = is_rebalance_date(asof_date, anchor)
    except Exception:
        _is_rebal = False
    _recovery = ((prev or {}).get("gate") == "Red" and color in ("Blue", "Green"))
    _take_new = (color in ("Blue", "Green")) and (_is_rebal or _recovery or (not prev_hold))
    _pick_rows = {t: r for t, _, r in picks}
    if color == "Red":
        active = []
    elif _take_new:
        # #1/#2: リバランス日は「継続条件(上位2Nのsma50>sma200 & rs189)を満たす旧保有」を残し、
        #   空いた枠だけ現在の候補で補充。旧保有を無条件に再追加しないので必ず最大N_PORT（13銘柄化を防ぐ）。
        _cont_rank = core_continuation_rank(m) if (m is not None and getattr(m, "index", None) is not None) else None
        survivors = []
        for _t in prev_hold:
            if _cont_rank is not None and _t in _cont_rank.index:
                _cr = _cont_rank.get(_t)
                _cont = (pd.notna(_cr) and float(_cr) <= 2 * N_PORT)
                if _cont:
                    survivors.append((_t, "", m.loc[_t] if _t in m.index else (_pick_rows.get(_t))))
            elif _t in _pick_rows:
                survivors.append((_t, "", _pick_rows[_t]))
        survivors = survivors[:N_PORT]
        _surv_set = {t for t, _, _ in survivors}
        _fill = [(t, th, r) for (t, th, r) in picks if t not in _surv_set]
        active = survivors + _fill[:max(0, N_PORT - len(survivors))]
        carry = [t for t, _, _ in survivors if t not in _pick_rows]
    else:
        active = []
        for _t in prev_hold:                       # 非リバランス日/黄：前回保有を継続（現在データはm優先・候補で補完）
            if m is not None and getattr(m, "index", None) is not None and _t in m.index:
                active.append((_t, "", m.loc[_t]))
            elif _t in _pick_rows:
                active.append((_t, "", _pick_rows[_t]))
    active = active[:N_PORT]                        # 安全弁：常に最大N_PORT銘柄
    pick_set = {t for t, _, _ in active}

    def _due_date(base):
        return next_rebalance_date(base, anchor, include_today=is_rebalance_date(base, anchor))

    def _process(t, px):
        ph = prev_hold.get(t) or {}
        try:
            ed = str(ph.get("ed") or today); ep = float(ph.get("ep", px)); peak = max(float(ph.get("peak", px)), px)
        except Exception:
            ed, ep, peak = today, px, px
        # #3: エントリー日以降の終値履歴の最大でピークを再計算（未実行日を取りこぼさない）
        try:
            if closes is not None and t in getattr(closes, "columns", []):
                _ch = closes[t].loc[str(ed):].dropna()
                if len(_ch):
                    peak = max(peak, float(_ch.max()))
        except Exception:
            pass
        init_stop = ep * 0.75
        wide_stop = peak * tf if peak > 0 else 0.0
        stop = max(init_stop, wide_stop)
        R = ep - init_stop
        t3 = ep + 3.0 * R if R > 0 else None
        try:
            days = _session_days(ed)          # #10 実取引セッション基準（米国祝日を含めない）。np.busday_countは土日のみ除外だった
            if not days or days < 1:
                days = 1
        except Exception:
            days = 1
        hold[t] = dict(ed=ed, ep=round(ep,4), peak=round(peak,4), istop=round(init_stop,4))
        for k in ("sell_due","sell_due_date"):
            if ph.get(k) is not None: hold[t][k]=ph.get(k)
        hv[t] = dict(days=days, stop=stop, dist=(px/stop-1 if stop>0 else np.nan),
                     which=("ピーク×0.70" if wide_stop >= init_stop and wide_stop > 0 else "建値×0.75"),
                     istop=init_stop, t3=t3, hit3=bool(t3 is not None and px>=t3), R=R)
        if hold[t].get("sell_due"):
            hv[t]["sell_due"]=True; hv[t]["sell_due_date"]=hold[t].get("sell_due_date")
        if px>0: losses.append(max(0.0,(px-stop)/px))

    for t, _, r in active:
        try: _process(t,float(r["close"]))
        except Exception: continue

    # #8: 固定12枠・等ウェイト前提。各保有はスリーブの1/12を占める。
    #   ヒート＝Σ(現値→ストップ距離)×個別配分/枠数（保有が少ない時に過大にならない）
    heat=(float(np.sum(losses))*ALLOC[0]/100.0/N_PORT) if losses else None
    return hold,hv,heat,tf,carry

def build_changelog(prev, color, aux, senti, picks, asof_date,
                    soxl_ok=None, turnover_dir=None, updown_reg=None, emergency_active=None):
    """前回（別日）比の変化リスト。(lines, ref_date, major)を返す。"""
    today = str(asof_date)
    base = prev if (prev and prev.get("date") and prev["date"] != today) else (prev or {}).get("prevday")
    if not base or not base.get("date"):
        return [], None, False
    ch, major = [], False
    pg, cg = base.get("gate"), color
    if emergency_active is not None:
        _pe = bool(((base.get("emergency") or {}).get("active")))
        _ce = bool(emergency_active)
        if _pe != _ce:
            ch.append("非常口 <b>" + ("発動・レバ半減" if _ce else "解除・レバ通常") + "</b>")
            major = True
    if pg and cg and pg != cg:
        ch.append(f'地合い <b>{_COLOR_JP.get(pg, pg)}→{_COLOR_JP.get(cg, cg)}</b> → 翌寄りで露出調整')
        major = True
    try:
        dm = float(aux["cur"]) - float(base.get("mri", aux["cur"]))
        if abs(dm) >= 3:
            ch.append(f'地合いスコア <b>{base.get("mri"):.0f}→{aux["cur"]:.0f}</b>（{dm:+.0f}）')
    except Exception:
        pass
    pt, ct = set(base.get("picks") or []), {t for t, _, _ in picks}
    inn, out = sorted(ct - pt), sorted(pt - ct)
    if inn:
        ch.append("ポートフォリオ IN: <b>" + " ".join(inn) + "</b>")
        major = True
    if out:
        ch.append("ポートフォリオ OUT: <b>" + " ".join(out) + "</b>")
        major = True
    pb = set(base.get("bear_lit") or [])
    cb = {lab for lab, on in aux.get("bear_flags", []) if on}
    nb, cbk = sorted(cb - pb), sorted(pb - cb)
    if nb:
        ch.append("警戒 新点灯: " + "・".join(_h(x) for x in nb))   # state起点の保存型XSSを描画時にエスケープ
        major = True
    if cbk:
        ch.append("警戒 消灯: " + "・".join(_h(x) for x in cbk))
    ps = set(base.get("senti_flags") or [])
    cs = {l for l, on in (senti or {}).get("flags", []) if on}
    ns = sorted(cs - ps)
    if ns:
        ch.append("センチメント 新点灯: " + "・".join(_h(x) for x in ns))
        major = True
    # SOXL投入帯の切替（配分計算にも自動連動）
    if soxl_ok is not None:
        cur_band = "投入帯" if soxl_ok else "帯外"
        prev_band = base.get("soxl_band")
        if prev_band and prev_band != cur_band:
            if soxl_ok:
                ch.append("SOXL投入帯に入った → 段階投入 解禁（1/3ずつ）")
            else:
                ch.append("SOXL投入帯を外れた → 新規停止・全額TQQQ")
            major = True
    # 売買代金レジーム（拡大/縮小の転換のみ）
    pt2 = base.get("turnover")
    if pt2 and turnover_dir and pt2 != turnover_dir and turnover_dir in ("拡大", "縮小"):
        ch.append(f'売買代金 <b>{_h(pt2)}→{_h(turnover_dir)}</b>' + ("（参加が厚く）" if turnover_dir == "拡大" else "（参加細り・要注意）"))
        if turnover_dir == "縮小":
            major = True
    # 集積/分散レジーム（O'Neil式）
    pu = base.get("updown")
    if pu and updown_reg and pu != updown_reg:
        lab = "集積（買い集め優勢）" if updown_reg == "accum" else "分散（売り抜け優勢）"
        ch.append(f"集積/分散が <b>{lab}</b> に転換")
        major = True
    return ch, base.get("date"), major

def _changelog_card(ch, ref):
    if ref is None:
        body = '<div class="sub">初回記録。次回ビルドから前回比の変化をここに表示する。</div>'
    elif not ch:
        body = f'<div class="sub">前回（{ref}）から重要な変化なし。保有維持・トレール/ストップのみ対応。</div>'
    else:
        body = ('<ul class="chlog">' + "".join(f"<li>{x}</li>" for x in ch) + "</ul>"
                + f'<div class="note">比較基準: {ref}</div>')
    return f'<div class="card ch-card"><h2>前回からの変化</h2>{body}</div>'

def post_webhook(lines, color):
    if not _net_ok():
        return "skipped"
    url = os.environ.get("V38_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK")
    if not url or not lines:
        return "skipped"
    try:
        import urllib.request, re as _re
        txt = ("【V38】NQ:" + (_COLOR_JP.get(color, "—") if color else "—") + "\n"
               + "\n".join("・" + _re.sub("<[^>]+>", "", x) for x in lines))
        req = urllib.request.Request(url, data=json.dumps({"content": txt[:1900]}).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "v38-dashboard"})
        urllib.request.urlopen(req, timeout=8)
        sys.stderr.write("[webhook] sent %d lines\n" % len(lines))
        return "ok"
    except Exception as e:
        sys.stderr.write("[webhook] failed: %r\n" % repr(e)[:90])
        return "failed"

def _build_log_csv_content(path, asof_date, color, aux, senti, picks):
    today = str(asof_date)
    rows = []
    if os.path.exists(path):
        rows = [ln for ln in open(path).read().splitlines()
                if ln and not ln.startswith(today + ",") and not ln.startswith("date,")]
    line = ",".join([today, color or "", f"{aux['cur']:.1f}", str(aux["bear_n"]),
                     (f"{senti['cur']:.1f}" if senti else ""),
                     " ".join(t for t, _, _ in picks)])
    return "\n".join(["date,gate,mri,bear_n,senti,picks"] + rows + [line]) + "\n"

def append_log_csv(asof_date, color, aux, senti, picks):
    p = os.environ.get("V38_LOG_CSV") or os.path.join(os.path.dirname(CACHE), "daily_log.csv")
    atomic_write_text(p, _build_log_csv_content(p, asof_date, color, aux, senti, picks))

def _commit_state_trend_log(state_obj, trend_hist, log_content):
    """#5/#7 運用状態のトランザクションcommit。
       Phase1: state/trend/logを全てtmpへ書き切る（NaN混入は例外）。
       Phase1.5: tmpをschema検証（不正なら何も置換しない）。
       Phase2: 旧内容をメモリ退避しつつ trend→log→state の順で置換。途中で失敗したら、
               既に置換済みのファイルを旧内容へロールバックして本番の整合性を保つ（部分commitを残さない）。"""
    import shutil as _sh
    sp = (os.environ.get("V38_STATE_JSON") or os.path.join(os.path.dirname(CACHE), "state.json"))
    tp = _trend_history_path()
    lp = (os.environ.get("V38_LOG_CSV") or os.path.join(os.path.dirname(CACHE), "daily_log.csv"))
    _force = os.environ.get("V38_FORCE_COMMIT_FAIL")   # "state"|"trend"|"log": その置換段で失敗させ、ロールバックを検証
    specs = [(sp, json.dumps(state_obj, ensure_ascii=False, allow_nan=False)),   # NaN/Infを含むstateは保存前に例外（#4）
             (tp, json.dumps(trend_hist, ensure_ascii=False, allow_nan=False)),
             (lp, log_content)]
    tmps = []
    replaced = []   # [(path, old_bytes_or_None)] 既に本番へ置換した分（失敗時に戻す）
    try:
        # Phase1: 全てtmpへ書き切る（fsync）。1つでも失敗したらtmpを消して何も置換しない。
        for _path, _text in specs:
            _d = os.path.dirname(_path)
            if _d: os.makedirs(_d, exist_ok=True)
            _tmp = _path + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as _f:
                _f.write(_text); _f.flush(); os.fsync(_f.fileno())
            tmps.append((_path, _tmp))
        # Phase1.5: tmpの中身をschema検証（壊れた新版で本番を上書きしない）
        _sv = _load_json_safe(sp + ".tmp", None, "state.tmp", fail_closed=False, validator=_validate_state_schema)
        if _sv is None:
            raise ValueError("state tmp failed schema validation")
        _tv = _load_json_safe(tp + ".tmp", None, "trend.tmp", fail_closed=False, validator=_validate_trend_schema)
        if _tv is None:
            raise ValueError("trend tmp failed schema validation")
        # Phase2: 旧内容を退避しつつ trend→log→state 順で置換。失敗したら既置換分を復元。
        order = [(tp, "trend"), (lp, "log"), (sp, "state")]
        by_path = {_p: _t for _p, _t in tmps}
        for _path, _name in order:
            _old = None
            if os.path.exists(_path):
                with open(_path, "rb") as _rf:
                    _old = _rf.read()
                try: _sh.copy2(_path, _path + ".prev")
                except Exception: pass
            if _force == _name:                        # テストフック: この段で失敗させる
                raise IOError("forced %s replace failure (test hook)" % _name)
            os.replace(by_path[_path], _path)
            replaced.append((_path, _old))
    except Exception:
        # 既に置換済みのファイルを旧内容へ戻す（部分commitを残さない・#7）
        for _path, _old in reversed(replaced):
            try:
                if _old is None:
                    if os.path.exists(_path): os.remove(_path)
                else:
                    with open(_path + ".rollback", "wb") as _wf:
                        _wf.write(_old); _wf.flush(); os.fsync(_wf.fileno())
                    os.replace(_path + ".rollback", _path)
            except Exception as _re:
                sys.stderr.write("[commit] rollback failed for %s: %r\n" % (_path, repr(_re)[:80]))
        for _p, _t in tmps:                            # 残ったtmpを掃除
            try:
                if os.path.exists(_t): os.remove(_t)
            except Exception: pass
        raise

# ----------------------------------------------------------------------------- portfolio correlation / effective N
def portfolio_corr(W, tickers):
    try:
        cols = [t for t in tickers if t in W["Close"].columns]
        if len(cols) < 3:
            return None
        r = W["Close"][cols].pct_change(fill_method=None).iloc[-60:]
        cm = r.corr().values
        n = cm.shape[0]
        iu = np.triu_indices(n, 1)
        rho = float(np.nanmean(cm[iu]))
        neff = n / (1 + (n - 1) * max(rho, 0.0))
        return dict(rho=rho, neff=neff, n=n)
    except Exception:
        return None

# ----------------------------------------------------------------------------- earnings dates (保有+控えのみ・キャッシュ)
def _er_next(rec):
    """earningsキャッシュのレコード(旧: 日付文字列 / 新: dict)から次回決算日文字列を取り出す。無ければNone。"""
    if isinstance(rec, str):
        return rec or None
    if isinstance(rec, dict):
        return rec.get("next_earnings")
    return None

def load_earnings(tickers, live, strict=False):
    env_p = os.environ.get("V38_ER_JSON")
    if strict:
        paths = [env_p] if env_p else []
    else:
        paths = [env_p, os.path.join(os.path.dirname(CACHE), "earnings.json")]
    p = next((x for x in paths if x and os.path.exists(x)), None)
    cache = {}
    if p:
        try:
            cache = json.load(open(p))
        except Exception:
            cache = {}
    if live and _net_ok():
        try:
            import yfinance as yf, time as _t
            today = pd.Timestamp.today().normalize()
            def needs_fetch(t):
                rec = cache.get(t)
                if rec is None:
                    return True                              # 未取得（空キャッシュ）→ 取得（#4の核心）
                if isinstance(rec, str):
                    try: return pd.Timestamp(rec) < today    # 旧形式: 過去日なら再取得
                    except Exception: return True
                if isinstance(rec, dict):
                    ca = rec.get("checked_at")
                    if not ca:
                        return True
                    try: return (today - pd.Timestamp(ca)).days >= 1   # 1日以上前の確認なら再取得
                    except Exception: return True
                return True
            todo = [t for t in tickers if needs_fetch(t)][:40]
            t0 = _t.time()
            _tday = str(today.date())
            for t in todo:
                if _t.time() - t0 > 120:
                    break
                try:
                    cal = yf.Ticker(t).calendar
                    d = None
                    if isinstance(cal, dict):
                        ds = cal.get("Earnings Date") or []
                        d = ds[0] if ds else None
                    elif cal is not None and hasattr(cal, "loc"):
                        try:
                            d = cal.loc["Earnings Date"][0]
                        except Exception:
                            d = None
                    if d is not None:
                        cache[t] = {"next_earnings": str(pd.Timestamp(d).date()), "checked_at": _tday, "status": "ok"}
                    else:
                        cache[t] = {"next_earnings": None, "checked_at": _tday, "status": "no_date"}   # 予定なしを記録（未取得と区別）
                except Exception:
                    continue
            outp = p or os.environ.get("V38_ER_JSON") or os.path.join(os.path.dirname(CACHE), "earnings.json")
            _defer_cache_write(outp, cache)   # #6 保留→selftest後にflush
        except Exception:
            pass
    return cache

def _er_badge(t, er, asof_bar):
    try:
        d = pd.Timestamp(_er_next((er or {}).get(t)))
        n = (d.normalize() - pd.Timestamp(asof_bar).normalize()).days
        if 0 <= n <= 8:
            return f'<span class="erb">決算{"当日" if n == 0 else f"{n}日"}</span>'
    except Exception:
        pass
    return ""

def _risk_note(mkt):
    """ポートフォリオ・ヒート（全トレール同時発動の想定毀損）＋相関・実効N。"""
    heat, corr = mkt.get("heat"), mkt.get("corr")
    bits = []
    if heat is not None:
        hcls = "neg" if heat >= 0.12 else ("mut" if heat >= 0.07 else "pos")
        bits.append(f'ポートフォリオ・ヒート: 全トレール同時発動で想定 <b class="{hcls}">−{heat*100:.1f}%</b>（NAV比・個別スリーブ{ALLOC[0]}%換算）')
    if corr:
        ccls = "neg" if corr["rho"] >= 0.65 else ("mut" if corr["rho"] >= 0.45 else "pos")
        bits.append(f'60日ペア相関 平均 <b class="{ccls}">{corr["rho"]:.2f}</b> → 実効銘柄数(近似) <b>{corr["neff"]:.1f}</b>/{corr["n"]}'
                    f'（相関が高いほど「{corr["n"]}銘柄」でなく単一ベータに近づく）')
    if not bits:
        return ""
    return '<div class="note risknote">' + '<br>'.join(bits) + '</div>'

def _rs_arrow(d, th=2):
    """RSランクの変化矢印（ローテーション初動の可視化）。th=表示閾値。"""
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return ""
    if d >= th:
        return f'<span class="rsd up">▲{d:.0f}</span>'
    if d <= -th:
        return f'<span class="rsd dn">▼{abs(d):.0f}</span>'
    return '<span class="rsd fl">·</span>'

def _adr_badge(adr):
    """ADR(20日平均日中値幅%)が最適レンジ 3.5〜8% の外なら印。低=鈍い/高=荒い。表示のみ・選定は"""
    if adr is None or (isinstance(adr, float) and adr != adr):
        return ""
    a = adr * 100.0
    if a < 3.5:
        return f'<span class="adrb adr-lo" title="ADRが低い＝値幅が小さく伸びにくい">ADR {a:.1f}%↓</span>'
    if a > 8.0:
        return f'<span class="adrb adr-hi" title="ADRが高い＝値幅が荒くストップに掛かりやすい">ADR {a:.1f}%↑</span>'
    return ""

def _noise_badge(adr, dist, horizon=21):
    """出口線が実現ボラ(ADR)の約1ヶ月1σ想定変動より内側なら「出口ノイズ内」印（=タイトで振り落とされやすい）。"""
    if adr is None or adr != adr or dist is None or dist != dist:
        return ""
    em = float(adr) * 0.55 * float(np.sqrt(horizon))          # ~1ヶ月 1σ（ADR実現ボラ）
    if float(dist) < em:
        return ('<span class="adrb adr-hi" '
                'title="出口線が想定変動(1σ)の内側＝通常のノイズで振り落とされやすい">出口ノイズ内</span>')
    return ""

def _entry_badge(rs, close, ema21):
    """RS階層別エントリー枠（21EMAからの距離ゾーン×RS階層の妥当性）。
       検証(2026-07-07): RS97+はゾーン内(−1〜+4%)が最良+0.53R・伸びを追うと最低+0.32R→枠を広げない。
       RS90-97はゾーン優先。RS75-90は位置ほぼ不問(+0.46〜0.54R)。低リスク/タイトストップ要件は不変。"""
    try:
        rs = float(rs); close = float(close); ema21 = float(ema21)
    except Exception:
        return ""
    if not (ema21 > 0) or rs != rs:
        return ""
    d = close / ema21 - 1
    pos = ("21EMA下" if d < -0.01 else "ゾーン内" if d <= 0.04 else
           "やや伸び" if d <= 0.07 else "伸び切り" if d <= 0.12 else "過伸長")
    note = ""
    if d > 0.12:                                    # 過伸長はどの階層でも見送り寄り
        cls, mark = "ent-warn", "△"
    elif rs >= 97:                                  # 最強クラス: ゾーン内が最良・伸びは追わない
        if -0.01 <= d <= 0.04:
            cls, mark, note = "ent-good", "◎", "最良帯"
        elif d > 0.04:
            cls, mark, note = "ent-bad", "×", "RS97+は追わない"
        else:
            cls, mark = "ent-ok", "○"
    elif rs >= 90:                                  # ゾーン優先
        cls, mark = ("ent-good", "◎") if (-0.01 <= d <= 0.04) else ("ent-ok", "○")
    else:                                           # RS75-90: 位置ほぼ不問
        cls, mark = ("ent-good", "◎") if (-0.01 <= d <= 0.04) else ("ent-ok", "○")
    tip = f"21EMA {d*100:+.0f}%・{pos}" + (f"・{note}" if note else "")
    return f'<span class="entb {cls}" title="{tip}">{mark} {pos}</span>'

def _fade_badge(r):
    """防御アラート: 189日RSはまだ強い(≥80)のに短期(63日/21日)RSが細り＝勢い低下の初動。
       順張りの"降り遅れ"対策の早期警戒（自動売却はしない・降りは確定出口線で）。"""
    try:
        rs189 = float(r.get("rs189")); rs63 = float(r.get("rs"))
        rs21 = float(r.get("rs21")); dd = float(r.get("rs63_d"))
    except Exception:
        return ""
    if rs189 != rs189 or rs189 < 80:
        return ""
    sev = 0
    if dd == dd and dd <= -8: sev += 1                       # 63日RSが1週で8ランク以上低下
    if rs63 == rs63 and rs63 <= rs189 - 20: sev += 1         # 短期が長期より20ランク以上弱い（乖離）
    if rs21 == rs21 and rs63 == rs63 and rs21 <= rs63 - 15: sev += 1  # 21日が63日よりさらに弱い（加速）
    if sev == 0:
        return ""
    if sev >= 2:
        return ('<span class="fadeb fade-hi" '
                'title="189日RSは強いが短期RSが明確に細り＝勢い低下。降りどき警戒（出口線を引き上げ or 部分利確）">勢い細り⚠</span>')
    return ('<span class="fadeb fade-lo" '
            'title="短期RSがやや細り＝要観察">勢い細り</span>')

def _rs_cell(r):
    """RSセル（期間トグル対応）。既定は189日、タップで63日/21日に切替（.rsv を JS が書換）。"""
    def f(k):
        v = r.get(k)
        try:
            return f'{float(v):.0f}' if v == v else '—'
        except Exception:
            return '—'
    v189, v63, v21 = f("rs189"), f("rs"), f("rs21")
    return (f'<span class="rsv" data-p21="{v21}" data-p63="{v63}" data-p189="{v189}">{v189}</span>'
            f'{_rs_arrow(r.get("rs63_d"), th=8)}')

# ----------------------------------------------------------------------------- セクターローテーション (RRG風・SPY相対)
# RRG ETFテーマ名 → 属するs2tサブテーマ(部分一致キーワード)。チップタップ展開用。
RRG_TO_SUB = {
    "半導体": ["半導体", "ファブレス", "パワー半導体", "アナログ", "EDA", "EMS", "電子製造受託"],
    "半導体装置": ["半導体製造装置", "製造装置"],
    "データセンター": ["データセンター", "AIサーバー", "冷却", "HPC"],
    "ソフトウェア": ["ソフトウェア", "SaaS"],
    "サイバー": ["サイバー"],
    "AI": ["AI GPU", "AIアナリティクス", "AIエッジ", "AIエンタープライズ", "AIデータ基盤", "AIハイパースケーラー", "AI光接続", "フォトニクス", "量子"],
    "バイオテック": ["バイオ"],
    "医療機器": ["医療機器"],
    "銀行": ["銀行"],
    "証券": ["証券", "資産運用"],
    "石油探査": ["E&P", "探査", "ミッドストリーム", "石油精製"],
    "油田": ["オイルフィールド", "石油機器", "石油装置"],
    "金鉱": ["金鉱"],
    "金属": ["金属", "レアアース", "チタン", "鉄鋼", "鉱業"],
    "ウラン": ["ウラン", "SMR", "原発", "原子力"],
    "防衛": ["防衛", "軍事"],
    "インフラ": ["インフラ", "電力設備", "送配電", "建設"],
    "運輸": ["海運", "トラック", "輸送", "航空"],
}

def build_theme_hierarchy(m, s2t):
    """大テーマ(表示名)→サブテーマ群のローテ+構成銘柄。RRGチップ(大テーマ)のjaキーと一致。
       全367サブテーマが必ず親を持つ(取りこぼしゼロ)。63×189日RS中央値で粒度統一。"""
    from collections import defaultdict
    big = defaultdict(lambda: defaultdict(list))   # theme_disp -> subtheme -> [tickers]
    for t in m.index:
        v = s2t.get(t)
        if not v or len(v) < 2 or not v[0] or not v[1]:
            continue
        disp = v[0].split(". ", 1)[-1] if ". " in v[0] else v[0]
        big[disp][v[1]].append(t)
    def _agg(tickers):
        sub_m = m.loc[[t for t in tickers if t in m.index]]
        if len(sub_m) == 0:
            return None
        med63 = float(np.nanmedian(sub_m["rs"])) if "rs" in sub_m else np.nan
        med189 = float(np.nanmedian(sub_m["rs189"])) if "rs189" in sub_m else med63
        prev = float(np.nanmedian(sub_m["rs_l1"])) if "rs_l1" in sub_m else med63
        drs = (med63 - prev) if (med63 == med63 and prev == prev) else 0.0
        members = sorted(((t, float(m.at[t, "rs189"]) if ("rs189" in m.columns and t in m.index) else np.nan)
                          for t in tickers), key=lambda x: -(x[1] if x[1] == x[1] else -9))
        q = ("主導" if (med189 >= 60 and drs >= 0) else "弱化" if med189 >= 60 else
             "改善" if drs >= 0 else "停滞")
        return dict(rs=round(med189) if med189 == med189 else 0, drs=round(drs, 1), n=len(sub_m), q=q,
                    members=[{"t": t, "rs": round(r) if r == r else None} for t, r in members[:20]])
    out = {}
    for disp, subs in big.items():
        arr = []
        for sub, tks in subs.items():
            a = _agg(tks)
            if a:
                a["sub"] = sub
                arr.append(a)
        if arr:
            arr.sort(key=lambda z: -z["rs"])
            out[disp] = arr
    return out

def build_etf_hier(m, s2t, min_n=2):
    """ETF → 大分類 → 詳細セクター(状態別) → 構成銘柄。ETFの日本語名をキーに返す。
       詳細セクターの状態は構成銘柄のRS189中央値(x)と、その5日変化(y=勢い)で四象限判定。
       ETF→大分類は実保有の重み付き多数決（低カバレッジ時は超過リターン相関）で決定。表示専用の導線。"""
    from collections import defaultdict
    if "rs189" not in m.columns:
        return {}
    det = defaultdict(list); big_of = {}
    for t in m.index:
        v = s2t.get(t)
        if not v or len(v) < 2 or not v[0] or not v[1]:
            continue
        det[v[1]].append(t); big_of[v[1]] = v[0]
    have_l5 = "rs189_l5" in m.columns
    big = defaultdict(list)
    for name, tks in det.items():
        idxs = [t for t in tks if t in m.index]
        sub = m.loc[idxs]
        rs = sub["rs189"].dropna()
        if len(rs) < min_n:
            continue
        x = float(rs.median()); y = 0.0
        if have_l5:
            prev = sub["rs189_l5"].dropna()
            if len(prev) >= min_n:
                y = x - float(prev.median())
        q = "主導" if (x >= 50 and y >= 0) else "弱化" if x >= 50 else "改善" if y >= 0 else "停滞"
        top = sub["rs189"].sort_values(ascending=False).head(12)
        members = [dict(t=t, rs=int(round(float(v)))) for t, v in top.items() if v == v]
        big[big_of[name]].append(dict(sub=name, q=q, rs=int(round(x)), drs=int(round(y)),
                                      n=len(idxs), members=members))
    order = {"主導": 0, "改善": 1, "弱化": 2, "停滞": 3}
    for k in big:
        big[k].sort(key=lambda d: (order[d["q"]], -d["rs"]))
    # ETF日本語名 → その大分類の詳細セクター群
    ja_of = {tk: ja for tk, ja in MICRO_ETFS}
    out = {}
    for etf, bg in ETF_TO_BIG.items():
        subs = big.get(bg)
        ja = ja_of.get(etf)
        if subs and ja:
            out[ja] = subs
    return out

def build_rrg_etf(macro, extras, win=63, mom=10, themes=None):
    """【大枠・市場全体】テーマETFのSPY相対力(63日基準)×その10日モメンタムで4象限。
       市場全体のセクター資金フローを見る古典的RRG。themes未指定なら主要18テーマ(RRG_THEMES)。"""
    b = macro.get("SPY")
    if b is None:
        return []
    bc = b["Close"].dropna()
    pts = []
    for tk, ja in (themes if themes is not None else RRG_THEMES):
        sc = extras.get(tk)
        if sc is None:
            d = macro.get(tk); sc = d["Close"] if d is not None else None
        if sc is None:
            continue
        sc = sc.dropna()
        r = (sc / bc).dropna()
        if len(r) < win + mom + 15:
            continue
        ratio = (100 * r / r.rolling(win).mean()).dropna()
        if len(ratio) < mom + 12:
            continue
        mser = (ratio / ratio.shift(mom) - 1) * 100
        def _snap(lag):
            if len(ratio) <= lag or len(mser) <= lag:
                return None
            xx, yy = float(ratio.iloc[-1 - lag]), float(mser.iloc[-1 - lag])
            if xx != xx or yy != yy:
                return None
            qq = "主導" if (xx >= 100 and yy >= 0) else "弱化" if xx >= 100 else "改善" if yy >= 0 else "停滞"
            return dict(x=round(xx, 2), y=round(yy, 2), q=qq, cross=False)
        per = {}
        for pk, lag in (("now", 0), ("w1", 5), ("w2", 10), ("m1", 20)):
            sn = _snap(lag)
            if sn:
                per[pk] = sn
        if "now" not in per:
            continue
        # ローテの芽 = 勢いがマイナス→プラスに転換した期間のみ
        _seq = ["m1", "w2", "w1", "now"]
        for a, b in zip(_seq, _seq[1:]):
            if a in per and b in per:
                per[b]["cross"] = bool(per[a]["y"] < 0 <= per[b]["y"])
        pn = per["now"]
        pts.append(dict(tk=tk, ja=ja, x=pn["x"], y=pn["y"], q=pn["q"],
                        cross=pn["cross"], semis=(tk == "SMH"), per=per))
    return pts

def build_rrg(m, s2t, win=63, mom=10):
    """テーマRRG。粒度=中分類(s2t[1]があれば中テーマ、無ければ大テーマ)。
       期間切替: 現在・先週(5d前)・2週前(10d前)・先月(20d前)の4スナップショットを各テーマで計算。
       x=RS189百分位中央値(50=市場中央), y=勢い(5日あたりのRSランク変化)。表示専用・尾なし。"""
    from collections import defaultdict
    grp = defaultdict(list)
    for t in m.index:
        v = s2t.get(t)
        if not v:
            continue
        # 中分類優先(v[1])、無ければ大分類(v[0])
        key = None
        if len(v) >= 2 and v[1]:
            key = f"{v[0]}｜{v[1]}" if v[0] else v[1]
        elif v[0]:
            key = v[0]
        if key:
            grp[key].append(t)

    def _rank(col):
        return (m[col].where(m[col].notna()).rank(pct=True) * 100) if col in m.columns else None
    # 各期間のx(RS百分位)源
    # x = 各スナップショット時点のRS百分位（now/5日前/10日前/20日前）
    rk = {"now": _rank("ret189"), "w1": _rank("ret189_l5"),
          "w2": _rank("ret189_l10"), "m1": _rank("ret189_l20")}
    # y = 「5営業日あたり」のRS百分位変化。各点の5営業日前を専用に用意する。
    # 旧: now/w1は5日差だが w2は10日差(l10-l20)、m1も10日差(l20-l30) → 同じY軸で振幅が2倍になっていた。
    rk_prev = {"now": _rank("ret189_l5"),  "w1": _rank("ret189_l10"),
               "w2": _rank("ret189_l15"), "m1": _rank("ret189_l25")}
    pts = []
    for theme, tickers in grp.items():
        idxs = [t for t in tickers if t in m.index]
        if len(idxs) < 3:               # 中分類は薄いので3社以上で採用
            continue
        disp = theme.split("｜")[-1]
        disp = disp.split(". ", 1)[-1] if ". " in disp else disp
        parent = theme.split("｜")[0].split(". ", 1)[-1] if "｜" in theme else ""
        per = {}
        xs = {}; ys_prev = {}
        for pk, _s in rk.items():
            if _s is None:
                continue
            xs[pk] = float(np.nanmedian(_s.loc[idxs]))
        for pk, _s in rk_prev.items():
            if _s is None:
                continue
            ys_prev[pk] = float(np.nanmedian(_s.loc[idxs]))
        if "now" not in xs or xs["now"] != xs["now"]:
            continue
        for pk in ("now", "w1", "w2", "m1"):
            if pk not in xs:
                continue
            x = xs[pk]
            p = ys_prev.get(pk, np.nan)
            if not (p == p and x == x):    # #20: 過去値が無ければ勢い不明。0扱いせず象限に置かない
                continue
            y = x - p
            q = "主導" if (x >= 50 and y >= 0) else "弱化" if x >= 50 else "改善" if y >= 0 else "停滞"
            per[pk] = dict(x=round(x, 1), y=round(y, 1), q=q, cross=False)
        if "now" not in per:
            continue
        # ローテの芽 = 勢いが「マイナス→プラス」に転換した期間のみTrue（説明どおりの真の転換）
        _seq = ["m1", "w2", "w1", "now"]
        for a, b in zip(_seq, _seq[1:]):
            if a in per and b in per:
                per[b]["cross"] = bool(per[a]["y"] < 0 <= per[b]["y"])
        pn = per["now"]
        pts.append(dict(tk=theme, ja=disp, parent=parent,
                        x=pn["x"], y=pn["y"], q=pn["q"], cross=pn["cross"],
                        semis=("半導体" in theme), per=per))
    pts.sort(key=lambda p: -p["x"])
    return pts

_RRG_COL = {"主導": "#4ade80", "改善": "#60a5fa", "弱化": "#fbbf24", "停滞": "#f87171"}

def _rrg_svg(pts, cxv=50, period="now"):
    """全テーマにラベルを付け、貪欲法でラベルの重なりを回避したSVGを返す。
       period=now/w1(先週)/w2(2週前)/m1(先月)。尾は廃止＝各期間のスナップショットを表示。"""
    if not pts or len(pts) < 4:
        return ""
    # 指定期間の座標に差し替え（per が無ければ現在値）
    def _xy(p):
        pr = (p.get("per") or {}).get(period)
        if pr:
            return pr["x"], pr["y"], pr["q"], pr.get("cross", False)
        return p["x"], p["y"], p["q"], p.get("cross", False)
    Wd, Ht, pad = 1040, 1140, 42
    xs = [_xy(p)[0] for p in pts]; ys = [_xy(p)[1] for p in pts]
    # 外れ値1本にレンジを引き伸ばされると中央が団子になるため、90%点でスケールし外れ値は枠に寄せる
    def _q(vals, q):
        v = sorted(vals)
        if not v:
            return 0.0
        i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
        return v[i]
    xr = max(8.0, _q([abs(v - cxv) for v in xs], 0.90) * 1.18)
    yr = max(2.0, _q([abs(v) for v in ys], 0.90) * 1.18)
    # ソフト圧縮: レンジ内はほぼ線形、外れ値は枠内に漸近させる（順序が保たれ、点が重ならない）
    def _sq(d, r):
        return r * math.tanh(d / r) * 0.98 if r > 0 else 0.0
    def X(v): return pad + (_sq(v - cxv, xr) + xr) / (2 * xr) * (Wd - 2 * pad)
    def Y(v): return pad + (1 - (_sq(v, yr) + yr) / (2 * yr)) * (Ht - 2 * pad)
    cx, cy = X(cxv), Y(0)
    quads = (f'<rect x="{cx}" y="{pad}" width="{Wd-pad-cx:.0f}" height="{cy-pad:.0f}" fill="#22c55e" opacity="0.08"/>'
             f'<rect x="{pad}" y="{pad}" width="{cx-pad:.0f}" height="{cy-pad:.0f}" fill="#3b82f6" opacity="0.08"/>'
             f'<rect x="{cx}" y="{cy}" width="{Wd-pad-cx:.0f}" height="{Ht-pad-cy:.0f}" fill="#eab308" opacity="0.08"/>'
             f'<rect x="{pad}" y="{cy}" width="{cx-pad:.0f}" height="{Ht-pad-cy:.0f}" fill="#ef4444" opacity="0.08"/>')
    QFS = 46                                   # 象限ラベルのフォント（大きく・薄く）
    qlab = (f'<text x="{Wd-pad-10}" y="{pad+QFS+2}" fill="#4ade80" fill-opacity="0.72" font-size="{QFS}" font-weight="800" text-anchor="end">主導</text>'
            f'<text x="{pad+10}" y="{pad+QFS+2}" fill="#60a5fa" fill-opacity="0.72" font-size="{QFS}" font-weight="800">改善</text>'
            f'<text x="{Wd-pad-10}" y="{Ht-pad-12}" fill="#fbbf24" fill-opacity="0.72" font-size="{QFS}" font-weight="800" text-anchor="end">弱化</text>'
            f'<text x="{pad+10}" y="{Ht-pad-12}" fill="#f87171" fill-opacity="0.72" font-size="{QFS}" font-weight="800">停滞</text>')
    FS = 15; CH = FS * 1.02
    placed = []
    def overlaps(bx):
        for q in placed:
            if not (bx[2] < q[0] or bx[0] > q[2] or bx[3] < q[1] or bx[1] > q[3]):
                return True
        return False
    marks = ""; labels = ""
    order_pts = sorted(pts, key=lambda p: (0 if p.get("semis") else 1 if _xy(p)[2] == "主導" or _xy(p)[3] else 2, -_xy(p)[0]))
    for p in order_pts:
        px, py, pq, pcross = _xy(p)
        col = _RRG_COL.get(pq, "#9aa4b2")
        cxp, cyp = X(px), Y(py)
        if pcross:
            marks += f'<circle cx="{cxp:.1f}" cy="{cyp:.1f}" r="10" fill="none" stroke="#fff" stroke-width="1.6" opacity="0.9"/>'
        if p.get("semis"):
            marks += (f'<rect x="{cxp-7:.1f}" y="{cyp-7:.1f}" width="14" height="14" rx="3" '
                      f'fill="{col}" stroke="#fff" stroke-width="2"/>')
            lw = len(p["ja"]) * (FS + 2)
            bx = [cxp - lw/2, cyp - 24, cxp + lw/2, cyp - 11]
            labels += f'<text x="{cxp:.1f}" y="{cyp-12:.1f}" fill="#fff" font-size="16.5" font-weight="900" text-anchor="middle">{_h(p["ja"])}</text>'
            placed.append(bx); continue
        marks += f'<circle cx="{cxp:.1f}" cy="{cyp:.1f}" r="5" fill="{col}"/>'
        lw = len(p["ja"]) * CH
        cands = [(cxp, cyp - 9, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp, cyp + 16, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp + 8, cyp + 4, "start", cxp + 8, cxp + 8 + lw),
                 (cxp - 8, cyp + 4, "end", cxp - 8 - lw, cxp - 8),
                 (cxp, cyp - 24, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp, cyp + 31, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp, cyp - 39, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp, cyp + 46, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp + 8, cyp - 11, "start", cxp + 8, cxp + 8 + lw),
                 (cxp - 8, cyp - 11, "end", cxp - 8 - lw, cxp - 8),
                 (cxp + 8, cyp + 19, "start", cxp + 8, cxp + 8 + lw),
                 (cxp - 8, cyp + 19, "end", cxp - 8 - lw, cxp - 8)]
        chosen = None
        for (tx, ty, anc, x0, x1) in cands:
            bx = [x0, ty - FS, x1, ty + 2]
            if not overlaps(bx):
                chosen = (tx, ty, anc, bx); break
        if chosen is None:
            tx, ty, anc, x0, x1 = cands[0]; chosen = (tx, ty, anc, [x0, ty - FS, x1, ty + 2])
        tx, ty, anc, bx = chosen
        placed.append(bx)
        lcol = "#dbe4ef" if (pq == "主導" or pcross) else "#9fb0c5"
        fw = "800" if (pq == "主導" or pcross) else "600"
        labels += f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{lcol}" font-size="{FS}" font-weight="{fw}" text-anchor="{anc}">{_h(p["ja"])}</text>'
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="xMidYMid meet">{quads}'
            f'<line x1="{cx}" y1="{pad}" x2="{cx}" y2="{Ht-pad}" stroke="#2a3548" stroke-width="1"/>'
            f'<line x1="{pad}" y1="{cy}" x2="{Wd-pad}" y2="{cy}" stroke="#2a3548" stroke-width="1"/>'
            f'{qlab}{marks}{labels}'
            f'<text x="{Wd/2}" y="{Ht-6}" fill="#7d8da1" font-size="12" text-anchor="middle">→ SPYに対する相対力（右=強い）</text>'
            f'<text x="12" y="{Ht/2}" fill="#7d8da1" font-size="12" text-anchor="middle" transform="rotate(-90 12 {Ht/2})">↑ 相対力の勢い</text></svg>')

_RRG_ETF_DESC = ('テーマETF56本をSPYとの相対力で配置（横=相対力・100が市場並み／縦=その10日モメンタム）。'
                 '改善→主導→弱化→停滞の時計回りに循環。上のボタンで<b>現在・先週・2週前・先月</b>を切替。'
                 '<b>› 付きチップをタップ→そのETFの大分類に属する詳細セクター（主導・改善を既定表示）→さらにタップで構成銘柄</b>。'
                 'ETFと大分類の対応は<b>実保有銘柄の重み付き多数決</b>で決定（保有の大半がユニバース外のETFは超過リターン相関で判定）。'
                 '⚡＝勢いがマイナス→プラスに転換。■＝半導体。')

def _rrg_card(pts, pts_all=None, sub_data=None, cxv=50, title="テーマ・ローテーション（RS基準）", desc=None):
    if not pts or len(pts) < 4:
        return ""
    def seeds_html(ps):
        seeds = sorted([p for p in ps if p["cross"]], key=lambda p: -p["y"])
        if not seeds:
            return ""
        _top = seeds[:8]
        _more = f'<span class="mut"> ほか{len(seeds)-8}件</span>' if len(seeds) > 8 else ""
        return ('<div class="rrgseed">ローテの芽（勢いがマイナス→プラスに転換）: '
                + "・".join(f'<b>{_h(p["ja"])}</b>' for p in _top) + _more + '</div>')
    def lists_html(ps, hier=None):
        import json as _j
        order = ["主導", "改善", "弱化", "停滞"]
        def chip(p):
            subs = (hier or {}).get(p["ja"])
            base = f'{_h(p["ja"])}{"⚡" if p["cross"] else ""}'
            if not subs:
                return f'<span class="chip">{base}</span>'
            # ペイロードは window.HIER に一本化（期間ビュー4枚ぶんの重複を排除）
            return (f'<span class="chip chip-tap" data-hkey="{_h(p["ja"])}" onclick="showThemeHier(event,this)">'
                    f'{base}<span class="chip-arr">›</span></span>')
        return "".join(
            f'<div class="rrgq"><span class="rrgq-l" style="color:{_RRG_COL[q]}">{q}</span>'
            + ("".join(chip(p) for p in sorted([x for x in ps if x["q"] == q], key=lambda z: -z["x"])) or '<span class="empty">なし</span>')
            + '</div>' for q in order)
    has_all = bool(pts_all and len(pts_all) >= 4)
    # 期間スナップショット4種（現在/先週/2週前/先月）を切替表示
    _pers = [("now", "現在", "on"), ("w1", "先週", ""), ("w2", "2週前", ""), ("m1", "先月", "")]
    ptog = '<div class="rrgtog">' + "".join(
        f'<button class="rtg {onc}" onclick="rrgPer(this,\'{pk}\')">{lab}</button>'
        for pk, lab, onc in _pers) + '</div>'
    views = ""
    for pk, lab, onc in _pers:
        disp = "" if pk == "now" else ' style="display:none"'
        views += (f'<div class="rrgview rrg-per" data-per="{pk}"{disp}>'
                  f'<div class="chart" style="height:auto">{_rrg_svg(pts, cxv, period=pk)}</div>'
                  f'{seeds_html(pts)}{lists_html(pts, sub_data)}</div>')
    _brief = desc or 'テーマ（中分類）のRS配置。横=強さ・縦=勢い。改善→主導→弱化→停滞の時計回り。上のボタンで期間切替。'
    _detail = ('横=RS189百分位中央値（50が市場中央・右ほど強い）／縦=勢い（5日あたりのRSランク変化・上ほど資金流入）。'
               '4象限は<b>改善（左上・弱いが上向き）→主導（右上・強く上向き）→弱化（右下・強いが下向き）→停滞（左下・弱く下向き）</b>を時計回りに循環。'
               '上のボタンで<b>現在・先週・2週前・先月</b>を切替＝同じテーマがどこから来たかを期間送りで確認。'
               '<b>⚡＝勢いがプラス側</b>／<b>■＝半導体</b>／<b>白丸＝ローテの芽（勢いがマイナス→プラスに転換）</b>。'
               '<b>› 付きチップをタップ→構成銘柄</b>。テーマRSは資金の向きを示す。')
    return (f'<div class="card"><div class="hdr"><h2>{title}</h2>{ptog}</div>'
            f'<div class="sub">{_brief} <span class="msec-more rrg-more" onclick="rrgDesc(this)">▸ 詳しく</span></div>'
            f'<div class="msec-g rrg-desc" style="display:none">{_detail}</div>'
            f'{views}</div>')

# ----------------------------------------------------------------------------- 映え: レジームリボン / LED / ヒートマップ / 品質
# ----------------------------------------------------------------------------- レバレッジ・エントリー環境（表示専用・配分に非接続）
def build_lev_env(macro):
    """SOXX(半導体指数)のトレンドゲート状態＋実現ボラ分位。SOXLの新規サイズ判断の材料。
    ※ボラは『可否』でなく『覚悟の目盛り』。強度スロットルも配分昇格しない。"""
    d = macro.get("SOXX")
    if d is None:
        return None
    c = d["Close"].dropna()
    if len(c) < 130:
        return None
    ma50 = c.rolling(50).mean(); ma100 = c.rolling(100).mean()
    up = bool(float(ma50.iloc[-1]) > float(ma100.iloc[-1]))
    gap = float(ma50.iloc[-1]) / float(ma100.iloc[-1]) - 1
    diff = (ma50 - ma100)
    streak = 0
    sign = 1 if up else -1
    for v in diff.iloc[::-1]:
        if v != v:
            break
        if (v > 0) == up:
            streak += 1
        else:
            break
    r = c.pct_change(fill_method=None)
    vol20 = float((r.rolling(20).std() * np.sqrt(252)).iloc[-1])
    vser = (r.rolling(20).std() * np.sqrt(252)).dropna()
    vpct_ser = _roll_pct(vser, win=504, minp=120)
    vpct = float(vpct_ser.dropna().iloc[-1]) if len(vpct_ser.dropna()) else None
    if vpct is None:
        size, scls, snote = "—", "mut", "分位の履歴不足"
    elif vpct >= 75:
        size, scls, snote = "薄く（半分目安）", "neg", "荒れ帯。新規は枚数を半分に"
    elif vpct >= 50:
        size, scls, snote = "標準", "mut", "平常。無理に追わない"
    else:
        size, scls, snote = "フル（配分どおり）", "pos", "静穏。減衰リスクが最も低い帯"
    # SOXL投入帯（MAE実測: SOXXが50MAの+0〜3%上＝初期逆行が最も浅く−25%級の大事故が半減）
    px = float(c.iloc[-1]); m50 = float(ma50.iloc[-1])
    dist50 = px / m50 - 1 if m50 else 0.0
    above50 = px > m50
    if above50 and dist50 <= 0.03:
        entry_ok, entry_txt, entry_cls = True, "投入帯（50MA +0〜3%）", "pos"
        entry_note = "初期逆行が最も浅い帯。段階投入で1/3ずつ。割れたら即撤退＝深傷回避"
    elif not above50:
        entry_ok, entry_txt, entry_cls = False, "50MA割れ＝TQQQのみ", "neg"
        entry_note = "リバウンド狙いに見えるがテール最悪(−25%級25%)。SOXLは入れない"
    else:
        entry_ok, entry_txt, entry_cls = False, f"50MAから+{dist50*100:.0f}%乖離＝待機", "mut"
        entry_note = "支持線が遠い。0〜+3%まで引きつけるかTQQQのみ"
    return dict(up=up, gap=gap, streak=streak, vol20=vol20, vpct=vpct,
                size=size, scls=scls, snote=snote,
                dist50=dist50, above50=above50, entry_ok=entry_ok,
                entry_txt=entry_txt, entry_cls=entry_cls, entry_note=entry_note)

def _lev_env_card(le, rrg):
    if not le:
        return ('<div class="card"><h2>レバレッジ・コンディション（SOXL）</h2>'
                '<div class="sub">SOXX(半導体指数)データ取得不可。</div></div>')
    semis = next((p for p in (rrg or []) if p.get("semis")), None)
    if semis:
        qcol = _RRG_COL.get(semis["q"], "#9aa4b2")
        rot = (f'<span class="le-rot" style="color:{qcol}">{semis["q"]}'
               + ('⚡' if semis.get("cross") else '') + '</span>')
        rot_note = {"主導": "強く、勢いも上", "改善": "勢いが上向き＝先回り候補",
                    "弱化": "強いが勢いは鈍化", "停滞": "弱く、勢いも下"}.get(semis["q"], "")
    else:
        rot, rot_note = '<span class="mut">—</span>', "SMH未取得"
    tcls = "st-good" if le["up"] else "st-bad"
    tchip = "追い風" if le["up"] else "逆風"
    tdet = (f'MA50&gt;MA100・連続{le["streak"]}日' if le["up"]
            else f'MA50&lt;MA100・連続{le["streak"]}日＝SOXL除外（全額TQQQ）の地合い')
    # SOXL投入帯（MAE実測ベース・50MAからの距離）
    _eligible = bool(le.get("up") and le.get("entry_ok"))
    _echip = "SOXL投入可" if _eligible else "TQQQのみ"
    _ecls = "st-good" if _eligible else "st-bad"
    entry_row = (
        f'<div class="le-row"><span class="le-k">投入帯</span>'
        f'<span class="st {_ecls}">{_echip}</span>'
        f'<span class="le-sub"><b class="{le.get("entry_cls","mut")}">{le.get("entry_txt","—")}</b>'
        f'（50MA距離 {le.get("dist50",0)*100:+.1f}%）</span></div>')
    vp = le["vpct"]
    meter = (f'<div class="sn-gauge le-vg"><i style="left:{max(0,min(100,vp or 0)):.1f}%"></i></div>'
             f'<div class="sn-gl"><span>静穏</span><span>平常</span><span>荒れ（薄く）</span></div>')
    return (
        f'<div class="card"><h2>レバレッジ・コンディション（SOXL）</h2>'
        f'<div class="sub">SOXLを新規で入れる時の環境チェック。<b>投入帯＝SOXXが50MAの+0〜3%上</b>のときだけ段階投入、それ以外はTQQQのみ。</div>'
        f'<div class="le-row"><span class="le-k">トレンド</span>'
        f'<span class="st {tcls}">{tchip}</span>'
        f'<span class="le-sub">{tdet}</span></div>'
        + entry_row +
        f'<div class="le-row"><span class="le-k">ローテ</span>{rot}'
        f'<span class="le-sub">{rot_note}</span></div>'
        f'<div class="le-row"><span class="le-k">ボラ</span>'
        f'<span class="le-v">{le["vol20"]*100:.0f}%<span class="le-pct">（分位{("—" if vp is None else f"{vp:.0f}")}）</span></span>'
        f'<span class="le-size {le["scls"]}">サイズ: {le["size"]}</span></div>'
        f'{meter}'
        f'<div class="note">{le.get("entry_note","")}。{le["snote"]}。</div></div>')

_RB_CLS = {"Blue": "c-bl", "Green": "c-gr", "Yellow": "c-yl", "Red": "c-rd"}

def _ribbon(hist, n=60):
    if not hist:
        return ""
    seg = [hc for hc in hist if hc and len(hc) == 2][-n:]
    if len(seg) < 5:
        return ""
    cells = "".join(f'<span class="rb {_RB_CLS.get(c, "c-gr")}" title="{d} {c}"></span>' for d, c in seg)
    return (f'<div class="ribwrap"><div class="riblab">レジーム履歴 {seg[0][0]} → {seg[-1][0]}（記録{len(seg)}日）</div>'
            f'<div class="ribbon">{cells}</div></div>')

def _led(n, tot=11):
    cells = "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(tot))
    return f'<span class="led">{cells}</span>'

def _heatmap_card(ranks):
    recs = [x for x in ((ranks or {}).get("micro") or []) if x.get("w1") == x.get("w1")]
    if len(recs) < 4:
        recs = [x for x in ((ranks or {}).get("macro") or []) if x.get("w1") == x.get("w1")]
    if len(recs) < 4:
        return ""
    def _tiles(key, cap):
        rs = sorted([x for x in recs if x.get(key) == x.get(key)], key=lambda x: -x[key])
        out = []
        _paper = (246, 244, 239)                       # タイルが載るカード地色に実ブレンド（rgba透過をやめ確定色に）
        for s in rs:
            v = max(-cap, min(cap, s[key]))
            a = abs(v) / cap * 0.78 + 0.10
            base = (26, 152, 80) if v >= 0 else (214, 69, 69)
            r_, g_, b_ = (round(p * (1 - a) + c * a) for p, c in zip(_paper, base))
            # 相対輝度で文字色を自動選択: 薄いタイル=濃インク / 濃いタイル=白（背景と文字の同化を防ぐ）
            def _lin(u):
                u /= 255.0
                return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
            lum = 0.2126 * _lin(r_) + 0.7152 * _lin(g_) + 0.0722 * _lin(b_)
            if lum > 0.32:
                ink = "rgb(32,38,31)" if v >= 0 else "rgb(58,27,27)"
                tk_c, sh = "rgb(88,94,84)" if v >= 0 else "rgb(110,72,72)", "none"
            else:
                ink, tk_c, sh = "rgb(255,255,255)", "rgb(228,230,226)", "0 1px 2px rgba(0,0,0,.35)"
            bg = f"rgb({r_},{g_},{b_})"
            out.append(f'<div class="hm" style="background:{bg};color:{ink};text-shadow:{sh}">'
                       f'<span class="hm-n">{_h(s["ja"])}'
                       f'<span class="hm-tk" style="color:{tk_c};opacity:1">{s["tk"]}</span></span>'
                       f'<span class="hm-v">{s[key]*100:+.1f}%</span></div>')
        return "".join(out)
    g_d = _tiles("d1", 0.03); g_w = _tiles("w1", 0.06); g_m = _tiles("m1", 0.12)
    return (f'<div class="card"><div class="hdr"><h2>セクター温度マップ</h2>'
            f'<div class="hmper">'
            f'<button class="hmp" onclick="hmPer(this,\'d\')">日</button>'
            f'<button class="hmp on" onclick="hmPer(this,\'w\')">週</button>'
            f'<button class="hmp" onclick="hmPer(this,\'m\')">月</button></div></div>'
            f'<div class="sub">セクター・テーマETFの騰落率・強い順（緑=上昇/赤=下落・濃さ=大きさ）</div>'
            f'<div class="hmgrid hmg-d" style="display:none">{g_d}</div>'
            f'<div class="hmgrid hmg-w">{g_w}</div>'
            f'<div class="hmgrid hmg-m" style="display:none">{g_m}</div></div>')

def _quality_card(q):
    if not q:
        return ""
    _cov = q.get("mcap_cov")
    _covtxt = ("—" if not _finite(_cov) else f'{_cov*100:.0f}%' + ("　<b style=\"color:#C2453A\">要更新（&lt;95%）</b>" if _cov < 0.95 else ""))
    rows = [
        ("ユニバース", f'{q.get("uni_ok", 0)}/{q.get("uni_total", 0)} 銘柄'),
        ("時価総額カバー率", _covtxt),
        ("分割サスペクト", (f'{q.get("split_suspect")}銘柄 除外' if q.get("split_suspect") else "0（クリーン）")),
        ("RSプール幅", f'{q.get("rs_pool", 0)}銘柄（非サスペクト×$5×$10M内で順位付け）'),
        ("地合いソース", {"file": "手動(TradingView)＝正", "estimate": "自動推定(FSM復元)", "none": "無判定"}.get(q.get("nq_src"), q.get("nq_src") or "—")),
        ("次回リバランス", q.get("next_rebal") or "—"),
        ("マクロ未取得", "・".join(q.get("macro_missing") or []) or "なし"),
        ("地合い除外指標", "・".join(q.get("mri_dropped") or []) or "なし"),
        ("センチメント源", "・".join(q.get("senti_src") or []) or "なし"),
        ("決算日キャッシュ", f'{q.get("er_n", 0)}銘柄'),
        ("エクイティCSV", "あり" if q.get("eq") else "未設定"),
        ("状態記録(前回)", str(q.get("state") or "初回")),
    ]
    kv = "".join(f'<div class="kv"><span class="k">{k}</span><span class="v" style="font-weight:600;font-size:11.5px">{v}</span></div>'
                 for k, v in rows)
    return (f'<div class="card"><h2>データ品質</h2>'
            f'<div class="sub">取得状況の自己申告（欠けがあれば数字を割り引いて読む）</div>{kv}</div>')

_OV_MICRO_EN = {
    "海運": "Shipping", "地銀": "Regional Banks", "石油探査": "Oil E&P", "銀行": "Banks",
    "小売": "Retail", "林業": "Timber", "鉄鋼": "Steel", "住宅建設": "Homebuilders",
    "EC": "E-Commerce", "農業": "Agribusiness", "運輸": "Transports", "水関連": "Water",
    "証券・取引所": "Brokers/Exchanges", "医療機器": "Medical Devices", "油田装置": "Oil Equipment",
    "クラウドSaaS": "Cloud SaaS", "油田サービス": "Oil Services", "インフラ": "Infrastructure",
    "建設": "Construction", "レジャー": "Leisure", "製薬": "Pharma", "保険": "Insurance",
    "風力": "Wind", "ソフトウェア": "Software", "銅鉱": "Copper Miners", "ソーラー": "Solar",
    "サイバー": "Cybersecurity", "防衛テック": "Defense Tech", "ロボティクス": "Robotics",
    "次世代ネット": "Next-Gen Internet", "スマートグリッド": "Smart Grid", "航空": "Airlines",
    "航空宇宙・防衛": "Aerospace & Def", "クラウド基盤": "Cloud Infra", "金属・鉱業": "Metals & Mining",
    "クリーンEN": "Clean Energy", "データセンター": "Data Centers", "宇宙・防衛": "Space & Defense",
    "リチウム電池": "Lithium/Battery", "金鉱": "Gold Miners", "ゲノム": "Genomics",
    "ブロックチェーン": "Blockchain", "EV・自動運転": "EV/Autonomous", "銀鉱": "Silver Miners",
    "半導体": "Semiconductors", "AI": "AI", "原子力": "Nuclear", "バイオテック": "Biotech",
    "ウラン": "Uranium", "量子・次世代": "Quantum", "レアアース": "Rare Earths",
    "半導体装置": "Semi Equipment", "水素": "Hydrogen", "半導体EW": "Semis (EW)",
    "BTCマイニング": "BTC Miners", "メモリ": "Memory",
}
_OV_MAJOR_EN = {
    "情報技術": "Technology", "金融": "Financials", "資本財": "Industrials", "一般消費財": "Cons. Disc",
    "素材": "Materials", "通信": "Comm. Svcs", "公益": "Utilities", "生活必需品": "Cons. Staples",
    "ヘルスケア": "Health Care", "不動産": "Real Estate", "エネルギー": "Energy",
}

# ============================================================================= Overview投稿カード（元デザインのテンプレートに実データを差し込み）
#   写真の書式（1680x1080 Almanac・SVGチャート/テーブル/ゲージ）はテンプレートのまま保持し、
#   JSデータ（D/SUB/SEC/TOP/MOM・MAJ/SUB/LEADERS）とヘッダのスカラー値だけ実測値に置換する。
#   各データは try/except でフォールバック（欠損時はテンプレのサンプルを残す）→ ビルドは絶対に止めない。
import base64 as _b64, json as _json, re as _re2, math as _math2

# 元カードのHTMLテンプレート（前セッションの完成デザインをそのまま格納）
OV1_TPL_B64 = "PCFkb2N0eXBlIGh0bWw+CjxodG1sIGxhbmc9ImphIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9InV0Zi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCxpbml0aWFsLXNjYWxlPTEiPgo8dGl0bGU+44Oe44O844Kx44OD44OI77yI5qaC55Wl77yJPC90aXRsZT4KPHN0eWxlPgogICp7Ym94LXNpemluZzpib3JkZXItYm94O21hcmdpbjowO3BhZGRpbmc6MH0KICBodG1sey13ZWJraXQtdGV4dC1zaXplLWFkanVzdDoxMDAlfQogIGJvZHl7YmFja2dyb3VuZDojMTExMDE0O2ZvbnQtZmFtaWx5Oi1hcHBsZS1zeXN0ZW0sJ0hlbHZldGljYSBOZXVlJyxBcmlhbCwnSGlyYWdpbm8gU2Fucycsc2Fucy1zZXJpZjtwYWRkaW5nOjEycHggOHB4IDUwcHg7Y29sb3I6I2RkZH0KICAudG9we21heC13aWR0aDoxNjgwcHg7bWFyZ2luOjAgYXV0byAxMHB4O3RleHQtYWxpZ246Y2VudGVyO2ZvbnQtc2l6ZToxM3B4O2NvbG9yOiM5YTlhYTR9CiAgLnN0YWdle3dpZHRoOjEwMCU7ZGlzcGxheTpmbGV4O2p1c3RpZnktY29udGVudDpjZW50ZXI7b3ZlcmZsb3c6aGlkZGVufS5zY2FsZXJ7dHJhbnNmb3JtLW9yaWdpbjp0b3AgY2VudGVyfQoKICAuY2FyZHt3aWR0aDoxNjgwcHg7aGVpZ2h0OjEwODBweDtiYWNrZ3JvdW5kOiNFOUU3REY7Y29sb3I6IzFCMUQxQztwYWRkaW5nOjIycHggMjZweCAxNnB4O2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47CiAgICAtLWluazojMUIxRDFDOy0tbXV0OiM3Mjc1Njk7LS1saW5lOiNENUQxQzY7LS1jYXJkOiNGNkY0RUU7LS10cmFjazojREFENkNCOy0tYWNjZW50OiMxNzY4NUM7LS1hY2NlbnQyOiMyQTkzODQ7CiAgICAtLXBvczojMUU3QTREOy0tcG9zYmc6I0RCRUJERjstLXBvc2JnMjojQzZFMENDOy0tbmVnOiNCMjNBMkU7LS1uZWdiZzojRjFERUQ5Oy0tbmVnYmcyOiNFN0M3QzI7LS1uZXU6IzdDN0Y3ODstLW5ldWJnOiNFNkUzREI7LS13YXJuOiNCMDdBMTY7LS13YXJuYmc6I0YwRTZDRjsKICAgIC0tY2hpcGJnOiNFRUVCRTM7LS1mbnVtOnVpLW1vbm9zcGFjZSwnU0YgTW9ubycsTWVubG8sbW9ub3NwYWNlO2ZvbnQtc2l6ZToxNHB4fQogIC5udW17Zm9udC1mYW1pbHk6dmFyKC0tZm51bSk7Zm9udC12YXJpYW50LW51bWVyaWM6dGFidWxhci1udW1zO2xldHRlci1zcGFjaW5nOi0uMDFlbX0KICAucG9ze2NvbG9yOnZhcigtLXBvcyl9Lm5lZ3tjb2xvcjp2YXIoLS1uZWcpfS5hY2N7Y29sb3I6dmFyKC0tYWNjZW50KX0ud2FybmN7Y29sb3I6dmFyKC0td2Fybil9Lmlua3tjb2xvcjp2YXIoLS1pbmspfQoKICAuaGR7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6MTJweDttYXJnaW4tYm90dG9tOjlweH0KICAuaGQgLmJhcnt3aWR0aDo1cHg7aGVpZ2h0OjI0cHg7YmFja2dyb3VuZDp2YXIoLS1hY2NlbnQpO2JvcmRlci1yYWRpdXM6M3B4fQogIC5oZCBoMXtmb250LXNpemU6MjRweDtmb250LXdlaWdodDo4MDA7bGV0dGVyLXNwYWNpbmc6LS4wMmVtfQogIC5oZCAuc3RhdGV7Zm9udC1zaXplOjEzcHg7Zm9udC13ZWlnaHQ6ODAwO2NvbG9yOnZhcigtLXdhcm4pO2JvcmRlcjoxLjVweCBzb2xpZCB2YXIoLS13YXJuKTtib3JkZXItcmFkaXVzOjhweDtwYWRkaW5nOjNweCAxMnB4fQogIC5oZCAuc3RhdHN7Zm9udC1zaXplOjEyLjVweDtjb2xvcjp2YXIoLS1tdXQpO2ZvbnQtd2VpZ2h0OjcwMH0uaGQgLnN0YXRzIGJ7Y29sb3I6dmFyKC0taW5rKX0KICAuaGQgLmRhdGV7bWFyZ2luLWxlZnQ6YXV0bztmb250LXNpemU6MTRweDtjb2xvcjp2YXIoLS1tdXQpO2ZvbnQtd2VpZ2h0OjcwMH0KICAuaGQgLmJyYW5ke2ZvbnQtc2l6ZToxNXB4O2ZvbnQtd2VpZ2h0OjgwMDttYXJnaW4tbGVmdDoxMHB4fS5oZCAuYnJhbmQgLmF0e2NvbG9yOnZhcigtLWFjY2VudCl9CgogIC5ncmlke2Rpc3BsYXk6Z3JpZDtncmlkLXRlbXBsYXRlLWNvbHVtbnM6cmVwZWF0KDQsMWZyKTtncmlkLXRlbXBsYXRlLXJvd3M6MjAwcHggMTUwcHggMWZyIDIwMHB4O2dhcDoxMHB4O2ZsZXg6MTttaW4taGVpZ2h0OjB9CiAgLnNwMntncmlkLWNvbHVtbjpzcGFuIDJ9CiAgLnR7YmFja2dyb3VuZDp2YXIoLS1jYXJkKTtib3JkZXI6MXB4IHNvbGlkIHZhcigtLWxpbmUpO2JvcmRlci1yYWRpdXM6MTFweDtwYWRkaW5nOjEwcHggMTJweDttaW4taGVpZ2h0OjA7b3ZlcmZsb3c6aGlkZGVuO2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW59CiAgLnRoe2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjZweDttYXJnaW4tYm90dG9tOjZweH0KICAudGggaDR7Zm9udC1zaXplOjEzLjVweDtmb250LXdlaWdodDo4MDA7bGV0dGVyLXNwYWNpbmc6LS4wMWVtfS50aCAuc3tmb250LXNpemU6MTAuNXB4O2NvbG9yOnZhcigtLW11dCk7Zm9udC13ZWlnaHQ6NzAwfS50aCAuZ3ttYXJnaW4tbGVmdDphdXRvO2NvbG9yOnZhcigtLW11dCk7b3BhY2l0eTouNTtmb250LXNpemU6MTJweH0KICAuY2hhcnRue2ZvbnQtc2l6ZToyMnB4O2ZvbnQtd2VpZ2h0OjgwMH0KCiAgLnJlZ3Jvd3tkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDo3cHh9CiAgLmRvdHt3aWR0aDoxMnB4O2hlaWdodDoxMnB4O2JvcmRlci1yYWRpdXM6NTAlO2JhY2tncm91bmQ6dmFyKC0td2Fybik7Ym94LXNoYWRvdzowIDAgMCA0cHggY29sb3ItbWl4KGluIHNyZ2IsdmFyKC0td2FybikgMjAlLHRyYW5zcGFyZW50KX0KICAucm4ye2ZvbnQtc2l6ZToyMXB4O2ZvbnQtd2VpZ2h0OjgwMH0ucGlsbHtmb250LXNpemU6MTAuNXB4O2ZvbnQtd2VpZ2h0OjgwMDtib3JkZXI6MS41cHggc29saWQgY3VycmVudENvbG9yO2JvcmRlci1yYWRpdXM6NnB4O3BhZGRpbmc6MXB4IDZweH0KICAuZHJ7Zm9udC1zaXplOjExLjVweDtjb2xvcjp2YXIoLS1tdXQpO21hcmdpbjo4cHggMCA3cHg7bGluZS1oZWlnaHQ6MS40NX0KICAuZGF5c3tkaXNwbGF5OmZsZXg7Z2FwOjJweH0uZGF5cyBpe2ZsZXg6MTtoZWlnaHQ6MTFweDtib3JkZXItcmFkaXVzOjJweH0KICAuZC1ne2JhY2tncm91bmQ6dmFyKC0tcG9zKX0uZC15e2JhY2tncm91bmQ6dmFyKC0td2Fybil9LmQtcntiYWNrZ3JvdW5kOnZhcigtLW5lZyl9LmQtbntiYWNrZ3JvdW5kOnZhcigtLXRyYWNrKX0KICAuYWN0aW9ue21hcmdpbi10b3A6YXV0bztmb250LXNpemU6MTEuNXB4O2NvbG9yOnZhcigtLW11dCk7Zm9udC13ZWlnaHQ6NzAwO2JvcmRlci10b3A6MXB4IHNvbGlkIHZhcigtLWxpbmUpO3BhZGRpbmctdG9wOjhweH0KCiAgLmdhdWdle3dpZHRoOjEwMHB4O2ZsZXg6MCAwIGF1dG99CiAgLnN0bWV0YXtmb250LXNpemU6MTJweH0uc3RtZXRhIC5sYWJ7Y29sb3I6dmFyKC0tbXV0KX0KICAud2FybmxlZHtkaXNwbGF5OmlubGluZS1mbGV4O2dhcDoycHg7dmVydGljYWwtYWxpZ246bWlkZGxlO21hcmdpbi1sZWZ0OjRweH0ud2FybmxlZCBpe3dpZHRoOjZweDtoZWlnaHQ6NnB4O2JvcmRlci1yYWRpdXM6NTAlO2JhY2tncm91bmQ6dmFyKC0tdHJhY2spfQoKICAvKiBjb21tZW50IGNhcmQgKi8KICAuY210e21hcmdpbi1ib3R0b206MTFweH0KICAuY210IC5jbHtmb250LXNpemU6MTFweDtmb250LXdlaWdodDo4MDA7Y29sb3I6dmFyKC0tYWNjZW50KTttYXJnaW4tYm90dG9tOjNweH0KICAuY210IC5jeHtmb250LXNpemU6MTNweDtmb250LXdlaWdodDo2MDA7bGluZS1oZWlnaHQ6MS40Mn0KCiAgLmxlZ2VuZHtkaXNwbGF5OmZsZXg7Z2FwOjE0cHg7Zm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0tbXV0KTttYXJnaW4tdG9wOjVweDtmbGV4LXdyYXA6d3JhcH0KICAubGVnZW5kIHNwYW57ZGlzcGxheTppbmxpbmUtZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjVweH0ubGVnZW5kIGl7d2lkdGg6MTJweDtoZWlnaHQ6MnB4O2JvcmRlci1yYWRpdXM6MnB4fQoKICAuZnJvd3tkaXNwbGF5OmdyaWQ7Z3JpZC10ZW1wbGF0ZS1jb2x1bW5zOjFmciAxZnIgMWZyO2dhcDo3cHh9CiAgLmZib3h7Ym9yZGVyOjEuNXB4IHNvbGlkIHZhcigtLWxpbmUpO2JvcmRlci1yYWRpdXM6OHB4O3BhZGRpbmc6OHB4IDZweCA0cHg7dGV4dC1hbGlnbjpjZW50ZXJ9CiAgLmZib3ggLmZse2ZvbnQtc2l6ZToxMHB4O2NvbG9yOnZhcigtLW11dCk7Zm9udC13ZWlnaHQ6NzAwfS5mYm94IC5mdntmb250LXNpemU6MjNweDtmb250LXdlaWdodDo4MDA7bWFyZ2luOjFweCAwIDRweH0KICAuZm5vdGV7bWFyZ2luLXRvcDphdXRvO2ZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLW11dCk7Zm9udC13ZWlnaHQ6NzAwO2JvcmRlci10b3A6MXB4IHNvbGlkIHZhcigtLWxpbmUpO3BhZGRpbmctdG9wOjdweH0KCiAgLnJzcXtkaXNwbGF5OmdyaWQ7Z3JpZC10ZW1wbGF0ZS1jb2x1bW5zOjFmciAxZnI7Z2FwOjhweDtmbGV4OjF9CiAgLnJzYm94e2JvcmRlcjoxLjVweCBzb2xpZCB2YXIoLS1saW5lKTtib3JkZXItcmFkaXVzOjhweDtwYWRkaW5nOjZweCA5cHg7ZGlzcGxheTpmbGV4O2ZsZXgtZGlyZWN0aW9uOmNvbHVtbjtqdXN0aWZ5LWNvbnRlbnQ6Y2VudGVyfQogIC5yc2JveCAucmh7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6NnB4O21hcmdpbi1ib3R0b206NnB4fS5yc2JveCAucmx7Zm9udC1zaXplOjEwLjVweDtjb2xvcjp2YXIoLS1tdXQpO2ZvbnQtd2VpZ2h0OjgwMH0ucnNib3ggLnJue2ZvbnQtc2l6ZToxOXB4O2ZvbnQtd2VpZ2h0OjgwMDttYXJnaW4tbGVmdDphdXRvO2NvbG9yOnZhcigtLWFjY2VudCl9CiAgLmNoaXBze2Rpc3BsYXk6ZmxleDtmbGV4LXdyYXA6d3JhcDtnYXA6NHB4fS5jaGlwe2ZvbnQtZmFtaWx5OnZhcigtLWZudW0pO2ZvbnQtc2l6ZToxMXB4O2ZvbnQtd2VpZ2h0OjcwMDtiYWNrZ3JvdW5kOnZhcigtLWNoaXBiZyk7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1saW5lKTtib3JkZXItcmFkaXVzOjZweDtwYWRkaW5nOjJweCA2cHh9CgogIHRhYmxlLnRie3dpZHRoOjEwMCU7Ym9yZGVyLWNvbGxhcHNlOmNvbGxhcHNlO2ZvbnQtc2l6ZToxMi41cHh9CiAgdGFibGUudGIgdGh7Zm9udC1zaXplOjEwcHg7Y29sb3I6dmFyKC0tbXV0KTtmb250LXdlaWdodDo4MDA7dGV4dC1hbGlnbjpjZW50ZXI7cGFkZGluZzozcHggM3B4O2JvcmRlci1ib3R0b206MS41cHggc29saWQgdmFyKC0tbGluZSk7d2hpdGUtc3BhY2U6bm93cmFwfQogIHRhYmxlLnRiIHRoLmx7dGV4dC1hbGlnbjpsZWZ0fQogIHRhYmxlLnRiIHRke3BhZGRpbmc6M3B4IDNweDt0ZXh0LWFsaWduOmNlbnRlcjtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1saW5lKTt3aGl0ZS1zcGFjZTpub3dyYXB9CiAgdGFibGUudGIgdGQubHt0ZXh0LWFsaWduOmxlZnQ7Zm9udC13ZWlnaHQ6ODAwfQogIHRhYmxlLnRiIHRyOmxhc3QtY2hpbGQgdGR7Ym9yZGVyLWJvdHRvbTowfQogIC5yc2N7Zm9udC1mYW1pbHk6dmFyKC0tZm51bSk7Zm9udC13ZWlnaHQ6ODAwO2JvcmRlci1yYWRpdXM6NHB4O2ZvbnQtc2l6ZToxMS41cHh9CgogIC5zZWN0dGx7Zm9udC1zaXplOjExcHg7Zm9udC13ZWlnaHQ6ODAwO2NvbG9yOnZhcigtLWFjY2VudCk7bWFyZ2luOjlweCAwIDVweDtib3JkZXItdG9wOjFweCBzb2xpZCB2YXIoLS1saW5lKTtwYWRkaW5nLXRvcDo4cHh9CiAgLnNlY3RibHt3aWR0aDoxMDAlO2JvcmRlci1jb2xsYXBzZTpjb2xsYXBzZTtmb250LXNpemU6MTJweH0KICAuc2VjdGJsIHRke3BhZGRpbmc6M3B4IDRweDtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1saW5lKX0uc2VjdGJsIHRyOmxhc3QtY2hpbGQgdGR7Ym9yZGVyLWJvdHRvbTowfQogIC5zZWN0YmwgdGQubHtmb250LXdlaWdodDo4MDB9LnNlY3RibCB0ZC5ye3RleHQtYWxpZ246cmlnaHQ7Zm9udC13ZWlnaHQ6ODAwfQoKICAubXJvdzJ7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczphdXRvIGF1dG8gMWZyIGF1dG87Z2FwOjdweDthbGlnbi1pdGVtczpjZW50ZXI7Zm9udC1zaXplOjEzcHg7cGFkZGluZzo0cHggMnB4O2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWxpbmUpfQogIC5tcm93MjpsYXN0LWNoaWxke2JvcmRlci1ib3R0b206MH0ubXJvdzIgLm10a3tmb250LXdlaWdodDo4MDB9Lm1yb3cyIC5tc3R7Zm9udC1zaXplOjEwLjVweH0ubXJvdzIgLmxie2NvbG9yOnZhcigtLW11dCk7Zm9udC1zaXplOjEwLjVweH0ubXJvdzIgLm1yc3tmb250LXdlaWdodDo4MDB9CgogIC5yYXRlcm93e2Rpc3BsYXk6ZmxleDtqdXN0aWZ5LWNvbnRlbnQ6c3BhY2UtYmV0d2Vlbjtmb250LXNpemU6MTIuNXB4O3BhZGRpbmc6NHB4IDA7Ym9yZGVyLWJvdHRvbToxcHggc29saWQgdmFyKC0tbGluZSl9CiAgLnJhdGVyb3c6bGFzdC1jaGlsZHtib3JkZXItYm90dG9tOjB9LnJhdGVyb3cgLmt7Y29sb3I6dmFyKC0tbXV0KTtmb250LXdlaWdodDo3MDB9LnJhdGVyb3cgLnZ7Zm9udC13ZWlnaHQ6ODAwfQouc2VjcmFua3tkaXNwbGF5OmdyaWQ7Z3JpZC10ZW1wbGF0ZS1jb2x1bW5zOjFmciAxZnIgMWZyO2dhcDoxMnB4fS5zdWJmaWxse2p1c3RpZnktY29udGVudDpzcGFjZS1iZXR3ZWVufS5zdWJmaWxsIC50YnttYXJnaW4tYm90dG9tOjJweH0KICAuc3Jjb2wgLnNyaHtmb250LXNpemU6MTAuNXB4O2ZvbnQtd2VpZ2h0OjgwMDtjb2xvcjp2YXIoLS1hY2NlbnQpO21hcmdpbi1ib3R0b206NHB4O3RleHQtYWxpZ246Y2VudGVyO2JvcmRlci1ib3R0b206MS41cHggc29saWQgdmFyKC0tbGluZSk7cGFkZGluZy1ib3R0b206M3B4fQogIC5zcnJvd3tkaXNwbGF5OmdyaWQ7Z3JpZC10ZW1wbGF0ZS1jb2x1bW5zOjhweCAxMnB4IDFmciBhdXRvO2dhcDo0cHg7YWxpZ24taXRlbXM6Y2VudGVyO2ZvbnQtc2l6ZToxMC41cHg7cGFkZGluZzoyLjVweCAwO2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWxpbmUpfQogIC5kb3Rje3dpZHRoOjdweDtoZWlnaHQ6N3B4O2JvcmRlci1yYWRpdXM6NTAlfS5zcmFye2ZvbnQtc2l6ZTo5cHg7Zm9udC13ZWlnaHQ6ODAwO21hcmdpbi1yaWdodDoycHh9LnN2Y2VsbHt3aGl0ZS1zcGFjZTpub3dyYXA7dGV4dC1hbGlnbjpyaWdodH0KICAuc3Jyb3c6bGFzdC1jaGlsZHtib3JkZXItYm90dG9tOjB9CiAgLnNycm93IC5ya3tjb2xvcjp2YXIoLS1tdXQpO2ZvbnQtc2l6ZTo5LjVweDt0ZXh0LWFsaWduOmNlbnRlcn0uc3Jyb3cgLnNubXtmb250LXdlaWdodDo3MDA7d2hpdGUtc3BhY2U6bm93cmFwO292ZXJmbG93OmhpZGRlbjt0ZXh0LW92ZXJmbG93OmVsbGlwc2lzfS5zcnJvdyAuc3Z7Zm9udC13ZWlnaHQ6ODAwO3RleHQtYWxpZ246cmlnaHR9Ci5tb21zdW17ZGlzcGxheTpmbGV4O2p1c3RpZnktY29udGVudDpzcGFjZS1iZXR3ZWVuO2ZvbnQtc2l6ZToxMS41cHg7Zm9udC13ZWlnaHQ6NzAwO21hcmdpbi1ib3R0b206NXB4fS5tb21zdW0gYntmb250LXNpemU6MTRweH0KICAubWh3cmFwe2ZsZXg6MTtkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO21pbi1oZWlnaHQ6MDttYXJnaW4tdG9wOjRweH0ubWh0dGx7Zm9udC1zaXplOjEwcHg7Y29sb3I6dmFyKC0tbXV0KTtmb250LXdlaWdodDo3MDA7bWFyZ2luLWJvdHRvbTozcHh9CiAgLm1oe2ZsZXg6MTtkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6ZmxleC1lbmQ7Z2FwOjVweDttaW4taGVpZ2h0OjB9Lm1oIC5taGJ7ZmxleDoxO2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47YWxpZ24taXRlbXM6Y2VudGVyO2p1c3RpZnktY29udGVudDpmbGV4LWVuZDtoZWlnaHQ6MTAwJX0KICAubWggLm1oYiAudntmb250LXNpemU6OXB4O2ZvbnQtd2VpZ2h0OjgwMDttYXJnaW4tYm90dG9tOjFweH0ubWggLm1oYiAuYnt3aWR0aDoxMDAlO2JvcmRlci1yYWRpdXM6MnB4IDJweCAwIDA7bWluLWhlaWdodDoycHh9Lm1oIC5taGIgLnh7Zm9udC1zaXplOjhweDtjb2xvcjp2YXIoLS1tdXQpO21hcmdpbi10b3A6MnB4O3doaXRlLXNwYWNlOm5vd3JhcH0KICAubW9tYmFye2Rpc3BsYXk6ZmxleDtoZWlnaHQ6OHB4O2JvcmRlci1yYWRpdXM6NHB4O292ZXJmbG93OmhpZGRlbjttYXJnaW4tYm90dG9tOjhweDtnYXA6MXB4fS5tb21iYXIgaXtkaXNwbGF5OmJsb2NrfQoudGggaDQgLmVue2ZvbnQtc2l6ZTo5cHg7Zm9udC13ZWlnaHQ6NjAwO2NvbG9yOnZhcigtLW11dCk7bWFyZ2luLWxlZnQ6NXB4O2xldHRlci1zcGFjaW5nOi4wMmVtfQo8L3N0eWxlPgo8L2hlYWQ+Cjxib2R5PgogIDxkaXYgY2xhc3M9InN0YWdlIiBpZD0ic3RhZ2UiPjxkaXYgY2xhc3M9InNjYWxlciIgaWQ9InNjYWxlciI+CiAgPGRpdiBjbGFzcz0iY2FyZCI+CiAgICA8ZGl2IGNsYXNzPSJoZCI+PHNwYW4gY2xhc3M9ImJhciI+PC9zcGFuPjxoMT7jg57jg7zjgrHjg4Pjg4ggPHNwYW4gc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXQpO2xldHRlci1zcGFjaW5nOi4wMmVtIj5NYXJrZXQ8L3NwYW4+PC9oMT48c3BhbiBjbGFzcz0ic3RhdGUiPlllbGxvd+ODu+OChOOChOazqOaEjzwvc3Bhbj4KICAgICAgPHNwYW4gY2xhc3M9InN0YXRzIj7lr77osaEgPGI+4oCUPC9iPumKmOafhCDjg7sg6YGp5qC8IDxiPuKAlDwvYj4g44O7IOebo+imluS4iuS9jSA8Yj7igJQ8L2I+PC9zcGFuPgogICAgICA8c3BhbiBjbGFzcz0iZGF0ZSBudW0iPuKAlDwvc3Bhbj48L2Rpdj4KCiAgICA8ZGl2IGNsYXNzPSJncmlkIj4KICAgICAgPCEtLSBST1cgMSAtLT4KICAgICAgPGRpdiBjbGFzcz0idCI+PGRpdiBjbGFzcz0idGgiPjxoND7jg6zjgrjjg7zjg6DliKTlrpo8c3BhbiBjbGFzcz0iZW4iPlJlZ2ltZTwvc3Bhbj48L2g0PjxzcGFuIGNsYXNzPSJnIj7ii688L3NwYW4+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0icmVncm93Ij48c3BhbiBjbGFzcz0iZG90Ij48L3NwYW4+PHNwYW4gY2xhc3M9InJuMiB3YXJuYyI+WWVsbG93PC9zcGFuPjxzcGFuIGNsYXNzPSJwaWxsIHdhcm5jIj7jgoTjgoTms6jmhI88L3NwYW4+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iZHIiPuKAlDwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImRheXMiPjxpIGNsYXNzPSJkLW4iPjwvaT48aSBjbGFzcz0iZC1uIj48L2k+PGkgY2xhc3M9ImQtbiI+PC9pPjxpIGNsYXNzPSJkLW4iPjwvaT48aSBjbGFzcz0iZC1uIj48L2k+PGkgY2xhc3M9ImQtbiI+PC9pPjxpIGNsYXNzPSJkLW4iPjwvaT48aSBjbGFzcz0iZC1uIj48L2k+PGkgY2xhc3M9ImQtbiI+PC9pPjxpIGNsYXNzPSJkLW4iPjwvaT48aSBjbGFzcz0iZC1uIj48L2k+PGkgY2xhc3M9ImQtbiI+PC9pPjxpIGNsYXNzPSJkLW4iPjwvaT48aSBjbGFzcz0iZC1uIj48L2k+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iYWN0aW9uIj7igJQ8L2Rpdj48L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9InQgc3AyIj48ZGl2IGNsYXNzPSJ0aCI+PGg0PuODnuODvOOCseODg+ODiOOCueODhuODvOOCv+OCuTxzcGFuIGNsYXNzPSJlbiI+TWFya2V0IFN0YXR1czwvc3Bhbj48L2g0PjxzcGFuIGNsYXNzPSJzIj7lnLDlkIjjgYTjgrnjgrPjgqIg77yLIDLlubTmjqjnp7s8L3NwYW4+PHNwYW4gY2xhc3M9ImciPuKamTwvc3Bhbj48L2Rpdj4KICAgICAgICA8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7Z2FwOjE4cHg7ZmxleDoxO21pbi1oZWlnaHQ6MCI+CiAgICAgICAgICA8ZGl2IHN0eWxlPSJmbGV4OjAgMCBhdXRvO3dpZHRoOjE3NnB4O2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47anVzdGlmeS1jb250ZW50OmNlbnRlciI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImdhdWdlIiBpZD0iZF9nIj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBzdHlsZT0ibWFyZ2luLXRvcDoycHgiPjxiIGNsYXNzPSJudW0iIHN0eWxlPSJmb250LXNpemU6MjdweCI+4oCUPC9iPjxzcGFuIGNsYXNzPSJudW0iIHN0eWxlPSJjb2xvcjp2YXIoLS1tdXQpIj4vMTAwPC9zcGFuPiA8c3BhbiBjbGFzcz0iYWNjIiBzdHlsZT0iZm9udC13ZWlnaHQ6ODAwO2ZvbnQtc2l6ZToxNXB4Ij7lvLfmsJc8L3NwYW4+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InN0bWV0YSIgc3R5bGU9Im1hcmdpbi10b3A6N3B4Ij48c3BhbiBjbGFzcz0ibGFiIj7lgr7jgY08L3NwYW4+IDxiIGNsYXNzPSJwb3MiPuKAlDwvYj4g44O7IDxzcGFuIGNsYXNzPSJsYWIiPjFEPC9zcGFuPiA8YiBjbGFzcz0ibnVtIHBvcyI+4oCUPC9iPiDjg7sgPHNwYW4gY2xhc3M9ImxhYiI+MVc8L3NwYW4+IDxiIGNsYXNzPSJudW0gcG9zIj7igJQ8L2I+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InN0bWV0YSIgc3R5bGU9Im1hcmdpbi10b3A6NHB4Ij48c3BhbiBjbGFzcz0ibGFiIj7orabmiJLnga88L3NwYW4+IDxiIGNsYXNzPSJudW0iPuKAlDwvYj48c3BhbiBjbGFzcz0id2FybmxlZCI+PGk+PC9pPjxpPjwvaT48aT48L2k+PGk+PC9pPjwvc3Bhbj48L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPGRpdiBzdHlsZT0iZmxleDoxO2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47bWluLXdpZHRoOjAiPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJ0aCI+PHNwYW4gY2xhc3M9InMiPuaOqOenu++8iDLlubTjg7vpgLHmrKHvvIk8L3NwYW4+PC9kaXY+PGRpdiBpZD0iZF9tcmkiIHN0eWxlPSJmbGV4OjE7bWluLWhlaWdodDowIj48L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgIDwvZGl2PjwvZGl2PgoKICAgICAgPGRpdiBjbGFzcz0idCI+PGRpdiBjbGFzcz0idGgiPjxoND7jg57jg7zjgrHjg4Pjg4jjgrPjg6Hjg7Pjg4g8c3BhbiBjbGFzcz0iZW4iPkNvbW1lbnRhcnk8L3NwYW4+PC9oND48c3BhbiBjbGFzcz0iZyI+4pqZPC9zcGFuPjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImNtdCI+PGRpdiBjbGFzcz0iY2wiPuS7iuaXpTwvZGl2PjxkaXYgY2xhc3M9ImN4Ij7igJQ8L2Rpdj48L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJjbXQiIHN0eWxlPSJtYXJnaW4tYm90dG9tOjAiPjxkaXYgY2xhc3M9ImNsIj7ku4rpgLE8L2Rpdj48ZGl2IGNsYXNzPSJjeCI+4oCUPC9kaXY+PC9kaXY+PC9kaXY+CgogICAgICA8IS0tIFJPVyAyIGludGVybmFscyAtLT4KICAgICAgPGRpdiBjbGFzcz0idCI+PGRpdiBjbGFzcz0idGgiPjxoND7jg5bjg6zjg4Pjg4njgrnjg5fjg6zjg4Pjg4k8c3BhbiBjbGFzcz0iZW4iPkJyZWFkdGg8L3NwYW4+PC9oND48c3BhbiBjbGFzcz0icyI+NTAvMjAw5pel57ea5LiKJTwvc3Bhbj48c3BhbiBjbGFzcz0iZyI+4pqZPC9zcGFuPjwvZGl2PgogICAgICAgIDxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6MTBweDthbGlnbi1pdGVtczpiYXNlbGluZSI+PHNwYW4gY2xhc3M9ImNoYXJ0biBudW0gYWNjIj7igJQ8L3NwYW4+PHNwYW4gY2xhc3M9Im51bSIgc3R5bGU9ImZvbnQtc2l6ZToxMS41cHg7Y29sb3I6dmFyKC0tbXV0KSI+NTDml6UgPGIgY2xhc3M9ImluayI+4oCUPC9iPuODuzIwMOaXpSA8YiBjbGFzcz0iaW5rIj7igJQ8L2I+PC9zcGFuPjwvZGl2PjxkaXYgaWQ9ImRfYnIiIHN0eWxlPSJmbGV4OjE7bWluLWhlaWdodDowIj48L2Rpdj48L2Rpdj4KICAgICAgPGRpdiBjbGFzcz0idCI+PGRpdiBjbGFzcz0idGgiPjxoND7lo7Losrfku6Pph5E8c3BhbiBjbGFzcz0iZW4iPkRvbGxhciBWb2x1bWU8L3NwYW4+PC9oND48c3BhbiBjbGFzcz0icyI+UVFRIC8gU1BZ44O75pel5qyhJOWHuuadpemrmDwvc3Bhbj48c3BhbiBjbGFzcz0iZyI+4pqZPC9zcGFuPjwvZGl2PjxkaXYgaWQ9ImRfcGFydCIgc3R5bGU9ImZsZXg6MTttaW4taGVpZ2h0OjAiPjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImxlZ2VuZCI+PHNwYW4+PGkgc3R5bGU9ImJhY2tncm91bmQ6dmFyKC0tcG9zKSI+PC9pPlFRUSAk4oCUQjwvc3Bhbj48c3Bhbj48aSBzdHlsZT0iYmFja2dyb3VuZDp2YXIoLS1tdXQpIj48L2k+U1BZICTigJRCPC9zcGFuPjwvZGl2PjwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJ0Ij48ZGl2IGNsYXNzPSJ0aCI+PGg0PuOCu+ODs+ODgeODoeODs+ODiDxzcGFuIGNsYXNzPSJlbiI+U2VudGltZW50PC9zcGFuPjwvaDQ+PHNwYW4gY2xhc3M9InMiPue+pOihhua4qeW6puioiDwvc3Bhbj48c3BhbiBjbGFzcz0iZyI+4pqZPC9zcGFuPjwvZGl2PgogICAgICAgIDxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDtnYXA6MTBweDthbGlnbi1pdGVtczpiYXNlbGluZSI+PHNwYW4gY2xhc3M9ImNoYXJ0biBudW0iPuKAlDwvc3Bhbj48c3BhbiBjbGFzcz0ibnVtIiBzdHlsZT0iZm9udC1zaXplOjExLjVweDtjb2xvcjp2YXIoLS1tdXQpIj7igJTjg7tWSVgg4oCU44O7UC9DIOKAlDwvc3Bhbj48L2Rpdj48ZGl2IGlkPSJkX3NlIiBzdHlsZT0iZmxleDoxO21pbi1oZWlnaHQ6MCI+PC9kaXY+PC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InQiPjxkaXYgY2xhc3M9InRoIj48aDQ+5YWI5bCO44Gu5bSp44KMPHNwYW4gY2xhc3M9ImVuIj5MZWFkZXIgQnJlYWtkb3duPC9zcGFuPjwvaDQ+PHNwYW4gY2xhc3M9InMiPuODrOOCuOODvOODoOitpuaIkueBrzwvc3Bhbj48c3BhbiBjbGFzcz0iZyI+4pqZPC9zcGFuPjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImZyb3ciPjxkaXYgY2xhc3M9ImZib3giPjxkaXYgY2xhc3M9ImZsIj7ohLHokL3njoc8L2Rpdj48ZGl2IGNsYXNzPSJmdiBwb3MgbnVtIj7igJQ8L2Rpdj48ZGl2IGlkPSJkX2YxIj48L2Rpdj48L2Rpdj48ZGl2IGNsYXNzPSJmYm94Ij48ZGl2IGNsYXNzPSJmbCI+54uZ44GE546HPC9kaXY+PGRpdiBjbGFzcz0iZnYgd2FybmMgbnVtIj7igJQ8L2Rpdj48ZGl2IGlkPSJkX2YyIj48L2Rpdj48L2Rpdj48ZGl2IGNsYXNzPSJmYm94Ij48ZGl2IGNsYXNzPSJmbCI+44Kt44Ol44O85bSp44KMPC9kaXY+PGRpdiBjbGFzcz0iZnYgbmVnIG51bSI+4oCUPC9kaXY+PGRpdiBpZD0iZF9mMyI+PC9kaXY+PC9kaXY+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iZm5vdGUiPuWIpOWumu+8muKAlDwvZGl2PjwvZGl2PgoKICAgICAgPCEtLSBST1cgMyB0YWJsZXMgLS0+CiAgICAgIDxkaXYgY2xhc3M9InQgc3AyIHN1YmZpbGwiPjxkaXYgY2xhc3M9InRoIj48aDQ+44K144OW44OG44O844OeUlMg77yGIOOCu+OCr+OCv+ODvOmosOiQvTxzcGFuIGNsYXNzPSJlbiI+U3ViLXRoZW1lIFJTICYgU2VjdG9yIE1vdmVzPC9zcGFuPjwvaDQ+PHNwYW4gY2xhc3M9InMiPlJTMjEvNjMvMTI2LzE4OeODu+S4u+WwjuODu+WJjeaXpS8x6YCxPC9zcGFuPjxzcGFuIGNsYXNzPSJnIj7impk8L3NwYW4+PC9kaXY+CiAgICAgICAgPHRhYmxlIGNsYXNzPSJ0YiI+PHRoZWFkPjx0cj48dGggY2xhc3M9ImwiPuOCteODluODhuODvOODnjwvdGg+PHRoPlJTMjE8L3RoPjx0aD5SUzYzPC90aD48dGg+UlMxMjY8L3RoPjx0aD5SUzE4OTwvdGg+PHRoPumAsSU8L3RoPjx0aD7ku7bmlbA8L3RoPjx0aCBjbGFzcz0ibCI+5Li75bCOPC90aD48L3RyPjwvdGhlYWQ+PHRib2R5IGlkPSJzdWIiPjwvdGJvZHk+PC90YWJsZT4KICAgICAgICA8ZGl2IGNsYXNzPSJzZWN0dGwiPuOCu+OCr+OCv+ODvOODu+ODreODvOODhuODvOOCt+ODp+ODs++8iOWQhOacn+mWk+OBrumghuS9jeODu+KWsuKWvO+8neWJjeWIl+avlOOBrumghuS9jeWkieWMlu+8iTwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9InNlY3JhbmsiIGlkPSJzZWNyYW5rIj48L2Rpdj48L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9InQgc3AyIj48ZGl2IGNsYXNzPSJ0aCI+PGg0PlRvcOWAmeijnO+8iFJTMTg54omlODXjg7vpganmoLzvvIk8c3BhbiBjbGFzcz0iZW4iPlRvcCBDYW5kaWRhdGVzPC9zcGFuPjwvaDQ+PHNwYW4gY2xhc3M9InMiPlJTMjEvNjMvMTg544O75YmN5pel5q+U44O7dnM1MC8yMDDjg7tBRFLjg7vnirbmhYs8L3NwYW4+PHNwYW4gY2xhc3M9ImciPuKamTwvc3Bhbj48L2Rpdj4KICAgICAgICA8dGFibGUgY2xhc3M9InRiIj48dGhlYWQ+PHRyPjx0aD4jPC90aD48dGggY2xhc3M9ImwiPumKmOafhDwvdGg+PHRoPlJTMjE8L3RoPjx0aD5SUzYzPC90aD48dGg+UlMxODk8L3RoPjx0aD7liY3ml6Xmr5Q8L3RoPjx0aD52czUwPC90aD48dGg+dnMyMDA8L3RoPjx0aD5BRFI8L3RoPjx0aD7nirbmhYs8L3RoPjwvdHI+PC90aGVhZD48dGJvZHkgaWQ9InRvcCI+PC90Ym9keT48L3RhYmxlPjwvZGl2PgoKICAgICAgPCEtLSBST1cgNCAtLT4KICAgICAgPGRpdiBjbGFzcz0idCI+PGRpdiBjbGFzcz0idGgiPjxoND5SU+ODnuODq+ODgVRGIOe2mee2muaApzxzcGFuIGNsYXNzPSJlbiI+UlMgTXVsdGktVEYgUGVyc2lzdGVuY2U8L3NwYW4+PC9oND48c3BhbiBjbGFzcz0icyI+5pyf6ZaT44Gu6YeN44Gq44KK5Lu25pWwPC9zcGFuPjxzcGFuIGNsYXNzPSJnIj7impk8L3NwYW4+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0icnNxIj4KICAgICAgICAgIDxkaXYgY2xhc3M9InJzYm94Ij48ZGl2IGNsYXNzPSJyaCI+PHNwYW4gY2xhc3M9InJsIj7lhajmnJ/plpNUb3AxMDwvc3Bhbj48c3BhbiBjbGFzcz0icm4gbnVtIj7igJQ8L3NwYW4+PC9kaXY+PGRpdiBjbGFzcz0iY2hpcHMiPjwvZGl2PjwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0icnNib3giPjxkaXYgY2xhc3M9InJoIj48c3BhbiBjbGFzcz0icmwiPjYzw5cxMjY8L3NwYW4+PHNwYW4gY2xhc3M9InJuIG51bSI+4oCUPC9zcGFuPjwvZGl2PjxkaXYgY2xhc3M9ImNoaXBzIj48L2Rpdj48L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9InJzYm94Ij48ZGl2IGNsYXNzPSJyaCI+PHNwYW4gY2xhc3M9InJsIj4xMjbDlzE4OTwvc3Bhbj48c3BhbiBjbGFzcz0icm4gbnVtIj7igJQ8L3NwYW4+PC9kaXY+PGRpdiBjbGFzcz0iY2hpcHMiPjwvZGl2PjwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0icnNib3giPjxkaXYgY2xhc3M9InJoIj48c3BhbiBjbGFzcz0icmwiPjYzw5cxODk8L3NwYW4+PHNwYW4gY2xhc3M9InJuIG51bSI+4oCUPC9zcGFuPjwvZGl2PjxkaXYgY2xhc3M9ImNoaXBzIj48L2Rpdj48L2Rpdj4KICAgICAgICA8L2Rpdj48L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9InQiPjxkaXYgY2xhc3M9InRoIj48aDQ+44Oq44O844OA44O844Gu5Yqg6YCfIC8g5aSx6YCfPHNwYW4gY2xhc3M9ImVuIj5MZWFkZXIgQWNjZWwgLyBEZWNlbDwvc3Bhbj48L2g0PjxzcGFuIGNsYXNzPSJzIj7pgLHOlFJT44O75YWo5L2T5oSfPC9zcGFuPjxzcGFuIGNsYXNzPSJnIj7impk8L3NwYW4+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0ibW9tc3VtIj48c3Bhbj7liqDpgJ8gPGIgY2xhc3M9InBvcyI+4oCUPC9iPjwvc3Bhbj48c3Bhbj7kuK3nq4sgPGI+4oCUPC9iPjwvc3Bhbj48c3Bhbj7lpLHpgJ8gPGIgY2xhc3M9Im5lZyI+4oCUPC9iPjwvc3Bhbj48c3Bhbj7kuK3lpK4gPGIgY2xhc3M9Im5lZyBudW0iPuKAlDwvYj48L3NwYW4+PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0ibW9tYmFyIj48aSBzdHlsZT0id2lkdGg6MzMlO2JhY2tncm91bmQ6dmFyKC0tcG9zKSI+PC9pPjxpIHN0eWxlPSJ3aWR0aDoyNSU7YmFja2dyb3VuZDp2YXIoLS10cmFjaykiPjwvaT48aSBzdHlsZT0id2lkdGg6NDIlO2JhY2tncm91bmQ6dmFyKC0tbmVnKSI+PC9pPjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9Im1od3JhcCI+PGRpdiBjbGFzcz0ibWh0dGwiPumAsc6UUlMg5YiG5biD77yI44Oq44O844OA44O84oCU6YqY5p+E77yJPC9kaXY+PGRpdiBjbGFzcz0ibWgiIGlkPSJtb21oIj48L2Rpdj48L2Rpdj48L2Rpdj4KCiAgICAgIDxkaXYgY2xhc3M9InQgc3AyIj48ZGl2IGNsYXNzPSJ0aCI+PGg0PumHkeWIqeODu+ODnuOCr+ODreWcp+WKmzxzcGFuIGNsYXNzPSJlbiI+UmF0ZXMgJiBNYWNybzwvc3Bhbj48L2g0PjxzcGFuIGNsYXNzPSJzIj5GUkVE44O7MTBZLzJZLzNN5o6o56e7PC9zcGFuPjxzcGFuIGNsYXNzPSJnIj7impk8L3NwYW4+PC9kaXY+CiAgICAgICAgPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2dhcDoxNnB4O2ZsZXg6MTttaW4taGVpZ2h0OjAiPgogICAgICAgICAgPGRpdiBzdHlsZT0iZmxleDowIDAgYXV0bzt3aWR0aDoyMzBweCI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InJhdGVyb3ciPjxzcGFuIGNsYXNzPSJrIj7nsbMy5bm0IC8gMTDlubTlkI3nm648L3NwYW4+PHNwYW4gY2xhc3M9InYgbnVtIj7igJQgLyDigJQ8L3NwYW4+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InJhdGVyb3ciPjxzcGFuIGNsYXNzPSJrIj4xMOW5tOWun+izqiAvIOacn+W+he+9su++ne++jO++mjwvc3Bhbj48c3BhbiBjbGFzcz0idiBudW0iPuKAlCAvIOKAlDwvc3Bhbj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0icmF0ZXJvdyI+PHNwYW4gY2xhc3M9ImsiPjEwLTIg44K544OX44Os44OD44OJPC9zcGFuPjxzcGFuIGNsYXNzPSJ2IG51bSBwb3MiPuKAlDwvc3Bhbj48L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzcz0icmF0ZXJvdyI+PHNwYW4gY2xhc3M9ImsiPkhZIE9BUyAvIE5GQ0k8L3NwYW4+PHNwYW4gY2xhc3M9InYgbnVtIj7igJQgLyDigJQ8L3NwYW4+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InJhdGVyb3ciPjxzcGFuIGNsYXNzPSJrIj7luoPnvqnjg4njg6vmjIfmlbA8L3NwYW4+PHNwYW4gY2xhc3M9InYgbnVtIj4xMjEuMCA8c3BhbiBjbGFzcz0ibmVnIj7ihpE8L3NwYW4+PC9zcGFuPjwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8ZGl2IHN0eWxlPSJmbGV4OjE7ZGlzcGxheTpmbGV4O2ZsZXgtZGlyZWN0aW9uOmNvbHVtbjttaW4td2lkdGg6MCI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9ImxlZ2VuZCIgc3R5bGU9Im1hcmdpbjowIDAgNHB4Ij48c3Bhbj48aSBzdHlsZT0iYmFja2dyb3VuZDp2YXIoLS1uZWcpIj48L2k+MTBZPC9zcGFuPjxzcGFuPjxpIHN0eWxlPSJiYWNrZ3JvdW5kOnZhcigtLWFjY2VudCkiPjwvaT4yWTwvc3Bhbj48c3Bhbj48aSBzdHlsZT0iYmFja2dyb3VuZDp2YXIoLS1tdXQpIj48L2k+M008L3NwYW4+PC9kaXY+CiAgICAgICAgICAgIDxkaXYgaWQ9ImRfeWxkIiBzdHlsZT0iZmxleDoxO21pbi1oZWlnaHQ6MCI+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICA8L2Rpdj48L2Rpdj4KICAgIDwvZGl2PgogIDwvZGl2PgogIDwvZGl2PjwvZGl2PgoKPHNjcmlwdD4KICBmdW5jdGlvbiBzZXIoc2VlZCxuLGJhc2UsYW1wLGRyaWZ0KXt2YXIgYT1bXSx4PXNlZWQ7Zm9yKHZhciBpPTA7aTxuO2krKyl7eD0oeCo5MzAxKzQ5Mjk3KSUyMzMyODA7dmFyIHI9eC8yMzMyODA7YS5wdXNoKGJhc2UrZHJpZnQqaSsoci0wLjUpKmFtcCk7fXJldHVybiBhO30KICBmdW5jdGlvbiBsaW5lKHZhbHMsdyxoLHN0cm9rZSxmaWxsT3Ape3ZhciBtbj1NYXRoLm1pbi5hcHBseShudWxsLHZhbHMpLG14PU1hdGgubWF4LmFwcGx5KG51bGwsdmFscykscj0obXgtbW4pfHwxOwogICAgdmFyIHB0cz12YWxzLm1hcChmdW5jdGlvbih2LGkpe3JldHVybiBbaS8odmFscy5sZW5ndGgtMSkqdyxoLSgodi1tbikvcikqKGgtNiktM107fSk7CiAgICB2YXIgZD0nTScrcHRzLm1hcChmdW5jdGlvbihwKXtyZXR1cm4gcFswXS50b0ZpeGVkKDEpKycgJytwWzFdLnRvRml4ZWQoMSk7fSkuam9pbignIEwnKTsKICAgIHZhciBhPWZpbGxPcD8oJzxwYXRoIGQ9IicrZCsnIEwnK3crJyAnK2grJyBMMCAnK2grJyBaIiBmaWxsPSInK3N0cm9rZSsnIiBmaWxsLW9wYWNpdHk9IicrZmlsbE9wKyciLz4nKTonJzsKICAgIHJldHVybiAnPHN2ZyB2aWV3Qm94PSIwIDAgJyt3KycgJytoKyciIHByZXNlcnZlQXNwZWN0UmF0aW89Im5vbmUiIHN0eWxlPSJ3aWR0aDoxMDAlO2hlaWdodDonK2grJ3B4O2Rpc3BsYXk6YmxvY2siPicrYSsnPHBhdGggZD0iJytkKyciIGZpbGw9Im5vbmUiIHN0cm9rZT0iJytzdHJva2UrJyIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48L3N2Zz4nO30KICAvLyBzaGFyZWQtc2NhbGUgbXVsdGktbGluZSAoZml4ZXMgdGFuZ2xlZCBwYXJ0aWNpcGF0aW9uKQogIGZ1bmN0aW9uIG11bHRpbGluZShzZXJpZXMsdyxoLHBhZCl7cGFkPXBhZHx8MC4xMDt2YXIgYWxsPVtdO3Nlcmllcy5mb3JFYWNoKGZ1bmN0aW9uKHMpe2FsbD1hbGwuY29uY2F0KHMudmFscyk7fSk7CiAgICB2YXIgbW49TWF0aC5taW4uYXBwbHkobnVsbCxhbGwpLG14PU1hdGgubWF4LmFwcGx5KG51bGwsYWxsKSxyZz0obXgtbW4pfHwxO21uLT1yZypwYWQ7bXgrPXJnKnBhZDt2YXIgcj1teC1tbjsKICAgIHZhciBwYXRocz1zZXJpZXMubWFwKGZ1bmN0aW9uKHMpe3ZhciBwdHM9cy52YWxzLm1hcChmdW5jdGlvbih2LGkpe3JldHVybiBbaS8ocy52YWxzLmxlbmd0aC0xKSp3LGgtKCh2LW1uKS9yKSooaC00KS0yXTt9KTsKICAgICAgdmFyIGQ9J00nK3B0cy5tYXAoZnVuY3Rpb24ocCl7cmV0dXJuIHBbMF0udG9GaXhlZCgxKSsnICcrcFsxXS50b0ZpeGVkKDEpO30pLmpvaW4oJyBMJyk7CiAgICAgIHJldHVybiAnPHBhdGggZD0iJytkKyciIGZpbGw9Im5vbmUiIHN0cm9rZT0iJytzLnN0cm9rZSsnIiBzdHJva2Utd2lkdGg9IicrKHMud3x8MikrJyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Jzt9KS5qb2luKCcnKTsKICAgIHJldHVybiAnPHN2ZyB2aWV3Qm94PSIwIDAgJyt3KycgJytoKyciIHByZXNlcnZlQXNwZWN0UmF0aW89Im5vbmUiIHN0eWxlPSJ3aWR0aDoxMDAlO2hlaWdodDonK2grJ3B4O2Rpc3BsYXk6YmxvY2siPicrcGF0aHMrJzwvc3ZnPic7fQogIGZ1bmN0aW9uIGxpbmVEYXRlZCh2YWxzLHcsaCxzdHJva2UsZmlsbE9wLGxhYmVscyl7dmFyIG1uPU1hdGgubWluLmFwcGx5KG51bGwsdmFscyksbXg9TWF0aC5tYXguYXBwbHkobnVsbCx2YWxzKSxyPShteC1tbil8fDE7CiAgICB2YXIgcHRzPXZhbHMubWFwKGZ1bmN0aW9uKHYsaSl7cmV0dXJuIFtpLyh2YWxzLmxlbmd0aC0xKSp3LGgtKCh2LW1uKS9yKSooaC02KS0zXTt9KTsKICAgIHZhciBkPSdNJytwdHMubWFwKGZ1bmN0aW9uKHApe3JldHVybiBwWzBdLnRvRml4ZWQoMSkrJyAnK3BbMV0udG9GaXhlZCgxKTt9KS5qb2luKCcgTCcpOwogICAgdmFyIGdyaWQ9bGFiZWxzLm1hcChmdW5jdGlvbihMKXt2YXIgeD0oTC5pLyh2YWxzLmxlbmd0aC0xKSp3KS50b0ZpeGVkKDEpO3JldHVybiAnPGxpbmUgeDE9IicreCsnIiB5MT0iMCIgeDI9IicreCsnIiB5Mj0iJytoKyciIHN0cm9rZT0idmFyKC0tbGluZSkiIHN0cm9rZS13aWR0aD0iMSIgc3Ryb2tlLWRhc2hhcnJheT0iMyAzIi8+Jzt9KS5qb2luKCcnKTsKICAgIHZhciBhcmVhPWZpbGxPcD8oJzxwYXRoIGQ9IicrZCsnIEwnK3crJyAnK2grJyBMMCAnK2grJyBaIiBmaWxsPSInK3N0cm9rZSsnIiBmaWxsLW9wYWNpdHk9IicrZmlsbE9wKyciLz4nKTonJzsKICAgIHZhciBzdmc9Jzxzdmcgdmlld0JveD0iMCAwICcrdysnICcraCsnIiBwcmVzZXJ2ZUFzcGVjdFJhdGlvPSJub25lIiBzdHlsZT0id2lkdGg6MTAwJTtoZWlnaHQ6MTAwJTtkaXNwbGF5OmJsb2NrIj4nK2dyaWQrYXJlYSsnPHBhdGggZD0iJytkKyciIGZpbGw9Im5vbmUiIHN0cm9rZT0iJytzdHJva2UrJyIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48L3N2Zz4nOwogICAgdmFyIGxibHM9bGFiZWxzLm1hcChmdW5jdGlvbihMKXt2YXIgcGN0PShMLmkvKHZhbHMubGVuZ3RoLTEpKjEwMCkudG9GaXhlZCgyKTt2YXIgcG9zPUwuaT09PTA/J2xlZnQ6MCc6KEwuaT49dmFscy5sZW5ndGgtMT8ncmlnaHQ6MCc6J2xlZnQ6JytwY3QrJyU7dHJhbnNmb3JtOnRyYW5zbGF0ZVgoLTUwJSknKTtyZXR1cm4gJzxzcGFuIHN0eWxlPSJwb3NpdGlvbjphYnNvbHV0ZTsnK3BvcysnO2ZvbnQtc2l6ZTo5cHg7Y29sb3I6dmFyKC0tbXV0KSIgY2xhc3M9Im51bSI+JytMLnQrJzwvc3Bhbj4nO30pLmpvaW4oJycpOwogICAgcmV0dXJuICc8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2hlaWdodDoxMDAlIj48ZGl2IHN0eWxlPSJmbGV4OjE7bWluLWhlaWdodDowIj4nK3N2ZysnPC9kaXY+PGRpdiBzdHlsZT0icG9zaXRpb246cmVsYXRpdmU7aGVpZ2h0OjEycHg7bWFyZ2luLXRvcDozcHgiPicrbGJscysnPC9kaXY+PC9kaXY+Jzt9CiAgZnVuY3Rpb24gbXVsdGlsaW5lRGF0ZWQoc2VyaWVzLHcsaCxwYWQsbGFiZWxzKXtwYWQ9cGFkfHwwLjEwO3ZhciBhbGw9W107c2VyaWVzLmZvckVhY2goZnVuY3Rpb24ocyl7YWxsPWFsbC5jb25jYXQocy52YWxzKTt9KTsKICAgIHZhciBtbj1NYXRoLm1pbi5hcHBseShudWxsLGFsbCksbXg9TWF0aC5tYXguYXBwbHkobnVsbCxhbGwpLHJnPShteC1tbil8fDE7bW4tPXJnKnBhZDtteCs9cmcqcGFkO3ZhciByPW14LW1uO3ZhciBuPXNlcmllc1swXS52YWxzLmxlbmd0aDsKICAgIHZhciBncmlkPWxhYmVscy5tYXAoZnVuY3Rpb24oTCl7dmFyIHg9KEwuaS8obi0xKSp3KS50b0ZpeGVkKDEpO3JldHVybiAnPGxpbmUgeDE9IicreCsnIiB5MT0iMCIgeDI9IicreCsnIiB5Mj0iJytoKyciIHN0cm9rZT0idmFyKC0tbGluZSkiIHN0cm9rZS13aWR0aD0iMSIgc3Ryb2tlLWRhc2hhcnJheT0iMyAzIi8+Jzt9KS5qb2luKCcnKTsKICAgIHZhciBwYXRocz1zZXJpZXMubWFwKGZ1bmN0aW9uKHNyKXt2YXIgcHRzPXNyLnZhbHMubWFwKGZ1bmN0aW9uKHYsaSl7cmV0dXJuIFtpLyhzci52YWxzLmxlbmd0aC0xKSp3LGgtKCh2LW1uKS9yKSooaC00KS0yXTt9KTsKICAgICAgdmFyIGQ9J00nK3B0cy5tYXAoZnVuY3Rpb24ocHApe3JldHVybiBwcFswXS50b0ZpeGVkKDEpKycgJytwcFsxXS50b0ZpeGVkKDEpO30pLmpvaW4oJyBMJyk7CiAgICAgIHJldHVybiAnPHBhdGggZD0iJytkKyciIGZpbGw9Im5vbmUiIHN0cm9rZT0iJytzci5zdHJva2UrJyIgc3Ryb2tlLXdpZHRoPSInKyhzci53fHwyKSsnIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz4nO30pLmpvaW4oJycpOwogICAgdmFyIHN2Zz0nPHN2ZyB2aWV3Qm94PSIwIDAgJyt3KycgJytoKyciIHByZXNlcnZlQXNwZWN0UmF0aW89Im5vbmUiIHN0eWxlPSJ3aWR0aDoxMDAlO2hlaWdodDoxMDAlO2Rpc3BsYXk6YmxvY2siPicrZ3JpZCtwYXRocysnPC9zdmc+JzsKICAgIHZhciBsYmxzPWxhYmVscy5tYXAoZnVuY3Rpb24oTCl7dmFyIHBjdDI9KEwuaS8obi0xKSoxMDApLnRvRml4ZWQoMik7dmFyIHBvcz1MLmk9PT0wPydsZWZ0OjAnOihMLmk+PW4tMT8ncmlnaHQ6MCc6J2xlZnQ6JytwY3QyKyclO3RyYW5zZm9ybTp0cmFuc2xhdGVYKC01MCUpJyk7cmV0dXJuICc8c3BhbiBzdHlsZT0icG9zaXRpb246YWJzb2x1dGU7Jytwb3MrJztmb250LXNpemU6OXB4O2NvbG9yOnZhcigtLW11dCkiIGNsYXNzPSJudW0iPicrTC50Kyc8L3NwYW4+Jzt9KS5qb2luKCcnKTsKICAgIHJldHVybiAnPGRpdiBzdHlsZT0iZGlzcGxheTpmbGV4O2ZsZXgtZGlyZWN0aW9uOmNvbHVtbjtoZWlnaHQ6MTAwJSI+PGRpdiBzdHlsZT0iZmxleDoxO21pbi1oZWlnaHQ6MCI+JytzdmcrJzwvZGl2PjxkaXYgc3R5bGU9InBvc2l0aW9uOnJlbGF0aXZlO2hlaWdodDoxMnB4O21hcmdpbi10b3A6M3B4Ij4nK2xibHMrJzwvZGl2PjwvZGl2Pic7fQogIGZ1bmN0aW9uIGdhdWdlKHBjdCx3KXt2YXIgY3g9dy8yLGN5PXcqMC41LHJhZD13KjAuNDAsc3c9dyowLjEyLGg9dyowLjU4OwogICAgZnVuY3Rpb24gcHQoYSl7cmV0dXJuIFtjeCtyYWQqTWF0aC5jb3MoYSksY3ktcmFkKk1hdGguc2luKGEpXTt9CiAgICBmdW5jdGlvbiBBKHApe3JldHVybiBNYXRoLlBJKigxLXAvMTAwKTt9CiAgICBmdW5jdGlvbiBhcmMocDBwLHAxcCxjb2xvcix3aWR0aCxjYXApe3ZhciBxMD1wdChBKHAwcCkpLHExPXB0KEEocDFwKSk7cmV0dXJuICc8cGF0aCBkPSJNJytxMFswXS50b0ZpeGVkKDEpKycgJytxMFsxXS50b0ZpeGVkKDEpKycgQScrcmFkKycgJytyYWQrJyAwIDAgMSAnK3ExWzBdLnRvRml4ZWQoMSkrJyAnK3ExWzFdLnRvRml4ZWQoMSkrJyIgZmlsbD0ibm9uZSIgc3Ryb2tlPSInK2NvbG9yKyciIHN0cm9rZS13aWR0aD0iJyt3aWR0aCsnIiBzdHJva2UtbGluZWNhcD0iJysoY2FwfHwnYnV0dCcpKyciLz4nO30KICAgIHZhciB6b25lcz1hcmMoMCw0MCwndmFyKC0tbmVnYmcyKScsc3cpK2FyYyg0MCw2MCwndmFyKC0tbmV1YmcpJyxzdykrYXJjKDYwLDEwMCwndmFyKC0tcG9zYmcyKScsc3cpOwogICAgdmFyIHZhbD1hcmMoMCxwY3QsJ3ZhcigtLWFjY2VudCknLHN3KjAuNSwncm91bmQnKTsKICAgIHZhciBtPXB0KEEocGN0KSksbW89W2N4KyhyYWQtc3cqMC43MikqTWF0aC5jb3MoQShwY3QpKSxjeS0ocmFkLXN3KjAuNzIpKk1hdGguc2luKEEocGN0KSldLG1pPVtjeCsocmFkK3N3KjAuNzIpKk1hdGguY29zKEEocGN0KSksY3ktKHJhZCtzdyowLjcyKSpNYXRoLnNpbihBKHBjdCkpXTsKICAgIHZhciBtaz0nPGxpbmUgeDE9IicrbW9bMF0udG9GaXhlZCgxKSsnIiB5MT0iJyttb1sxXS50b0ZpeGVkKDEpKyciIHgyPSInK21pWzBdLnRvRml4ZWQoMSkrJyIgeTI9IicrbWlbMV0udG9GaXhlZCgxKSsnIiBzdHJva2U9InZhcigtLWluaykiIHN0cm9rZS13aWR0aD0iMi41Ii8+JzsKICAgIHJldHVybiAnPHN2ZyB2aWV3Qm94PSIwIDAgJyt3KycgJytoKyciIHN0eWxlPSJ3aWR0aDonK3crJ3B4O2hlaWdodDphdXRvIj4nK3pvbmVzK3ZhbCttaysnPC9zdmc+Jzt9CiAgdmFyIE1SSUxBQj1be2k6MCx0OiIifSx7aToxMCx0OiIifSx7aToyMCx0OiIifSx7aTozMCx0OiIifSx7aTozOSx0OiIifV07CiAgdmFyIExBQjFZPVt7aTowLHQ6IiJ9LHtpOjksdDoiIn0se2k6MTgsdDoiIn0se2k6MjcsdDoiIn1dOwogIHZhciBEPXttcmk6W10sYnJlYWR0aDpbXSxzZW50aTpbXSxmMTpbXSxmMjpbXSxmMzpbXSwKICAgIC8vIHBhcnRpY2lwYXRpb246IHNlcGFyYXRlZCBiYW5kcyBzbyBsaW5lcyBkb24ndCBjcm9zcwogICAgcF9xcXE6W10scF9zcHk6W10sCiAgICB5MTA6W10seTI6W10seTNtOltdfTsKICBmdW5jdGlvbiByc2Modil7dmFyIGJnLGZnO2lmKHY+PTgwKXtiZz0ndmFyKC0tcG9zYmcyKSc7Zmc9J3ZhcigtLXBvcyknO31lbHNlIGlmKHY+PTYwKXtiZz0ndmFyKC0tcG9zYmcpJztmZz0ndmFyKC0tcG9zKSc7fWVsc2UgaWYodj49NDApe2JnPSd0cmFuc3BhcmVudCc7Zmc9JyM0QTRDNDYnO31lbHNlIGlmKHY+PTIwKXtiZz0ndmFyKC0tbmVnYmcpJztmZz0ndmFyKC0tbmVnKSc7fWVsc2V7Ymc9J3ZhcigtLW5lZ2JnMiknO2ZnPSd2YXIoLS1uZWcpJzt9cmV0dXJuICc8dGQgY2xhc3M9InJzYyIgc3R5bGU9ImJhY2tncm91bmQ6JytiZysnO2NvbG9yOicrZmcrJyI+Jyt2Kyc8L3RkPic7fQogIGZ1bmN0aW9uIHBuYyh4KXtyZXR1cm4gKFN0cmluZyh4KS5pbmRleE9mKCctJyk8MCk/J3Bvcyc6J25lZyc7fQogIHZhciBTVUI9W107CiAgdmFyIFNFQz1bXTsKICB2YXIgVE9QPVtdOwogIHZhciBNT009W107CiAgZnVuY3Rpb24gc3RhdGVCYWRnZShzKXt2YXIgYz0ndmFyKC0tbXV0KSc7aWYocz09PSfimIUnKWM9J3ZhcigtLXdhcm4pJztlbHNlIGlmKHM9PT0nTkVXJ3x8cz09PSdSRVNVTUUnfHxzPT09J0FEVid8fHM9PT0n4oaRJyljPSd2YXIoLS1wb3MpJztlbHNlIGlmKHM9PT0nUEInKWM9J3ZhcigtLW5lZyknO3JldHVybiAnPHNwYW4gc3R5bGU9ImNvbG9yOicrYysnO2ZvbnQtd2VpZ2h0OjgwMDtmb250LXNpemU6MTAuNXB4Ij4nK3MrJzwvc3Bhbj4nO30KICBmdW5jdGlvbiByZW5kZXIoKXsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkX2cnKS5pbm5lckhUTUw9Z2F1Z2UoNzAsMTAwKTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkX21yaScpLmlubmVySFRNTD1saW5lRGF0ZWQoRC5tcmksNDQwLDExMCwndmFyKC0tcG9zKScsMC4xMixNUklMQUIpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RfYnInKS5pbm5lckhUTUw9bGluZURhdGVkKEQuYnJlYWR0aCwzMDAsNTgsJ3ZhcigtLWFjY2VudCknLDAuMTQsTEFCMVkpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RfcGFydCcpLmlubmVySFRNTD1tdWx0aWxpbmVEYXRlZChbe3ZhbHM6RC5wX3NweSxzdHJva2U6J3ZhcigtLW11dCknLHc6Mi40fSx7dmFsczpELnBfcXFxLHN0cm9rZTondmFyKC0tcG9zKScsdzoyLjR9XSwzMDAsNzAsMC4yNSxMQUIxWSk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZF9zZScpLmlubmVySFRNTD1saW5lRGF0ZWQoRC5zZW50aSwzMDAsNTgsJ3ZhcigtLW11dCknLDAuMTAsTEFCMVkpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RfZjEnKS5pbm5lckhUTUw9bGluZShELmYxLDExMCwzMCwndmFyKC0tcG9zKScsMC4xNCk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZF9mMicpLmlubmVySFRNTD1saW5lKEQuZjIsMTEwLDMwLCd2YXIoLS13YXJuKScsMC4xNCk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZF9mMycpLmlubmVySFRNTD1saW5lKEQuZjMsMTEwLDMwLCd2YXIoLS1uZWcpJywwLjE0KTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkX3lsZCcpLmlubmVySFRNTD1tdWx0aWxpbmVEYXRlZChbe3ZhbHM6RC55MTAsc3Ryb2tlOid2YXIoLS1uZWcpJyx3OjIuMn0se3ZhbHM6RC55MixzdHJva2U6J3ZhcigtLWFjY2VudCknLHc6Mi4yfSx7dmFsczpELnkzbSxzdHJva2U6J3ZhcigtLW11dCknLHc6Mi4yfV0sMzAwLDEyMCwwLjE1LE1SSUxBQik7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3ViJykuaW5uZXJIVE1MPVNVQi5tYXAoZnVuY3Rpb24ocyl7CiAgICAgIHJldHVybiAnPHRyPjx0ZCBjbGFzcz0ibCI+JytzWzBdKyc8L3RkPicrcnNjKHNbMV0pK3JzYyhzWzJdKStyc2Moc1szXSkrcnNjKHNbNF0pCiAgICAgICAgKyc8dGQgY2xhc3M9Im51bSAnK3BuYyhzWzVdKSsnIiBzdHlsZT0iZm9udC13ZWlnaHQ6ODAwIj4nK3NbNV0rJzwvdGQ+PHRkIGNsYXNzPSJudW0iIHN0eWxlPSJjb2xvcjp2YXIoLS1tdXQpIj4nK3NbNl0rJzwvdGQ+PHRkIGNsYXNzPSJsIG51bSI+JytzWzddKyc8L3RkPjwvdHI+Jzt9KS5qb2luKCcnKTsKICAgIHZhciBfcGVyPVtbJ+WJjeaXpScsMV0sWycx6YCxJywyXSxbJzHjg7bmnIgnLDNdXTsKICAgIHZhciBTRUNDT0w9eyfph5Hono0nOicjMkY2RTk2Jywn6YCa5L+hJzonIzdENUVBNicsJ+ODmOODq+OCueOCseOCoic6JyMzRTkyNzYnLCfljYrlsI7kvZMnOicjQzA3NjNBJywn57Sg5p2QJzonIzhGN0I0QScsJ+OCqOODjeODq+OCruODvCc6JyNBODRDNDAnLCfjg4bjg4Pjgq8nOicjNTY4MEEwJ307CiAgICBmdW5jdGlvbiBfcmFua3MoaWR4KXt2YXIgc3J0PVNFQy5zbGljZSgpLnNvcnQoZnVuY3Rpb24oYSxiKXtyZXR1cm4gcGFyc2VGbG9hdChiW2lkeF0pLXBhcnNlRmxvYXQoYVtpZHhdKTt9KTt2YXIgcms9e307c3J0LmZvckVhY2goZnVuY3Rpb24oeCxpKXtya1t4WzBdXT1pKzE7fSk7cmV0dXJuIHtvcmRlcjpzcnQscmFuazpya307fQogICAgdmFyIF9SPV9wZXIubWFwKGZ1bmN0aW9uKHBwKXtyZXR1cm4gX3JhbmtzKHBwWzFdKTt9KTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzZWNyYW5rJykuaW5uZXJIVE1MPV9wZXIubWFwKGZ1bmN0aW9uKHBwLGNpKXsKICAgICAgdmFyIFI9X1JbY2ldLCBwcmV2PWNpPjA/X1JbY2ktMV0ucmFuazpudWxsOwogICAgICB2YXIgcm93cz1SLm9yZGVyLm1hcChmdW5jdGlvbih4LGkpe3ZhciB2PXhbcHBbMV1dOwogICAgICAgIHZhciBhcj0nJzsKICAgICAgICBpZihwcmV2KXt2YXIgZD1wcmV2W3hbMF1dLShpKzEpOyBhcj0gZD4wPyc8c3BhbiBjbGFzcz0ic3JhciIgc3R5bGU9ImNvbG9yOnZhcigtLXBvcykiPuKWsicrZCsnPC9zcGFuPic6KGQ8MD8nPHNwYW4gY2xhc3M9InNyYXIiIHN0eWxlPSJjb2xvcjp2YXIoLS1uZWcpIj7ilrwnKygtZCkrJzwvc3Bhbj4nOic8c3BhbiBjbGFzcz0ic3JhciIgc3R5bGU9ImNvbG9yOnZhcigtLW11dCkiPsK3PC9zcGFuPicpO30KICAgICAgICByZXR1cm4gJzxkaXYgY2xhc3M9InNycm93Ij48c3BhbiBjbGFzcz0iZG90YyIgc3R5bGU9ImJhY2tncm91bmQ6JysoU0VDQ09MW3hbMF1dfHwnIzk5OScpKyciPjwvc3Bhbj48c3BhbiBjbGFzcz0icmsgbnVtIj4nKyhpKzEpKyc8L3NwYW4+PHNwYW4gY2xhc3M9InNubSI+Jyt4WzBdKyc8L3NwYW4+PHNwYW4gY2xhc3M9InN2Y2VsbCI+JythcisnPHNwYW4gY2xhc3M9InN2IG51bSAnK3BuYyh2KSsnIj4nK3YrJzwvc3Bhbj48L3NwYW4+PC9kaXY+Jzt9KS5qb2luKCcnKTsKICAgICAgcmV0dXJuICc8ZGl2IGNsYXNzPSJzcmNvbCI+PGRpdiBjbGFzcz0ic3JoIj4nK3BwWzBdKyc8L2Rpdj4nK3Jvd3MrJzwvZGl2Pic7fSkuam9pbignJyk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndG9wJykuaW5uZXJIVE1MPVRPUC5tYXAoZnVuY3Rpb24odCl7CiAgICAgIHJldHVybiAnPHRyPjx0ZCBjbGFzcz0ibnVtIiBzdHlsZT0iY29sb3I6dmFyKC0tbXV0KSI+Jyt0WzBdKyc8L3RkPjx0ZCBjbGFzcz0ibCBudW0iPicrdFsxXSsnPC90ZD4nK3JzYyh0WzJdKStyc2ModFszXSkrcnNjKHRbNF0pCiAgICAgICAgKyc8dGQgY2xhc3M9Im51bSAnK3BuYyh0WzVdKSsnIiBzdHlsZT0iZm9udC13ZWlnaHQ6ODAwIj4nK3RbNV0rJzwvdGQ+PHRkIGNsYXNzPSJudW0gJytwbmModFs2XSkrJyI+Jyt0WzZdKyc8L3RkPjx0ZCBjbGFzcz0ibnVtIHBvcyI+Jyt0WzddKyc8L3RkPjx0ZCBjbGFzcz0ibnVtIj4nK3RbOF0rJzwvdGQ+PHRkPicrc3RhdGVCYWRnZSh0WzldKSsnPC90ZD48L3RyPic7fSkuam9pbignJyk7CiAgICB2YXIgTU9NSD1bXTsKICAgIHZhciBfbW14PU1hdGgubWF4LmFwcGx5KG51bGwsTU9NSC5tYXAoZnVuY3Rpb24oYil7cmV0dXJuIGIuYzt9KSk7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnbW9taCcpLmlubmVySFRNTD1NT01ILm1hcChmdW5jdGlvbihiKXtyZXR1cm4gJzxkaXYgY2xhc3M9Im1oYiI+PHNwYW4gY2xhc3M9InYiIHN0eWxlPSJjb2xvcjonK2IuY29sKyciPicrYi5jKyc8L3NwYW4+PGRpdiBjbGFzcz0iYiIgc3R5bGU9ImhlaWdodDonKyhiLmMvX21teCoxMDApLnRvRml4ZWQoMSkrJyU7YmFja2dyb3VuZDonK2IuY29sKyciPjwvZGl2PjxzcGFuIGNsYXNzPSJ4Ij4nK2IubCsnPC9zcGFuPjwvZGl2Pic7fSkuam9pbignJyk7CiAgfQogIGZ1bmN0aW9uIGZpdCgpe3ZhciBzdGFnZT1kb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhZ2UnKSxzY2FsZXI9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NjYWxlcicpO3ZhciBzYz1NYXRoLm1pbigxLHN0YWdlLmNsaWVudFdpZHRoLzE2ODApO3NjYWxlci5zdHlsZS50cmFuc2Zvcm09J3NjYWxlKCcrc2MrJyknO3NjYWxlci5zdHlsZS5oZWlnaHQ9KDEwODAqc2MpKydweCc7c2NhbGVyLnN0eWxlLndpZHRoPScxNjgwcHgnO30KICByZW5kZXIoKTsgZml0KCk7IHdpbmRvdy5hZGRFdmVudExpc3RlbmVyKCdyZXNpemUnLGZpdCk7Cjwvc2NyaXB0Pgo8L2JvZHk+CjwvaHRtbD4K"
OV2_TPL_B64 = "PCFkb2N0eXBlIGh0bWw+CjxodG1sIGxhbmc9ImphIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9InV0Zi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCxpbml0aWFsLXNjYWxlPTEiPgo8dGl0bGU+44K744Kv44K/44O844O744Ot44O844OG44O844K344On44Oz77yI6Kmz57Sw77yJPC90aXRsZT4KPHN0eWxlPgogICp7Ym94LXNpemluZzpib3JkZXItYm94O21hcmdpbjowO3BhZGRpbmc6MH0KICBodG1sey13ZWJraXQtdGV4dC1zaXplLWFkanVzdDoxMDAlfQogIGJvZHl7YmFja2dyb3VuZDojMTExMDE0O2ZvbnQtZmFtaWx5Oi1hcHBsZS1zeXN0ZW0sJ0hlbHZldGljYSBOZXVlJyxBcmlhbCwnSGlyYWdpbm8gU2Fucycsc2Fucy1zZXJpZjtwYWRkaW5nOjEycHggOHB4IDUwcHg7Y29sb3I6I2RkZH0KICAudG9we21heC13aWR0aDoxNjgwcHg7bWFyZ2luOjAgYXV0byAxMHB4O3RleHQtYWxpZ246Y2VudGVyO2ZvbnQtc2l6ZToxM3B4O2NvbG9yOiM5YTlhYTR9CiAgLnN0YWdle3dpZHRoOjEwMCU7ZGlzcGxheTpmbGV4O2p1c3RpZnktY29udGVudDpjZW50ZXI7b3ZlcmZsb3c6aGlkZGVufS5zY2FsZXJ7dHJhbnNmb3JtLW9yaWdpbjp0b3AgY2VudGVyfQoKICAuY2FyZHt3aWR0aDoxNjgwcHg7aGVpZ2h0OjEwODBweDtiYWNrZ3JvdW5kOiNFOUU3REY7Y29sb3I6IzFCMUQxQztwYWRkaW5nOjE4cHggMjJweCAxMnB4O2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47CiAgICAtLWluazojMUIxRDFDOy0tbXV0OiM3Mjc1Njk7LS1saW5lOiNENUQxQzY7LS1jYXJkOiNGNkY0RUU7LS10cmFjazojREFENkNCOy0tYWNjZW50OiMxNzY4NUM7LS1hY2NlbnQyOiMyQTkzODQ7CiAgICAtLXBvczojMUU3QTREOy0tcG9zYmc6I0RCRUJERjstLXBvc2JnMjojQzZFMENDOy0tbmVnOiNCMjNBMkU7LS1uZWdiZzojRjFERUQ5Oy0tbmVnYmcyOiNFN0M3QzI7LS1uZXU6IzdDN0Y3ODstLW5ldWJnOiNFNkUzREI7LS13YXJuOiNCMDdBMTY7LS13YXJuYmc6I0YwRTZDRjsKICAgIC0tY2hpcGJnOiNFRUVCRTM7LS1mbnVtOnVpLW1vbm9zcGFjZSwnU0YgTW9ubycsTWVubG8sbW9ub3NwYWNlO2ZvbnQtc2l6ZToxMy41cHh9CiAgLm51bXtmb250LWZhbWlseTp2YXIoLS1mbnVtKTtmb250LXZhcmlhbnQtbnVtZXJpYzp0YWJ1bGFyLW51bXM7bGV0dGVyLXNwYWNpbmc6LS4wMWVtfQogIC5wb3N7Y29sb3I6dmFyKC0tcG9zKX0ubmVne2NvbG9yOnZhcigtLW5lZyl9LmFjY3tjb2xvcjp2YXIoLS1hY2NlbnQpfS53YXJuY3tjb2xvcjp2YXIoLS13YXJuKX0uaW5re2NvbG9yOnZhcigtLWluayl9CgogIC5oZHtkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDoxMXB4O21hcmdpbi1ib3R0b206NHB4fQogIC5oZCAuYmFye3dpZHRoOjVweDtoZWlnaHQ6MjFweDtiYWNrZ3JvdW5kOnZhcigtLWFjY2VudCk7Ym9yZGVyLXJhZGl1czozcHh9CiAgLmhkIGgxe2ZvbnQtc2l6ZToyMnB4O2ZvbnQtd2VpZ2h0OjgwMDtsZXR0ZXItc3BhY2luZzotLjAyZW19CiAgLmhkIC5wZ3tmb250LXNpemU6MTEuNXB4O2ZvbnQtd2VpZ2h0OjgwMDtjb2xvcjp2YXIoLS1hY2NlbnQpO2JvcmRlcjoxLjVweCBzb2xpZCB2YXIoLS1hY2NlbnQpO2JvcmRlci1yYWRpdXM6OHB4O3BhZGRpbmc6MnB4IDEwcHh9CiAgLmhkIC5kYXRle21hcmdpbi1sZWZ0OmF1dG87Zm9udC1zaXplOjEzLjVweDtjb2xvcjp2YXIoLS1tdXQpO2ZvbnQtd2VpZ2h0OjcwMH0KICAucmVhZHtmb250LXNpemU6MTNweDtmb250LXdlaWdodDo3MDA7Y29sb3I6IzMzMzUyRTttYXJnaW4tYm90dG9tOjhweDtsaW5lLWhlaWdodDoxLjM1O3BhZGRpbmctYm90dG9tOjhweDtib3JkZXItYm90dG9tOjEuNXB4IHNvbGlkIHZhcigtLWxpbmUpfQogIC5yZWFkIGJ7Y29sb3I6dmFyKC0tYWNjZW50KX0ucmVhZCAuZG57Y29sb3I6dmFyKC0tbmVnKX0KCiAgLmdyaWR7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczpyZXBlYXQoNCwxZnIpO2dyaWQtdGVtcGxhdGUtcm93czozOThweCAxZnI7Z2FwOjhweDtmbGV4OjE7bWluLWhlaWdodDowfQogIC5zcDJ7Z3JpZC1jb2x1bW46c3BhbiAyfS5zcDN7Z3JpZC1jb2x1bW46c3BhbiAzfQogIC50e2JhY2tncm91bmQ6dmFyKC0tY2FyZCk7Ym9yZGVyOjFweCBzb2xpZCB2YXIoLS1saW5lKTtib3JkZXItcmFkaXVzOjEwcHg7cGFkZGluZzo5cHggMTFweDttaW4taGVpZ2h0OjA7b3ZlcmZsb3c6aGlkZGVuO2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW59CiAgLnRoe2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjZweDttYXJnaW4tYm90dG9tOjZweH0KICAudGggaDR7Zm9udC1zaXplOjEyLjVweDtmb250LXdlaWdodDo4MDA7bGV0dGVyLXNwYWNpbmc6LS4wMWVtfS50aCAuc3tmb250LXNpemU6MTBweDtjb2xvcjp2YXIoLS1tdXQpO2ZvbnQtd2VpZ2h0OjcwMH0udGggLmd7bWFyZ2luLWxlZnQ6YXV0bztjb2xvcjp2YXIoLS1tdXQpO29wYWNpdHk6LjU7Zm9udC1zaXplOjEycHh9CgogIC5wcmd7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczpyZXBlYXQoNCwxZnIpO2dhcDoxMXB4O2ZsZXg6MTttaW4taGVpZ2h0OjB9CiAgLnByZy50aWdodHtnYXA6OHB4fQogIC5wcmNvbHtkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO21pbi1oZWlnaHQ6MH0KICAucHJjb2wgLnBoe2ZvbnQtc2l6ZToxMC41cHg7Zm9udC13ZWlnaHQ6ODAwO2NvbG9yOnZhcigtLWFjY2VudCk7dGV4dC1hbGlnbjpjZW50ZXI7Ym9yZGVyLWJvdHRvbToxLjVweCBzb2xpZCB2YXIoLS1saW5lKTtwYWRkaW5nLWJvdHRvbTozcHg7bWFyZ2luLWJvdHRvbToycHh9CiAgLnByY29sIC5waCBzcGFue2ZvbnQtc2l6ZTo5cHg7Y29sb3I6dmFyKC0tbXV0KTtmb250LXdlaWdodDo3MDB9CiAgLnByY29sIC5ib2R5e2ZsZXg6MTtkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2p1c3RpZnktY29udGVudDpzcGFjZS1iZXR3ZWVuO21pbi1oZWlnaHQ6MH0KICAucHJyb3d7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczo4cHggMTNweCAxZnIgYXV0byAyMHB4O2dhcDo1cHg7YWxpZ24taXRlbXM6Y2VudGVyO3doaXRlLXNwYWNlOm5vd3JhcH0KICAucHJyb3cgLnJre2NvbG9yOnZhcigtLW11dCk7dGV4dC1hbGlnbjpjZW50ZXJ9LnBycm93IC5ubXtmb250LXdlaWdodDo3MDA7b3ZlcmZsb3c6aGlkZGVuO3RleHQtb3ZlcmZsb3c6ZWxsaXBzaXN9CiAgLnBycm93IC5ydntmb250LXdlaWdodDo4MDA7Zm9udC1mYW1pbHk6dmFyKC0tZm51bSk7dGV4dC1hbGlnbjpyaWdodH0ucHJyb3cgLmFye2ZvbnQtd2VpZ2h0OjgwMDt0ZXh0LWFsaWduOnJpZ2h0fQogIC5kb3Rje2Rpc3BsYXk6aW5saW5lLWJsb2NrO3dpZHRoOjhweDtoZWlnaHQ6OHB4O2JvcmRlci1yYWRpdXM6NTAlfQogIC5tYWogLnBycm93e2ZvbnQtc2l6ZToxMnB4fS5tYWogLnBycm93IC5ya3tmb250LXNpemU6MTBweH0ubWFqIC5wcnJvdyAucnZ7Zm9udC1zaXplOjEycHh9Lm1haiAucHJyb3cgLmFye2ZvbnQtc2l6ZTo5LjVweH0KICAubWluIC5wcnJvd3tmb250LXNpemU6MTBweH0ubWluIC5wcnJvdyAucmt7Zm9udC1zaXplOjguNXB4fS5taW4gLnBycm93IC5ydntmb250LXNpemU6MTBweH0ubWluIC5wcnJvdyAuYXJ7Zm9udC1zaXplOjhweH0KICAubWluIC5wcnJvd3tncmlkLXRlbXBsYXRlLWNvbHVtbnM6N3B4IDEycHggMWZyIGF1dG8gMTZweDtnYXA6NHB4fS5taW4gLmRvdGN7d2lkdGg6NnB4O2hlaWdodDo2cHh9CgogIC5ycmd3cmFwe2ZsZXg6MTttaW4taGVpZ2h0OjB9CiAgI3JyZ3t3aWR0aDoxMDAlO2hlaWdodDoxMDAlfQoKICAvKiBtb25leSBmbG93ICovCiAgLmZsb3dib2R5e2ZsZXg6MTttaW4taGVpZ2h0OjA7ZGlzcGxheTpmbGV4O2ZsZXgtZGlyZWN0aW9uOmNvbHVtbjtnYXA6NHB4fQogIC5mdHRse2ZvbnQtc2l6ZToxMHB4O2ZvbnQtd2VpZ2h0OjgwMDtjb2xvcjp2YXIoLS1hY2NlbnQpO21hcmdpbi1ib3R0b206MXB4fQogIC5kdnJvd3tkaXNwbGF5OmdyaWQ7Z3JpZC10ZW1wbGF0ZS1jb2x1bW5zOjk2cHggMWZyIDQycHg7Z2FwOjZweDthbGlnbi1pdGVtczpjZW50ZXI7Zm9udC1zaXplOjExcHg7cGFkZGluZzoxcHggMH0KICAuZHZyb3cgLmRubXtmb250LXdlaWdodDo3MDA7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6NHB4O3doaXRlLXNwYWNlOm5vd3JhcDtvdmVyZmxvdzpoaWRkZW47dGV4dC1vdmVyZmxvdzplbGxpcHNpc30KICAuZHZ7cG9zaXRpb246cmVsYXRpdmU7aGVpZ2h0OjEwcHg7YmFja2dyb3VuZDp2YXIoLS10cmFjayk7Ym9yZGVyLXJhZGl1czozcHh9CiAgLmR2IC56ZXJve3Bvc2l0aW9uOmFic29sdXRlO2xlZnQ6NTAlO3RvcDotMnB4O2JvdHRvbTotMnB4O3dpZHRoOjFweDtiYWNrZ3JvdW5kOnZhcigtLW11dCk7b3BhY2l0eTouNTV9CiAgLmR2IC5maWxse3Bvc2l0aW9uOmFic29sdXRlO3RvcDowO2JvdHRvbTowO2JvcmRlci1yYWRpdXM6M3B4fQogIC5kdnJvdyAuZHZhbHt0ZXh0LWFsaWduOnJpZ2h0O2ZvbnQtd2VpZ2h0OjgwMDtmb250LWZhbWlseTp2YXIoLS1mbnVtKTtmb250LXNpemU6MTAuNXB4fQogIC5zZnNwbGl0e2Rpc3BsYXk6Z3JpZDtncmlkLXRlbXBsYXRlLWNvbHVtbnM6MWZyIDFmcjtnYXA6NHB4IDEycHg7Zm9udC1zaXplOjEwLjVweH0KICAuc2Zse2ZvbnQtc2l6ZTo5LjVweDtmb250LXdlaWdodDo4MDA7bWFyZ2luLWJvdHRvbToxcHg7ZGlzcGxheTpmbGV4O2dhcDo0cHg7YWxpZ24taXRlbXM6Y2VudGVyfQogIC5zZnJvd3tkaXNwbGF5OmZsZXg7anVzdGlmeS1jb250ZW50OnNwYWNlLWJldHdlZW47cGFkZGluZzoxcHggMDtib3JkZXItYm90dG9tOjFweCBzb2xpZCB2YXIoLS1saW5lKX0uc2Zyb3c6bGFzdC1jaGlsZHtib3JkZXItYm90dG9tOjB9CiAgLnNmcm93IC5zbntmb250LXdlaWdodDo3MDA7b3ZlcmZsb3c6aGlkZGVuO3RleHQtb3ZlcmZsb3c6ZWxsaXBzaXM7d2hpdGUtc3BhY2U6bm93cmFwfS5zZnJvdyAuc3Z7Zm9udC13ZWlnaHQ6ODAwO2ZvbnQtZmFtaWx5OnZhcigtLWZudW0pO3BhZGRpbmctbGVmdDo2cHh9CiAgLmZsb3dub3Rle21hcmdpbi10b3A6YXV0bztmb250LXNpemU6MTBweDtmb250LXdlaWdodDo2MDA7Y29sb3I6IzMzMzUyRTtsaW5lLWhlaWdodDoxLjM2O2JvcmRlci10b3A6MS41cHggc29saWQgdmFyKC0tbGluZSk7cGFkZGluZy10b3A6NXB4fQogIC5mbG93bm90ZSBie2NvbG9yOnZhcigtLWFjY2VudCl9Ci5ycmdsZWdlbmR7ZGlzcGxheTpmbGV4O2ZsZXgtd3JhcDp3cmFwO2dhcDozcHggMTJweDtqdXN0aWZ5LWNvbnRlbnQ6Y2VudGVyO3BhZGRpbmctdG9wOjRweDtmb250LXNpemU6OS41cHg7Y29sb3I6dmFyKC0tbXV0KTtmb250LXdlaWdodDo3MDA7ZmxleDowIDAgYXV0b30KICAucnJnbGVnZW5kIHNwYW57ZGlzcGxheTppbmxpbmUtZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjRweH0ucnJnbGVnZW5kIGl7d2lkdGg6OHB4O2hlaWdodDo4cHg7Ym9yZGVyLXJhZGl1czo1MCV9CiAgLmxkcm93e2Rpc3BsYXk6Z3JpZDtncmlkLXRlbXBsYXRlLWNvbHVtbnM6NjBweCAxZnI7Z2FwOjZweDthbGlnbi1pdGVtczpiYXNlbGluZTtwYWRkaW5nOjIuNXB4IDA7Ym9yZGVyLWJvdHRvbToxcHggc29saWQgdmFyKC0tbGluZSl9Lmxkcm93Omxhc3QtY2hpbGR7Ym9yZGVyLWJvdHRvbTowfQogIC5sZHB7Zm9udC1zaXplOjEwcHg7Zm9udC13ZWlnaHQ6ODAwO2NvbG9yOnZhcigtLWFjY2VudCk7d2hpdGUtc3BhY2U6bm93cmFwfS5sZHAgLnN7Zm9udC1zaXplOjguNXB4O2NvbG9yOnZhcigtLW11dCk7bWFyZ2luLWxlZnQ6M3B4fQogIC5sZHR7Zm9udC1mYW1pbHk6dmFyKC0tZm51bSk7Zm9udC13ZWlnaHQ6ODAwO2ZvbnQtc2l6ZToxMXB4O2xldHRlci1zcGFjaW5nOi0uMDFlbX0KLmxkcnN7ZmxleDoxO2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47anVzdGlmeS1jb250ZW50OnNwYWNlLWFyb3VuZDttaW4taGVpZ2h0OjA7Z2FwOjJweH0KICAubGRyb3cye2JvcmRlci1ib3R0b206MXB4IHNvbGlkIHZhcigtLWxpbmUpO3BhZGRpbmctYm90dG9tOjdweH0ubGRyb3cyOmxhc3QtY2hpbGR7Ym9yZGVyLWJvdHRvbTowfQogIC5sZHJvdzIgLmxoe2ZvbnQtc2l6ZToxMHB4O2ZvbnQtd2VpZ2h0OjgwMDtjb2xvcjp2YXIoLS1hY2NlbnQpO21hcmdpbi1ib3R0b206NXB4fS5sZHJvdzIgLmxoIC5ze2ZvbnQtc2l6ZTo4LjVweDtjb2xvcjp2YXIoLS1tdXQpO21hcmdpbi1sZWZ0OjRweH0KICAubGRyb3cyIC5sY3tkaXNwbGF5OmZsZXg7ZmxleC13cmFwOndyYXA7Z2FwOjVweH0KICAudGNoaXB7Zm9udC1mYW1pbHk6dmFyKC0tZm51bSk7Zm9udC1zaXplOjExLjVweDtmb250LXdlaWdodDo4MDA7YmFja2dyb3VuZDp2YXIoLS1jaGlwYmcpO2JvcmRlcjoxcHggc29saWQgdmFyKC0tbGluZSk7Ym9yZGVyLXJhZGl1czo1cHg7cGFkZGluZzoyLjVweCA4cHg7bGV0dGVyLXNwYWNpbmc6LS4wMWVtfQoudGggaDQgLmVue2ZvbnQtc2l6ZTo5LjVweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0KTttYXJnaW4tbGVmdDo2cHg7bGV0dGVyLXNwYWNpbmc6LjAyZW19CiAgLnBycm93IC5ubS5iaXtkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2xpbmUtaGVpZ2h0OjEuMDI7b3ZlcmZsb3c6aGlkZGVufQogIC5wcnJvdyAubm0uYmkgLmpwe292ZXJmbG93OmhpZGRlbjt0ZXh0LW92ZXJmbG93OmVsbGlwc2lzO3doaXRlLXNwYWNlOm5vd3JhcH0KICAucHJyb3cgLm5tLmJpIC5lbjJ7Zm9udC1zaXplOjcuNXB4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXQpO292ZXJmbG93OmhpZGRlbjt0ZXh0LW92ZXJmbG93OmVsbGlwc2lzO3doaXRlLXNwYWNlOm5vd3JhcH0KICAuZW4yaXtmb250LXNpemU6Ny41cHg7Zm9udC13ZWlnaHQ6NjAwO2NvbG9yOnZhcigtLW11dCl9CiAgLmR2cm93IC5kbm0uYml7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2FsaWduLWl0ZW1zOmZsZXgtc3RhcnQ7Z2FwOjA7bGluZS1oZWlnaHQ6MS4wMn0KICAuZHZyb3cgLmRubS5iaSAuanB7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6NHB4fS5kdnJvdyAuZG5tLmJpIC5lbjJ7Zm9udC1zaXplOjcuNXB4O2ZvbnQtd2VpZ2h0OjYwMDtjb2xvcjp2YXIoLS1tdXQpO3doaXRlLXNwYWNlOm5vd3JhcH0KPC9zdHlsZT4KPC9oZWFkPgo8Ym9keT4KICA8ZGl2IGNsYXNzPSJzdGFnZSIgaWQ9InN0YWdlIj48ZGl2IGNsYXNzPSJzY2FsZXIiIGlkPSJzY2FsZXIiPgogIDxkaXYgY2xhc3M9ImNhcmQiPgogICAgPGRpdiBjbGFzcz0iaGQiPjxzcGFuIGNsYXNzPSJiYXIiPjwvc3Bhbj48aDE+44K744Kv44K/44O844O744Ot44O844OG44O844K344On44OzIDxzcGFuIHN0eWxlPSJmb250LXNpemU6MTNweDtmb250LXdlaWdodDo2MDA7Y29sb3I6dmFyKC0tbXV0KTtsZXR0ZXItc3BhY2luZzouMDJlbSI+U2VjdG9yIFJvdGF0aW9uPC9zcGFuPjwvaDE+PHNwYW4gY2xhc3M9InBnIj4yIC8g6Kmz57SwPC9zcGFuPjxzcGFuIGNsYXNzPSJkYXRlIG51bSI+4oCUPC9zcGFuPjwvZGl2PgogICAgPGRpdiBjbGFzcz0icmVhZCI+4oCUPC9kaXY+CgogICAgPGRpdiBjbGFzcz0iZ3JpZCI+CiAgICAgIDwhLS0gUjE6IG1ham9yIHJhbmtpbmcgKyB3aWRlIHJvdGF0aW9uIG1hcCAtLT4KICAgICAgPGRpdiBjbGFzcz0idCBzcDIgbWFqIj48ZGl2IGNsYXNzPSJ0aCI+PGg0PuWkp+WIhumhniDigJQg5pyf6ZaT44GU44Go44Op44Oz44Kt44Oz44KwPHNwYW4gY2xhc3M9ImVuIj5NYWpvciBTZWN0b3JzIMK3IFJhbmsgYnkgUGVyaW9kPC9zcGFuPjwvaDQ+PHNwYW4gY2xhc3M9InMiPlJTMjEvNjMvMTI2LzE4OeODu+KWsuKWvO+8nemVt+acnyhSUzE4OSnpoIbkvY3jgYvjgonjga7lpInljJY8L3NwYW4+PHNwYW4gY2xhc3M9ImciPuKamTwvc3Bhbj48L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJwcmciIGlkPSJwcmdNYWoiPjwvZGl2PjwvZGl2PgoKICAgICAgPGRpdiBjbGFzcz0idCBzcDIiPjxkaXYgY2xhc3M9InRoIj48aDQ+6aCG5L2N44OV44Ot44O877yI5aSn5YiG6aGe77yJPHNwYW4gY2xhc3M9ImVuIj5SYW5rIEZsb3c8L3NwYW4+PC9oND48c3BhbiBjbGFzcz0icyI+6ZW35pyf4oaS55+t5pyf44GuUlPpoIbkvY3mjqjnp7vjg7vlj7PogqnkuIrjgYzjgorvvJ3os4fph5HmtYHlhaUgLyDlj7PogqnkuIvjgYzjgorvvJ3mtYHlh7o8L3NwYW4+PHNwYW4gY2xhc3M9ImciPuKamTwvc3Bhbj48L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJycmd3cmFwIj48ZGl2IGlkPSJidW1wIj48L2Rpdj48L2Rpdj48L2Rpdj4KCiAgICAgIDwhLS0gUjI6IGdyYW51bGFyIHN1YnRoZW1lIHJhbmtpbmcgKyByaWNoIGZsb3cgLS0+CiAgICAgIDxkaXYgY2xhc3M9InQgc3AzIG1pbiI+PGRpdiBjbGFzcz0idGgiPjxoND7lsI/liIbpoZ7vvIjjgrXjg5bjg4bjg7zjg57vvInigJQg5pyf6ZaT44GU44Go44Op44Oz44Kt44Oz44KwPHNwYW4gY2xhc3M9ImVuIj5TdWItdGhlbWVzIMK3IFJhbmsgYnkgUGVyaW9kPC9zcGFuPjwvaDQ+PHNwYW4gY2xhc3M9InMiPlJTMjEvNjMvMTI2LzE4OeODu+iJsu+8neWkp+WIhumhnuODu+KWsuKWvO+8nemVt+acn+mghuS9jeOBi+OCieOBruWkieWMljwvc3Bhbj48c3BhbiBjbGFzcz0iZyI+4pqZPC9zcGFuPjwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9InByZyB0aWdodCIgaWQ9InByZ01pbiI+PC9kaXY+PC9kaXY+CgogICAgICA8ZGl2IGNsYXNzPSJ0Ij48ZGl2IGNsYXNzPSJ0aCI+PGg0Puizh+mHkeOBrua1geOCjDxzcGFuIGNsYXNzPSJlbiI+TW9uZXkgRmxvdzwvc3Bhbj48L2g0PjxzcGFuIGNsYXNzPSJzIj7nn63mnJ9SUyDiiJIg6ZW35pyfUlM8L3NwYW4+PHNwYW4gY2xhc3M9ImciPuKamTwvc3Bhbj48L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJmbG93Ym9keSI+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJmdHRsIj7lpKfliIbpoZ7jg5Xjg63jg7zvvIjlt6Y95rWB5Ye6IO+8jyDlj7M95rWB5YWl77yJPC9kaXY+CiAgICAgICAgICA8ZGl2IGlkPSJtYWpmbG93Ij48L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImZ0dGwiIHN0eWxlPSJtYXJnaW4tdG9wOjVweCI+5pyf6ZaT44GU44Go44Gu5YWI5bCO5qCq77yIUlPkuIrkvY0177yJPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJsZHJzIiBpZD0ibGVhZGVycyI+PC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJmbG93bm90ZSIgaWQ9ImZub3RlIj48L2Rpdj4KICAgICAgICA8L2Rpdj48L2Rpdj4KICAgIDwvZGl2PgogIDwvZGl2PgogIDwvZGl2PjwvZGl2PgoKPHNjcmlwdD4KICB2YXIgUEFQRVI9JyNFOUU3REYnLElOSz0nIzFCMUQxQycsTVVUPScjNzI3NTY5JyxMSU5FPScjRDVEMUM2JyxBQ0M9JyMxNzY4NUMnLFdBUk49JyNCMDdBMTYnLE5FRz0nI0IyM0EyRScsCiAgICAgIFNBTlM9Ii1hcHBsZS1zeXN0ZW0sJ0hlbHZldGljYSBOZXVlJyxBcmlhbCxzYW5zLXNlcmlmIjsKICBmdW5jdGlvbiBjbGFtcCh2KXtyZXR1cm4gTWF0aC5tYXgoMyxNYXRoLm1pbig5OSxNYXRoLnJvdW5kKHYpKSk7fQogIHZhciBQQz17J+ODhuODg+OCryc6JyNDMDhBM0UnLCfjg4bjgq/jg47jg63jgrjjg7wnOicjQzA4QTNFJywn6YeR6J6NJzonIzJGNkU5NicsJ+mAmuS/oSc6JyM3RDVFQTYnLCfpgJrkv6HjgrXjg7zjg5PjgrknOicjN0Q1RUE2Jywn6LOH5pys6LKhJzonIzRFODc2OCcsJ+izh+acrOiyoS/pmLLooZsnOicjNEU4NzY4Jywn44OY44Or44K544Kx44KiJzonIzNFOTI3NicsJ+S4gOiIrOa2iOiyuyc6JyNCMDc5NEEnLCfkuIDoiKzmtojosrvosqEnOicjQjA3OTRBJywn57Sg5p2QJzonIzhGN0I0QScsJ+OCqOODjeODq+OCruODvCc6JyNBODRDNDAnLCflhaznm4onOicjOEE4QUEwJywn5LiN5YuV55SjJzonIzlBNkZBMCcsJ+eUn+a0u+W/hemcgOWTgSc6JyM3ODlBODgnfTsKCiAgdmFyIE1BSj1bXTsKCiAgLy8g5bCP5YiG6aGeIOKAlCDntLDliIbljJYo57SEMzApOiBbbmFtZSwgcGFyZW50LCBiYXNlKFJTMTg5KSwgdHJlbmRdCiAgdmFyIFNVQj1bXTsKCiAgZnVuY3Rpb24gcnNjRmcodil7aWYodj49ODApcmV0dXJuJ3ZhcigtLXBvcyknO2lmKHY+PTYwKXJldHVybicjMkM3QTRBJztpZih2Pj00MClyZXR1cm4nIzRBNEM0Nic7cmV0dXJuJ3ZhcigtLW5lZyknO30KICBmdW5jdGlvbiByYW5rQXJyKGl0ZW1zLGtleSl7cmV0dXJuIGl0ZW1zLnNsaWNlKCkuc29ydChmdW5jdGlvbihhLGIpe3JldHVybiBiLnJzW2tleV0tYS5yc1trZXldO30pO30KICBmdW5jdGlvbiBhcnJvdyhkKXtyZXR1cm4gZD4wPyc8c3BhbiBjbGFzcz0iYXIgcG9zIj7ilrInK2QrJzwvc3Bhbj4nOihkPDA/JzxzcGFuIGNsYXNzPSJhciBuZWciPuKWvCcrKC1kKSsnPC9zcGFuPic6JzxzcGFuIGNsYXNzPSJhciIgc3R5bGU9ImNvbG9yOnZhcigtLW11dCkiPsK3PC9zcGFuPicpO30KICBmdW5jdGlvbiByYW5rQmxvY2soaXRlbXMsZW5Nb2RlKXsKICAgIHZhciByMTg5PXJhbmtBcnIoaXRlbXMsJ3IxODknKSxyazE4OT17fTtyMTg5LmZvckVhY2goZnVuY3Rpb24oeCxpKXtyazE4OVt4Lm5hbWVdPWkrMTt9KTsKICAgIHZhciBwZXJpb2RzPVtbJ1JTMjEnLCdyMjEnLCfnn63mnJ8nXSxbJ1JTNjMnLCdyNjMnLCfkuK3nn60nXSxbJ1JTMTI2JywncjEyNicsJ+S4remVtyddLFsnUlMxODknLCdyMTg5Jywn6ZW35pyfJ11dOwogICAgcmV0dXJuIHBlcmlvZHMubWFwKGZ1bmN0aW9uKHApe3ZhciBhcnI9cmFua0FycihpdGVtcyxwWzFdKTsKICAgICAgdmFyIHJvd3M9YXJyLm1hcChmdW5jdGlvbih4LGkpe3ZhciBhcj1wWzFdPT09J3IxODknPyc8c3BhbiBjbGFzcz0iYXIiPjwvc3Bhbj4nOmFycm93KHJrMTg5W3gubmFtZV0tKGkrMSkpOwogICAgICAgIHZhciBubTtpZihlbk1vZGU9PT0nc3RhY2snJiZ4LmVuKXtubT0nPHNwYW4gY2xhc3M9Im5tIGJpIj48c3BhbiBjbGFzcz0ianAiPicreC5uYW1lKyc8L3NwYW4+PHNwYW4gY2xhc3M9ImVuMiI+Jyt4LmVuKyc8L3NwYW4+PC9zcGFuPic7fWVsc2UgaWYoZW5Nb2RlPT09J2lubGluZScmJnguZW4pe25tPSc8c3BhbiBjbGFzcz0ibm0iPjxzcGFuIGNsYXNzPSJqcCI+Jyt4Lm5hbWUrJzwvc3Bhbj4gPHNwYW4gY2xhc3M9ImVuMmkiPicreC5lbisnPC9zcGFuPjwvc3Bhbj4nO31lbHNle25tPSc8c3BhbiBjbGFzcz0ibm0iPicreC5uYW1lKyc8L3NwYW4+Jzt9CiAgICAgICAgcmV0dXJuICc8ZGl2IGNsYXNzPSJwcnJvdyI+PHNwYW4gY2xhc3M9ImRvdGMiIHN0eWxlPSJiYWNrZ3JvdW5kOicreC5jb2wrJyI+PC9zcGFuPjxzcGFuIGNsYXNzPSJyayBudW0iPicrKGkrMSkrJzwvc3Bhbj4nK25tKyc8c3BhbiBjbGFzcz0icnYiIHN0eWxlPSJjb2xvcjonK3JzY0ZnKHgucnNbcFsxXV0pKyciPicreC5yc1twWzFdXSsnPC9zcGFuPicrYXIrJzwvZGl2Pic7fSkuam9pbignJyk7CiAgICAgIHJldHVybiAnPGRpdiBjbGFzcz0icHJjb2wiPjxkaXYgY2xhc3M9InBoIj4nK3BbMF0rJyA8c3Bhbj4nK3BbMl0rJzwvc3Bhbj48L2Rpdj48ZGl2IGNsYXNzPSJib2R5Ij4nK3Jvd3MrJzwvZGl2PjwvZGl2Pic7fSkuam9pbignJyk7CiAgfQogIGZ1bmN0aW9uIHNwcmVhZCh4KXtyZXR1cm4geC5ycy5yMjEteC5ycy5yMTg5O30KCiAgLy8gV0lERSByb3RhdGlvbiBtYXA6IGZpbGxzIFcgeCBIIChubyBzaWRlIHdoaXRlc3BhY2UpLCBjaXJjbGVzIHN0YXkgcm91bmQgKHZpZXdCb3ggbWF0Y2hlcyBjb250YWluZXIpCiAgZnVuY3Rpb24gcnJnKHNlY3RvcnMsVyxIKXsKICAgIHZhciBwYWRMPVcqMC4wNTUscGFkUj1XKjAuMDU1LHBhZFQ9SCowLjEwLHBhZEI9SCowLjE0LHB3PVctcGFkTC1wYWRSLHBoPUgtcGFkVC1wYWRCOwogICAgdmFyIHhzPXNlY3RvcnMubWFwKGZ1bmN0aW9uKHMpe3JldHVybiBzLnJzLnIxODk7fSksbXM9c2VjdG9ycy5tYXAoZnVuY3Rpb24ocyl7cmV0dXJuIHNwcmVhZChzKTt9KTsKICAgIHZhciB4bWluPU1hdGgubWluLmFwcGx5KG51bGwseHMpLTUseG1heD1NYXRoLm1heC5hcHBseShudWxsLHhzKSs1LHltaW49TWF0aC5taW4uYXBwbHkobnVsbCxtcyktNCx5bWF4PU1hdGgubWF4LmFwcGx5KG51bGwsbXMpKzQ7CiAgICBmdW5jdGlvbiBYKHYpe3JldHVybiBwYWRMKygodi14bWluKS8oeG1heC14bWluKSkqcHc7fWZ1bmN0aW9uIFkodil7cmV0dXJuIHBhZFQrKDEtKHYteW1pbikvKHltYXgteW1pbikpKnBoO30KICAgIHZhciBteD14cy5yZWR1Y2UoZnVuY3Rpb24oYSxiKXtyZXR1cm4gYStiO30sMCkveHMubGVuZ3RoLG1tPW1zLnJlZHVjZShmdW5jdGlvbihhLGIpe3JldHVybiBhK2I7fSwwKS9tcy5sZW5ndGg7CiAgICB2YXIgY3g9WChteCksY3k9WShtbSksZG90Uj1NYXRoLm1heCg0LEgqMC4wMTUpLGZsPU1hdGgubWF4KDksSCowLjAzMiksZnE9TWF0aC5tYXgoMTEsSCowLjA0Mik7CiAgICBmdW5jdGlvbiByZWN0KHgseSx3LGgsYyxvKXtyZXR1cm4gJzxyZWN0IHg9IicreC50b0ZpeGVkKDEpKyciIHk9IicreS50b0ZpeGVkKDEpKyciIHdpZHRoPSInK3cudG9GaXhlZCgxKSsnIiBoZWlnaHQ9IicraC50b0ZpeGVkKDEpKyciIGZpbGw9IicrYysnIiBvcGFjaXR5PSInK28rJyIvPic7fQogICAgdmFyIHE9cmVjdChjeCxwYWRULHBhZEwrcHctY3gsY3ktcGFkVCxBQ0MsMC4wNykrcmVjdChwYWRMLHBhZFQsY3gtcGFkTCxjeS1wYWRULFdBUk4sMC4wNikrcmVjdChjeCxjeSxwYWRMK3B3LWN4LHBhZFQrcGgtY3ksTVVULDAuMDUpK3JlY3QocGFkTCxjeSxjeC1wYWRMLHBhZFQrcGgtY3ksTkVHLDAuMDYpOwogICAgdmFyIGZyYW1lPSc8cmVjdCB4PSInK3BhZEwrJyIgeT0iJytwYWRUKyciIHdpZHRoPSInK3B3KyciIGhlaWdodD0iJytwaCsnIiByeD0iNiIgZmlsbD0ibm9uZSIgc3Ryb2tlPSInK0xJTkUrJyIgc3Ryb2tlLXdpZHRoPSIxLjUiLz4nOwogICAgdmFyIGNyb3NzPSc8bGluZSB4MT0iJytjeC50b0ZpeGVkKDEpKyciIHkxPSInK3BhZFQrJyIgeDI9IicrY3gudG9GaXhlZCgxKSsnIiB5Mj0iJysocGFkVCtwaCkrJyIgc3Ryb2tlPSInK0xJTkUrJyIgc3Ryb2tlLXdpZHRoPSIxIi8+PGxpbmUgeDE9IicrcGFkTCsnIiB5MT0iJytjeS50b0ZpeGVkKDEpKyciIHgyPSInKyhwYWRMK3B3KSsnIiB5Mj0iJytjeS50b0ZpeGVkKDEpKyciIHN0cm9rZT0iJytMSU5FKyciIHN0cm9rZS13aWR0aD0iMSIvPic7CiAgICBmdW5jdGlvbiBjbCh4LHksYW5jLHQsYyl7cmV0dXJuICc8dGV4dCB4PSInK3gudG9GaXhlZCgxKSsnIiB5PSInK3kudG9GaXhlZCgxKSsnIiB0ZXh0LWFuY2hvcj0iJythbmMrJyIgZm9udC1mYW1pbHk9IicrU0FOUysnIiBmb250LXNpemU9IicrZnErJyIgZm9udC13ZWlnaHQ9IjgwMCIgbGV0dGVyLXNwYWNpbmc9IjIuNSIgZmlsbD0iJytjKyciIG9wYWNpdHk9IjAuODUiPicrdCsnPC90ZXh0Pic7fQogICAgdmFyIGNvcm5lcnM9Y2wocGFkTCtwdy0xMCxwYWRUK2ZxKzIsJ2VuZCcsJ+S4u+WwjicsQUNDKStjbChwYWRMKzEwLHBhZFQrZnErMiwnc3RhcnQnLCfmlLnlloQnLFdBUk4pK2NsKHBhZEwrcHctMTAscGFkVCtwaC04LCdlbmQnLCflvozpgIAnLE1VVCkrY2wocGFkTCsxMCxwYWRUK3BoLTgsJ3N0YXJ0Jywn5L2O6L+3JyxORUcpOwogICAgdmFyIGt4PTAuMTAsa3k9MC4xNix0YWlscz0nJyxoZWFkcz0nJzsKICAgIHZhciBIbj1zZWN0b3JzLm1hcChmdW5jdGlvbihzKXt2YXIgbW9tPXNwcmVhZChzKTtyZXR1cm4ge3M6cyxtb206bW9tLHJzOnMucnMucjE4OSx4Olgocy5ycy5yMTg5KSx5OlkobW9tKX07fSk7CiAgICBIbi5mb3JFYWNoKGZ1bmN0aW9uKGl0KXt2YXIgcz1pdC5zLG1vbT1pdC5tb207dmFyIHIxeD1YKGl0LnJzLW1vbSpreCkscjF5PVkobW9tLW1vbSpreSkscjJ4PVgoaXQucnMtMiptb20qa3gpLHIyeT1ZKG1vbS0yKm1vbSpreSk7CiAgICAgIHRhaWxzKz0nPHBhdGggZD0iTScrcjJ4LnRvRml4ZWQoMSkrJyAnK3IyeS50b0ZpeGVkKDEpKycgTCcrcjF4LnRvRml4ZWQoMSkrJyAnK3IxeS50b0ZpeGVkKDEpKycgTCcraXQueC50b0ZpeGVkKDEpKycgJytpdC55LnRvRml4ZWQoMSkrJyIgZmlsbD0ibm9uZSIgc3Ryb2tlPSInK3MuY29sKyciIHN0cm9rZS13aWR0aD0iJysoZG90UiowLjQpLnRvRml4ZWQoMSkrJyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBvcGFjaXR5PSIwLjMiLz4nOwogICAgICB0YWlscys9JzxjaXJjbGUgY3g9IicrcjF4LnRvRml4ZWQoMSkrJyIgY3k9IicrcjF5LnRvRml4ZWQoMSkrJyIgcj0iJysoZG90UiowLjQyKS50b0ZpeGVkKDEpKyciIGZpbGw9Iicrcy5jb2wrJyIgb3BhY2l0eT0iMC4zIi8+Jzt9KTsKICAgIEhuLmZvckVhY2goZnVuY3Rpb24oaXQpe3ZhciBzPWl0LnM7aGVhZHMrPSc8Y2lyY2xlIGN4PSInK2l0LngudG9GaXhlZCgxKSsnIiBjeT0iJytpdC55LnRvRml4ZWQoMSkrJyIgcj0iJytkb3RSLnRvRml4ZWQoMSkrJyIgZmlsbD0iJytzLmNvbCsnIi8+PGNpcmNsZSBjeD0iJytpdC54LnRvRml4ZWQoMSkrJyIgY3k9IicraXQueS50b0ZpeGVkKDEpKyciIHI9IicrZG90Ui50b0ZpeGVkKDEpKyciIGZpbGw9Im5vbmUiIHN0cm9rZT0iJytQQVBFUisnIiBzdHJva2Utd2lkdGg9IjEuOCIvPic7fSk7CiAgICB2YXIgY3huPWN4LGN5bj1jeTt2YXIgc2NvcmVkPUhuLm1hcChmdW5jdGlvbihpdCl7cmV0dXJuIHtpdDppdCxkOk1hdGguYWJzKGl0LngtY3huKStNYXRoLmFicyhpdC55LWN5bil9O30pLnNvcnQoZnVuY3Rpb24oYSxiKXtyZXR1cm4gYi5kLWEuZDt9KTsKICAgIHZhciBrZWVwPXt9O3Njb3JlZC5zbGljZSgwLDE0KS5mb3JFYWNoKGZ1bmN0aW9uKHope2tlZXBbei5pdC5zLm5hbWVdPTE7fSk7CiAgICB2YXIgbGFiPUhuLmZpbHRlcihmdW5jdGlvbihpdCl7cmV0dXJuIGtlZXBbaXQucy5uYW1lXTt9KS5tYXAoZnVuY3Rpb24oaXQpe3ZhciByaWdodD1pdC54PD1wYWRMK3B3KjAuNjI7cmV0dXJuIHt4Oml0LngrKHJpZ2h0P2RvdFIrNTotKGRvdFIrNSkpLHk6aXQueStmbCowLjM0LGFuY2hvcjpyaWdodD8nc3RhcnQnOidlbmQnLHQ6aXQucy5uYW1lfTt9KTsKICAgIFsnc3RhcnQnLCdlbmQnXS5mb3JFYWNoKGZ1bmN0aW9uKHNpZGUpe3ZhciBnPWxhYi5maWx0ZXIoZnVuY3Rpb24obCl7cmV0dXJuIGwuYW5jaG9yPT09c2lkZTt9KS5zb3J0KGZ1bmN0aW9uKGEsYil7cmV0dXJuIGEueS1iLnk7fSk7dmFyIG1nPWZsKjEuMTU7CiAgICAgIGZvcih2YXIgaT0xO2k8Zy5sZW5ndGg7aSsrKXtpZihnW2ldLnktZ1tpLTFdLnk8bWcpZ1tpXS55PWdbaS0xXS55K21nO30KICAgICAgdmFyIGJvdD1wYWRUK3BoLTIsdG9wPXBhZFQrZmw7aWYoZy5sZW5ndGgpe3ZhciBvdmVyPWdbZy5sZW5ndGgtMV0ueS1ib3Q7aWYob3Zlcj4wKWZvcih2YXIgaj0wO2o8Zy5sZW5ndGg7aisrKWdbal0ueT1NYXRoLm1heCh0b3AsZ1tqXS55LW92ZXIpO319KTsKICAgIHZhciBsYWJlbHM9bGFiLm1hcChmdW5jdGlvbihsKXtyZXR1cm4gJzx0ZXh0IHg9IicrbC54LnRvRml4ZWQoMSkrJyIgeT0iJytsLnkudG9GaXhlZCgxKSsnIiB0ZXh0LWFuY2hvcj0iJytsLmFuY2hvcisnIiBmb250LWZhbWlseT0iJytTQU5TKyciIGZvbnQtc2l6ZT0iJytmbCsnIiBmb250LXdlaWdodD0iNzAwIiBmaWxsPSInK0lOSysnIj4nK2wudCsnPC90ZXh0Pic7fSkuam9pbignJyk7CiAgICB2YXIgaGludD0nPHRleHQgeD0iJysocGFkTCtwdy8yKS50b0ZpeGVkKDEpKyciIHk9IicrKHBhZFQrcGgrcGFkQiowLjYyKS50b0ZpeGVkKDEpKyciIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtZmFtaWx5PSInK1NBTlMrJyIgZm9udC1zaXplPSInKyhmbCowLjk1KS50b0ZpeGVkKDEpKyciIGZpbGw9IicrTVVUKyciPuKGkCDlvLHjgYTjgIDnm7jlr77lvLfluqYoUlMxODkp44CA5by344GEIOKGkjwvdGV4dD4nOwogICAgcmV0dXJuICc8c3ZnIHZpZXdCb3g9IjAgMCAnK01hdGgucm91bmQoVykrJyAnK01hdGgucm91bmQoSCkrJyIgcHJlc2VydmVBc3BlY3RSYXRpbz0ibm9uZSIgc3R5bGU9IndpZHRoOjEwMCU7aGVpZ2h0OjEwMCU7ZGlzcGxheTpibG9jayI+JytxK2ZyYW1lK2Nyb3NzK2Nvcm5lcnMrdGFpbHMraGVhZHMrbGFiZWxzK2hpbnQrJzwvc3ZnPic7CiAgfQoKICBmdW5jdGlvbiBidW1wKGl0ZW1zLFcsSCl7CiAgICB2YXIgcGFkTD1XKjAuMDQ1LHBhZFI9VyowLjE1NSxwYWRUPUgqMC4xNixwYWRCPUgqMC4wNyxwdz1XLXBhZEwtcGFkUixwaD1ILXBhZFQtcGFkQjsKICAgIHZhciBrZXlzPVsncjE4OScsJ3IxMjYnLCdyNjMnLCdyMjEnXSxsYWJzPVtbJ1JTMTg5Jywn6ZW35pyfJ10sWydSUzEyNicsJ+S4remVtyddLFsnUlM2MycsJ+S4reefrSddLFsnUlMyMScsJ+efreacnyddXSxuPWl0ZW1zLmxlbmd0aDsKICAgIHZhciByYW5rcz1rZXlzLm1hcChmdW5jdGlvbihrKXt2YXIgYT1yYW5rQXJyKGl0ZW1zLGspLG09e307YS5mb3JFYWNoKGZ1bmN0aW9uKHgsaSl7bVt4Lm5hbWVdPWkrMTt9KTtyZXR1cm4gbTt9KTsKICAgIGZ1bmN0aW9uIFgoY2kpe3JldHVybiBwYWRMKyhjaS8oa2V5cy5sZW5ndGgtMSkpKnB3O31mdW5jdGlvbiBZKHJrKXtyZXR1cm4gcGFkVCsoKHJrLTEpLyhuLTEpKSpwaDt9CiAgICB2YXIgZG90Uj1NYXRoLm1heCgzLjUsSCowLjAxMyksZmw9TWF0aC5tYXgoOSxIKjAuMDMyKSxmaD1NYXRoLm1heCgxMCxIKjAuMDM4KTsKICAgIHZhciBncmlkPScnOwogICAgZm9yKHZhciByPTE7cjw9bjtyKyspe3ZhciB5PVkocik7Z3JpZCs9JzxsaW5lIHgxPSInK3BhZEwudG9GaXhlZCgxKSsnIiB5MT0iJyt5LnRvRml4ZWQoMSkrJyIgeDI9IicrKHBhZEwrcHcpLnRvRml4ZWQoMSkrJyIgeTI9IicreS50b0ZpeGVkKDEpKyciIHN0cm9rZT0iJytMSU5FKyciIHN0cm9rZS13aWR0aD0iMSIgb3BhY2l0eT0iMC40NSIvPic7CiAgICAgIGdyaWQrPSc8dGV4dCB4PSInKyhwYWRMLTYpLnRvRml4ZWQoMSkrJyIgeT0iJysoeStmbCowLjM0KS50b0ZpeGVkKDEpKyciIHRleHQtYW5jaG9yPSJlbmQiIGZvbnQtZmFtaWx5PSInK1NBTlMrJyIgZm9udC1zaXplPSInKyhmbCowLjg1KS50b0ZpeGVkKDEpKyciIGZpbGw9IicrTVVUKyciPicrcisnPC90ZXh0Pic7fQogICAgdmFyIHZnPScnLGhlYWRzPScnOwogICAgbGFicy5mb3JFYWNoKGZ1bmN0aW9uKGwsY2kpe3ZhciB4PVgoY2kpO3ZnKz0nPGxpbmUgeDE9IicreC50b0ZpeGVkKDEpKyciIHkxPSInK3BhZFQudG9GaXhlZCgxKSsnIiB4Mj0iJyt4LnRvRml4ZWQoMSkrJyIgeTI9IicrKHBhZFQrcGgpLnRvRml4ZWQoMSkrJyIgc3Ryb2tlPSInK0xJTkUrJyIgc3Ryb2tlLXdpZHRoPSIxIiBvcGFjaXR5PSIwLjMiLz4nOwogICAgICBoZWFkcys9Jzx0ZXh0IHg9IicreC50b0ZpeGVkKDEpKyciIHk9IicrKHBhZFQtZmgqMC45NSkudG9GaXhlZCgxKSsnIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LWZhbWlseT0iJytTQU5TKyciIGZvbnQtc2l6ZT0iJytmaCsnIiBmb250LXdlaWdodD0iODAwIiBmaWxsPSInK0FDQysnIj4nK2xbMF0rJzwvdGV4dD4nOwogICAgICBoZWFkcys9Jzx0ZXh0IHg9IicreC50b0ZpeGVkKDEpKyciIHk9IicrKHBhZFQtZmgqMC4xKS50b0ZpeGVkKDEpKyciIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtZmFtaWx5PSInK1NBTlMrJyIgZm9udC1zaXplPSInKyhmaCowLjYpLnRvRml4ZWQoMSkrJyIgZmlsbD0iJytNVVQrJyI+JytsWzFdKyc8L3RleHQ+Jzt9KTsKICAgIHZhciBsaW5lcz1pdGVtcy5tYXAoZnVuY3Rpb24oc2Mpe3ZhciBwdHM9a2V5cy5tYXAoZnVuY3Rpb24oayxjaSl7cmV0dXJuIFtYKGNpKSxZKHJhbmtzW2NpXVtzYy5uYW1lXSldO30pOwogICAgICB2YXIgZD0nTScrcHRzLm1hcChmdW5jdGlvbihwcCl7cmV0dXJuIHBwWzBdLnRvRml4ZWQoMSkrJyAnK3BwWzFdLnRvRml4ZWQoMSk7fSkuam9pbignIEwnKTsKICAgICAgdmFyIGRvdHM9cHRzLm1hcChmdW5jdGlvbihwcCl7cmV0dXJuICc8Y2lyY2xlIGN4PSInK3BwWzBdLnRvRml4ZWQoMSkrJyIgY3k9IicrcHBbMV0udG9GaXhlZCgxKSsnIiByPSInK2RvdFIudG9GaXhlZCgxKSsnIiBmaWxsPSInK3NjLmNvbCsnIiBzdHJva2U9IicrUEFQRVIrJyIgc3Ryb2tlLXdpZHRoPSIxLjIiLz4nO30pLmpvaW4oJycpOwogICAgICB2YXIgbHA9cHRzW3B0cy5sZW5ndGgtMV07CiAgICAgIHZhciBseD0obHBbMF0rZG90Uis1KS50b0ZpeGVkKDEpO3ZhciBsYmw9Jzx0ZXh0IHg9IicrbHgrJyIgeT0iJysobHBbMV0tZmwqMC4xOCkudG9GaXhlZCgxKSsnIiBmb250LWZhbWlseT0iJytTQU5TKyciIGZvbnQtc2l6ZT0iJytmbCsnIiBmb250LXdlaWdodD0iNzAwIiBmaWxsPSInK0lOSysnIj4nK3NjLm5hbWUrJzwvdGV4dD48dGV4dCB4PSInK2x4KyciIHk9IicrKGxwWzFdK2ZsKjAuNzIpLnRvRml4ZWQoMSkrJyIgZm9udC1mYW1pbHk9IicrU0FOUysnIiBmb250LXNpemU9IicrKGZsKjAuNjgpLnRvRml4ZWQoMSkrJyIgZmlsbD0iJytNVVQrJyI+Jysoc2MuZW58fCcnKSsnPC90ZXh0Pic7CiAgICAgIHJldHVybiAnPHBhdGggZD0iJytkKyciIGZpbGw9Im5vbmUiIHN0cm9rZT0iJytzYy5jb2wrJyIgc3Ryb2tlLXdpZHRoPSInKyhkb3RSKjAuOTUpLnRvRml4ZWQoMSkrJyIgb3BhY2l0eT0iMC44NSIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPicrZG90cytsYmw7fSkuam9pbignJyk7CiAgICByZXR1cm4gJzxzdmcgdmlld0JveD0iMCAwICcrTWF0aC5yb3VuZChXKSsnICcrTWF0aC5yb3VuZChIKSsnIiBwcmVzZXJ2ZUFzcGVjdFJhdGlvPSJub25lIiBzdHlsZT0id2lkdGg6MTAwJTtoZWlnaHQ6MTAwJTtkaXNwbGF5OmJsb2NrIj4nK2dyaWQrdmcraGVhZHMrbGluZXMrJzwvc3ZnPic7CiAgfQogIGZ1bmN0aW9uIHJlbmRlcigpewogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3ByZ01haicpLmlubmVySFRNTD1yYW5rQmxvY2soTUFKLCdzdGFjaycpOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3ByZ01pbicpLmlubmVySFRNTD1yYW5rQmxvY2soU1VCLCdpbmxpbmUnKTsKICAgIHZhciBtZj1NQUoubWFwKGZ1bmN0aW9uKG0pe3JldHVybiB7bmFtZTptLm5hbWUsZW46bS5lbixjb2w6bS5jb2wsc3A6c3ByZWFkKG0pfTt9KS5zb3J0KGZ1bmN0aW9uKGEsYil7cmV0dXJuIGIuc3AtYS5zcDt9KTsKICAgIHZhciBtYXhBYnM9TWF0aC5tYXguYXBwbHkobnVsbCxtZi5tYXAoZnVuY3Rpb24oeCl7cmV0dXJuIE1hdGguYWJzKHguc3ApO30pKXx8MTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtYWpmbG93JykuaW5uZXJIVE1MPW1mLm1hcChmdW5jdGlvbih4KXt2YXIgdz0oTWF0aC5hYnMoeC5zcCkvbWF4QWJzKjQ4KS50b0ZpeGVkKDEpOwogICAgICB2YXIgZmlsbD14LnNwPj0wPyc8c3BhbiBjbGFzcz0iZmlsbCIgc3R5bGU9ImxlZnQ6NTAlO3dpZHRoOicrdysnJTtiYWNrZ3JvdW5kOicreC5jb2wrJyI+PC9zcGFuPic6JzxzcGFuIGNsYXNzPSJmaWxsIiBzdHlsZT0icmlnaHQ6NTAlO3dpZHRoOicrdysnJTtiYWNrZ3JvdW5kOicreC5jb2wrJyI+PC9zcGFuPic7CiAgICAgIHJldHVybiAnPGRpdiBjbGFzcz0iZHZyb3ciPjxzcGFuIGNsYXNzPSJkbm0gYmkiPjxzcGFuIGNsYXNzPSJqcCI+PHNwYW4gY2xhc3M9ImRvdGMiIHN0eWxlPSJiYWNrZ3JvdW5kOicreC5jb2wrJyI+PC9zcGFuPicreC5uYW1lKyc8L3NwYW4+PHNwYW4gY2xhc3M9ImVuMiI+JysoeC5lbnx8JycpKyc8L3NwYW4+PC9zcGFuPjxzcGFuIGNsYXNzPSJkdiI+PHNwYW4gY2xhc3M9Inplcm8iPjwvc3Bhbj4nK2ZpbGwrJzwvc3Bhbj48c3BhbiBjbGFzcz0iZHZhbCAnKyh4LnNwPj0wPydwb3MnOiduZWcnKSsnIj4nKyh4LnNwPj0wPycrJzonJykreC5zcCsnPC9zcGFuPjwvZGl2Pic7fSkuam9pbignJyk7CiAgICB2YXIgaW5OPW1mLmZpbHRlcihmdW5jdGlvbih4KXtyZXR1cm4geC5zcD4wO30pLmxlbmd0aCxvdXROPW1mLmZpbHRlcihmdW5jdGlvbih4KXtyZXR1cm4geC5zcDwwO30pLmxlbmd0aDsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdmbm90ZScpLmlubmVySFRNTD0n5rWB5YWlIDxiPicraW5OKyc8L2I+IC8g5rWB5Ye6IDxiPicrb3V0TisnPC9iPiDlpKfliIbpoZ7jgIJIQk3jg7vlnLDpioDjg7vpm7vlipsv6Ziy6KGbQUnjgYznn63mnJ9SU+OBp+mVt+acn+OCkuWkp+OBjeOBj+S4iuaKnOOBje+8neizh+mHkea1geWFpeOAguefs+ayuS/jgqzjgrnjg7vmsrnnlLDjgrXjg7zjg5Pjgrnjg7vlhaznm4rjga/mtYHlh7rjgILjg43jg4Pjg4jjga88Yj7mlLvjgoE8L2I+44G45Zue6Lui44CCJzsKICAgIHZhciBhcmVhPWRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoJy5ycmd3cmFwJyk7ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2J1bXAnKS5pbm5lckhUTUw9YnVtcChNQUosYXJlYS5jbGllbnRXaWR0aCxhcmVhLmNsaWVudEhlaWdodCk7CiAgICB2YXIgTEVBREVSUz1bXTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdsZWFkZXJzJykuaW5uZXJIVE1MPUxFQURFUlMubWFwKGZ1bmN0aW9uKGwpe3JldHVybiAnPGRpdiBjbGFzcz0ibGRyb3cyIj48ZGl2IGNsYXNzPSJsaCI+JytsWzBdKyc8c3BhbiBjbGFzcz0icyI+JytsWzFdKyc8L3NwYW4+PC9kaXY+PGRpdiBjbGFzcz0ibGMiPicrbFsyXS5tYXAoZnVuY3Rpb24odCl7cmV0dXJuICc8c3BhbiBjbGFzcz0idGNoaXAiPicrdCsnPC9zcGFuPic7fSkuam9pbignJykrJzwvZGl2PjwvZGl2Pic7fSkuam9pbignJyk7CiAgfQogIGZ1bmN0aW9uIGZpdCgpe3ZhciBzdGFnZT1kb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc3RhZ2UnKSxzY2FsZXI9ZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NjYWxlcicpO3ZhciBzYz1NYXRoLm1pbigxLHN0YWdlLmNsaWVudFdpZHRoLzE2ODApO3NjYWxlci5zdHlsZS50cmFuc2Zvcm09J3NjYWxlKCcrc2MrJyknO3NjYWxlci5zdHlsZS5oZWlnaHQ9KDEwODAqc2MpKydweCc7c2NhbGVyLnN0eWxlLndpZHRoPScxNjgwcHgnO3JlbmRlcigpO30KICBmaXQoKTsgd2luZG93LmFkZEV2ZW50TGlzdGVuZXIoJ3Jlc2l6ZScsZml0KTsgc2V0VGltZW91dChmaXQsNjApOwo8L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+Cg=="


def _ov_num(x, d=1):
    try:
        v = float(x)
        return round(v, d) if v == v else None
    except Exception:
        return None


def _ov_pctstr(x, d=1):
    try:
        v = float(x) * 100.0
        return f"{v:+.{d}f}%"
    except Exception:
        return "—"


def _ov_pctstr_raw(x, d=1):
    """既に%値（例 3.1 が 3.1%）で来る場合。"""
    try:
        return f"{float(x):+.{d}f}%"
    except Exception:
        return "—"


def _ov_resample(vals, n):
    """任意長 → n点に等間隔リサンプル（末尾を必ず含む）。"""
    vals = [float(v) for v in vals if v == v]
    if not vals:
        return None
    if len(vals) == n:
        return [round(v, 3) for v in vals]
    out = []
    for i in range(n):
        p = i / (n - 1) * (len(vals) - 1)
        lo = int(_math2.floor(p)); hi = min(lo + 1, len(vals) - 1); fr = p - lo
        out.append(round(vals[lo] * (1 - fr) + vals[hi] * fr, 3))
    return out


def _ov_jsarr(vals):
    return "[" + ",".join(f"{v:.3f}" for v in vals) + "]"


_OV_INJECT_MISSES = []
def _ov_sub_required(pattern, replacement, text, name, flags=0):
    """重要スカラー注入用。count!=1（不一致or多重一致）を _OV_INJECT_MISSES に記録して検知する。
       replacement は文字列または関数（re.subn互換）。"""
    try:
        new_text, count = _re2.subn(pattern, replacement, text, count=1, flags=flags)
        if count != 1:
            _OV_INJECT_MISSES.append(f"sub:{name}:{count}")
            return text
        return new_text
    except Exception as _e:
        _OV_INJECT_MISSES.append(f"sub:{name}:ERR")
        return text
def _ov_replace_def(script, name, js_literal):
    """`var NAME=...;`（次のトップレベル ; まで）を丸ごと置換。ブラケット対応で終端を取る。
       パターン不一致（テンプレ変更等で注入失敗）は _OV_INJECT_MISSES に記録して検知可能にする。"""
    m = _re2.search(r'(var|const)\s+' + name + r'\s*=\s*', script)
    if not m:
        try: _OV_INJECT_MISSES.append("def:" + name)
        except Exception: pass
        return script
    i = m.end()
    depth = 0; j = i; instr = None
    while j < len(script):
        c = script[j]
        if instr:
            if c == '\\':
                j += 2; continue
            if c == instr:
                instr = None
        else:
            if c in "'\"":
                instr = c
            elif c in "[{(":
                depth += 1
            elif c in "]})":
                depth -= 1
            elif c == ';' and depth <= 0:
                break
        j += 1
    return script[:m.start()] + f'{m.group(1)} {name} = {js_literal}' + script[j:]


# ---- Overview 1 用データ計算 ----------------------------------------------
def _ov1_data(ctx):
    mkt = ctx.get("mkt") or {}
    aux = ctx.get("aux") or {}
    sar = ctx.get("sar") or (None, None)
    breadth = ctx.get("breadth") or {}
    sectors = ctx.get("sectors") or []
    perf = mkt.get("perf") or {}
    out = {"repl": {}, "defs": {}, "series": {}}

    # --- スコア・地合い ---
    score = None
    for k in ("mri_score", "score"):
        if isinstance(mkt.get(k), (int, float)):
            score = float(mkt[k]); break
    if score is None and isinstance(aux.get("cur"), (int, float)):
        score = float(aux["cur"])
    if score is not None:
        out["repl"]["gauge_val"] = int(round(score))

    # レジーム色/ラベル（sar色 or バンド）
    col = (sar[0] if isinstance(sar, (list, tuple)) and sar else None) or aux.get("regime_color")
    band_map = {"Blue": ("Blue", "強気", "bullc"), "Green": ("Green", "堅調", "posc"),
                "Yellow": ("Yellow", "やや注意", "warnc"), "Red": ("Red", "警戒", "negc")}
    if col in band_map:
        out["repl"]["regime"] = band_map[col]

    return out


def _ov_fs_patch(tpl):
    """フルスクリーン時に画面いっぱいに表示されるようレイアウトを補正する。
    - body背景を濃色→カードと同じベージュにし、余白が黒く見えないように
    - カードを画面中央に配置
    - 縦画面ではカードを90°回転して画面を最大活用、横画面は高さに合わせて最大化
    - 埋め込みタブ（aspect-ratio付きiframe）では横比率のため回転せず従来通りぴったり表示
    """
    # body: 濃色→ベージュ・全高フレックス中央・パディング撤去
    tpl = _re2.sub(
        r'body\{background:#111014;[^}]*\}',
        "html{height:100%}body{background:#E9E7DF;font-family:-apple-system,'Helvetica Neue',Arial,"
        "'Hiragino Sans','Noto Sans JP',sans-serif;margin:0;height:100%;display:flex;align-items:center;"
        "justify-content:center;overflow:hidden;color:#1B1D1C}", tpl, count=1)
    # stage: 全高フレックス中央
    tpl = _re2.sub(r'\.stage\{[^}]*\}',
                   ".stage{width:100%;height:100%;display:flex;align-items:center;justify-content:center;overflow:hidden}",
                   tpl, count=1)
    # scaler: 変形基準を中央へ
    tpl = _re2.sub(r'\.scaler\{transform-origin:[^}]*\}',
                   ".scaler{transform-origin:center center}", tpl, count=1)
    # fit(): contain＋縦回転
    tpl = _re2.sub(
        r'function fit\(\)\{var stage=document\.getElementById\(.stage.\),scaler=document\.getElementById\(.scaler.\);[^}]*\}',
        "function fit(){var scaler=document.getElementById('scaler');var W=window.innerWidth,H=window.innerHeight,"
        "cw=1680,ch=1080;if(H>W){var sc=Math.min(W/ch,H/cw);scaler.style.transform='rotate(90deg) scale('+sc+')';}"
        "else{var sc=Math.min(W/cw,H/ch);scaler.style.transform='scale('+sc+')';}"
        "scaler.style.width=cw+'px';scaler.style.height=ch+'px';if(typeof render==='function'){render();}}", tpl, count=1)
    # Publish内のミニチャートは欠損系列を描画しない。空配列のまま path を作ると
    # Chromiumで d="M" / d="M L..." となり、コンソールエラーと書式崩れの原因になる。
    _empty_chart = "'<div style=\"height:'+h+'px;display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:10.5px;opacity:.8\">履歴なし</div>'"
    tpl = tpl.replace(
        "function line(vals,w,h,stroke,fillOp){var mn=",
        "function line(vals,w,h,stroke,fillOp){if(!Array.isArray(vals)||vals.length<2)return " + _empty_chart + ";var mn=",
        1)
    tpl = tpl.replace(
        "function lineDated(vals,w,h,stroke,fillOp,labels){var mn=",
        "function lineDated(vals,w,h,stroke,fillOp,labels){if(!Array.isArray(vals)||vals.length<2)return " + _empty_chart + ";labels=Array.isArray(labels)?labels:[];var mn=",
        1)
    tpl = tpl.replace(
        "function multiline(series,w,h,pad){pad=pad||0.10;var all=[];series.forEach(function(s){all=all.concat(s.vals);});",
        "function multiline(series,w,h,pad){series=(Array.isArray(series)?series:[]).filter(function(s){return s&&Array.isArray(s.vals)&&s.vals.length>=2;});if(!series.length)return " + _empty_chart + ";pad=pad||0.10;var all=[];series.forEach(function(s){all=all.concat(s.vals);});",
        1)
    tpl = tpl.replace(
        "function multilineDated(series,w,h,pad,labels){pad=pad||0.10;var all=[];series.forEach(function(s){all=all.concat(s.vals);});",
        "function multilineDated(series,w,h,pad,labels){series=(Array.isArray(series)?series:[]).filter(function(s){return s&&Array.isArray(s.vals)&&s.vals.length>=2;});if(!series.length)return " + _empty_chart + ";labels=Array.isArray(labels)?labels:[];pad=pad||0.10;var all=[];series.forEach(function(s){all=all.concat(s.vals);});",
        1)
    # 色マップに「情報技術」を追加（sector_ranks は 情報技術 表記だが PC は テクノロジー のみ→線が無色化する対策）
    tpl = tpl.replace("var PC={", "var PC={'情報技術':'#C08A3E',", 1)
    # Top候補を「期間別リーダー」形式に：各RS期間(RS21/RS63/RS189)の上位5銘柄を全列表示。
    #   TOP は [{lab, rows:[...]}]。RS列は RS21/RS63/RS189 の3つ（RS126は出さない）。
    tpl = _re2.sub(
        r"getElementById\('top'\)\.innerHTML=TOP\.map\(function\(t\)\{.*?\}\)\.join\(''\);",
        "getElementById('top').innerHTML=TOP.map(function(g){if(!g||!g.rows)return '';return '<tr class=\"tsec\"><td colspan=\"10\">'"
        "+g.lab+'</td></tr>'+(g.rows||[]).map(function(t){return '<tr><td class=\"num\" style=\"color:var(--mut)\">'"
        "+t[0]+'</td><td class=\"l num\">'+t[1]+'</td>'+rsc(t[2])+rsc(t[3])+rsc(t[4])"
        "+'<td class=\"num '+pnc(t[5])+'\" style=\"font-weight:800\">'+t[5]+'</td><td class=\"num '+pnc(t[6])+'\">'"
        "+t[6]+'</td><td class=\"num pos\">'+t[7]+'</td><td class=\"num\">'+t[8]+'</td><td>'+stateBadge(t[9])"
        "+'</td></tr>';}).join('');}).join('');",
        tpl, count=1, flags=_re2.S)
    # 見出し行＋行を詰めて 18行(3期間×5＋見出し3)を下までぴったり埋める
    _top_css = ("#top .tsec td{background:#EDEAE1;color:#3d4137;font-weight:800;font-size:10.5px;"
                "padding:2px 8px 1px;letter-spacing:.03em;border-top:1px solid rgba(0,0,0,.10)}"
                "#top td{padding:3px 8px;font-size:11.5px;line-height:1.15}")
    tpl = tpl.replace("</style>", _top_css + "</style>", 1)
    tpl = tpl.replace("Top候補（RS189≥85・適格）", "期間別リーダー（各RS期間 上位5）", 1)
    tpl = tpl.replace("Top Candidates", "Period Leaders", 1)
    # サブテーマRS表も RS126 を外して 21/63/189 に統一（カード全体で期間軸を揃える）
    tpl = tpl.replace("RS21/63/126/189・主導・前日/1週", "RS21/63/189・主導・前日/1週", 1)
    tpl = tpl.replace("<th>RS63</th><th>RS126</th><th>RS189</th><th>週%</th>",
                      "<th>RS63</th><th>RS189</th><th>週%</th>", 1)
    tpl = tpl.replace("rsc(s[1])+rsc(s[2])+rsc(s[3])+rsc(s[4])",
                      "rsc(s[1])+rsc(s[2])+rsc(s[4])", 1)
    # RSマルチTF：チップを詰めて見切れ防止（最大10銘柄でも2〜3行で収まるように）
    _mtf_css = (".rsq .rsbox{padding:6px 8px}.rsq .chips{gap:3px}"
                ".rsq .chip{font-size:9.5px;padding:1px 5px;line-height:1.55}"
                ".rsq .rn{font-size:16px}.rsq .rh{margin-bottom:4px}")
    tpl = tpl.replace("</style>", _mtf_css + "</style>", 1)
    return tpl


def _ov_fold_patch(tpl):
    """本体の foldCalc と同じ発想で、冗長な説明文（コメント/判定/副題/フロー解説）を
    既定で閉じた <details> に折りたたむ。スクショ時は小さなトグルだけ残り本文は非表示、
    タップで展開できる。結論値・チャート・ランキングは常時表示のまま。"""
    css = ("details.ovfold{margin:8px 0 0}"
           "details.ovfold>summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;"
           "gap:5px;font-size:12px;font-weight:700;color:var(--mut);opacity:.68;user-select:none;padding:2px 0}"
           "details.ovfold>summary::-webkit-details-marker{display:none}"
           "details.ovfold>summary::before{content:'\\25B8';font-size:9px}"
           "details.ovfold[open]>summary::before{content:'\\25BE'}"
           "details.ovfold[open]>summary{margin-bottom:5px}"
           "details.ovfold:not([open])>*:not(summary){display:none!important}")
    js = ("<script>function ovFold(){try{"
          "function mk(label){var d=document.createElement('details');d.className='ovfold';"
          "var s=document.createElement('summary');s.textContent=label;d.appendChild(s);return d;}"
          # 単体（判定/副題/フロー解説）。コメントは常時表示のため畳まない。
          "var L={'fnote':'判定','read':'解説','flownote':'フロー解説'};"
          "['fnote','read','flownote'].forEach(function(cl){"
          "Array.prototype.forEach.call(document.getElementsByClassName(cl),function(el){"
          "if(el.closest('details.ovfold'))return;var d=mk(L[cl]||'詳しく');"
          "el.parentNode.insertBefore(d,el);d.appendChild(el);});});"
          "}catch(e){}}"
          "if(document.readyState!=='loading'){setTimeout(ovFold,90);}"
          "else{document.addEventListener('DOMContentLoaded',function(){setTimeout(ovFold,90);});}</script>")
    if "</style>" in tpl:
        tpl = tpl.replace("</style>", css + "</style>", 1)
    if "</body>" in tpl:
        tpl = tpl.replace("</body>", js + "</body>", 1)
    else:
        tpl = tpl + js
    return tpl


def build_overview_cards(ctx):
    """写真の元デザイン（テンプレート）に実データを差し込んで2枚のカードHTMLを返す。"""
    _OV_INJECT_MISSES.clear()   # 同一プロセス内で複数回生成しても前回の失敗記録を持ち越さない
    try:
        tpl1 = _ov_fold_patch(_ov_fs_patch(_b64.b64decode(OV1_TPL_B64).decode("utf-8")))
    except Exception:
        tpl1 = "<html><body>Overview 1</body></html>"
    try:
        tpl2 = _ov_fold_patch(_ov_fs_patch(_b64.b64decode(OV2_TPL_B64).decode("utf-8")))
    except Exception:
        tpl2 = "<html><body>Overview 2</body></html>"

    mkt = ctx.get("mkt") or {}
    aux = ctx.get("aux") or {}
    sar = ctx.get("sar") or (None, None)
    breadth = ctx.get("breadth") or {}
    sectors = ctx.get("sectors") or []
    m = ctx.get("m")
    perf = mkt.get("perf") or {}
    asof = ctx.get("asof_disp") or ""

    # =========================== Overview 1 ===================================
    doc1 = tpl1
    try:
        sc = _re2.search(r'<script>(.*?)</script>', doc1, _re2.S).group(1)
        sc0 = sc

        # ---- 時系列（D） ----
        def ts_vals(key):
            ser = mkt.get(key)
            if not ser:
                return None
            try:
                return [float(x[1]) for x in ser]
            except Exception:
                try:
                    return [float(x) for x in ser]
                except Exception:
                    return None
        Dparts = {}
        mri = ts_vals("mri_ts")
        if mri:
            Dparts["mri"] = _ov_resample(mri[-126:], 28)
        br = ts_vals("breadth_ts")
        if br:
            Dparts["breadth"] = _ov_resample([v * 100 if v <= 1.5 else v for v in br][-126:], 28)
        se = None
        senti = mkt.get("senti") or {}
        if senti.get("ts"):
            try:
                se = [float(x[1]) if isinstance(x, (list, tuple)) else float(x) for x in senti["ts"]]
            except Exception:
                se = None
        if se:
            Dparts["senti"] = _ov_resample(se[-126:], 28)
        # 売買代金参加度（QQQ/SPY）。build_dollarvol_ts の系列は ys（値）/ last_abs（$）。
        dv = mkt.get("dollarvol_ts") or {}
        try:
            series = dv.get("series") or []
            for s in series:
                lab = (s.get("name") or s.get("label") or "").upper()
                vals = s.get("ys") or s.get("vals") or s.get("values")
                if not vals:
                    continue
                clean = [float(v) for v in vals if v is not None and v == v]
                if len(clean) < 3:
                    continue
                if "QQQ" in lab:
                    Dparts["p_qqq"] = _ov_resample(clean[-126:], 28)
                elif "SPY" in lab:
                    Dparts["p_spy"] = _ov_resample(clean[-126:], 28)
        except Exception:
            pass
        # 金利チャート（10Y/2Y/3M の時系列）: fred_all の vals から。系列が無ければ空のまま（線は出ない）。
        try:
            _mcf = mkt.get("fred_all") or {}
            def _yld_ts(sid):
                d = _mcf.get(sid) or {}
                vv = d.get("vals") or []
                try:
                    arr = [float(x[1]) for x in vv if x[1] is not None and float(x[1]) == float(x[1])]
                    return _ov_resample(arr[-252:], 40) if len(arr) >= 3 else None
                except Exception:
                    return None
            _t10 = _yld_ts("DGS10"); _t2 = _yld_ts("DGS2"); _t3m = _yld_ts("DGS3MO")
            if _t10: Dparts["y10"] = _t10
            if _t2: Dparts["y2"] = _t2
            if _t3m: Dparts["y3m"] = _t3m
        except Exception:
            pass
        # F1/F2/F3の日次スパーク（d_f1/d_f2/d_f3）: reg_hist の *_series から
        try:
            _rh = mkt.get("reg_hist") or {}
            for _k, _sk in (("f1", "f1_series"), ("f2", "f2_series"), ("f3", "f3_series")):
                _arr = _rh.get(_sk)
                if _arr and len(_arr) >= 2:
                    Dparts[_k] = [float(x) * 100.0 if abs(float(x)) <= 1.5 else float(x) for x in _arr]
        except Exception:
            pass
        if Dparts:
            # 既存 D の各キーだけ差し替え（無いキーはテンプレの ser(...) を残す）
            mD = _re2.search(r'(var|const)\s+D\s*=\s*\{', sc)
            if mD:
                # D 全体を取り出し
                start = mD.end() - 1
                depth = 0; j = start
                while j < len(sc):
                    if sc[j] == '{': depth += 1
                    elif sc[j] == '}':
                        depth -= 1
                        if depth == 0: break
                    j += 1
                body = sc[start + 1:j]
                for k, arr in Dparts.items():
                    if arr is None: continue
                    body2 = _re2.sub(r'(\b' + k + r'\s*:\s*)ser\([^)]*\)', r'\1' + _ov_jsarr(arr), body)
                    if body2 == body:
                        body2 = _re2.sub(r'(\b' + k + r'\s*:\s*)\[[^\]]*\]', r'\1' + _ov_jsarr(arr), body)
                    body = body2
                sc = sc[:start + 1] + body + sc[j:]

        # ---- SEC（大分類ローテ d1/w1/m1） ----
        try:
            macro = ((mkt.get("sector_ranks") or {}).get("macro")) or []
            if macro:
                rows = []
                for x in macro[:7]:
                    nm = x.get("ja") or x.get("name") or "—"
                    rows.append([nm, _ov_pctstr(x.get("d1")), _ov_pctstr(x.get("w1")), _ov_pctstr(x.get("m1"))])
                lit = "[" + ",".join("['%s','%s','%s','%s']" % (r[0], r[1], r[2], r[3]) for r in rows) + "]"
                sc = _ov_replace_def(sc, "SEC", lit)
        except Exception:
            pass

        # ---- SUB（サブテーマRS表） ----
        try:
            if sectors:
                ss = sorted(sectors, key=lambda s: -(s.get("score") or s.get("med") or 0))[:8]
                rows = []
                def _clampi(v):
                    try:
                        return max(1, min(99, int(round(float(v)))))
                    except Exception:
                        return 50
                for s in ss:
                    med = float(s.get("med") or s.get("score") or 50)
                    med189 = float(s.get("med189") or med)
                    dw1 = float(s.get("d_w1") or 0)
                    r63 = _clampi(med); r189 = _clampi(med189)
                    r21 = _clampi(med + dw1); r126 = _clampi((med + med189) / 2)
                    wk = _ov_pctstr(s.get("w1"))
                    n = int(s.get("n") or 0)
                    members = s.get("members") or []
                    ldr = str(members[0][0]) if members else "—"
                    nm = s.get("ja") or "—"
                    rows.append([nm, r21, r63, r126, r189, wk, n, ldr])
                if rows:
                    lit = "[" + ",".join("['%s',%d,%d,%d,%d,'%s',%d,'%s']" %
                                         (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows) + "]"
                    sc = _ov_replace_def(sc, "SUB", lit)
        except Exception:
            pass

        # ---- TOP（期間別リーダー：各RS期間 RS21/RS63/RS189 の上位5・全列） ----
        try:
            if m is not None and hasattr(m, "sort_values"):
                periods = [("rs21", "RS21"), ("rs63", "RS63"), ("rs189", "RS189")]
                groups = []
                for col, lab in periods:
                    if col not in m.columns:
                        continue
                    dd = m.sort_values(col, ascending=False).head(5)
                    rows = []
                    for i, (tk, row) in enumerate(dd.iterrows(), 1):
                        tkn = str(row.get("ticker", tk))
                        def gi(*names):
                            for nm in names:
                                if nm in row and row[nm] == row[nm]:
                                    return row[nm]
                            return None
                        r21 = int(round(float(gi("rs21", col) or 0)))
                        r63 = int(round(float(gi("rs63", col) or 0)))
                        r189 = int(round(float(gi("rs189", col) or 0)))
                        d1 = _ov_pctstr(gi("pchg", "ret1", "d1", "chg", "chg1"))
                        vs50 = _ov_pctstr(gi("d50", "vs50", "ma50_dist"))
                        vs200 = _ov_pctstr(gi("d200", "vs200", "ma200_dist"))
                        adr = _ov_pctstr(gi("adr")) if gi("adr") is not None else "—"
                        st = str(gi("state", "flag") or "")
                        rows.append([i, tkn, r21, r63, r189, d1, vs50, vs200, adr, st])
                    if rows:
                        rows_lit = ",".join("[%d,'%s',%d,%d,%d,'%s','%s','%s','%s','%s']" %
                                            (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]) for r in rows)
                        groups.append("{lab:'%s',rows:[%s]}" % (lab, rows_lit))
                if groups:
                    lit = "[" + ",".join(groups) + "]"
                    sc = _ov_replace_def(sc, "TOP", lit)
        except Exception:
            pass

        # ---- MOM（加速/失速） ----
        try:
            lr = mkt.get("leader_run") or {}
            rows_lr = lr.get("rows") or []
            if rows_lr:
                order = {"加速": 0, "巡航": 1, "失速": 2}
                srt = sorted(rows_lr, key=lambda r: (order.get(r.get("phase"), 3),
                                                      -(r.get("d_recent") or 0)))
                acc = [r for r in srt if r.get("phase") == "加速"][:4]
                fad = [r for r in srt if r.get("phase") == "失速"][-4:]
                pick = acc + fad
                rows = []
                for r in pick:
                    d = int(round(float(r.get("d_recent") or 0)))
                    cls = "pos" if d >= 0 else "neg"
                    rows.append([str(r.get("t") or r.get("ticker") or "—"),
                                 f"{d:+d}", r.get("phase") or "", cls])
                if rows:
                    lit = "[" + ",".join("['%s','%s','%s','%s']" % (r[0], r[1], r[2], r[3]) for r in rows) + "]"
                    sc = _ov_replace_def(sc, "MOM", lit)
        except Exception:
            pass

        if sc != sc0:
            doc1 = doc1.replace(sc0, sc)
    except Exception:
        pass

    # ---- Overview 1 ヘッダ等スカラー置換（安全なアンカーのみ） ----
    try:
        # 日付
        if asof:
            doc1 = _ov_sub_required(r'<span class="date num">[^<]*</span>',
                            f'<span class="date num">{asof}</span>', doc1, "date_d1")
        # 地合いスコア（gauge & 数値）
        score = None
        for k in ("mri_score", "score"):
            if isinstance(mkt.get(k), (int, float)):
                score = int(round(mkt[k])); break
        if score is None and isinstance(aux.get("cur"), (int, float)):
            score = int(round(aux["cur"]))
        if score is not None:
            doc1 = doc1.replace("gauge(70,100)", f"gauge({score},100)")
            doc1 = _re2.sub(r'(<b class="num" style="font-size:27px">)[\d—]+(</b>)',
                            r'\g<1>' + str(score) + r'\g<2>', doc1, count=1)
        # 傾き・1D・1W・警戒灯（mkt20/auxから。テンプレは全て「—」なので実値を注入）
        try:
            _slope = aux.get("slope"); _bear = aux.get("bear_n")
            def _ts_d(ts, k):
                try:
                    if ts and len(ts) > k:
                        a = ts[-1][1] if isinstance(ts[-1], (list, tuple)) else ts[-1]
                        b = ts[-1-k][1] if isinstance(ts[-1-k], (list, tuple)) else ts[-1-k]
                        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                            return a - b
                except Exception:
                    pass
                return None
            _mri = mkt.get("mri_ts")
            _d1 = _ts_d(_mri, 1); _d5 = _ts_d(_mri, 5)
            def _sgn(v):
                if v is None:
                    return None
                return ("+%d" % round(v)) if v >= 0 else ("−%d" % round(-v))
            if _slope:
                _sc = "pos" if _slope == "↑" else ("neg" if _slope == "↓" else "mut")
                doc1 = _re2.sub(r'(<span class="lab">傾き</span> <b class=")[^"]*(">)[^<]*(</b>)',
                                lambda mm: mm.group(1) + _sc + mm.group(2) + _slope + mm.group(3), doc1, count=1)
            _d1t = _sgn(_d1)
            if _d1t is not None:
                _c1 = "num pos" if (_d1 is not None and _d1 >= 0) else "num neg"
                doc1 = _re2.sub(r'(<span class="lab">1D</span> <b class=")[^"]*(">)[^<]*(</b>)',
                                lambda mm: mm.group(1) + _c1 + mm.group(2) + _d1t + mm.group(3), doc1, count=1)
            _d5t = _sgn(_d5)
            if _d5t is not None:
                _c5 = "num pos" if (_d5 is not None and _d5 >= 0) else "num neg"
                doc1 = _re2.sub(r'(<span class="lab">1W</span> <b class=")[^"]*(">)[^<]*(</b>)',
                                lambda mm: mm.group(1) + _c5 + mm.group(2) + _d5t + mm.group(3), doc1, count=1)
            if isinstance(_bear, int):
                doc1 = _re2.sub(r'(<span class="lab">警戒灯</span> <b class="num">)[^<]*(</b>)',
                                lambda mm: mm.group(1) + ('%d/4' % _bear) + mm.group(2), doc1, count=1)
                # 点灯ドットをbear_n個だけ色付け
                def _leds(mm):
                    inner = mm.group(1)
                    dots = _re2.findall(r'<i[^>]*></i>', inner)
                    out = []
                    for _idx in range(len(dots)):
                        if _idx < _bear:
                            out.append('<i style="background:var(--neg)"></i>')
                        else:
                            out.append('<i></i>')
                    return '<span class="warnled">' + "".join(out) + '</span>'
                doc1 = _re2.sub(r'<span class="warnled">(.*?)</span>', _leds, doc1, count=1, flags=_re2.S)
        except Exception:
            pass
        # レジーム状態ピル（ラベル＋色をインライン指定して整合。CSSの警戒色固定を上書き）
        col = (sar[0] if isinstance(sar, (list, tuple)) and sar else None)
        lab_map = {"Blue": ("Blue", "強気", "#2456A6", "36,86,166"),
                   "Green": ("Green", "堅調", "#1E7A4D", "30,122,77"),
                   "Yellow": ("Yellow", "やや注意", "#A16207", "161,98,7"),
                   "Red": ("Red", "警戒", "#C2453A", "194,69,58")}
        if col in lab_map:
            nm, jp, hexc, rgb = lab_map[col]
            doc1 = _re2.sub(r'<span class="state">[^<]*</span>',
                            f'<span class="state" style="color:{hexc};border-color:{hexc}">{nm}・{jp}</span>', doc1, count=1)
            doc1 = _re2.sub(r'<span class="rn2 [^"]*">[^<]*</span>',
                            f'<span class="rn2" style="color:{hexc}">{nm}</span>', doc1, count=1)
            doc1 = _re2.sub(r'<span class="pill [^"]*">[^<]*</span>',
                            f'<span class="pill" style="color:{hexc}">{jp}</span>', doc1, count=1)
            doc1 = _re2.sub(r'<span class="dot"></span>',
                            f'<span class="dot" style="background:{hexc};box-shadow:0 0 0 4px rgba({rgb},.2)"></span>', doc1, count=1)
        # ブレッドス %（50/200）
        try:
            pa50 = breadth.get("pa50"); pa200 = breadth.get("pa200")
            cur200 = None
            brs = mkt.get("breadth_ts")
            if brs:
                v = brs[-1][1] if isinstance(brs[-1], (list, tuple)) else brs[-1]
                cur200 = v * 100 if v <= 1.5 else v
            if cur200 is None and isinstance(pa200, (int, float)):
                cur200 = pa200   # 時系列が無くても現値(200日線上%)は出す（大きな数値の空白を防ぐ）
            doc1 = _re2.sub(r'(<span class="chartn num acc">)[\d.—]+%?(</span>)',
                            lambda mm: mm.group(1) + (f'{cur200:.0f}%' if cur200 is not None else '—') + mm.group(2), doc1, count=1)
            if pa50 is not None and pa200 is not None:
                doc1 = _re2.sub(r'50日 <b class="ink">[\d.—]+%?</b>・200日 <b class="ink">[\d.—]+%?</b>',
                                f'50日 <b class="ink">{pa50:.0f}%</b>・200日 <b class="ink">{pa200:.0f}%</b>', doc1, count=1)
        except Exception:
            pass
        # センチメント数値・VIX
        try:
            scur = senti.get("cur")
            vix = (perf.get("vix") if isinstance(perf.get("vix"), (int, float))
                   else (perf.get("vix") or {}).get("cur") if isinstance(perf.get("vix"), dict) else None)
            doc1 = _re2.sub(r'(<span class="chartn num">)[\d—]+(</span>)',
                            lambda mm: mm.group(1) + (str(int(round(scur))) if scur is not None else '—') + mm.group(2), doc1, count=1)
            doc1 = _ov_sub_required(r'VIX [\d.—]+',
                            lambda mm: (f'VIX {vix:.1f}' if isinstance(vix, (int, float)) else 'VIX —'), doc1, "vix")
            pc = senti.get("pc") or senti.get("put_call") or (perf.get("pc") if isinstance(perf, dict) else None)
            doc1 = _ov_sub_required(r'P/C [\d.—]+',
                            lambda mm: (f'P/C {pc:.2f}' if isinstance(pc, (int, float)) else 'P/C —'), doc1, "pc")
        except Exception:
            pass

        # ---- ヘッダ統計（対象/適格/監視上位） ----
        try:
            uni = int(len(m)) if m is not None else None
            qual = None
            if m is not None and "rs189" in getattr(m, "columns", []):
                try:
                    qual = int(m["rs189"].notna().sum())
                except Exception:
                    qual = None
            watch = None
            try:
                lp = mkt.get("leader_run") or {}
                watch = int(lp.get("n")) if lp.get("n") else None
            except Exception:
                watch = None
            if uni:
                doc1 = _re2.sub(r'対象 <b>[\d—]+</b>', f'対象 <b>{uni}</b>', doc1, count=1)
            if qual:
                doc1 = _re2.sub(r'適格 <b>[\d—]+</b>', f'適格 <b>{qual}</b>', doc1, count=1)
            if watch:
                doc1 = _re2.sub(r'監視上位 <b>[\d—]+</b>', f'監視上位 <b>{watch}</b>', doc1, count=1)
        except Exception:
            pass

        # ---- MOM サマリー（加速/中立/失速/中央） ----
        try:
            lr = mkt.get("leader_run") or {}
            acc = lr.get("acc"); fade = lr.get("fade"); n = lr.get("n")
            if acc is not None and fade is not None and n is not None:
                neu = max(0, int(n) - int(acc) - int(fade))
                med = None
                rows = lr.get("rows") or []
                dvals = []
                for r in rows:
                    dv = (r.get("d_recent") if isinstance(r, dict) else None)
                    if isinstance(dv, (int, float)):
                        dvals.append(dv)
                if dvals:
                    dvals.sort(); med = dvals[len(dvals) // 2]
                new = ("<div class=\"momsum\"><span>加速 <b class=\"pos\">%d</b></span>"
                       "<span>中立 <b>%d</b></span><span>失速 <b class=\"neg\">%d</b></span>" % (int(acc), neu, int(fade)))
                if med is not None:
                    mc = "pos" if med > 0 else ("neg" if med < 0 else "mut")
                    sgn = ("+%d" % med) if med > 0 else (("−%d" % (-med)) if med < 0 else "0")
                    new += "<span>中央 <b class=\"%s num\">%s</b></span>" % (mc, sgn)
                else:
                    new += "<span>中央 <b class=\"mut num\">—</b></span>"
                doc1 = _re2.sub(r'<div class="momsum">.*?</span></div>',
                                new + "</div>", doc1, count=1, flags=_re2.S)
                # 「週ΔRS 分布（リーダーX銘柄）」の銘柄数も実数に（テンプレのサンプル73を置換）
                doc1 = _re2.sub(r'(週ΔRS 分布（リーダー)[\d—]+(銘柄）)',
                                lambda mm: mm.group(1) + str(int(n)) + mm.group(2), doc1, count=1)
                # MOMHヒストグラム（週ΔRS分布）を d_recent から実データ化（空配列のままだと空グラフになる）
                if dvals:
                    _bk = [("≤−15", "var(--neg)", lambda v: v <= -15),
                           ("−15〜−5", "var(--neg)", lambda v: -15 < v <= -5),
                           ("−5〜+5", "var(--mut)", lambda v: -5 < v < 5),
                           ("+5〜+15", "var(--pos)", lambda v: 5 <= v < 15),
                           ("≥+15", "var(--pos)", lambda v: v >= 15)]
                    _items = []
                    for _lab, _col, _fn in _bk:
                        _c = sum(1 for v in dvals if _fn(v))
                        _items.append("{l:'%s',c:%d,col:'%s'}" % (_lab, _c, _col))
                    _momh_lit = "[" + ",".join(_items) + "]"
                    doc1 = _re2.sub(r'var MOMH\s*=\s*\[\s*\]', 'var MOMH=' + _momh_lit, doc1, count=1)
        except Exception:
            pass

        # ---- 先導の崩れ F1/F2/F3（脱落率/狙い率/キュー崩れ） ----
        try:
            rh = mkt.get("reg_hist") or {}
            _rs_state = mkt.get("regime_state")
            _state_ok = isinstance(_rs_state, dict) and bool(_rs_state)   # 適格母集団≥30でregime_stateが算出済みか
            rs_state = _rs_state or {}
            def _pctf(x):
                try:
                    v = float(x)
                    if v != v:
                        return None
                    return v * 100.0 if v <= 1.5 else v
                except Exception:
                    return None
            if _state_ok:
                # F1はreg_hist(時系列)が正だが、F2/F3はregime_stateにしか無い。全てregime_state優先で拾う。
                f1 = _pctf(rs_state.get("f1")); f2 = _pctf(rs_state.get("f2")); f3 = _pctf(rs_state.get("f3"))
                if f1 is None: f1 = _pctf(rh.get("f1_now"))
            else:
                f1 = f2 = f3 = None   # 適格が少なくregime_state算出不可 → F1だけ0%等の不整合を避け3つとも—
            def _fv_sub(_cls, _val):
                # クラスで対象を特定し値に関わらず必ず置換（テンプレ既定値が残る固定値化を防ぐ）。値なしは「—」
                _txt = ('%d%%' % round(_val)) if _val is not None else '—'
                return _re2.sub(r'(<div class="fv %s num">)[^<]*(</div>)' % _cls,
                                lambda mm: mm.group(1) + _txt + mm.group(2), doc1, count=1)
            doc1 = _fv_sub('pos', f1)      # 脱落率
            doc1 = _fv_sub('warnc', f2)    # 狙い率
            doc1 = _fv_sub('neg', f3)      # キュー崩れ
            # 判定文（事実ベース・処方箋なし）。全値揃わなければ既定文を残さずデータ不足表示に
            if not _state_ok:
                fn = '判定：適格銘柄が少なく先導分析を保留（適格12銘柄以上で有効）。'
            elif None not in (f1, f2, f3):
                labs = [("脱落率", f1), ("狙い率", f2), ("キュー崩れ", f3)]
                hi = max(labs, key=lambda x: x[1])
                qual_word = "良好" if (f1 < 20 and f3 < 40) else ("低下" if (f1 >= 30 or f3 >= 60) else "混在")
                fn = f'判定：{hi[0]}が最も高く{hi[1]:.0f}%。監視銘柄の質は{qual_word}。'
            else:
                fn = '判定：データ準備中（履歴の蓄積待ち）。'
            doc1 = _re2.sub(r'<div class="fnote">判定：[^<]*</div>',
                            f'<div class="fnote">{fn}</div>', doc1, count=1)
        except Exception:
            pass

        # ---- 金利・マクロ（FRED実値。全系列=fred_allから。macro_contextは金利のみで不足） ----
        try:
            mc = mkt.get("fred_all") or {}
            def _fv(sid):
                d = mc.get(sid) or {}
                vals = d.get("vals") or []
                if vals:
                    try:
                        return float(vals[-1][1])
                    except Exception:
                        return None
                return None
            y2 = _fv("DGS2"); y10 = _fv("DGS10"); y10r = _fv("DFII10"); infl = _fv("T10YIE")
            slope = _fv("T10Y2Y")
            if slope is None and (y10 is not None and y2 is not None):
                slope = y10 - y2
            hy = _fv("BAMLH0A0HYM2"); nfci = _fv("NFCI"); dxy = _fv("DTWEXBGS")
            def _pair(v1, v2, fmt="%.2f / %.2f"):
                return (fmt % (v1, v2)) if (v1 is not None and v2 is not None) else "— / —"
            doc1 = _ov_sub_required(r'(米2年 / 10年名目</span><span class="v num">)[^<]*(</span>)',
                            lambda mm: mm.group(1) + _pair(y2, y10) + mm.group(2), doc1, "rate_2y_10y")
            doc1 = _ov_sub_required(r'(10年実質 / 期待ｲﾝﾌﾚ</span><span class="v num">)[^<]*(</span>)',
                            lambda mm: mm.group(1) + _pair(y10r, infl) + mm.group(2), doc1, "rate_real_infl")
            doc1 = _ov_sub_required(r'(10-2 スプレッド</span><span class="v num[^"]*">)[^<]*(</span>)',
                            lambda mm: mm.group(1) + (('%+.2f' % slope) if slope is not None else '—') + mm.group(2), doc1, "rate_slope")
            doc1 = _ov_sub_required(r'(HY OAS / NFCI</span><span class="v num">)[^<]*(</span>)',
                            lambda mm: mm.group(1) + (('%.2f / %+.2f' % (hy, nfci)) if (hy is not None and nfci is not None) else '— / —') + mm.group(2), doc1, "rate_hy_nfci")
            # 広義ドル指数：値＋矢印をまとめて方向に応じ置換（固定↑を排除）。上昇=neg(株の逆風)。
            _dxy_d = mc.get("DTWEXBGS") or {}
            _dxy_vals = _dxy_d.get("vals") or []
            dxy_chg = None
            try:
                _cl = [float(x[1]) for x in _dxy_vals if x[1] is not None and float(x[1]) == float(x[1])]
                if len(_cl) >= 6:
                    dxy_chg = _cl[-1] - _cl[-6]
                elif len(_cl) >= 2:
                    dxy_chg = _cl[-1] - _cl[-2]
            except Exception:
                dxy_chg = None
            if dxy is None:
                _dxy_html = '<span class="v num">—</span>'
            else:
                if dxy_chg is not None and dxy_chg > 0:
                    _ar, _cls = '↑', 'neg'
                elif dxy_chg is not None and dxy_chg < 0:
                    _ar, _cls = '↓', 'pos'
                else:
                    _ar, _cls = '→', 'mut'
                _dxy_html = '<span class="v num">%.1f <span class="%s">%s</span></span>' % (dxy, _cls, _ar)
            doc1 = _ov_sub_required(r'(広義ドル指数</span>)<span class="v num">[^<]*(?:<span[^>]*>[^<]*</span>)?</span>',
                            lambda mm: mm.group(1) + _dxy_html, doc1, "dollar_index")
        except Exception:
            pass

        # ---- 売買代金 凡例（QQQ/SPY $B）: series の last_abs（$）を $B 換算 ----
        try:
            dv = mkt.get("dollarvol_ts")
            qqqb = spyb = None
            if isinstance(dv, dict):
                for s in (dv.get("series") or []):
                    lab = (s.get("name") or s.get("label") or "").upper()
                    la = s.get("last_abs")
                    if not isinstance(la, (int, float)) or la != la:
                        continue
                    b = la / 1e9 if la > 1e6 else la  # 生$なら$B換算、既に$Bならそのまま
                    if "QQQ" in lab:
                        qqqb = b
                    elif "SPY" in lab:
                        spyb = b
            if qqqb is not None:
                doc1 = _ov_sub_required(r'QQQ \$[\d.—]+B?', f'QQQ ${qqqb:.1f}B', doc1, "dvol_qqq")
            if spyb is not None:
                doc1 = _ov_sub_required(r'SPY \$[\d.—]+B?', f'SPY ${spyb:.1f}B', doc1, "dvol_spy")
        except Exception:
            pass

        # ---- コメント（今日/今週：このページの要点ダイジェスト・事実ベース） ----
        try:
            macro = ((mkt.get("sector_ranks") or {}).get("macro")) or []
            def _sw(x):
                return x.get("w1") if isinstance(x, dict) else None
            def _wpct(w):
                return f"{w*100:+.1f}%" if abs(w) <= 1.5 else f"{w:+.1f}%"
            secs = [s for s in macro if isinstance(_sw(s), (int, float))]
            top = sorted(secs, key=lambda s: -_sw(s))[:2]
            bot = sorted(secs, key=lambda s: _sw(s))[:2]
            lr = mkt.get("leader_run") or {}
            acc, fade = lr.get("acc"), lr.get("fade")
            rh = mkt.get("reg_hist") or {}
            _rst_c = mkt.get("regime_state") or {}
            def _pf(x):
                try:
                    v = float(x)
                    return (v * 100 if v <= 1.5 else v) if v == v else None
                except Exception:
                    return None
            f3 = _pf(_rst_c.get("f3"))
            if f3 is None: f3 = _pf(rh.get("f3_now"))
            pa50 = breadth.get("pa50")
            adpct = breadth.get("adpct")   # 真の当日上昇銘柄率(adv/(adv+dec))。pa50(50MA上比率)とは別物。
            regime = sar[0] if (isinstance(sar, (list, tuple)) and sar) else None
            streak = (mkt.get("regime_state") or {}).get("streak")
            score = aux.get("cur") if isinstance(aux, dict) else None

            # ===== 今日：地合いスナップショット =====
            s1 = []
            seg = ""
            if regime:
                seg = "レジーム" + regime + (f"（{streak}日連続）" if isinstance(streak, int) else "")
            if isinstance(score, (int, float)):
                seg = (seg + "・" if seg else "") + f"地合い{score:.0f}"
            if seg:
                s1.append(seg)
            if isinstance(adpct, (int, float)):
                ap = adpct * 100 if adpct <= 1.5 else adpct
                q = "狭い" if ap < 40 else ("広い" if ap >= 60 else "中位")
                s1.append(f"上昇銘柄{ap:.0f}%で広がりは{q}")
            s2 = []
            if top:
                tnm = "・".join((t.get("ja") or "—") for t in top)
                lt = f"主導は{tnm}"
                if isinstance(_sw(top[0]), (int, float)):
                    lt += f"（{_wpct(_sw(top[0]))}）"
                if bot:
                    lt += f"、{bot[0].get('ja')}は後退"
                s2.append(lt)
            if acc is not None and fade is not None:
                ls = f"先導株は加速{acc}/失速{fade}"
                if f3 is not None:
                    qual = "質低下" if (fade > acc and f3 >= 55) else ("良好" if (acc >= fade and f3 < 40) else "混在")
                    ls += f"・キュー崩れ{f3:.0f}%（{qual}）"
                s2.append(ls)
            cx1 = "。".join([x for x in ["。".join(s1), "。".join(s2)] if x])
            if cx1:
                cx1 += "。"
                doc1 = _ov_sub_required(r'(<div class="cl">今日</div><div class="cx">)[^<]*(</div>)',
                                lambda mm: mm.group(1) + cx1 + mm.group(2), doc1, "cmt_today")
            else:
                doc1 = _ov_sub_required(r'(<div class="cl">今日</div><div class="cx">)[^<]*(</div>)',
                                lambda mm: mm.group(1) + "データ準備中。" + mm.group(2), doc1, "cmt_today")

            # ===== 今週：流動性＋フロー＋センチメント＋金利の背景 =====
            s3 = []
            nl = mkt.get("net_liq")
            _nlr = _net_liq_read(nl)
            if nl and nl.get("vals") and _nlr:
                s3.append(f"ネット流動性は{_nlr[0]}（${nl['last']:.2f}T）")
            if top:
                tnm = "・".join((t.get("ja") or "—") for t in top)
                fl = f"資金は{tnm}へ"
                if bot:
                    fl += f"、{('・'.join((b.get('ja') or '—') for b in bot))}から流出"
                s3.append(fl)
            vix = perf.get("vix")
            if isinstance(vix, dict):
                vix = vix.get("cur")
            pc = senti.get("pc") or senti.get("put_call")
            sent_bits = []
            if isinstance(vix, (int, float)):
                sent_bits.append(f"VIX{vix:.1f}")
            if isinstance(pc, (int, float)):
                sent_bits.append(f"P/C{pc:.2f}")
            if sent_bits:
                s3.append("センチメントは" + "・".join(sent_bits))
            mc = mkt.get("fred_all") or {}
            def _fv(sid):
                d = mc.get(sid) or {}
                vv = d.get("vals") or []
                try:
                    return float(vv[-1][1]) if vv else None
                except Exception:
                    return None
            y2, y10 = _fv("DGS2"), _fv("DGS10")
            if y2 is not None and y10 is not None:
                s3.append(f"金利は2年{y2:.2f}/10年{y10:.2f}")
            cx2 = "。".join(s3)
            if cx2:
                cx2 += "。"
                doc1 = _ov_sub_required(r'(<div class="cl">今週</div><div class="cx">)[^<]*(</div>)',
                                lambda mm: mm.group(1) + cx2 + mm.group(2), doc1, "cmt_week")
            else:
                doc1 = _ov_sub_required(r'(<div class="cl">今週</div><div class="cx">)[^<]*(</div>)',
                                lambda mm: mm.group(1) + "データ準備中。" + mm.group(2), doc1, "cmt_week")
        except Exception:
            pass

        # ---- レジーム欄（日次NQ色系列 regime_days があれば分布/連続/日次バーを実データ化） ----
        try:
            rh = mkt.get("reg_hist") or {}
            rs_state = mkt.get("regime_state") or {}
            rd = mkt.get("regime_days") or {}
            streak = rd.get("streak") if (isinstance(rd, dict) and rd.get("streak") is not None) else (rs_state.get("streak") if isinstance(rs_state, dict) else None)
            regnm = (sar[0] if isinstance(sar, (list, tuple)) and sar else None)
            g60 = rd.get("g60") if rd.get("g60") is not None else rs_state.get("g60")
            y60 = rd.get("y60") if rd.get("y60") is not None else rs_state.get("y60")
            r60 = rd.get("r60") if rd.get("r60") is not None else rs_state.get("r60")
            days = rd.get("days") if isinstance(rd, dict) else None
            if days:
                _cmap = {"g": "d-g", "y": "d-y", "r": "d-r"}
                bars = "".join('<i class="%s"></i>' % _cmap.get(c, "d-n") for c in days[-40:])
                doc1 = _re2.sub(r'<div class="days">.*?</div>', '<div class="days">%s</div>' % bars, doc1, count=1, flags=_re2.S)
            # 正確色streakと強気側streak・履歴末尾色を使い、現在色と食い違う時も誤表示しない
            _lhc = rd.get("last_history_color") if isinstance(rd, dict) else None
            _se = rd.get("streak_exact") if isinstance(rd, dict) else None
            _ss = rd.get("streak_side") if isinstance(rd, dict) else None
            if _se is None: _se = streak
            def _side_of(c):
                return "g" if c in ("Blue", "青", "Green", "緑") else ("y" if c in ("Yellow", "黄") else "r")
            def _streak_lbl():
                if not regnm:
                    return None
                # 正確色が一致 → 正確色の連続日数
                if _lhc and regnm == _lhc and isinstance(_se, int):
                    return f"{_se}日連続{regnm}"
                # Blue↔Greenの入れ替わりのみ（両方が強気g側）→ 強気側継続として表示
                if _lhc and _side_of(regnm) == "g" and _side_of(_lhc) == "g" and isinstance(_ss, int):
                    return f"現在{regnm} ・ 強気(青+緑){_ss}日継続"
                # 色の「側」まで食い違う（Red×Yellow, Blue×Red等）→ 現在色と履歴末尾色を両方明示
                # （_se/_ssは履歴末尾色の連続であって現在色の連続ではないため、現在色には付けない）
                if _lhc and isinstance(_se, int):
                    return f"現在{regnm} ・ 履歴末尾{_lhc} {_se}日"
                return f"現在{regnm}"
            _slbl = _streak_lbl()
            if _slbl:
                doc1 = _re2.sub(r'<div class="dr">[^<]*</div>',
                                f'<div class="dr">{_slbl}</div>', doc1, count=1)
            else:
                doc1 = _re2.sub(r'<div class="dr">[^<]*</div>', '<div class="dr">—</div>', doc1, count=1)
            if regnm and all(isinstance(v, int) for v in (g60, y60, r60)):
                act = (f'過去60日: <b class="pos">強気(青+緑) {g60}</b> / '
                       f'<b class="warnc">Yellow {y60}</b> / <b class="neg">Red {r60}</b>')
                if _slbl:
                    act = f'{_slbl} ・ ' + act
                doc1 = _re2.sub(r'<div class="action">.*?</div>',
                                f'<div class="action">{act}</div>', doc1, count=1, flags=_re2.S)
            else:
                doc1 = _re2.sub(r'<div class="action">.*?</div>',
                                '<div class="action">データ準備中（履歴の蓄積待ち）</div>', doc1, count=1, flags=_re2.S)
        except Exception:
            pass

        # ---- RSマルチTF 継続性（各期間top10の重なり・実データ・21/63/189。数字＝表示銘柄数） ----
        try:
            if m is not None and hasattr(m, "sort_values"):
                _N = 10
                _poolm = m[m["rs_pool"].fillna(False)] if ("rs_pool" in m.columns) else m
                def _tset(col):
                    return set(_poolm.sort_values(col, ascending=False).head(_N).index) if col in _poolm.columns else set()
                s21, s63, s189 = _tset("rs21"), _tset("rs63"), _tset("rs189")
                _rankidx = list(_poolm.sort_values("rs189", ascending=False).index) if "rs189" in _poolm.columns else list(_poolm.index)
                def _box(inter):
                    ordered = [t for t in _rankidx if t in inter]
                    names = [str(m.loc[t].get("ticker", t)) for t in ordered]
                    chips = "".join('<span class="chip">%s</span>' % t for t in names)
                    return chips, len(names)  # 件数＝表示チップ数（一致させる）
                def _repl(old_label, new_label, inter):
                    chips, cnt = _box(inter)
                    box = ('<div class="rsbox"><div class="rh"><span class="rl">%s</span>'
                           '<span class="rn num">%d</span></div><div class="chips">%s</div></div>'
                           % (new_label, cnt, chips))
                    return _re2.sub(
                        r'<div class="rsbox"><div class="rh"><span class="rl">' + _re2.escape(old_label) + r'</span>.*?</div></div>',
                        box, doc1, count=1, flags=_re2.S)
                doc1 = _repl("全期間Top10", "全期間 Top10", s21 & s63 & s189)
                doc1 = _repl("63×126", "21×63", s21 & s63)
                doc1 = _repl("126×189", "21×189", s21 & s189)
                doc1 = _repl("63×189", "63×189", s63 & s189)
        except Exception:
            pass
    except Exception:
        pass
    doc2 = tpl2
    try:
        sc = _re2.search(r'<script>(.*?)</script>', doc2, _re2.S).group(1)
        sc0 = sc
        # MAJ（大分類 11）: 各期間の実リターンからセクター横断の相対順位(0-100)を算出。
        #   従来は base(=RS189)がmacroに存在せず全セクター50固定→順位フローがtrendのみで駆動される不具合。
        #   ret189/ret126/ret63/m1(21日) をパーセンタイル化して rs21/63/126/189 に直接渡す。
        try:
            macro = ((mkt.get("sector_ranks") or {}).get("macro")) or []
            en_map = globals().get("_OV_MAJOR_EN", {})
            macro11 = macro[:11]
            if macro11:
                def _pctrank(key):
                    pairs = [(i, x.get(key)) for i, x in enumerate(macro11)]
                    out = {i: 50 for i, _ in pairs}
                    valid = [(i, float(v)) for i, v in pairs if v is not None and v == v]
                    if len(valid) >= 2:
                        valid.sort(key=lambda t: t[1])
                        n = len(valid)
                        for rank, (i, _) in enumerate(valid):
                            out[i] = int(round(100 * rank / (n - 1)))
                    return out
                r21r, r63r, r126r, r189r = (_pctrank(k) for k in ("m1", "ret63", "ret126", "ret189"))
                rows = []
                for i, x in enumerate(macro11):
                    nm = x.get("ja") or x.get("name") or "—"
                    rows.append([nm, en_map.get(nm, ""), r21r[i], r63r[i], r126r[i], r189r[i]])
                if rows:
                    inner = ",".join("['%s','%s',%d,%d,%d,%d]" % (r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows)
                    lit = ("[" + inner + "]\n    .map(function(r){return {name:r[0],en:r[1],col:PC[r[0]],"
                           "rs:{r21:clamp(r[2]),r63:clamp(r[3]),r126:clamp(r[4]),r189:clamp(r[5])}};})")
                    sc = _ov_replace_def(sc, "MAJ", lit)
        except Exception:
            pass
        # SUB（小分類）: [name, en, parent, base(RS189), trend]
        try:
            en_map = globals().get("_OV_MICRO_EN", {})
            if sectors:
                ss = sorted(sectors, key=lambda s: -(s.get("score") or s.get("med") or 0))[:30]
                rows = []
                for s in ss:
                    nm = s.get("ja") or "—"
                    en = en_map.get(nm, "")
                    parent = s.get("parent") or "テクノロジー"
                    try:
                        base = int(round(float(s.get("med189") or s.get("score") or s.get("med") or 50)))
                    except Exception:
                        base = 50
                    try:
                        tr = round(float(s.get("d_w1") or 0), 1)
                    except Exception:
                        tr = 0.0
                    rows.append([nm, en, parent, base, tr])
                if rows:
                    lit = ("[" + ",".join("['%s','%s','%s',%d,%s]" % (r[0], r[1], r[2], r[3], r[4]) for r in rows) + "]"
                           ".map(function(r){return {name:r[0],en:r[1],parent:r[2],col:PC[r[2]],"
                           "rs:{r21:clamp(r[3]+r[4]*5),r63:clamp(r[3]+r[4]*3),"
                           "r126:clamp(r[3]+r[4]*1.5),r189:clamp(r[3])}};})")
                    sc = _ov_replace_def(sc, "SUB", lit)
        except Exception:
            pass
        # LEADERS（期間別先導株 RS上位5）: 各RS期間の上位5銘柄
        try:
            if m is not None and hasattr(m, "sort_values"):
                _poolm2 = m[m["rs_pool"].fillna(False)] if ("rs_pool" in m.columns) else m
                periods = [("RS21", "短期", "rs21"), ("RS63", "中短", "rs63"),
                           ("RS126", "中長", "rs126"), ("RS189", "長期", "rs189")]
                out_rows = []
                ok = True
                for lab, sub, col in periods:
                    if col not in _poolm2.columns:
                        ok = False; break
                    top = _poolm2.sort_values(col, ascending=False).head(5)
                    tks = [str(top.loc[i].get("ticker", i)) for i in top.index]
                    tks = (tks + ["—"] * 5)[:5]
                    out_rows.append((lab, sub, tks))
                if ok and out_rows:
                    lit = "[" + ",".join(
                        "['%s','%s',[%s]]" % (r[0], r[1], ",".join("'%s'" % t for t in r[2]))
                        for r in out_rows) + "]"
                    sc = _ov_replace_def(sc, "LEADERS", lit)
        except Exception:
            pass
        # fnote 説明文・副題を大分類フローの実データで生成（事実ベース）
        try:
            macro2 = ((mkt.get("sector_ranks") or {}).get("macro")) or []
            def _w(x):
                return x.get("w1") if isinstance(x, dict) else None
            sflow = [s for s in macro2 if isinstance(_w(s), (int, float))]
            if sflow:
                ins = sorted(sflow, key=lambda s: -_w(s))
                outs = sorted(sflow, key=lambda s: _w(s))
                in_nm = "・".join((s.get("ja") or "—") for s in ins[:3])
                out_nm = "・".join((s.get("ja") or "—") for s in outs[:2])
                # fnote（JS内静的説明文の差し替え。流入N/流出Nの計算部は保持）
                fn_txt = f"{in_nm}が短期RSで上抜き＝資金流入。{out_nm}は流出。"
                sc = _re2.sub(
                    r"(getElementById\('fnote'\)\.innerHTML='流入 <b>'\+inN\+'</b> / 流出 <b>'\+outN\+'</b> 大分類。).*?(';)",
                    lambda mm: mm.group(1) + fn_txt + mm.group(2), sc, count=1, flags=_re2.S)
        except Exception:
            pass
        if sc != sc0:
            doc2 = doc2.replace(sc0, sc)
        # 副題（read）を実データで生成
        try:
            macro3 = ((mkt.get("sector_ranks") or {}).get("macro")) or []
            def _w3(x):
                return x.get("w1") if isinstance(x, dict) else None
            sflow3 = [s for s in macro3 if isinstance(_w3(s), (int, float))]
            if sflow3:
                ins3 = sorted(sflow3, key=lambda s: -_w3(s))
                outs3 = sorted(sflow3, key=lambda s: _w3(s))
                in3 = "・".join((s.get("ja") or "—") for s in ins3[:3])
                out3 = "・".join((s.get("ja") or "—") for s in outs3[:2])
                read = (f'<div class="read">短期RSで<b>{in3}</b>が上位に浮上、'
                        f'<span class="dn">{out3}</span>は長期RSに対し短期が沈み後退。</div>')
                doc2 = _re2.sub(r'<div class="read">.*?</div>', read, doc2, count=1, flags=_re2.S)
        except Exception:
            pass
        # ヘッダ日付
        if asof:
            doc2 = _ov_sub_required(r'<span class="date num">[^<]*</span>',
                            f'<span class="date num">{asof}</span>', doc2, "date_d2")
    except Exception:
        pass

    # 部分的な置換失敗でテンプレのサンプル数値が残らないよう最終検査（残っていれば「—」化）。
    # ※ティッカーは実際に選ばれ得るのでサニティネルにしない。日付・出来高・見出し数値など固有値のみ。
    # サンプル残留の"参考"検出。ただし表示値(VIX/PC/売買代金/日付/レジーム等)は実データと衝突し得るため
    # これ自体では selftest を失敗させない（誤検出防止）。致命的な注入失敗検知は _ov_sub_required/_ov_replace_def
    # の件数カウンタ(_OV_INJECT_MISSES)に一本化した。ここは診断ログのみ。
    _SAMPLE_SENTINELS = ["2026-07-15", "$12.4B", "$28.6B", "P/C 0.92", "VIX 15.7",
                         "14日連続Yellow", "24 / 18 / 31", "Top10継続8/10"]
    _sample_hits = [mk for mk in _SAMPLE_SENTINELS if (mk in doc1 or mk in doc2)]
    if _sample_hits:
        sys.stderr.write("[overview] sample-like string present (advisory only; not failing selftest): %r\n" % _sample_hits)

    if _OV_INJECT_MISSES:
        # テンプレ変更等で var 配列/スカラーの注入が不一致だった場合に検知（サンプル残存の主因）。
        sys.stderr.write("[overview] structured injection missed: %r\n" % sorted(set(_OV_INJECT_MISSES)))

    return doc1, doc2


# --- 投稿カードのタブ埋め込み（srcdoc iframe・全画面スクショ・閉じるボタン自動フェード） ---
POST_CSS = (".postwrap{position:relative;margin:4px 0}"
    ".pfsbtn{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:700;color:#3d4137;background:#DDDAD0;border:1px solid rgba(0,0,0,.14);border-radius:9px;padding:8px 15px;cursor:pointer;margin-bottom:8px}"
    ".pfsbtn:active{opacity:.7}"
    ".postframe{width:100%;aspect-ratio:1680/1080;border:1px solid #D5D1C6;border-radius:12px;display:block;background:#E9E7DF}"
    ".pfsclose{display:none}"
    ".postnote{font-size:11px;color:#84887c;margin-top:6px}"
    ".postwrap.fs{position:fixed;inset:0;z-index:99999;background:#E9E7DF;display:flex;align-items:center;justify-content:center;margin:0}"
    # カードは静的表示のみのため透明レイヤでタップを親に届ける（iframeが飲むと閉じるボタンを再表示できない）
    ".postwrap.fs::after{content:'';position:absolute;inset:0;z-index:1}"
    ".postwrap.fs .postframe{width:100vw;height:100vh;max-width:none;aspect-ratio:auto;border-radius:0;border:0}"
    ".postwrap.fs .pfsbtn,.postwrap.fs .postnote{display:none}"
    ".postwrap.fs .pfsclose{display:flex;align-items:center;justify-content:center;position:fixed;top:calc(env(safe-area-inset-top,0px) + 10px);right:10px;z-index:100000;width:34px;height:34px;font-size:16px;font-weight:700;color:#fff;background:rgba(0,0,0,.45);border:1px solid rgba(255,255,255,.3);border-radius:50%;cursor:pointer;padding:0;line-height:1;opacity:1;transition:opacity .5s}"
    ".postwrap.fs.hideui .pfsclose{opacity:0;pointer-events:none}"
    "body.fslock{overflow:hidden}")
POST_JS = ("var _pfsT=null;"
    "function pfs(b,o){var w=b.closest('.postwrap');w.classList.toggle('fs',!!o);document.body.classList.toggle('fslock',!!o);"
    "if(o){_pfsShow(w);}else{w.classList.remove('hideui');clearTimeout(_pfsT);}}"
    "function _pfsShow(w){w.classList.remove('hideui');clearTimeout(_pfsT);_pfsT=setTimeout(function(){w.classList.add('hideui');},2800);}"
    "document.addEventListener('click',function(e){var t=e.target;if(t.closest&&t.closest('.pfsclose'))return;"
    "var w=t.closest?t.closest('.postwrap.fs'):null;if(w)_pfsShow(w);});")

# --- ティッカー・タップでTradingViewチャートをポップアップ（Advanced・遅延ロード・ページ遷移なし） ---
TV_POPUP_CSS = (
    ".tvovl{position:fixed;inset:0;z-index:99998;background:rgba(24,22,18,.55);display:none;"
    "align-items:center;justify-content:center;padding:14px;opacity:0;transition:opacity .18s;-webkit-backdrop-filter:blur(2px);backdrop-filter:blur(2px)}"
    ".tvovl.on{display:flex;opacity:1}"
    ".tvpop{width:100%;max-width:920px;height:84vh;max-height:660px;background:#F4F2EC;border:1px solid #D5D1C6;"
    "border-radius:16px;overflow:hidden;position:relative;display:flex;flex-direction:column;transform:translateY(8px);"
    "transition:transform .18s;box-shadow:0 24px 60px rgba(0,0,0,.35)}"
    ".tvovl.on .tvpop{transform:translateY(0)}"
    ".tvhd{display:flex;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid #D5D1C6}"
    ".tvhd .sym{font-size:16px;font-weight:800;letter-spacing:.02em;color:#1B1D1C}"
    ".tvhd .sp{flex:1}"
    ".tvhd a{font-size:12px;font-weight:700;color:#2456A6;text-decoration:none;opacity:.85}"
    ".tvhd button{width:32px;height:32px;border:0;border-radius:50%;background:rgba(0,0,0,.06);color:#3d4137;"
    "font-size:16px;font-weight:700;cursor:pointer;line-height:1;padding:0}"
    ".tvhd button:active{opacity:.6}"
    ".tvbody{flex:1;position:relative;background:#fff}"
    ".tvbody .tradingview-widget-container,.tvbody .tradingview-widget-container>div,.tvbody iframe{height:100%!important;width:100%!important}"
    ".tvload{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#84887c;font-size:12px}"
    ".tk{cursor:pointer}.tk:active{opacity:.55}")

TV_POPUP_JS = (
    "(function(){"
    "var s=document.createElement('script');s.src='https://s3.tradingview.com/tv.js';s.async=true;document.head.appendChild(s);"
    "var ovl=document.createElement('div');ovl.className='tvovl';ovl.id='tvovl';"
    "ovl.innerHTML='<div class=\\'tvpop\\'><div class=\\'tvhd\\'><span class=\\'sym\\' id=\\'tvSym\\'></span>"
    "<span class=\\'sp\\'></span><a id=\\'tvFull\\' target=\\'_blank\\' rel=\\'noopener\\'>TVで開く \\u2197</a>"
    "<button onclick=\\'tvClose()\\'>\\u2715</button></div><div class=\\'tvbody\\' id=\\'tvBody\\'></div></div>';"
    "if(document.body){document.body.appendChild(ovl);}else{document.addEventListener('DOMContentLoaded',function(){document.body.appendChild(ovl);});}"
    "var _w=null;"
    "window.tvOpen=function(tk){tk=(tk||'').toUpperCase().replace(/[^A-Z.]/g,'');if(!tk)return;"
    "document.getElementById('tvSym').textContent=tk;"
    "document.getElementById('tvFull').href='https://jp.tradingview.com/chart/?symbol='+encodeURIComponent(tk);"
    "var body=document.getElementById('tvBody');body.innerHTML='<div class=\\'tvload\\'>\\u30c1\\u30e3\\u30fc\\u30c8\\u8aad\\u8fbc\\u4e2d\\u2026</div><div id=\\'tvHost\\'></div>';"
    "ovl.classList.add('on');document.body.style.overflow='hidden';"
    "try{_w=new TradingView.widget({container_id:'tvHost',symbol:tk,interval:'D',theme:'light',style:'1',locale:'ja',"
    "autosize:true,allow_symbol_change:false,studies:['MASimple@tv-basicstudies'],timezone:'America/New_York',withdateranges:true});"
    "setTimeout(function(){var l=body.querySelector('.tvload');if(l)l.style.display='none';},1500);}catch(e){}};"
    "window.tvClose=function(){ovl.classList.remove('on');document.body.style.overflow='';"
    "setTimeout(function(){var b=document.getElementById('tvBody');if(b)b.innerHTML='';_w=null;},200);};"
    "ovl.addEventListener('click',function(e){if(e.target===ovl)tvClose();});"
    "document.addEventListener('keydown',function(e){if(e.key==='Escape')tvClose();});"
    "document.addEventListener('click',function(e){var el=e.target.closest?e.target.closest('.tk'):null;if(!el)return;"
    "var host=el.closest('[data-tkone],[data-tk]');"
    "var tk=host?(host.getAttribute('data-tkone')||host.getAttribute('data-tk')):(el.getAttribute('data-tk')||'');"
    "if(!tk){var mm=(el.textContent||'').match(/^[\\s#0-9]*([A-Z][A-Z.]{0,5})(?![a-z])/);tk=mm?mm[1]:'';}"
    "tk=(tk||'').toUpperCase().replace(/[^A-Z.]/g,'');if(!tk)return;"
    "e.preventDefault();e.stopPropagation();tvOpen(tk);},true);"
    "})();")

def _post_iframe(doc):
    if not doc:
        return ('<div class="card"><h2>投稿カード</h2>'
                '<div class="sub">データ不足のため今回は生成できませんでした（次回ビルドで自動再生成）。</div></div>')
    esc = _html.escape(doc, quote=True)
    return ('<div class="postwrap"><button class="pfsbtn" onclick="pfs(this,1)">⛶ 全画面表示</button>'
            f'<iframe class="postframe" srcdoc="{esc}"></iframe>'
            '<button class="pfsclose" onclick="pfs(this,0)">✕</button></div>')

# ----------------------------------------------------------------------------- X投稿用シェアカード (1200x675)
def build_share_html(aux, sar, mkt, picks, senti, asof_disp):
    color = sar[0]
    hexes = {"Blue": "#1d4ed8", "Green": "#16a34a", "Yellow": "#ca8a04", "Red": "#dc2626"}
    glow = hexes.get(color, "#4b5563")
    cj = _COLOR_JP.get(color, "—")
    band_lab, _ = mri_band(aux["hl"])
    dd = mkt.get("distrib", {})
    ddtxt = " ・ ".join(f"{_h(k)} {v['n']}日" for k, v in dd.items()) or "—"
    ranks = [x for x in ((mkt.get("sector_ranks") or {}).get("micro") or []) if x.get("w1") == x.get("w1")]
    top3 = "、".join(_h(s["ja"]) for s in sorted(ranks, key=lambda x: -x["w1"])[:3]) or "—"
    chips = "".join(f'<span class="pk">{_h(t)}</span>' for t, _, _ in picks)
    seg = [hc for hc in (mkt.get("trend_hist") or []) if hc and len(hc) == 2][-60:]
    rib = "".join(f'<i style="background:{hexes.get(c, "#4b5563")}"></i>' for _, c in seg)
    sn = f'{senti["cur"]:.0f}（{senti["band"]}）' if senti else "—"
    return f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>V38 share</title><style>
body{{margin:0;background:#0b0f17;font-family:'Hiragino Sans','Noto Sans JP',sans-serif}}
.fr{{width:1200px;height:675px;box-sizing:border-box;padding:44px 56px;display:flex;flex-direction:column;
background:radial-gradient(1200px 500px at 80% -10%,{glow}33,transparent),#0b0f17;color:#e6edf3}}
.top{{display:flex;align-items:center;gap:22px}}
.gate{{font-size:56px;font-weight:900;color:#fff;background:{glow};border-radius:18px;padding:10px 34px;box-shadow:0 0 44px {glow}88}}
.ttl{{font-size:30px;font-weight:800;color:#9ecbff}} .asof{{margin-left:auto;font-size:20px;color:#7d8da1}}
.mid{{display:flex;gap:40px;align-items:center;margin:34px 0 8px}}
.mri{{font-size:120px;font-weight:900;line-height:1}} .mrs{{font-size:26px;color:#9fb0c5}}
.kv{{font-size:24px;color:#cbd5e1;line-height:1.9}} .kv b{{color:#fff}}
.rgrid{{display:flex;flex-direction:column;gap:8px;margin-top:6px}}
.rcard{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:9px 11px}}
.rcat{{font-size:10px;color:#64748b;letter-spacing:.04em}}
.rlab{{font-size:12px;color:#94a3b8;margin-top:1px}}
.rval{{font-size:19px;color:#e6edf3;font-weight:700;margin-top:2px}}
.rmeta{{font-size:10.5px;margin-top:2px}}
.rrow{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 10px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:9px 12px}}
.rrow .lft{{min-width:0}}
.rrow .foot,.rrow .hint{{grid-column:1 / -1}}
.rrow .nm{{font-size:13px;color:#cbd5e1;font-weight:600;line-height:1.25}}
.rrow .cat{{font-size:10px;color:#64748b;letter-spacing:.03em}}
.rrow .rgt{{text-align:right;white-space:nowrap}}
.rrow .big{{font-size:19px;font-weight:700;color:#e6edf3}}
.rrow .chg{{font-size:11px;margin-left:5px}}
.rrow .hint{{display:block;font-size:10.5px;color:#8b9bb0;margin-top:2px;letter-spacing:.02em}}
.rrow .foot{{flex-basis:100%;font-size:10px;color:#5f6b7e;margin-top:3px;border-top:1px solid rgba(255,255,255,.05);padding-top:3px}}
.rrow .na{{font-size:13px;color:#5f6b7e}}
.rwarn{{color:#f59e0b;font-size:11px;font-weight:700}}
.rib{{display:flex;gap:2px;margin:22px 0 14px}} .rib i{{flex:1;height:22px;border-radius:3px}}
.pks{{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}}
.pk{{font-size:21px;font-weight:800;color:#9ecbff;background:#16243e;border-radius:9px;padding:5px 14px}}
.ft{{margin-top:auto;font-size:17px;color:#5b6b80}}</style></head><body><div class="fr">
<div class="top"><span class="gate">{cj}</span><span class="ttl">V38 Command Center</span><span class="asof">{asof_disp}</span></div>
<div class="mid"><div><div class="mri">{aux['cur']:.0f}</div><div class="mrs">地合いスコア ・ {band_lab}</div></div>
<div class="kv">傾き <b>{aux['slope']}</b> ／ 警戒 <b>{aux['bear_n']}/4</b><br>売り抜け日 <b>{ddtxt}</b><br>群衆温度計 <b>{sn}</b><br>非常口 <b>{'発動・レバ半減' if (mkt.get('emergency') or {}).get('active') else '待機'}</b><br>主導 <b>{top3}</b></div></div>
<div class="rib">{rib}</div>
<div class="pks">{chips}</div>
<div class="ft">レジーム履歴（直近{len(seg)}記録）・個人の研究用であり投資助言ではありません</div>
</div></body></html>"""

# ----------------------------------------------------------------------------- setups (D, all chips)
def build_setups(m):
    up200 = m["close"] > m["sma200"]
    up50  = m["close"] > m["sma50"]
    def names(mask, sort="rs"):
        sub = m[mask.fillna(False)].sort_values(sort, ascending=False)
        return list(sub.index)
    setups = {}
    setups["押し目"] = names(up200 & up50 & (m["rs"] >= 88) &
                           ((m["close"] / m["ema21"] - 1).abs() <= 0.025))
    setups["ブレイク近"] = names((m["stage2"] == True) & (m["rs189"] >= 85)
                              & (m["pivot_dist"] >= -0.03) & (m["pivot_dist"] <= 0.005), "vcp_score")
    setups["出来高急増"] = names(up50 & (m["pchg"] > 0) & (m["volx"] >= 2.5) & (m["rs"] >= 85))
    setups["モメンタム"] = names(up50 & (m["rs"] >= 92) & (m["ret21"] >= 0.15))
    setups["ボラ収縮"] = names((m["vcp_ready"] == True) & (m["rs189"] >= 80), "vcp_score")
    setups["深押し"] = names(up200 & (m["dist52"] <= -0.15) & (m["rs"] >= 75))
    return setups


# LEGACY: 未使用（現在のSetupsからは呼ばれない。旧ロジック。編集しても画面に反映されない点に注意）
def build_structure_scanner(m, cap=10):
    """Compact structural scanner: confirmed breakout, VCP, cup/handle, trend change and 20/4."""
    liq = (m["close"] >= 5) & (m["dvol"] >= DVOL_FLOOR)
    leader = (m["rs189"] >= 80)
    specs = [
        ("真のブレイク", m[(m["true_breakout"] == True) & liq & leader], "breakout_score"),
        ("VCP準備", m[(m["vcp_ready"] == True) & (m["true_breakout"] != True) & liq & leader], "vcp_score"),
        ("カップ・ハンドル", m[((m["cup_ready"] == True) | (m["cup_breakout"] == True)) & liq & leader], "rs189"),
        ("転換確認", m[(m["trend_change"] == True) & (m["true_breakout"] != True)
                         & (m["cup_breakout"] != True) & liq & (m["rs189"] >= 70)], "rs189"),
        ("20/4進行", m[(m["power20_4"] == True) & liq & leader], "brk_ret"),
        ("ブレイク失敗", m[(m["breakout_failure"] == True) & liq], "brk_ret"),
    ]
    blocks = []
    for name, sub, sortcol in specs:
        if sub.empty:
            chips = '<span class="empty">該当なし</span>'
            n = 0
        else:
            sub = sub.sort_values(sortcol, ascending=False).head(cap)
            n = len(sub)
            cc = []
            for t, r in sub.iterrows():
                if name == "真のブレイク":
                    meta = f'RVOL {float(r.get("rvol_pre")):.1f}×' if pd.notna(r.get("rvol_pre")) else ''
                elif name == "VCP準備":
                    meta = f'質 {int(round(float(r.get("vcp_score", 0))))}'
                elif name == "カップ・ハンドル":
                    meta = f'深さ {float(r.get("cup_depth"))*100:.0f}%' if pd.notna(r.get("cup_depth")) else ''
                elif name == "転換確認":
                    meta = f'RS {float(r.get("rs189")):.0f}' if pd.notna(r.get("rs189")) else ''
                elif name == "20/4進行":
                    meta = f'+{float(r.get("brk_ret"))*100:.0f}%/{int(r.get("brk_days"))}日' if pd.notna(r.get("brk_ret")) and pd.notna(r.get("brk_days")) else ''
                else:
                    meta = f'{float(r.get("brk_ret"))*100:.1f}%/{int(r.get("brk_days"))}日' if pd.notna(r.get("brk_ret")) and pd.notna(r.get("brk_days")) else ''
                _pv = float(r.get("pivot40")) if pd.notna(r.get("pivot40")) else float("nan")
                _pd = float(r.get("pivot_dist")) if pd.notna(r.get("pivot_dist")) else float("nan")
                title = (f'ピボット {_pv:.2f} / 距離 {_pd*100:+.1f}% / '
                         f'収縮 {int(r.get("contractions") or 0)} / 安値切上げ {"○" if bool(r.get("higher_lows")) else "—"}')
                cc.append(f'<span class="chip hot" title="{title}" data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}"><b>{t}</b><span class="mut" style="font-size:10px">{meta}</span></span>')
            chips = ''.join(cc)
        blocks.append(f'<div class="patblk"><div class="patname">{name}<span class="ct">{n}</span></div><div class="chips">{chips}</div></div>')
    return ('<div class="card"><h2>構造スキャナー</h2>'
            '<div class="sub">トレンド・収縮・ピボット・出来高を分けて判定</div>'
            + ''.join(blocks) + '</div>')

def _tkcopy(t):
    """ティッカー横のコピーボタン（リスト用コピーと同じピル型・タップで詳細モーダルは維持）。"""
    return f'<button class="cp cp-one" onclick="copyOne(event,\'{t}\')" title="{t}をコピー">コピー</button>'

def pullback_quality(r):
    """押し目質スコア（検証準拠・裁量執行の質の目安・売買非連動）。
       検証(確定チェーン出口・16k機会)で各要素の実測R差に応じた加点式。
       思想: 長期上昇(21EMA上向き・10日安値切上げ)だが直近は深く押した所が最良＝教科書ブレイクの逆。"""
    pts = 0; lit = []
    d52 = r.get("dist52"); rs21 = r.get("rs21"); rs126 = r.get("rs126"); rs63 = r.get("rs63")
    ret5 = r.get("ret5"); close = r.get("close"); ema = r.get("ema21"); ema10 = r.get("ema21_10ago")
    lo10 = r.get("lo10"); lo10p = r.get("lo10_prev")
    # 加点（効く順・実測R差ベース）
    if d52 == d52 and d52 is not None and d52 <= -0.25:
        pts += 25; lit.append(("深押し", "52週高値-25%超下＝実測+1.20R", "pq-hi"))
    if (rs21 == rs21 and rs21 is not None and rs21 >= 85) or (rs126 == rs126 and rs126 is not None and rs126 >= 85):
        pts += 20; lit.append(("突出RS", "21日 or 126日RS≥85＝+0.57〜0.59R", "pq-hi"))
    if all(x == x and x is not None for x in (close, ema, ema10)) and ema10 > 0 and (ema/ema10 - 1) > 0.02:
        pts += 18; lit.append(("EMA上向き", "21EMA 10日+2%超＝トレンド生存+0.48R", "pq-mid"))
    if ret5 == ret5 and ret5 is not None and ret5 < 0:
        pts += 15; lit.append(("押し目中", "直近5日マイナス＝+0.39R（追わない）", "pq-mid"))
    if all(x == x and x is not None for x in (lo10, lo10p)) and lo10 > lo10p:
        pts += 12; lit.append(("10日安値切上げ", "安値切上げ＝+0.31R", "pq-mid"))
    if rs63 == rs63 and rs63 is not None and rs63 >= 85:
        pts += 10; lit.append(("63日RS強", "≥85＝+0.25R", "pq-lo"))
    # 減点（追う形・出遅れ）
    if d52 == d52 and d52 is not None and d52 >= -0.10:
        pts -= 15; lit.append(("高値圏", "52週高値-10%以内＝追う形-0.32R", "pq-neg"))
    if ret5 == ret5 and ret5 is not None and ret5 > 0.05:
        pts -= 15; lit.append(("直近急伸", "5日+5%超＝出遅れ-0.38R", "pq-neg"))
    return pts, lit

def _pp_badge(r):
    """ポケットピボット(10D)。当日=PP、直近10日内=PP Nd前。"""
    d = r.get("pp_days")
    if d is None or d != d:
        return ""
    try:
        d = int(d)
    except Exception:
        return ""
    rt = r.get("pp_ratio")
    rtxt = f"（下げ日最大出来高の{rt:.1f}倍）" if rt == rt else ""
    lab = "PP" if d == 0 else f"PP {d}日前"
    cls = "ppb ppb-now" if d == 0 else "ppb"
    return (f'<span class="{cls}" title="ポケットピボット(10D){rtxt}: 上げ日かつ出来高が直近10営業日の'
            f'「下げ日の最大出来高」を上回る（10日線・50日線の上のみ）。Kacher/Morales。'
            f'">{lab}</span>')


# 兆候8種。実測(2017-2026・適格プール内・前向き60日で+10%超=テール捕捉):
#   ≥3: 1.04x(効果なし) / ≥4: 1.22x(前半1.23・後半1.21) / ≥5: 1.34x / ≥6: 1.39x
#   → 閾値は4。3では基準(30%)と変わらない。
CONFLUENCE_MIN = 4
_SIG_DEF = [
    ("RS", "リーダー（189日RS≥85）"),
    ("高値圏", "52週高値−15%以内"),
    ("21EMA", "21EMAの上"),
    ("PP", "本日ポケットピボット(10D)"),
    ("出来高", "20日平均の1.3倍以上"),
    ("新規", f"{NEW_ENTRY_OUT_RANK}位圏外→{NEW_ENTRY_IN_RANK}位以内へ参入"),
    ("ADR", "ADR 3.5〜8%"),
    ("圧縮", "BB幅が126日で下位25%"),
]


def _signals_of(r, new_entry=None):
    out = []
    def ok(v):
        return v is not None and v == v
    rs = r.get("rs189")
    if ok(rs) and rs >= LEADER_RS: out.append("RS")
    d52 = r.get("dist52")
    if ok(d52) and d52 >= -0.15: out.append("高値圏")
    cl, e21 = r.get("close"), r.get("ema21")
    if ok(cl) and ok(e21) and cl > e21: out.append("21EMA")
    pp = r.get("pp_days")
    if ok(pp) and int(pp) == 0: out.append("PP")
    rv = r.get("rvol_pre")
    if ok(rv) and rv >= 1.3: out.append("出来高")
    if isinstance(new_entry, str) and new_entry: out.append("新規")
    a = r.get("adr")
    if ok(a) and 0.035 <= a <= 0.080: out.append("ADR")
    bp = r.get("bbw_pct")
    if ok(bp) and bp <= 25: out.append("圧縮")
    return out


def setup_eligible(m):
    """Setups全カード共通の適格母集団：株価≥5・売買代金≥$10M・時価総額≥$1B・分割疑い除外・除外テーマ除外。
       RSや200MA等の個別条件はこれに & して各カードで足す（早期転換でRSを緩めるのは可・株価/流動性/時価総額/除外は共通）。
       列欠損・例外時はフェイルクローズ（全除外）——適格側に倒すより安全。"""
    try:
        _nan = pd.Series(np.nan, index=m.index)
        mask = pd.Series(True, index=m.index)
        mask &= m.get("close", _nan).ge(5)
        mask &= m.get("dvol", _nan).ge(DVOL_FLOOR)
        mask &= m.get("mcap", _nan).ge(1e9)
        mask &= ~m.get("split_suspect", pd.Series(True, index=m.index)).fillna(True)
        mask &= ~m.get("excluded_theme", pd.Series(True, index=m.index)).fillna(True)
        return mask.fillna(False)
    except Exception as _e:
        sys.stderr.write("[setup_eligible] eligibility failed: %r\n" % (_e,))
        return pd.Series(False, index=m.index)


def build_confluence_watch(m, cand=None, cap=20, min_rs=95):
    """コンフルエンス・ボード。兆候4つ以上で基準比1.22x(テール)。"""
    pool = m[setup_eligible(m) & (m["sma50"] > m["sma200"]) & (m["rs189"] >= min_rs)]
    if pool.empty:
        return ""
    ne = {}
    if cand is not None and "new_entry" in cand.columns:
        ne = {t: v for t, v in cand["new_entry"].items() if isinstance(v, str)}
    rows = []
    for t, r in pool.iterrows():
        sg = _signals_of(r, ne.get(t))
        if len(sg) >= CONFLUENCE_MIN:
            rows.append((len(sg), float(r.get("rs189") or 0), t, r, sg))
    legend = " ・ ".join(f'<b>{k}</b>＝{v}' for k, v in _SIG_DEF)
    det = (f'<details class="cfdet"><summary>兆候の定義</summary>'
           f'<div class="cflg">{legend}</div>'
           f'<div class="cflg" style="margin-top:5px">実測(2017-2026・前向き60日で+10%超): '
           f'3つ=1.04x（基準と同等）／<b>4つ=1.22x</b>（前半1.23・後半1.21）／5つ=1.34x。</div></details>')
    if not rows:
        return (f'<div class="card"><h2>コンフルエンス・ボード</h2>'
                f'<div class="sub">RS189≥{min_rs}で{CONFLUENCE_MIN}つ以上重なる銘柄は現在なし。{det}</div></div>')
    rows.sort(key=lambda x: (-x[0], -x[1]))
    total = len(rows)
    body = ""
    for n, rs, t, r, sg in rows[:cap]:
        pills = "".join(f'<span class="sgp">{x}</span>' for x in sg)
        cls = "cf-hi" if n >= 5 else ""
        body += (f'<div class="cfrow {cls}" data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}">'
                 f'<div class="cfl"><span class="cfn">{n}</span>'
                 f'<b class="cft">{t}</b><span class="mut" style="font-size:10.5px">RS189 {int(round(rs))}</span></div>'
                 f'<div class="cfs">{pills}</div></div>')
    more = f'<div class="mut" style="font-size:10.5px;margin-top:6px">上位{cap}件／{total}件中</div>' if total > cap else ""
    _cptk = [t for _n, _rs, t, _r, _sg in rows[:cap]]
    return (f'<div class="card"><div class="hdr"><h2>コンフルエンス・ボード</h2>{_cp(_cptk)}</div>'
            f'<div class="sub">RS189≥{min_rs}・兆候が<b>{CONFLUENCE_MIN}つ以上</b>重なる銘柄を多い順に。5つ以上は緑。{det}</div>'
            f'{body}{more}</div>')


def build_pocket_pivots(m, cap=10):
    """ポケットピボット(10D)ウォッチリスト。当日発生を優先し、出来高の増加率(下げ日最大比)上位。"""
    if "pp_days" not in m.columns:
        return ""
    # 流動性・株価の下限を適用（倍率は分母が小さいほど大きくなるため、薄商いを除く）
    # リーダーに限定（RS189≥85・200MA上）＋流動性/株価の下限。
    # 倍率は分母（下げ日の出来高）が小さいほど大きくなるため、薄商いを除かないと上位が汚れる。
    pp = m[setup_eligible(m) & m["pp_days"].notna() & (m["close"] > m["sma200"])
           & (m["rs189"] >= LEADER_RS)].copy()
    if pp.empty:
        return ""
    pp["pp_days"] = pp["pp_days"].astype(int)
    secs = ""
    for d_lo, d_hi, lab in ((0, 0, "本日"), (1, 3, "直近3日"), (4, 10, "4〜10日前")):
        sub = pp[(pp["pp_days"] >= d_lo) & (pp["pp_days"] <= d_hi)]
        if sub.empty:
            continue
        n = len(sub)
        sub = sub.sort_values("pp_ratio", ascending=False).head(cap)
        chips = ""
        for t, r in sub.iterrows():
            rt = r.get("pp_ratio")
            rs = r.get("rs189")
            dtxt = "" if r["pp_days"] == 0 else f'<span class="ppd">{int(r["pp_days"])}日前</span>'
            chips += (f'<span class="chip hot" data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}">'
                      f'<b>{t}</b>{dtxt}'
                      f'<span class="ppx">×{rt:.1f}</span>'
                      f'<span class="mut" style="font-size:10px">RS189 {int(round(float(rs)))if rs==rs else "—"}</span></span>')
        more = f'<span class="more">上位{cap}件／{n}件中</span>' if n > cap else ""
        secs += (f'<div class="setup-h"><span class="nm">{lab}</span>'
                 f'<span class="ct">{n}銘柄</span></div><div class="chips">{chips}{more}</div>')
    if not secs:
        return ""
    _pptk = [t for t in pp.index[:cap]] if hasattr(pp, "index") else []
    return (f'<div class="card"><div class="hdr"><h2>ポケットピボット（10D）</h2>{_cp(_pptk)}</div>'
            f'<div class="sub">上げ日かつ出来高が直近10営業日の「下げ日の最大出来高」を上回った銘柄'
            f'（10日線・50日線の上）。リーダー（RS189≥85）のみ。<b>×</b>＝その倍率で、高い順に上位{cap}件。</div>{secs}</div>')


def build_new_entrants(cand):
    """新規参入ボード: 3N=NEW_ENTRY_OUT_RANK位圏外 → NEW_ENTRY_IN_RANK位以内に飛び込んだ銘柄を期間別に。"""
    if cand is None or "new_entry" not in cand.columns:
        return ""
    rk = cand["rk189_now"] if "rk189_now" in cand.columns else cand["rs189"].rank(ascending=False)
    buckets = {"今日": [], "今週": [], "今月": []}
    for t, r in cand.iterrows():
        lab = r.get("new_entry")
        if isinstance(lab, str) and lab in buckets:
            buckets[lab].append((int(rk.get(t, 999)), t, r))
    if not any(buckets.values()):
        return ""
    secs = ""
    _sub = {"今日": f"前日は{NEW_ENTRY_OUT_RANK}位圏外 → 今日{NEW_ENTRY_IN_RANK}位以内", "今週": f"5日前は{NEW_ENTRY_OUT_RANK}位圏外 → 今{NEW_ENTRY_IN_RANK}位以内",
            "今月": f"20日前は{NEW_ENTRY_OUT_RANK}位圏外 → 今{NEW_ENTRY_IN_RANK}位以内"}
    for lab in ("今日", "今週", "今月"):
        rows = sorted(buckets[lab])
        if not rows:
            continue
        chips = "".join(
            f'<span class="chip hot" data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}">'
            f'<b>{rk_}</b>位 {t}{_pp_badge(r)}</span>' for rk_, t, r in rows)
        secs += (f'<div class="setup-h"><span class="nm">{lab}<span class="mut" style="font-weight:400;font-size:10.5px">'
                 f'・{_sub[lab]}</span></span><span class="ct">{len(rows)}銘柄</span></div>'
                 f'<div class="chips">{chips}</div>')
    return (f'<div class="card"><h2>新規参入（ポート候補{NEW_ENTRY_OUT_RANK}位圏）</h2>'
            f'<div class="sub">{NEW_ENTRY_OUT_RANK}位圏の外から{NEW_ENTRY_IN_RANK}位以内へ飛び込んだ銘柄。'
            f'</div>{secs}</div>')



def _rank_in_badge(t, hold, selected):
    """選定Core 12の銘柄に「いつからランキング入りか」を表示。holdのed(継承された初回日)を使う。"""
    if not selected or not hold:
        return ""
    h = hold.get(t) or {}
    ed = h.get("ed")
    if not ed:
        return ""
    try:
        n = _session_days(ed)                        # #8 壁時計でなく分析基準日までの実取引セッション数
        nn = f"{n}営業日" if n and n > 0 else ""
    except Exception:
        nn = ""
    return f'<span class="inb" title="Core 12に入り継続中の起点日">IN {ed}{("・"+nn) if nn else ""}</span>'

def _new_entry_badge(r):
    """3N=36位圏に新しく入ってきた銘柄（今週/今月）。ランキングの新陳代謝を見るための表示。"""
    lab = r.get("new_entry")
    if lab is None or lab != lab or not isinstance(lab, str) or not lab:
        return ""                      # NaN/None/非文字列は非表示
    return (f'<span class="newb" title="{lab}、36位圏の外から入ってきた銘柄。'
            f'">NEW {lab}</span>')

def _chase_alert(r):
    """高値追いアラート: 唯一生き残った入口注意(52wH−10%以内=−0.28R・両期間頑健)。"""
    d52 = r.get("dist52")
    if d52 == d52 and d52 is not None and d52 >= -0.10:
        return ('<span class="chaseb" title="52週高値−10%以内。検証: 追いかけは−0.28R（時期分割でも頑健・唯一生き残った入口注意）。'
                '指値は下で待つ（1-2日ズレてよい）">⚠ 高値圏・追わない</span>')
    return ""

def _ent_btn(t):
    """エントリー済みトグル（指値運用で執行が1-2日ズレるため手動マーク・localStorage保存）。"""
    return f'<button class="entb2" data-tk="{t}" onclick="entToggle(event,this)">未</button>'

def _pq_badge(r, compact=False):
    """押し目質バッジ。compact=Trueならスコアのみ（保有テーブル用）、Falseなら点灯要素も（詳細用）。"""
    pts, lit = pullback_quality(r)
    if not lit:
        return ""
    cls = "pq-a" if pts >= 55 else "pq-b" if pts >= 35 else "pq-c" if pts >= 15 else "pq-d"
    tip = " / ".join(f"{name}: {desc}" for name, desc, _ in lit)
    if compact:
        return f'<span class="pqb {cls}" title="{tip}">押し目質 {pts}</span>'
    tags = "".join(f'<span class="pqtag {c}">{name}</span>' for name, _, c in lit[:4])
    return (f'<span class="pqb {cls}" title="{tip}">押し目質 {pts}</span>{tags}')

# LEGACY: 未使用（現在のSetupsからは呼ばれない。旧ロジック。編集しても画面に反映されない点に注意）
def build_pullback_screener(m, k=20):
    """押し目質スクリーナー: 全リーダーを押し目質スコア順に抽出（裁量参考・売買非連動）。"""
    try:
        pool = m[(m["dvol"] >= DVOL_FLOOR) & (m["close"] >= 5) & (m["rs"] >= LEADER_RS)
                 & (m["close"] > m["sma200"])].copy()
        if len(pool) < 5:
            return ""
        scored = []
        for t, r in pool.iterrows():
            pts, lit = pullback_quality(r)
            if pts >= 35 and lit:   # 良質のみ
                scored.append((t, pts, lit, r))
        scored.sort(key=lambda x: -x[1])
        scored = scored[:k]
        if not scored:
            return ""
        rows = ""
        for t, pts, lit, r in scored:
            tags = "".join(f'<span class="pqtag {c}">{name}</span>' for name, _, c in lit[:5])
            d52 = r.get("dist52"); rs189 = r.get("rs189")
            rows += (f'<tr data-tkone="{t}"><td class="l tk">{t}</td>'
                     f'<td><b class="pqnum">{pts}</b></td>'
                     f'<td class="rsc">{rs189:.0f}</td>'
                     f'<td class="{color_pct(d52) if d52==d52 else "mut"}">{fmt_pct(d52) if d52==d52 else "—"}</td>'
                     f'<td class="l">{tags}</td></tr>')
        return (f'<div class="card"><h2>押し目質スクリーナー <span class="pqbadge">セットアップ</span></h2>'
                f'<div class="sub"><b>検証で+EVだった押し目の形</b>を全リーダーからスコア順に抽出（35点以上）。'
                f'長期は上昇だが直近は深く押した銘柄＝教科書ブレイクの逆が上位に来る。行タップで詳細。</div>'
                f'<table><tr><th class="l">銘柄</th><th>質</th><th>RS</th><th>52週差</th><th class="l">点灯要素</th></tr>'
                f'{rows}</table>'
                f'<div class="note"><b>スコア構成</b>（実測R差ベース）: 深押し+25／突出RS(21or126日≥85)+20／EMA上向き+18／押し目中+15／10日安値切上げ+12／63日RS+10。'
                f'減点: 高値圏-15／直近急伸-15。<b>セクターRSは無相関につき非算入</b>（検証±0.03R）。'
                f'※執行タイミングの質の目安であり、機械的なエントリー条件ではない。</div></div>')
    except Exception as e:
        print("[warn] pullback screener failed:", e)
        return ""

def build_buy_today(m, s2i, e2j, s2t, k=20, pick_set=None):
    """Leader setup scanner. Breakouts require an actual close-through of a prior pivot."""
    base = (setup_eligible(m) & (m["stage2"] == True) & (m["rs"] >= 90) & (m["rs189"] >= 85)
            & (m["dist52"] >= -0.25) & (m["breakout_failure"] != True))
    sub = m[base.fillna(False)].copy()
    if sub.empty:
        return []

    def classify(r):
        pb = r.get("pb"); d52 = r.get("dist52")
        if bool(r.get("true_breakout")):
            return ("ブレイク", "st-break", 0, float(r.get("breakout_score") or 0))
        if bool(r.get("vcp_ready")) or bool(r.get("cup_ready")) or bool(r.get("triangle_ready")):
            return ("保ち合い", "st-base", 1, float(r.get("vcp_score") or 0))
        if pd.notna(pb) and -0.20 <= pb <= -0.06 and r.get("close") > r.get("sma50"):
            return ("押し目", "st-pull", 2, float(r.get("rs189") or 0))
        if pd.notna(d52) and d52 >= -0.03:
            return ("新高値", "st-high", 3, float(r.get("rs189") or 0))
        return (None, None, 9, 0.0)

    ranked = []
    for t, r in sub.iterrows():
        tag, tcls, prio, quality = classify(r)
        if tag is not None:
            ranked.append((prio, -quality, -float(r["rs189"]), t, r, tag, tcls))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]))
    caps = {"ブレイク": k, "保ち合い": k, "押し目": 10, "新高値": 10}
    counts, selected = {}, []
    for item in ranked:
        tag = item[5]
        if counts.get(tag, 0) >= caps.get(tag, 10):
            continue
        counts[tag] = counts.get(tag, 0) + 1
        selected.append(item)
    out = []
    for _prio, _q, _rs, t, r, tag, tcls in selected:
        ind = s2i.get(t); indja = e2j.get(ind, ind) if ind else "—"
        vdry = r.get("vdry_pre"); rvol = r.get("rvol_pre")
        pivot = float(r["pivot40"]) if pd.notna(r.get("pivot40")) else float(r["close"])
        out.append(dict(t=t, rs=r["rs"], tag=tag, tcls=tcls,
                        theme=theme_of(t, s2t), ind=subtheme_of(t, s2t, indja),
                        tier_lab=r.get("tier_lab", "—"), tier_key=r.get("tier_key", "none"),
                        dvol=r.get("dvol"), pb=r.get("pb"), pos52=r.get("pos52"),
                        rvol=rvol, vdry=vdry,
                        dry=(pd.notna(vdry) and vdry <= 0.90),
                        pivot=pivot, stop=pivot * 0.93,
                        held=(pick_set is not None and t in pick_set)))
    return out


def build_vcp(m, s2i, e2j, s2t, k=12):
    """VCP candidates ranked by actual contraction, higher lows, dry volume and pivot proximity."""
    try:
        base = (setup_eligible(m) & (m["vcp_ready"] == True) & (m["rs189"] >= 80)
                & (m["adr"] >= 0.025) & (m["true_breakout"] != True)
                & (m["breakout_failure"] != True))
    except Exception:
        return []
    sub = m[base.fillna(False)].copy()
    if sub.empty:
        return []
    sub = sub.sort_values(["vcp_score", "rs189"], ascending=[False, False])
    out = []
    for t, r in sub.head(k).iterrows():
        ind = s2i.get(t); indja = e2j.get(ind, ind) if ind else "—"
        out.append(dict(t=t, rs=float(r["rs189"]), score=float(r.get("vcp_score") or 0),
                        contractions=int(r.get("contractions") or 0), higher_lows=bool(r.get("higher_lows")),
                        vdry=r.get("vdry_pre"), atrc=r.get("atr_contract"), pivot_dist=r.get("pivot_dist"),
                        touches=int(r.get("pivot_touches") or 0), rsline=bool(r.get("rsline_newhigh")),
                        uvdv=r.get("uvdv20"),
                        adr=float(r["adr"]), d52=float(r["dist52"]), pb=r.get("pb"), dvol=r.get("dvol"),
                        theme=theme_of(t, s2t), ind=subtheme_of(t, s2t, indja),
                        tier_lab=r.get("tier_lab", "—"), tier_key=r.get("tier_key", "none")))
    return out

# ----------------------------------------------------------------------------- portfolio (A)
def build_betas(W, macro, window=120, min_obs=60):
    """各銘柄の対QQQベータ（直近window日の日次リターン回帰 β=cov/var）。QQQ欠損時は空。
       #10: 銘柄ごとに同一観測日でペアワイズ計算し、最低60日を満たさない銘柄はNaN。"""
    spy = macro.get("QQQ")
    if spy is None:
        return pd.Series(dtype=float)
    closes = W.get("Close")
    if closes is None or closes.empty:
        return pd.Series(dtype=float)
    sret = spy["Close"].pct_change(fill_method=None)
    rets = closes.pct_change(fill_method=None).iloc[-window:]
    s = sret.reindex(rets.index)
    out = {}
    for tk in rets.columns:
        pair = pd.concat([rets[tk], s], axis=1).dropna()      # 同一観測日だけで平均・分散・共分散
        if len(pair) < min_obs:
            out[tk] = np.nan; continue
        vq = float(pair.iloc[:, 1].var())
        if not vq or vq != vq:
            out[tk] = np.nan; continue
        out[tk] = float(pair.iloc[:, 0].cov(pair.iloc[:, 1])) / vq
    return pd.Series(out, dtype=float).replace([np.inf, -np.inf], np.nan)

def _beta_card(bv):
    if not bv:
        return ""
    def bcls(x): return "neg" if x >= 1.3 else "pos" if x <= 0.9 else "mut"
    p = bv["port"]
    read = ("市場より大きく動く（攻め）" if p >= 1.3 else "市場並み" if p >= 0.9 else "市場より穏やか")
    def grow(lbl, v, sub):
        return (f'<div class="bt-row"><span class="bt-k">{lbl}</span>'
                f'<b class="{bcls(v)}">{v:.2f}</b><span class="bt-s">{sub}</span></div>') if v is not None else ""
    return (
        f'<div class="card"><h2>マーケット感応度（β vs QQQ）</h2>'
        f'<div class="beta-hero"><div><div class="beta-big {bcls(p)}">{p:.2f}</div>'
        f'<div class="beta-lb">ポートβ（{bv["n"]}銘柄・等加重）</div></div>'
        f'<div class="beta-read">{read}<span class="mut">・QQQが1%動くと約{p:.1f}%</span></div></div>'
        f'<details class="beta-det"><summary>先導株・市場平均・出遅れ株のβ</summary>'
        f'<div class="bt-grid">'
        + grow("先導株（RS≥85）", bv["lead"], "サイクルの先頭・振れ大")
        + grow("市場平均（QQQ）", bv["mkt"], "基準=1.00")
        + grow("出遅れ株（RS≤20）", bv["lag"], "サイクルの後尾")
        + '<div class="mut" style="font-size:10.5px;margin-top:2px">直近120日の日次リターンをQQQに回帰。先導株ほどβが高い＝強気サイクルで先に大きく動く。</div>'
        + '</div></details></div>')

# LEGACY（未使用・参照用に残置。呼び出しなし）
def build_beta_view(m, picks):
    """ポートβ（採用12銘柄の等加重平均）＋先導/市場平均/出遅れの群別β。"""
    if "beta" not in m.columns:
        return None
    b = m["beta"]
    pk = [t for t, _, _ in picks if t in b.index and b[t] == b[t]]
    port = float(np.mean([b[t] for t in pk])) if pk else None
    def grp(mask):
        v = b[mask & b.notna()]
        return float(v.mean()) if len(v) else None
    lead = grp(m["rs189"] >= 85)
    lag = grp(m["rs189"] <= 20)
    if port is None:
        return None
    return dict(port=port, lead=lead, mkt=1.00, lag=lag, n=len(pk))

def compute_regime_history(W, days=112):
    """F1/F2/F3の日次系列を過去days日分再計算し、各灯が注意/警戒に入った日を返す。
       F1=リーダー脱落率 / F2=勢い細り率 / F3=キュー崩れ。名称・変数名・閾値は compute_regime_state と完全一致。
       （旧版は本関数だけF2/F3が入れ替わっており、表示側で再度入れ替えて相殺していた＝技術的負債。解消済み）
       200日線+189日RSの助走が要るため、供給される価格履歴の後半のみ計算可能。"""
    try:
        C = W["Close"]; H = W["High"]; V = W["Volume"]
        if len(C) < 230:
            return None
        ma50 = C.rolling(50).mean(); ma200 = C.rolling(200).mean()
        dv = (C * V).rolling(20).mean()
        split_bad = (C.pct_change(fill_method=None).abs() > 1.5).rolling(189).max().fillna(0).astype(bool)
        pool = (ma50 > ma200) & (C >= 5) & (dv >= DVOL_FLOOR) & ~split_bad
        r189 = C.pct_change(189, fill_method=None).where(pool)
        rk = r189.rank(axis=1, ascending=False)
        rs189p = r189.rank(axis=1, pct=True) * 100
        rs63 = (C.pct_change(63, fill_method=None).where(pool).rank(axis=1, pct=True) * 100)
        ret20 = C.pct_change(20, fill_method=None)
        d52 = C / H.rolling(252).max() - 1

        # --- F1: 20日前(当時プール)の上位24 → 今日どうなったか。
        # NaNを一律「悪化」にすると、データ取得失敗・未更新・上場廃止・ティッカー変更まで
        # リーダー悪化として数えてしまう。→ 観測可能かどうかで先に分ける。
        observable = (C.notna() & ma200.notna() & ma50.notna()
                      & dv.notna() & C.shift(189).notna() & ~split_bad)
        eligible = pool
        was24 = (rk.shift(20) <= LEADER_BREADTH_BASE_N)
        rank_drop = was24 & observable & eligible & (rk > LEADER_BREADTH_DROP_RANK)      # 観測でき、適格だが順位が落ちた
        elig_drop = was24 & observable & ~eligible                 # 観測でき、適格条件から脱落（50>200割れ/流動性/株価）
        unknown   = was24 & ~observable                            # 値が取れない＝理由不明（分子に入れない）
        dropped_mask = rank_drop | elig_drop
        den_all = was24.sum(axis=1).replace(0, np.nan)
        den_obs = (was24 & observable).sum(axis=1).replace(0, np.nan)   # #23: 分母＝観測可能な元上位24
        coverage = den_obs / den_all
        f1 = dropped_mask.sum(axis=1) / den_obs
        f1 = f1.where(coverage >= 0.90)                            # 観測率90%未満はF1を無効化(DATA_INCOMPLETE)

        # --- 定義と変数名を全関数で一致させる（旧: history側でF2/F3が逆で、表示側で入れ替えて相殺していた）
        # F2 = 勢い細り率: 上位24のうち 63日RS < 85
        top24 = (rk <= LEADER_BREADTH_BASE_N)
        _obs63 = top24 & rs63.notna()                                  # #23: rs63欠損を分母に残さない
        f2 = ((rs63 < LEADER_RS) & _obs63).sum(axis=1) / _obs63.sum(axis=1).replace(0, np.nan)
        # F3 = キュー崩れ: 適格キュー(189RS>=85 かつ 200MA上)のうち反発待ち
        qual = (rs189p >= LEADER_RS) & (C > ma200) & pool
        f3 = (qual & ((ret20 <= 0) | (d52 < -0.15))).sum(axis=1) / qual.sum(axis=1).replace(0, np.nan)
        idx = C.index[-days:]
        out = {}
        for key, ser, warn, bad in (("f1", f1, F1_WARN, LEADER_DROPOUT_WARN),
                                    ("f2", f2, LEADER_FADE_CAUTION, LEADER_FADE_WARN),     # 勢い細り
                                    ("f3", f3, QUEUE_BREAK_WARN, QUEUE_BREAK_SEVERE)):    # キュー崩れ
            v = ser.reindex(idx).dropna()
            if len(v) < 5:
                out[key] = dict(warn_since=None, warn_trunc=False, bad_since=None, bad_trunc=False); continue
            def _since(level):
                """今その水準以上なら、連続でその水準以上を保っている最初の日。
                   窓の先頭まで遡り切った場合は truncated=True（実際の点灯日はもっと前）。"""
                if v.iloc[-1] < level:
                    return None, False
                d = None
                for t in reversed(v.index):
                    if v.loc[t] >= level:
                        d = t
                    else:
                        return d, False
                return d, True          # 窓の先頭で打ち切り
            w_d, w_tr = _since(warn)
            b_d, b_tr = _since(bad)
            out[key] = dict(warn_since=w_d, warn_trunc=w_tr, bad_since=b_d, bad_trunc=b_tr)
        out["asof"] = idx[-1]
        # 最新のF1: 値・分母・観測率・脱落銘柄と「脱落理由」を state 側へ供給
        try:
            rk_last = rk.iloc[-1]
            reasons = {}
            for t in rank_drop.columns[rank_drop.iloc[-1]]:
                reasons[t] = "順位落ち"
            for t in elig_drop.columns[elig_drop.iloc[-1]]:
                reasons[t] = "適格脱落"
            unk = list(unknown.columns[unknown.iloc[-1]])
            names = sorted(reasons, key=lambda t: (reasons[t] != "適格脱落",
                                                   -(float(rk_last[t]) if pd.notna(rk_last.get(t)) else 1e9)))
            out["f1_now"]      = float(f1.iloc[-1]) if pd.notna(f1.iloc[-1]) else np.nan
            out["f1_names"]    = names[:8]
            out["f1_reasons"]  = reasons
            out["f1_den"]      = int(was24.iloc[-1].sum())
            out["f1_num"]      = int(dropped_mask.iloc[-1].sum())
            out["f1_rank_drop"]= int(rank_drop.iloc[-1].sum())
            out["f1_elig_drop"]= int(elig_drop.iloc[-1].sum())
            out["f1_unknown"]  = unk
            out["f1_coverage"] = float(coverage.iloc[-1]) if pd.notna(coverage.iloc[-1]) else np.nan
            out["f1_status"]   = ("OK" if pd.notna(f1.iloc[-1]) else "DATA_INCOMPLETE")
            # F1/F2/F3の日次系列（OVの小スパーク d_f1/d_f2/d_f3 用）。末尾30点を保持。
            try:
                out["f1_series"] = [float(x) for x in f1.tail(30).tolist() if pd.notna(x)]
                out["f2_series"] = [float(x) for x in f2.tail(30).tolist() if pd.notna(x)]
                out["f3_series"] = [float(x) for x in f3.tail(30).tolist() if pd.notna(x)]
            except Exception:
                pass
        except Exception:
            pass
        return out
    except Exception:
        return None

def compute_regime_state(m, hist=None):
    """F1-F3の値と点灯数を計算して返す（パネルと条件カードで共用）。
       母集団はポートフォリオ選定と同一の適格プール（50日SMA>200日SMA × $10M × $5）に統一。
       F1だけは「20日前の当時プール」で上位24を確定し今日まで追跡する必要があるため、
       時系列を持つ compute_regime_history() の結果(hist)があればそちらを正とする。"""
    try:
        pool = m[(m["sma50"] > m["sma200"]) & (m["dvol"] >= DVOL_FLOOR)
                 & (m["close"] >= 5) & m["rs189"].notna()].copy()
        # 母集団が極小(<12)なら先導分析は無意味なので保留。12以上あればF2/F3を算出（小universeでも動く）。
        if len(pool) < 12:
            return None
        rank_now = core_continuation_rank(m).reindex(pool.index)
        top24_now = set(rank_now[rank_now <= 2 * N_PORT].index)
        f1 = np.nan; f1_names = []; f1_meta = {}
        if hist and hist.get("f1_status") == "OK":
            # 正: 当時プールで上位24を確定 → 今日まで追跡。
            #     分子は「観測できた脱落」のみ（順位落ち / 適格脱落）。値が取れない銘柄は分子に入れない。
            f1 = float(hist["f1_now"]); f1_names = list(hist.get("f1_names", []))
            f1_meta = {k: hist.get(k) for k in
                       ("f1_den", "f1_num", "f1_rank_drop", "f1_elig_drop",
                        "f1_coverage", "f1_unknown", "f1_reasons", "f1_status")}
        elif hist and hist.get("f1_status") == "DATA_INCOMPLETE":
            f1_meta = {"f1_status": "DATA_INCOMPLETE", "f1_coverage": hist.get("f1_coverage")}
        elif "rs189_l20" in pool and pool["rs189_l20"].notna().sum() >= 30:
            # フォールバック（履歴不足時）。今日のプール内でしか追えず、F1を過小評価する点に注意。
            rank_l20 = pool["rs189_l20"].rank(ascending=False)
            was24 = set(rank_l20[rank_l20 <= 2 * N_PORT].index)
            if was24:
                # 20日前は適格だったが今日プールから消えた銘柄も「脱落」に数える
                gone = set(m.index[(m["rs189_l20"].rank(ascending=False) <= 2 * N_PORT)]) - set(pool.index)
                was24 |= gone
                dropped = [t for t in was24 if (t not in pool.index) or rank_now.get(t, 999) > 3 * N_PORT]
                f1 = len(dropped) / len(was24)
                f1_names = sorted(dropped, key=lambda t: rank_now.get(t, 999))[:8]
        f2 = np.nan; f2_names = []
        if top24_now and "rs63" in pool:
            weak = [t for t in top24_now if pd.notna(pool.loc[t, "rs63"]) and pool.loc[t, "rs63"] < LEADER_RS]
            f2 = len(weak) / len(top24_now)
            f2_names = sorted(weak, key=lambda t: rank_now.get(t, 999))[:8]
        f3 = np.nan; qn = 0; f3_names = []
        try:
            # 資格キュー = エントリー適格の母集団（189RS≥85 かつ 200MA上）。検証定義に一致。
            # ※以前は rs63≥85 と 21EMA近接 を追加していたが、これは「反発待ち＝深く押した」概念と矛盾し
            #   （深押し銘柄は21EMAに接していない）、リーダー脱落中の銘柄を母集団から誤って除外していた。
            qual = pool[(pool["rs189"] >= LEADER_RS) & (pool["close"] > pool["sma200"])]
            qn = len(qual)
            if qn >= 3:
                # 反発待ち = 直近20日がマイナス（押している）or 52週高値から15%超下（深く押した）
                bad = qual[(qual["ret20"] <= 0) | (qual["dist52"] < -0.15)]
                f3 = len(bad) / qn
                # 表示は「押しが深い順」（52週高値差が大きい順）に
                f3_names = sorted(bad.index,
                                  key=lambda t: (qual.loc[t, "dist52"] if qual.loc[t, "dist52"] == qual.loc[t, "dist52"] else 0))[:8]
        except Exception:
            pass
        def stat(v, warn, hi):
            if v != v: return "reg-na"
            if v >= hi: return "reg-bad"
            if v >= warn: return "reg-warn"
            return "reg-ok"
        c1 = stat(f1, F1_WARN, LEADER_DROPOUT_WARN); c2 = stat(f2, LEADER_FADE_CAUTION, LEADER_FADE_WARN)
        c3 = stat(f3, QUEUE_BREAK_WARN, QUEUE_BREAK_SEVERE) if qn >= 3 else "reg-na"
        n_bad = sum(1 for c in (c1, c2, c3) if c == "reg-bad")
        n_warn = sum(1 for c in (c1, c2, c3) if c == "reg-warn")
        return dict(f1=f1, f2=f2, f3=f3, qn=qn, c1=c1, c2=c2, c3=c3,
                    n_bad=n_bad, n_warn=n_warn, f1_names=f1_names, f2_names=f2_names, f3_names=f3_names,
                    **f1_meta)
    except Exception as e:
        print("[warn] regime state failed:", e)
        return None

def build_regime_alerts(m, st=None, collapsible=False, hist=None):
    """レジーム先行警戒灯 F1-F3。"""
    if st is None:
        st = compute_regime_state(m, hist=hist)
    if not st:
        return ""
    try:
        f1, f2, f3, qn = st["f1"], st["f2"], st["f3"], st["qn"]
        c1, c2, c3 = st["c1"], st["c2"], st["c3"]
        f1_names, f2_names = st["f1_names"], st["f2_names"]
        f3_names = st.get("f3_names", [])
        def lab(v, c):
            if c == "reg-na": return "—", "算出不可"
            txt = f"{v*100:.0f}%"
            return txt, {"reg-bad": "警戒", "reg-warn": "注意", "reg-ok": "平常"}[c]
        v1, l1 = lab(f1, c1); v2, l2 = lab(f2, c2)
        v3, l3 = (lab(f3, c3) if qn >= 3 else ("—", f"母数{qn}<3"))
        n_bad = st["n_bad"]
        _lit = [n for n, c in (("F1", c1), ("F2", c2), ("F3", c3)) if c == "reg-bad"]
        if   _lit:            hdr, hcls = f'⚠ {"・".join(_lit)} 点灯', "reg-hdr-bad"
        elif st["n_warn"]:    hdr, hcls = "注意域（点灯手前）", "reg-hdr-warn"
        else:                 hdr, hcls = "平常（内部は健全）", "reg-hdr-ok"
        def _onset(key):
            h = (hist or {}).get(key) or {}
            asof = (hist or {}).get("asof")
            def _fmt(d, lab, cls, trunc=False):
                if d is None:
                    return ""
                ago = (asof - d).days if asof is not None else None
                if trunc:
                    return f'<span class="onset {cls}" title="計算できる期間の先頭より前から継続中">{lab} {ago}日以上前から</span>'
                agotxt = f"（{ago}日前）" if ago is not None and ago > 0 else "（今日）"
                return f'<span class="onset {cls}">{lab} {d.month}/{d.day}{agotxt}</span>'
            a = _fmt(h.get("bad_since"), "警戒入り", "on-bad", h.get("bad_trunc"))
            b = _fmt(h.get("warn_since"), "注意入り", "on-warn", h.get("warn_trunc"))
            body = (a + b) if (a or b) else '<span class="onset on-ok">平常</span>'
            return f'<div class="reg-onset">{body}</div>'
        _rsn = st.get("f1_reasons") or {}
        chips1 = " ".join(f'<span class="rgchip" title="{_rsn.get(t,"")}">{t}'
                          + (f'<sup>{"適" if _rsn.get(t)=="適格脱落" else "順"}</sup>' if _rsn.get(t) else "")
                          + '</span>' for t in f1_names) or '<span class="mut">—</span>'
        _cov = st.get("f1_coverage")
        if st.get("f1_status") == "DATA_INCOMPLETE":
            _f1meta = f'<div class="reg-onset"><span class="onset on-warn">データ不足で無効化（観測率 {(_cov or 0)*100:.0f}%）</span></div>'
        elif _cov is not None and _cov == _cov:
            _f1meta = (f'<div class="reg-onset"><span class="onset on-ok">分母{st.get("f1_den","?")}・観測率{_cov*100:.0f}%'
                       f'・順位落ち{st.get("f1_rank_drop",0)}／適格脱落{st.get("f1_elig_drop",0)}</span></div>')
        else:
            _f1meta = ""
        chips2 = " ".join(f'<span class="rgchip">{t}</span>' for t in f2_names) or '<span class="mut">—</span>'
        chips3 = " ".join(f'<span class="rgchip">{t}</span>' for t in f3_names) or '<span class="mut">—</span>'
        _cc = " regfold" if collapsible else ""
        _tog = '<span class="reg-tog">タップで開閉 ▾</span>' if collapsible else ""
        _onc = ' onclick="regTog(this)"' if collapsible else ""
        return (
            f'<div class="card reg-card{_cc}">'
            f'<div class="hdr reg-hd"{_onc}><h2>レジーム警戒灯 <span class="h2en">Regime Early-Warning</span></h2>'
            f'<span class="reg-hdr {hcls}">{hdr}</span>{_tog}</div>'
            f'<div class="reg-body">'
            f'<div class="reg-grid">'
            f'<div class="reg-cell {c1}"><div class="reg-k">F1 リーダー脱落率 <span class="reg-kind kind-t">タイミング</span></div>'
            f'<div class="reg-role">最速の警報｜赤転換の中央48日前・19/22的中・誤報1.1/年</div>'
            f'{_onset("f1")}{_f1meta}'
            f'<div class="reg-v">{v1}</div><div class="reg-l">{l1}</div>'
            f'<div class="reg-chips">{chips1}</div></div>'
            f'<div class="reg-cell {c2}"><div class="reg-k">F2 勢い細り率 <span class="reg-kind kind-t">タイミング</span></div>'
            f'<div class="reg-role">確定が近い｜赤転換の中央32日前・12/22的中・誤報1.0/年</div>'
            f'{_onset("f2")}'
            f'<div class="reg-v">{v2}</div><div class="reg-l">{l2}</div>'
            f'<div class="reg-chips">{chips2}</div></div>'
            f'<div class="reg-cell {c3}"><div class="reg-k">F3 キュー崩れ <span class="reg-kind kind-p">深さ</span></div>'
            f'<div class="reg-role">下落の深さを見積もる｜60%超でDD10%確率が1.84倍（前半2.14x／後半1.63x）</div>'
            f'{_onset("f3")}'
            f'<div class="reg-v">{v3}</div><div class="reg-l">{l3}</div>'
            f'<div class="reg-chips">{chips3}</div></div>'
            f'</div>'
            f'<div class="note">'
            f'<p><b>3灯は足し算しない。</b>それぞれ別の問いに答える計器。複合ルール（2灯以上）は時期によって安定しないため採用しない。</p>'
            f'<p><b>F1 リーダー脱落率</b>（≥30%）｜<b>いつ</b>を答える<br>'
            f'20日前に上位{2*N_PORT}だった銘柄のうち、今{3*N_PORT}位より下に落ちた割合。'
            f'点灯＝<b>天井ゾーンに入った</b>。赤転換の中央48日前に点き19/22で的中（誤報1.1/年）＝3灯で最も早い。</p>'
            f'<p><b>F2 勢い細り率</b>（≥40%・母数=上位{2*N_PORT}）｜<b>いつ</b>を答える<br>'
            f'上位{2*N_PORT}のうち63日RSが85未満の割合。点灯＝<b>確定が近い</b>。赤転換の中央32日前・12/22的中（誤報1.0/年）。'
            f'母数の上位{2*N_PORT}はポート表の継続境界線までと一致。</p>'
            f'<p><b>F3 キュー崩れ</b>（≥60%・母数{qn}）｜<b>どれくらい深いか</b>を答える<br>'
            f'適格母集団（189日RS≥85＆200日線上）のうち「反発待ち＝20日マイナス、または52週高値−15%超下」の割合。'
            f'60%超のとき今後60日にDD10%が起きる確率が<b>1.84倍</b>（前半2.14x／後半1.63xで両期間クリア）。'
            f'タイミングではなく<b>下落の深さの見積もり</b>に使う。</p>'
            f'<p><b>行動</b>：F1点灯で構えを作り、F2点灯で新規サイズを絞り、F3が60%超なら深い下落を想定して裁量スイングの+25%到達玉を⅓利確（Core 12はピーク×0.70トレール維持）。'
            f'売買ルール本体（地合いゲートとRS選定）は変えない。</p>'
            f'<p class="fver">※上記の検証成績（19/22・1.84倍・+28.8% 等）は <b>logic {LOGIC_VERSION}</b>（build {LOGIC_HASH}）／検証データ {BACKTEST_THROUGH} 時点で算出。ロジック変更時は再検証までの暫定値。</p>'
            f'<p class="mut">裏取りにはクレジット・VIX期間構造・売り抜け日・センチメントを併せて見る（単体では動かさない）。</p></div></div></div>')
    except Exception as e:
        print("[warn] regime alerts failed:", e)
        return ""

def build_portfolio(m, s2t):
    # v2確定仕様の適格3条件: 50日SMA>200日SMA × 出来高金額$10M/日 × 株価$5以上（テーマ上限なし）
    # ※「週足SAR非弱気」はアブレーションで撤廃（撤廃版がCAGR+4.4pt/年・Sharpe+0.114・12/12サブサンプルで優位。
    #   代償: 最大DD −31.6→−35.0。危機はNQ4色ゲートが露出制御、平時は勝ち筋(押し目中の最強銘柄)の出禁だった）。
    # ※「終値>50日SMA」も検証外規則として同時削除済み。
    cand = m[(m["sma50"] > m["sma200"])
             & (m["dvol"] >= DVOL_FLOOR) & (m["close"] >= 5)
             & m["rs189"].notna() & (m["rs189"] >= 85)].copy()   # 189日RS≥85（冒頭仕様と一致・監査#2）
    cand = cand.sort_values("rs189", ascending=False)
    # 出遅れ株: 業種内相対 <−20%。※方針変更(2026-07-07): 出遅れも買う。フラグはタグ表示用に残すだけ。
    cand["laggard"] = False
    try:
        if "sec_rel" in cand.columns:
            cand["laggard"] = (cand["sec_rel"] < -0.20).fillna(False)
    except Exception as e:
        print("[warn] laggard flag failed:", e)
        cand["laggard"] = False
    # 思想的除外(バイオ/創薬): 選定から外す。candには excluded_theme フラグを残し表示する。
    cand["excluded_theme"] = [is_excluded_theme(t, s2t) for t in cand.index]
    # リーダー外除外: リーダー(63日RS≥85 かつ 200MA上)でない銘柄は買わない。
    #   RS189の適格を満たしても先導株でなければ選定対象外＝「上から順に、リーダーの中で12銘柄」。
    def _is_leader_row(t):
        try:
            return bool(leader_state(cand.loc[t])[0])
        except Exception:
            return False
    cand["nonleader"] = [not _is_leader_row(t) for t in cand.index]
    # 勢い落ち除外: 189日RSリーダーでも63日RS<85(中期の勢いが落ちた)なら選定から外す。
    #   基本思想: 189日をベースに、63日で勢いが落ちたものは買わない。表示は残す(タグのみ・強さ確認用)。
    def _fade63(t):
        try:
            v63 = cand.loc[t].get("rs63")
            return bool(v63 is not None and v63 == v63 and v63 < LEADER_RS)
        except Exception:
            return False
    cand["fade63"] = [_fade63(t) for t in cand.index]
    # --- 新規参入（ヒステリシス付き）---
    #   判定: 過去(1d/5d/20d前)に3N=36位圏の「外」→ 今 30位「以内」に飛び込んだ銘柄。
    #   実測(2017-2026): 単純な36位線またぎだと「今日」の新規は63%が5日以内に出戻る境界ノイズ。
    #   30位に絞る緩衝帯を入れると 脱落63%→44%・10日後在籍48%→60%・60日後中央+4.2% に改善。
    _CAP_OUT, _CAP_IN = NEW_ENTRY_OUT_RANK, NEW_ENTRY_IN_RANK
    _rk_now = m["rs189"].rank(ascending=False)              # 全ユニバース基準（プール外はNaN=当時未在籍）
    cand["rk189_now"] = _rk_now.reindex(cand.index)         # 表示用の現在順位
    _entry = {}
    for col, lab in (("rs189_l1", "今日"), ("rs189_l5", "今週"), ("rs189_l20", "今月")):
        if col not in m.columns or m[col].notna().sum() < 30:
            continue
        r = m[col].rank(ascending=False, na_option="bottom")   # 各時点の順位（当時プール基準・NaN=当時圏外）
        for t in cand.index:
            if t in _entry:
                continue                              # より短い期間の判定を優先
            if _rk_now.get(t, 999) <= _CAP_IN and r.get(t, 999) > _CAP_OUT:
                _entry[t] = lab
    cand["new_entry"] = [_entry.get(t) for t in cand.index]
    # プール = 小型創薬・リーダー外・勢い落ち を除いた上位RS189から N_PORT（出遅れは含める＝買う・タグのみ）。
    pool = cand[~(cand["excluded_theme"] | cand["nonleader"] | cand["fade63"])]
    picks = [(t, theme_of(t, s2t), row) for t, row in pool.head(N_PORT).iterrows()]
    return picks, cand

# ----------------------------------------------------------------------------- leaders + ①〜⑤ states
# Canonical state machine + leader filter from v38_auto.py / SETUP_自動更新.md
# --- 思想的除外テーマ: モメンタム継続性が構造的に効かない業種(選定から外す・表示は残す) ---
#   バイオ/創薬/臨床段階は「治験結果で一夜に倍か半減」でトレンド追随が成立しない。
#   検証: 除外してもCAGR/Sharpe不変(55.9→55.9・te+0.01)=リターン犠牲ゼロで思想を通せる。
# バイオ除外はサブテーマ単位: ヘッドライン一発で±30%飛ぶ投機的小型創薬のみ外す。
# 大手バイオ/大手製薬/GLP-1/手術ロボ/医療機器等はモメンタムで来れば拾う(思想: 大型は別物)。
EXCLUDE_SUBTHEMES = ("臨床段階・中小型バイオ",)
def is_excluded_theme(t, s2t):
    v = s2t.get(t)
    if not isinstance(v, list) or len(v) < 2:
        return False
    sub = v[1] or ""
    return sub in EXCLUDE_SUBTHEMES

LEADER_RS = 85   # リーダー(=先導株)の唯一の定義: 63日RS≥85 かつ 200日線上。
                 # マーケットタブ「リーダー一覧」もピックアップの母集団もこの1定義を参照(重複定義なし)。
BUY_RS = 90                                           # 押し目シグナルは更に厳選: RS>=90
BUY_CAP = 12                                          # 表示上限
STATE_DEF = [("②", "新高値圏/継続", "s-go"),
             ("③", "押し目（形状）", "s-shape"),
             ("①", "伸び過ぎ（待ち）", "s-wait"),
             ("④", "深押し/ベース", "s-deep"),
             ("⑤", "割れ/様子見", "s-break")]

def tag_state(r):
    """Exact replication of v38_auto.py tag(): ①〜⑤ in priority order."""
    dma50 = r["dma50"]; dma21 = r["dma21"]; pb = r["pb"]; ret5 = r["ret5"]
    if (pd.notna(dma50) and r["close"] < r["sma50"]) or (pd.notna(dma21) and dma21 < -0.06):
        return "⑤"
    if pd.notna(pb) and pb < -0.08:
        return "④"
    if (pd.notna(pb) and -0.08 <= pb <= -0.02 and pd.notna(dma21) and -0.05 <= dma21 <= 0.05
            and pd.notna(ret5) and ret5 > -0.03):
        return "③"
    if pd.notna(dma21) and dma21 > 0.10:
        return "①"
    return "②"

_STATE_LABEL = {c: l for c, l, _ in STATE_DEF}
_STATE_SHORT = {"②": "継続", "③": "押し目", "①": "伸び過ぎ", "④": "深押し", "⑤": "割れ"}

def _state_badge(code, nut, nucls, reason=""):
    """状態(①〜⑤)＋値動きニュアンス（堅調/急落中等）のバッジHTML。code空=リーダー外（理由付き）。"""
    nu = f' ・ <b class="{nucls}">{nut}</b>' if nut else ''
    if code:
        return f'<span class="stb stb-{code}">{code}{_STATE_SHORT.get(code,"")}{nu}</span>'
    why = ""
    if reason:
        if "200MA" in reason: why = "：200MA下"
        elif "RS" in reason:  why = "：RS&lt;85"
    return f'<span class="stb stb-none">リーダー外{why}{nu}</span>'

def leader_state(r):
    """RSリーダー判定（RS>=85 かつ 200MA上）と状態①〜⑤。Returns (is_leader, code, label, reason)."""
    rs = r.get("rs"); close = r.get("close"); sma200 = r.get("sma200")
    has_rs = rs is not None and not (isinstance(rs, float) and np.isnan(rs))
    above = close is not None and sma200 is not None and pd.notna(sma200) and close > sma200
    if has_rs and rs >= LEADER_RS and above:
        code = tag_state(r)
        return (True, code, _STATE_LABEL.get(code, ""), "")
    if not has_rs or rs < LEADER_RS:
        return (False, "", "", f"63日RS<{LEADER_RS}（リーダー対象外）")
    return (False, "", "", "200MA下（リーダー対象外）")

def momentum_nuance(r):
    """同じ位置でも『堅調に止まっている』のか『急落中』なのかを区別。Returns (tag, note, cls)."""
    pchg = r.get("pchg"); ret5 = r.get("ret5"); adr = r.get("adr")
    if pchg is None or (isinstance(pchg, float) and np.isnan(pchg)):
        return ("", "", "mut")
    a = adr if (adr is not None and adr == adr and adr > 0) else 0.03
    r5 = ret5 if (ret5 is not None and ret5 == ret5) else 0.0
    if pchg <= -1.5 * a or (r5 <= -0.10 and pchg < 0):
        return ("急落中", "下げが速い（急落局面）。急落注意・投げ（セリングクライマックス）の有無を確認。急落注意・投げの有無を確認", "neg")
    if pchg >= 1.0 * a:
        return ("反発中", "下げ止まって切り返し。押し目なら入りやすい局面", "pos")
    if pchg >= -0.5 * a and r5 > -0.05:
        return ("堅調", "値持ちが良く落ち着いた値動き・押しが浅い", "pos")
    return ("軟調", "じり安で方向感に乏しい・様子見", "mut")

# LEGACY（未使用・参照用に残置。呼び出しなし）
def _leaders_watch_card(m, cap=80):
    """リーダー一覧（RS≥85 かつ 200MA上）をRS順のチップで。タップで詳細。ウォッチ用。（旧称「リーダー一覧」を統合）"""
    lead = m[(m["rs"] >= LEADER_RS) & (m["close"] > m["sma200"])].copy()
    if lead.empty:
        return ""
    lead = lead.sort_values("rs189", ascending=False)
    n = len(lead)
    chips = "".join(
        f'<span class="thstk" data-tk="{t}" onclick="thStk(this)">'
        f'<b>{t}</b><span class="thstk-rs">RS{int(round(float(r.get("rs189",0) or 0)))}</span></span>'
        for t, r in lead.head(cap).iterrows())
    more = f'<span class="thmore">+{n-cap}銘柄</span>' if n > cap else ""
    tks = " ".join(lead.head(cap).index.tolist())
    return (f'<div class="card"><h2>リーダー一覧 '
            f'<button class="copybtn" onclick="copyList(event,this)" data-list="{tks}">📋 コピー</button></h2>'
            f'<div class="sub">RS≥{LEADER_RS}（63日）かつ200日線上＝<b>リーダー</b>・{n}銘柄。ピックアップの候補もこの母集団から。RS強い順・タップで詳細。</div>'
            f'<div class="thstks">{chips}{more}</div></div>')

def build_leaders(m, s2i, e2j, s2t):
    """Leaders = RS>=85 & above 200MA, tagged with state ①〜⑤. Returns (by_state, buys)."""
    lead = m[(m["rs"] >= LEADER_RS) & (m["close"] > m["sma200"])].copy()
    if lead.empty:
        return {}, []
    lead["state"] = lead.apply(tag_state, axis=1)
    lead = lead.sort_values("rs", ascending=False)
    def info(t, r):
        th = theme_of(t, s2t)
        ind = s2i.get(t); indja = e2j.get(ind, ind) if ind else "—"
        nu_tag, _nun, nu_cls = momentum_nuance(r)
        return dict(t=t, rs=r["rs"], theme=th, ind=subtheme_of(t, s2t, indja), pb=r["pb"],
                    pp_days=r.get("pp_days"), pp_ratio=r.get("pp_ratio"),
                    dma21=r["dma21"], ret20=r["ret20"], adr=r["adr"], rvol=r["rvol"],
                    close=r["close"], state=r["state"], nut=nu_tag, nucls=nu_cls,
                    tier_lab=r.get("tier_lab", "—"), tier_key=r.get("tier_key", "none"),
                    mcap=r.get("mcap"), dvol=r.get("dvol"))
    by_state = {}
    for code, _, _ in STATE_DEF:
        sub = lead[lead["state"] == code]
        by_state[code] = [info(t, r) for t, r in sub.iterrows()]
    # 本日◎押し目: state ③ かつ RS>=BUY_RS で厳選 (entry range + 初期ストップ; 利確はトレール)
    buys = []
    sub3 = lead[(lead["state"] == "③") & (lead["rs"] >= BUY_RS)].sort_values("rs", ascending=False)
    for t, r in sub3.head(BUY_CAP).iterrows():
        adr_d = r["close"] * r["adr"]
        lo = max(r["sma21"] - 0.5*adr_d, r["hi40"]*0.92)
        hiR = r["close"]
        if lo >= hiR:
            lo = hiR * 0.985
        mid = (lo + hiR) / 2
        d = info(t, r); d.update(lo=lo, hi=hiR, t15=mid*1.15, t30=mid*1.30)
        buys.append(d)
    return by_state, buys

# ----------------------------------------------------------------------------- sector RS
def build_sector_rs(m, s2i, e2j, s2t):
    """サブテーマ(s2t)単位で括る（量子/メモリ/AI GPU等を分離・銘柄選定とは独立の参考ランキング）。"""
    grp = {}
    sub_parent = {}
    for t in m.index:
        st = s2t.get(t)
        sth = st[1] if (isinstance(st, list) and len(st) >= 2 and st[1] and st[1] not in ("?", "")) else None
        if not sth:
            continue
        grp.setdefault(sth, []).append(t)
        if sth not in sub_parent and isinstance(st, list) and st[0]:
            sub_parent[sth] = st[0].split(". ", 1)[-1] if ". " in st[0] else st[0]
    recs = []
    for nm, tks in grp.items():
        if len(tks) < 2:                       # 少数でも可（ランキング参考用）
            continue
        sub = m.loc[tks]
        pairs = sorted(((t, float(sub.at[t, "rs"])) for t in tks),
                       key=lambda x: -(x[1] if x[1] == x[1] else -9))   # RS desc
        med63 = float(np.nanmedian(sub["rs"]))
        med189 = float(np.nanmedian(sub["rs189"])) if "rs189" in sub.columns else med63
        prev = float(np.nanmedian(sub["rs_l1"])) if "rs_l1" in sub.columns else med63
        # 定点比較: 現在のRS中央値 − 各時点のRS中央値（先週/2週前/1ヶ月前）
        _pw1 = float(np.nanmedian(sub["rs_w1"])) if "rs_w1" in sub.columns else med63
        _pw2 = float(np.nanmedian(sub["rs_w2"])) if "rs_w2" in sub.columns else med63
        _pm1 = prev
        d_w1 = (med63 - _pw1) if (med63 == med63 and _pw1 == _pw1) else 0.0   # 先週比
        d_w2 = (med63 - _pw2) if (med63 == med63 and _pw2 == _pw2) else 0.0   # 2週間前比
        d_m1 = (med63 - _pm1) if (med63 == med63 and _pm1 == _pm1) else 0.0   # 1ヶ月前比
        # 広がり（breadth）と集中度（top2依存）＝初動の質。単独材料株テーマを弾く。
        #   #21: EMA/SMAがNaNの銘柄を分母から除外（未上場期間をFalse扱いしない）
        if "ema21" in sub.columns:
            _v21 = sub["close"].notna() & sub["ema21"].notna()
            breadth21 = float((sub.loc[_v21, "close"] > sub.loc[_v21, "ema21"]).mean()) if bool(_v21.any()) else float("nan")
        else:
            breadth21 = float("nan")
        if "sma50" in sub.columns:
            _v50 = sub["close"].notna() & sub["sma50"].notna()
            breadth50 = float((sub.loc[_v50, "close"] > sub.loc[_v50, "sma50"]).mean()) if bool(_v50.any()) else float("nan")
        else:
            breadth50 = float("nan")
        _pos = sub["ret5"].clip(lower=0).sort_values(ascending=False)
        # #22: 上昇株が皆無なら「集中度100%」ではなくNaN（勝者不在と完全集中を区別）
        top2 = float(_pos.head(2).sum() / _pos.sum()) if float(_pos.sum()) > 0 else float("nan")
        # ローテ状態（短期d_w1・中期d_m1・長期med189）: 初動＝短期加速×広がり×非集中
        if d_w1 >= 4 and breadth21 >= 0.5 and top2 < 0.70 and med189 < 85:
            rot = "初動"
        elif med63 >= 70 and med189 >= 70:
            rot = "強い継続"
        elif d_m1 >= 3 and d_w1 >= 0:
            rot = "改善"
        elif med63 >= 55:
            rot = "監視"
        else:
            rot = "弱い"
        recs.append(dict(ja=nm, parent=sub_parent.get(nm, "—"), n=len(tks),
                         med=med63, med189=med189,
                         drs=(med63 - prev) if (med63 == med63 and prev == prev) else 0.0,
                         d_w1=d_w1, d_w2=d_w2, d_m1=d_m1,
                         breadth21=breadth21, breadth50=breadth50, top2=top2, rot=rot,
                         d1=float(np.nanmedian(sub["pchg"])),
                         w1=float(np.nanmedian(sub["ret5"])),
                         m1=float(np.nanmedian(sub["ret21"])),
                         members=pairs))
    if not recs:
        return []
    df = pd.DataFrame(recs)
    # スコア = 63日RS(勢い) と 189日RS(持続) の中央値ランクを均等ブレンド → 0-100
    df["score"] = (df["med"].rank(pct=True) * 0.5 + df["med189"].rank(pct=True) * 0.5) * 100
    df = df.sort_values(["score", "med"], ascending=False).reset_index(drop=True)
    return df.to_dict("records")

# ----------------------------------------------------------------------------- テーマ・ドリルダウン（2階層: 中テーマ → 中の銘柄RSローテ）
def load_theme_map():
    """ticker→中テーマ の対応（committed JSON）。env V38_THEME_JSON→/mnt/project→同階層→カレント。"""
    import json as _j
    paths = [os.environ.get("V38_THEME_JSON"), "/mnt/project/theme_map.json",
             os.path.join(os.path.dirname(CACHE or "."), "theme_map.json"), "theme_map.json"]
    for p in paths:
        if p and os.path.exists(p):
            try:
                return _j.load(open(p, encoding="utf-8"))
            except Exception:
                pass
    return {}

def build_theme_drill(m, tmap, min_members=3):
    """中テーマ別に構成銘柄のRS189(強さ)とRSランクΔ(勢い)を集計。強い順。"""
    if not tmap or "rs189" not in m.columns:
        return []
    from collections import defaultdict
    groups = defaultdict(list)
    for t in m.index:
        th = tmap.get(t)
        if not th:
            continue
        rs = m.at[t, "rs189"]
        if rs is None or (isinstance(rs, float) and np.isnan(rs)):
            continue
        mom = m.at[t, "rs189_d"] if "rs189_d" in m.columns else 0.0
        r21 = m.at[t, "ret21"] if "ret21" in m.columns else np.nan
        groups[th].append(dict(t=t, rs=float(rs), mom=float(mom) if mom == mom else 0.0,
                               ret21=float(r21) if r21 == r21 else 0.0))
    out = []
    for th, mem in groups.items():
        if len(mem) < min_members:
            continue
        mem.sort(key=lambda x: -x["rs"])
        rs_med = float(np.median([x["rs"] for x in mem]))
        mom_med = float(np.median([x["mom"] for x in mem]))
        q = ("主導" if rs_med >= 50 and mom_med >= 0 else "弱化" if rs_med >= 50
             else "改善" if mom_med >= 0 else "停滞")
        out.append(dict(name=th, n=len(mem), rs=rs_med, mom=mom_med, q=q, members=mem))
    out.sort(key=lambda d: -d["rs"])
    return out

def _theme_drill_card(themes):
    if not themes:
        return ""
    def tile(i, th):
        rs = th["rs"]; g = rs >= 50
        inten = min(1.0, abs(rs - 50) / 42)
        bg = (f"rgba(34,197,94,{0.14+inten*0.34:.2f})" if g else f"rgba(239,68,68,{0.14+inten*0.34:.2f})")
        arr = "▲" if th["mom"] > 1.5 else "▼" if th["mom"] < -1.5 else "▬"
        acol = "#4ade80" if th["mom"] > 1.5 else "#f87171" if th["mom"] < -1.5 else "#8fa0b5"
        return (f'<button class="thtile" style="background:{bg}" onclick="thDrill({i})" id="tht-{i}">'
                f'<span class="tht-n">{th["name"]}</span>'
                f'<span class="tht-m"><b>RS{rs:.0f}</b> <span style="color:{acol}">{arr}</span>'
                f'<span class="tht-c">{th["n"]}銘柄</span></span></button>')
    tiles = "".join(tile(i, th) for i, th in enumerate(themes))
    panels = ""
    for i, th in enumerate(themes):
        chips = "".join(
            f'<span class="thstk" data-tk="{x["t"]}" onclick="thStk(this)">'
            f'<b>{x["t"]}</b><span class="thstk-rs">RS{x["rs"]:.0f}</span>'
            f'<span class="thstk-m" style="color:{"#4ade80" if x["mom"]>1.5 else "#f87171" if x["mom"]<-1.5 else "#7d8da1"}">'
            f'{"▲" if x["mom"]>1.5 else "▼" if x["mom"]<-1.5 else "▬"}</span></span>'
            for x in th["members"][:24])
        more = f'<span class="thmore">+{len(th["members"])-24}銘柄</span>' if len(th["members"]) > 24 else ""
        panels += (f'<div class="thpanel" id="thp-{i}" style="display:none">'
                   f'<div class="thpanel-h">{th["name"]}・{th["n"]}銘柄 <span class="mut">（RS強い順・タップで詳細）</span></div>'
                   f'<div class="thstks">{chips}{more}</div></div>')
    return (f'<div class="card"><h2>テーマ・ドリルダウン</h2>'
            f'<div class="sub">中テーマの強さ順（緑=強い/濃さ=強度・▲=RSランク上昇中）。'
            f'<b>タップでその中の銘柄ローテ</b>（RS強い順）を表示。</div>'
            f'<div class="thgrid">{tiles}</div>{panels}</div>')

# equal-weight sector ETF RS — market-representative, unbiased, complete (11 GICS sectors)
SECTOR_ETFS = [("RSPT","情報技術"),("RSPF","金融"),("RSPN","資本財"),("RSPD","一般消費財"),
               ("RSPM","素材"),("RSPC","通信"),("RSPU","公益"),("RSPS","生活必需品"),
               ("RSPH","ヘルスケア"),("RSPR","不動産"),("RSPG","エネルギー")]

def build_sector_etf_rs(macro):
    recs = []
    rets63 = {}
    for tk, ja in SECTOR_ETFS:
        if tk not in macro:
            continue
        c = macro[tk]["Close"].dropna()
        if len(c) < 70:
            continue
        last = float(c.iloc[-1])
        def r(d):
            return (last/float(c.iloc[-d-1])-1) if len(c) > d else np.nan
        rets63[tk] = r(63)
        recs.append(dict(tk=tk, ja=ja, d1=r(1), w1=r(5), m1=r(21), r63=r(63)))
    if not recs:
        return []
    sr = pd.Series({x["tk"]: x["r63"] for x in recs}).rank(pct=True) * 100
    for x in recs:
        x["rs"] = float(sr[x["tk"]])
    recs.sort(key=lambda x: (-(x["r63"] if x["r63"] == x["r63"] else -9)))
    return recs

# 小分類（業種テーマETF）— sector_etf.csv から代表を厳選（重複テーマは1本に集約）
MICRO_ETFS = [("SMH","半導体"),("XSD","半導体EW"),("DRAM","メモリ"),("SOXX","半導体装置"),
              ("DTCR","データセンター"),("IGV","ソフトウェア"),("WCLD","クラウドSaaS"),("SKYY","クラウド基盤"),
              ("CIBR","サイバー"),("AIQ","AI"),("QTUM","量子・次世代"),("BOTZ","ロボティクス"),("ARKW","次世代ネット"),
              ("XBI","バイオテック"),("IHI","医療機器"),("PPH","製薬"),("GNOM","ゲノム"),
              ("KBE","銀行"),("KRE","地銀"),("IAI","証券・取引所"),("KIE","保険"),
              ("XOP","石油探査"),("OIH","油田サービス"),("XES","油田装置"),
              ("TAN","ソーラー"),("ICLN","クリーンEN"),("GRID","スマートグリッド"),("FAN","風力"),
              ("URA","ウラン"),("NLR","原子力"),("LIT","リチウム電池"),("HYDR","水素"),
              ("GDX","金鉱"),("SIL","銀鉱"),("COPX","銅鉱"),("XME","金属・鉱業"),("SLX","鉄鋼"),("REMX","レアアース"),
              ("ITA","航空宇宙・防衛"),("SHLD","防衛テック"),("XAR","宇宙・防衛"),
              ("JETS","航空"),("IYT","運輸"),("BOAT","海運"),
              ("XHB","住宅建設"),("PAVE","インフラ"),("PKB","建設"),
              ("XRT","小売"),("IBUY","EC"),("PEJ","レジャー"),
              ("BLOK","ブロックチェーン"),("WGMI","BTCマイニング"),("DRIV","EV・自動運転"),
              ("MOO","農業"),("PHO","水関連"),("WOOD","林業")]

# --- ETF(56) → 大分類(s2tの第1階層) の対応表 ---
#   【根拠】名前ではなく実データで決定（2026-07-08）:
#     ① 各ETFの実保有(yfinance top-holdings)を取り、保有銘柄がs2tでどの大分類に
#        属するかを保有比率で重み付き多数決 → 主信号（分類は「事業実体」で決まるため）
#     ② ETFの対SPY超過リターン と 各大分類の等加重超過リターン の日次相関(1年)
#        → 従信号。保有の大半がユニバース外(海外株)のETFで使用。
#     45/56で①②が一致。不一致12本は保有内訳を個別精査して確定（各行のコメント参照）。
#     相関はAI/石油ベータに汚染されるため、事業実体が明確な場合は①を優先した。
#   ドリルダウン: ETF → 大分類 → 詳細セクター(主導/改善を既定表示) → 構成銘柄。
ETF_TO_BIG = {
    "SMH": "2. 半導体・製造サプライチェーン",                               # 半導体: 保有59%+相関0.88
    "XSD": "2. 半導体・製造サプライチェーン",                               # 半導体EW: 保有43%+相関0.93
    "DRAM": "2. 半導体・製造サプライチェーン",                              # メモリ: 保有の大半が韓国メモリ半導体。詳細「メモリ/HBM」は2に所属
    "SOXX": "2. 半導体・製造サプライチェーン",                              # 半導体装置: 保有58%+相関0.91
    "DTCR": "14. 不動産・住宅・建設",                                  # データセンター: 保有: EQIX/DLR/AMT/CCI=DCリート37.6%。相関の半導体はAIベータ
    "IGV": "1. AI・テック成長テーマ",                                  # ソフトウェア: 保有51%+相関0.76
    "WCLD": "8. デジタルインフラ・先進テック",                              # クラウドSaaS: 保有55%+相関0.76
    "SKYY": "1. AI・テック成長テーマ",                                 # クラウド基盤: 保有89%+相関0.82
    "CIBR": "8. デジタルインフラ・先進テック",                              # サイバー: 保有88%+相関0.72
    "AIQ": "2. 半導体・製造サプライチェーン",                               # AI: 保有47%+相関0.68
    "QTUM": "2. 半導体・製造サプライチェーン",                              # 量子・次世代: 保有59%+相関0.86
    "BOTZ": "1. AI・テック成長テーマ",                                 # ロボティクス: 保有72%が日欧ロボ株。マッチ分の最大はNVDA=1。確度低
    "ARKW": "1. AI・テック成長テーマ",                                 # 次世代ネット: 保有: AMD/GOOG/AMZN/CRWV=19.5%が最大。相関のフィンテックはHOOD/CRCL由来
    "XBI": "6. バイオ・ヘルスケア",                                    # バイオテック: 保有100%+相関0.28
    "IHI": "15. ディフェンシブ（公益・通信・大手医薬）",                         # 医療機器: 保有: ABT/SYK/EW/BDX/MDT=医療機器大42.3% > バイオ32.3%
    "PPH": "6. バイオ・ヘルスケア",                                    # 製薬: 保有: 全マッチが大手製薬=6。相関のディフェンシブは性質ベータ
    "GNOM": "6. バイオ・ヘルスケア",                                   # ゲノム: 保有100%+相関0.46
    "KBE": "12. 金融・銀行・保険",                                    # 銀行: 保有100%+相関0.91
    "KRE": "12. 金融・銀行・保険",                                    # 地銀: 保有100%+相関0.89
    "IAI": "12. 金融・銀行・保険",                                    # 証券・取引所: 保有94%+相関0.48
    "KIE": "12. 金融・銀行・保険",                                    # 保険: 保有100%+相関0.74
    "XOP": "10. エネルギー（化石燃料）",                                 # 石油探査: 保有100%+相関0.94
    "OIH": "10. エネルギー（化石燃料）",                                 # 油田サービス: 保有85%+相関0.80
    "XES": "10. エネルギー（化石燃料）",                                 # 油田装置: 保有78%+相関0.81
    "TAN": "3. クリーンエネルギー・資源",                                 # ソーラー: 保有92%+相関0.77
    "ICLN": "3. クリーンエネルギー・資源",                                # クリーンEN: 保有100%+相関0.78
    "GRID": "1. AI・テック成長テーマ",                                 # スマートグリッド: 保有: ETN/PWR=AI DC電力装置16.6% > 産業13.5%
    "FAN": "3. クリーンエネルギー・資源",                                 # 風力: 相関0.32（保有95%が欧州風力でユニバース外）
    "URA": "4. 原子力・エネルギー代替",                                  # ウラン: 相関0.90（保有は海外株中心）
    "NLR": "4. 原子力・エネルギー代替",                                  # 原子力: 保有52%+相関0.90
    "LIT": "11. 素材・鉱業・化学",                                    # リチウム電池: 保有84%+相関0.58
    "HYDR": "3. クリーンエネルギー・資源",                                # 水素: 保有100%+相関0.68
    "GDX": "11. 素材・鉱業・化学",                                    # 金鉱: 相関0.80（保有は海外鉱山）
    "SIL": "11. 素材・鉱業・化学",                                    # 銀鉱: 相関0.81（同）
    "COPX": "11. 素材・鉱業・化学",                                   # 銅鉱: 相関0.73（同）
    "XME": "11. 素材・鉱業・化学",                                    # 金属・鉱業: 保有78%+相関0.82
    "SLX": "11. 素材・鉱業・化学",                                    # 鉄鋼: 保有100%+相関0.70
    "REMX": "11. 素材・鉱業・化学",                                   # レアアース: 相関0.65（同）
    "ITA": "5. 宇宙・防衛・モビリティ",                                  # 航空宇宙・防衛: 保有70%+相関0.58
    "SHLD": "5. 宇宙・防衛・モビリティ",                                 # 防衛テック: 保有84%+相関0.54
    "XAR": "5. 宇宙・防衛・モビリティ",                                  # 宇宙・防衛: 保有78%+相関0.84
    "JETS": "9. 消費者・小売りテーマ",                                  # 航空: 保有100%+相関0.55
    "IYT": "13. 産業・資本財・輸送",                                   # 運輸: 保有60%+相関0.66
    "BOAT": "13. 産業・資本財・輸送",                                  # 海運: 保有: FRO/MATX/INSW=全て「海運」。相関の石油はタンカー由来
    "XHB": "14. 不動産・住宅・建設",                                   # 住宅建設: 保有81%+相関0.74
    "PAVE": "13. 産業・資本財・輸送",                                  # インフラ: 保有68%+相関0.79
    "PKB": "13. 産業・資本財・輸送",                                   # 建設: 保有ほぼ拮抗(11:14.5/13:13.9)を相関0.70が13へ決定
    "XRT": "9. 消費者・小売りテーマ",                                   # 小売: 保有89%+相関0.83
    "IBUY": "9. 消費者・小売りテーマ",                                  # EC: 保有69%+相関0.62
    "PEJ": "9. 消費者・小売りテーマ",                                   # レジャー: 保有100%+相関0.79
    "BLOK": "7. フィンテック・デジタル金融",                               # ブロックチェーン: 保有61%+相関0.79
    "WGMI": "7. フィンテック・デジタル金融",                               # BTCマイニング: 保有100%+相関0.63
    "DRIV": "2. 半導体・製造サプライチェーン",                              # EV・自動運転: 保有41%+相関0.80
    "MOO": "11. 素材・鉱業・化学",                                    # 農業: 保有: CTVA+CF=農業化学13.1%（9.消費者13.0%と僅差）
    "PHO": "13. 産業・資本財・輸送",                                   # 水関連: 保有36%+相関0.74
    "WOOD": "11. 素材・鉱業・化学",                                   # 林業: 保有: SW/IP=パッケージング11.1% > 不動産8.0%
}


# RRG用の厳選テーマ（読みやすさ優先で16本・半導体は特別マーカー）
RRG_THEMES = [("SMH","半導体"),("SOXX","半導体装置"),("DTCR","データセンター"),
              ("IGV","ソフトウェア"),("CIBR","サイバー"),("AIQ","AI"),
              ("XBI","バイオテック"),("IHI","医療機器"),
              ("KBE","銀行"),("IAI","証券"),
              ("XOP","石油探査"),("OIH","油田"),
              ("GDX","金鉱"),("XME","金属"),("URA","ウラン"),
              ("ITA","防衛"),("PAVE","インフラ"),("IYT","運輸")]

def load_market_extras(period="9mo", asof_date=None):
    """小分類テーマETF + QQQE + ^VIX6M をライブ取得（macroキャッシュとは独立・失敗時は空dict）。
       返り値: {ticker: Close系列}。--selftest(オフライン)時はネット取得せず空dictを返す。
       #7 asof_date指定時は取得系列を index<=asof で切り、過去as-of分析に現在のライブ値を混ぜない。"""
    tks = [t for t, _ in MICRO_ETFS] + ["QQQE", "^VIX6M"]
    out = {}
    if not _net_ok():
        return out
    _cut = pd.Timestamp(asof_date) if asof_date is not None else None
    try:
        import yfinance as yf, warnings as _w
        _w.filterwarnings("ignore")
        df = yf.download(tks, period=period, interval="1d", progress=False, threads=True)
        if df is None or getattr(df, "empty", True):
            return out
        cl = df["Close"] if isinstance(df.columns, pd.MultiIndex) and "Close" in df.columns.get_level_values(0) else df
        for t in tks:
            try:
                s = cl[t].dropna() if hasattr(cl, "columns") and t in cl.columns else None
                if s is not None and _cut is not None:
                    try: s = s[pd.to_datetime(s.index) <= _cut]      # #7 as-ofより後のバーを落とす
                    except Exception: pass
                if s is not None and len(s) >= 22:
                    out[t] = s
            except Exception:
                pass
    except Exception as e:
        sys.stderr.write(f"[extras] fetch failed: {e}\n")
    return out

def _rank_etfs(close_dict, etf_list, minbars=22):
    """{tk: Close系列} と [(tk,ja)] から d1/w1/m1 と 63/126/189日リターンを計算した recs を返す。"""
    recs = []
    for tk, ja in etf_list:
        c = close_dict.get(tk)
        if c is None:
            continue
        c = c.dropna()
        if len(c) < minbars:
            continue
        last = float(c.iloc[-1])
        def r(d):
            return (last/float(c.iloc[-d-1]) - 1) if len(c) > d else np.nan
        recs.append(dict(tk=tk, ja=ja, d1=r(1), w1=r(5), m1=r(21),
                         ret63=r(63), ret126=r(126), ret189=r(189)))
    return recs

def build_sector_ranks(macro, extras):
    """大分類(11セクター・等ウェイトRSP*=キャッシュ) と 小分類(テーマ=ライブextras) の d1/w1/m1。"""
    macro_close = {tk: macro[tk]["Close"] for tk, _ in SECTOR_ETFS if tk in macro}
    return {"macro": _rank_etfs(macro_close, SECTOR_ETFS),
            "micro": _rank_etfs(extras, MICRO_ETFS)}

# ----------------------------------------------------------------------------- breadth + yields
def build_breadth(m):
    """分母は「そのMAを算出できた銘柄」だけ。IPO等でsma200がNaNの銘柄を分母に含めると
       (NaN比較はFalse) 200日線上比率が構造的に過小になるため。
       全銘柄欠損などで分母0のときは0%でなくNone（下流で「—」表示）にしてデータ障害を隠さない。"""
    n = len(m)
    v200 = m["sma200"].notna(); n200 = int(v200.sum())
    v50  = m["sma50"].notna();  n50  = int(v50.sum())
    a200 = int((m.loc[v200, "close"] > m.loc[v200, "sma200"]).sum())
    a50  = int((m.loc[v50,  "close"] > m.loc[v50,  "sma50"]).sum())
    _vc  = m["pchg"].notna()
    adv  = int((m.loc[_vc, "pchg"] > 0).sum())
    dec  = int((m.loc[_vc, "pchg"] < 0).sum())
    unch = int((m.loc[_vc, "pchg"] == 0).sum())
    _addn = adv + dec                                  # 変わらず(unch)は分母に入れない（=上昇/下落の比率）
    v52  = m["dist52"].notna(); n52 = int(v52.sum())
    nh   = int((m.loc[v52, "dist52"] >= -0.005).sum())
    return dict(n=int(n), n200=n200, n50=n50,
                pa200=(100*a200/n200 if n200 > 0 else None),
                pa50=(100*a50/n50 if n50 > 0 else None),
                adv=int(adv), dec=int(dec), unch=int(unch),
                adpct=(100*adv/_addn if _addn > 0 else None),
                nh=int(nh), pnh=(100*nh/n52 if n52 > 0 else None))

def build_yields(macro):
    """（旧・互換用）yfinance ^TNX/^FVX/^TYX の水準。現在は金利カードには使わず、
       DIAGとフォールバック表示のためだけに残す。金利カード本体は build_rates_card()。"""
    out = {}
    for tk, lab in [("^TNX", "米10年名目"), ("^FVX", "米5年"), ("^TYX", "米30年")]:
        if tk in macro:
            c = macro[tk]["Close"].dropna()
            if len(c) >= 2:
                out[lab] = dict(y=float(c.iloc[-1]), chg=float(c.iloc[-1] - c.iloc[-2]))
    return out

# ============================================================================
#  FRED macro-context layer (第1段階: 金利カード)
#  取得優先順位: ① FRED_API_KEY 経由の公式API → ② 無鍵CSV → ③ 前回成功キャッシュ → ④ 欠損表示
#  ・複数系列は1呼び出しにまとめず順次だが、成功値は日付付きでキャッシュし失敗時に退避。
#  ・yfinance系macroとは完全分離（confirmed-session cut には混ぜない）。
#  ・FRED取得失敗でHTML生成は絶対に止めない。
# ============================================================================
FRED_SERIES = {
    "DGS2":   "米2年金利",
    "DFII10": "米10年実質金利",
    "T10YIE": "10年期待インフレ",
    "T10Y2Y": "10年−2年スプレッド",
    "DGS10":  "米10年名目",        # T10Y2Y欠損時の代替計算用
    "DGS3MO": "米3ヶ月金利",        # 金利チャートの3M線用
}

# 第2段階 マクロ圧力パネル用のFRED系列（金利カードとは別セット）。
#   BAMLH0A0HYM2=HYオプション調整後スプレッド(日次) / DTWEXBGS=広義ドル指数(日次) / NFCI=金融環境(週次)
FRED_PRESSURE_SERIES = {
    "BAMLH0A0HYM2": "HY OAS",
    "DTWEXBGS":     "広義ドル指数",
    "NFCI":         "金融環境指数",
}
# 1回の取得予算を金利＋圧力系列で共有する。別々に呼ぶと50秒×2になり、
# 「FRED全体50秒」のつもりでも最大100秒超まで膨らむため。
FRED_ALL_SERIES = {**FRED_SERIES, **FRED_PRESSURE_SERIES}

# 第3段階: ネット流動性（WALCL−RRP−TGA）と週末マクロ（マーケット/ウィークリータブ用）。
#   ネット流動性はリスク資産ベータと相関の高い本命指標。バランスシート単体より地合い判断に効く。
FRED_LIQUIDITY_SERIES = {
    "WALCL":     "FRB総資産",        # 百万ドル
    "RRPONTSYD": "リバースレポ",      # 十億ドル
    "WTREGEN":   "TGA(財務省勘定)",   # 十億ドル
}
FRED_WEEKLY_SERIES = {
    "T10Y3M":     "10年−3ヶ月",        # 景気後退シグナル(誤爆少)
    "BAMLC0A0CM": "IG OAS",           # 投資適格クレジット
    "T5YIFR":     "5年5年先期待ｲﾝﾌﾚ",  # 長期インフレ織り込み
    "ICSA":       "新規失業保険",       # 週次・労働の亀裂
    "CCSA":       "継続失業保険",       # 週次
    "SOFR":       "SOFR",             # 資金調達ストレス
}
FRED_ALL_SERIES = {**FRED_ALL_SERIES, **FRED_LIQUIDITY_SERIES, **FRED_WEEKLY_SERIES}

def _fred_cache_path():
    return os.environ.get("V38_FRED_CACHE") or os.path.join(os.path.dirname(CACHE), "fred_cache.json")

def _fred_load_cache():
    try:
        _c = json.load(open(_fred_cache_path()))
    except Exception:
        return {}
    if not isinstance(_c, dict):        # #6 FREDは再取得可能。トップレベルが非dictなら{}にリセット（AttributeError回避）
        sys.stderr.write(f"[fred] cache is not a dict; resetting to empty: {_fred_cache_path()}\n")
        return {}
    return _c

def _fred_save_cache(cache):
    _defer_cache_write(_fred_cache_path(), cache)   # #6 保留→selftest後にflush
    if True:
        return
    try:
        atomic_write_json(_fred_cache_path(), cache)
    except Exception:
        pass

def _fred_parse_csv(text, sid):
    import io as _io
    rows = [r for r in csv.reader(_io.StringIO(text)) if r]
    if not rows:
        return []
    # 列名は 'observation_date','<SID>' 想定だが順番だけで拾う
    out = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in ("", ".", "NaN", "nan"):
            try:
                out.append((r[0], float(r[1])))
            except Exception:
                continue
    return out

def _fred_fetch_one(sid, api_key=None, timeout=9, start=None, retry=True, deadline=None):
    """1系列を取得。(観測日,値)昇順リストと取得元を (vals, src) で返す。失敗時 (None, None)。
       src ∈ 'api'/'csv'。タイムアウトは短め、503/429はretry=Trueのとき1回だけ2.5秒後にリトライ。
       --selftest(オフライン)時はネット取得せず (None,None)。※selftestのFRED機能テストは本関数を差し替えるので影響なし。"""
    if not _net_ok():
        return (None, None)
    import urllib.request, urllib.parse, urllib.error
    start = start or (dt.date.today() - dt.timedelta(days=800)).isoformat()

    def _remaining_timeout():
        if deadline is None:
            return float(timeout)
        remain = float(deadline - time.monotonic())
        if remain <= 0.25:
            raise TimeoutError("FRED overall time budget exhausted")
        return max(0.25, min(float(timeout), remain))

    def _try(url, hdr):
        tries = 2 if retry else 1
        for attempt in range(tries):
            try:
                return urllib.request.urlopen(
                    urllib.request.Request(url, headers=hdr),
                    timeout=_remaining_timeout(),
                ).read()
            except urllib.error.HTTPError as he:
                if he.code in (429, 503) and attempt < tries - 1:
                    if deadline is not None:
                        remain = deadline - time.monotonic()
                        if remain <= 0.25:
                            raise TimeoutError("FRED overall time budget exhausted")
                        time.sleep(min(2.5, max(0.0, remain - 0.25)))
                    else:
                        time.sleep(2.5)
                    continue
                raise
        return None

    # ① 公式API（キーがあれば本線）
    if api_key:
        try:
            q = urllib.parse.urlencode(dict(series_id=sid, api_key=api_key, file_type="json",
                                            observation_start=start))
            raw = _try(f"https://api.stlouisfed.org/fred/series/observations?{q}", {"User-Agent": "v38/1.0"})
            if raw:
                obs = json.loads(raw).get("observations", [])
                out = [(o["date"], float(o["value"])) for o in obs if o.get("value") not in ("", ".", None)]
                if out:
                    return out, "api"
        except Exception as e:
            sys.stderr.write(f"[fred] API失敗 {sid}: {repr(e)[:70]}\n")
    # ② 無鍵CSV（予備）
    try:
        url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
               f"&cosd={start}")
        raw = _try(url, {"User-Agent": "Mozilla/5.0"})
        if raw:
            out = _fred_parse_csv(raw.decode(), sid)
            if out:
                return out, "csv"
    except Exception as e:
        sys.stderr.write(f"[fred] CSV失敗 {sid}: {repr(e)[:70]}\n")
    return None, None

def fetch_fred_context(series=FRED_SERIES, history_days=800, time_budget=50.0, persist_cache=True):
    """FRED系列をまとめて取得し macro_context を返す。
       各系列: {vals, last_date, last, src, cached_at}。src ∈ api/csv/cache/none。
       ・同日取得済みキャッシュがあればネットワークに行かない（当日再実行の高速化）。
       ・②CSV/①APIの取得元は _fred_fetch_one が返す src をそのまま使う（api誤表示を防ぐ）。
       ・③キャッシュ利用時は cached_at を上書きしない（古い取得日を保持）。
       ・DGS10 は T10Y2Y が取れた場合は取得を省略（無駄打ち削減）。
       ・history_days: 取得開始日（%ile窓より長く。圧力系列は3年%ileのため1200日）。
       ・time_budget: FRED全体の時間上限(秒)。超過したら残り系列はネットワークに行かず
         キャッシュへ直行（冷間実行×FRED障害でHTML生成が数分止まるのを防ぐ）。"""
    api_key = os.environ.get("FRED_API_KEY") or None
    cache = _fred_load_cache()
    today = str(dt.date.today())
    start_iso = (dt.date.today() - dt.timedelta(days=history_days)).isoformat()
    t0 = time.monotonic()
    deadline = t0 + max(0.0, float(time_budget))
    budget_hit = False
    ctx = {}
    _t10y2y_ok = False
    for i, (sid, lab) in enumerate(series.items()):
        # DGS10 は 2s10s が取れているならスキップ（代替計算が不要）
        if sid == "DGS10" and _t10y2y_ok:
            cv = cache.get(sid) or {}
            ctx[sid] = dict(lab=lab, vals=[(d, v) for d, v in (cv.get("vals") or [])],
                            last_date=cv.get("last_date"), last=cv.get("last"),
                            src=("cache" if cv.get("vals") else "none"),
                            cached_at=cv.get("cached_at"))
            continue
        cv = cache.get(sid) or {}
        # 同日キャッシュが新鮮ならネットワークを省略
        if cv.get("cached_at") == today and cv.get("vals"):
            vals, src, cached_at = [(d, v) for d, v in cv["vals"]], "csv", cv.get("cached_at")
            # 当日キャッシュ由来は取得元を api/csv どちらか判別できないため、保存済み src を尊重
            src = cv.get("src", src)
        elif time.monotonic() >= deadline:             # ★時間上限超過→残りはキャッシュ直行
            if not budget_hit:
                sys.stderr.write(f"[fred] 時間上限{time_budget:.0f}s超過→残り系列はキャッシュ退避\n")
                budget_hit = True
            vals, src, cached_at = (([(d, v) for d, v in cv["vals"]], "cache", cv.get("cached_at"))
                                    if cv.get("vals") else (None, "none", None))
        else:
            # 残り予算が少ない時はリトライを省いて素早く諦める
            _left = deadline - time.monotonic()
            vals, src = _fred_fetch_one(
                sid, api_key=api_key, start=start_iso,
                timeout=min(9.0, max(0.25, _left)),
                retry=(_left > 25), deadline=deadline,
            )
            cached_at = today if src in ("api", "csv") else None
            if vals is None:                          # 取得失敗 → 前回成功キャッシュへ退避
                if cv.get("vals"):
                    vals = [(d, v) for d, v in cv["vals"]]
                    src = "cache"
                    cached_at = cv.get("cached_at")    # ★上書きしない（古い取得日を保持）
                    sys.stderr.write(f"[fred] {sid} キャッシュ退避 (取得日 {cached_at})\n")
        if vals:
            if src in ("api", "csv"):                  # ★新規取得成功時だけキャッシュ更新
                cache[sid] = dict(vals=vals[-900:], cached_at=today, src=src,
                                  last_date=vals[-1][0], last=vals[-1][1])
            ctx[sid] = dict(lab=lab, vals=vals[-920:], last_date=vals[-1][0],
                            last=vals[-1][1], src=src, cached_at=cached_at)
            if sid == "T10Y2Y":
                _t10y2y_ok = True
            if src in ("api", "csv") and i < len(series) - 1:
                _nap = min(0.5, max(0.0, deadline - time.monotonic()))
                if _nap > 0:
                    time.sleep(_nap)   # 実際にネットワークへ行った時だけ間隔を空ける
        else:
            ctx[sid] = dict(lab=lab, vals=[], last_date=None, last=None, src="none", cached_at=None)
    if persist_cache:
        _fred_save_cache(cache)
    return ctx

def _fred_metrics(vals, last_date, asof=None):
    """(水準, 20営業日変化[生], 1年パーセンタイル, 更新経過日数, 有効観測日) を返す。欠損は None。
       ★asof(=株価の確定営業日)より後のFRED観測は使わない。株式指標が6月末なのに
         金利だけ7月最新、という時間ズレ（未来データを本日扱い）を構造的に防ぐ。"""
    if not vals:
        return None, None, None, None, last_date
    if asof is not None:
        try:
            cutoff = pd.Timestamp(asof).date()
            vals = [(d, v) for d, v in vals if pd.Timestamp(d).date() <= cutoff]
        except Exception:
            pass
        if not vals:
            return None, None, None, None, None
    last_date = vals[-1][0]
    xs = [v for _, v in vals]
    lvl = xs[-1]
    chg20 = (xs[-1] - xs[-21]) if len(xs) >= 21 else None
    # 1年パーセンタイルも短尺キャッシュを「1年」と偽らない。
    latest = pd.Timestamp(last_date)
    start_1y = latest - pd.DateOffset(years=1)
    win_pairs = [(pd.Timestamp(d), v) for d, v in vals if pd.Timestamp(d) >= start_1y]
    win = [v for _, v in win_pairs]
    oldest = min((pd.Timestamp(d) for d, _ in vals), default=latest)
    has_1y_coverage = oldest <= (start_1y + pd.Timedelta(days=30))
    pct = (sum(1 for x in win if x <= lvl) / len(win) * 100) if (len(win) >= 30 and has_1y_coverage) else None
    stale = None
    if last_date:
        try:
            ref = pd.Timestamp(asof).date() if asof else dt.date.today()
            stale = max(0, int(np.busday_count(pd.Timestamp(last_date).date(), ref)))
        except Exception:
            stale = None
    return lvl, chg20, pct, stale, last_date

def _change_percentile(vals, current_change, asof=None, bdays=20, years=3, min_obs=30):
    """日次・週次を問わず暦日ベースで同じ営業日幅の変化分布を作る。"""
    if current_change is None or not vals: return None
    try:
        ser=pd.Series({pd.Timestamp(d):float(v) for d,v in vals}).sort_index()
        if asof is not None: ser=ser[ser.index<=pd.Timestamp(asof)]
        if ser.empty: return None
        start=ser.index[-1]-pd.DateOffset(years=years)
        changes=[]
        for d,v in ser.loc[start:].items():
            past=ser.loc[:d-pd.offsets.BDay(bdays)]
            if len(past): changes.append(float(v-past.iloc[-1]))
        if len(changes)<min_obs: return None
        return sum(x<=current_change for x in changes)/len(changes)*100.0
    except Exception:
        return None

def build_rates_card(ctx, asof=None):
    def _bp(x): return None if x is None else x*100.0
    # risk_high: 値が高いほど株に逆風か。カーブは低い/逆転ほど警戒なのでFalse
    rows_def=[("DGS2","政策期待","米2年金利","%",False,True),("DFII10","成長株の割引率","米10年実質金利","%",True,True),
              ("T10YIE","インフレ期待","10年期待インフレ","%",False,True),("T10Y2Y","イールドカーブ","10年−2年","pt",False,False)]
    cells=[]
    for sid,cat,lab,unit,colored,risk_high in rows_def:
        d=ctx.get(sid,{}); vals=d.get("vals") or []; ld=d.get("last_date"); src=d.get("src","none"); cached_at=d.get("cached_at"); alt=""
        if sid=="T10Y2Y" and not vals:
            g10,g2=ctx.get("DGS10",{}),ctx.get("DGS2",{})
            if g10.get("vals") and g2.get("vals"):
                m10,m2=dict(g10["vals"]),dict(g2["vals"]); common=sorted(set(m10)&set(m2))
                if common: vals=[(dd,m10[dd]-m2[dd]) for dd in common]; ld=common[-1]; alt="（代替）"; src=g10.get("src",src)
        lvl,chg20,pct,stale,eff_ld=_fred_metrics(vals,ld,asof)
        spd=_change_percentile(vals,chg20,asof=asof,bdays=20,years=3)
        if lvl is None:
            cells.append(f'<div class="rrow"><div class="lft"><div class="nm">{lab}</div><div class="cat">{cat}</div></div><div class="rgt"><span class="na">—</span></div><div class="foot">未取得</div></div>'); continue
        chg=_bp(chg20); chg_txt="—" if chg is None else f'{chg:+.0f}bp'; chg_cls=("neg" if chg>0 else "pos" if chg<0 else "mut") if colored and chg is not None else "mut"
        pct_txt="—" if pct is None else f'{pct:.0f}%'; src_lab={"api":"API","csv":"CSV","cache":"前回値","none":"—"}.get(src,src)
        stale_txt="" if stale is None else (f'・{stale}営業日前' if stale>0 else "・本日"); cache_txt=f'・取得 {cached_at}' if src=="cache" and cached_at else ""
        speed_txt=f'・変化 {spd:.0f}%' if spd is not None else ''
        # 直近5営業日の変化（20日変化と方向が食い違う時に投稿で過大表現しないための補足）
        chg5_txt=""
        try:
            _ys=[float(v) for _,v in vals if v==v]
            if len(_ys)>=6:
                _c5=(_ys[-1]-_ys[-6])*(100.0 if unit=="%" else 1.0)
                _c5cls=("neg" if _c5>0 else "pos" if _c5<0 else "mut") if colored else "mut"
                _div=" *" if (chg is not None and abs(chg)>1e-9 and (_c5>0)!=(chg>0) and abs(_c5)>0.5) else ""
                chg5_txt=f'・<span class="{_c5cls}">直近5日 {_c5:+.0f}bp{_div}</span>'
        except Exception:
            chg5_txt=""
        badge=_alert_badge(pct, risk_high)
        sp=_spark(vals, asof)
        cells.append(f'<div class="rrow"><div class="lft"><div class="nm">{lab}{alt}{badge}</div><div class="cat">{cat}</div></div>'
                     f'<div class="rgt"><span class="big">{lvl:.2f}{"%" if unit=="%" else ""}</span><span class="chg {chg_cls}">{chg_txt}<span class="mut">/20日</span></span></div>'
                     f'<div class="hint">水準 {pct_txt}{speed_txt}{chg5_txt}</div>{sp}<div class="foot">観測 {eff_ld or "—"}{stale_txt}・{src_lab}{cache_txt}</div></div>')
    return '<div class="card"><h2>金利レジーム <span class="h2en">Rates</span></h2><div class="sub">10年実質金利を中心に、20日変化と<b>直近5日</b>の方向・現在位置を確認（* =20日と逆方向）。</div><div class="rgrid">'+''.join(cells)+'</div></div>'

def build_rates_insight(fred_ctx, asof=None):
    """実質金利×HY OASの月末観測別にQQQの21営業日先を集計する。--selftest(オフライン)時はNone。"""
    if not _net_ok():
        return None
    try:
        cache=_fred_load_cache(); today=dt.date.today(); long_vals={}
        for sid in ("DFII10","BAMLH0A0HYM2"):
            key="LONG:"+sid; cv=cache.get(key) or {}; use_cache=False
            if cv.get("vals"):
                try: use_cache=(today-pd.Timestamp(cv.get("cached_at")).date()).days<=7
                except Exception: use_cache=True
            if use_cache: long_vals[sid]=cv["vals"]; continue
            vals,_src=_fred_fetch_one(sid,api_key=os.environ.get("FRED_API_KEY") or None,start="2003-01-01",timeout=8,retry=False,deadline=time.monotonic()+12)
            if vals: cache[key]=dict(vals=vals,cached_at=today.isoformat()); long_vals[sid]=vals
            elif cv.get("vals"): long_vals[sid]=cv["vals"]
        qcv=cache.get("LONG:QQQ") or {}; q=None
        if qcv.get("vals"):
            try:
                q=pd.Series({pd.Timestamp(d):float(v) for d,v in qcv["vals"]}).sort_index()
                fresh=(today-pd.Timestamp(qcv.get("cached_at")).date()).days<=7
            except Exception: q=None; fresh=False
        else: fresh=False
        if q is None or not fresh:
            try:
                import yfinance as yf
                qq=yf.download("QQQ",start="2003-01-01",progress=False,auto_adjust=True)["Close"].squeeze()
                qq.index=pd.to_datetime(qq.index).tz_localize(None); q=qq.dropna().astype(float)
                cache["LONG:QQQ"]=dict(vals=[(str(i.date()),float(v)) for i,v in q.items()],cached_at=today.isoformat())
            except Exception: pass
        _fred_save_cache(cache)
        if not long_vals.get("DFII10") or not long_vals.get("BAMLH0A0HYM2") or q is None or len(q)<500: return ""
        real=pd.Series({pd.Timestamp(d):v for d,v in long_vals["DFII10"]}).sort_index(); oas=pd.Series({pd.Timestamp(d):v for d,v in long_vals["BAMLH0A0HYM2"]}).sort_index()
        if asof is not None:
            cut=pd.Timestamp(asof); q=q[q.index<=cut]; real=real[real.index<=cut]; oas=oas[oas.index<=cut]
        df=pd.DataFrame({"q":q}).join(real.rename("r"),how="left").join(oas.rename("o"),how="left").ffill().dropna()
        df["dr"]=(df["r"]-df["r"].shift(20))*100; df["do"]=(df["o"]-df["o"].shift(20))*100; df["fwd"]=df["q"].shift(-21)/df["q"]-1
        # 21営業日先を評価 → 21営業日間隔で観測（重複カウントを避ける。週次化はnの水増しになるため不採用）
        hist=df.dropna(subset=["dr","do","fwd"]).iloc[::21]
        def _wilson(k,n,z=1.96):
            if n==0: return (0.0,0.0)
            p=k/n; d=1+z*z/n; c=(p+z*z/(2*n))/d; h=z*((p*(1-p)/n+z*z/(4*n*n))**0.5)/d
            return ((c-h)*100,(c+h)*100)
        cells={}
        for rn,rc in (("実質金利↑",hist.dr>0),("実質金利↓",hist.dr<=0)):
            for on,oc in (("OAS拡大",hist.do>0),("OAS縮小",hist.do<=0)):
                seg=hist.loc[rc&oc,"fwd"]
                if len(seg)>=30:
                    wins=int((seg>0).sum()); lo,hi=_wilson(wins,len(seg))
                    cells[(rn,on)]=(float(seg.median())*100,wins/len(seg)*100,len(seg),lo,hi)
                else:
                    cells[(rn,on)]=None
        cur=("実質金利↑" if df.dr.iloc[-1]>0 else "実質金利↓","OAS拡大" if df.do.iloc[-1]>0 else "OAS縮小")
        st=cells.get(cur)
        if st is None:
            return ""
        med,win,n,lo,hi=st; mcls="pos" if med>0 else "neg"
        cur_html=('<div style="border:1.5px solid #38bdf8;background:rgba(56,189,248,.07);border-radius:12px;padding:12px 14px">'
                  f'<div style="font-size:12px;color:#94a3b8">現在の環境：<b style="color:#cbd5e1">{cur[0]} \u00d7 {cur[1]}</b></div>'
                  f'<div style="margin-top:4px"><span class="{mcls}" style="font-size:24px;font-weight:800">{med:+.1f}%</span>'
                  '<span class="mut" style="font-size:12px">\u300021\u55b6\u696d\u65e5\u5148QQQ\u30fb\u4e2d\u592e\u5024</span></div>'
                  f'<div class="mut" style="font-size:12px;margin-top:2px">\u52dd\u7387 {win:.0f}%\uff0895%\u533a\u9593 {lo:.0f}\u301c{hi:.0f}%\uff09\u30fbn={n}</div></div>')
        others=[]
        for rn in ("実質金利↑","実質金利↓"):
            for on in ("OAS拡大","OAS縮小"):
                if (rn,on)==cur: continue
                stx=cells.get((rn,on))
                if stx is None:
                    b2='<span class="mut">n\u4e0d\u8db3</span>'
                else:
                    m2,w2,n2,_,_=stx; b2=f'<span class="{"pos" if m2>0 else "neg"}" style="font-weight:700">{m2:+.1f}%</span><span class="mut" style="font-size:10px">\u3000\u52dd\u7387{w2:.0f}%\u30fbn={n2}</span>'
                others.append(f'<div style="display:flex;justify-content:space-between;padding:6px 2px;border-bottom:1px solid rgba(255,255,255,.05)"><span style="font-size:11px;color:#94a3b8">{rn} \u00d7 {on}</span><span>{b2}</span></div>')
        start=hist.index[0].strftime("%Y-%m"); end=hist.index[-1].strftime("%Y-%m")
        return ('<div class="card"><h2>\u91d1\u5229\u00d7\u4fe1\u7528 <span class="h2en">Rates \u00d7 Credit</span></h2>'
                '<div class="sub mut">\u5b9f\u8cea\u91d1\u5229\u3068HY OAS\u306e20\u65e5\u5909\u5316\u306e\u7d44\u5408\u305b\u5225\u306b\u3001QQQ\u306e21\u55b6\u696d\u65e5\u5148\u30ea\u30bf\u30fc\u30f3\u3092\u5b9f\u6e2c\uff0821\u55b6\u696d\u65e5\u9593\u9694\u30fb\u91cd\u8907\u306a\u3057\uff09\u3002\u58f2\u8cb7\u306b\u306f\u63a5\u7d9a\u3057\u306a\u3044\u6587\u8108\u60c5\u5831\u3002</div>'
                f'{cur_html}'
                '<details style="margin-top:8px"><summary class="mut" style="font-size:11px;cursor:pointer">\u4ed6\u306e3\u74b0\u5883\u306e\u5b9f\u6e2c\u5024\u3092\u898b\u308b</summary>'
                f'<div style="margin-top:6px">{"".join(others)}</div></details>'
                f'<div class="rmeta mut" style="margin-top:6px">{start}\u301c{end}\u30fbn={len(hist):,}\uff0821\u55b6\u696d\u65e5\u9593\u9694\u306e\u72ec\u7acb\u89b3\u6e2c\uff09</div></div>')
    except Exception as e:
        sys.stderr.write("[rates_insight] %r\n" % repr(e)[:100]); return ""

def _bondvol_from_macro(macro):
    """MOVE代替: 債券ボラを ^MOVE → TLT20日実現ボラ → なし の順で用意。
       戻り値 (vals=[(date,val)...], src, unit)。src ∈ 'MOVE'/'TLT実現ボラ'/'none'。
       ★DTWEXBGSとDXYを混同しないのと同様、MOVEとTLT実現ボラは別物なので unit/src で明示。"""
    d = macro.get("^MOVE")
    if d is not None:
        c = d["Close"].dropna()
        if len(c) >= 30:
            vals = [(idx.strftime("%Y-%m-%d"), float(v)) for idx, v in c.items()]
            return vals, "MOVE", "指数"
    d = macro.get("TLT")
    if d is not None:
        c = d["Close"].dropna()
        if len(c) >= 30:
            ret = c.pct_change(fill_method=None)
            rv = ret.rolling(20).std() * (252 ** 0.5) * 100.0     # 年率換算・%
            rv = rv.dropna()
            if len(rv) >= 20:
                vals = [(idx.strftime("%Y-%m-%d"), float(v)) for idx, v in rv.items()]
                return vals, "TLT実現ボラ", "%(年率)"
    return [], "none", ""

def _dollar_from_macro_or_fred(fred_ctx, macro):
    """ドル: FRED DTWEXBGS(広義ドル・日次) を第一候補。取れなければ yfinance DX-Y.NYB(DXY・日次)。
       ★DTWEXBGSとDXYは構成が違う別指標なので、src/labを分けて名称を混同させない。"""
    d = (fred_ctx or {}).get("DTWEXBGS", {})
    if d.get("vals"):
        return d["vals"], "DTWEXBGS（広義ドル・日次）", d.get("last_date"), d.get("src"), d.get("cached_at")
    dxy = macro.get("DX-Y.NYB")
    if dxy is not None:
        c = dxy["Close"].dropna()
        if len(c) >= 30:
            vals = [(idx.strftime("%Y-%m-%d"), float(v)) for idx, v in c.items()]
            return vals, "DXY（ドル指数・日次・別系列）", vals[-1][0], "yf", None
    return [], "ドル指数（未取得）", None, "none", None

def _pressure_metrics(vals, last_date, asof=None):
    """圧力パネル1指標の (水準, 20営業日変化[生], 3年%ile, 経過日数, 有効観測日)。
       asof以前に切る（週次系列でも未来を本日扱いしない）。
       ★変化・%ileは観測数ではなく【日付】で切る。週次系列(NFCI等)で
         xs[-21] を使うと「20日」表示なのに実際は20週(≈140日)前比較になるため。"""
    if not vals:
        return None, None, None, None, last_date
    if asof is not None:
        try:
            cutoff = pd.Timestamp(asof).date()
            vals = [(d, v) for d, v in vals if pd.Timestamp(d).date() <= cutoff]
        except Exception:
            pass
        if not vals:
            return None, None, None, None, None
    last_date = vals[-1][0]
    lvl = vals[-1][1]
    latest = pd.Timestamp(last_date)
    # 20営業日変化: 「最新日−20営業日」以前で最も新しい観測と比較（週次でも正しい期間）
    target_20d = latest - pd.offsets.BDay(20)
    past = [v for d, v in vals if pd.Timestamp(d) <= target_20d]
    chg20 = (lvl - past[-1]) if past else None
    # 3年パーセンタイル: 日付で3年窓を切る（週次なら約156観測、日次なら約756観測）。
    # 古い短尺キャッシュを使った際に、1～2年しかないのに「3年%ile」と表示しない。
    start_3y = latest - pd.DateOffset(years=3)
    win_pairs = [(pd.Timestamp(d), v) for d, v in vals if pd.Timestamp(d) >= start_3y]
    win = [v for _, v in win_pairs]
    oldest = min((pd.Timestamp(d) for d, _ in vals), default=latest)
    has_3y_coverage = oldest <= (start_3y + pd.Timedelta(days=45))
    pct = (sum(1 for x in win if x <= lvl) / len(win) * 100) if (len(win) >= 20 and has_3y_coverage) else None
    stale = None
    if last_date:
        try:
            ref = pd.Timestamp(asof).date() if asof else dt.date.today()
            stale = max(0, int(np.busday_count(pd.Timestamp(last_date).date(), ref)))
        except Exception:
            stale = None
    return lvl, chg20, pct, stale, last_date

_SPARK_SEQ = 0

def _spark(vals, asof=None, days=60, color="#6f93c9"):
    """直近days営業日のミニ推移(SVG)。データ不足時は空文字。表示専用。
       メインの推移チャートと線・塗り・高さを完全に揃える（軸ラベルは省く）。"""
    try:
        xs = [(d, v) for d, v in (vals or [])]
        if asof is not None:
            cut = pd.Timestamp(asof).date()
            xs = [(d, v) for d, v in xs if pd.Timestamp(d).date() <= cut]
        ys = [float(v) for _, v in xs][-days:]
        if len(ys) < 10:
            return ""
        lo, hi = min(ys), max(ys)
        rng = (hi - lo) or 1.0
        W, H, P = 680, 68, 6            # 幅はメインと同じ680で線の太さ・塗りを一致させ、高さだけcompactに
        n = len(ys)
        def X(i): return P + i * (W - 2 * P) / (n - 1)
        def Y(v): return H - P - (v - lo) / rng * (H - 2 * P)
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
        area = (f"M{X(0):.1f},{Y(ys[0]):.1f} " + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
                + f" L{X(n-1):.1f},{H-P:.1f} L{X(0):.1f},{H-P:.1f} Z")
        global _SPARK_SEQ
        _SPARK_SEQ += 1
        gid = f"spk{_SPARK_SEQ}"
        return (f'<svg class="spark" viewBox="0 0 {W} {H}" preserveAspectRatio="none">'
                f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="{color}" stop-opacity="0.28"/>'
                f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
                f'<path d="{area}" fill="url(#{gid})"/>'
                f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>'
                f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.2" fill="{color}"/></svg>')
    except Exception:
        return ""


def _alert_badge(pct, risk_high=True):
    """水準パーセンタイル(0-100)と方向から株への警戒度バッジを返す。
       risk_high=True: 値が高いほど株に逆風（OAS/ドル/NFCI/債券ボラ/実質金利/2年金利）。
       risk_high=False: 値が高いほど追い風。判定は表示専用・ゲート非接続。"""
    if pct is None:
        return ""
    risk = pct if risk_high else (100 - pct)
    if risk >= 80:
        lab, col = "警戒", "#f8514a"
    elif risk >= 60:
        lab, col = "やや警戒", "#f59e0b"
    else:
        lab, col = "平常", "#64748b"
    return f'<span class="albadge" style="color:{col};border-color:{col}55">{lab}</span>'


def build_macro_pulse(rates_ctx, press_ctx, asof=None):
    """毎日見るマクロ最小セット（OAS=カナリア・実質金利=割引率）。全量はWeeklyタブに委ねる。"""
    rows = []
    def _one(d, lab, cat, is_bp, note, metrics_fn):
        vals = d.get("vals"); ld = d.get("last_date"); src = d.get("src")
        if not vals:
            return ""
        lvl, chg, pct, stale, eff = metrics_fn(vals, ld, asof)
        if lvl is None:
            return ""
        lvl_txt = (f"{lvl*100:.0f}bp" if is_bp else f"{lvl:.2f}%")
        chg_txt = "—" if chg is None else f"{chg*100:+.0f}bp"
        pct_txt = "—" if pct is None else f"{pct:.0f}%"
        spd = None
        try:
            xs = [v for _, v in vals][-780:]
            if chg is not None and len(xs) >= 120:
                dist = [xs[i] - xs[i-21] for i in range(21, len(xs))]
                spd = sum(1 for x in dist if x <= chg) / len(dist) * 100.0
        except Exception:
            spd = None
        spd_txt = ("・変化 %.0f%%" % spd) if spd is not None else ""
        badge = _alert_badge(pct, True)
        sp = _spark(vals, asof)
        src_lab = {"api": "API", "csv": "CSV", "cache": "前回値"}.get(src, src or "—")
        return (f'<div class="pulse"><div class="ptop"><span class="pnm">{lab}{badge}</span>'
                f'<span class="pbig">{lvl_txt}</span>'
                f'<span class="pchg mut">{chg_txt}<span class="mut">/20日</span></span></div>'
                f'<div class="pcat">{cat}</div>'
                f'<div class="pmeta">水準 {pct_txt}{spd_txt}・{note}</div>'
                f'{sp}<div class="pfoot mut">観測 {eff or "—"}・{src_lab}</div></div>')
    rows.append(_one((press_ctx or {}).get("BAMLH0A0HYM2") or {}, "HY OAS", "信用スプレッド（カナリア）", True,
                     "拡大=信用悪化。株より先に傷むことが多い", _pressure_metrics))
    rows.append(_one((rates_ctx or {}).get("DFII10") or {}, "米10年実質金利", "成長株の割引率", False,
                     "上昇が速い時だけ逆風", _fred_metrics))
    rows = [r for r in rows if r]
    if not rows:
        return ""
    return (f'<div class="card"><h2>信用と金利 <span class="h2en">Credit & Rates</span></h2>'
            f'<div class="sub">クレジット（OAS）と実質金利。全量はWeekly。</div>'
            f'{"".join(rows)}</div>')


def compute_net_liquidity(fred_all, asof=None):
    """ネット流動性 = FRB総資産 − リバースレポ − TGA（全て$兆換算・週次）。
       FRED公式単位で固定換算：WALCL/WTREGENは百万$(/1e6)、RRPONTSYDは十億$(/1e3)。
       桁推定は誤差源になるため使わない。成分が揃わない期間は算出しない（0埋め禁止）。
       #4: asof指定時は各系列を先にasof以前へ切ってから最新値・4週変化・チャートを作る。"""
    try:
        import bisect
        fa = fred_all or {}
        _a = None
        if asof is not None:
            try:
                _a = pd.Timestamp(asof).normalize()
            except Exception:
                _a = None
        def _map(sid, div):
            d = fa.get(sid) or {}
            out = sorted(((pd.Timestamp(dd).normalize(), float(v) / div)
                          for dd, v in (d.get("vals") or []) if v == v), key=lambda x: x[0])
            if _a is not None:
                out = [x for x in out if x[0] <= _a]
            return out
        walcl = _map("WALCL", 1e6); rrp = _map("RRPONTSYD", 1e3); tga = _map("WTREGEN", 1e6)
        if len(walcl) < 4:
            return None
        rd = [x[0] for x in rrp]; rv = [x[1] for x in rrp]
        td = [x[0] for x in tga]; tv = [x[1] for x in tga]
        def _asof(dd, ds, vs):
            if not ds:
                return None
            i = bisect.bisect_right(ds, dd) - 1
            return vs[i] if i >= 0 else None
        vals = []
        for dd, w in walcl:
            r = _asof(dd, rd, rv); t = _asof(dd, td, tv)
            if r is None or t is None:   # RRP/TGAが未取得の期間は0埋めせずスキップ
                continue
            vals.append((dd.strftime("%Y-%m-%d"), w - r - t))
        if len(vals) < 4:
            return None
        last = vals[-1][1]
        if not (1.0 < last < 15.0):      # 米ネット流動性は概ね$3〜10兆。桁破綻の保険
            return None
        prev4 = vals[-5][1] if len(vals) >= 5 else vals[0][1]
        prev13 = vals[-14][1] if len(vals) >= 14 else vals[0][1]
        _lr = _asof(walcl[-1][0], rd, rv) or 0.0
        _lt = _asof(walcl[-1][0], td, tv) or 0.0
        return dict(vals=vals, last=last, chg4w=last - prev4, chg13w=last - prev13,
                    walcl=walcl[-1][1], rrp=_lr, tga=_lt)
    except Exception:
        return None


def build_net_liquidity_card(nl, asof=None):
    """マーケットタブ用：ネット流動性の水準・4週トレンド・推移。"""
    if not nl or not nl.get("vals"):
        return ""
    last = nl["last"]; chg = nl.get("chg4w")
    _has = (chg is not None and chg == chg)
    _c = chg if _has else 0.0
    dirt = "—" if not _has else ("拡大" if _c > 0.02 else ("縮小" if _c < -0.02 else "横ばい"))
    dcls = "mut" if not _has else ("pos" if _c > 0.02 else ("neg" if _c < -0.02 else "mut"))
    sp = _spark([(d, v) for d, v in nl["vals"]], asof, days=104,
                color=("#1E7A4D" if _c >= 0 else "#C2453A"))
    _col = "#5b6b82" if not _has else ("#1E7A4D" if _c > 0.02 else ("#C2453A" if _c < -0.02 else "#5b6b82"))
    _chg_txt = (f'{chg:+.2f}T/4週' if _has else '—/4週')
    _chg13 = nl.get("chg13w")
    _chg13_txt = (f'{_chg13:+.2f}T' if (_chg13 is not None and _chg13 == _chg13) else '—')
    return (f'<div class="card"><div class="chd"><h2>ネット流動性 <span class="h2en">Net Liquidity</span></h2>'
            f'<div class="chd-now" style="color:{_col}"><b>${last:.2f}<span style="font-size:12px">T</span></b>'
            f'<span>{_chg_txt}</span></div></div>'
            f'<div class="sub">FRB総資産 − リバースレポ − TGA（$兆）。リスク資産のベータと連動＝地合いの本命。</div>'
            f'<div class="pulse"><div class="pcat">4週トレンド：<b class="{dcls}">{dirt}</b>（13週 {_chg13_txt}）</div>'
            f'{sp}'
            f'<div class="pmeta">内訳：総資産 {nl["walcl"]:.2f} − RRP {nl["rrp"]:.2f} − TGA {nl["tga"]:.2f}（$兆）</div>'
            f'</div></div>')


def build_econ_calendar(asof=None):
    """来週(8日以内)の主要US経済指標を定例スケジュールから推定（目安）。曜日別・重要度付き。"""
    try:
        import datetime as _dt, calendar as _cal
        today = (pd.Timestamp(asof).date() if asof else _dt.date.today())
        end = today + _dt.timedelta(days=8)
        def nthwd(y, mo, wd, n):
            d = _dt.date(y, mo, 1)
            return d + _dt.timedelta(days=(wd - d.weekday()) % 7 + (n - 1) * 7)
        FOMC_MONTHS = {1, 3, 5, 6, 7, 9, 11, 12}   # 年8回(概算)
        ev = []
        months = [today.replace(day=1)]
        nxt = (today.replace(day=28) + _dt.timedelta(days=7)).replace(day=1)
        months.append(nxt)
        for base in months:
            y, mo = base.year, base.month
            ld = _cal.monthrange(y, mo)[1]
            ism1 = _dt.date(y, mo, 1)
            while ism1.weekday() >= 5:
                ism1 += _dt.timedelta(days=1)
            cand = [
                (ism1, "ISM製造業", 2, "景況感"),
                (nthwd(y, mo, 4, 1), "雇用統計(NFP)", 3, "雇用・賃金"),
                (nthwd(y, mo, 2, 2), "CPI", 3, "インフレ"),
                (nthwd(y, mo, 2, 2) + _dt.timedelta(days=1), "PPI", 2, "卸インフレ"),
                (nthwd(y, mo, 2, 3), "小売売上高", 2, "消費"),
                (_dt.date(y, mo, min(ld, 30)), "PCE(個人消費/物価)", 3, "FRB重視インフレ"),
            ]
            if mo in FOMC_MONTHS:
                cand.append((nthwd(y, mo, 2, 3), "FOMC(政策金利)", 3, "金融政策"))
            for dt_, nm, imp, cat in cand:
                if today <= dt_ < end:
                    ev.append((dt_, nm, imp, cat))
        for i in range(8):   # 毎週木曜: 新規失業保険
            d = today + _dt.timedelta(days=i)
            if d.weekday() == 3 and today <= d < end:
                ev.append((d, "新規失業保険", 2, "労働(週次)"))
        ev = sorted(set(ev), key=lambda x: (x[0], -x[2]))
        WK = "月火水木金土日"
        if not ev:
            body = '<div class="empty">来週の主要指標なし（谷間）</div>'
        else:
            rows = []
            for dt_, nm, imp, cat in ev:
                star = "★" * imp
                icls = "neg" if imp >= 3 else ("warnc" if imp == 2 else "mut")
                rows.append(
                    f'<div class="ecrow"><span class="ecdate num">{dt_.month}/{dt_.day}<span class="ecw">({WK[dt_.weekday()]})</span></span>'
                    f'<span class="ecnm">{_h(nm)}<span class="eccat">{_h(cat)}</span></span>'
                    f'<span class="ecimp {icls}">{star}</span></div>')
            body = "".join(rows)
        return (f'<div class="card"><h2>来週の経済指標 <span class="h2en">Next Week</span></h2>'
                f'<div class="sub">定例スケジュールからの推定（目安）。★=重要度。持ち越し判断の材料に。</div>'
                f'<div class="eccal">{body}</div>'
                f'<div class="note" data-fold="0">※日付・時刻・コンセンサスは各自で最終確認。FOMC/CPI/雇用統計を跨ぐ週はポジション管理を優先。</div></div>')
    except Exception:
        return ""


def _macro_line(lab, sid, fred_all, asof=None, unit="", digits=2, invert=False, note="", weekly=False, days=800):
    """構造マクロの1行：水準＋約1ヶ月変化＋推移スパーク(既定約3年)。invert=Trueで色反転(低いほど良い)。
       weekly=Trueで週次系列(変化を4点=約1ヶ月で取る)。"""
    d = (fred_all or {}).get(sid) or {}
    vals = d.get("vals") or []
    if asof is not None:                       # #35: 先にas-ofで切る（株価の確定日と数値・チャートを揃える）
        try:
            _a = pd.Timestamp(asof)
            vals = [(dd, v) for dd, v in vals if pd.Timestamp(dd) <= _a]
        except Exception:
            pass
    if not vals:
        return ""
    try:
        ys = [float(v) for _, v in vals if v == v]
        if len(ys) < 5:
            return ""
        _n = 4 if weekly else 21
        last = ys[-1]; prev = ys[-min(len(ys), 1 + _n)]
        chg = last - prev
        up_good = (not invert)
        cls = ("pos" if (chg > 0) == up_good else "neg") if abs(chg) > 1e-9 else "mut"
        col = "#1E7A4D" if cls == "pos" else ("#C2453A" if cls == "neg" else "#6f93c9")
        sp = _spark(vals, asof, days=days, color=col)
        return (f'<div class="mbrow"><div class="mbtop"><span class="mbnm">{lab}</span>'
                f'<span class="mbval num">{last:.{digits}f}{unit}</span>'
                f'<span class="mbchg {cls} num">{chg:+.{digits}f}<span class="mut">/1ヶ月</span></span></div>'
                f'{sp}<div class="mbnote">{note}</div></div>')
    except Exception:
        return ""


def _macro_read(fred_all, nl, asof=None):
    """構造マクロ全体を素人にも分かる1段落に統合。流動性・カーブ・クレジット・インフレ・労働から、
       マクロが株の追い風か逆風か＋注目点を平易な言葉で。"""
    fa = fred_all or {}
    _a = None
    if asof is not None:
        try:
            _a = pd.Timestamp(asof)
        except Exception:
            _a = None
    def _lv(sid, back_pts):
        v = (fa.get(sid) or {}).get("vals") or []
        if _a is not None:                     # #35: 文章もas-of参照（最新FRED値で株の話をしない）
            v = [x for x in v if pd.Timestamp(x[0]) <= _a]
        ys = [float(x[1]) for x in v if x[1] == x[1]]
        if not ys:
            return (None, None)
        return (ys[-1], ys[-min(len(ys), 1 + back_pts)])
    parts = []
    risk = 0   # 逆風スコア（＋=リスクオフ／−=リスクオン）
    nlr = _net_liq_read(nl)
    if nlr:
        parts.append(f"流動性は{nlr[0]}")
        risk += (1 if nlr[1] == "neg" else (-1 if nlr[1] == "pos" else 0))
    c_now, c_prev = _lv("T10Y3M", 60)
    if c_now is not None:
        if c_now < -0.1:
            parts.append("イールドカーブは逆イールドで景気後退シグナルが点灯中"); risk += 1
        elif c_prev is not None and c_now > c_prev and c_now < 0.3:
            parts.append("カーブは正常化に向かい後退リスクは後退")
        else:
            parts.append("カーブは正常で後退シグナルは出ていない")
    h_now, h_prev = _lv("BAMLH0A0HYM2", 20)
    if h_now is not None:
        if h_prev is not None and (h_now - h_prev) > 0.3:
            parts.append("クレジット（HY）が拡大＝信用不安が台頭（株より先に傷む）"); risk += 1
        elif h_now < 3.5:
            parts.append("クレジットは落ち着き信用不安は限定的")
        else:
            parts.append("クレジットはやや高めで注意")
    i_now, i_prev = _lv("T5YIFR", 60)
    if i_now is not None and i_prev is not None:
        if (i_now - i_prev) > 0.2:
            parts.append("期待インフレが上昇＝利下げ後ずれのタカ派圧力"); risk += 1
        else:
            parts.append("期待インフレは安定")
    j_now, j_prev = _lv("ICSA", 8)
    if j_now is not None and j_prev is not None:
        if (j_now - j_prev) > 30000:
            parts.append("失業保険が増加＝労働に亀裂（リスクオフ前兆）"); risk += 1
        else:
            parts.append("失業保険は低位で労働は健全")
    if not parts:
        return ""
    stance = "追い風" if risk <= -1 else ("逆風" if risk >= 2 else "中立")
    scls = "pos" if risk <= -1 else ("neg" if risk >= 2 else "mut")
    tail = ("株を後押しするマクロ環境" if stance == "追い風"
            else ("株の重石になりやすいマクロ環境で注意" if stance == "逆風"
                  else "株の重石になるマクロ要因は今のところ乏しい"))
    return (f'マクロの土台は<b class="{scls}">{stance}</b>。' + "。".join(parts) + f"。総じて、{tail}。")


def build_weekly_macro_board(fred_all, nl, asof=None):
    """ウィークリータブ用：構造マクロを一望（ネット流動性・イールドカーブ・クレジット・インフレ・労働）。"""
    blocks = []
    # ネット流動性（週次トレンド・約3年）
    if nl and nl.get("vals"):
        chg = nl.get("chg13w")
        _cf = _finite(chg)
        col = ("#1E7A4D" if (_cf and chg >= 0) else "#C2453A") if _cf else "#667085"
        sp = _spark([(d, v) for d, v in nl["vals"]], asof, days=180, color=col)
        cls = "mut" if not _cf else ("pos" if chg > 0.02 else ("neg" if chg < -0.02 else "mut"))
        _chgtxt = (f"{chg:+.2f}" if _cf else "—")
        blocks.append(
            f'<div class="mbrow"><div class="mbtop"><span class="mbnm">ネット流動性</span>'
            f'<span class="mbval num">${nl["last"]:.2f}T</span>'
            f'<span class="mbchg {cls} num">{_chgtxt}<span class="mut">/13週</span></span></div>'
            f'{sp}<div class="mbnote">総資産−RRP−TGA。拡大=リスクオンの追い風</div></div>')
    blocks.append(_macro_line("イールドカーブ 10Y−3M", "T10Y3M", fred_all, asof, unit="%", invert=False,
                              note="マイナス深化=景気後退シグナル(誤爆少)"))
    blocks.append(_macro_line("イールドカーブ 10Y−2Y", "T10Y2Y", fred_all, asof, unit="%", invert=False,
                              note="スティープ化=景気回復期待"))
    blocks.append(_macro_line("HY OAS(ハイイールド)", "BAMLH0A0HYM2", fred_all, asof, unit="%", invert=True,
                              note="拡大=投機クレジット悪化。株より先に傷む"))
    blocks.append(_macro_line("IG OAS(投資適格)", "BAMLC0A0CM", fred_all, asof, unit="%", invert=True,
                              note="拡大=本体の信用緊張"))
    blocks.append(_macro_line("5年5年先 期待インフレ", "T5YIFR", fred_all, asof, unit="%", invert=False,
                              note="長期の織り込み。急伸はタカ派圧力"))
    blocks.append(_macro_line("新規失業保険", "ICSA", fred_all, asof, unit="", digits=0, invert=True,
                              weekly=True, note="増加=労働の亀裂。リスクオフ前兆"))
    blocks.append(_macro_line("SOFR(資金調達金利)", "SOFR", fred_all, asof, unit="%", invert=True,
                              note="急伸=資金調達ストレスのカナリア"))
    blocks = [b for b in blocks if b]
    if not blocks:
        return ""
    read = _macro_read(fred_all, nl, asof)
    read_html = f'<div class="mbread">{read}</div>' if read else ''
    return (f'<div class="card"><h2>構造マクロ <span class="h2en">Structural Macro</span></h2>'
            f'<div class="sub">週末に腰を据えて見る、低頻度で効く指標。流動性→カーブ→クレジット→インフレ→労働（推移は約3年）。</div>'
            f'{read_html}{"".join(blocks)}</div>')


def build_macro_pressure(fred_ctx, macro, asof=None):
    """第2段階：マクロ圧力パネル。HY OAS / ドル / NFCI / 債券ボラ を
       水準・20日変化・3年パーセンタイル・観測日で並べるだけ。
       ★総合点や「追い風/中立/逆風/急変」の判定は作らない（ルール未固定のため。第3段で固定後に追加）。
       ★得点化しない＝MRIには一切入れない。取得失敗はその行だけ欠損表示、パネルは生成継続。"""
    rows = []

    def _row(cat, lab, vals, ld, src, unit, cached_at=None, is_bp=False,
             pct3_hint="水準", up_note=None, risk_high=True):
        lvl, chg20, pct, stale, eff = _pressure_metrics(vals, ld, asof)
        spd = None
        try:
            spd = _change_percentile(vals, chg20, asof=asof, bdays=20, years=3)
        except Exception:
            spd = None
        if lvl is None:
            return (f'<div class="pulse"><div class="ptop"><span class="pnm">{lab}</span>'
                    f'<span class="na">—</span></div><div class="pcat">{cat}</div>'
                    f'<div class="pfoot mut">未取得</div></div>')
        if is_bp:                                     # スプレッドはbp表示
            chg_txt = "—" if chg20 is None else f'{chg20*100:+.0f}bp'
            lvl_txt = f'{lvl*100:.0f}bp'
        else:
            chg_txt = "—" if chg20 is None else f'{chg20:+.2f}'
            lvl_txt = f'{lvl:.2f}{unit}'
        pct_txt = "—" if pct is None else f'{pct:.0f}%'
        src_lab = {"api": "API", "csv": "CSV", "cache": "前回値", "yf": "yfinance",
                   "MOVE": "MOVE", "TLT実現ボラ": "TLT実現ボラ", "none": "—"}.get(src, src)
        stale_txt = "" if stale is None else (f'・{stale}営業日前' if stale > 0 else "・本日")
        note = f'・{up_note}' if up_note else ""
        spd_txt = ("・変化 %.0f%%" % spd) if spd is not None else ""
        badge = _alert_badge(pct, risk_high)
        sp = _spark(vals, asof)
        return (f'<div class="pulse"><div class="ptop"><span class="pnm">{lab}{badge}</span>'
                f'<span class="pbig">{lvl_txt}</span>'
                f'<span class="pchg mut">{chg_txt}<span class="mut">/20日</span></span></div>'
                f'<div class="pcat">{cat}</div>'
                f'<div class="pmeta">{pct3_hint} {pct_txt}{spd_txt}{note}</div>'
                f'{sp}<div class="pfoot mut">観測 {eff or "—"}{stale_txt}・{src_lab}</div></div>')

    # HY OAS（信用）
    oas = (fred_ctx or {}).get("BAMLH0A0HYM2", {})
    rows.append(_row("信用スプレッド（カナリア）", "HY OAS", oas.get("vals"), oas.get("last_date"),
                     oas.get("src"), "%", oas.get("cached_at"), is_bp=True,
                     up_note="拡大=信用悪化。株より先に傷むことが多い"))
    # ドル（DTWEXBGS→DXYフォールバック・別名明示）
    dv, dlab, dld, dsrc, dcached = _dollar_from_macro_or_fred(fred_ctx, macro)
    rows.append(_row("ドル", dlab, dv, dld, dsrc, "", dcached, up_note="ドル高=世界の資金逼迫"))
    # NFCI（金融環境・週次）
    nfci = (fred_ctx or {}).get("NFCI", {})
    rows.append(_row("金融環境(週次)", "NFCI", nfci.get("vals"), nfci.get("last_date"),
                     nfci.get("src"), "", nfci.get("cached_at"),
                     up_note="0超=平均より引き締まり"))
    # 債券ボラ（MOVE→TLT実現ボラ）
    bv, bsrc, bunit = _bondvol_from_macro(macro)
    blab = {"MOVE": "MOVE（金利ボラ）", "TLT実現ボラ": "TLT 20日実現ボラ（MOVE代替）",
            "none": "債券ボラ（未取得）"}.get(bsrc, "債券ボラ")
    rows.append(_row("債券ボラ", blab, bv, (bv[-1][0] if bv else None), bsrc, bunit,
                     up_note="上昇=金利市場が不安定"))

    body = "".join(rows)
    return (f'<div class="card"><h2>マクロ圧力 <span class="h2en">Macro Pressure</span></h2>'
            f'<div class="sub">信用・ドル・金融環境・金利ボラの水準、20日変化、3年%ile。</div>'
            f'<div class="rgrid">{body}</div></div>')


def build_breadth_ts(W, lookback=CHART_LB):
    """% of universe above its 200-day MA, as a daily time series (S5TH analog)."""
    C = W["Close"]
    sma200 = C.rolling(200, min_periods=200).mean()   # 150日平均を「200DMA」と呼ばない
    # 十分な銘柄数(母数の6割以上)が200MAを持つ日からのみ集計→頭のスカスカ区間を除去
    valid_cnt = sma200.notna().sum(axis=1)
    uni_cnt = C.notna().sum(axis=1)
    ok = valid_cnt >= (uni_cnt * 0.6).clip(lower=30)
    # 分母は200MAを持つ銘柄数（分子と母集団を一致させる）
    pct = ((C > sma200).sum(axis=1) / valid_cnt.replace(0, np.nan) * 100)
    pct = pct[ok].dropna()
    s = pct.iloc[-lookback:]
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]

def build_dollarvol_ts(W, macro=None, lookback=CHART_LB, smooth=21):
    """売買代金推移: ユニバース合算(終値×出来高の総和)＋QQQ/SPYの売買代金を、
       <b>21日平滑</b>してから期間開始=100にリベース（日次スパイクで潰れないよう平滑）。約2年。
       あわせてユニバース売買代金のトレンド（拡大/縮小）を判定してコメント用に返す。"""
    C = W.get("Close"); V = W.get("Volume")
    if C is None or V is None or getattr(C, "shape", (0,))[0] < 30:
        return None
    dv_raw = (C * V).sum(axis=1, min_count=1)
    cnt = C.notna().sum(axis=1)
    uni = int(cnt.max()) if len(cnt) else 0
    if uni:
        dv_raw = dv_raw[cnt >= 0.6 * uni]
    dv_raw = dv_raw.dropna()
    if len(dv_raw) < max(60, smooth + 5):
        return None
    mp = max(5, smooth // 2)
    dvs = dv_raw.rolling(smooth, min_periods=mp).mean().dropna()
    # ユニバース売買代金のトレンド（平滑後・3ヶ月前比＋直近1ヶ月の向き）
    uni_trend = None
    if len(dvs) >= 80:
        cur = float(dvs.iloc[-1]); ref = float(dvs.iloc[-min(len(dvs), 63)])
        s21 = float(dvs.iloc[-min(len(dvs), 21)])
        pct = (cur / ref - 1) if ref else 0.0
        if pct >= 0.08 and cur >= s21:
            d = "拡大"
        elif pct <= -0.08 and cur <= s21:
            d = "縮小"
        else:
            d = "横ばい"
        uni_trend = dict(dir=d, pct=pct * 100, sig=abs(pct) >= 0.08, cur=cur)
    idx = dvs.iloc[-lookback:].index
    raw_series = [("ユニバース合算", dv_raw, "#38bdf8")]
    if macro:
        for key, color in (("QQQ", "#a78bfa"), ("SPY", "#7ff0a8")):
            d = macro.get(key)
            if d is None:
                continue
            raw_series.append((key, (d["Close"] * d["Volume"]).dropna(), color))
    out = {"dates": [dd.strftime("%Y-%m-%d") for dd in idx], "series": [],
           "span": _span_label([(dd.strftime("%Y-%m-%d"), 0.0) for dd in idx]),
           "uni_trend": uni_trend, "smooth": smooth}
    for name, s, color in raw_series:
        sm_full = s.rolling(smooth, min_periods=mp).mean()          # 21日平滑（全期間）
        ma200 = sm_full.rolling(200, min_periods=60).mean()         # 自分の200日平均
        ratio = (sm_full / ma200).reindex(idx).ffill()             # 参加度＝平滑売買代金÷200日平均（先頭NaNはそのまま）
        rv = ratio.dropna()
        if rv.empty:
            continue
        smv = sm_full.reindex(idx).ffill().dropna()
        last_abs = float(smv.iloc[-1]) if len(smv) else float("nan")
        chg20 = (last_abs / float(smv.iloc[-min(len(smv), 21)]) - 1) * 100 if len(smv) else 0.0
        out["series"].append(dict(
            name=name, color=color, last_abs=last_abs, chg20=chg20, last_ratio=float(rv.iloc[-1]),
            ys=[(float(v) if v == v else None) for v in ratio.values]))
    return out if out["series"] else None

def _updown_state(v):
    """上げ日/下げ日 売買代金比の状態（O'Neil式 集積/分散）。"""
    if v >= 1.25: return ("集積（買い集め優勢）", "#7ff0a8", "accum")
    if v >= 1.00: return ("集積寄り", "#9ae6b4", "accum")
    if v >= 0.80: return ("分散寄り（注意）", "#fcd34d", "distrib")
    return ("分散（売り抜け優勢）", "#fca5a5", "distrib")

def build_updown_vol_ts(W, macro=None, lookback=CHART_LB, win=20):
    """O'Neil式 Up/Down Volume Ratio（ユニバース版）。
       ★銘柄ごとに前日比で上げ/下げを判定し、その銘柄の$売買代金をUp側/Down側に振り分ける。
       （旧実装は「QQQの上げ日/下げ日にユニバース総売買代金を丸ごと振る」もので、
         これは市場回転率であってUp/Down Volumeではない。指標名と計算が不一致だった。）
       >1 = 買い集め優勢。"""
    C = W.get("Close"); V = W.get("Volume")
    if C is None or V is None or getattr(C, "shape", (0,))[0] < win + 10:
        return None
    cnt = C.notna().sum(axis=1)
    uni = int(cnt.max()) if len(cnt) else 0
    keep = (cnt >= 0.6 * uni) if uni else cnt.astype(bool)
    ret = C.pct_change(fill_method=None)
    dv = C * V
    up = dv.where(ret > 0).sum(axis=1, min_count=1)
    dn = dv.where(ret < 0).sum(axis=1, min_count=1)
    up = up[keep]; dn = dn[keep]
    ups = up.rolling(win).sum(); dns = dn.rolling(win).sum()
    ratio = (ups / dns.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(ratio) < 20:
        return None
    s = ratio.iloc[-lookback:]
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]

def _updown_vol_card(ts):
    """集積/分散: 上げ日/下げ日 売買代金比の推移・1.0基準線つき。"""
    if not ts or len(ts) < 5:
        return ""
    raw_last = ts[-1][1]
    ys = [min(3.0, max(0.2, v)) for _, v in ts]      # 表示クランプ（スパイク抑制）
    n = len(ys)
    Wd, Ht, pad = 680, 180, 6
    lo, hi = min(ys), max(ys); lo = min(lo, 0.85); hi = max(hi, 1.20)
    rng = (hi - lo) or 1
    lo2, hi2 = lo - rng * 0.08, hi + rng * 0.08; rng2 = (hi2 - lo2) or 1
    def X(i): return pad + i * (Wd - 2 * pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo2) / rng2) * (Ht - 2 * pad)
    # ゾーン塗り（>1.25集積 / <0.8分散）
    zr = ""
    if hi2 > 1.25:
        zr += f'<rect x="{pad}" y="{Y(hi2):.1f}" width="{Wd-2*pad}" height="{max(0.0,Y(1.25)-Y(hi2)):.1f}" fill="#22c55e" opacity="0.06"/>'
    if lo2 < 0.80:
        zr += f'<rect x="{pad}" y="{Y(0.80):.1f}" width="{Wd-2*pad}" height="{max(0.0,Y(lo2)-Y(0.80)):.1f}" fill="#ef4444" opacity="0.06"/>'
    gl = ""
    for g in (0.8, 1.0, 1.25):
        if not (lo2 <= g <= hi2):
            continue
        is1 = abs(g - 1.0) < 1e-9
        stroke = "#3b4b63" if is1 else "#1c2533"
        dash = ' stroke-dasharray="4 3"' if is1 else ""
        gl += (f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="{stroke}" stroke-width="1"{dash}/>'
               f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g:.2f}</text>')
    area = (f"M{X(0):.1f},{Y(ys[0]):.1f} " + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
            + f" L{X(n-1):.1f},{Ht-pad:.1f} L{X(0):.1f},{Ht-pad:.1f} Z")
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    state, col, _reg = _updown_state(raw_last)
    svg = (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
           f'<defs><linearGradient id="uvg" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="{col}" stop-opacity="0.28"/>'
           f'<stop offset="1" stop-color="{col}" stop-opacity="0"/></linearGradient></defs>'
           f'{zr}{gl}<path d="{area}" fill="url(#uvg)"/>'
           f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>'
           f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="{col}"/></svg>')
    return (f'<div class="card"><div class="chd"><h2>集積／分散（上げ日÷下げ日 売買代金）</h2>'
            f'<div class="chd-now" style="color:{col}"><b>{raw_last:.2f}</b><span>{state}</span></div></div>'
            f'<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">上げ日÷下げ日の売買代金（20日）。<b>1.0超＝買い集め</b>／<b>1.0割れ＝売り抜け</b>（O\'Neil式）</div></details>'
            f'<div class="chart">{svg}'
            f'{_date_axis(ts)}</div></div>')

def build_ratio_ts(macro, num, den_keys, lookback=CHART_LB):
    """num / basket(den_keys) の比率を期間先頭=100にリベースした系列（B-2/B-3用）。
    分母バスケットは各系列を初期値=1に正規化してから平均（生値平均だと高株価ETFに過重になるのを修正）。"""
    cl = lambda k: macro[k]["Close"] if k in macro else None
    n = cl(num)
    dens = [cl(k) for k in den_keys if cl(k) is not None]
    if n is None or not dens:
        return []
    df = pd.concat([n] + dens, axis=1).sort_index().ffill().dropna()
    if len(df) < 30:
        return []
    den_norm = df.iloc[:, 1:].apply(lambda col: col / col.iloc[0], axis=0).mean(axis=1)
    ratio = (df.iloc[:, 0] / df.iloc[:, 0].iloc[0]) / den_norm
    s = ratio.iloc[-lookback:]
    if len(s) < 20:
        return []
    # #29: 各点を「その時点までのトレーリング窓」で標準化（全期間平均だと過去点が未来データを使う先読み）
    _win = min(252, len(s))
    _mp = max(20, _win // 3)
    mu_s = s.rolling(_win, min_periods=_mp).mean()
    sd_s = s.rolling(_win, min_periods=_mp).std()
    if float(sd_s.iloc[-1] or 0) <= 0 or sd_s.iloc[-1] != sd_s.iloc[-1]:
        return []
    z = ((s - mu_s) / sd_s).dropna()             # 平均からの偏差(σ)＝狭い比率でも足元の強弱が読める
    if len(z) < 10:
        return []
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in z.items()]

import math as _math_em

def build_expected_move(macro, m=None, picks=None, horizon=21):
    """オプション想定変動幅（下値予測）。
       市場=VIX/VXN（=S&P/Nasdaqのオプション・インプライド・ボラ）／個別=ADR（実現ボラ）。
       1σ move ≈ price × σ_daily × √(horizon)。個別のyfinance IVは歯抜けで信頼不可のためADRで代替。"""
    out = {"market": [], "holdings": [], "horizon": horizon}
    def last(k):
        try:
            return float(macro[k]["Close"].dropna().iloc[-1])
        except Exception:
            return None
    def _mkt(sym, volkey, mult=1.0, label=None):
        px = last(sym)
        iv = last(volkey)
        if iv is None:
            v = last("^VIX")
            iv = (v * mult) if v is not None else None
        if px is None or not iv:
            return
        ivf = iv / 100.0
        em = ivf * _math_em.sqrt(horizon / 252.0)          # horizon日 1σ（年率IV→期間換算）
        out["market"].append(dict(sym=sym, label=label or sym, px=px, iv=iv, em=em,
                                  dn1=px * (1 - em), dn2=px * (1 - 2 * em), up1=px * (1 + em)))
    _mkt("SPY", "^VIX", label="SPY（VIX）")
    _mkt("QQQ", "^VXN", mult=1.15, label="QQQ（VXN）")
    if m is not None and picks:
        for t, _, r in picks:
            adr = r.get("adr"); px = r.get("close")
            if adr is None or adr != adr or px is None or px != px:
                continue
            em = float(adr) * 0.55 * _math_em.sqrt(horizon)  # ADR≈日中レンジ→日次σ≈ADR×0.55, N日1σ
            out["holdings"].append(dict(t=t, px=float(px), adr=float(adr), em=em, dn1=float(px) * (1 - em)))
    return out

def _expected_move_card(em):
    """オプション/ボラ想定変動幅カード（市場VIX/VXN・~1ヶ月の下値バンド）。"""
    if not em or not em.get("market"):
        return ""
    hd = em.get("horizon", 21)
    rows = ""
    for mk in em["market"]:
        rows += (f'<div class="le-row"><span class="le-k">{mk["label"]}</span>'
                 f'<span class="le-sub">IV {mk["iv"]:.1f}% ・ 1σ <b>±{mk["em"]*100:.1f}%</b> '
                 f'→ 下値 <b class="neg">{mk["dn1"]:.0f}</b>（−{mk["em"]*100:.1f}%）／2σ {mk["dn2"]:.0f}'
                 f'<span class="mut">・現在 {mk["px"]:.0f}</span></span></div>')
    return (f'<div class="card"><h2>オプション想定変動幅（VIX/VXN・約1ヶ月）</h2>'
            f'<div class="sub">VIX/VXN（S&P/Nasdaqのインプライド・ボラ）が織り込む{hd}営業日先の<b>1σ変動</b>と下値目安。'
            f'理論上の1σ目安。保有個別はADRで近似。</div>'
            f'{rows}</div>')

def build_vix_term_ts(macro, lookback=CHART_LB):
    """B-4a: VIX/VIX3M の生比率系列（リベースしない・1.0が構造的原点）。"""
    cl = lambda k: macro[k]["Close"] if k in macro else None
    v1, v3 = cl("^VIX"), cl("^VIX3M")
    if v1 is None or v3 is None:
        return []
    df = pd.concat([v1, v3], axis=1).sort_index().ffill().dropna()
    if len(df) < 30:
        return []
    r = (df.iloc[:, 0] / df.iloc[:, 1]).iloc[-lookback:]
    return [(d.strftime("%Y-%m-%d"), float(x)) for d, x in r.items()]

def build_adline_ts(W, lookback=CHART_LB):
    """騰落ライン→マクレラン・オシレーター（足元の広がりの勢い）。
       RANA=(adv−dec)/(adv+dec)×1000 の EMA19−EMA39。0中心・プラス=買い広がり/マイナス=売り広がり。
       2年累積ラインは"遅い確認"で200日線上%と重複するため、足元感応のオシレーターに変更。"""
    C = W["Close"]
    ret = C.pct_change(fill_method=None)
    adv = (ret > 0).sum(axis=1); dec = (ret < 0).sum(axis=1)
    denom = (adv + dec).replace(0, np.nan)
    rana = ((adv - dec) / denom * 1000.0).dropna()     # 銘柄数に依存しない正規化ネット
    if len(rana) < 45:
        return []
    osc = (rana.ewm(span=19, adjust=False).mean() - rana.ewm(span=39, adjust=False).mean())
    s = osc.iloc[-lookback:]
    if len(s) < 5:
        return []
    return [(d.strftime("%Y-%m-%d"), float(x)) for d, x in s.items()]

def build_distribution(macro):
    """IBD式の売り抜け日（QQQ/SPY代理）:
      Classic = 前日比 −0.2%以下 かつ 出来高が前日超
      Stall   = 上昇したのに +0.4%以下で止まり、出来高は前日超、レンジ下半分で引け、かつ高値圏(20日高値の-3%以内)
    ★点灯(4/6)に使うのは Classic のみ。Stall は【表示専用】。
      Stall を件数に足すのは「係数1.0で未検証パラメータを採用する」ことに等しいため、
      バックテストが通るまで点灯ロジックには入れない。
    直近25営業日で集計。その日の終値から+5%上昇したらリセット（IBDのラリー・ウォッシュアウト）。"""
    out = {}
    for tk in ["SPY", "QQQ"]:
        if tk not in macro:
            continue
        df = macro[tk].dropna(subset=["Close"])
        if len(df) < 30:
            continue
        c = df["Close"]; v = df["Volume"]
        h = df["High"] if "High" in df.columns else c
        l = df["Low"]  if "Low"  in df.columns else c
        ret = c / c.shift(1) - 1
        rng = (h - l).replace(0, np.nan)
        cpos = (c - l) / rng                       # 日中レンジ内の引け位置 (0=安値, 1=高値)
        hi20 = c.rolling(20).max()
        classic = (ret <= -0.002) & (v > v.shift(1))
        # ストール日: 「上げたのに値幅が進まず、出来高だけ膨らみ、安値寄りで引けた」＝買い疲れ。
        #   ret>0・出来高の厳密増加を要求（でないと平坦な日が全部ストールになる）。
        #   高値更新は必須にしない（高値を更新できずに押される日こそ典型）。代わりに高値圏(20日高値-3%以内)を要求。
        stall   = ((ret > 0) & (ret <= 0.004) & (v > v.shift(1))
                   & (cpos <= 0.5) & (c >= hi20 * 0.97) & rng.notna())
        heavy   = ret <= -0.01
        hit = (classic | stall).iloc[-25:]
        days, n_cl, n_st, n_hv, n_r10 = [], 0, 0, 0, 0
        idx25 = list(hit.index)
        for k, (d, ok) in enumerate(hit.items()):
            if not bool(ok):
                continue
            cd = float(c.loc[d])
            future = c.loc[c.index > d]
            if len(future) and float(future.max()) >= cd * 1.05:
                continue                            # +5%上昇でリセット → カウントしない
            is_st = bool(stall.loc[d]) and not bool(classic.loc[d])
            n_st += is_st; n_cl += (not is_st)
            n_hv += bool(heavy.loc[d])
            if k >= len(idx25) - 10:
                n_r10 += 1
            days.append(d.strftime("%-m/%-d") + ("s" if is_st else ""))
        # ★点灯は Classic のみ（旧版と完全に同一の件数）。Stall は
        n_alert = n_cl
        if   n_alert >= 6: st_, cls = "調整警戒", "bad"
        elif n_alert >= 4: st_, cls = "観察",    "warn"
        else:              st_, cls = "良好",    "good"
        out[tk] = dict(n=n_alert, alert_basis="classic_only",
                       cl=n_cl, stall=n_st, heavy=n_hv, r10=n_r10,
                       total=n_cl + n_st, st=st_, cls=cls, days=days)
    return out

FTD_PCT = 0.0125          # FTDの必要上昇率（IBD教育資料: 1.25%）。1.0%も許容されるが厳しめを既定とする。

def build_ftd(macro, idxs=(("QQQ", "NASDAQ100"), ("SPY", "S&P500"))):
    """フォロースルー・デイ（QQQ/SPYベースの代理判定）。内部状態:
       NO_CORRECTION / CORRECTION / RALLY_ATTEMPT / FTD_ACTIVE / FTD_FAILED
    - 調整局面 = 終値 < 50日線 または 52週高値から−8%以下
    - Day1 = 調整安値後の最初のプラス引け。安値更新（日中安値）で数え直し（IBD準拠）
    - FTD = Day4以降に 前日比+1.25%以上 × 出来高が前日超（★最初の成立で確定）
    - 無効化:
        (a) FTD_FAILED : 終値がFTD日の安値を割る（★終値ベース。日中1セント割れでは失敗にしない）
        (b) 新規調整入り: FTD後に一度50日線を回復(armed)してから、
              「FTD後高値から−8%以下」または「50日線下の終値が5営業日連続」
            → inactive化して新しい試行を待つ。
            ※単に50日線を1〜2日わずかに割っただけでは無効化しない（2026/7のQQQ:−0.3%×2日で誤発火した）。
      → 時間経過だけでは失効させない。"""
    out = []
    for tk, lab in idxs:
        d = macro.get(tk)
        if d is None:
            continue
        df = d.dropna(subset=["Close"])
        if len(df) < 60:
            continue
        c = df["Close"]
        l = df["Low"] if "Low" in df.columns else df["Close"]
        v = df["Volume"] if "Volume" in df.columns else None
        sma50_s = c.rolling(50).mean()
        hi252_s = c.rolling(252, min_periods=252).max()   # #34: 60日でなく252本必須（真の52週高値）
        corr_s = (c < sma50_s) | (c / hi252_s - 1 <= -0.08)

        N = min(500, len(c))   # #8: 150では長い無調整局面でFTD/ラリー状態を取りこぼす。500に拡大
        dates = df.index[-N:]
        cc = c.iloc[-N:].to_numpy(dtype=float)
        ll = l.iloc[-N:].to_numpy(dtype=float)
        vv = v.iloc[-N:].to_numpy(dtype=float) if v is not None else None
        corr = corr_s.iloc[-N:].fillna(False).to_numpy(dtype=bool)

        sm50 = sma50_s.iloc[-N:].to_numpy(dtype=float)
        low_v = low_i = day1 = None
        ftd_i = ftd_pct = ftd_low = ftd_day = None
        armed = False; post_max = np.nan; below50 = 0
        failed_ago = None; inval = None
        for j in range(1, N):
            cj, cp, lj = cc[j], cc[j - 1], ll[j]
            if ftd_i is not None:
                post_max = cj if not np.isfinite(post_max) else max(post_max, cj)
                s = sm50[j]
                if np.isfinite(s):
                    below50 = below50 + 1 if cj < s else 0
                    if cj >= s:
                        armed = True                     # 50日線を回復＝以後の崩れは「新しい調整」
                deep = np.isfinite(post_max) and (cj / post_max - 1) <= -0.08
                if cj < ftd_low:                         # (a) 終値でFTD日の安値を割る
                    failed_ago, inval = (N - 1) - j, "FTD日安値を終値で割れ"
                elif armed and (deep or below50 >= 5):   # (b) 実質的な新規調整入り
                    failed_ago, inval = ((N - 1) - j,
                        "新規調整入り: FTD後高値−8%" if deep else "新規調整入り: 50日線下5日連続")
                else:
                    continue
                ftd_i = ftd_pct = ftd_low = ftd_day = None
                armed = False; below50 = 0; post_max = np.nan
                day1, low_v, low_i = None, lj, j
                continue
            if day1 is not None:
                if lj < low_v:                       # 試行安値割れ（日中）= 数え直し
                    low_v, low_i, day1 = lj, j, None
                    continue
                att = j - day1 + 1
                if att >= 4 and vv is not None and np.isfinite(vv[j]) and np.isfinite(vv[j - 1]):
                    chg = cj / cp - 1
                    if chg >= FTD_PCT and vv[j] > vv[j - 1]:
                        ftd_i, ftd_pct, ftd_low, ftd_day = j, chg, lj, att
                        armed = False; below50 = 0; post_max = cj; failed_ago = inval = None
                continue
            if not corr[j]:
                low_v = low_i = None
                continue
            if low_v is None or lj < low_v:
                low_v, low_i = lj, j
                if cj > cp:
                    day1 = j
            elif cj > cp:
                day1 = j

        last = float(c.iloc[-1])
        sma50 = sma50_s.iloc[-1]; sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else np.nan
        above50 = bool(pd.notna(sma50) and last >= float(sma50))
        above200 = bool(pd.notna(sma200) and last >= float(sma200))
        corr_now = bool(corr[-1])
        att_day = ((N - 1) - day1 + 1) if day1 is not None else 0
        rec = dict(tk=tk, lab=lab,
                   rally_start=(dates[day1].strftime("%-m/%-d") if day1 is not None else None),
                   rally_day=(att_day or None),
                   ftd_date=(dates[ftd_i].strftime("%-m/%-d") if ftd_i is not None else None),
                   ftd_age=((N - 1) - ftd_i if ftd_i is not None else None),
                   ftd_day=ftd_day, ftd_low=(round(ftd_low, 2) if ftd_low else None),
                   invalidation=inval)

        if ftd_i is not None:
            ago = (N - 1) - ftd_i
            q = "" if ftd_day <= 7 else ("・やや遅い" if ftd_day <= 10 else "・信頼度低")
            state = "FTD_ACTIVE"                       # 状態は有効のまま（時間で消さない）
            if not above50:
                st, cls = f"点灯後に50日線割れ（{rec['ftd_date']} Day{ftd_day} / {ago}日前）", "warnt"
            elif ago > 40 and above200:
                # 上昇が定着した後は強調表示をやめる。ただしFTDの出所は残す（消灯ではない）
                st, cls = f"上昇継続中（{rec['ftd_date']}以来{ago}日）", "mut"
            else:
                st, cls = f"点灯 {rec['ftd_date']} Day{ftd_day}{q}・{ago}日前 +{ftd_pct * 100:.1f}%", "pos"
        elif failed_ago is not None and failed_ago <= 20 and not (
                day1 is not None and att_day is not None and att_day <= failed_ago):
            # 新しいDay1が失敗より後に始まっていれば RALLY_ATTEMPT を優先（監査#次点1）
            state = "FTD_FAILED"
            st, cls = f"FTD無効（{failed_ago}日前・{inval}）", "warnt"
        elif day1 is not None:
            state = "RALLY_ATTEMPT"
            st, cls = f"試行 {att_day}日目・確認待ち（安値 {rec['rally_start']}〜）", "warnt"
        elif corr_now:
            state = "CORRECTION"
            st, cls = "調整局面・試行未開始（安値模索）", "mut"
        elif above50 and above200:
            state = "NO_CORRECTION"
            st, cls = "上昇継続中（FTD非対象）", "mut"
        else:
            state = "NO_CORRECTION"
            st, cls = "—", "mut"
        rec.update(state=state, st=st, cls=cls)
        out.append(rec)
    return out

def _perf_one(c):
    last = float(c.iloc[-1])
    def ret(d):
        return (last / float(c.iloc[-d-1]) - 1) if len(c) > d else None
    _y0 = pd.Timestamp(year=c.index[-1].year, month=1, day=1)
    _prev = c[c.index < _y0]                       # YTDの基準は「前年最終取引日の終値」
    ytd = (last / float(_prev.iloc[-1]) - 1) if len(_prev) else None
    if len(c) >= 252:
        hi52 = float(c.iloc[-252:].max()); lo52 = float(c.iloc[-252:].min())
        pos = (last - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None
    else:
        pos = None   # #22 252本未満は52週位置を出さない（利用可能期間だけで誤誘導しない）
    sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else None
    ext200 = (last / float(sma200) - 1) if sma200 and not np.isnan(sma200) else None
    return dict(d1=ret(1), ytd=ytd, w1=ret(5), m1=ret(21), y1=ret(252), pos52=pos, ext200=ext200)

def build_perf(macro, extras=None):
    """Performance: cap-weight (SPY/QQQ) + equal-weight/breadth (RSP/QQQE) + VIX curve."""
    extras = extras or {}
    def _close(tk):
        if tk in macro:
            return macro[tk]["Close"].dropna()
        if tk in extras:
            return extras[tk].dropna()
        return None
    out = {"indices": [], "breadth_etf": [], "vix": None, "vixcurve": None}
    for tk, lab in [("SPY", "S&P500"), ("QQQ", "NASDAQ100")]:
        c = _close(tk)
        if c is not None and len(c) >= 30:
            d = _perf_one(c); d["label"] = lab
            out["indices"].append(d)
    # 等ウェイト/ブレッドスETF（地合いの本音）— 21EMA・50SMA に対する位置も
    for tk, lab in [("RSP", "S&P均等 RSP"), ("QQQE", "NDX均等 QQQE")]:
        c = _close(tk)
        if c is not None and len(c) >= 30:
            d = _perf_one(c); d["label"] = lab
            d["px"] = float(c.iloc[-1])
            d["e21"] = float(c.ewm(span=21, adjust=False).mean().iloc[-1])
            d["s50"] = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
            out["breadth_etf"].append(d)
    v1, v3, v6 = _close("^VIX"), _close("^VIX3M"), _close("^VIX6M")
    if v1 is not None and len(v1):
        out["vix"] = float(v1.iloc[-1])
    if v1 is not None and v3 is not None and len(v1) and len(v3):
        a, b = float(v1.iloc[-1]), float(v3.iloc[-1])
        c6 = float(v6.iloc[-1]) if (v6 is not None and len(v6)) else None
        out["vixcurve"] = {"v1": a, "v3": b, "v6": c6, "ratio": (a / b if b else None)}
    # ブレッドス乖離：大型株(SPY)先行 vs 等ウェイト(RSP)追随
    out["divergence"] = None
    spy = next((x for x in out["indices"] if x["label"].startswith("S&P")), None)
    rsp = next((x for x in out["breadth_etf"] if x["label"].startswith("S&P")), None)
    if spy and rsp and spy.get("m1") is not None and rsp.get("m1") is not None:
        gap = spy["m1"] - rsp["m1"]
        pos_gap = (spy.get("pos52") or 0) - (rsp.get("pos52") or 0)
        if spy["m1"] > 0 and (gap >= 0.03 or pos_gap >= 12):
            out["divergence"] = {"st": f"乖離・警戒（大型株が1カ月 {gap * 100:+.1f}pt 先行）", "cls": "neg"}
        elif rsp["m1"] >= spy["m1"]:
            out["divergence"] = {"st": "良好（等ウェイトが追随）", "cls": "pos"}
        else:
            out["divergence"] = {"st": "中立", "cls": "mut"}
    return out

# ----------------------------------------------------------------------------- HTML
def fmt_pct(x, d=1):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x*100:+.{d}f}%"
def fmt_pct0(x, d=1):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x*100:.{d}f}%"
def fmt_num(x, d=2):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x:,.{d}f}"

def _pcls(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return "mut"
    return "pos" if x >= 0 else "neg"

def _perf_card(p):
    if not p or not p.get("indices"):
        return ""
    def _strip(ix, cells):
        inner = "".join(f'<div class="c"><div class="k">{k}</div>'
                        f'<div class="v {cl}">{v}</div></div>' for k, v, cl in cells)
        return f'<div class="ixn">{ix["label"]}</div><div class="perf">{inner}</div>'
    blocks = []
    for ix in p["indices"]:
        blocks.append(_strip(ix, [
            ("YTD", fmt_pct(ix["ytd"]), _pcls(ix["ytd"])),
            ("1週", fmt_pct(ix["w1"]), _pcls(ix["w1"])),
            ("1カ月", fmt_pct(ix["m1"]), _pcls(ix["m1"])),
            ("1年", fmt_pct(ix["y1"]), _pcls(ix["y1"])),
            ("52週位置", (f'{ix["pos52"]:.0f}%' if ix.get("pos52") is not None else "—"), "mut")]))
    # 等ウェイト（RSP / QQQE）— 時価加重(QQQ/SPY)と同じ書き振りで並べる
    be = p.get("breadth_etf") or []
    if be:
        blocks.append('<div class="perf-div">等ウェイト（ブレッドス）</div>')
        for ix in be:
            blocks.append(_strip(ix, [
                ("YTD", fmt_pct(ix["ytd"]), _pcls(ix["ytd"])),
                ("1週", fmt_pct(ix["w1"]), _pcls(ix["w1"])),
                ("1カ月", fmt_pct(ix["m1"]), _pcls(ix["m1"])),
                ("1年", fmt_pct(ix["y1"]), _pcls(ix["y1"])),
                ("52週位置", (f'{ix["pos52"]:.0f}%' if ix.get("pos52") is not None else "—"), "mut")]))
    # VIXカーブ
    # VIX水準のみ（カーブ＝期間構造の物語は④の「VIX期間構造」チャートが担当）
    vixhtml = ""
    if p.get("vix") is not None:
        vixhtml = (f'<div class="vixc"><span class="vixc-l">VIX</span> <b>{p["vix"]:.1f}</b>'
                   f'<span class="mut" style="font-size:11px"> ・カーブはVIX期間構造を参照</span></div>')
    dv = p.get("divergence")
    dvhtml = (f'<div class="vixc"><span class="vixc-l">ブレッドス</span> '
              f'<span class="{dv["cls"]}">{dv["st"]}</span></div>') if dv else ""
    return (f'<div class="card"><h2>マーケット・パフォーマンス</h2>'
            + "".join(blocks) + dvhtml + vixhtml + '</div>')

def _dd_card(dd):
    if not dd:
        return ""
    def _box(tk, d):
        days = d.get("days") or []
        dline = (f'<div class="dddays">{"・".join(days)}</div>') if days else ""
        bd = (f'<div class="dddays mut">売り抜け{d.get("cl",0)}・ストール{d.get("stall",0)}'
              f'・直近10日{d.get("r10",0)}</div>')
        return (f'<div class="box"><div class="t">{tk}</div>'
                f'<div class="num">{d["n"]}</div>'
                f'<span class="st st-{d["cls"]}">{d["st"]}</span>{bd}{dline}</div>')
    boxes = "".join(_box(tk, d) for tk, d in dd.items())
    return (f'<div class="card"><h2>ディストリビューション・デイ（直近25営業日）</h2>'
            f'<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">前日比−0.2%以下＆出来高増＝<b>売り抜け日</b>／上げても値幅出ず出来高だけ膨らむ＝<b>ストール日（末尾s）</b>。4=観察・6=警戒、指数+5%で解消</div></details>' 
            f'<div class="dd">{boxes}</div></div>')

def _ftd_card(ftd):
    if not ftd:
        return ""
    def _meta(x):
        bits = []
        if x.get("ftd_date"):    bits.append(f'FTD {x["ftd_date"]}(Day{x.get("ftd_day")})')
        if x.get("ftd_low") is not None: bits.append(f'安値 {x["ftd_low"]}')
        if x.get("invalidation"): bits.append(f'割れ {x["invalidation"]}')
        return f'<div class="dddays">{"・".join(bits)}</div>'
    rows = "".join(
        f'<div class="ftd-row"><span class="ftd-x">{x["lab"]}</span>'
        f'<span class="{x["cls"]}">{x["st"]}</span>{_meta(x)}</div>' for x in ftd)
    return (f'<div class="card"><h2>フォロースルー・デイ <span class="h2en">FTD (proxy)</span></h2>'
            f'<div class="sub">前提＝<b>調整局面</b>（50日線下 or 52週高値−8%以下）。安値後の最初のプラス引け＝Day1、'
            f'<b>Day4以降に前日比+1.25%以上×出来高増</b>で点灯（最初の1回で確定）。'
            f'試行安値割れ（日中）＝数え直し／<b>終値がFTD日の安値を割る＝失敗</b>／'
            f'FTD後に調整を脱してから再び調整入り＝無効化。時間経過では消さない。<br>'
            f'</div>'
            f'{rows}</div>')

def _ext_card(perf):
    """指数の200日線乖離（参考表示）。+12〜15%超で青モードでも新規勝率↓、+5〜10%が妙味。"""
    if not perf or not perf.get("indices"):
        return ""
    rows = []
    for ix in perf["indices"]:
        e = ix.get("ext200")
        if e is None or (isinstance(e, float) and np.isnan(e)):
            ev, ek, ecls = "—", "通常", "ex-warn"
        else:
            ep = e * 100
            if   ep >= 15:  ek, ecls = "過熱（押し目待ち）", "ex-bad"
            elif ep >= 12:  ek, ecls = "やや過熱",         "ex-bad"
            elif ep >= 5:   ek, ecls = "妙味",            "ex-good"
            elif ep >= -2:  ek, ecls = "通常",            "ex-warn"
            else:           ek, ecls = "200日割れ近辺",    "ex-bad"
            ev = f"{ep:+.1f}%"
        rows.append(f'<div class="exrow"><div class="exk">{ix["label"]}</div>'
                    f'<div class="exv">{ev}</div>'
                    f'<div class="exn {ecls}">{ek}</div></div>')
    return (f'<div class="card"><h2>指数の200日線乖離</h2>'
            f'<div class="sub">+12〜15%超は過熱（青でも新規は押し目待ち）／+5〜10%が妙味。'
            f'フィルタではなく地合いの過熱度メーター</div>'
            f'<div class="extbl">{"".join(rows)}</div></div>')

_COLOR_RANK = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}
_COLOR_JP = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}

def load_trend_history(cur_color, asof_date, persist=True, strict=False, fail_closed=False):
    """trend_history.jsonへ今日の色を追記し (history, prev_color) を返す。
    persist=False（selftest/diag）: 書き込まない。strict=True（offline selftest）: 明示env以外は読まない。"""
    import json
    env_p = os.environ.get("V38_TREND_JSON")
    if strict:
        paths = [env_p]
    else:
        paths = [env_p, os.path.join(os.path.dirname(CACHE), "trend_history.json"),
                 "/mnt/project/trend_history.json", "trend_history.json"]
    path = next((p for p in paths if p and os.path.exists(p)), None)
    today = str(asof_date)
    hist = []
    if strict:
        # 明示fixture(テスト)は破損/schema不一致なら停止（再現性のため）。
        if path:
            hist = _load_json_safe(path, [], "trend_history.json", fail_closed=True, validator=_validate_trend_schema) or []
        # strictでも未来日は不正として停止（テストの意図）
        _future = [hc for hc in hist if hc and hc[0] > today]
        if _future:
            raise SystemExit(f"[FATAL] trend_history に as-of({today}) より未来の日付が含まれます: {_future[:3]}")
    else:
        # 本番: 実履歴は『拒否』でなく『修復』。旧schema/余分な列/重複/未来日があっても有効分だけ残す。
        raw = None
        if path:
            raw = _load_json_raw(path)
            if raw is None:
                raw = _load_json_raw(path + ".prev")
                if raw is not None:
                    sys.stderr.write("[trend] %s parse失敗; .prev から復元\n" % path)
        else:
            for _base in [env_p, os.path.join(os.path.dirname(CACHE), "trend_history.json")]:
                if _base and os.path.exists(_base + ".prev"):
                    raw = _load_json_raw(_base + ".prev")
                    break
        _before = len(raw) if isinstance(raw, list) else 0
        hist = _sanitize_trend_history(raw or [], asof=today)
        if _before and len(hist) < _before:
            sys.stderr.write("[trend] 修復: %d→%d エントリ（不正/重複/未来日を除去）\n" % (_before, len(hist)))
    prev = None
    for d, c in reversed(hist):
        if d != today and c:
            prev = c; break
    hist = [hc for hc in hist if hc and hc[0] != today]   # upsert today
    if cur_color:
        hist.append([today, cur_color])
    hist = hist[-120:]
    if persist:
        outp = path or env_p or os.path.join(os.path.dirname(CACHE), "trend_history.json")
        _atomic_write_json_with_prev(outp, hist)          # 失敗はcommitで検知（例外送出）
    return hist, prev

def _trend_history_path():
    return (os.environ.get("V38_TREND_JSON") or os.path.join(os.path.dirname(CACHE), "trend_history.json"))

def save_trend_history(hist):
    """画面生成時に確定した履歴(_thist)をそのまま保存（commitで再読込せず、表示と保存を一致させる・#3）。"""
    _atomic_write_json_with_prev(_trend_history_path(), hist)

def trend_phrase(prev, cur):
    """Transition-aware phrase for the trend pill (色変化でコメントを変える)."""
    if not cur:
        return "判定不可"
    if not prev or prev == cur:
        return {"Blue": "強い上昇が継続", "Green": "上昇(中位)が継続",
                "Yellow": "弱含みが継続", "Red": "下落が継続"}.get(cur, cur)
    arrow = f"{_COLOR_JP.get(prev, prev)}→{_COLOR_JP.get(cur, cur)}"
    improving = _COLOR_RANK.get(cur, -1) > _COLOR_RANK.get(prev, -1)
    if improving:
        msg = {"Blue": "上昇が加速", "Green": "弱含みから持ち直し(中位)",
               "Yellow": "下げ止まり・様子見"}.get(cur, "改善")
    else:
        msg = {"Green": "上昇一服(中位へ減速)", "Yellow": "弱含みへ転換",
               "Red": "下落へ転換・回避"}.get(cur, "悪化")
    return f"{arrow} {msg}"

def broad_vs_cap_note(vals):
    """時価加重と等加重を同じ時間軸で比較し、相場の広がりを1行で返す。"""
    try:
        last = vals.iloc[-1]
    except Exception:
        return None
    def avg(*ks):
        xs = [last.get(k) for k in ks if last.get(k) == last.get(k)]
        return (sum(xs) / len(xs)) if xs else None
    # まず50日軸で比較。欠損時だけ200日軸へフォールバックする。
    cap = avg("qqq_50", "spy_50")
    broad = avg("rsp_50", "qqqe_50")
    if cap is None or broad is None:
        cap = avg("qqq_200", "spy_200")
        broad = avg("rsp_200")
    if cap is None or broad is None:
        return None
    cu, bu = cap > 0, broad > 0
    if cu and bu:
        return ("広く強い：時価加重・等加重とも上向き", "pos")
    if cu and not bu:
        return ("細い相場：指数は上向き、等加重は弱い", "neg")
    if (not cu) and bu:
        return ("循環：大型株は調整、等加重は底堅い", "pos")
    return ("全面安：時価加重・等加重とも下向き", "neg")

def _net_liq_read(nl):
    """ネット流動性を素人にも分かる解釈に変換：(短ラベル, cls, 平易な説明)。
       気にすべきか無視していい範囲かを明示。4週変化($兆)で判定。"""
    if not nl or not nl.get("vals"):
        return None
    ch = nl.get("chg4w")
    if not _finite(ch):
        return None
    if ch >= 0.15:
        return ("追い風", "pos", "流動性が増加中＝株の支援材料")
    if ch >= 0.04:
        return ("やや追い風", "pos", "流動性はやや増加＝リスクオン寄り")
    if ch <= -0.15:
        return ("警戒", "neg", "流動性が減少中＝株の重石・戻り売り注意")
    if ch <= -0.04:
        return ("やや警戒", "neg", "流動性はやや減少＝単独では弱いが注意")
    return ("中立", "mut", "ほぼ横ばい＝今は気にしなくてよい")


def _market_comment(aux, mkt, sar, breadth, cat_html=""):
    """Market opening narrative: readable in about 20 seconds and directly reusable on X.

    The visible block carries the story. A native <details> panel keeps the supporting
    diagnostics available without taking permanent vertical space.
    """
    def finite(v):
        try: return v is not None and np.isfinite(float(v))
        except Exception: return False
    def ts_delta(ts, lag):
        vals = [float(v) for _, v in (ts or []) if finite(v)]
        return (vals[-1] - vals[-1-lag]) if len(vals) > lag else None
    def dnum(v, suffix=""):
        return "—" if not finite(v) else f"{float(v):+.0f}{suffix}"
    def dpct(v):
        return "—" if not finite(v) else f"{float(v)*100:+.1f}%"
    def dirof(ts, up, dn):
        if not ts or len(ts) < 60: return None
        st, _ = _trend_state([v for _, v in ts], up, dn)
        return "横ばい" if st == "中立" else st
    def pick_index(prefix):
        for x in ((mkt.get("perf") or {}).get("indices") or []):
            if str(x.get("label", "")).startswith(prefix): return x
        return {}
    def rank_one(recs, key, top=True):
        arr = [x for x in (recs or []) if finite(x.get(key))]
        if not arr: return None
        arr.sort(key=lambda x: float(x[key]), reverse=top)
        return arr[0]
    def lead_text(rec, key):
        if not rec: return "—"
        return f'{rec.get("ja") or rec.get("label") or rec.get("tk") or "—"} {dpct(rec.get(key))}'
    def period_sector(key):
        sr = mkt.get("sector_ranks") or {}
        mac = sr.get("macro") or []
        mic = sr.get("micro") or []
        tm = rank_one(mac, key, True); tn = rank_one(mic, key, True)
        wm = rank_one(mac, key, False); wn = rank_one(mic, key, False)
        tops = [lead_text(x, key) for x in (tm, tn) if x]
        weaks = [lead_text(x, key) for x in (wm, wn) if x]
        return ("・".join(tops) if tops else "—", "・".join(weaks) if weaks else "—")
    def names(xs, n=2):
        return "・".join(str(x.get("ja") or x.get("sub") or x.get("tk")) for x in xs[:n]) if xs else "—"

    slope = {"↑":"上向き", "→":"横ばい", "↓":"鈍化"}.get(aux.get("slope"), aux.get("slope"))
    band = mri_band(aux["hl"])[0].replace("（過熱・反落注意⚠）", "（過熱気味）")
    score = float(aux.get("cur") or 0.0)
    sd1, sd5, sd21 = (ts_delta(mkt.get("mri_ts"), x) for x in (1, 5, 21))
    bd5, bd21 = (ts_delta(mkt.get("breadth_ts"), x) for x in (5, 21))

    qqq, spy = pick_index("NASDAQ"), pick_index("S&P500")
    today_top, today_weak = period_sector("d1")
    week_top, week_weak = period_sector("w1")
    month_top, month_weak = period_sector("m1")

    bts = mkt.get("breadth_ts", [])
    pa200 = bts[-1][1] if bts else breadth.get("pa200")
    bd = dirof(bts, "拡大", "縮小")
    ad = dirof(mkt.get("adline_ts", []), "改善", "悪化")
    cr = dirof(mkt.get("credit_ts", []), "良好", "悪化")
    vt = mkt.get("vixterm_ts", []); vv = vt[-1][1] if vt else None
    vx = "平穏" if finite(vv) and vv < .95 else "注意" if finite(vv) and vv <= 1 else "逆転" if finite(vv) else "—"
    dv = mkt.get("dollarvol_ts"); ut = (dv.get("uni_trend") or {}) if isinstance(dv, dict) else {}
    turn = ut.get("dir") if ut.get("sig") else "横ばい"
    warn = [k for k, v in (mkt.get("distrib") or {}).items() if v.get("n", 0) >= 6]
    rst = mkt.get("regime_state") or {}; pulse = mkt.get("lead_pulse") or {}

    det = sum([bd == "縮小", ad == "悪化", cr == "悪化", vx == "逆転", bool(warn), turn == "縮小"])
    imp = sum([bd == "拡大", ad == "改善", cr == "良好", turn == "拡大"])
    if det >= 3: verdict = "内部悪化が優勢。新規は絞る。"
    elif imp >= 3 and det == 0: verdict = "中身を伴う上昇。押し目を優先。"
    elif det >= 2 and imp >= 2: verdict = "強弱が割れている。選別を強める。"
    elif det > imp: verdict = "やや守り優勢。確認を待つ。"
    else: verdict = "地合いは安定。ルール通り継続。"
    if aux.get("hl", 0) >= 60 and sar and sar[0] in ("Yellow", "Red"):
        verdict += " 指数トレンドを優先。"

    if finite(sd5) and finite(sd21):
        if sd5 >= 2 and sd21 >= 2: change = "短期・1カ月とも改善"
        elif sd5 >= 2 and sd21 < 0: change = "1カ月低下の中で短期反発"
        elif sd5 < 0 and sd21 >= 2: change = "1カ月上向き、足元は一服"
        elif sd5 <= -2 and sd21 <= -2: change = "短期・1カ月とも悪化"
        else: change = "方向感は横ばい"
    else:
        change = "変化判定はデータ待ち"

    rrg = mkt.get("rrg_etf") or []
    center = sorted([x for x in rrg if x.get("q") == "主導"], key=lambda x: -float(x.get("x", 0)))
    improving = sorted([x for x in rrg if x.get("cross") or x.get("q") == "改善"],
                       key=lambda x: (not bool(x.get("cross")), -float(x.get("y", 0))))
    weakening = sorted([x for x in rrg if x.get("q") == "弱化"], key=lambda x: float(x.get("y", 0)))
    sec = mkt.get("sectors_rs") or []
    early = sorted([x for x in sec if x.get("rot") == "初動"], key=lambda x: -float(x.get("d_w1", 0)))
    if not early:
        early = sorted([x for x in sec if x.get("rot") == "改善"], key=lambda x: -float(x.get("d_w1", 0)))

    nq_col = _COLOR_JP.get(sar[0], "—") if sar else "—"
    nq_phrase = trend_phrase(mkt.get("trend_prev"), sar[0] if sar else None)
    em = mkt.get("emergency") or {}
    emtxt = "非常口発動・レバ半減" if em.get("active") else "非常口待機" if em.get("available") else "非常口判定不可"

    advp = breadth.get("adpct")
    _advf = float(advp) if finite(advp) else None
    qd = qqq.get("d1")
    if finite(qd) and _advf is not None:
        if float(qd) >= .006 and _advf >= 60:
            hook = "指数高だけでなく、個別にも買いが広がる強い上昇"
        elif float(qd) > 0 and _advf < 45:
            hook = "指数は上昇。ただし買いは一部の大型株に偏る"
        elif float(qd) < 0 and _advf >= 55:
            hook = "指数は軟調でも、個別株の中身は崩れていない"
        elif float(qd) <= -.006 and _advf < 40:
            hook = "指数も個別も売られるリスクオフ"
        else:
            hook = "指数は小動き。セクターと銘柄の選別が中心"
    elif finite(qd):
        hook = "指数の方向は確認。ただし騰落データは未取得"
    else:
        hook = "指数・騰落データを確認中"

    gate_action = {
        "Blue": "押し目を優先。急騰は追わない。",
        "Green": "個別は継続、レバは半分。質の高い形だけ拾う。",
        "Yellow": "新規は止め、保有銘柄の出口管理を優先。",
        "Red": "新規なし。現金化とリスク縮小を優先。",
    }.get(sar[0] if sar else None, "ゲート判定を確認。")
    if em.get("active"):
        gate_action += " 非常口発動中でレバはさらに半減。"

    score_line = f'Health {score:.0f}（日 {dnum(sd1)}／週 {dnum(sd5)}／月 {dnum(sd21)}）'
    breadth_line = f'200MA上 {pa200:.0f}%（週 {dnum(bd5, "pt")}／月 {dnum(bd21, "pt")}）' if finite(pa200) else '200MA上 —'
    risk_line = f'信用 {cr or "—"}・VIX構造 {vx}' + (f'・売り抜け {"/".join(warn)}' if warn else '')

    # ---- 総括（下の詳細分析を凝縮した"結論"。内部・先導株・資金・マクロを具体的に、最後に行動） ----
    _COL_JP = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}
    _regime = sar[0] if sar else None
    _syn = []
    # 1) 相場の中身（売り抜け・新高値・広がり）
    _dd_max = max(((v.get("n") or 0) for v in (mkt.get("distrib") or {}).values()), default=0)
    _pnh = breadth.get("pnh")
    _inner = []
    if _dd_max >= 6:
        _inner.append(f"売り抜け日が最も多い指数で{_dd_max}日まで積み上がり、内部は明確に劣化")
    elif _dd_max >= 4:
        _inner.append(f"売り抜け日は最も多い指数で{_dd_max}日とやや売り圧力")
    if finite(_pnh):
        _inner.append(f"新高値{_pnh:.0f}%と" + ("拡大" if _pnh >= 15 else ("縮小し弱い" if _pnh < 5 else "限定的")))
    if finite(advp):
        _inner.append(f"上昇銘柄{advp:.0f}%で広がりは" + ("狭く一部主導" if advp < 45 else ("良好" if advp >= 60 else "中位")))
    if _inner:
        _syn.append("相場の中身は" + "・".join(_inner))
    # 2) 先導株の質
    _all3 = pulse.get("all3"); _f1 = (mkt.get("reg_hist") or {}).get("f1_now")
    _lead = []
    if isinstance(_all3, (int, float)):
        _lead.append(f"RS3期間85超（RS21/63/189）の質の高いリーダー{_all3}銘柄で層は" + ("薄い" if _all3 < 8 else "厚い"))
    if isinstance(_f1, (int, float)):
        _f1p = _f1 * 100 if _f1 <= 1.5 else _f1
        if _f1p >= 30:
            _lead.append(f"脱落率{_f1p:.0f}%で先導株から崩れ始め")
    if _lead:
        _syn.append("先導株は" + "・".join(_lead))
    # 3) 資金の向き
    if week_top and week_top != "—":
        _w = f"資金は{week_top.split(' ')[0]}へ"
        if week_weak and week_weak != "—":
            _w += f"、{week_weak.split(' ')[0]}から流出"
        _syn.append(_w)
    # 4) マクロ（流動性＋クレジット）
    _nlr = _net_liq_read(mkt.get("net_liq"))
    _mb = []
    if _nlr:
        _mb.append(f"流動性は{_nlr[0]}")
    if cr == "悪化":
        _mb.append("クレジット悪化で株より先に傷むサイン")
    elif cr == "良好":
        _mb.append("クレジットは落ち着き")
    if _mb:
        _no_head = (not _nlr or _nlr[1] != "neg") and cr != "悪化"
        _syn.append("マクロは" + "・".join(_mb) + ("で逆風は乏しい" if _no_head else "で逆風が強まる"))
    # 5) 結論（行動）
    _gate = {"Blue": "押し目を積極的に拾う", "Green": "質の高い形に絞って継続・レバは抑えめ",
             "Yellow": "新規は止め、保有の出口管理を優先", "Red": "現金化とリスク縮小を優先"}.get(_regime, "ルール通り継続")
    narrative = ("。".join(_syn) + f"。結論として、地合いは{_COL_JP.get(_regime, '—')}——{_gate}。") if _syn else ""

    # ネット流動性の1行（コピー用ポストにも入れる）
    _nl = mkt.get("net_liq")
    nl_post = ""
    if _nl and _nlr:
        _c4 = _nl.get("chg4w")
        _c4t = (f"{_c4:+.2f}" if finite(_c4) else "—")
        nl_post = f'【流動性】ネット流動性 ${_nl["last"]:.2f}T（4週{_c4t}）→ {_nlr[0]}：{_nlr[2]}。'

    post_lines = [
        "米国株・セクターローテーション定点観測 🔄",
        f'【今日】{hook}。QQQ {dpct(qqq.get("d1"))}、SPY {dpct(spy.get("d1"))}、上昇銘柄 {(f"{_advf:.0f}%" if _advf is not None else "—")}。主役は {today_top}、下位は {today_weak}。',
        f'【1週間】QQQ {dpct(qqq.get("w1"))}、SPY {dpct(spy.get("w1"))}。資金が集まったのは {week_top}、弱いのは {week_weak}。',
        f'【1カ月】QQQ {dpct(qqq.get("m1"))}、SPY {dpct(spy.get("m1"))}。主役は {month_top}、下位は {month_weak}。',
        f'【変化】{score_line}。{change}、{breadth_line}。',
    ] + ([nl_post] if nl_post else []) + [
        f'【ローテ】主導 {names(center, 3)}／初動 {names(early, 3)}／弱化 {names(weakening, 3)}。',
        f'【地合い】NQ {nq_col}（{nq_phrase}）。{risk_line}。{gate_action}',
    ]
    post_text = "\n".join(post_lines)
    post_html = "".join(
        f'<div class="mkt-post-line"><b>{_html.escape(line.split("】",1)[0] + "】")}</b>{_html.escape(line.split("】",1)[1])}</div>'
        if line.startswith("【") and "】" in line else f'<div class="mkt-post-hook">{_html.escape(line)}</div>'
        for line in post_lines
    )

    f1 = lambda v: f'{v*100:.0f}%' if finite(v) else '—'
    note = mkt.get("broad_note")
    note_html = f'<div class="cmt-note cmt-{note[1]}">{note[0]}</div>' if note else ''
    _p50v = breadth.get("pa50")
    _p50s = (f'{float(_p50v):.0f}%' if finite(_p50v) else '—')
    def _nlchg(k):
        v = _nl.get(k) if isinstance(_nl, dict) else None
        return (f'{float(v):+.2f}' if finite(v) else '—')
    deep = [
        ("相場の中身", f'50MA上 {_p50s}・200MA上 {pa200:.0f}%・騰落 {ad or "—"}・幅 {bd or "—"}・売買代金 {turn}' if finite(pa200) else f'50MA上 {_p50s}・騰落 {ad or "—"}・幅 {bd or "—"}・売買代金 {turn}'),
    ] + ([("流動性", f'ネット流動性 ${_nl["last"]:.2f}T（4週{_nlchg("chg4w")}／13週{_nlchg("chg13w")}）→ {_nlr[0]}。{_nlr[2]}')] if (_nl and _nlr) else []) + [
        ("リーダー", f'RS63/126/189すべて85以上 {pulse.get("all3", 0)}・定着 {pulse.get("stable", 0)}・失速 {pulse.get("fade", 0)}・中心テーマ {_h(pulse.get("top_theme") or "—")}'),
        ("リスク", f'{risk_line}・{emtxt}'),
        ("先行灯", f'F1 リーダー脱落 {f1(rst.get("f1"))}・F2 勢い細り {f1(rst.get("f2"))}・F3 下落余地 {f1(rst.get("f3"))}'),
        ("資金移動", f'主導 {names(center, 3)}・改善 {names(improving, 3)}・弱化 {names(weakening, 3)}・初動 {names(early, 3)}'),
    ]
    detailed = ''.join(f'<div class="mkt20-deep"><span>{_h(k)}</span><b>{_h(v)}</b></div>' for k, v in deep)
    narrative_html = f'<div class="mkt20-read">{_html.escape(narrative)}</div>' if narrative else ''
    cat_section = f'<div class="mkt20-cats">{cat_html}</div>' if cat_html else ''
    return (
        f'<div class="card cmt mkt20"><div class="mkt20-top"><div><h2>今日のマーケット</h2>'
        f'<div class="mkt20-verdict">{verdict}</div></div>'
        f'<div class="mkt20-score"><b>{score:.0f}</b><span>{band}</span><em>傾き {slope}</em></div></div>'
        f'{narrative_html}{note_html}{cat_section}'
        f'<details class="mkt-fold"><summary><span>コピー用ポスト・数字と根拠</span><span class="mkt-fold-state"></span></summary>'
        f'<div class="mkt-post-tools"><span>X投稿用</span>'
        f'<button class="copybtn mkt-copy" onclick="copyBlock(event,\'mktPostText\')">コピー</button></div>'
        f'<div id="mktPostText" class="mkt-post">{post_html}</div>'
        f'<div class="mkt-fold-body" style="margin-top:9px">{detailed}</div></details></div>'
    )


def _rotation_comment(mkt):
    """Rotation is integrated into the 20-second market digest to avoid duplicate prose."""
    return ""


def build_categorized_commentary(mkt, m, breadth, sar, aux):
    """市況を5カテゴリ（マーケット/指数/個別株/セクター/市況）×時間軸で網羅コメント。素人にも分かる言葉で。"""
    def fin(v):
        try:
            return v is not None and np.isfinite(float(v))
        except Exception:
            return False
    def pct(v):
        return f"{float(v)*100:+.1f}%" if fin(v) else "—"
    def dnum(v, s=""):
        return f"{float(v):+.0f}{s}" if fin(v) else "—"
    def idx(pfx):
        for x in ((mkt.get("perf") or {}).get("indices") or []):
            if str(x.get("label", "")).startswith(pfx):
                return x
        return {}
    def ts_d(ts, lag):
        vs = [float(v) for _, v in (ts or []) if fin(v)]
        return (vs[-1] - vs[-1-lag]) if len(vs) > lag else None
    qqq, spy = idx("NASDAQ"), idx("S&P500")
    sr = mkt.get("sector_ranks") or {}
    mac = sr.get("macro") or []
    def sec(key):
        arr = [x for x in mac if fin(x.get(key))]
        if not arr:
            return None
        arr.sort(key=lambda x: -float(x[key]))
        return (arr[0].get("ja") or "—", pct(arr[0].get(key)), arr[-1].get("ja") or "—", pct(arr[-1].get(key)))
    def top_tk(col, n=3):
        if m is None or not hasattr(m, "sort_values") or col not in m.columns:
            return "—"
        dd = m.sort_values(col, ascending=False).head(n)
        return "・".join(str(dd.loc[t].get("ticker", t)) for t in dd.index) or "—"

    _CJP = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}
    blocks = []

    # ---- 内部シグナルを収集（数字ではなく傾向の分析に使う） ----
    distrib = mkt.get("distrib") or {}
    def dd_n(*pfx):
        for k, v in distrib.items():
            if any(p.lower() in str(k).lower() for p in pfx):
                return v.get("n")
        return None
    qqq_dd, spy_dd = dd_n("qqq", "nasdaq"), dd_n("spy", "s&p")
    dd_max = max(((v.get("n") or 0) for v in distrib.values()), default=0)
    dd_detail = "・".join(f"{k} {(v.get('n') or 0)}日" for k, v in distrib.items()) or "—"
    ftd = mkt.get("ftd") or []
    ftd_ok = any((not it.get("invalidation")) and it.get("ftd_date") for it in ftd) if ftd else False
    dv = mkt.get("dollarvol_ts") or {}
    ut = (dv.get("uni_trend") or {}) if isinstance(dv, dict) else {}
    vol_dir = ut.get("dir") if ut.get("sig") else "横ばい"
    pnh = breadth.get("pnh")
    lp = mkt.get("lead_pulse") or {}
    all3, stable, fade_l = lp.get("all3"), lp.get("stable"), lp.get("fade")
    rh = mkt.get("reg_hist") or {}
    _rst7 = mkt.get("regime_state") or {}
    def pf(v):
        return (v * 100 if fin(v) and v <= 1.5 else (v if fin(v) else None))
    f1 = pf(rh.get("f1_now")); f3 = pf(_rst7.get("f3"))
    if f3 is None: f3 = pf(rh.get("f3_now"))
    lr = mkt.get("leader_run") or {}
    acc, fade_r = lr.get("acc"), lr.get("fade")
    rrg = mkt.get("rrg_etf") or []
    def rq(q):
        return [x.get("ja") or x.get("label") or x.get("tk") for x in rrg if x.get("q") == q]
    center = rq("主導")
    improving = [x.get("ja") or x.get("label") for x in rrg if x.get("q") == "改善" or x.get("cross")]
    weakening = rq("弱化")

    # 1) マーケット（地合いの内部と方向）
    regime = _CJP.get(sar[0], "—") if sar else "—"
    st = (mkt.get("regime_state") or {}).get("streak")
    score = float(aux.get("cur") or 0)
    sd1, sd5, sd21 = (ts_d(mkt.get("mri_ts"), x) for x in (1, 5, 21))
    pa50 = breadth.get("pa50")
    p50 = (pa50 * 100 if fin(pa50) and pa50 <= 1.5 else pa50)   # 50MA上比率（買いの広がり判定用）
    _adp = breadth.get("adpct")
    adp = (_adp * 100 if fin(_adp) and _adp <= 1.5 else _adp)   # 真の当日上昇銘柄率
    def scdir(v):
        return "改善" if fin(v) and v >= 2 else ("悪化" if fin(v) and v <= -2 else "横ばい")
    stance = {"青": "積極的にリスクを取れる", "緑": "リスクは取れるが選別", "黄": "守り優先・新規は慎重", "赤": "守り最優先"}.get(regime, "")
    _stk = f'（{st}日連続）' if isinstance(st, int) else ''
    _bq = ("広く買われている" if fin(p50) and p50 >= 60 else ("一部の主力に偏る" if fin(p50) and p50 < 45 else "まずまず"))
    _ddq = ("内部が劣化し要警戒" if dd_max >= 6 else ("やや重い" if dd_max >= 4 else "健全"))
    blocks.append(("マーケット", "Regime", [
        ("日次", f'地合いは{regime}{_stk}で{stance}局面。前日スコア{dnum(sd1)}＝{scdir(sd1)}。' + (f'上昇銘柄{adp:.0f}%・50MA上{p50:.0f}%で買いの広がりは{_bq}。' if fin(adp) and fin(p50) else (f'50MA上{p50:.0f}%で買いの広がりは{_bq}。' if fin(p50) else ''))),
        ("週次", f'スコアは週{dnum(sd5)}＝{scdir(sd5)}。売り抜け(distribution)は{dd_detail}で、多い指数が6日以上なら内部劣化のサイン。{_ddq}。'),
        ("月次", f'スコアは月{dnum(sd21)}＝{scdir(sd21)}。' + ("フォロースルー(FTD)を確認済みで反発に裏付けあり。" if ftd_ok else "フォロースルー(FTD)は未確認で本格反発の裏付けは乏しい。")),
    ]))

    # 2) 指数（値動きより中身：出来高・新高値・売り抜け・FTD）
    def volnote(ret):
        if vol_dir == "拡大":
            return "出来高増を伴い" + ("下げ＝売り圧力が強い" if fin(ret) and ret < 0 else "上げ＝買いが本物")
        if vol_dir == "縮小":
            return "出来高細り＝" + ("投げ一巡の兆し" if fin(ret) and ret < 0 else "上値追いの勢いは限定的")
        return "出来高は平常"
    _nhq = ("拡大" if fin(pnh) and pnh >= 15 else ("縮小し内部は弱い" if fin(pnh) and pnh < 5 else "限定的"))
    blocks.append(("指数", "Indices", [
        ("日次", f'QQQ {pct(qqq.get("d1"))}・SPY {pct(spy.get("d1"))}。{volnote(qqq.get("d1"))}。' + (f'52週高値銘柄{pnh:.0f}%で新高値は{_nhq}。' if fin(pnh) else '')),
        ("週次", f'QQQ {pct(qqq.get("w1"))}・SPY {pct(spy.get("w1"))}。' + (f'売り抜けはQQQ {qqq_dd}日・SPY {spy_dd}日＝' + ("6日以上で内部劣化・戻りは慎重" if (qqq_dd or 0) >= 6 or (spy_dd or 0) >= 6 else "許容範囲で押し目は機能") + '。' if qqq_dd is not None else '')),
        ("月次", f'QQQ {pct(qqq.get("m1"))}・SPY {pct(spy.get("m1"))}。' + ("直近FTDありで押し目反発に裏付け。" if ftd_ok else "FTD未確認＝戻りは戻り売りに警戒。")),
    ]))

    # 3) 個別株（先導株の状況・質・持続性）
    _ls = ""
    if fin(acc) and fin(fade_r):
        _ls = f'先導株は加速{acc:.0f}／失速{fade_r:.0f}で勢いは' + ("細り気味＝選別を厳しく" if fade_r > acc else "健全") + '。'
    _layer = ""
    if fin(all3):
        _layer = f'RS3期間85超（RS21/63/189）の質の高いリーダーは{all3}銘柄で層は' + ("薄い（トレンドの土台が細い）" if all3 < 8 else "厚い") + '。'
    _f1n = (f'脱落率(F1){f1:.0f}%で先導株から' + ("崩れ始め" if f1 >= 30 else "まだ安定") + '。') if fin(f1) else ''
    blocks.append(("個別株", "Stocks", [
        ("短期(1ヶ月)", f'RS21上位：{top_tk("rs21")}。足元で急伸。' + _ls),
        ("中期(3ヶ月)", f'RS63上位：{top_tk("rs63")}。' + (f'定着{stable}銘柄で中期の担い手は' + ("厚い" if fin(stable) and stable >= 5 else "限定的") + '。' if fin(stable) else '')),
        ("長期(9ヶ月)", f'RS189上位：{top_tk("rs189")}。' + _layer + _f1n),
    ]))

    # 4) セクター（内部＝出来高/構成銘柄＋クロス期間で弱化を検出）
    weak_all, fading, emerging = [], [], []
    for x in mac:
        d1v, w1v, m1v = x.get("d1"), x.get("w1"), x.get("m1")
        ja = x.get("ja") or "—"
        if fin(w1v) and fin(m1v):
            if w1v < 0 and m1v < 0 and (not fin(d1v) or d1v < 0):
                weak_all.append(ja)
            elif m1v > 0.02 and w1v < -0.005:
                fading.append(ja)
            elif m1v < -0.005 and w1v > 0.02:
                emerging.append(ja)
    def secline(key):
        s = sec(key)
        return f'主導 {s[0]}（{s[1]}）／弱い {s[2]}（{s[3]}）' if s else "—"
    _rrgline = ""
    if center or improving or weakening:
        _rrgline = f'。RRG象限では主導 {"・".join(x for x in center[:2] if x) or "—"}／改善(初動) {"・".join(x for x in improving[:2] if x) or "—"}／弱化 {"・".join(x for x in weakening[:2] if x) or "—"}'
    trend_bits = []
    if weak_all:
        trend_bits.append(f'全期間で弱く資金流出が明確なのは{"・".join(weak_all[:2])}')
    if fading:
        trend_bits.append(f'月は強いが週で失速の兆しは{"・".join(fading[:2])}')
    if emerging:
        trend_bits.append(f'新たに資金が向かい始めたのは{"・".join(emerging[:2])}')
    blocks.append(("セクター", "Sectors", [
        ("日次", secline("d1")),
        ("週次", secline("w1") + _rrgline),
        ("月次", secline("m1")),
        ("傾向", ("。".join(trend_bits) + "。") if trend_bits else "—"),
    ]))

    # 5) 市況（マクロ・解釈付き）
    nl = mkt.get("net_liq"); nlr = _net_liq_read(nl)
    mc = mkt.get("macro_context") or {}
    def lv(sid):
        v = (mc.get(sid) or {}).get("vals") or []
        try:
            return float(v[-1][1])
        except Exception:
            return None
    y2, y10 = lv("DGS2"), lv("DGS10")
    senti = mkt.get("senti") or {}; perf = mkt.get("perf") or {}
    vix = perf.get("vix"); vix = vix.get("cur") if isinstance(vix, dict) else vix
    pc = senti.get("pc")
    curve, infl = lv("T10Y3M"), lv("T5YIFR")
    _day = []
    if fin(vix): _day.append(f'VIX {vix:.1f}（' + ("リスクオフ" if vix >= 20 else ("落ち着き" if vix < 16 else "中立")) + '）')
    if fin(pc): _day.append(f'P/C {pc:.2f}')
    if fin(y2) and fin(y10): _day.append(f'金利2年{y2:.2f}%/10年{y10:.2f}%')
    _cv = ""
    if fin(curve):
        _cv = ("逆イールドで景気後退シグナル点灯" if curve < -0.1 else "カーブは正常で後退シグナルなし")
    blocks.append(("市況(マクロ)", "Macro", [
        ("日次", ("・".join(_day) + "。心理と金利の当日水準。") if _day else "—"),
        ("週次", (f'ネット流動性 ${nl["last"]:.2f}T＝{nlr[0]}。{nlr[2]}' if nl and nlr else "—")),
        ("構造", ((_cv + (f'。期待インフレ{infl:.2f}%' if fin(infl) else '') + "。景気後退/インフレの織り込み。") if _cv else "—")),
    ]))

    def blk(title, en, rows):
        body = "".join(
            f'<div class="ccrow"><span class="cctf">{tf}</span><span class="cctxt">{txt}</span></div>'
            for tf, txt in rows if txt and txt != "—")
        if not body:
            return ""
        return f'<div class="ccblock"><div class="cchd">{title}<span class="cchd-en">{en}</span></div>{body}</div>'
    body = "".join(blk(t, e, r) for t, e, r in blocks)
    return body  # 内側ブロックのみ（今日のマーケットカードに統合するため枠は付けない）

def build_leader_breadth(m, macro=None):
    """リーダー・ブレッドス警戒灯（レジーム心構え・売買非連動）。検証(2026-07-07)より2段階:
       第1警戒(最速・天井の平均45日前): 脱落率＝20日前に上位24だったRS銘柄のうち現在36位外に落ちた割合 ≥30%。
       第2警戒(確認・平均26日前): 上位24(189日RS)のうち63日RS<85が ≥40%（勢い細りのポート版）。
       ※短期タイミング予測力はゼロ（中間帯）。生存バイアスで両指標とも過小評価＝実際はもっと早く点く可能性。"""
    rs = m["rs"].dropna(); rs189 = m["rs189"].dropna()
    rsl1 = m["rs_l1"].dropna() if "rs_l1" in m.columns else pd.Series(dtype=float)
    if len(rs) < 45 or len(rsl1) < 45 or len(rs189) < 45:
        return None
    # 第1: 脱落率（20日前=rs_l1で上位24 → 現在rsで36位外）
    rank_now = rs.rank(ascending=False)
    then24 = rsl1.rank(ascending=False)
    then24 = list(then24[then24 <= LEADER_BREADTH_BASE_N].index)
    if len(then24) < 12:
        return None
    dropped = sum(1 for t in then24 if (t not in rank_now.index) or float(rank_now.get(t, 9999)) > LEADER_BREADTH_DROP_RANK)
    dropout = dropped / len(then24)
    # 脱落した銘柄（旧上位24 → 現在36位外）: (ティッカー, 現在順位, $出来高)
    def _dv(t):
        try: return float(m.at[t, "dvol"]) if (t in m.index and m.at[t, "dvol"] == m.at[t, "dvol"]) else 0.0
        except Exception: return 0.0
    dropped_list = sorted(
        [(t, float(rank_now.get(t, 9999)), _dv(t), float(rs.get(t, float("nan")))) for t in then24
         if (t not in rank_now.index) or float(rank_now.get(t, 9999)) > LEADER_BREADTH_DROP_RANK],
        key=lambda x: -x[1])
    # 第2: 上位24(189日RS)のうち 63日RS<85 の割合
    top189 = rs189.rank(ascending=False)
    top189 = list(top189[top189 <= LEADER_BREADTH_BASE_N].index)
    faded = sum(1 for t in top189 if float(rs.get(t, 100)) < 85)
    fade = faded / max(1, len(top189))
    faded_list = sorted(
        [(t, float(rs189.get(t, 0)), float(rs.get(t, 0)), _dv(t)) for t in top189 if float(rs.get(t, 100)) < 85],
        key=lambda x: x[2])   # 63日RSが低い順
    # QQQ 高値からの経過（確認シグナル・予兆ではない）
    dsh = None
    if macro is not None and macro.get("QQQ") is not None:
        cc = macro["QQQ"]["Close"].dropna().iloc[-252:]
        if len(cc) > 20:
            dsh = int(len(cc) - 1 - int(np.argmax(cc.values)))
    s1 = "警戒" if dropout >= LEADER_DROPOUT_WARN else "注意" if dropout >= LEADER_DROPOUT_CAUTION else "平常"
    s2 = "深刻" if fade >= LEADER_FADE_SEVERE else "警戒" if fade >= LEADER_FADE_WARN else "平常"
    # 総合心構え
    if s1 == "警戒" and s2 in ("警戒", "深刻"):
        mood, mcol = "最警戒（両方点灯・防御態勢へ）", "#f87171"
    elif s1 == "警戒":
        mood, mcol = "第1警戒（地殻変動の初動・身構える）", "#fb923c"
    elif s2 in ("警戒", "深刻"):
        mood, mcol = "第2警戒（痛みが本物・防御態勢へ移行）", "#fb923c"
    elif s1 == "注意":
        mood, mcol = "注意（内部が痛み始め）", "#eab308"
    else:
        mood, mcol = "平常（リーダー健在）", "#4ade80"
    return dict(dropout=dropout, fade=fade, s1=s1, s2=s2, dsh=dsh, mood=mood, mcol=mcol,
                n_then=len(then24), n189=len(top189),
                dropped_list=dropped_list, faded_list=faded_list)

def build_tenbagger_l1(m):
    """テンバガー・レーダー L1（検証: <$20×ADR≥5×RS≥60×上場4年未満でP≈10.3%/リフト29.7x）。
       宝くじ帳簿・本体と分離。生存バイアスで割引後の実態6-8%。捕獲は広トレール、サイズ≤0.25%/本。"""
    try:
        pool = m[(m["dvol"] >= DVOL_FLOOR) & (m["close"] >= 5)].copy()
        if len(pool) < 20:
            return ""
        # L1条件: 低位<$20 × ADR≥5% × RS189≥60 × (52週高値圏でない=まだ上げ切っていない)
        rows = []
        for t, r in pool.iterrows():
            px = r.get("close"); adr = r.get("adr"); rs189 = r.get("rs189"); d52 = r.get("dist52")
            if px is None or px != px or px >= 20: continue
            if adr is None or adr != adr or adr < 0.05: continue
            if rs189 is None or rs189 != rs189 or rs189 < 60: continue
            rows.append(dict(t=t, px=float(px), adr=float(adr)*100, rs=float(rs189),
                             d52=float(d52)*100 if d52 == d52 else 0.0, dvol=r.get("dvol")))
        rows.sort(key=lambda x: -x["rs"])
        rows = rows[:24]
        if not rows:
            return ""
        chips = "".join(
            f'<span class="tbchip" data-liq="{(x["dvol"] or 0)/1e6:.1f}" data-tkone="{x["t"]}">'
            f'<span class="tbtk">{x["t"]}</span>'
            f'<span class="tbmeta">${x["px"]:.0f}・ADR{x["adr"]:.0f}%・RS189 {x["rs"]:.0f}</span></span>'
            for x in rows)
        return (f'<div class="card"><h2>テンバガー・レーダー <span class="tbbadge">宝くじ枠</span></h2>'
                f'<div class="sub"><b>3年内10倍の生息地</b>を機械抽出（該当{len(rows)}銘柄）。'
                f'52週高値圏からは生まれない（安く・若く・荒い所から）＝本体システムとは別の帳簿。</div>'
                f'<div class="tbgrid">{chips}</div>'
                f'<div class="note"><b>L1条件</b>: 株価&lt;$20 × ADR≥5% × RS189≥60（検証: P≈10.3%/リフト29.7x）。'
                f'生存バイアスで割引後の実態6-8%＝<b>9割は外れる</b>。サイズは<b>≤0.25%/本の宝くじ枠</b>、捕獲装置は広トレール（当てるのでなく掴んだ1本を離さない）。'
                f'テンバガーは「ベア底×次サイクル主導テーマ」で群生（2020/04・2022-23AI群）。※本体の12枠選定には</div></div>')
    except Exception as e:
        print("[warn] tenbagger L1 failed:", e)
        return ""

def build_defense_checklist(st):
    """点灯した灯ごとに、その灯が実測で答える問いに対応する行動だけを出す。
       各灯の点灯=警戒(bad)水準。売買ルール本体は変えない（心構えと執行の質のみ）。"""
    if not st:
        return ""
    f1_on = st.get("c1") == "reg-bad"          # 脱落 ≥30%
    f2_on = st.get("c2") == "reg-bad"          # 勢い細り ≥40%
    f3_on = st.get("c3") == "reg-bad"          # キュー崩れ ≥60%
    if not (f1_on or f2_on or f3_on):
        return ""
    lit = []
    if f1_on: lit.append("F1")
    if f2_on: lit.append("F2")
    if f3_on: lit.append("F3")
    items = ""
    if f1_on:
        items += ('<li><b>F1 点灯（天井ゾーン・中央48日前）</b>'
                  '<ul><li>構えを防御に切り替える。枠を無理に埋めない</li>'
                  '<li>この局面のリーダー群を記録（転換時に+28.8%で回帰する候補）</li></ul></li>')
    if f2_on:
        items += ('<li><b>F2 点灯（確定が近い・中央32日前）</b>'
                  '<ul><li>新規サイズを絞る（0.75%リスク/件 → 確信度の低いものは半分に）</li>'
                  '<li>レバの途中参入を止める（SOXL/TQQQの新規トランシェを保留）</li></ul></li>')
    if f3_on:
        items += ('<li><b>F3 点灯（深い下落の確率1.84倍）</b>'
                  '<ul><li>裁量スイングは+25%到達玉の⅓利確を確実に。<b>Core 12はピーク×0.70トレール維持（途中利確しない＝二層出口は不採用）</b></li>'
                  '<li>全保有のピーク×0.70距離を点検。近い玉から目視レビュー</li></ul></li>')
    return (f'<div class="card def-card"><h2>⚠ 防御チェックリスト <span class="def-badge">{"・".join(lit)} 点灯</span></h2>'
            f'<div class="sub">点灯した灯に対応する行動だけを表示。<b>売買ルール本体（地合いゲートとRS選定）は変えない</b>。</div>'
            f'<ul class="def-list">{items}</ul>'
            f'<div class="note">'
            f'<p>3灯は別々の問いに答えるため<b>足し算しない</b>。F1・F2は「いつ」（赤転換までの先行）、F3は「どれくらい深いか」（条件付きDD倍率）を答える。</p>'
            f'<p>これは心構えと執行の質を上げるトリガーであって自動売買ではない。短期タイミングの売買予測力はゼロ（検証済み）。</p>'
            f'</div></div>')

def build_transition_leaders(m, macro):
    """転換初動リーダーボード（警戒灯の裏面）。検証(49局面)より、−10%DDから底→回復の初動は
       "旧リーダー回帰"が圧勝(+28.8%/勝率86%)。ディフェンシブは来ない・新顔≒QQQ。
       トリガー: QQQが直近の−10%超DDの安値から+5%回復。旧リーダー=約42日前の63日RS上位20。
       ※底は事後的にしか分からない＝2段階警戒灯が緑に戻り始めた時に開くリスト（心構え・ウォッチ用）。"""
    q = macro.get("QQQ") if macro else None
    if q is None or "rs_l2" not in m.columns:
        return None
    c = q["Close"].dropna()
    if len(c) < 60:
        return None
    win = c.iloc[-90:] if len(c) >= 90 else c
    hi = float(win.cummax().iloc[-1])
    lo = float(win.min()); lo_i = int(np.argmin(win.values))
    cur = float(c.iloc[-1])
    dd_at_low = lo / float(win.iloc[:lo_i + 1].cummax().iloc[-1]) - 1   # 安値時点のDD深さ
    off_low = cur / lo - 1 if lo > 0 else 0.0
    dd_now = cur / hi - 1
    active = (dd_at_low <= -0.10 and off_low >= 0.05 and lo_i < len(win) - 2)
    rsl2 = m["rs_l2"].dropna()
    if len(rsl2) < 20:
        return None
    old = list(rsl2.sort_values(ascending=False).head(20).index)
    rows = []
    for t in old:
        if t not in m.index:
            continue
        r = m.loc[t]
        cl = r.get("close"); ema = r.get("ema21"); rv = r.get("rvol")
        if cl is None or cl != cl:
            continue
        reclaim = bool(ema == ema and cl > ema)
        volrec = bool(rv == rv and float(rv) >= 1.0)
        rows.append(dict(t=t, rs=float(r.get("rs") or 0), rs189=float(r.get("rs189") or 0),
                         reclaim=reclaim, volrec=volrec, dvol=r.get("dvol"),
                         score=(2 if reclaim else 0) + (1 if volrec else 0)))
    rows.sort(key=lambda x: (-x["score"], -x["rs"]))
    ready = sum(1 for r in rows if r["reclaim"] and r["volrec"])
    return dict(active=active, dd_now=dd_now, off_low=off_low, dd_at_low=dd_at_low,
                leaders=rows, ready=ready)

def _transition_leaders_card(tl):
    if not tl or not tl.get("leaders"):
        return ""
    act = tl["active"]
    head = ("#4ade80" if act else "#9fb0c5")
    status = (f'● 回復初動が進行中（安値から +{tl["off_low"]*100:.0f}%・DD最深 {tl["dd_at_low"]*100:.0f}%）'
              if act else f'○ 待機中（QQQは高値から {tl["dd_now"]*100:.0f}%・−10%DDからの回復トリガー未成立）')
    chips = ""
    for r in tl["leaders"][:16]:
        if r["reclaim"] and r["volrec"]:
            cls, mk = "tl-go", "◎奪回+出来高"
        elif r["reclaim"]:
            cls, mk = "tl-ok", "○21EMA奪回"
        else:
            cls, mk = "tl-wait", "・待ち"
        chips += (f'<span class="chip {cls}" data-liq="{(r["dvol"] or 0)/1e6:.1f}" data-tkone="{r["t"]}">'
                  f'{r["t"]} <span class="mut" style="font-size:10px">RS189 {r["rs"]:.0f}・{mk}</span></span>')
    return (f'<div class="card"><div class="hdr"><h2>転換初動リーダーボード</h2>{_cp([r["t"] for r in tl["leaders"][:16]])}</div>'
            f'<div class="sub">警戒灯の<b>裏面</b>。−10%DDから底→回復の初動は、検証(49局面)で<b>旧リーダー回帰が圧勝</b>'
            f'（+28.8%/勝率86%）。ディフェンシブは来ない・新顔≒QQQ。<b>約42日前(DD入口)の63日RS上位20</b>が、'
            f'今<b>21EMAを奪回＋出来高回復</b>したら初動候補。※底は暫定（安値更新で変わる）。</div>'
            f'<div class="lbmood" style="color:{head}">{status} ・ 奪回+出来高 {tl["ready"]}/20</div>'
            f'<div class="lbchips"><span class="lbcl">旧リーダー（DD入口の上位20）</span>{chips}</div>'
            f'<div class="lbnote"><b>面取り</b>：個別が確認できるまでは TQQQ/SOXL の投入帯（50MA上0〜3%）で"面"を取る→旧リーダー確認で個別へ（段階論）。'
            f'<b>但し書き</b>：底は事後的にしか分からない＝<b>2段階警戒灯が緑に戻り始めた時に開くリスト</b>（売買シグナルではない）。'
            f'生存バイアスで個別リターンは過大評価。</div></div>')

def _leader_breadth_card(lb):
    """リーダー・ブレッドス警戒灯カード（2段階・心構え専用）。"""
    if not lb:
        return ""
    def bar(frac, thA, thB):
        p = min(100, max(0, frac * 100))
        col = "#f87171" if frac >= thB else "#eab308" if frac >= thA else "#4ade80"
        return (f'<div class="lbbar"><div class="lbfill" style="width:{p:.0f}%;background:{col}"></div>'
                f'<div class="lbmark" style="left:{thA*100:.0f}%"></div>'
                f'<div class="lbmark" style="left:{thB*100:.0f}%"></div></div>')
    dsh = (f'QQQ高値から <b>{lb["dsh"]}営業日</b>' if lb.get("dsh") is not None else "QQQ高値 —")
    dl = lb.get("dropped_list") or []
    fl = lb.get("faded_list") or []
    drop_chips = ("".join(
        f'<span class="chip warn" data-liq="{dv/1e6:.1f}" data-tkone="{t}">{t} '
        f'<span class="mut" style="font-size:10px">RS63 {r63:.0f}・{"圏外" if nr>900 else str(int(nr))+"位"}</span></span>'
        for t, nr, dv, r63 in dl) if dl else '<span class="mut">なし</span>')
    fade_chips = ("".join(
        f'<span class="chip warn" data-liq="{dv/1e6:.1f}" data-tkone="{t}">{t} '
        f'<span class="mut" style="font-size:10px">RS63 {r63:.0f}</span></span>'
        for t, r189, r63, dv in fl) if fl else '<span class="mut">なし</span>')
    return (f'<div class="card"><h2>リーダー・ブレッドス警戒灯</h2>'
            f'<div class="sub"><b>売買シグナルではなく"心構え"の装置</b>（短期の下落タイミングは予測しない）。'
            f'検証で、指数天井の<b>3〜8週間前</b>に点灯する早期警戒。あなたの「勢い細り」の<b>ポートフォリオ版</b>。</div>'
            f'<div class="lbmood" style="color:{lb["mcol"]}">● {lb["mood"]}</div>'
            f'<div class="lbrow"><div class="lbk">第1警戒 脱落率 <span class="mut">（最速・平均45日前）</span></div>'
            f'<div class="lbv">{lb["dropout"]*100:.0f}%<span class="mut">・{lb["s1"]}</span></div></div>'
            f'{bar(lb["dropout"],0.15,0.30)}'
            f'<div class="lbsub">20日前に上位{LEADER_BREADTH_BASE_N}だったRS銘柄のうち、現在{LEADER_BREADTH_DROP_RANK}位外に落ちた割合。<b>≥{LEADER_BREADTH_DROPOUT_WARN*100:.0f}%で警戒</b>。</div>'
            f'<div class="lbchips"><span class="lbcl">脱落した銘柄</span>{drop_chips}</div>'
            f'<div class="lbrow"><div class="lbk">第2警戒 勢い細り率 <span class="mut">（確認・平均26日前）</span></div>'
            f'<div class="lbv">{lb["fade"]*100:.0f}%<span class="mut">・{lb["s2"]}</span></div></div>'
            f'{bar(lb["fade"],0.40,0.60)}'
            f'<div class="lbsub">上位{LEADER_BREADTH_BASE_N}（189日RS）のうち、63日RSが85未満に萎えた割合。<b>≥{LEADER_BREADTH_FADE_WARN*100:.0f}%で防御態勢へ</b>（≥60%は予測力も1.6x）。</div>'
            f'<div class="lbchips"><span class="lbcl">勢い細りの銘柄</span>{fade_chips}</div>'
            f'<div class="lbnote">{dsh}（高値途絶は"確認"であって予兆ではない・序列は脱落→勢い細り→高値途絶）。'
            f'<b>但し書き</b>: これは売買シグナルではない（中間帯の予測力ゼロ）／生存バイアスで過小評価＝実際はもっと早く点く可能性。</div></div>')

def build_leader_run(m, k=24):
    """先導株モメンタム・ラン: 現リーダー(189日RS上位k)の63日RSの軌跡(42日前→21日前→現在)で
       ランの局面を分類。加速=ラン拡大／巡航=高値維持／失速=ラン細り(=個別勢い細り・H2で自動売買は不可、表示専用)。
       思想(添付): 序列が信頼区間・表示専用の裁量/心構え材料。均等分散×ワイドトレールの本体は触らない。"""
    if "rs189" not in m.columns or "rs_l1" not in m.columns or "rs_l2" not in m.columns:
        return None
    lead = m[m["rs189"].notna()].sort_values("rs189", ascending=False).head(k)
    if len(lead) < 6:
        return None
    rows = []
    for t, r in lead.iterrows():
        rs = float(r.get("rs") or 0); l1 = float(r.get("rs_l1") or rs); l2 = float(r.get("rs_l2") or l1)
        d_recent = rs - l1          # 直近21日のRS変化
        d_mid = l1 - l2             # その前21日のRS変化
        if rs >= 90 and d_recent >= 3:
            phase, pcls = "加速", "run-acc"
        elif rs < 85 and d_recent <= -3:
            phase, pcls = "失速", "run-fade"
        elif d_recent <= -8:
            phase, pcls = "失速", "run-fade"
        elif rs >= 85 and abs(d_recent) < 5:
            phase, pcls = "巡航", "run-cru"
        elif d_recent >= 3:
            phase, pcls = "加速", "run-acc"
        else:
            phase, pcls = "巡航", "run-cru"
        rows.append(dict(t=t, rs=rs, l1=l1, l2=l2, d_recent=d_recent, d_mid=d_mid,
                         phase=phase, pcls=pcls, dvol=r.get("dvol")))
    order = {"加速": 0, "巡航": 1, "失速": 2}
    rows.sort(key=lambda x: (order[x["phase"]], -x["d_recent"]))
    n = len(rows)
    acc = sum(1 for r in rows if r["phase"] == "加速")
    fade = sum(1 for r in rows if r["phase"] == "失速")
    if acc >= fade * 2 and acc >= n * 0.3:
        health, hcol = "ラン拡大（先導株の勢いが伸びている）", "#4ade80"
    elif fade > acc:
        health, hcol = "ラン細り（勢いが失われつつある・防御寄り）", "#fb923c"
    else:
        health, hcol = "巡航（高値維持・方向感は中立）", "#9fb0c5"
    return dict(rows=rows, n=n, acc=acc, fade=fade, health=health, hcol=hcol)

def _leader_run_card(lr):
    if not lr or not lr.get("rows"):
        return ""
    def traj(r):
        # 42日前 → 21日前 → 現在 の63日RS軌跡（矢印で方向）
        a = "↑" if r["d_mid"] >= 3 else "↓" if r["d_mid"] <= -3 else "→"
        b = "↑" if r["d_recent"] >= 3 else "↓" if r["d_recent"] <= -3 else "→"
        return f'{r["l2"]:.0f} {a} {r["l1"]:.0f} {b} <b>{r["rs"]:.0f}</b>'
    order = {"失速": 0, "巡航": 1, "加速": 2}   # 失速を先頭に(防御上いちばん見たい)
    rows = sorted(lr["rows"], key=lambda r: (order.get(r["phase"], 3), -r["d_recent"]))
    chips = ""
    for r in rows:
        chips += (f'<span class="mrchip {r["pcls"]}" data-liq="{(r["dvol"] or 0)/1e6:.1f}" data-tkone="{r["t"]}">'
                  f'<span class="mrtk">{r["t"]}</span>'
                  f'<span class="mrph">{r["phase"]}</span>'
                  f'<span class="mrtr">{traj(r)}</span></span>')
    return (f'<div class="card"><div class="hdr"><h2>先導株モメンタム・ラン</h2>{_cp([r["t"] for r in rows])}</div>'
            f'<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">現リーダー（RS189上位{lr["n"]}）の63日RSの軌跡（42日前→現在）。<b class="mr-acc">加速</b>＝拡大／<b class="mr-cru">巡航</b>＝維持／<b class="mr-fad">失速</b>＝細り</div></details>'
            f'<div class="lbmood" style="color:{lr["hcol"]}">● {lr["health"]} ・ 加速{lr["acc"]} / 失速{lr["fade"]}（{lr["n"]}中）</div>'
            f'<div class="mrgrid">{chips}</div>'
            f'<div class="lbnote">数字＝63日RSパーセンタイル。失速は出口線を意識——執行は確定出口線で（予兆での自動売却はしない）。</div></div>')

def build_leader_temp(W, win=CHART_LB):
    """先導株の強さ温度計: 先導株(RS189上位10%)の63日リターン平均の、過去分布に対する%タイル系列。
       予測でなく現状描写。非対称=左端(枯渇)のみNQ底に中央値18日先行(的中6割)/右端(過熱)は先取りせず。"""
    closes = W.get("Close")
    if closes is None or closes.shape[0] < 200:
        return None
    r63 = closes / closes.shift(63) - 1
    rs189 = closes / closes.shift(189) - 1
    lead = []
    idx = closes.index
    for i in range(189, len(idx)):
        rr = r63.iloc[i]; rk = rs189.iloc[i]
        valid = rk.dropna()
        if len(valid) < 30:
            lead.append(np.nan); continue
        thr = valid.quantile(0.90)
        top = rr[rk >= thr].dropna()
        lead.append(float(top.mean()) if len(top) else np.nan)
    lead_s = pd.Series(lead, index=idx[189:]).dropna()
    if len(lead_s) < 60:
        return None
    # #29: 各点を「その時点までのトレーリング窓」内の%タイルに（全期間rankだと過去点が未来データを使う）
    _wp = min(504, len(lead_s))
    pctile = lead_s.rolling(_wp, min_periods=60).apply(
        lambda x: float((x <= x.iloc[-1]).mean() * 100), raw=False).dropna()
    if len(pctile) < 10:
        return None
    cur = float(pctile.iloc[-1])
    # 推移: 直近 win 営業日・%タイル（他グラフと同じ表示期間・密度）
    tail = pctile.iloc[-win:]
    ts = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in tail.items()]
    # 実際の期間ラベルを動的生成（表記と実データのズレを防ぐ）
    if len(tail) >= 2:
        _mo = round((tail.index[-1] - tail.index[0]).days / 30.44)
        _y, _m = _mo // 12, _mo % 12
        span_label = (f"{_y}年{_m}ヶ月" if _y and _m else f"{_y}年" if _y else f"{_m}ヶ月")
    else:
        span_label = "—"
    return dict(cur=cur, ts=ts, span=span_label)

def _leader_temp_card(lt):
    """先導株の強さ: %タイル推移（マーケットステータスと同形式のゾーン塗り折れ線）。"""
    if not lt or not lt.get("ts"):
        return ""
    cur = lt["cur"]; ts = lt["ts"]; span = lt.get("span", "")
    zone = ("枯渇（反発予兆）" if cur < 10 else "過熱（現状の強さ）" if cur >= 82 else
            "強（過熱手前）" if cur >= 65 else "並" if cur >= 30 else "やや枯渇")
    # 推移SVG: _svg_mri と同じ幾何・帯域塗り（%タイル0-100固定）
    ys = [v for _, v in ts]; n = len(ys)
    if n < 3:
        chart = ""
    else:
        Wd, Ht, pad = 680, 180, 6
        def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
        def Y(v): return pad + (1 - v/100) * (Ht - 2*pad)
        zones = [(0,10,"#1f6feb"),(10,30,"#22c55e"),(30,65,"#64748b"),(65,82,"#d29922"),(82,100,"#ef4444")]
        zr = "".join(f'<rect x="{pad}" y="{Y(z1):.1f}" width="{Wd-2*pad}" '
                     f'height="{max(0.0,Y(z0)-Y(z1)):.1f}" fill="{zc}" opacity="0.07"/>' for z0,z1,zc in zones)
        gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="#1c2533" stroke-width="1"/>'
                     f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g}</text>'
                     for g in (10,30,65,82))
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i,v in enumerate(ys))
        svg = (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">{zr}{gl}'
               f'<polyline points="{pts}" fill="none" stroke="#e6edf3" stroke-width="2"/>'
               f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="#e6edf3"/></svg>')
        chart = (f'<div class="chart">{svg}'
                 f'{_date_axis(ts)}</div>')
    return (
        f'<div class="card"><div class="chd"><h2>リーダーの強さ</h2>'
        f'<div class="chd-now" style="color:#5b6b7f"><b>{cur:.0f}%</b><span>{zone}</span></div></div>'
        f'<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">リーダー群（RS189上位10%）の勢いを過去分布の%タイルで表示・{span}</div></details>'
        f'{chart}'
        f'</div>')

def build_structure_pivot_screen(m, s2t=None):
    """記事(Advanced Structure Pivot)を参考にしたLL→HL構造スクリーナー。
       フィボナッチ・TP・フェーズ別ストップは使用せず、Low/High/Closeによる簡略版。RS63主軸・RS189文脈。"""
    hd = ('<div class="card"><div class="hdr"><h2>底打ち（構造ピボット） <span class="h2en">Structure Pivot</span></h2></div>')
    if m is None or "sp" not in getattr(m, "columns", []):
        return hd + '<div class="empty">データなし</div></div>'
    try:
        u = m[setup_eligible(m)].copy()
    except Exception as _e:
        sys.stderr.write("[structure_pivot] eligibility failed: %r\n" % (_e,))
        u = m.iloc[0:0].copy()

    def _rs(t, col):
        try:
            v = u.at[t, col]
            return float(v) if (col in u.columns and v == v) else None
        except Exception:
            return None

    rows = [(t, u.at[t, "sp"]) for t in u.index if isinstance(u.at[t, "sp"], dict)]
    if not rows:
        return hd + '<div class="sub">現在、条件を満たす底打ち構造なし（LL→HLの安値切り上げが出ていない）。</div></div>'
    # 出来高減（売り枯れ＝健全）を最優先 → RS63順
    rows.sort(key=lambda x: (0 if x[1].get('vdry') else 1, -(_rs(x[0], 'rs63') or -1)))
    _stg = {'base': ('底固め', 'sp-hl'), 'confirm': ('上放れ確認', 'sp-confirm'), 'retest': ('ブレイク後リテスト', 'sp-retest')}
    body = []
    for t, sp in rows[:24]:
        r63 = _rs(t, 'rs63'); r189 = _rs(t, 'rs189')
        lab, cls = _stg.get(sp.get('stage'), ('底固め', 'sp-hl'))
        p2 = sp.get('p2'); rhd = sp.get('rh_dist')
        th = ""
        try:
            th = theme_of(t, s2t) if s2t else ""
        except Exception:
            th = ""
        vtag = ' <span class="sp-vdry">出来高減</span>' if sp.get('vdry') else ''
        impr = ' <span class="sp-impr">短期優位</span>' if (r63 is not None and r189 is not None and r63 > r189 + 5) else ''
        extras = []
        if r63 is not None:
            extras.append(f'<span class="mvr-e{" hot" if r63 >= 80 else ""}">RS63 {r63:.0f}</span>')
        if r189 is not None:
            extras.append(f'<span class="mvr-e">RS189 {r189:.0f}</span>')
        if th:
            extras.append(f'<span class="mvr-th">{_h(th)}</span>')
        if rhd is None:
            rhtxt = ''
        elif rhd >= 0:
            rhtxt = f'上放れ +{rhd:.0f}%'
        else:
            rhtxt = f'P2まで +{-rhd:.0f}%'
        e21l = _rs(t, 'ema21l'); pxc = _rs(t, 'close')
        risk = ((e21l / pxc - 1) * 100) if (e21l and pxc and e21l < pxc) else None
        lvls = (f'<div class="sp-lvls">LL ${sp.get("ll_px",0):.2f} → HL ${sp.get("hl_px",0):.2f} → 反発高値 ${sp.get("p2_px",0):.2f}'
                f' ・ 切上げ+{sp.get("hl_gain",0):.0f}% ・ HL {sp.get("hl_age",0)}日前'
                + (f' ・ 21EMA Low ${e21l:.2f}（撤退リスク {risk:.1f}%）' if risk is not None else '') + '</div>')
        body.append(f'<div class="mvr sp-row" data-tkone="{t}">'
                    f'<div class="sp-top"><span class="mvr-t">{t} <span class="stratbadge {cls}">{lab}</span>{vtag}{impr}</span>'
                    f'<span class="mvr-x">{"".join(extras)}</span>'
                    f'<span class="mvr-v mut" style="font-weight:700">{rhtxt}</span></div>'
                    f'{lvls}</div>')
    return (hd + '<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">'
            'LL→高い安値(HL)の<b>安値切り上げ構造</b>を検出（フィボ不使用・構造のみ）。'
            '段階：底固め（反発高値未突破）→上放れ確認（反発高値突破）→ブレイク後リテスト（突破後の押し戻し）。'
            '<b>［出来高減］＝HL付近の出来高がLL付近より枯れている＝売り枯れの健全な下げ止まり（最優先表示）</b>。'
            'RS63主軸（適格ユニバース内の約3か月リターン順位。SPY比率ではない）、RS189は文脈（低=早期/高=リーダー押し目底）。'
            '「短期優位」＝RS63がRS189を上回る。撤退目安は<b>21EMA Low</b>（プランナーと統一）。行タップで詳細。</div></details>'
            + f'<div class="mv-wrap">{"".join(body)}</div></div>')


def build_movers_tab(m, s2t=None):
    """投資対象ユニバース内のパフォーマンス上位・下位（前日/1週/1ヶ月）。
       3窓一致（継続モメンタム）・市場サマリー・RVOL/RS189/テーマ付き。"""
    _hd = ('<div class="card"><div class="hdr"><h2>値動き 上位・下位 <span class="h2en">Movers</span></h2></div>')
    if m is None or not hasattr(m, "columns") or "ret1" not in getattr(m, "columns", []):
        return _hd + '<div class="empty">データなし</div></div>'
    def _fin(x):
        try:
            return x is not None and float(x) == float(x)
        except Exception:
            return False
    # #1: 適格条件を他タブ（Pickup/W30/Structure Pivot）と統一＝投資対象ユニバース（setup_eligible）
    try:
        u = m[setup_eligible(m)].copy()
    except Exception as _e:
        sys.stderr.write("[movers] eligibility failed: %r\n" % (_e,))
        u = m.iloc[0:0].copy()
    n_uni = int(len(u))
    periods = [("ret1", "前日"), ("ret5", "1週間"), ("ret21", "1ヶ月")]

    def _th(tk):
        try:
            return theme_of(tk, s2t) if s2t else ""
        except Exception:
            return ""

    # 各期間の上位/下位20（3窓一致の判定に使う）
    top_sets, bot_sets = {}, {}
    for col, _ in periods:
        if col in u.columns:
            s = u[col].dropna()
            top_sets[col] = set(s.nlargest(20).index) if not s.empty else set()
            bot_sets[col] = set(s.nsmallest(20).index) if not s.empty else set()
        else:
            top_sets[col] = set(); bot_sets[col] = set()
    up3 = top_sets["ret1"] & top_sets["ret5"] & top_sets["ret21"]
    dn3 = bot_sets["ret1"] & bot_sets["ret5"] & bot_sets["ret21"]

    def _row(tk, v, cls):
        extras = []
        try:
            rv = u.at[tk, "rvol_pre"] if ("rvol_pre" in u.columns and _fin(u.at[tk, "rvol_pre"])) else (u.at[tk, "rvol"] if "rvol" in u.columns else None)
            if _fin(rv):
                extras.append(f'<span class="mvr-e{" hot" if float(rv) >= 2 else ""}">RVOL{float(rv):.1f}</span>')
        except Exception:
            pass
        try:
            if "rs189" in u.columns and _fin(u.at[tk, "rs189"]):
                _rs = float(u.at[tk, "rs189"]); extras.append(f'<span class="mvr-e{" hot" if _rs >= 90 else ""}">RS189 {_rs:.0f}</span>')
        except Exception:
            pass
        th = _th(tk)
        if th:
            extras.append(f'<span class="mvr-th">{_h(th)}</span>')
        b3 = '<span class="mvr-3w">3窓</span>' if (tk in up3 or tk in dn3) else ''
        return (f'<div class="mvr" data-tkone="{tk}"><span class="mvr-t">{tk}{b3}</span>'
                f'<span class="mvr-x">{"".join(extras)}</span>'
                f'<span class="mvr-v {cls}">{float(v) * 100:+.1f}%</span></div>')

    def _col(ser, cls, head):
        rows = [_row(tk, v, cls) for tk, v in ser.items()]
        head_html = f'<div class="mv-col-h {cls}">{head}</div>'
        if len(rows) <= 10:
            return head_html + "".join(rows) or head_html + '<div class="mvr mut">—</div>'
        return (head_html + "".join(rows[:10])
                + f'<details class="cxpl"><summary>11〜20位</summary>{"".join(rows[10:])}</details>')

    # ① 市場サマリー
    sum_rows = []
    for col, lab in periods:
        if col not in u.columns:
            continue
        s = u[col].dropna()
        if s.empty:
            continue
        _bt = {"ret1": 0.03, "ret5": 0.07, "ret21": 0.12}.get(col, 0.03)
        med = float(s.median()) * 100; adv = float((s > 0).mean()) * 100
        n_up = int((s >= _bt).sum()); n_dn = int((s <= -_bt).sum())
        _btp = int(_bt * 100)
        tone = "pos" if adv >= 55 else ("neg" if adv < 45 else "mut")
        sum_rows.append(f'<div class="mv-sum"><b>{lab}</b>　中央値 <span class="{tone}">{med:+.1f}%</span>'
                        f'　上昇 {adv:.0f}%　+{_btp}%以上 {n_up}　−{_btp}%以下 {n_dn}</div>')
    sum_block = ('<div class="mv-sec-h">① 本日の値動きサマリー</div>' + "".join(sum_rows)) if sum_rows else ""

    # ② 継続モメンタム（3窓一致）
    def _chips(tks):
        try:
            ordered = sorted(tks, key=lambda t: -(float(u.at[t, "ret21"]) if _fin(u.at[t, "ret21"]) else -9))
        except Exception:
            ordered = list(tks)
        return "・".join(ordered) if ordered else "—"
    mom_block = ('<div class="mv-sec-h">② 3窓一致（1日・1週・1ヶ月すべてで上位/下位20＝相対的に一貫して強い/弱い）</div>'
                 f'<div class="mv-mom"><div class="mv-mom-l pos">3窓上位</div><div class="mv-mom-b">{_chips(up3)}</div></div>'
                 f'<div class="mv-mom"><div class="mv-mom-l neg">3窓下位</div><div class="mv-mom-b">{_chips(dn3)}</div></div>')

    # ③ 期間別 上位/下位（1日は展開・1週/1ヶ月は折りたたみ）
    per_blocks = []
    for i, (col, lab) in enumerate(periods):
        if col not in u.columns:
            continue
        s = u[col].dropna()
        if s.empty:
            continue
        up = s.nlargest(20); dn = s.nsmallest(20)
        inner = (f'<div class="mv-cols"><div class="mv-col">{_col(up, "pos", "パフォーマンス上位")}</div>'
                 f'<div class="mv-col">{_col(dn, "neg", "パフォーマンス下位")}</div></div>')
        if i == 0:
            per_blocks.append(f'<div class="mv-per"><div class="mv-per-h">{lab}</div>{inner}</div>')
        else:
            per_blocks.append(f'<details class="mv-per"{"" if False else ""}><summary class="mv-per-h">{lab}</summary>{inner}</details>')
    per_block = ('<div class="mv-sec-h">③ 期間別ランキング（上位/下位20）</div>' + "".join(per_blocks)) if per_blocks else '<div class="empty">対象銘柄なし</div>'

    return (_hd
            + f'<div class="sub">投資対象ユニバース（{n_uni}銘柄・時価総額$1B以上／株価・売買代金フロア通過）内の'
              f'パフォーマンス上位・下位を前日・1週・1ヶ月で表示。終値ベースの騰落率。'
              f'<b>3窓</b>＝1日・1週・1ヶ月すべてで上位/下位＝資金が継続している銘柄。</div>'
            + f'<div class="mv-wrap">{sum_block}{mom_block}{per_block}</div></div>')


def _buy_today_card(buys):
    """本日のピックアップ＝セットアップ・スクリーナー（裁量参考）。セットアップ別のコンパクト表・タップで詳細。"""
    if not buys:
        return ('<div class="card hot-card"><h2>本日のピックアップ</h2>'
                '<div class="empty">本日の該当なし（RS63≥90のセットアップ）</div></div>')
    GMETA = {
        "ブレイク": ("st-break", "ghb-break", "新高値・出来高増"),
        "保ち合い": ("st-base",  "ghb-base",  "高値圏で収縮・出来高枯れ"),
        "押し目":   ("st-pull",  "ghb-pull",  "上昇トレンドの押し目"),
        "新高値":   ("st-high",  "ghb-high",  "高値圏・様子見"),
    }
    from collections import Counter
    cnt = Counter(b["tag"] for b in buys)
    body = []; cur = None
    for b in buys:
        if b["tag"] != cur:
            cur = b["tag"]
            gcls, gbg, gdesc = GMETA.get(cur, ("st-high", "ghb-high", ""))
            body.append(
                f'<tr class="scr-gh {gbg}"><td colspan="5">'
                f'<span class="bt-tag {gcls}">{cur}</span>'
                f'<span class="scr-gn">{cnt[cur]}件</span>'
                f'<span class="scr-gd">{gdesc}</span></td></tr>'
                f'<tr class="scr-ch {gbg}"><td class="l">銘柄</td><td>RS63</td><td>40D高値</td>'
                f'<td>出来高</td><td class="l">押し目</td></tr>')
        held = '<span class="scr-core">Core</span>' if b.get("held") else ''
        if b["tag"] == "ブレイク":                       # ブレイクは当日の出来高増(RVOL)
            rv = b.get("rvol"); vval = (f'{rv:.1f}×' if rv == rv else '—')
            vcls = "pos" if (rv == rv and rv >= 1.4) else "mut"
        else:                                            # それ以外は枯れ(vdry)
            vd = b.get("vdry"); vval = (f'{vd:.2f}×' if vd == vd else '—')
            vcls = "pos" if b.get("dry") else "mut"
        pb = b.get("pb")
        if pb == pb:
            drop = max(0.0, -pb * 100)                 # 高値からの下げ幅(%)
            w = max(2, min(100, drop / 20 * 100))      # 20%下げで満タン
            num = '0%' if drop < 0.5 else f'-{drop:.0f}%'
            poscell = (f'<span class="posbar"><span class="posfill" style="width:{w:.0f}%"></span></span>'
                       f'<span class="posn">{num}</span>')
        else:
            poscell = '—'
        body.append(
            f'<tr class="scr-row" data-liq="{(b.get("dvol") or 0)/1e6:.1f}" data-tkone="{b["t"]}">'
            f'<td class="scr-tk">{b["t"]}{held}</td>'
            f'<td class="scr-c">{b["rs"]:.0f}</td>'
            f'<td class="scr-c">${b["pivot"]:.2f}</td>'
            f'<td class="scr-c {vcls}">{vval}</td>'
            f'<td class="scr-c scr-pos">{poscell}</td></tr>')
    return (f'<div class="card hot-card"><div class="hdr"><h2>本日のピックアップ</h2>'
            f'{_cp([b["t"] for b in buys])}</div>'
            f'<div class="sub">RS63≥90・ステージ2・$10M以上。ブレイクは前日までの40日高値を終値で突破。</div>'
            f'<table class="scrtab"><tbody>' + "".join(body) + '</tbody></table></div>')


def _vcp_card(rows):
    """VCP table using contraction count, higher lows, dry volume, ATR contraction and pivot distance."""
    head = ('<div class="card"><div class="hdr"><h2>圧縮コイル（VCP）</h2>'
            + (_cp([r["t"] for r in rows]) if rows else "") + '</div>'
            '<div class="sub">収縮回数・安値切上げ・出来高枯れ・ピボット距離</div>')
    if not rows:
        return head + '<div class="empty">該当なし</div></div>'
    trs = ""
    for r in rows:
        score = max(0.0, min(100.0, float(r.get("score") or 0)))
        vd = f'{r["vdry"]:.2f}×' if pd.notna(r.get("vdry")) else "—"
        at = f'{r["atrc"]:.2f}×' if pd.notna(r.get("atrc")) else "—"
        pdist = f'{float(r["pivot_dist"])*100:+.1f}%' if pd.notna(r.get("pivot_dist")) else "—"
        _fl = [f'{int(r.get("contractions") or 0)}回']
        if r.get("higher_lows"): _fl.append("HL")
        if r.get("rsline"): _fl.append("RS新高値")
        if pd.notna(r.get("uvdv")) and float(r.get("uvdv")) >= 1.05: _fl.append("買増")
        flags = " ".join(_fl)
        trs += (f'<tr data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{r["t"]}">'
                f'<td class="l tk">{_h(r["t"])}<div class="rowsec">{_h(r["theme"])} ・ {_h(r["ind"])}</div>'
                f'<div class="rowbadges"><span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span></div></td>'
                f'<td>{r["rs"]:.0f}</td>'
                f'<td><div class="coil"><i style="width:{score:.0f}%"></i></div><span class="mut" style="font-size:10px">{score:.0f}</span></td>'
                f'<td style="white-space:nowrap">{flags}</td><td class="pos">{vd}</td><td>{at}</td><td>{pdist}</td></tr>')
    return (head + '<table><tr><th class="l">銘柄</th><th>RS189</th><th>形状</th>'
            '<th style="white-space:nowrap">収縮/印</th><th>出来高</th><th>ATR</th><th>ピボット差</th></tr>' + trs + '</table></div>')


_PAT_DESC = {
    "アンダーカット&ラリー": "安値割れから即回復",
    "3タイトクローズ": "直近3終値が1.5%以内",
    "フラットベース": "5週前後・深さ15%以内",
    "カップ・ハンドル": "上半分の浅いハンドルと出来高枯れ",
    "ハイタイトフラグ": "8週で約90%上昇後の浅い保ち合い",
}

def build_patterns(m, s2i, e2j, s2t, k=8):
    """Conservative pattern candidates. Exact chart review remains necessary for shape-sensitive patterns."""
    up50 = m["close"] > m["sma50"]
    near = m["dist52"] >= -0.25
    liq = setup_eligible(m)   # 株価・流動性・時価総額・分割疑い・除外テーマを共通適用
    pats = {
        "アンダーカット&ラリー": m[(m["ucr"] == True) & up50 & (m["rs189"] >= 70) & liq],
        "3タイトクローズ": m[(m["tc3"] <= 0.015) & (m["vdry_pre"] <= 0.90) & up50 & near & (m["rs189"] >= 80) & liq],
        "フラットベース": m[(m["stage2"] == True) & near & (m["base_depth25"] <= 0.15)
                           & (m["range20"] <= 0.15) & (m["vdry_pre"] <= 0.95) & (m["rs189"] >= 80) & liq],
        "カップ・ハンドル": m[((m["cup_ready"] == True) | (m["cup_breakout"] == True)) & (m["rs189"] >= 80) & liq],
        "ハイタイトフラグ": m[(m["ret20"] >= 0.20) & (m["ret63"] >= 0.70)
                              & (m["base_depth25"] <= 0.20) & up50 & (m["rs189"] >= 85) & liq],
    }
    out = {}
    for name, sub in pats.items():
        sortcol = "vcp_score" if name in ("3タイトクローズ", "フラットベース", "カップ・ハンドル") else "rs189"
        sub = sub[sub["rs189"].notna()].sort_values(sortcol, ascending=False).head(k)
        out[name] = [dict(t=t, rs=float(r["rs189"]), dvol=r.get("dvol")) for t, r in sub.iterrows()]
    return out

_PAT_EN = {
    "アンダーカット&ラリー": "Undercut & Rally",
    "3タイトクローズ": "3 Tight Closes",
    "フラットベース": "Flat Base",
    "カップ・ハンドル": "Cup with Handle",
    "ハイタイトフラグ": "High Tight Flag",
}

def _patterns_card(pats):
    """パターン別スキャナー・カード（チップ群）。"""
    if not pats:
        return ""
    blocks = ""
    for name, rows in pats.items():
        if rows:
            chips = "".join(
                f'<span class="chip hot" data-liq="{(r["dvol"] or 0)/1e6:.1f}" data-tkone="{r["t"]}">'
                f'{r["t"]} <span class="mut" style="font-size:10px">RS189 {r["rs"]:.0f}</span></span>' for r in rows)
        else:
            chips = '<span class="empty">該当なし</span>'
        _en = _PAT_EN.get(name, "")
        blocks += (f'<div class="patblk"><div class="patname">{name}'
                   f'{f" <span class=" + chr(34) + "h2en" + chr(34) + ">" + _en + "</span>" if _en else ""}'
                   f'<span class="mut" style="font-size:11px">・{_PAT_DESC.get(name, "")}</span></div>'
                   f'<div class="chips">{chips}</div></div>')
    _pttk = []
    for _nm, _rws in pats.items():
        _pttk += [r["t"] for r in (_rws or [])]
    return (f'<div class="card"><div class="hdr"><h2>テクニカル・パターン別</h2>{_cp(_pttk[:30])}</div>'
            f'<div class="sub">ベース・反転・タイト化</div>{blocks}</div>')



def _swing_planner_card():
    """スイング・プランナー（R建てを 円・% ・株数 に翻訳する計算機。JSが window.SWING と入力から算出）。"""
    return (
        '<div class="card"><h2>スイング・プランナー（R建てを分かりやすく）</h2>'
        '<div class="sub"><b>1銘柄＝総資産の8%</b>を2分割で買う前提。株数・ハードストップ・利確が全部 <b>円と%</b> で出ます。'
        '<b>エントリーは2分割</b>（今すぐ50% ＋ 押し目/ブレイクで50%）。<b>撤退（ハードストップ）は21EMA安値／10日線から選択</b>。'
        '許容損失は株数計算には使わず、ハードストップの位置だけに使います。</div>'
        '<div class="swin">'
        '<div class="swrow"><span class="swlab">総資産 ¥</span>'
        '<input id="swAsset" type="number" inputmode="numeric" placeholder="例 7000000" oninput="swingCalc()"></div>'
        '<div class="swrow"><span class="swlab">USD/JPY</span>'
        '<input id="swFx" type="number" inputmode="decimal" placeholder="取得中…取れなければ手入力" oninput="swingCalc()">'
        '<span class="mut" style="font-size:11px">取得値を自動入力。取得できない時のみ手入力（固定150円では計算しません）</span></div>'
        '<div class="swrow"><span class="swlab">銘柄サイズ %（総資産比）</span>'
        '<input id="swRisk" type="number" inputmode="decimal" value="8" oninput="swingCalc()">'
        '<span class="mut" style="font-size:11px">総資産に対する1銘柄の投入比率（初期8%）</span></div>'
        '<div class="swrow"><span class="swlab">候補/銘柄</span>'
        '<input id="swPick" type="text" autocomplete="off" placeholder="ティッカー入力 例 NVDA（候補から選択も可）" list="swList" oninput="swPickFill()"><datalist id="swList"></datalist></div>'
        '<div class="swrow"><span class="swlab">エントリー① $</span>'
        '<input id="swEntry" type="number" inputmode="decimal" placeholder="今すぐ50%" oninput="swingCalc()"></div>'
        '<div class="swrow"><span class="swlab">エントリー② $</span>'
        '<input id="swEntry2" type="number" inputmode="decimal" placeholder="押し目/ブレイクで50%（空欄可）" oninput="swingCalc()"></div>'
        '<div class="swrow"><span class="swlab">撤退ライン</span>'
        '<select id="swExit" onchange="swExitChange()"><option value="e21l">21EMA安値で撤退</option><option value="s10">10日線で撤退</option><option value="manual">手入力</option></select></div>'
        '<div class="swrow"><span class="swlab">ハードストップ $</span>'
        '<input id="swStop" type="number" inputmode="decimal" oninput="swStopManual()">'
        '<span class="mut" id="swStopHint" style="font-size:11px"></span></div>'
        '<div class="swrow"><span class="swlab">部分利確 +%</span>'
        '<input id="swTp" type="number" inputmode="decimal" value="25" oninput="swingCalc()">'
        '<span class="swlab" style="margin-left:8px">売る割合 %</span>'
        '<input id="swTpf" type="number" inputmode="decimal" value="33" oninput="swingCalc()">'
        '<span class="mut" style="font-size:11px">初期 +25%到達で1/3(33%)利確→残りは撤退ラインでトレール</span></div>'
        '</div>'
        '<div id="swOut" class="swout"></div>'
        # ===== 保有記録（上のプランから記録、または手動追加。この端末に保存） =====
        '<div class="swdiv"></div>'
        '<div class="swhold-h">保有中 <span class="mut" style="font-weight:400;font-size:11px">・この端末に保存・経過日数(暦日)を自動計算</span></div>'
        '<div class="mut" style="font-size:11px;margin:-4px 0 8px">Core 12（システム選定）＋裁量スイングを含む<b>実際の保有</b>。Core 12に限定されない。</div>'
        '<div class="calc-in">'
        '<div class="ci-row"><span class="ci-pre" style="font-size:12px">銘柄</span>'
        '<input id="hldTk" type="text" autocomplete="off" placeholder="例 NVDA（空欄で上のプラン銘柄）" list="hldTkList"></div>'
        '<datalist id="hldTkList"></datalist>'
        '<div class="ci-row2" style="margin-top:6px;gap:6px;align-items:center">'
        '<span class="ci-pre" style="font-size:12px;flex:0 0 auto">戦略</span>'
        '<div class="stratseg" id="hldStratSeg">'
        '<button type="button" class="stratbtn on" data-strat="core" onclick="hldStratPick(this)">Core 12</button>'
        '<button type="button" class="stratbtn" data-strat="swing" onclick="hldStratPick(this)">裁量スイング</button>'
        '</div></div>'
        '<div class="ci-row2" style="margin-top:6px;gap:6px">'
        '<input id="hldSh" type="number" inputmode="decimal" placeholder="株数(任意)">'
        '<input id="hldPx" type="number" inputmode="decimal" placeholder="建値$(任意)">'
        '<input id="hldDt" type="date"></div>'
        '<div class="ci-row2" style="margin-top:6px;gap:6px">'
        '<select id="hldSetup" class="hldsel" style="flex:1"><option value="">セットアップ（なぜ入る？・任意）</option>'
        '<option>重なり(confluence)</option><option>ポケットピボット</option><option>VCPブレイク</option>'
        '<option>底打ち(構造ピボット)</option><option>本日ブレイク</option><option>押し目(21EMA)</option>'
        '<option>リーダー継続</option><option>裁量</option><option>その他</option></select>'
        '<select id="hldConv" class="hldsel" style="flex:0 0 auto"><option value="">確信度</option>'
        '<option>高</option><option>中</option><option>低</option></select></div>'
        '<div class="ci-row2" style="margin-top:6px">'
        '<input id="hldMemo" type="text" placeholder="エントリー理由・見立て（なぜ今か／トリガー／想定リスク）" style="width:100%"></div>'
        '<details class="cxpl"><summary>記録のコツ（何を書くと後で役立つか）</summary><div class="cxpl-b">'
        '<b>入る前に一言で言語化</b>すると後の振り返りが効きます。'
        '記録推奨：①<b>セットアップ</b>（どの型か）②<b>トリガー</b>（何を見て今日入ったか）'
        '③<b>環境</b>（地合い・NQゲート＝自動記録）④<b>RS/テーマ</b>（自動記録）'
        '⑤<b>想定シナリオと無効化条件</b>（どこで撤退か）⑥<b>確信度</b>。'
        '手仕舞い時に⑦<b>結果</b>（+R/−R）⑧<b>学び</b>（次に活かす1点）を追記。'
        '下の「ノート書き出し」で全記録をノート形式で出力できます。</div></details>'
        '<div class="ci-row2" style="margin-top:6px;gap:6px">'
        '<button class="memx" onclick="hldFromPlan()">↑ 上のプランを保有に記録</button>'
        '<button class="memx" onclick="hldAdd()">＋ 手動で追加</button></div>'
        '</div>'
        '<div id="hldList"></div>'
        '</div>')


# LEGACY（未使用・参照用に残置。呼び出しなし）
def _manual_holdings_card():
    """保有記録（手入力）。買った銘柄・株数・建値・開始日をこの端末に保存し、保有日数を自動計算。"""
    return (
        '<div class="card"><h2>保有記録（手入力）</h2>'
        '<div class="sub">実際に<b>買った銘柄</b>をここに記録（この端末に保存）。保有日数は開始日から自動計算。'
        '建値を入れると現在損益も出る。<b>Core 12はシステムの選定候補</b>、ここは<b>裁量スイングも含む自分の実保有</b>（Core 12に限定されない）。</div>'
        '<div class="calc-in">'
        '<div class="ci-row"><span class="ci-pre" style="font-size:12px">銘柄</span>'
        '<input id="hldTk" type="text" autocomplete="off" placeholder="例 NVDA" list="hldTkList"></div>'
        '<datalist id="hldTkList"></datalist>'
        '<div class="ci-row2" style="margin-top:6px;gap:6px">'
        '<input id="hldSh" type="number" inputmode="decimal" placeholder="株数(任意)">'
        '<input id="hldPx" type="number" inputmode="decimal" placeholder="建値$(任意)">'
        '<input id="hldDt" type="date"></div>'
        '<div class="ci-row2" style="margin-top:6px">'
        '<button class="memx" onclick="hldAdd()">＋ 保有に追加</button></div>'
        '</div>'
        '<div id="hldList"></div></div>')


# LEGACY（未使用・参照用に残置。呼び出しなし）
def _buy_card(buys, pick_set=None):
    if not buys:
        return ('<div class="card"><h2>本日の押し目シグナル</h2>'
                '<div class="empty">本日の③該当なし</div></div>')
    rows = []
    for b in buys:
        held = f'<span class="bt-held">★トップ{N_PORT}</span>' if (pick_set and b["t"] in pick_set) else ''
        rows.append(
            f'<div class="buy" data-liq="{(b.get("dvol") or 0)/1e6:.1f}" data-tkone="{b["t"]}">'
            f'<div class="buy-h"><span class="tk">{b["t"]}</span>{held}'
            f'<span class="rs">RS {b["rs"]:.0f}</span></div>'
            f'<div class="buy-m">{b["theme"]} ・ {b["ind"]}</div>'
            f'<div class="rowbadges">'
            f'<span class="capb cap-{b["tier_key"]}">{b["tier_lab"]}</span>'
            f'{_state_badge(b.get("state",""), b.get("nut",""), b.get("nucls","mut"))}</div>'
            f'<div class="buy-g">'
            f'<div><span class="k">エントリー</span><span class="v">${b["lo"]:.2f}〜${b["hi"]:.2f}</span></div>'
            f'<div><span class="k">−25%ストップ</span><span class="v neg">${b["lo"]*0.75:.2f}</span></div>'
            f'<div><span class="k">利確</span><span class="v mut">ピーク×0.70</span></div>'
            f'<div><span class="k">押し目</span><span class="v">{fmt_pct(b["pb"])}</span></div>'
            f'<div><span class="k">ADR</span><span class="v">{fmt_pct0(b["adr"])}</span></div>'
            f'<div><span class="k">RVOL</span><span class="v">{b["rvol"]:.1f}</span></div>'
            f'</div></div>')
    return (f'<div class="card"><div class="hdr"><h2>本日の押し目シグナル <span class="role-tag rt-act">仕掛ける</span></h2>'
            f'{_cp([b["t"] for b in buys])}</div>'
            f'<div class="sub">RS90以上の主力（リーダー）で押し目が成立した銘柄。<b>押し目</b>＝直近高値からの下げ幅、<b>ADR</b>＝1日の平均値幅（値動きの荒さ）、<b>RVOL</b>＝平常比の出来高（注目度）。エントリー幅と初期ストップ付き（利確はトレール・固定目標なし）。<b>★トップ{N_PORT}</b>＝機械システムの保有候補と一致。</div>'
            + "".join(rows) + '</div>')

def _leaders_card(by_state):
    total = sum(len(v) for v in by_state.values())
    all_tk = [x["t"] for code, _, _ in STATE_DEF for x in by_state.get(code, [])]
    secs = []
    _state_en = {"新高値圏/継続": "New Highs / Continuation", "押し目（形状）": "Pullback (shape)",
                 "伸び過ぎ（待ち）": "Extended (wait)", "深押し/ベース": "Deep Pullback / Base",
                 "割れ/様子見": "Broken (watch)"}
    for code, label, cls in STATE_DEF:
        lst = by_state.get(code, [])
        ticks = [x["t"] for x in lst]
        shown = lst[:CHIP_CAP]
        extra = len(lst) - len(shown)
        chips = "".join(f'<span class="chip {cls}" data-liq="{(x.get("dvol") or 0)/1e6:.1f}" data-tkone="{x["t"]}">{x["t"]}</span>' for x in shown)
        more = f'<span class="more">+{extra}件</span>' if extra > 0 else ""
        _en = _state_en.get(label, "")
        secs.append(
            f'<div class="setup-h"><span class="nm">{code} {label}'
            f'{f" <span class=" + chr(34) + "h2en" + chr(34) + ">" + _en + "</span>" if _en else ""}</span>'
            f'<span style="display:flex;gap:6px;align-items:center">{_cp(ticks)}'
            f'<span class="ct">{len(lst)}銘柄</span></span></div>'
            f'<div class="chips">{chips or "<span class=empty>なし</span>"}{more}</div>')
    return (f'<div class="card"><div class="hdr"><h2>リーダー監視（RS≥85・200MA上）</h2>{_cp(all_tk)}</div>'
            f'<div class="sub">高RSリーダーを状態①〜⑤で色分け（計{total}銘柄）。'
            f'③押し目／②継続／①伸び過ぎ待ち／④深押し／⑤様子見。'
            f''
f'</div>'
            + "".join(secs) + '</div>')



def build_rs_continuity(W, m, top_n=CONTINUE_TOP_N):
    """Compute RS189 leadership persistence from price history (display-only).

    Metrics: Top10 days in the last 21 sessions, Top24 occupancy over 63 sessions,
    consecutive Top10 streak, 21-session rank change, and 21-session RS deltas for
    63/126/189-day horizons.
    """
    try:
        C = W.get("Close") if isinstance(W, dict) else None
        V = W.get("Volume") if isinstance(W, dict) else None
        if C is None or V is None or C.empty or V.empty or m is None or m.empty:
            return None
        cols = [t for t in m.index if t in C.columns and t in V.columns]
        if len(cols) < 30:
            return None
        # 189d return + 63d observation window + volume warm-up.
        C = C[cols].sort_index().iloc[-320:]
        V = V[cols].reindex(C.index).sort_index()
        pool = (C >= 5) & ((C * V.rolling(20).mean()) >= DVOL_FLOOR)
        if "split_suspect" in m.columns:
            bad = [t for t in cols if bool(m.at[t, "split_suspect"])]
            if bad:
                pool.loc[:, bad] = False

        def _rs(period):
            ret = C.pct_change(period, fill_method=None)
            return ret.where(pool).rank(axis=1, pct=True) * 100.0
        r63, r126, r189 = _rs(63), _rs(126), _rs(189)
        rk189 = r189.rank(axis=1, ascending=False, method="min")
        if r189.dropna(how="all").empty:
            return None
        latest = r189.dropna(how="all").index[-1]
        cur = pd.to_numeric(m.get("rs189"), errors="coerce").dropna().sort_values(ascending=False).head(top_n)
        rows = []
        for t, rs_now in cur.items():
            if t not in rk189.columns:
                continue
            rr = rk189[t].loc[:latest].dropna()
            if rr.empty:
                continue
            w21 = rr.iloc[-21:]
            w63 = rr.iloc[-63:]
            top10_days = int((w21 <= 10).sum())
            top24_days = int((w63 <= top_n).sum())   # 継続占有=上位top_n(=2N)日数。対象数と基準を一致させる
            valid21, valid63 = int(len(w21)), int(len(w63))
            streak = 0
            for v in rr.iloc[::-1]:
                if v <= 10:
                    streak += 1
                else:
                    break
            old_rank = float(rr.iloc[-22]) if len(rr) >= 22 else None
            cur_rank = float(rr.iloc[-1])
            move21 = (old_rank - cur_rank) if old_rank is not None else None

            def _delta(frame):
                x = frame[t].loc[:latest].dropna() if t in frame.columns else pd.Series(dtype=float)
                return (float(x.iloc[-1] - x.iloc[-22]) if len(x) >= 22 else None)
            d63, d126, d189 = _delta(r63), _delta(r126), _delta(r189)
            smooth63 = float(m.at[t, "rs_smooth"]) if ("rs_smooth" in m.columns and pd.notna(m.at[t, "rs_smooth"])) else None
            rate24 = (top24_days / valid63) if valid63 else None

            # Heuristic labels are deliberately display-only; they do not alter selection.
            if (top10_days <= 2 and streak <= 2 and d63 is not None and d63 >= 12 and (smooth63 is None or float(rs_now)-smooth63 >= 8)):
                tag = "一日急騰型"
            elif (streak <= 4 and move21 is not None and move21 >= 10
                  and d63 is not None and d63 >= 5):
                tag = "新規急浮上"
            elif (move21 is not None and move21 <= -8) or (
                    d63 is not None and d126 is not None and d63 <= -10 and d126 <= -5):
                tag = "失速中"
            elif (streak <= 5 and top10_days >= 5 and move21 is not None and move21 >= 5):
                tag = "再浮上"
            elif (top10_days >= 15 and rate24 is not None and rate24 >= 0.75
                  and (d189 is None or d189 >= -3) and (smooth63 is None or smooth63 >= 85)):
                tag = "定着"
            else:
                tag = "継続"
            rows.append(dict(
                t=t, rank=int(round(cur_rank)), rs=float(rs_now),
                top10_days=top10_days, valid21=valid21,
                top24_days=top24_days, valid63=valid63, top24_rate=rate24,
                streak=streak, move21=move21, d63=d63, d126=d126, d189=d189, smooth63=smooth63,
                tag=tag,
            ))
        rows.sort(key=lambda x: x["rank"])
        return dict(rows=rows, asof=str(pd.Timestamp(latest).date()), top_n=top_n)
    except Exception as e:
        sys.stderr.write("[rs_continuity] %r\n" % repr(e)[:120])
        return None

def _rs_continuity_card(cont):
    if not cont or not cont.get("rows"):
        return '<div class="card"><h2>RS189 継続性</h2><div class="empty">履歴不足</div></div>'
    rows = cont["rows"]
    groups = {}
    for r in rows:
        groups.setdefault(r["tag"], []).append(r["t"])
    order = ["定着", "新規急浮上", "再浮上", "失速中", "一日急騰型", "継続"]
    clsmap = {"定着":"stable", "新規急浮上":"surge", "再浮上":"return", "失速中":"fade", "一日急騰型":"spike", "継続":"hold"}
    chips = ''.join(
        f'<div class="rscg"><b>{lab}</b><span>{len(groups.get(lab, []))}</span><div class="chips">'
        + ''.join(f'<span class="chip" data-tkone="{t}">{t}</span>' for t in groups.get(lab, []))
        + '</div></div>' for lab in order if groups.get(lab)
    )
    def _num(v, plus=False):
        if v is None or not np.isfinite(v): return '—'
        return f'{float(v):+.0f}' if plus else f'{float(v):.0f}'
    body=[]
    for r in rows:
        mv = r.get("move21")
        mvtxt = '—' if mv is None else (f'↑{int(round(mv))}' if mv>0 else f'↓{abs(int(round(mv)))}' if mv<0 else '→')
        mvcls = 'pos' if mv is not None and mv>0 else 'neg' if mv is not None and mv<0 else 'mut'
        rate = '—' if r.get("top24_rate") is None else f'{r["top24_rate"]*100:.0f}%'
        tag=r["tag"]; tc=clsmap.get(tag,'hold')
        body.append(
            '<div class="rsc-row">'
            f'<div class="rsc-head"><span class="rsc-rk">#{r["rank"]}</span><b data-tkone="{r["t"]}">{r["t"]}</b>'
            f'<span class="rsc-tag {tc}">{tag}</span><span class="rsc-rs">RS {r["rs"]:.1f}</span></div>'
            f'<div class="rsc-metrics"><span>Top10 <b>{r["top10_days"]}/{r["valid21"]}日</b></span>'
            f'<span>Top24 <b>{rate}</b></span><span>連続Top10 <b>{r["streak"]}日</b></span>'
            f'<span>21日順位 <b class="{mvcls}">{mvtxt}</b></span></div>'
            f'<div class="rsc-slopes">63平滑 <b>{_num(r.get("smooth63"))}</b>・21日変化: 63 <b>{_num(r.get("d63"),True)}</b> / 126 <b>{_num(r.get("d126"),True)}</b> / 189 <b>{_num(r.get("d189"),True)}</b></div>'
            '</div>'
        )
    return (
        '<div class="card rs-cont"><div class="hdr"><h2>RS189 継続性 <span class="h2en">Leadership Persistence</span></h2>' + _cp([r["t"] for r in rows]) + '</div>'
        '<div class="sub">Top10滞在、Top24滞在率、連続日数、順位・RS変化。</div><details class="mut" style="margin:2px 0 6px"><summary style="font-size:11px;cursor:pointer">分類の定義</summary><div class="sub">直近21営業日のRS189順位で機械分類：<b>定着</b>=Top10に15日以上×Top24滞在率75%以上×長期RS悪化なし／<b>継続</b>=Top24圏内を維持／<b>失速中</b>=順位が21日で8以上悪化、またはRS63・126がともに低下／<b>再浮上</b>=一度圏外→直近でTop10に5日以上／<b>新規急浮上</b>=順位を21日で10以上上げて浮上直後／<b>一日急騰型</b>=滞在2日以下の瞬間芸（定着未確認）。</div></details>'
        f'<div class="rsc-groups">{chips}</div><div class="rsc-list">{"".join(body)}</div>'
        '<div class="sub mut">定着・急浮上・再浮上・失速を同じ基準で分類。</div></div>'
    )


def build_leadership_pulse(m, continuity, s2t):
    try:
        top=m.dropna(subset=["rs189"]).sort_values("rs189",ascending=False).head(RS_CONTINUITY_TOP_N)
        rows=(continuity or {}).get("rows") or []
        themes=[theme_of(t,s2t) for t in top.index]
        from collections import Counter
        # #6 同数テーマで set 反復順(PYTHONHASHSEED依存)に落ちないよう、(出現数降順, テーマ名昇順)で決定的に選ぶ
        if themes:
            _tc=Counter(themes); top_theme=sorted(_tc, key=lambda x:(-_tc[x], x))[0]
        else:
            top_theme=None
        return dict(all3=int(((top.rs21>=85)&(top.rs63>=85)&(top.rs189>=85)).sum()),
                    stable=sum(r.get("tag")=="定着" for r in rows), fade=sum(r.get("tag")=="失速中" for r in rows),
                    rising=int((pd.to_numeric(top.get("rs126_d"),errors="coerce")>=5).sum()),
                    falling=int((pd.to_numeric(top.get("rs126_d"),errors="coerce")<=-5).sum()), top_theme=top_theme)
    except Exception: return {}

def theme_quad_map(m, s2t):
    """テーマごとの勢い象限（主導/改善/弱化/停滞）。x=RS189中央値, y=1ヶ月変化中央値。"""
    try:
        th = m.index.to_series().map(lambda t: theme_of(t, s2t))
        x = pd.to_numeric(m.get("rs189"), errors="coerce")
        y = x - pd.to_numeric(m.get("rs189_m1"), errors="coerce")
        g = pd.DataFrame({"th": th, "x": x, "y": y}).dropna()
        gm = g.groupby("th").agg(x=("x", "median"), y=("y", "median"), n=("x", "size"))
        gm = gm[gm["n"] >= 3]
        xm = float(gm["x"].median()) if len(gm) else 50.0
        out = {}
        for ix, r in gm.iterrows():
            out[ix] = ("主導" if (r.x >= xm and r.y > 0) else "改善" if r.y > 0 else "弱化" if r.x >= xm else "停滞")
        return out
    except Exception:
        return {}

def _rs_compare_tab(m, picks, s2i, e2j, s2t, continuity=None):
    """RS63/126/189のTop10比較と、1日・1週・1か月のIN/OUT履歴。売買ルールには"""
    if m is None or m.empty:
        return '<div class="card"><h2>RS比較</h2><div class="empty">データなし</div></div>'

    df = m.copy()
    if "rs_pool" in df.columns:
        df = df[df["rs_pool"].fillna(False)]
    specs = [
        ("RS63", "rs63", "rs_w1", "ret63", "約3ヶ月", "短期の加速・失速を最も早く捉える",
         (("1日", "前営業日", "rs63_d1"), ("1週", "約5営業日前", "rs_w1"), ("1か月", "約21営業日前", "rs63_m1"))),
        ("RS126", "rs126", "rs126_l5", "ret126", "約6ヶ月", "中期トレンドの持続性を確認する",
         (("1日", "前営業日", "rs126_d1"), ("1週", "約5営業日前", "rs126_l5"), ("1か月", "約21営業日前", "rs126_m1"))),
        ("RS189", "rs189", "rs189_l5", "ret189", "約9ヶ月・主指標", "個別株スリーブの選定順位に使用する",
         (("1日", "前営業日", "rs189_l1"), ("1週", "約5営業日前", "rs189_l5"), ("1か月", "約21営業日前", "rs189_m1"))),
    ]
    pick_set = {t for t, *_ in (picks or [])}
    ranks, prev_ranks, tops = {}, {}, {}

    def _series(col):
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(index=df.index, dtype=float)

    def _top10(col):
        return list(_series(col).dropna().sort_values(ascending=False).head(10).index)

    for lab, col, pcol, _retcol, _period, _desc, _hist in specs:
        vals = _series(col)
        ranks[lab] = vals.rank(ascending=False, method="min")
        prev_ranks[lab] = _series(pcol).rank(ascending=False, method="min")
        tops[lab] = list(vals.dropna().sort_values(ascending=False).head(10).index)

    def _chips(xs, cls=""):
        xs = list(xs)
        if not xs:
            return '<span class="empty">なし</span>'
        c = f' {cls}' if cls else ''
        return ''.join(f'<span class="chip{c}" data-tkone="{t}">{t}</span>' for t in xs)

    s63, s126, s189 = set(tops["RS63"]), set(tops["RS126"]), set(tops["RS189"])
    all3 = [t for t in tops["RS189"] if t in s63 and t in s126]
    both63_126 = [t for t in tops["RS63"] if t in s126]
    both126_189 = [t for t in tops["RS126"] if t in s189]
    both63_189 = [t for t in tops["RS63"] if t in s189]


    # ── タブ横断サマリー: 三窓一致リーダー × テーマ勢い × 高値距離 × 保有状態（表示専用）
    def _theme_quads():
        try:
            th = df.index.to_series().map(lambda t: theme_of(t, s2t))
            r_now = _series("rs189"); r_m1 = _series("rs189_m1")
            g = pd.DataFrame({"th": th, "x": r_now, "y": r_now - r_m1}).dropna()
            gm = g.groupby("th").agg(x=("x", "median"), y=("y", "median"), n=("x", "size"))
            gm = gm[gm["n"] >= 3]
            xm = float(gm["x"].median()) if len(gm) else 50.0
            def q(row):
                if row.x >= xm and row.y > 0: return "主導"
                if row.x < xm and row.y > 0: return "改善"
                if row.x >= xm: return "弱化"
                return "停滞"
            return {ix: q(r) for ix, r in gm.iterrows()}
        except Exception:
            return {}
    _tq = _theme_quads()
    _qcls = {"主導": "pos", "改善": "", "弱化": "neg", "停滞": "mut"}
    def _synth_rows(ts):
        rows = []
        for t in ts:
            th = theme_of(t, s2t)
            quad = _tq.get(th, "—")
            d52 = df.at[t, "dist52"] if "dist52" in df.columns else None
            d52t = "—" if d52 is None or d52 != d52 else f"{d52*100:+.0f}%"
            r1, r2 = _series("rs189").get(t), _series("rs63").get(t)
            stat = "採用" if t in pick_set else ""
            chip = ('<span class="rsx-badge sel">' + stat + '</span>') if stat else ''
            rows.append(
                f'<tr><td><b data-tkone="{t}">{t}</b>{chip}</td>'
                f'<td><div class="thcell"><span class="thnm">{_h(th)}</span>'
                f'<span class="thmom {_qcls.get(quad, "mut")}">{quad}</span></div></td>'
                f'<td>{r1:.0f}/{r2:.0f}</td><td>{d52t}</td></tr>')
        return "".join(rows)
    if all3:
        synth_card = (
            f'<div class="card"><div class="hdr"><h2>三窓一致リーダー <span class="h2en">Cross-Window Leaders</span></h2>{_cp(all3)}</div>'
            '<div class="sub">RS63・126・189すべてでTop10に入る銘柄を、テーマの勢い象限・52週高値距離・保有状態と結合。'
            '短中長の全時間軸で強い＝いま市場が最も一貫して買っている名前。</div>'
            '<table class="tbl"><thead><tr><th>銘柄</th><th>テーマ（勢い）</th><th>RS189/63</th><th>52wH</th></tr></thead>'
            f'<tbody>{_synth_rows(all3)}</tbody></table></div>')
    else:
        synth_card = ('<div class="card"><h2>三窓一致リーダー <span class="h2en">Cross-Window Leaders</span></h2>'
                      '<div class="sub mut">現在、三窓すべてでTop10に入る銘柄はなし（リーダーシップが時間軸で分裂中）。</div></div>')

    r63 = ranks["RS63"]
    r189 = ranks["RS189"]
    early = [t for t in tops["RS63"] if pd.isna(r189.get(t)) or float(r189.get(t)) > 30]
    fading = [t for t in tops["RS189"] if pd.isna(r63.get(t)) or float(r63.get(t)) > 30]

    summary = (
        '<div class="card rsx-intro"><div class="hdr"><h2>RSマルチタイムフレーム比較</h2></div>'
        '<div class="sub"><b>RS189が選定の主指標</b>。RS126は中期の持続性、RS63は短期の加速・失速を見る補助計器。'
        'Top10入りだけで売買せず、既存の50日線&gt;200日線・流動性・リーダー条件を優先する。</div>'
        '<div class="rsx-overlap">'
        f'<div class="rsx-stat"><div class="rsx-stat-h"><span>3期間すべてTop10</span><b>{len(all3)}</b>{_cp(all3)}</div><div class="chips">{_chips(all3)}</div></div>'
        f'<div class="rsx-stat"><div class="rsx-stat-h"><span>RS63 × RS126</span><b>{len(both63_126)}</b>{_cp(both63_126)}</div><div class="chips">{_chips(both63_126)}</div></div>'
        f'<div class="rsx-stat"><div class="rsx-stat-h"><span>RS126 × RS189</span><b>{len(both126_189)}</b>{_cp(both126_189)}</div><div class="chips">{_chips(both126_189)}</div></div>'
        f'<div class="rsx-stat"><div class="rsx-stat-h"><span>RS63 × RS189</span><b>{len(both63_189)}</b>{_cp(both63_189)}</div><div class="chips">{_chips(both63_189)}</div></div>'
        '</div>'
        '<div class="rsx-signals">'
        f'<div class="rsx-sig"><b>短期先行</b><span>RS63 Top10・RS189 Top30外</span>{_cp(early)}<div class="chips">{_chips(early)}</div></div>'
        f'<div class="rsx-sig"><b>長期鈍化</b><span>RS189 Top10・RS63 Top30外</span>{_cp(fading)}<div class="chips">{_chips(fading)}</div></div>'
        '</div><div class="sub mut">短期先行と長期鈍化を分けて確認。</div></div>'
    )

    # Top10の入替履歴。価格履歴から各基準日時点のRSを再計算するため、毎日実行していなくても欠損しない。
    hist_blocks = []
    for lab, col, _pcol, _retcol, period, _desc, hist_specs in specs:
        now = tops[lab]
        now_set = set(now)
        hrows = []
        for win, asof_txt, hcol in hist_specs:
            old = _top10(hcol)
            old_set = set(old)
            ins = [t for t in now if t not in old_set]
            outs = [t for t in old if t not in now_set]
            stay = len(now_set & old_set)
            unavailable = not old
            if unavailable:
                hrows.append(
                    f'<div class="rsx-hrow"><div class="rsx-hwhen"><b>{win}</b><small>{asof_txt}</small></div>'
                    '<div class="rsx-hna">履歴不足</div></div>'
                )
                continue
            hrows.append(
                '<div class="rsx-hrow">'
                f'<div class="rsx-hwhen"><b>{win}</b><small>{asof_txt}</small><em>継続 {stay}/10・入替 {len(ins)}</em></div>'
                f'<div class="rsx-hflow"><div><strong class="hin">IN {len(ins)}</strong><span class="chips">{_chips(ins, "in")}</span></div>'
                f'<div><strong class="hout">OUT {len(outs)}</strong><span class="chips">{_chips(outs, "out")}</span></div></div>'
                '</div>'
            )
        hist_blocks.append(
            '<div class="rsx-hblock">'
            f'<div class="rsx-hhead"><b>{lab}</b><span>{period}</span>{_cp(now)}</div>'
            + ''.join(hrows) + '</div>'
        )
    history = (
        '<div class="card rsx-history"><div class="hdr"><h2>Top10 IN / OUT履歴</h2></div>'
        '<div class="sub">現在のTop10を、前営業日・約1週間前・約1か月前のTop10と比較。'
        '<b>IN</b>は新規入り、<b>OUT</b>は脱落。入替数が多いほどランキングの回転が速い。価格履歴から再計算するため、ダッシュボード未実行日があっても比較できる。</div>'
        '<div class="rsx-hgrid">' + ''.join(hist_blocks) + '</div></div>'
    )

    cards = [synth_card]
    for lab, col, pcol, retcol, period, desc, _hist in specs:
        tickers = tops[lab]
        rows = []
        for pos, t in enumerate(tickers, 1):
            r = df.loc[t]
            cur = r.get(col)
            prev_rank = prev_ranks[lab].get(t)
            cur_rank = ranks[lab].get(t)
            if pd.isna(prev_rank) or pd.isna(cur_rank):
                move = '<span class="mut">—</span>'
            elif float(prev_rank) > 10:
                move = '<span class="rsx-new">NEW</span>'
            else:
                d = int(round(float(prev_rank) - float(cur_rank)))
                if d > 0:
                    move = f'<span class="pos">↑{d}</span>'
                elif d < 0:
                    move = f'<span class="neg">↓{abs(d)}</span>'
                else:
                    move = '<span class="mut">→</span>'

            excluded = bool(is_excluded_theme(t, s2t))
            eligible = (
                pd.notna(r.get("sma50")) and pd.notna(r.get("sma200")) and float(r.get("sma50")) > float(r.get("sma200"))
                and pd.notna(r.get("close")) and float(r.get("close")) > float(r.get("sma200"))
                and pd.notna(r.get("rs63")) and float(r.get("rs63")) >= LEADER_RS
                and pd.notna(r.get("rs189")) and float(r.get("rs189")) >= LEADER_RS
            )
            if t in pick_set:
                badge = '<span class="rsx-badge sel">採用</span>'
            elif excluded:
                badge = '<span class="rsx-badge ex">除外</span>'
            elif eligible:
                badge = '<span class="rsx-badge ok">適格</span>'
            else:
                badge = '<span class="rsx-badge watch">監視</span>'

            sth = subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))
            def _rv(k):
                v = r.get(k)
                return f'{float(v):.0f}' if pd.notna(v) else '—'
            rr = r.get(retcol)
            rr_txt = f'{float(rr)*100:+.1f}%' if pd.notna(rr) else '—'
            dv = r.get("dvol")
            dv_txt = f'${float(dv)/1e6:.0f}M' if pd.notna(dv) else '—'
            rows.append(
                '<div class="rsx-item">'
                f'<div class="rsx-row"><span class="rsx-rk">{pos}</span>'
                f'<div class="rsx-name"><div><b>{t}</b>{badge}</div><small>{_h(sth)}</small></div>'
                f'<div class="rsx-score"><b>{float(cur):.1f}</b><small>{move}</small></div></div>'
                f'<div class="rsx-sub"><span class="rsx-nums">63 <b>{_rv("rs63")}</b>・126 <b>{_rv("rs126")}</b>・189 <b>{_rv("rs189")}</b></span>'
                f'<span class="rsx-ret">リターン {rr_txt}・{dv_txt}/日</span></div></div>'
            )
        cards.append(
            '<div class="card rsx-card">'
            f'<div class="hdr"><h2>{lab} Top10 <span class="h2en">{period}</span></h2>{_cp(tickers)}</div>'
            f'<div class="sub">{desc}。右下は5営業日前の順位比（NEW＝Top10新規入り）。</div>'
            '<details class="cxpl"><summary>バッジの意味</summary><div class="cxpl-b">'
            '<b>採用</b>＝現在Core 12として保有中（システム選定の12銘柄）。'
            '<b>監視</b>＝Top10だがCore 12には未採用（候補・ウォッチ）。'
            '<b>NEW</b>＝5営業日前はTop10外→今回新規入り。'
            '右の数字（↑↓）は5営業日前からの順位変化。</div></details>'
            + ''.join(rows or ['<div class="empty">該当なし</div>']) + '</div>'
        )
    return summary + history + _rs_continuity_card(continuity) + '<div class="rsx-grid">' + ''.join(cards) + '</div>'

CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
.rrow{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 10px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:9px 12px;margin-top:8px}
.rrow .lft{min-width:0}
.rrow .foot,.rrow .hint{grid-column:1 / -1}
.rrow .nm{font-size:13px;color:#cbd5e1;font-weight:600;line-height:1.25}
.rrow .cat{font-size:10.5px;color:#7e8ea3;letter-spacing:.03em}
.rrow .rgt{text-align:right;white-space:nowrap}
.rrow .big{font-size:19px;font-weight:700;color:#e6edf3}
.rrow .chg{font-size:11px;margin-left:5px}
.rrow .hint{font-size:11px;color:#9fb0c5;margin-top:2px;letter-spacing:.02em}
.cxpl{margin:2px 0 0}.cxpl>summary{list-style:none;cursor:pointer;font-size:10px;color:#6f8198;display:inline-flex;align-items:center;gap:3px;padding:1px 0;user-select:none}.cxpl>summary::-webkit-details-marker{display:none}.cxpl>summary::before{content:"\25B8";font-size:7px}.cxpl[open]>summary::before{content:"\25BE"}.cxpl-b{font-size:11px;line-height:1.55;color:#8b9bb0;margin:3px 0 2px}.chd{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}.chd h2{margin:0}.chd-now{text-align:right;line-height:1.05;white-space:nowrap;flex:0 0 auto}.chd-now b{font-size:18px;font-weight:800;display:block;letter-spacing:-.01em}.chd-now span{font-size:10px;color:#7e8ea3;display:block;margin-top:1px;font-weight:600}.mv-wrap{display:flex;flex-direction:column;gap:14px;margin-top:6px}.mv-per-h{font-size:13px;font-weight:700;color:#cbd5e1;margin-bottom:6px;padding-bottom:3px;border-bottom:1px solid rgba(255,255,255,.08)}.mv-cols{display:grid;grid-template-columns:1fr;gap:10px}@media(min-width:560px){.mv-cols{grid-template-columns:1fr 1fr}}.mv-col-h{font-size:11px;font-weight:700;margin-bottom:4px;letter-spacing:.02em}.mvr{display:flex;align-items:center;gap:6px;padding:3px 7px;border-radius:5px;font-size:12px;cursor:pointer;min-width:0}.mvr:active{background:rgba(91,124,194,.15)}.mvr:nth-child(odd){background:rgba(255,255,255,.03)}.mvr-t{font-weight:600;color:#cbd5e1;flex:0 0 auto}.mvr-v{font-weight:700;font-variant-numeric:tabular-nums;flex:0 0 auto;margin-left:auto;padding-left:6px}.mv-sec-h{font-size:12px;font-weight:800;color:#a9bad0;margin:14px 0 6px;letter-spacing:.02em}.mv-sum{font-size:12px;color:#c3d0e0;padding:3px 0;line-height:1.5}.mv-mom{display:flex;gap:8px;align-items:baseline;padding:4px 0;font-size:12.5px}.mv-mom-l{font-weight:800;flex:0 0 auto;font-size:11px}.mv-mom-b{color:#cbd5e1;font-weight:600;line-height:1.5}.mvr-x{display:flex;gap:5px;align-items:center;flex:1 1 auto;justify-content:flex-end;min-width:0;overflow:hidden;flex-wrap:nowrap}.mvr-e{font-size:10px;color:#8b9bb0;font-weight:600;white-space:nowrap;flex:0 0 auto}.mvr-e.hot{color:#c7923f}.mvr-th{font-size:10px;color:#7e8ea3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1 1 auto;min-width:24px;max-width:120px}.mvr-3w{font-size:9px;font-weight:800;color:#fff;background:#5b7cc2;border-radius:4px;padding:0 4px;margin-left:5px;vertical-align:middle}details.mv-per>summary.mv-per-h{cursor:pointer;list-style:none}details.mv-per>summary.mv-per-h::-webkit-details-marker{display:none}details.mv-per>summary.mv-per-h::before{content:"▸ ";font-size:9px}details.mv-per[open]>summary.mv-per-h::before{content:"▾ "}
.rrow .foot{font-size:10.5px;color:#7b8aa0;margin-top:3px;border-top:1px solid rgba(255,255,255,.06);padding-top:3px}
.rrow .na{font-size:13px;color:#5f6b7e}
.pulse{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:10px 12px;margin-top:8px}
.pulse .ptop{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 8px}
.pulse .pnm{font-size:13px;font-weight:700;color:#e6edf3}
.pulse .pbig{font-size:20px;font-weight:800;color:#e6edf3}
.pulse .pchg{font-size:11px}
.pulse .pcat{font-size:10.5px;color:#7e8ea3;margin-top:1px}
.pulse .pmeta{font-size:11px;color:#9fb0c5;margin-top:4px;line-height:1.5}
.pulse .spark{width:100%;height:34px;margin:5px 0 0;display:block}
.pulse .pfoot{font-size:10px;margin-top:4px;border-top:1px solid rgba(255,255,255,.06);padding-top:3px}
.eccal{margin-top:6px;display:flex;flex-direction:column;gap:2px}
.ecrow{display:flex;align-items:center;gap:10px;padding:7px 4px;border-bottom:1px solid rgba(255,255,255,.06)}
.ecrow:last-child{border-bottom:0}
.ecdate{font-weight:800;color:#e6edf3;min-width:60px;font-size:13px}
.ecdate .ecw{font-size:10px;color:#7e8ea3;font-weight:700;margin-left:3px}
.ecnm{flex:1;font-size:13px;font-weight:700;color:#cdd6e0;display:flex;flex-direction:column;line-height:1.25}
.ecnm .eccat{font-size:10px;color:#7e8ea3;font-weight:600}
.ecimp{font-size:12px;font-weight:800;letter-spacing:1px}
.mbrow{background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.06);border-radius:9px;padding:8px 11px;margin-top:7px}
.mbtop{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 8px}
.mbnm{font-size:12.5px;font-weight:700;color:#e6edf3}
.mbval{font-size:17px;font-weight:800;color:#e6edf3;margin-left:auto}
.mbchg{font-size:11px}
.mbnote{font-size:10.5px;color:#7e8ea3;margin-top:3px;line-height:1.4}
.mbread{font-size:12.5px;line-height:1.7;color:#d4deea;margin:8px 0 4px;padding:10px 12px;border-radius:9px;background:rgba(122,148,177,.10);border:1px solid rgba(122,148,177,.20)}
.mbread b{font-weight:800}
.spark{grid-column:1 / -1;display:block;width:100%;height:34px;margin:5px 0 0;opacity:1}
.w30b{display:inline-block;margin-left:5px;font-size:10px;font-weight:800;border-radius:5px;padding:0 5px;background:#233047;color:#9fb2cc}
.w30b-full{background:#14532d;color:#86efac}
.w30b-part{background:#3f3f14;color:#fde047}
.w30b-weak{background:#4c1d24;color:#fca5a5}
.w30row{padding:9px 2px;border-bottom:1px solid rgba(255,255,255,.06)}
.w30row-h{display:flex;align-items:baseline;gap:2px}
.w30row-h>b{font-size:14px;font-weight:800;color:#e6edf3}
.w30row-m{font-size:11px;color:#9fb0c5;margin-top:3px}
.w30t{display:inline-block;margin-left:4px;font-size:10px;font-weight:900;border-radius:4px;padding:0 5px;vertical-align:middle}
.w30hi td{background:rgba(161,98,7,.10)}
.w30hi td:nth-child(n+3){color:#fbbf24;font-weight:800}
.w30t-s{background:#a16207;color:#fde68a}
.w30s{display:inline-block;margin-left:4px;font-size:10px;font-weight:700;border-radius:4px;padding:0 5px}
.w30s-new{background:#1e3a5f;color:#93c5fd}.w30s-adv{background:#233047;color:#9fb2cc}
.w30s-pb{background:#3f3f14;color:#fde047}.w30s-resume{background:#14532d;color:#86efac}
.w30s-stall{background:#2a2431;color:#c4b5fd}.w30s-dead{background:#4c1d24;color:#fca5a5}
.w30t-a{background:#14532d;color:#86efac}
.w30t-b{background:#334155;color:#cbd5e1}
.w30new{display:inline-block;margin-left:4px;font-size:9px;font-weight:900;border-radius:4px;padding:0 5px;background:#1d4ed8;color:#dbeafe;vertical-align:middle}
.w30wk{margin-left:4px;font-size:10px;color:#8595aa}
.w30g-full{color:#86efac}.w30g-part{color:#fde047}.w30g-weak{color:#fca5a5}
.w30exit{display:grid;grid-template-columns:74px 1fr;gap:10px;padding:8px 2px;border-bottom:1px solid rgba(255,255,255,.06)}
.w30exit-t{font-size:11px;font-weight:800;color:#8fb3ff}
.w30exit-b{font-size:11.5px;color:#cbd5e1;line-height:1.5}
.w30coh{font-size:11.5px;color:#cbd5e1;line-height:1.5;padding:8px 2px;border-bottom:1px solid rgba(255,255,255,.06)}
.albadge{font-size:9px;font-weight:800;padding:1px 6px;border-radius:6px;border:1px solid;margin-left:6px;vertical-align:middle;letter-spacing:.03em}
.lead-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-end;margin:8px 0 6px}.lead-head b{font-size:15px}.lead-head span{font-size:10px;color:#7d8da1;white-space:nowrap}.lead-grid{display:grid;gap:5px}.lead-row{display:grid;grid-template-columns:58px 1fr;gap:8px;padding:7px 8px;border-radius:8px;background:rgba(255,255,255,.025)}.lead-row>span{font-size:10px;color:#7d8da1}.lead-row>b{font-size:11px;font-weight:600;line-height:1.35}
.mkt20{padding-bottom:12px}.mkt20-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.mkt20-top h2{margin-bottom:4px}.mkt20-verdict{font-size:14px;font-weight:800;line-height:1.45;color:#e6edf3}.mkt20-read{font-size:12.5px;line-height:1.65;color:#d4deea;margin:9px 0 2px;padding:10px 12px;border-radius:9px;background:rgba(122,148,177,.10);border:1px solid rgba(122,148,177,.20)}
.mkt20-cats{margin-top:10px;padding-top:9px;border-top:1px solid rgba(255,255,255,.08)}
.ccblock{margin-top:11px;padding-top:9px;border-top:1px solid rgba(255,255,255,.07)}.ccblock:first-of-type{border-top:0;margin-top:4px}.cchd{font-size:12.5px;font-weight:800;color:#e6edf3;margin-bottom:4px}.cchd-en{font-size:9px;font-weight:700;color:#6f8198;letter-spacing:.1em;text-transform:uppercase;margin-left:6px}.ccrow{display:flex;gap:9px;padding:4px 0;align-items:baseline}.cctf{flex:0 0 84px;font-size:10.5px;font-weight:800;color:#86a8cb}.cctxt{flex:1;font-size:11.8px;line-height:1.5;color:#cdd6e0}@media(max-width:620px){.cctf{flex:0 0 66px;font-size:9.5px}.cctxt{font-size:11.2px}}.mkt20-score{min-width:74px;text-align:right;display:flex;flex-direction:column;align-items:flex-end}.mkt20-score>b{font-size:27px;line-height:1;color:#9ecbff}.mkt20-score>span{font-size:10px;font-weight:800;color:#c8d5e6;margin-top:3px}.mkt20-score>em{font-size:9px;font-style:normal;color:#718096;margin-top:2px}.mkt20-label{font-size:9px;font-weight:800;letter-spacing:.12em;color:#6f8198;margin:9px 0 5px;text-transform:uppercase}.mkt20-grid{display:grid;gap:5px}.mkt-post-tools{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:10px 0 6px;font-size:9.5px;font-weight:800;color:#70839a}.mkt-copy{margin-left:auto}.mkt-post{display:grid;gap:5px;padding:9px 10px;border-radius:10px;background:linear-gradient(180deg,rgba(30,50,76,.42),rgba(12,21,33,.55));border:1px solid rgba(91,127,176,.28)}.mkt-post-hook{font-size:12px;font-weight:900;line-height:1.42;color:#f0f5fb;padding-bottom:5px;border-bottom:1px solid rgba(122,148,177,.18)}.mkt-post-line{font-size:10.7px;line-height:1.48;color:#c8d5e6}.mkt-post-line>b{color:#8fb3ff;margin-right:3px}.mkt-post-line:nth-child(2){font-size:11.2px;color:#eef4fb}.mkt20-row{display:grid;grid-template-columns:44px minmax(0,1fr);gap:8px;padding:7px 9px;border-radius:8px;background:rgba(255,255,255,.028);border:1px solid rgba(255,255,255,.035)}.mkt20-k{font-size:10px;font-weight:800;color:#86a8cb;padding-top:1px}.mkt20-row b{display:block;font-size:11.5px;line-height:1.35;color:#e6edf3;white-space:normal}.mkt20-row small{display:block;font-size:9.5px;line-height:1.35;color:#8593a6;margin-top:2px;white-space:normal}.mkt-fold{margin-top:8px;border-top:1px solid rgba(122,148,177,.18);padding-top:7px}.mkt-fold>summary{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;font-size:10.5px;font-weight:800;color:#8fb3ff;padding:2px 1px}.mkt-fold>summary::-webkit-details-marker{display:none}.mkt-fold>summary:before{content:"▸";font-size:9px;margin-right:6px}.mkt-fold[open]>summary:before{content:"▾"}.mkt-fold-state:after{content:"タップで開く";font-size:9px;color:#63738a;font-weight:600}.mkt-fold[open] .mkt-fold-state:after{content:"折りたたむ"}.mkt-fold-body{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:7px}.mkt20-deep{padding:8px 9px;border-radius:8px;background:#0d1725;border:1px solid #1c2a3b}.mkt20-deep>span{display:block;font-size:9px;color:#718096;margin-bottom:3px}.mkt20-deep>b{display:block;font-size:10.5px;line-height:1.45;color:#cbd5e1}.mkt20-deep:last-child:nth-child(odd){grid-column:1/-1}@media(max-width:620px){.mkt20-top{align-items:flex-start}.mkt20-verdict{font-size:13px}.mkt20-score>b{font-size:24px}.mkt-fold-body{grid-template-columns:1fr}.mkt20-deep:last-child:nth-child(odd){grid-column:auto}.mkt20-row{grid-template-columns:42px minmax(0,1fr);padding:7px 8px}}


html{background:#0b0f17;color-scheme:dark}
body{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;background:#0b0f17;color:#e6edf3;font-size:14px;-webkit-text-size-adjust:100%}
.wrap{max-width:680px;margin:0 auto;padding:0 12px calc(60px + env(safe-area-inset-bottom))}
header{padding:14px 4px 8px}
h1{font-size:18px;font-weight:800;letter-spacing:.01em}
.asof{color:#7d8da1;font-size:11px;margin-top:2px}
.banner{border-radius:14px;padding:14px 16px;margin:10px 0 4px;border:1px solid #1c2533;background:linear-gradient(135deg,#121a28,#172033)}
.banner .lab{font-size:12px;color:#cbd5e1;opacity:.85}
.banner .val{font-size:31px;font-weight:800;line-height:1.1;margin:2px 0;font-variant-numeric:tabular-nums}
.banner .st{font-size:13px;font-weight:800}
/* 地合いバンドは背景でなくラベル文字色で表現（トレンド判定ピルとの色被りを回避） */
.b-ovh .st{color:#86efac}.b-bull .st{color:#4ade80}
.b-neu .st{color:#fbbf24}.b-weak .st{color:#fb923c}.b-bear .st{color:#f87171}
.gauge{height:10px;border-radius:6px;margin:10px 0 4px;background:linear-gradient(90deg,#991b1b 0%,#9a3412 30%,#a16207 45%,#15803d 60%,#166534 100%);position:relative}
.gauge .mk{position:absolute;top:-4px;width:3px;height:18px;background:#fff;border-radius:2px;box-shadow:0 0 4px rgba(0,0,0,.6)}
.aux{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.aux .a{background:rgba(0,0,0,.22);border-radius:8px;padding:5px 9px;font-size:11px}
.aux .a b{font-size:13px}
/* NQ-SAR signal pill (leverage sleeve; logic hidden) */
.sar{border-radius:14px;padding:12px 16px;margin:10px 0 4px;border:1px solid rgba(255,255,255,.10);
     display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.sar .lhs{display:flex;align-items:center;gap:11px}
.sar .dot{width:16px;height:16px;border-radius:50%;box-shadow:0 0 0 3px rgba(255,255,255,.15),0 0 10px rgba(0,0,0,.4);flex:0 0 auto}
.sar .lab{font-size:11px;color:#dbe4ef;opacity:.9;letter-spacing:.04em}
.sar .col{font-size:22px;font-weight:800;line-height:1.05}
.sar .rhs{text-align:right}
.sar .jud{font-size:20px;font-weight:800;line-height:1.05}
.sar .lot{font-size:11px;opacity:.92;margin-top:2px}
.sar-blue{background:linear-gradient(135deg,#0b2a6b,#1d4ed8)}   .sar-blue .dot{background:#60a5fa}
.sar-green{background:linear-gradient(135deg,#14532d,#16a34a)}  .sar-green .dot{background:#4ade80}
.sar-yellow{background:linear-gradient(135deg,#713f12,#ca8a04)} .sar-yellow .dot{background:#facc15}
.sar-red{background:linear-gradient(135deg,#7f1d1d,#dc2626)}    .sar-red .dot{background:#f87171}
.sar-gray{background:linear-gradient(135deg,#374151,#4b5563)}   .sar-gray .dot{background:#9ca3af}
.sar-badge{display:inline-block;font-size:10px;font-weight:800;border-radius:6px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.sar-badge.ok{background:rgba(255,255,255,.18);color:#dffbe8}
.sar-badge.est{background:#a16207;color:#fde68a}
.sar-badge.none{background:#1f2937;color:#cbd5e1}
/* distribution-day + performance widgets */
.dd{display:flex;gap:10px;flex-wrap:wrap}
.dd .box{flex:1 1 120px;background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:10px 12px}
.dd .box .t{font-size:12px;color:#9fb0c5;font-weight:700}
.dd .box .num{font-size:26px;font-weight:800;line-height:1.1;margin:2px 0;font-variant-numeric:tabular-nums}
.dd .st{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:7px}
.st-good{background:#14532d;color:#86efac}.st-warn{background:#713f12;color:#fde68a}.st-bad{background:#7f1d1d;color:#fca5a5}
.perf{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.ixn{font-size:13px;font-weight:800;color:#9ecbff;margin:10px 0 6px}
.ixn:first-child{margin-top:0}
.perf-vix{margin-top:10px;font-size:13px;color:#9fb0c5}
.perf-vix b{font-size:16px;color:#e6edf3}
.perf-div{font-size:11px;font-weight:800;color:#8fa0b5;margin:10px 0 4px;padding-top:8px;border-top:1px dashed #1c2533}
.vixc{margin-top:10px;font-size:12.5px;color:#9fb0c5}
.vixc-l{font-weight:800;color:#cbd5e1;margin-right:4px}
.vixc b{font-size:15px;color:#e6edf3}
.warnt{color:#fbbf24;font-weight:700}
.ftd-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-top:1px solid #161e2b;font-size:13px}
.ftd-row:first-of-type{border-top:0}
.ftd-x{font-weight:800;color:#cbd5e1}
.perf .c{background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:8px 10px;text-align:center}
.perf .c .k{font-size:11px;color:#7d8da1}.perf .c .v{font-size:16px;font-weight:800;margin-top:2px;font-variant-numeric:tabular-nums}
nav{position:sticky;top:0;z-index:9;background:rgba(11,15,23,.88);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);display:flex;gap:6px;overflow-x:auto;padding:9px 0;border-bottom:1px solid #1c2533;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button,nav a.tabx{flex:0 0 auto;background:#141b29;color:#9fb0c5;border:1px solid #1f2a3a;border-radius:18px;padding:8px 15px;font-size:13px;font-weight:700;transition:background .15s,color .15s;text-decoration:none;display:inline-block;line-height:1.2;cursor:pointer}
nav button.on,nav a.tabx.on{background:#1f6feb;color:#fff;border-color:#1f6feb}
button:focus-visible,a:focus-visible{outline:2px solid #3b82f6;outline-offset:2px}
section{display:none;padding-top:12px}
section.on{display:block}
/* JS無効時のフォールバック: URLハッシュ(:target)で対象セクションを表示。JS有効時はハッシュ未使用で.onが優先。 */
section:target{display:block}
:has(section:target) section:not(:target){display:none}
/* JS無効時: 表示中セクションに合わせてタブ選択色も同期（:targetごとにデフォルトへ戻し当該タブを点灯） */
body:has(#t-market:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-market:target) nav a[href="#t-market"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-alloc:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-alloc:target) nav a[href="#t-alloc"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-port:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-port:target) nav a[href="#t-port"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-today:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-today:target) nav a[href="#t-today"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-rotation:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-rotation:target) nav a[href="#t-rotation"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-movers:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-movers:target) nav a[href="#t-movers"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-rs:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-rs:target) nav a[href="#t-rs"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-weekly:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-weekly:target) nav a[href="#t-weekly"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-post1:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-post1:target) nav a[href="#t-post1"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
body:has(#t-rules:target) nav a.tabx{background:#141b29;color:#9fb0c5;border-color:#1f2a3a}
body:has(#t-rules:target) nav a[href="#t-rules"]{background:#1f6feb;color:#fff;border-color:#1f6feb}
.card{background:#0f1623;border:1px solid #1c2533;border-radius:13px;padding:12px 14px;margin-bottom:12px}
.card h2{font-size:14.5px;font-weight:800;margin-bottom:7px;color:#eef3fa}
.card .sub{font-size:11px;color:#8494ab;line-height:1.55;margin:-3px 0 9px}
.setup-h{display:flex;justify-content:space-between;align-items:baseline;margin:10px 0 6px}
.setup-h .nm{font-size:13px;font-weight:700}
.setup-h .ct{font-size:11px;color:#7d8da1}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:#162132;border:1px solid #243349;border-radius:9px;padding:8px 12px;font-size:12.5px;font-weight:600;color:#cfe0f5;cursor:pointer}
.chip:active{background:#22324a}
.chip.hot{border-color:#2f81f7;color:#9ecbff}
.chip.ov{border-color:#a16207;color:#fde68a;background:#2a210a}
.chip.ov .b{display:inline-block;margin-left:5px;background:#a16207;color:#0b0f17;font-size:10px;font-weight:800;border-radius:5px;padding:0 5px}
/* ①〜⑤ state chips */
.chip.s-buy{background:#0f3d1f;border-color:#1f9d4d;color:#7ff0a8}
.chip.s-shape{background:#1a2130;border-color:#2b3648;color:#aab6c8}
.chip.s-go{background:#10331f;border-color:#1f7a45;color:#86efac}
.chip.s-wait{background:#33290a;border-color:#a16207;color:#fde68a}
.chip.s-deep{background:#3a210f;border-color:#c2660b;color:#fdba74}
.chip.s-break{background:#33161a;border-color:#a13030;color:#fca5a5}
.qb{font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;white-space:nowrap;border:1px solid}
.qb-go{background:#0f3d1f;color:#7ff0a8;border-color:#1d7840}
.qb-wait{background:#11161f;color:#8fa0b5;border-color:#2a3340}
.blkrow td{background:rgba(255,255,255,.018)}
.blkrow .tk{color:#aeb9c7}
/* 本日◎押し目 buy cards */
.buy{background:#0c1a12;border:1px solid #1f6d3c;border-radius:11px;padding:8px 11px;margin-bottom:6px}
.buy-h{display:flex;justify-content:space-between;align-items:baseline}
.buy-h .tk{font-size:16px;font-weight:800;color:#9ff0bb}
.buy-h .rs{font-size:12px;font-weight:700;color:#7d8da1}
.buy-m{font-size:11px;color:#9fb0c5;margin:2px 0 5px}
.buy-g{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}
.buy-g>div{background:rgba(0,0,0,.25);border-radius:7px;padding:4px 6px}
.buy-g .k{display:block;font-size:9px;color:#7d8da1}
.buy-g .v{font-size:12px;font-weight:700}
.cmt{background:linear-gradient(135deg,#0f1b2e,#10233b);border-color:#26415f}
.cmt-b{font-size:14px;line-height:1.65;color:#e6edf3}
.cmt-b b{color:#9ecbff}
.chart{margin-top:4px}
.chart svg{width:100%;height:auto;display:block}
.chart .cap{display:flex;justify-content:space-between;font-size:11px;color:#7d8da1;margin-top:4px}
.empty{color:#5b6b80;font-size:12px;font-style:italic}
.more{display:inline-block;color:#7d8da1;font-size:11px;font-weight:700;padding:4px 2px;vertical-align:middle}
/* copy buttons */
.cp{background:#16263a;border:1px solid #2f4a6a;border-radius:7px;color:#9ecbff;font-size:11px;
    font-weight:700;padding:3px 9px;cursor:pointer}
.cp .n{opacity:.6;font-weight:600}
.pendb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:3px;vertical-align:middle}
.pend-wait{background:rgba(239,68,68,.16);color:#f87171;border:1px solid rgba(239,68,68,.4)}
.pend-ok{background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.4)}
.waitb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;background:rgba(239,68,68,.16);color:#f87171;border:1px solid rgba(239,68,68,.4);vertical-align:middle}
.reg-card{border:1px solid #2b3850}
.reg-hdr{font-size:11px;font-weight:800;border-radius:6px;padding:3px 10px}
.reg-hdr-ok{background:rgba(67,201,138,.14);color:#43c98a;border:1px solid rgba(67,201,138,.35)}
.reg-hdr-warn{background:rgba(227,170,60,.15);color:#e3aa3c;border:1px solid rgba(227,170,60,.4)}
.reg-hdr-bad{background:rgba(229,100,94,.16);color:#e5645e;border:1px solid rgba(229,100,94,.45)}
.reg-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:10px 0 4px}
@media(max-width:640px){.reg-grid{grid-template-columns:1fr}}
.reg-cell{border:1px solid #1e2836;border-radius:10px;padding:11px 12px;background:#0e1420}
.reg-cell.reg-ok{border-color:rgba(67,201,138,.3)}
.reg-cell.reg-warn{border-color:rgba(227,170,60,.4);background:rgba(227,170,60,.05)}
.reg-cell.reg-bad{border-color:rgba(229,100,94,.5);background:rgba(229,100,94,.07)}
.reg-cell.reg-na{opacity:.6}
.reg-k{font-size:10px;letter-spacing:.04em;color:#9fb0c5;font-weight:700}
.reg-v{font-family:ui-monospace,Menlo,monospace;font-size:26px;font-weight:800;line-height:1.1;margin:2px 0}
.reg-ok .reg-v{color:#43c98a}.reg-warn .reg-v{color:#e3aa3c}.reg-bad .reg-v{color:#e5645e}.reg-na .reg-v{color:#55627a}
.reg-l{font-size:11px;font-weight:700;margin-bottom:3px}
.reg-ok .reg-l{color:#43c98a}.reg-warn .reg-l{color:#e3aa3c}.reg-bad .reg-l{color:#e5645e}
.reg-sub{font-size:9.5px;color:#7e8ca0;line-height:1.4}
.reg-chips{margin-top:6px;display:flex;flex-wrap:wrap;gap:3px}
.rgchip{font-family:ui-monospace,Menlo,monospace;font-size:9px;font-weight:700;color:#8fb3ff;background:#121a29;border:1px solid #2b3850;border-radius:4px;padding:1px 4px}
.pqb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;vertical-align:middle}
.pqb.pq-a{background:rgba(67,201,138,.18);color:#43c98a;border:1px solid rgba(67,201,138,.5)}
.pqb.pq-b{background:rgba(143,179,255,.16);color:#8fb3ff;border:1px solid rgba(143,179,255,.45)}
.pqb.pq-c{background:rgba(159,176,197,.12);color:#9fb0c5;border:1px solid rgba(159,176,197,.35)}
.pqb.pq-d{background:rgba(120,132,155,.1);color:#78849b;border:1px solid rgba(120,132,155,.3)}
.pqtag{display:inline-block;font-size:8.5px;font-weight:700;border-radius:4px;padding:0 4px;margin-left:3px;vertical-align:middle}
.pqtag.pq-hi{background:rgba(67,201,138,.14);color:#43c98a}
.pqtag.pq-mid{background:rgba(143,179,255,.13);color:#8fb3ff}
.pqtag.pq-lo{background:rgba(159,176,197,.1);color:#9fb0c5}
.pqtag.pq-neg{background:rgba(229,100,94,.13);color:#e5645e}
.pqbadge{font-size:9px;font-weight:800;color:#8fb3ff;background:rgba(143,179,255,.13);border:1px solid rgba(143,179,255,.4);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.pqnum{font-family:ui-monospace,Menlo,monospace;font-size:14px;color:#43c98a}
.cp-one{font-size:9.5px;padding:1px 7px;margin-left:6px;vertical-align:middle;font-weight:700}
.cp.cp-done{background:#0f3d1f;border-color:#1f9d4d;color:#7ff0a8}
.chaseb{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;vertical-align:middle;background:rgba(240,136,62,.14);color:#f0883e;border:1px solid rgba(240,136,62,.45)}
.inb{background:rgba(56,189,248,.14);border:1px solid rgba(56,189,248,.4);color:#7dd3fc;font-size:9px;font-weight:800;padding:1px 6px;border-radius:6px;margin-left:5px;white-space:nowrap}
.newb{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;vertical-align:middle;background:rgba(88,166,255,.16);color:#8fb3ff;border:1px solid rgba(88,166,255,.45)}
.ppb{display:inline-block;font-size:8.5px;font-weight:800;border-radius:4px;padding:0 4px;margin-left:5px;vertical-align:middle;background:rgba(167,139,250,.14);color:#a78bfa;border:1px solid rgba(167,139,250,.4)}
.ppb-now{background:rgba(67,201,138,.18);color:#43c98a;border-color:rgba(67,201,138,.5)}
.ppx{font-size:10px;font-weight:800;color:#a78bfa;margin-left:5px}
.cfrow{display:flex;align-items:center;gap:10px;padding:7px 9px;border-radius:8px;background:#0e1420;border:1px solid #1e2836;margin-bottom:5px;cursor:pointer;flex-wrap:wrap}
.cfrow.cf-hi{border-color:rgba(67,201,138,.45);background:rgba(67,201,138,.06)}
.cfl{display:flex;align-items:center;gap:7px;min-width:132px}
.cfn{font-size:12px;font-weight:800;color:#0d1117;background:#8fb3ff;border-radius:5px;min-width:20px;text-align:center;padding:1px 0}
.cf-hi .cfn{background:#43c98a}
.cft{font-size:13px;font-weight:800}
.cfs{display:flex;gap:4px;flex-wrap:wrap}
.sgp{font-size:9px;font-weight:700;padding:1px 6px;border-radius:4px;background:#141c2a;color:#9fb0c5;border:1px solid #232f42}
.cflg{margin-top:6px;font-size:10px;color:#6b7788;line-height:1.6}
.cfdet{margin-top:7px}
.cfdet summary{cursor:pointer;font-size:10.5px;color:#8fb3ff;list-style:none;font-weight:700}
.cfdet summary::-webkit-details-marker{display:none}
.cfdet summary::before{content:"▸ ";font-size:9px}
.cfdet[open] summary::before{content:"▾ "}
.ppd{font-size:9px;color:#7e8ca0;margin-left:4px}
.hgrp{margin:10px 0 4px}
.hgrp-h{font-size:12px;font-weight:800;letter-spacing:.03em;display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid #1c2738;margin-bottom:4px}
.hgrp-n{font-size:10px;font-weight:700;color:#7e8ca0;background:#141c2a;border-radius:4px;padding:0 5px}
.hgrp-tap{cursor:pointer}
.hgrp-arr{margin-left:auto;font-size:10px;color:#5f6b7e}
.hgrp-fold .hgrp-body{display:none}
.hgrp-fold.on .hgrp-body{display:block}
.hgrp-fold.on .hgrp-arr{transform:rotate(90deg)}
.entb2{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 8px;margin-left:5px;vertical-align:middle;background:#141c2a;color:#7e8ca0;border:1px solid #2b3850;cursor:pointer}
.entb2.ent-on{background:rgba(67,201,138,.16);color:#43c98a;border-color:rgba(67,201,138,.5)}
.hmper{display:inline-flex;gap:3px;margin-left:auto}
.hmp{font-size:11px;font-weight:700;padding:2px 10px;border-radius:6px;background:#141c2a;color:#7e8ca0;border:1px solid #2b3850;cursor:pointer}
.hmp.on{background:rgba(88,166,255,.16);color:#8fb3ff;border-color:rgba(88,166,255,.5)}
.card h2{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px}
.h2en{font-size:10px;font-weight:600;color:#5b6779;letter-spacing:.04em;text-transform:uppercase}
.msec-en{font-size:10px;font-weight:600;color:#5b6779;letter-spacing:.04em;text-transform:uppercase;margin-left:8px}
.lab-en{font-size:10px;font-weight:600;color:#5b6779;letter-spacing:.05em;text-transform:uppercase;margin-left:8px}
.msec-x{cursor:pointer}
.msec-x .msec-g{display:none;margin-top:7px;padding-top:8px;border-top:1px solid #1c2738;color:#93a1b5;font-size:11.5px;line-height:1.65}
.msec-x.open .msec-g{display:block}
.msec-more{font-size:10px;color:#5f6b7e;font-weight:700;margin-left:4px;white-space:nowrap}
.rrg-more{cursor:pointer;color:#8fb3ff}
.rrg-desc{font-size:11.5px;color:#93a1b5;line-height:1.65;margin:2px 0 10px;padding:9px 11px;background:#0d1420;border:1px solid #1a2434;border-left:3px solid #2b3850;border-radius:8px}
.rrgview .chart{width:100%;max-width:100%}
.rrgview .chart svg{width:100%;height:auto;display:block}
.msec-x.open .msec-more{color:#8fb3ff}
.reg-hd{cursor:pointer}
.reg-tog{font-size:10px;color:#5f6b7e;font-weight:700;margin-left:8px;white-space:nowrap}
.reg-card.folded .reg-body{display:none}
.reg-card.folded .reg-hd{margin-bottom:0}
.bdry td{text-align:center;font-size:9.5px;color:#5f6b7e;padding:4px 0;border-top:1px dashed #2b3850;border-bottom:1px dashed #2b3850;background:#0c1119}
.reg-role{font-size:9px;color:#7e8ca0;line-height:1.4;margin:2px 0 4px}
.reg-kind{font-size:8.5px;font-weight:800;border-radius:4px;padding:1px 4px;margin-left:4px;vertical-align:middle}
.kind-t{background:rgba(88,166,255,.15);color:#8fb3ff;border:1px solid rgba(88,166,255,.4)}
.kind-p{background:rgba(167,139,250,.15);color:#a78bfa;border:1px solid rgba(167,139,250,.4)}
.reg-onset{display:flex;flex-wrap:wrap;gap:4px;margin:1px 0 5px}
.onset{font-size:9px;font-weight:700;border-radius:4px;padding:1px 5px;white-space:nowrap}
.on-bad{background:rgba(229,100,94,.16);color:#e5645e;border:1px solid rgba(229,100,94,.4)}
.on-warn{background:rgba(240,136,62,.14);color:#f0883e;border:1px solid rgba(240,136,62,.38)}
.on-ok{background:rgba(67,201,138,.12);color:#43c98a;border:1px solid rgba(67,201,138,.32)}
.note p,.msec-g p{margin:0 0 7px;line-height:1.7}
.note p:last-child,.msec-g p:last-child{margin-bottom:0}
.note p.mut{color:#6b7788;font-size:10.5px;border-top:1px solid #1c2738;padding-top:6px;margin-top:8px}
.tbbadge{font-size:9px;font-weight:800;color:#f0b849;background:rgba(240,184,73,.13);border:1px solid rgba(240,184,73,.4);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.tbgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px;margin:8px 0}
.tbchip{display:flex;flex-direction:column;gap:1px;padding:6px 9px;border-radius:8px;background:#0e1420;border:1px solid #1e2836;border-left:3px solid #f0b849;cursor:pointer}
.tbchip:hover{background:#0f1726}
.tbtk{font-weight:800;font-size:12.5px}
.tbmeta{font-family:ui-monospace,Menlo,monospace;font-size:9.5px;color:#7e8ca0}
.def-card{border:1px solid rgba(229,100,94,.5);background:rgba(229,100,94,.05)}
.def-badge{font-size:9px;font-weight:800;color:#e5645e;background:rgba(229,100,94,.15);border:1px solid rgba(229,100,94,.45);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.def-list{margin:8px 0 4px;padding-left:0;list-style:none}
.def-list li{font-size:12px;color:#c8d2df;line-height:1.5;padding:5px 0 5px 20px;position:relative;border-top:1px solid #1a2230}
.def-list li:first-child{border-top:none}
.def-list li::before{content:"□";position:absolute;left:2px;color:#e5645e;font-size:11px}
.def-list li b{color:#eef3fa}
.mrgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(212px,1fr));gap:6px;margin-top:8px}
.mrchip{display:flex;align-items:center;gap:6px;padding:6px 9px;border-radius:8px;background:#0e1420;border:1px solid #1e2836;cursor:pointer;min-width:0;overflow:hidden}
.mrchip:hover{background:#0f1726}
.mrchip.run-acc{border-left:3px solid #43c98a}
.mrchip.run-cru{border-left:3px solid #8fb3ff}
.mrchip.run-fade{border-left:3px solid #e5645e}
.mrtk{font-weight:800;font-size:12px;min-width:38px;flex-shrink:0}
.mrph{font-size:9px;font-weight:700;padding:1px 4px;border-radius:4px;background:#121a29;color:#9fb0c5;white-space:nowrap;flex-shrink:0}
.mrchip.run-acc .mrph{color:#43c98a}.mrchip.run-cru .mrph{color:#8fb3ff}.mrchip.run-fade .mrph{color:#e5645e}
.mrtr{font-family:ui-monospace,Menlo,monospace;font-size:9.5px;color:#7e8ca0;margin-left:auto;white-space:nowrap;flex:0 1 auto;min-width:0;letter-spacing:-0.2px;overflow:hidden;text-overflow:ellipsis}
.mrtr b{color:#dbe4ef}
.mr-acc{color:#43c98a}.mr-cru{color:#8fb3ff}.mr-fad{color:#e5645e}
.okb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.4);vertical-align:middle}
.row-carry{background:rgba(96,165,250,.06)}
.coil{display:inline-block;width:52px;height:7px;border-radius:4px;background:#1c2533;overflow:hidden;vertical-align:middle;margin-right:4px}
.coil i{display:block;height:7px;border-radius:4px;background:linear-gradient(90deg,#22c55e,#84cc16)}
.adrb{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle}
.adr-lo{background:rgba(148,163,184,.18);color:#94a3b8;border:1px solid rgba(148,163,184,.4)}
.adr-hi{background:rgba(234,88,12,.16);color:#fb923c;border:1px solid rgba(234,88,12,.42)}
.r3b{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;background:rgba(34,197,94,.18);color:#4ade80;border:1px solid rgba(34,197,94,.45);vertical-align:middle}
.shallow{display:inline-block;font-size:9px;font-weight:800;border-radius:4px;padding:0 4px;margin-left:4px;background:rgba(234,88,12,.18);color:#fb923c;border:1px solid rgba(234,88,12,.5);vertical-align:middle}
.entb{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle;border:1px solid}
.ent-good{background:rgba(34,197,94,.16);color:#4ade80;border-color:rgba(34,197,94,.45)}
.ent-ok{background:rgba(56,189,248,.14);color:#7dd3fc;border-color:rgba(56,189,248,.4)}
.ent-lo{background:rgba(148,163,184,.16);color:#9fb0c5;border-color:rgba(148,163,184,.4)}
.ent-warn{background:rgba(234,179,8,.16);color:#eab308;border-color:rgba(234,179,8,.42)}
.ent-bad{background:rgba(239,68,68,.16);color:#f87171;border-color:rgba(239,68,68,.45)}
.fadeb{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle;border:1px solid}
.fade-lo{background:rgba(234,179,8,.14);color:#eab308;border-color:rgba(234,179,8,.4)}
.fade-hi{background:rgba(239,68,68,.18);color:#f87171;border-color:rgba(239,68,68,.5)}
.rspbar{margin:6px 0 2px}
.rsper{background:#132033;border:1px solid #24344a;color:#c7d2fe;font-size:12px;font-weight:700;border-radius:8px;padding:6px 12px;cursor:pointer}
.rsper:active{background:#1a2942}
.slrow{padding:8px 0;border-top:1px solid #141c28}
.slrow:first-of-type{border-top:0}
.slname{font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:5px}
.rotb{display:inline-block;font-size:10px;font-weight:800;border-radius:5px;padding:1px 6px;border:1px solid;background:#0b1220}
.rk-leg{margin:2px 0 8px}
.rk-leg summary{font-size:12px;color:#7dd3fc;cursor:pointer;padding:4px 0;list-style:none}
.rk-leg summary::-webkit-details-marker{display:none}
.rk-leg summary:before{content:"▸ ";color:#8b9bb0}
.rk-leg[open] summary:before{content:"▾ "}
.lbmood{font-size:15px;font-weight:800;margin:6px 0 10px}
.lbrow{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-top:8px}
.lbk{font-size:13px;font-weight:700;color:#e6edf3}
.lbv{font-size:15px;font-weight:800;color:#e6edf3}
.lbbar{position:relative;height:8px;background:#131c28;border-radius:5px;margin:5px 0 2px;overflow:hidden}
.lbfill{position:absolute;left:0;top:0;height:8px;border-radius:5px}
.lbmark{position:absolute;top:-1px;width:2px;height:10px;background:#3b4b63}
.lbsub{font-size:11px;color:#8b9bb0;margin-bottom:4px}
.lbnote{font-size:11px;color:#8b9bb0;margin-top:10px;border-top:1px solid #141c28;padding-top:8px}
.lbchips{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin:2px 0 8px}
.lbcl{font-size:10px;font-weight:700;color:#8b9bb0;margin-right:2px}
.chip.warn{background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.4);color:#f5b5b5}
.chip.tl-go{background:rgba(34,197,94,.16);border-color:rgba(34,197,94,.5);color:#bbf7d0}
.chip.tl-ok{background:rgba(56,189,248,.12);border-color:rgba(56,189,248,.4);color:#bae6fd}
.chip.tl-wait{background:#131c28;border-color:#26344a;color:#9fb0c5}
.chip.run-acc{background:rgba(34,197,94,.16);border-color:rgba(34,197,94,.5);color:#bbf7d0}
.chip.run-cru{background:rgba(56,189,248,.10);border-color:rgba(56,189,248,.35);color:#bae6fd}
.chip.run-fade{background:rgba(234,88,12,.14);border-color:rgba(234,88,12,.45);color:#fdba74}
.rflag{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:5px;vertical-align:middle;border:1px solid}
.rf-hi{background:rgba(239,68,68,.2);color:#fca5a5;border-color:rgba(239,68,68,.6)}
.rf-crit{background:#7f1d1d;color:#fecaca;border-color:#ef4444;box-shadow:0 0 0 1px rgba(239,68,68,.4)}
.dov-flag-crit{background:rgba(127,29,29,.5);border:1px solid #ef4444;color:#fecaca}
.rf-md{background:rgba(234,179,8,.16);color:#eab308;border-color:rgba(234,179,8,.45)}
.dov-flag{border-radius:10px;padding:10px 12px;margin:2px 0 10px;font-weight:800;font-size:14px}
.dov-flag-hi{background:rgba(239,68,68,.14);border:1px solid rgba(239,68,68,.5);color:#fca5a5}
.dov-flag-md{background:rgba(234,179,8,.12);border:1px solid rgba(234,179,8,.45);color:#eab308}
.dov-flag-n{font-weight:500;font-size:12px;color:#e6edf3;margin-top:5px;line-height:1.5}
.dov-flag-s{font-weight:500;font-size:11px;color:#8b9bb0;margin-top:5px}
.patblk{padding:8px 0;border-top:1px solid #141c28}
.patblk:first-of-type{border-top:0}
.patname{font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:5px}
.swin{display:flex;flex-direction:column;gap:8px;margin:8px 0}
.swrow{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.swlab{flex:0 0 108px;font-size:12px;color:#9fb0c5;font-weight:700}
.swin input,.swin select{flex:1;min-width:120px;background:#0b1220;border:1px solid #24344a;color:#e6edf3;border-radius:8px;padding:8px 10px;font-size:15px}
.swout{margin-top:6px}
.swkey{font-size:15px;font-weight:700;color:#e6edf3;margin:6px 0 10px}
.swkey b{color:#7dd3fc;font-size:18px}
.swline{display:flex;justify-content:space-between;align-items:baseline;gap:8px;padding:4px 0;border-top:1px solid #141c28;font-size:13px}
.swline span:first-child{color:#9fb0c5}
.swladder{display:flex;gap:6px;margin:8px 0 10px}
.swb{flex:1;border-radius:8px;padding:7px 4px;text-align:center;border:1px solid #24344a;background:#0b1220}
.swbl{font-size:10px;color:#9fb0c5;font-weight:700}
.swbp{font-size:14px;font-weight:800;color:#e6edf3;margin:2px 0}
.swbc{font-size:11px;font-weight:700}
.swbs{font-size:10px;color:#8b9bb0;margin-top:2px}
.swb-stop{border-color:rgba(239,68,68,.5)}.swb-stop .swbc{color:#f87171}
.swb-ent{border-color:rgba(148,163,184,.5)}
.swb-t2{border-color:rgba(56,189,248,.45)}.swb-t2 .swbc{color:#7dd3fc}
.swb-t3{border-color:rgba(34,197,94,.5)}.swb-t3 .swbc{color:#4ade80}
.carryb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;background:rgba(96,165,250,.16);color:#60a5fa;border:1px solid rgba(96,165,250,.4);vertical-align:middle}
.chip-tap{cursor:pointer}
.chip-arr{margin-left:3px;color:#8b949e;font-weight:800}
.hier-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:100;align-items:center;justify-content:center;padding:16px}
.hier-modal.on{display:flex}
.hier-box{background:#111722;border:1px solid #2f4a6a;border-radius:14px;padding:18px;max-width:460px;width:100%;max-height:82vh;overflow:auto}
.hier-box h3{font-size:15px;margin-bottom:2px}
.hier-box .hb-sub{font-size:11px;color:#8b949e;margin-bottom:12px}
.hsub-row{border-bottom:1px solid #1c2533;padding:9px 0}
.hsub-row:last-child{border:0}
.hsub-hd{display:flex;align-items:center;justify-content:space-between;cursor:pointer}
.hsub-name{font-size:12.5px;font-weight:700}
.hsub-q{font-size:9px;font-weight:800;padding:1px 6px;border-radius:5px;margin-left:6px}
.hsub-meta{font-size:11px;color:#8b949e}
.hsub-mem{display:none;flex-wrap:wrap;gap:6px;margin-top:8px}
.hsub-mem.on{display:flex}
.hmem{background:#0e1622;border:1px solid #263850;border-radius:7px;padding:3px 8px;font-size:11px;cursor:pointer}
.hmem .rsb{margin-left:4px;color:#9ecbff;font-weight:700}
.hback{background:#16263a;border:1px solid #2f4a6a;border-radius:7px;color:#9ecbff;font-size:11px;padding:3px 10px;cursor:pointer;margin-bottom:10px}
.copybtn{background:#16263a;border:1px solid #2f4a6a;border-radius:7px;color:#9ecbff;font-size:11px;font-weight:700;padding:3px 9px;cursor:pointer;vertical-align:middle;margin-left:8px}
.copybtn.done{background:#0d3320;border-color:#238636;color:#3fb950}
.exq{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:4px;background:rgba(139,148,158,.16);color:#8b949e;border:1px solid rgba(139,148,158,.4)}
.skip-note{font-size:11px;color:#eab308;background:rgba(234,179,8,.08);border-radius:8px;padding:8px 10px;margin:8px 0}
.lagb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:4px;background:rgba(234,179,8,.16);color:#eab308;border:1px solid rgba(234,179,8,.4)}
tr.row-excluded{opacity:.5}
tr.row-excluded td{text-decoration:line-through;text-decoration-color:rgba(139,148,158,.5)}
.cp.done{background:#0f3d1f;border-color:#1f9d4d;color:#7ff0a8}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px}
.hdr h2{margin:0}
table{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:4px 5px;border-bottom:1px solid #18212f;white-space:nowrap}.dhbanner{margin:0 0 10px;padding:9px 12px;background:#3a2410;color:#fde68a;border:1px solid #b45309;border-radius:9px;font-size:12px;line-height:1.5}.tbl{table-layout:fixed;width:100%}.tbl th,.tbl td{white-space:normal;overflow-wrap:break-word;vertical-align:top;line-height:1.35}.tbl th:nth-child(1),.tbl td:nth-child(1){width:24%}.tbl th:nth-child(2),.tbl td:nth-child(2){width:46%}.tbl th:nth-child(3),.tbl td:nth-child(3){width:17%}.tbl th:nth-child(4),.tbl td:nth-child(4){width:13%}.tbl td:first-child{text-align:left}.tbl td:first-child b{white-space:nowrap}.tbl td:first-child .rsx-badge{white-space:nowrap;margin-left:3px;padding:1px 3px;font-size:8px}.tbl td:nth-child(3),.tbl th:nth-child(3){white-space:nowrap}
.thcell{display:flex;align-items:baseline;gap:4px;min-width:0}.thnm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;font-size:11.5px}.thmom{flex:0 0 auto;font-size:10px}
td.l,th.l{white-space:normal}
th{color:#8595aa;font-weight:700;font-size:10.5px;letter-spacing:.05em}
td.l,th.l{text-align:left}
.tk{font-weight:700;color:#e6edf3}
.pos{color:#4ade80}.neg{color:#f87171}.mut{color:#8595aa}
.bar{height:6px;border-radius:4px;background:#16202e;overflow:hidden;min-width:54px;display:inline-block;vertical-align:middle}
.bar i{display:block;height:100%;background:#2f81f7}
.alloc{display:flex;height:30px;border-radius:8px;overflow:hidden;margin:6px 0}
.alloc div{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff}
.a-ind{background:#1f6feb}.a-lev{background:#8957e5}.a-cash{background:#3d4858}
.note{font-size:11px;color:#7d8da1;line-height:1.5;margin-top:6px}
.calcfold{margin:2px 0 8px}
.calcfold>summary{font-size:10px;color:#55627a;cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:3px;padding:1px 0;user-select:none;letter-spacing:.03em}
.calcfold>summary::-webkit-details-marker{display:none}
.calcfold>summary::before{content:"▸";font-size:8px;transition:transform .15s;color:#55627a}
.calcfold[open]>summary::before{transform:rotate(90deg)}
.calcfold>summary:hover{color:#8494ab}
.calcfold[open]>summary{margin-bottom:4px}
.calcfold .sub,.calcfold .note,.calcfold .lbnote,.calcfold .rk-note{margin-top:0}
.kv{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #18212f;font-size:12.5px}
.kv .k{color:#9fb0c5}.kv .v{font-weight:700}
ul.rules{font-size:12.5px;line-height:1.7;padding-left:18px;color:#cbd5e1}
ul.rules li{margin-bottom:4px}
.rh{font-size:13px;font-weight:800;color:#9ecbff;margin:14px 0 4px}
.nqt{margin:6px 0 2px}
.nqt th,.nqt td{text-align:center}
.nqt td.l,.nqt th.l{text-align:left}
.nqt tr.hl{background:rgba(56,161,105,.14)}
.nqt tr.hl td{font-weight:800;color:#e6edf3}
.nqd{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
.nqd.c-bl{background:#3b82f6}.nqd.c-gr{background:#22c55e}
.nqd.c-yl{background:#eab308}.nqd.c-rd{background:#ef4444}
.warn{background:#1a1206;border:1px solid #5c4410;border-radius:8px;padding:8px 10px;font-size:11.5px;color:#d6b56a;margin-top:8px}
/* ② distribution-day dates */
.dddays{font-size:10px;color:#7d8da1;margin-top:4px;line-height:1.5}
/* ⑤ index 200MA extension card */
.extbl{display:flex;flex-direction:column;gap:6px}
.exrow{display:flex;align-items:center;gap:10px;background:#0b1220;border:1px solid #1c2533;border-radius:9px;padding:8px 10px}
.exk{flex:0 0 84px;font-size:13px;font-weight:700;color:#e6edf3}
.exv{flex:0 0 64px;font-size:14px;font-weight:800;text-align:right}
.exn{flex:1;text-align:right;font-size:12px;font-weight:700}
.ex-good{color:#4ade80}.ex-warn{color:#9fb0c5}.ex-bad{color:#f87171}
/* ⑥ status breakdown panel */
.banner{cursor:pointer}
.cmt-sub{font-size:11px;color:#8b949e;margin:2px 0 10px;line-height:1.5}
.cmt-rot h2{font-size:15px}
.tap{font-size:10px;font-weight:700;color:#9ecbff;opacity:.85;margin-left:6px}
.mri-bd{display:none;cursor:default;margin-top:10px;background:rgba(0,0,0,.28);border-radius:10px;padding:10px 12px}
.mri-bd.open{display:block}
.mbd-h{font-size:12px;font-weight:800;color:#cbd5e1;margin-bottom:6px}
.mgrp{font-size:10px;font-weight:700;color:#9ecbff;letter-spacing:.04em;margin:8px 0 2px}
.mgrp:first-of-type{margin-top:0}
.mrow{display:flex;align-items:center;gap:8px;padding:3px 0}
.mk2{flex:0 0 116px;font-size:11px;color:#cbd5e1}
.mraw{flex:0 0 58px;font-size:11px;font-weight:700;text-align:right;color:#e6edf3}
.mbar{flex:1;height:6px;border-radius:4px;background:#16202e;overflow:hidden}
.mbar i{display:block;height:100%;background:#2f81f7}
.mpts{flex:0 0 50px;font-size:10px;color:#9fb0c5;text-align:right}
.mnote{font-size:10px;color:#7d8da1;text-align:center;margin-top:6px}
.bflags{display:flex;flex-wrap:wrap;gap:5px;margin-top:2px}
.bfl{font-size:10px;font-weight:700;border-radius:6px;padding:2px 7px}
.bfl.on{background:#3a1414;color:#fca5a5;border:1px solid #7f1d1d}
.bfl.off{background:#0f1622;color:#5b6b80;border:1px solid #1c2533}
/* ⑧ 本日のピックアップ */
.hot-card{border-color:#2f81f7}
.bt{background:#0c1422;border:1px solid #233149;border-radius:10px;padding:7px 10px;margin-bottom:6px}
.bt-h{display:flex;align-items:baseline;gap:8px}
.bt-h .tk{font-size:15px;font-weight:800;color:#9ecbff}
.bt-h .rs{margin-left:auto;font-size:12px;font-weight:700;color:#7d8da1}
.bt-tag{font-size:10px;font-weight:800;border-radius:6px;padding:1px 7px}
.st-break{color:#06210f;background:#7ff0a8}
.st-base{color:#241c00;background:#fcd34d}
.st-pull{color:#0a1830;background:#9cc2ff}
.st-high{color:#c7d2fe;background:#2a2f45}
.st-turn{color:#d8c9ff;background:#34245c}
.st-fail{color:#fecaca;background:#641f2a}
.scrtab{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
.techscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scrtab th{font-size:10px;color:#7f8ea3;font-weight:700;text-align:right;padding:3px 6px;border-bottom:1px solid #1c2433}
.scrtab th.l{text-align:left}
.scr-row td{padding:5px 6px;border-bottom:1px solid #141b27;text-align:right}
.scr-tk{font-weight:800;color:#cfe0f5;text-align:left!important;white-space:nowrap}.scr-tk .bt-tag{margin-left:6px}.scr-rank{font-size:11px;font-weight:900;color:#8fb3ff;text-align:center!important}
.scr-c{font-variant-numeric:tabular-nums}
.scr-star{color:#ffd34d;margin-left:3px;font-size:11px}.scr-core{font-size:8.5px;font-weight:800;color:#bfdbfe;background:#12275e;border:1px solid #2563eb;border-radius:4px;padding:0 3px;margin-left:3px;vertical-align:middle}
.scr-gh td{padding:8px 6px 2px;text-align:left}
.scr-gn{font-size:11px;color:#9fb0c5;margin-left:6px;font-weight:700}
.scr-gd{font-size:10px;color:#7f8ea3;margin-left:6px}
.scr-ch td{font-size:10px;color:#7f8ea3;font-weight:700;text-align:right;padding:1px 6px 5px;border-bottom:1px solid #1c2433}
.scr-ch td.l{text-align:left}
.ghb-break td{background:rgba(55,210,127,.06)}
.ghb-base td{background:rgba(252,211,77,.07)}
.ghb-pull td{background:rgba(156,194,255,.07)}
.ghb-high td{background:rgba(130,142,170,.07)}
.ghb-break td:first-child{border-left:3px solid #37d27f}
.ghb-base td:first-child{border-left:3px solid #fcd34d}
.ghb-pull td:first-child{border-left:3px solid #9cc2ff}
.ghb-high td:first-child{border-left:3px solid #6b7689}
.scr-pos{white-space:nowrap;text-align:left}
.posbar{display:inline-block;width:46px;height:7px;border-radius:4px;background:#26334a;vertical-align:middle;overflow:hidden;margin-right:6px}
.posfill{display:block;height:100%;background:linear-gradient(90deg,#5b7fb0,#9cc2ff);border-radius:4px}
.posn{font-size:11px;color:#9fb0c5;vertical-align:middle;font-variant-numeric:tabular-nums}
.bt-held{font-size:9px;font-weight:700;color:#0b0e14;background:#7ff0a8;border-radius:4px;padding:1px 5px;margin-left:5px}
.role-tag{font-size:10px;font-weight:700;border-radius:5px;padding:1px 7px;vertical-align:middle;margin-left:6px}
.rt-view{color:#9cc2ff;background:#16243e}
.rt-act{color:#7ff0a8;background:#0c2a1c}
.bt-good{background:#0f3d1f;color:#7ff0a8}
.bt-warn{background:#33290a;color:#fde68a}
.bt-bad{background:#3a210f;color:#fdba74}
.bt-g{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:6px}
.bt-g>div{background:rgba(0,0,0,.25);border-radius:7px;padding:4px 6px}
.bt-g .k{display:block;font-size:9px;color:#7d8da1}
.bt-g .v{font-size:12px;font-weight:700}
.bt-g .v.bt-good{background:none;color:#4ade80}
.bt-g .v.bt-warn{background:none;color:#9fb0c5}
.bt-g .v.bt-bad{background:none;color:#f87171}
/* §4 tap-to-ticker detail bottom-sheet */
.chip,.bt-h .tk,.buy-h .tk{cursor:pointer}
.dov-bg{display:none;position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.55);align-items:flex-end;justify-content:center}
.dov-bg.open{display:flex}
.dov{width:100%;max-width:680px;max-height:88vh;overflow-y:auto;background:#0f1623;border:1px solid #1c2533;border-bottom:none;border-radius:16px 16px 0 0;padding:16px 16px 28px;box-shadow:0 -8px 30px rgba(0,0,0,.5)}
.dov-h{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}
.dov-tk{font-size:20px;font-weight:800;color:#9ecbff}
.dov-x{font-size:18px;color:#7d8da1;cursor:pointer;padding:4px 10px}
.dov-nm{font-size:12px;color:#7d8da1;margin-bottom:10px}
.dov-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.dov-status{margin:2px 0 12px}
.dov-spark{width:100%;height:58px;margin:2px 0 12px;background:rgba(0,0,0,.02);border:1px solid rgba(0,0,0,.07);border-radius:9px;padding:7px 9px;box-sizing:border-box;position:relative}
.dov-spark svg.spark{width:100%;height:100%;margin:0;display:block}
.dov-spark .lbl{position:absolute;top:5px;left:9px;font-size:9.5px;font-weight:700;color:#9aa3ad;letter-spacing:.03em;pointer-events:none}
.dov-spark.empty{display:none}
.dov-tv{font-size:12px;font-weight:800;color:#2456A6;text-decoration:none;opacity:.9;white-space:nowrap;letter-spacing:.02em}
.dov-tv:active{opacity:.6}
.msec{margin:22px 0 8px;padding-top:14px;border-top:2px solid #1c2738;scroll-margin-top:56px}
section>.msec:first-child,section>.card:first-child{margin-top:6px}
section>.msec:first-child{border-top:none;padding-top:4px}
.msec-l{font-size:16px;font-weight:800;color:#e6edf3;letter-spacing:.02em}
.msec-q{font-size:12px;color:#a8b6c8;margin-top:2px;line-height:1.4}
.msec-g{font-size:11px;color:#93a3b8;line-height:1.6;margin-top:7px;padding:9px 11px;background:#0d1420;border:1px solid #1a2434;border-left:3px solid #2b3850;border-radius:8px}
.msec-g b{color:#c8d2df}
.disc{color:#5b6b80;font-size:11px;text-align:center;margin:26px 0 10px}
.gatebox{display:flex;align-items:center;gap:12px;margin:10px 0 14px}
.gate-c{font-size:18px;font-weight:800;color:#fff;border-radius:10px;padding:8px 16px;white-space:nowrap}
.gate-meta{font-size:13px;color:#cdd9ea;line-height:1.5}
.calc-in{display:flex;flex-direction:column;gap:8px;margin:8px 0 6px}
.ci-row{display:flex;align-items:center;gap:8px}
.ci-pre{font-size:18px;color:#8b9bb0;font-weight:700}
.ci-row input,.ci-row2 input{flex:1;min-width:0;background:#0b1220;border:1px solid #243044;border-radius:9px;color:#e6edf3;font-size:17px;padding:10px 12px;-webkit-appearance:none}
.ci-row2{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.ci-row2 input{flex:0 0 92px;font-size:14px;padding:7px 10px}
.ci-fxl{font-size:12px;color:#8b9bb0;font-weight:700}
.calc-sum{margin:8px 0}
.cs-row{display:flex;justify-content:space-between;align-items:center;padding:6px 2px;border-bottom:1px solid #161e2b;font-size:13px;color:#aab6c6}
.cs-row b{color:#e6edf3;font-size:14px}
.cs-cash b{color:#7ff0a8}
.lev-box{background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:10px 12px;margin:8px 0}
.lev-h{font-size:12px;color:#9fb0c5;margin-bottom:6px;font-weight:700}
.lev-r{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:14px}
.lev-r span:first-child{flex:0 0 56px;font-weight:700;color:#cdd9ea}
.lev-r b{flex:0 0 auto;color:#e6edf3}
.lev-r .mut{flex:1;text-align:right}
.soxl-tr{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 0 2px;font-size:12px;border-top:1px dashed #1c2533;margin-top:4px}
.soxl-tr .mut{flex:1;min-width:140px}
.soxl-btns{display:flex;gap:6px;flex:0 0 auto}
.soxl-btns .nqb{font-size:11px;padding:3px 8px}
.calc-tab{width:100%;border-collapse:collapse;margin-top:6px}
.calc-tab th{font-size:10px;color:#7f8da3;font-weight:700;text-align:right;padding:4px 6px;border-bottom:1px solid #243044}
/* --- v3 additions: sentiment / equity / ribbon / heatmap / changelog / trail --- */
.sn-hero{display:flex;align-items:baseline;gap:12px;margin:6px 0 2px}
.sn-num{font-size:38px;font-weight:900;line-height:1}
.sn-band{font-size:15px;font-weight:800}
.sn-cur{font-size:13px;font-weight:700;margin:8px 0 4px;line-height:1.2}
.sn-gauge{position:relative;height:10px;border-radius:6px;margin:6px 0 2px;
  background:linear-gradient(90deg,#22c55e 0 15%,#38bdf8 15% 35%,#64748b 35% 65%,#f97316 65% 85%,#ef4444 85% 100%);opacity:.9}
.sn-gauge i{position:absolute;top:-3px;width:4px;height:16px;background:#fff;border-radius:2px;box-shadow:0 0 6px #000}
.sn-gl{display:flex;justify-content:space-between;font-size:10px;color:#7d8da1;margin-bottom:8px}
.sn-ref{font-size:9px;font-weight:800;color:#7d8da1;background:#141c2b;border-radius:5px;padding:1px 5px;margin-left:5px}
.sn-note{font-size:10px;color:#5b6b80;margin:0 0 4px 0;padding-left:2px}
/* 要因分解 */
.attrib{margin-top:9px;background:#0b1220;border:1px solid #22304a;border-radius:10px;padding:9px 11px}
.attrib-h{font-size:11.5px;font-weight:800;color:#cfe0f5;margin-bottom:6px}
.attrib-g{display:flex;flex-wrap:wrap;align-items:baseline;gap:5px 7px;font-size:12px;margin-top:2px;font-variant-numeric:tabular-nums}
.attrib-g b{font-size:14px}
.atk{color:#8fa0b5;font-size:11px}
.atsub{font-size:9.5px;color:#5b6b82;margin-left:2px}
.eqrow{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:6px 0}
.eqkv{font-size:12px;color:#9fb0c5}.eqkv b{font-size:14px}
.ribwrap{margin:10px 0 12px}
.riblab{font-size:10px;color:#7d8da1;margin-bottom:4px;font-weight:700;letter-spacing:.03em}
.ribbon{display:flex;gap:1.5px}
.ribbon .rb{flex:1;height:16px;border-radius:2.5px;min-width:2px}
.rb.c-bl{background:#3b82f6}.rb.c-gr{background:#22c55e}.rb.c-yl{background:#eab308}.rb.c-rd{background:#ef4444}
.led{display:inline-flex;gap:2px;margin-left:8px;vertical-align:middle}
.led i{width:9px;height:12px;border-radius:2px;background:#1c2533;display:inline-block}
.led i.on{background:linear-gradient(180deg,#fca5a5,#ef4444);box-shadow:0 0 5px #ef444488}
.ch-card{border-color:#2f4a6a}
ul.chlog{font-size:13px;line-height:1.8;padding-left:18px;color:#dbe4ef;margin:4px 0}
ul.chlog li{margin-bottom:2px}
.hmgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:6px;margin-top:6px}
.hm{border-radius:9px;padding:8px 8px;display:flex;flex-direction:column;gap:2px;min-height:44px;border:1px solid rgba(0,0,0,.07)}
.hm-n{font-size:11px;font-weight:800;line-height:1.25}
.hm-tk{display:block;font-size:9px;font-weight:700;letter-spacing:.03em;margin-top:1px}
.hm-v{font-size:12px;font-weight:900}
.erb{font-size:9px;font-weight:800;color:#0b0e14;background:#fbbf24;border-radius:4px;padding:1px 6px;margin-left:5px;vertical-align:middle}
.rsd{font-size:10px;font-weight:800;margin-left:3px}
.rsd.up{color:#4ade80}.rsd.dn{color:#f87171}.rsd.fl{color:#4b5866}
.tday{font-size:9px;color:#7d8da1;font-weight:400}
.risknote{border-top:1px dashed #1c2533;padding-top:6px}
.dov-stage{display:flex;align-items:center;gap:8px;border-radius:9px;padding:7px 10px;margin-bottom:6px}
.dov-stage b{font-size:14px;font-weight:900}
.dov-stg-w{font-size:11.5px;opacity:.85}
.dov-stage.stg1{background:#1f2937;color:#cbd5e1;border:1px solid #4b5563}
.dov-stage.stg2{background:#12275e;color:#bfdbfe;border:1px solid #2563eb}
.dov-stage.stg3{background:#3d2a08;color:#fde68a;border:1px solid #ca8a04}
.dov-stage.stg4{background:#3a1414;color:#fca5a5;border:1px solid #dc2626}

/* 要因分解 */
.thgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}
.thtile{text-align:left;border:1px solid #22304a;border-radius:11px;padding:9px 11px;cursor:pointer;
        display:flex;flex-direction:column;gap:3px;color:#e6edf3;transition:border-color .15s}
.thtile.on{border-color:#e6edf3;box-shadow:0 0 0 1px #e6edf3 inset}
.tht-n{font-size:13.5px;font-weight:800}
.tht-m{font-size:11px;color:#cbd5e1;font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:6px}
.tht-m b{font-size:13px;color:#fff}
.tht-c{margin-left:auto;color:#8fa0b5;font-weight:600}
.thpanel{margin-top:9px;background:#0b1220;border:1px solid #22304a;border-radius:11px;padding:10px 11px}
.thpanel-h{font-size:12.5px;font-weight:800;color:#eef3fa;margin-bottom:8px}
.thpanel-h .mut{font-weight:500}
.thstks{display:flex;flex-wrap:wrap;gap:6px}
.thstk{display:inline-flex;align-items:center;gap:5px;background:#152134;border:1px solid #26374f;
       border-radius:8px;padding:5px 9px;font-size:12px;cursor:pointer;font-variant-numeric:tabular-nums}
.thstk:active{background:#1e2f49}
.thstk b{color:#cfe0f5;font-weight:800}
.thstk-rs{color:#8fa0b5;font-size:10.5px;font-weight:700}
.thstk-m{font-size:10px}
.thmore{align-self:center;color:#7d8da1;font-size:11px;font-weight:700;padding:0 4px}
.rrgtog{display:flex;gap:4px}
.rtg{background:#141b29;color:#9fb0c5;border:1px solid #1f2a3a;border-radius:14px;padding:4px 11px;font-size:11px;font-weight:700;cursor:pointer}
.rtg.on{background:#1f6feb;color:#fff;border-color:#1f6feb}
.rrgseed{font-size:12.5px;color:#bfe3ff;background:#0e2036;border:1px solid #1d3a55;border-radius:9px;padding:7px 10px;margin:8px 0 4px}
.rrgq{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:7px}
.rrgq-l{font-size:11px;font-weight:900;min-width:34px}
.shiftrow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:2px 0 10px}
.secparent{font-size:9.5px;color:#5a6b82;margin-top:2px;font-weight:500}
.shl{font-size:10px;font-weight:900;color:#4ade80}
.shl-n{color:#f87171;margin-left:6px}
.chip.shp{border-color:#14532d;color:#a7f3d0}
.chip.shn{border-color:#7f1d1d;color:#fecaca}
.le-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:6px 0 2px}
.le-k{font-size:11px;font-weight:900;color:#9fb0c5;min-width:76px;letter-spacing:.03em}
.le-v{font-size:15px;font-weight:800;color:#e6edf3}
.le-pct{font-size:11px;color:#9fb0c5;font-weight:600;margin-left:3px}
.le-rot{font-size:14px;font-weight:900}
.le-sub{font-size:11px;color:#7d8da1}
.le-size{font-size:12px;font-weight:800;margin-left:auto;padding:2px 9px;border-radius:7px;background:#141c2b}
.le-size.pos{color:#7ff0a8}.le-size.neg{color:#fca5a5}.le-size.mut{color:#cbd5e1}
.le-vg{margin:6px 0 2px}


.calc-tab th.l{text-align:left}
.calc-tab td{text-align:right;padding:7px 6px;border-bottom:1px solid #131a26;font-size:13px;vertical-align:top}
.calc-tab td.l{text-align:left}
.entIn{width:74px;background:#0b1220;border:1px solid #243044;border-radius:7px;color:#e6edf3;font-size:13px;padding:5px 7px;text-align:right;-webkit-appearance:none}
.calc-empty{color:#6b7a8d;font-size:13px;text-align:center;padding:18px 0}
.calc-mem{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}
.memx{background:#0b1220;border:1px solid #2a3850;color:#cdd9ea;border-radius:8px;font-size:12px;padding:6px 10px}
.memx:active{background:#0f1a2c}
.tkbtn{display:block;margin-top:5px;width:74px;background:#0b1220;border:1px solid #3a2a12;color:#d9b06a;border-radius:7px;font-size:10px;padding:4px 0;text-align:center}
.tkbtn.on{background:#3a2a12;border-color:#ca8a04;color:#fcd34d;font-weight:700}
.tkbtn:active{opacity:.7}
.redep{background:#0b1220;border:1px solid #20304a;border-radius:10px;padding:10px 12px;margin:8px 0}
.todayact{border:1px solid #243044;border-left:4px solid #6b7280;border-radius:11px;background:#121a26;padding:9px 12px;margin:0 0 10px}
.todayact.ta-blue{border-left-color:#4d9fff}.todayact.ta-green{border-left-color:#34d39c}
.todayact.ta-yellow{border-left-color:#fbbf24}.todayact.ta-red{border-left-color:#f87171}.todayact.ta-gray{border-left-color:#6b7280}
.ta-h{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:#7f8da3;font-weight:700}
.ta-top{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:5px}
.ta-col{font-weight:800;font-size:14px}
.todayact.ta-blue .ta-col{color:#4d9fff}.todayact.ta-green .ta-col{color:#34d39c}
.todayact.ta-yellow .ta-col{color:#fbbf24}.todayact.ta-red .ta-col{color:#f87171}.todayact.ta-gray .ta-col{color:#9aa4b2}
.ta-expo{font-size:12.5px;color:#cbd5e1}
.ta-est{font-size:10px;color:#fbbf24;border:1px solid #5b4a1f;border-radius:5px;padding:1px 6px}
.ta-act{font-size:12.5px;font-weight:600;line-height:1.4;padding:6px 9px;border-radius:7px;background:#0d1420}
.ta-act.ta-alert{color:#fecaca;background:#2a1416;border:1px solid #7f1d1d}
.ta-act.ta-change-up{color:#bfdbfe;background:#0f1d2e}
.ta-act.ta-change-dn{color:#fde68a;background:#241c0a}
.ta-act.ta-normal{color:#9aa4b2;background:transparent;padding-left:0}
.ta-rebal{margin-top:6px;font-size:12px;color:#c7d2fe;background:#161a2e;border-radius:7px;padding:6px 9px}
.ta-go{font-size:11.5px;font-weight:700;color:#a5c8ff;cursor:pointer;margin-left:auto;white-space:nowrap}
.ta-rec{margin-top:7px;display:flex;flex-wrap:wrap;gap:5px;align-items:center;font-size:11.5px;color:#9fb0c5}
.ta-reclab{color:#7f8ea3}
.nqb{font-size:11.5px;font-weight:800;border:1px solid #2a3950;background:#161d2b;color:#cfe0f5;border-radius:6px;padding:2px 9px;cursor:pointer}
.nqb.b-blue{border-color:#4f7fff}
.nqb.b-green{border-color:#37d27f}
.nqb.b-yellow{border-color:#e8b84a}
.nqb.b-red{border-color:#ef5d6c}
.nqb.b-clear{color:#7f8ea3;font-weight:700}
.ta-manual{font-size:10px;font-weight:800;background:#dbe7ff;color:#0e2138;border-radius:5px;padding:1px 7px;margin-left:6px}
.ta-recst{color:#7f8ea3;font-size:11px}
.ta-tog{margin-left:auto;font-size:14px;line-height:1;color:#8a99ad;cursor:pointer;user-select:none;padding:2px 5px}
.ta-tog:active{opacity:.55}
.ta-more{margin-top:5px}
.ta-go:active{opacity:.6}
.cmt-note{font-size:13.5px;font-weight:700;line-height:1.5;padding:9px 12px;border-radius:9px;margin-bottom:10px}
.cmt-pos{color:#9be8b8;background:#0c1f16;border:1px solid #1c4631}
.cmt-neg{color:#fecaca;background:#2a1416;border:1px solid #7f1d1d}
.secrs th.sortable{cursor:pointer}
.rottbl th.rsort{cursor:pointer;user-select:none}
.rottbl th.rsort:active{opacity:.55}
.rottbl th.rsort.act{color:#e6edf3;text-decoration:underline}
.rottbl{table-layout:fixed;width:100%}
.rottbl td:first-child,.rottbl th:first-child{width:31%;white-space:normal;word-break:keep-all;line-height:1.25}
.rottbl td:nth-child(2),.rottbl th:nth-child(2){width:13%}
.rottbl td:nth-child(3),.rottbl td:nth-child(4),.rottbl td:nth-child(5),.rottbl td:nth-child(6){width:11%;white-space:nowrap}
.rottbl th:nth-child(3),.rottbl th:nth-child(4),.rottbl th:nth-child(5),.rottbl th:nth-child(6){white-space:nowrap}
.rottbl td:last-child{width:auto}
.rottbl td:first-child b{font-size:12px}
.secrs th.sortable:active{opacity:.55}
.secrs th.sortable.act{color:#e6edf3;text-decoration:underline}
.secrs th .so{font-size:9px;color:#7f8da3}
.rc-h{font-size:12px;color:#aab6c6;margin-bottom:8px;font-weight:700}
.rc-sec{margin:8px 0}
.rc-l{font-size:11px;font-weight:700;margin-bottom:4px}
.rc-sl{color:#fca5a5}.rc-ad{color:#7ff0a8}
.rc-row{display:flex;justify-content:space-between;align-items:center;padding:6px 9px;border-radius:7px;background:#0b1220;border:1px solid #161e2b;margin-bottom:4px;font-size:13px}
.rc-row b{color:#e6edf3}
.rc-okall{font-size:12.5px;color:#7ff0a8;background:#0c1f16;border-radius:8px;padding:9px 11px}
.dov-meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 8px}
.dov-sec{font-size:12.5px;font-weight:700;color:#9ecbff}
.dov-cap{font-size:11px;font-weight:800;color:#cbd5e1;background:#1b2433;border:1px solid #2a3547;border-radius:6px;padding:1px 7px}
.dov-loc{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin:0 0 12px}
.dov-loc-l{font-size:10px;font-weight:800;color:#7d8da1;margin-right:2px}
.dov-loc-b{font-size:11px;font-weight:700;border-radius:6px;padding:2px 8px}
.loc-p{background:#0f3d1f;border:1px solid #1f9d4d;color:#86efac}
.loc-d{background:#10271f;border:1px solid #1f7a55;color:#7fe0c0}
.loc-k{background:#3a210f;border:1px solid #c2660b;color:#fdba74}
.loc-h{background:#0d2740;border:1px solid #2f81f7;color:#9ecbff}
.loc-w{background:#1b2433;border:1px solid #2a3547;color:#cbd5e1}
.dov-st{display:flex;align-items:center;gap:8px;flex-wrap:wrap;border-radius:10px;padding:9px 12px;border:1px solid #1c2533;background:#0b1220}
.dov-st.lead{border-left:4px solid #1f6feb}
.dov-st.nolead{border-left:4px solid #3a4452;opacity:.85}
.dov-st-pos{font-size:14px;font-weight:800;color:#e6edf3}
.dov-st-nu{font-size:11px;font-weight:800;border-radius:6px;padding:2px 8px;margin-left:auto}
.dov-st-nu.pos{background:#14331f;color:#86efac;border:1px solid #1d7840}
.dov-st-nu.neg{background:#3a1414;color:#fca5a5;border:1px solid #7f1d1d}
.dov-st-nu.mut{background:#0f1622;color:#9fb0c5;border:1px solid #1c2533}
.dov-st-note{font-size:11px;color:#9fb0c5;margin-top:6px;line-height:1.45}
.dov-st.st-③{border-left-color:#16a34a}.dov-st.st-②{border-left-color:#1f6feb}
.dov-st.st-①{border-left-color:#d97706}.dov-st.st-④{border-left-color:#ea580c}
.dov-st.st-⑤{border-left-color:#dc2626}
.dov-c{background:#0b1220;border:1px solid #1c2533;border-radius:9px;padding:8px 10px}
.dov-k{font-size:11px;color:#7d8da1}
.dov-v{font-size:16px;font-weight:800;margin-top:2px}
.dov-note{font-size:10px;color:#7d8da1;text-align:center;margin-top:12px}
/* 銘柄検索 */
.tksearch{width:100%;background:#0b1220;border:1px solid #243349;border-radius:9px;color:#e6edf3;font-size:15px;padding:10px 12px;margin-top:4px}
.tksearch:focus{outline:none;border-color:#2f81f7}
.tkresults{margin-top:8px;display:flex;flex-direction:column;gap:5px}
.tkr{display:flex;align-items:center;gap:8px;background:#0b1220;border:1px solid #1c2533;border-radius:8px;padding:8px 10px;cursor:pointer}
.tkr-s{font-size:14px;font-weight:800;color:#9ecbff;flex:0 0 62px}
.tkr-n{font-size:11px;color:#9fb0c5;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tkr-rs{font-size:11px;color:#7d8da1;flex:0 0 auto}
.tkno{color:#7d8da1;font-size:12px;padding:4px}
.secrow{cursor:pointer}
.secx{font-size:9px;color:#7d8da1}
.secsub{display:none}
.secsub.open{display:table-row}
.secchips{display:flex;flex-wrap:wrap;gap:5px;padding:8px 2px}
.rsb{margin-left:5px;opacity:.6;font-size:10px;font-weight:700}
.rowsec{font-size:9px;font-weight:400;color:#7d8da1;margin-top:1px;line-height:1.15}
.dov-since{font-size:11.5px;color:#9fb0c5;margin-top:5px}
.dov-since b{color:#e6edf3}
tr[data-tkone]{cursor:pointer}
tr[data-tkone]:active{background:#0f1a2c}
.bt:active,.buy:active,.tkr:active{background:#13233a}
.capb{font-size:9px;font-weight:800;border-radius:5px;padding:1px 4px;white-space:nowrap}
.cap-micro{background:#3a1414;color:#fca5a5;border:1px solid #7f1d1d}
.cap-small{background:#3a2a14;color:#fcd34d;border:1px solid #78531d}
.cap-mid{background:#14233a;color:#93c5fd;border:1px solid #1d4e78}
.cap-large{background:#14331f;color:#86efac;border:1px solid #1d7840}
.cap-mega{background:#0f2e2e;color:#5eead4;border:1px solid #156464}
.cap-none{background:#0f1622;color:#5b6b80;border:1px solid #1c2533}
.stb{font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;white-space:nowrap;border:1px solid #1c2533;background:#0b1220}
.stb b{font-weight:800}
.stb-③{color:#86efac;border-color:#1d7840}.stb-②{color:#93c5fd;border-color:#1d4e78}
.stb-①{color:#fcd34d;border-color:#78531d}.stb-④{color:#fdba74;border-color:#9a4a1d}
.stb-⑤{color:#fca5a5;border-color:#7f1d1d}.stb-none{color:#7d8da1}
.rowbadges{display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-top:2px}
.bt[data-tkone],.buy[data-tkone]{cursor:pointer}
.rk-note{background:#0b1626;border:1px solid #16324f;border-radius:9px;padding:8px 10px;color:#9fb0c5}
.capfil{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.liqstick{position:sticky;top:46px;z-index:8;padding:8px 12px;margin-bottom:10px;box-shadow:0 4px 12px rgba(0,0,0,.35)}
.liqrow{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.liqlab{font-size:11px;font-weight:800;color:#9fb0c5;display:flex;flex-direction:column;line-height:1.1;margin-right:3px}
.liqsub{font-size:8px;font-weight:600;color:#5b6b80}
.lqf-b{font-size:12px;font-weight:700;padding:6px 10px;border-radius:8px;background:#0f1622;color:#9fb0c5;border:1px solid #1c2533;cursor:pointer}
.lqf-b.active{background:#1d4ed8;color:#fff;border-color:#1d4ed8}
.lqf-rec{border-color:#1d7840}
.lqf-tag{font-size:8px;font-weight:800;margin-left:3px;color:#86efac;vertical-align:top}
.lqf-rec.active .lqf-tag{color:#bbf7d0}
.sectog{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:2px 0 8px}
.stg-g,.stg-t{font-size:12px;font-weight:700;padding:4px 10px;border-radius:7px;background:#0f1622;color:#9fb0c5;border:1px solid #1c2533;cursor:pointer}
.stg-g.active{background:#1d4ed8;color:#fff;border-color:#1d4ed8}
.stg-t.active{background:#334155;color:#fff;border-color:#475569}
.stg-sep{color:#3a4453;font-weight:400;margin:0 2px}
.secsub td{background:#0c1320;color:#8fa0b5;font-size:10px;font-weight:800;padding:3px 4px}
td.hl{background:rgba(56,80,140,.20);font-weight:800}
.subgrp{margin:6px 0 2px}
.subgrp-h{font-size:10px;font-weight:700;color:#8fa3bd;letter-spacing:.02em;margin:0 0 3px;display:flex;align-items:center;gap:5px}
.subgrp-n{font-size:9px;font-weight:700;color:#5b6b80;background:#0f1622;border:1px solid #1c2533;border-radius:4px;padding:0 4px}

/* ランク番号＋急落局面フラグ（配分calc） */
.rkb{display:inline-block;min-width:22px;text-align:center;font-size:10.5px;font-weight:800;color:#0b0f17;background:#93b7df;border-radius:5px;padding:1px 4px;margin-right:2px;font-variant-numeric:tabular-nums}
.kflag{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle}
.kf-half{background:rgba(234,179,8,.18);color:#eab308;border:1px solid rgba(234,179,8,.4)}
.kf-skip{background:rgba(239,68,68,.16);color:#f87171;border:1px solid rgba(239,68,68,.4)}
.kf-skiptxt{color:#f87171;font-weight:800;font-size:12px}
.kf-ok{background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.4)}
.kf-oktxt{color:#4ade80;font-weight:800;font-size:12px}
.hf{color:#eab308;font-weight:800;font-size:11px;margin-left:3px}
.row-skip{opacity:.72}
.th-w{white-space:nowrap;line-height:1.15}
.dax{display:flex;justify-content:space-between;font-size:9px;color:#5b6b82;padding:3px 3px 0;font-variant-numeric:tabular-nums}
.cap-c{justify-content:center}
/* 先導株の強さ温度計 */
.lt-hero{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:7px}
.lt-big{font-size:32px;font-weight:800;color:#f59e0b;font-variant-numeric:tabular-nums;line-height:1}
.lt-big span{font-size:13px;font-weight:700;color:#8494ab;margin-left:3px}
.lt-lv{font-size:13px;font-weight:700;color:#cfe0f5}
.lt-hist{display:flex;justify-content:space-between;gap:4px;margin-top:9px}
.lt-h{flex:1;text-align:center;background:#0b1220;border:1px solid #1c2533;border-radius:8px;padding:5px 2px}
.lt-hk{display:block;font-size:9.5px;color:#8494ab;margin-bottom:1px}
.lt-h b{font-size:15px;font-variant-numeric:tabular-nums}
.lt-hu{display:block;font-size:8.5px;color:#5b6b82}
/* マーケット感応度 β */
.beta-hero{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.beta-big{font-size:34px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums}
.beta-lb{font-size:11px;color:#8494ab;margin-top:2px}
.beta-read{font-size:13px;font-weight:700;color:#cfe0f5}
.beta-read .mut{font-weight:500;display:block;font-size:11px}
.beta-det{margin-top:9px}
.beta-det summary{font-size:12px;color:#93b7df;cursor:pointer;font-weight:700}
.bt-grid{margin-top:7px;display:flex;flex-direction:column;gap:5px}
.bt-row{display:flex;align-items:baseline;gap:8px;font-size:12.5px}
.bt-k{color:#8fa0b5;min-width:120px}
.bt-row b{font-size:15px;font-variant-numeric:tabular-nums}
.bt-s{color:#5b6b82;font-size:10.5px}

/* RS multi-timeframe comparison */

/* emergency brake */
.emergency{border-width:1px}.emergency.em-on{border-color:#7f1d1d;background:linear-gradient(135deg,#241014,#151018)}
.emergency.em-off{border-color:#21452d}.emergency.em-na{border-color:#374151}
.em-mult{font-size:12px;font-weight:900;border-radius:7px;padding:4px 8px;background:#111827;color:#e5e7eb}
.em-on .em-mult{background:#7f1d1d;color:#fecaca}.em-off .em-mult{background:#14532d;color:#bbf7d0}
.em-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.em-grid>div{background:#0b1220;border:1px solid #1c2533;border-radius:9px;padding:9px 10px}
.em-grid span{display:block;color:#8fa0b5;font-size:10.5px}.em-grid b{display:block;font-size:20px;margin:2px 0}.em-grid small{display:block;color:#66758a;font-size:9px;line-height:1.35}
.em-foot{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:8px;color:#8fa0b5;font-size:10px}.em-foot span:last-child{color:#65758a}
.em-note{margin-top:6px;padding:6px 8px;border-radius:7px;background:#241014;color:#fecaca;font-size:10.5px;font-weight:700}
/* RS persistence */
.rs-cont{margin-top:10px}.rsc-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:10px}
.rscg{background:#0b1220;border:1px solid #1c2533;border-radius:8px;padding:7px 8px;min-width:0}.rscg>b{font-size:11px}.rscg>span{margin-left:6px;font-weight:800;color:#9ecbff}.rscg .chips{margin-top:4px}.rscg .chip{font-size:9px;padding:1px 5px;margin:1px}
.rsc-list{margin-top:10px}.rsc-row{border-top:1px solid #182131;padding:8px 0}.rsc-row:first-child{border-top:0}
.rsc-head{display:flex;align-items:center;gap:6px;min-width:0}.rsc-rk{font-size:10px;color:#9ecbff;width:27px}.rsc-head>b{font-size:13px}.rsc-rs{margin-left:auto;font-size:10px;color:#9fb0c5}
.rsc-tag{font-size:8.5px;font-weight:800;border-radius:5px;padding:1px 5px}.rsc-tag.stable{background:#14351f;color:#86efac}.rsc-tag.surge{background:#102b42;color:#93c5fd}.rsc-tag.return{background:#2f2450;color:#c4b5fd}.rsc-tag.fade{background:#3a1717;color:#fca5a5}.rsc-tag.spike{background:#4c2b05;color:#fbbf24}.rsc-tag.hold{background:#1b2433;color:#9fb0c5}
.rsc-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 8px;padding-left:33px;margin-top:4px;font-size:9.5px;color:#7f8ea3}.rsc-metrics b{color:#cbd5e1}.rsc-slopes{padding-left:33px;margin-top:3px;font-size:9px;color:#65758a}.rsc-slopes b{color:#9fb0c5}
.rsx-overlap{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.rsx-stat{background:#0b1220;border:1px solid #1c2533;border-radius:9px;padding:8px 10px;min-width:0}
.rsx-stat-h{display:flex;align-items:center;gap:5px}
.rsx-stat-h>span{font-size:10.5px;color:#8fa0b5}.rsx-stat-h>b{font-size:19px}.rsx-stat-h .cp{margin-left:auto;flex:0 0 auto}
.rsx-stat .chips{margin-top:5px}.rsx-stat .chip{font-size:10px;padding:2px 6px;margin:1px}
.swdiv{height:1px;background:#1c2533;margin:14px 0 10px}
.swhold-h{font-size:13px;font-weight:800;color:#cfe0f5;margin-bottom:8px}.stratseg{display:inline-flex;border:1px solid #243349;border-radius:8px;overflow:hidden}.stratbtn{font-size:11px;font-weight:700;padding:4px 10px;background:#0f1622;color:#8b9bb0;border:none;cursor:pointer}.stratbtn.on{background:#12275e;color:#bfdbfe}.stratbadge{font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle;white-space:nowrap}.stratbadge.strat-core{background:#12275e;color:#bfdbfe;border:1px solid #2563eb}.stratbadge.strat-swing{background:#3d2a08;color:#fde68a;border:1px solid #ca8a04}.hld-exit{font-size:9.5px;margin-top:2px;line-height:1.4;opacity:.9}.hld-plan{font-size:9.5px;margin-top:3px;line-height:1.5}.hld-pt{margin-top:4px;font-size:10px;background:#14331f;color:#86efac;border:1px solid #1d7840}.hldsel{background:#0f1622;color:#cfe0f5;border:1px solid #243349;border-radius:7px;padding:5px 7px;font-size:12px}.hld-note{font-size:9.5px;margin-top:3px;line-height:1.5;display:flex;flex-wrap:wrap;gap:4px 6px}.hld-setup{font-weight:800;color:#a5b4fc;background:#1e2140;border:1px solid #3730a3;border-radius:4px;padding:0 5px}.hld-conv{font-weight:800;color:#fbbf24}.hld-memo{font-size:10px;margin-top:3px;line-height:1.5;color:#c7d2de;background:rgba(255,255,255,.04);border-left:2px solid #3b475a;padding:3px 7px;border-radius:0 5px 5px 0}.hld-noteb{margin-top:4px;font-size:10px;background:#161f2e;color:#9db1c9;border:1px solid #2b3a4f}.hld-btns{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}.hld-close{font-size:10px;background:#331416;color:#fca5a5;border:1px solid #7f1d1d}.hld-leg{font-size:9.5px;margin-top:3px;line-height:1.4}.hld-legb{margin-top:4px;font-size:10px;background:#2a2408;color:#fde68a;border:1px solid #a16207}.warnc{color:#fbbf24}.stratbadge.sp-entry{background:#14331f;color:#86efac;border:1px solid #1d7840}.stratbadge.sp-hl{background:#3d2a08;color:#fde68a;border:1px solid #ca8a04}.stratbadge.sp-confirm{background:#12275e;color:#bfdbfe;border:1px solid #2563eb}.stratbadge.sp-retest{background:#2a1e3d;color:#d0bcf0;border:1px solid #7c5bbf}.sp-impr{font-size:9px;font-weight:800;color:#5aa469;margin-left:3px}.sp-vdry{font-size:9px;font-weight:800;color:#5ea0a8;background:#0e2a2e;border:1px solid #2a5b60;border-radius:4px;padding:0 4px;margin-left:3px}.sp-row{flex-direction:column;align-items:stretch}.sp-top{display:flex;align-items:center;gap:6px;width:100%;min-width:0}.sp-lvls{font-size:9.5px;color:#8b9bb0;margin-top:2px;line-height:1.4}
.rsx-signals{display:grid;grid-template-columns:1fr;gap:7px;margin-top:9px}
.rsx-sig{background:#101824;border:1px solid #243044;border-radius:9px;padding:8px 10px}
.rsx-sig>b{font-size:12px;color:#cfe0f5;margin-right:7px}.rsx-sig>span{font-size:10.5px;color:#7f8ea3}
.rsx-sig .chips{margin-top:5px}.rsx-sig .chip{font-size:10px;padding:2px 6px;margin:1px}
.rsx-grid{display:grid;grid-template-columns:1fr;gap:10px}
.rsx-card{margin-bottom:0}.rsx-item{border-top:1px solid #182131;padding:7px 0}
.rsx-item:first-of-type{border-top:0}.rsx-row{display:flex;align-items:center;gap:7px}
.rsx-rk{width:22px;height:22px;border-radius:6px;background:#172033;color:#9ecbff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;flex:0 0 auto}
.rsx-name{min-width:0;flex:1}.rsx-name b{font-size:13px}.rsx-name small{display:block;color:#718197;font-size:9.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.rsx-score{text-align:right;min-width:44px}.rsx-score>b{display:block;font-size:15px}.rsx-score small{font-size:10px}
.rsx-badge{font-size:8.5px;font-weight:800;border-radius:5px;padding:1px 4px;margin-left:5px;vertical-align:1px}
.rsx-badge.sel{background:#173a24;color:#86efac;border:1px solid #287a45}.rsx-badge.ok{background:#102b42;color:#93c5fd;border:1px solid #245b85}
.rsx-badge.ex{background:#3a1717;color:#fca5a5;border:1px solid #7f1d1d}.rsx-badge.watch{background:#1b2433;color:#9fb0c5;border:1px solid #2a3547}
.rsx-new{background:#4c2b05;color:#fbbf24;border:1px solid #8a520d;border-radius:4px;padding:1px 4px;font-size:8.5px;font-weight:800}
.rsx-sub{font-size:9.5px;color:#8392a7;padding-left:24px;margin-top:3px;display:flex;justify-content:flex-start;align-items:baseline;gap:4px 8px;flex-wrap:wrap}
.rsx-sub .rsx-ret{color:#66758a;white-space:nowrap}
.rsx-sub .rsx-nums{white-space:nowrap}
.rsx-sub b{color:#cbd5e1}.rsx-sub span{color:#66758a}
.rsx-history .sub b{color:#e6edf3}.rsx-hgrid{display:grid;grid-template-columns:1fr;gap:9px;margin-top:10px}
.rsx-hblock{background:#0b1220;border:1px solid #1c2533;border-radius:10px;overflow:hidden}
.rsx-hhead{display:flex;align-items:center;gap:7px;padding:8px 10px;background:#101824;border-bottom:1px solid #1c2533}
.rsx-hhead>b{font-size:13px;color:#cfe0f5}.rsx-hhead>span{font-size:9.5px;color:#718197;flex:1}.rsx-hhead .cp{margin-left:auto}
.rsx-hrow{display:grid;grid-template-columns:74px minmax(0,1fr);gap:8px;padding:8px 10px;border-top:1px solid #182131}
.rsx-hrow:first-of-type{border-top:0}.rsx-hwhen b{display:block;font-size:12px}.rsx-hwhen small{display:block;font-size:8.5px;color:#718197;margin-top:1px}
.rsx-hwhen em{display:block;font-size:8.5px;color:#9fb0c5;font-style:normal;margin-top:4px}.rsx-hflow{min-width:0;display:grid;gap:5px}
.rsx-hflow>div{display:grid;grid-template-columns:48px minmax(0,1fr);gap:5px;align-items:start}.rsx-hflow strong{font-size:9px;border-radius:5px;padding:2px 4px;text-align:center}
.rsx-hflow .hin{background:#14351f;color:#86efac;border:1px solid #287a45}.rsx-hflow .hout{background:#3a1717;color:#fca5a5;border:1px solid #7f1d1d}
.rsx-hflow .chips{margin:0;line-height:1.3}.rsx-hflow .chip{font-size:9px;padding:1px 5px;margin:0 2px 2px 0}
.rsx-hflow .chip.in{border-color:#287a45;color:#86efac;background:#102b19}.rsx-hflow .chip.out{border-color:#7f1d1d;color:#fca5a5;background:#2b1212}
.rsx-hna{font-size:10px;color:#718197;display:flex;align-items:center}

/* ===== レスポンシブ: タブレット/デスクトップ（末尾＝最優先） ===== */
@media (min-width:760px){
  .wrap{max-width:920px;padding-left:20px;padding-right:20px}
  body{font-size:15px}
  h1{font-size:21px}
  .card{padding:14px 18px;border-radius:15px;margin-bottom:14px}
  .card h2{font-size:16px}
  .card .sub{font-size:12px}
  nav{padding:11px 0}
  nav button,nav a.tabx{font-size:14px;padding:9px 18px}
  .banner{padding:16px 20px}
  .banner .val{font-size:36px}
  .perf{grid-template-columns:repeat(6,1fr)}
  .hmgrid{grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:8px}
  .dov-grid{grid-template-columns:repeat(4,1fr)}
  .buy-g,.bt-g{grid-template-columns:repeat(4,1fr)}
  .rsc-groups{grid-template-columns:repeat(3,minmax(0,1fr))}
  .rsc-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}
  .rsx-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
  .rsx-overlap{grid-template-columns:repeat(4,minmax(0,1fr))}
  .rsx-signals{grid-template-columns:repeat(2,minmax(0,1fr))}
  .rsx-hgrid{grid-template-columns:repeat(3,minmax(0,1fr))}
  .rsx-hrow{grid-template-columns:68px minmax(0,1fr);padding:8px}
  table{font-size:13.5px}
  th,td{padding:6px 8px}
}
@media (min-width:1080px){
  .wrap{max-width:1060px}
  .buy-g,.bt-g{grid-template-columns:repeat(5,1fr)}
}
"""

JS = r"""
function escHtml(v){
  /* #1 innerHTMLへ外部由来文字列(テーマ/サブテーマ/社名/note等)を入れる際のエスケープ。
     DET(window.DET)のsec/sth/flags等はPython側で既にエスケープ済みなので二重には通さない。 */
  return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function _copyText(text, onOk){
  /* #24 Clipboard APIが使えない環境(file://・一部Safari・プレビュー)ではpromptにfallback。無反応にしない。 */
  try{
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){ if(onOk)onOk(); },
        function(){ window.prompt('コピーしてください', text); });
      return;
    }
  }catch(e){}
  try{ var ta=document.createElement('textarea'); ta.value=text; ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta); ta.select(); var ok=false; try{ok=document.execCommand('copy');}catch(e2){} document.body.removeChild(ta); if(ok){ if(onOk)onOk(); return; } }catch(e3){}
  window.prompt('コピーしてください', text);
}
function tab(id,btn){
  document.querySelectorAll('section').forEach(s=>s.classList.remove('on'));
  document.querySelectorAll('nav a.tabx').forEach(b=>b.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  btn.classList.add('on');
  window.scrollTo(0,0);
  if(id==='t-alloc'){ try{eqInit();}catch(e){} try{swInit();}catch(e){} try{hldRender();}catch(e){} }
  if(id==='t-today'){ try{swInit();}catch(e){} }
}
function goTab(id){
  var t=null;
  document.querySelectorAll('nav a.tabx').forEach(function(b){
    var oc=b.getAttribute('onclick')||''; if(oc.indexOf("'"+id+"'")>-1) t=b;
  });
  if(t) tab(id,t);
}
// JS有効時: URLハッシュ(#t-xxx)がある場合は初期ロード/back-forwardで表示とタブ選択色を同期
function _syncTabFromHash(){
  try{
    var h=((window.location&&window.location.hash)||'').replace('#','');
    if(!h) return;
    var a=document.querySelector('nav a.tabx[href="#'+h+'"]');
    if(a){ tab(h,a); }
  }catch(e){}
}
try{
  window.addEventListener('hashchange',_syncTabFromHash);
  if(window.location&&window.location.hash){ if(document.readyState!=='loading'){_syncTabFromHash();} else {document.addEventListener('DOMContentLoaded',_syncTabFromHash);} }
}catch(e){}
function rrgGran(mode,btn){
  var a=document.getElementById('rrg-16'), z=document.getElementById('rrg-all');
  if(!a||!z) return;
  if(mode===16){ a.style.display=''; z.style.display='none'; }
  else { a.style.display='none'; z.style.display=''; }
  var b16=document.getElementById('rtg-16'), ball=document.getElementById('rtg-all');
  if(b16&&ball){ b16.classList.toggle('on',mode===16); ball.classList.toggle('on',mode!==16); }
}
function showThemeHier(ev,el){
  if(ev){ev.stopPropagation();}
  var k=el.getAttribute('data-hkey'); var subs=(window.HIER||{})[k];
  if(!subs){ return; }
  var d={theme:k, subs:subs};
  var QC={'主導':'#4ade80','改善':'#60a5fa','弱化':'#fbbf24','停滞':'#f87171'};
  var disp=d.theme.indexOf('. ')>=0? d.theme.split('. ').slice(1).join('. '):d.theme;
  var ix=0;
  function rowHtml(su){
    var qc=QC[su.q]||'#8b949e';
    var mem=(su.members||[]).map(function(mm){
      return '<span class="hmem" data-tkone="'+mm.t+'" onclick="hierPick(event,this)">'+mm.t+
        (mm.rs!=null?'<span class="rsb">'+mm.rs+'</span>':'')+'</span>';
    }).join('');
    var arrow=su.drs>0?'▲':su.drs<0?'▼':'＝';
    var h='<div class="hsub-row"><div class="hsub-hd" onclick="hierSub('+ix+')">'+
      '<div class="hsub-name">'+escHtml(su.sub)+'<span class="hsub-q" style="background:'+qc+'22;color:'+qc+'">'+escHtml(su.q)+'</span></div>'+
      '<div class="hsub-meta">RS '+su.rs+' ・ '+arrow+Math.abs(su.drs)+' ・ '+su.n+'銘柄</div></div>'+
      '<div class="hsub-mem" id="hsub'+ix+'">'+mem+'</div></div>';
    ix++; return h;
  }
  var groups=[['主導',[]],['改善',[]],['弱化',[]],['停滞',[]]];
  var byq={};
  groups.forEach(function(g){ byq[g[0]]=g[1]; });
  (d.subs||[]).forEach(function(su){ if(byq[su.q]) byq[su.q].push(su); });
  var html='';
  groups.forEach(function(g){
    var q=g[0], list=g[1];
    if(!list.length) return;
    var qc=QC[q];
    var strong=(q==='主導'||q==='改善');
    var body=list.map(rowHtml).join('');
    if(strong){
      html+='<div class="hgrp"><div class="hgrp-h" style="color:'+qc+'">'+q+
            '<span class="hgrp-n">'+list.length+'</span></div>'+body+'</div>';
    }else{
      html+='<div class="hgrp hgrp-fold"><div class="hgrp-h hgrp-tap" style="color:'+qc+
            '" onclick="this.parentNode.classList.toggle(\'on\')">'+q+
            '<span class="hgrp-n">'+list.length+'</span><span class="hgrp-arr">▸</span></div>'+
            '<div class="hgrp-body">'+body+'</div></div>';
    }
  });
  if(!html) html='<div class="empty">該当なし</div>';
  var m=document.getElementById('hierModal');
  m.querySelector('.hier-box').innerHTML='<h3>'+escHtml(disp)+'</h3>'+
    '<div class="hb-sub">このETFの大分類に属する詳細セクター。主導・改善を既定表示、弱化・停滞はタップで展開。行タップで構成銘柄、銘柄タップで詳細。</div>'+html;
  m.classList.add('on');
}
function hierSub(ix){ var e=document.getElementById('hsub'+ix); if(e) e.classList.toggle('on'); }
function hierPick(ev,el){
  if(ev){ev.stopPropagation();}
  var tk=el.getAttribute('data-tkone');
  document.getElementById('hierModal').classList.remove('on');
  if(tk && typeof showDet==='function'){ showDet(tk); }
}
function copyTk(ev,b){
  if(ev){ev.stopPropagation();}
  var t=b.getAttribute('data-tk')||'';
  _copyText(t, function(){
    var o=b.textContent; b.textContent='✓ コピー済'; b.classList.add('done');
    setTimeout(function(){b.textContent=o; b.classList.remove('done');},1200);
  });
}
function copyList(ev,b){
  if(ev){ev.stopPropagation();}
  var t=b.getAttribute('data-list')||'';
  _copyText(t, function(){
    var o=b.textContent; b.textContent='✓ コピー済'; b.classList.add('done');
    setTimeout(function(){b.textContent=o; b.classList.remove('done');},1200);
  });
}
function copyBlock(ev,id){
  try{if(ev)ev.stopPropagation();}catch(e){}
  var el=document.getElementById(id); if(!el)return;
  var txt=(el.innerText||el.textContent||'').trim();
  var b=(ev&&ev.currentTarget)?ev.currentTarget:null;
  function done(){if(!b)return;var o=b.textContent;b.textContent='✓ コピー済';b.classList.add('done');setTimeout(function(){b.textContent=o;b.classList.remove('done');},1400);}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(done,function(){window.prompt('コピーしてください',txt);});}
  else{var ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);done();}
}
function eqInit(){
  try{
    var el=document.getElementById('eqIn'); if(!el) return;
    var jp=document.getElementById('jpyIn'); var jv=jp?parseFloat(jp.value):NaN;
    if(jv&&jv>0){ el.value=Math.round(jv); }
    else { var last=null; try{last=localStorage.getItem('eqLast');}catch(e){} if(last&&!el.value){ el.value=last; } }
    var ds=document.getElementById('eqDate');
    if(ds){ ds.textContent=sessionDate(); }   /* #9 USセッション日(=CALC.asof)。JST端末日だと米国月曜取引を火曜日付で記録してしまう */
  }catch(e){}
}
function copyEquityRow(){
  var el=document.getElementById('eqIn');
  var v=el?parseFloat(el.value):NaN;
  var btn=document.getElementById('eqCopyBtn');
  if(!v || v<=0){
    if(btn){var o=btn.textContent; btn.textContent='⚠ 金額を入力してから'; setTimeout(function(){btn.textContent=o;},1500);}
    return;
  }
  try{ localStorage.setItem('eqLast', String(Math.round(v))); }catch(e){}
  var ds=sessionDate();   /* #9 USセッション日基準。equity.csvにJST端末日を書かない */
  var ue=document.getElementById('eqUsIn');
  var uv=ue?parseFloat(ue.value):NaN;
  var dl=((window.CALC&&window.CALC.eq_delim)||',');   // 既存ファイルの区切りに合わせる（写真の体裁ズレ対策）
  var row=ds+dl+Math.round(v)+((uv||uv===0)&&uv>=0&&uv<=100?dl+uv:'');
  _copyText(row, function(){
    if(btn){var o=btn.textContent; btn.textContent='✓ コピー済（'+(dl===','?'カンマ':'スペース')+'区切り）→ equity.csvに貼り付け'; btn.classList.add('done');
      setTimeout(function(){btn.textContent=o; btn.classList.remove('done');},2200);}
  });
}
function toggleMri(){
  var p=document.getElementById('mri-bd');
  if(p){p.classList.toggle('open');}
}
function _f(v,s){ return (v===null||v===undefined)?'—':(v+(s||'')); }
function _sg(v){ if(v===null||v===undefined) return 'mut'; return v>=0?'pos':(v<0?'neg':'mut'); }
function thStk(el){ var t=el.getAttribute('data-tk'); if(t) showDet(t); }
function thDrill(i){
  var pan=document.getElementById('thp-'+i), til=document.getElementById('tht-'+i);
  if(!pan) return;
  var open = pan.style.display!=='none';
  // 全パネル閉じ＆全タイル非アクティブ
  document.querySelectorAll('.thpanel').forEach(function(x){x.style.display='none';});
  document.querySelectorAll('.thtile').forEach(function(x){x.classList.remove('on');});
  if(!open){ pan.style.display='block'; if(til) til.classList.add('on'); pan.scrollIntoView({block:'nearest',behavior:'smooth'}); }
}
function showDet(tk){
  var d=(window.DET||{})[tk]; if(!d) return;
  document.getElementById('dov-tk').textContent=tk;
  var _tv=document.getElementById('dov-tv'); if(_tv){ _tv.href='https://jp.tradingview.com/chart/?symbol='+encodeURIComponent(tk); }
  var _sp=document.getElementById('dov-spark');
  if(_sp){ var _svg=(window.SPARK||{})[tk];
    if(_svg){ _sp.innerHTML='<span class="lbl">6ヶ月</span>'+_svg; _sp.classList.remove('empty'); }
    else{ _sp.innerHTML=''; _sp.classList.add('empty'); } }
  var fb='';
  var fls=d.flags||(d.flag?[d.flag]:[]);
  if(fls.length){ fb=fls.map(function(f){
    var fc=(f.sev==='crit')?'dov-flag-crit':(f.sev==='high')?'dov-flag-hi':'dov-flag-md';
    return '<div class="dov-flag '+fc+'">'
      +'⚠ '+(f.type||'赤旗')+'アラート'
      +'<div class="dov-flag-n">'+(f.note||'')+'</div></div>'; }).join('')
    +'<div class="dov-flag-s">※キュレーション/自動判定（履歴含む・網羅でない）。売買判断は自身で確認を。</div>'; }
  var NUNOTE={'急落中':'下げが速い（急落局面）。急落注意・投げ（セリングクライマックス）の有無を確認。急落注意・投げの有無を確認',
              '反発中':'下げ止まって切り返し。押し目なら入りやすい局面',
              '堅調':'値持ちが良く落ち着いた値動き・押しが浅い',
              '軟調':'じり安で方向感に乏しい・様子見'};
  var nunote=NUNOTE[d.nut]||'';
  var sb='';
  if(d.ld){
    sb='<div class="dov-st lead st-'+d.stc+'"><span class="dov-st-pos">RSリーダー '+d.stc+d.stl+'</span>'
      +(d.nut?'<span class="dov-st-nu '+d.nucls+'">'+d.nut+'</span>':'')+'</div>'
      +(nunote?'<div class="dov-st-note">'+nunote+'</div>':'');
  } else {
    sb='<div class="dov-st nolead"><span class="dov-st-pos">'+(d.rsn||'リーダー対象外')+'</span>'
      +(d.nut?'<span class="dov-st-nu '+d.nucls+'">'+d.nut+'</span>':'')+'</div>'
      +(nunote?'<div class="dov-st-note">'+nunote+'</div>':'');
  }
  var STG={1:['ステージ1','stg1','底固め・移行期（30週線の上に出たが線はまだ下向き）。ステージ2入り＝線が上向くのを確認してから'],
           2:['ステージ2','stg2','上昇トレンド（30週線の上×線が上向き）。押し目・ブレイクの対象'],
           3:['ステージ3','stg3','天井圏の兆候（30週線割れ・線はまだ上向き）。新規は避け、利確・トレール管理を優先'],
           4:['ステージ4','stg4','下降トレンド（30週線の下×線が下向き）。買い禁止・戻りは売り場']};
  if(d.wst&&STG[d.wst]){
    var sg=STG[d.wst],ex='';
    if(d.wst==2){
      var done=d.wsb||0, late=done+(d.wsbf?1:0);
      if(d.wsbf){ex=' ・ 第'+(done+1)+'ベース形成中';}
      else if(done>0){ex=' ・ ベース'+done+'本消化';}
      if(late>=3){ex+='（後期・失敗率上昇）';}
    }
    sb='<div class="dov-stage stg'+d.wst+'"><b>'+sg[0]+'</b><span class="dov-stg-w">'
       +(d.wstw?d.wstw+'週目':'')+ex+'</span></div>'
       +'<div class="dov-st-note">'+sg[2]+'</div>'+sb;
  }
  document.getElementById('dov-status').innerHTML=fb+sb;
  // セクター/サブテーマ/時価総額
  var meta='';
  if(d.sec||d.sth){
    meta='<span class="dov-sec">'+(d.sec||'')+(d.sth&&d.sth!==d.sec?' ・ '+d.sth:'')+'</span>';
  }
  if(d.cap){ meta+='<span class="dov-cap">'+d.cap+'</span>'; }
  var sr=(window.SECROT||{})[d.sth];
  if(sr){ meta+='<span class="dov-rot" style="border-color:'+(sr.c||'#9fb0c5')+';color:'+(sr.c||'#9fb0c5')+'">ローテ: '+sr.rot+'（#'+sr.rk+'/'+sr.n+'・RS'+Math.round(sr.med)+'・週'+((sr.d1w>=0?'+':'')+sr.d1w.toFixed(1))+'）</span>'; }
  document.getElementById('dov-meta').innerHTML=meta;
  // 登場箇所（保有/控え/ピックアップ/新高値/ウォッチ）
  var lc=d.loc||[];
  var isHold=lc.some(function(x){return x.indexOf('保有')===0;});
  var sinceHtml='';
  if(isHold && d.since && d.since.d){
    var nn=(d.since.n!==null&&d.since.n!==undefined)?('（'+d.since.n+'営業日）'):'';
    sinceHtml='<div class="dov-since">ランキング入り <b>'+d.since.d+'</b>'+nn+'</div>';
  }
  document.getElementById('dov-loc').innerHTML = (lc.length
    ? '<span class="dov-loc-l">登場</span>'+lc.map(function(x){
        var c='loc-w'; if(x.indexOf('保有')===0)c='loc-p'; else if(x.indexOf('控え')===0)c='loc-d';
        else if(x.indexOf('ピックアップ')===0)c='loc-k'; else if(x.indexOf('新高値')===0)c='loc-h';
        return '<span class="dov-loc-b '+c+'">'+x+'</span>'; }).join('')
    : '') + sinceHtml;
  var rows=[['RS(63日)',_f(d.rs),'mut'],
            ['RS(189日・選定)',_f(d.rs189),'mut'],
            ['RS(21日・短期)',_f(d.rs21),'mut'],
            ['価格',(d.px===null||d.px===undefined)?'—':('$'+d.px),'mut'],
            ['前日比',_f(d.ch,'%'),_sg(d.ch)],
            ['vs50MA',_f(d.v50,'%'),_sg(d.v50)],
            ['vs200MA',_f(d.v200,'%'),_sg(d.v200)],
            ['21EMA乖離',_f(d.d21,'%'),'mut'],
            ['押し目',_f(d.pb,'%'),_sg(d.pb)],
            ['ADR',_f(d.adr,'%'),'mut'],
            ['RVOL',_f(d.rv),'mut'],
            ['ピボット差',_f(d.pdist,'%'),_sg(d.pdist===null?null:-d.pdist)],
            ['VCP形状',_f(d.vcpq),'mut'],
            ['収縮 / HL',_f(d.contract)+' / '+(d.hl?'○':'—'),'mut'],
            ['出来高枯れ',_f(d.vdry,'×'),'mut'],
            ['RS線高値',d.rsline?'○':'—',d.rsline?'pos':'mut'],
            ['構造',[(d.truebr?'真ブレイク':''),(d.cup?'カップ':''),(d.turn?'転換':''),(d.p204?'20/4':'')].filter(Boolean).join('・')||'—','mut'],
            ['β(市場感応度)',(d.beta===null||d.beta===undefined)?'—':_f(d.beta),(d.beta>=1.3?'neg':d.beta<=0.9?'pos':'mut')],
            ['出来高$',(d.dvol===null||d.dvol===undefined)?'—':(d.dvol+'M'),'mut']];
  document.getElementById('dov-body').innerHTML=rows.map(function(r){
    return '<div class="dov-c"><div class="dov-k">'+r[0]+'</div><div class="dov-v '+r[2]+'">'+r[1]+'</div></div>';
  }).join('');
  document.getElementById('dov-bg').classList.add('open');
}
function hideDet(){ var b=document.getElementById('dov-bg'); if(b){b.classList.remove('open');} }
function secToggle(id){ var r=document.getElementById(id); if(r){ r.classList.toggle('open'); } }
function rowSort(key, th){
  var tbl=th.closest('table'); if(!tbl) return;
  var tb=tbl.querySelector('tbody'); if(!tb) return;
  var rows=Array.prototype.slice.call(tb.querySelectorAll('tr'));
  var asc=th.getAttribute('data-asc')==='1';
  var val=function(r){var v=parseFloat(r.getAttribute('data-'+key));return isNaN(v)?-Infinity:v;};
  rows.sort(function(a,b){return asc? val(a)-val(b) : val(b)-val(a);});
  rows.forEach(function(r){tb.appendChild(r);});
  tbl.querySelectorAll('th.sortable').forEach(function(h){h.classList.remove('act');h.removeAttribute('data-asc');});
  th.classList.add('act'); th.setAttribute('data-asc', asc?'0':'1');
}
function secSort(key, th){
  var tbl=th.closest('table'); if(!tbl) return;
  var gs=Array.prototype.slice.call(tbl.querySelectorAll('tbody.secgrp'));
  var val=function(g){var v=parseFloat(g.getAttribute('data-'+key));return isNaN(v)?-Infinity:v;};
  gs.sort(function(a,b){return val(b)-val(a);});
  gs.forEach(function(g,i){tbl.appendChild(g);var n=g.querySelector('.secnum');if(n)n.textContent=(i+1);});
  tbl.querySelectorAll('th.sortable').forEach(function(h){h.classList.remove('act');});
  th.classList.add('act');
}
function liqFilter(min, btn){
  var sec=btn.closest('section'); if(!sec) return;
  sec.querySelectorAll('.lqf-b').forEach(function(b){ b.classList.remove('active'); });
  btn.classList.add('active');
  sec.querySelectorAll('[data-liq]').forEach(function(el){
    el.style.display=(parseFloat(el.getAttribute('data-liq'))>=min)?'':'none';
  });
}
document.addEventListener('click',function(e){
  var el=e.target.closest?e.target.closest('[data-tkone]'):null;
  if(el){ showDet(el.getAttribute('data-tkone')); return; }
  if(e.target.id==='dov-bg'){ hideDet(); }
});
function _liqDefault(){
  try{ document.querySelectorAll('section .lqf-rec').forEach(function(b){ liqFilter(10, b); }); }catch(e){}
}
if(document.readyState!=='loading'){ _liqDefault(); }
else { document.addEventListener('DOMContentLoaded', _liqDefault); }
/* --- NQ手動記録（localStorage上書き：推定より優先・端末ローカル） --- */
var NQG={Blue:[1,1],Green:[1,0.5],Yellow:[1,0],Red:[0,0]};
var NQL={Blue:'青',Green:'緑',Yellow:'黄',Red:'赤'};
var NQR={Red:0,Yellow:1,Green:2,Blue:3};
var NQJUD={Blue:['Blue','強い上昇','継続'],Green:['Green','上昇(中位)','中立'],Yellow:['Yellow','弱含み','警戒'],Red:['Red','下落','回避']};
function _nqPct(x){return Math.round(x*100);}
function _emMult(){var C=window.CALC||{}; return (C.emergency_mult!=null)?Number(C.emergency_mult):1;}
function _nqLev(c){return (NQG[c]?NQG[c][1]:0)*_emMult();}
function _nqExpo(c){
  if(c==='Red') return '個別 0% ／ レバ 0% ・ 全現金';
  var g=NQG[c], lev=_nqLev(c), em=_emMult();
  var cash=(g[0]<1||lev<1)?'残りは現金（ゲート/非常口由来）':'フル投資';
  return '個別 '+_nqPct(g[0])+'% ／ レバ '+_nqPct(lev)+'%'+(em<1?'（非常口で半減）':'')+' ・ '+cash;
}
function _nqMult(p,n){
  if(n<=0) return p<=0?'なし':'全部売り';
  if(p<=0) return 'Positionsの株数で新規';
  var r=n/p;
  if(Math.abs(r-1)<1e-9) return '変更なし';
  if(Math.abs(r-0.5)<1e-9) return '半分売り（×0.5）';
  if(Math.abs(r-2)<1e-9) return '倍に買い増し（×2）';
  return '×'+(Math.round(r*100)/100);
}
function _nqAct(prev,c){
  if(prev && prev!==c && NQG[prev]){
    var up=NQR[c]>NQR[prev]; var gp=NQG[prev], gn=NQG[c];
    return ''+NQL[prev]+'→'+NQL[c]+'（'+(up?'攻め強化':'守りへ')+'）→ 翌寄りで 個別：'+_nqMult(gp[0],gn[0])+'／レバ：'+_nqMult(gp[1],gn[1]);
  }
  if(c==='Red') return '退避：個別0%・レバ0%・全現金。保有は寄りで手仕舞い';
  if(c==='Blue') return 'フル投資：個別100%・レバ100%。保有維持・トレール対応';
  return NQL[c]+'：個別'+_nqPct(NQG[c][0])+'%／レバ'+_nqPct(_nqLev(c))+'%'+(_emMult()<1?'（非常口）':'')+'。色が変わったらPositionsで株数調整';
}
function _nqApply(c,prev,ts){
  var card=document.getElementById('taCard'); if(!card||!NQG[c]) return;
  card.className=card.className.replace(/ta-(blue|green|yellow|red|gray)/g,'ta-'+c.toLowerCase());
  var col=document.getElementById('taCol'); if(col) col.textContent=NQL[c];
  var ex=document.getElementById('taExpo'); if(ex) ex.textContent=_nqExpo(c);
  var k=(prev&&prev!==c&&NQG[prev])?(NQR[c]>NQR[prev]?'change-up':'change-dn'):(c==='Red'?'alert':'normal');
  var ac=document.getElementById('taAct'); if(ac){ ac.textContent=_nqAct(prev,c); ac.className='ta-act ta-'+k; }
  var es=document.getElementById('taEst'); if(es) es.style.display='none';
  var mb=document.getElementById('taManual'); if(mb) mb.innerHTML='<span class="ta-manual">手動確定 '+NQL[c]+(ts?'（記録 '+ts+'）':'')+'</span>';
  if(k!=='normal'){ var mm=document.getElementById('taMore'),tt=document.getElementById('taTog'); if(mm) mm.style.display=''; if(tt) tt.textContent='▴'; }
  var pill=document.getElementById('sarPill');
  if(pill){
    pill.className=pill.className.replace(/sar-(blue|green|yellow|red|gray)/g,'sar-'+c.toLowerCase());
    var J=NQJUD[c]||['','',''];
    var sc=document.getElementById('sarCol'); if(sc) sc.textContent=J[0];
    var sj=document.getElementById('sarJud'); if(sj) sj.textContent=J[1];
    var sl=document.getElementById('sarLot'); if(sl) sl.textContent=J[2];
    var sb=document.getElementById('sarBadge'); if(sb) sb.innerHTML='<span class="sar-badge ok">手動</span>';
  }
  var gc=document.getElementById('calcGateC');
  if(gc){ gc.className=gc.className.replace(/sar-(blue|green|yellow|red|gray)/g,'sar-'+c.toLowerCase()); gc.textContent='NQ '+NQL[c]; }
  var ce=document.getElementById('calcExpo');
  if(ce){ var g2=NQG[c], l2=_nqLev(c); ce.innerHTML='個別 露出 <b>'+_nqPct(g2[0])+'%</b> ／ レバ 露出 <b>'+_nqPct(l2)+'%</b>'+( _emMult()<1?' <span class="neg">非常口×0.5</span>':''); }
  if(window.CALC){ window.CALC.e_ind=NQG[c][0]; window.CALC.e_lev_base=NQG[c][1]; window.CALC.e_lev=NQG[c][1]*_emMult(); window.CALC.color=c; }
  if(typeof calcRun==='function'){ try{calcRun();}catch(e){} }
}
function taToggle(){
  var m=document.getElementById('taMore'), t=document.getElementById('taTog'); if(!m) return;
  var open=m.style.display!=='none';
  m.style.display=open?'none':''; if(t) t.textContent=open?'▾':'▴';
}
function _nqNow(){var d=new Date();function z(x){return(x<10?'0':'')+x;}return z(d.getMonth()+1)+'/'+z(d.getDate())+' '+z(d.getHours())+':'+z(d.getMinutes());}
function setNQ(c){
  var cur=null; try{cur=JSON.parse(localStorage.getItem('nqManual'));}catch(e){}
  try{ if(cur&&cur.d!==sessionDate()){ cur=null; localStorage.removeItem('nqManual'); } }catch(e){}  /* セッション日が変わったら手動色は失効(#9: JST端末日でなくUSセッション日) */
  var card=document.getElementById('taCard');
  var prev=(cur&&cur.color)||(card?card.getAttribute('data-srv'):'')||'';
  var rec={color:c,prev:prev,ts:_nqNow()};
  try{ rec.d=sessionDate(); localStorage.setItem('nqManual',JSON.stringify(rec)); }catch(e){}
  _nqApply(c,prev,rec.ts);
}
function clearNQ(){ try{localStorage.removeItem('nqManual');}catch(e){} location.reload(); }
(function(){ try{
  var s=JSON.parse(localStorage.getItem('nqManual'));
  var today=sessionDate();            /* USセッション日(=CALC.asof)基準。JST端末日だと再読込で正当な手動色が消える(#2/#9) */
  if(!s || s.d!==today){ localStorage.removeItem('nqManual'); return; }  /* セッション日が違えば失効 */
  if(s.color&&NQG[s.color]) _nqApply(s.color,'',s.ts||'');
}catch(e){} })();
/* ---- 隔週リバランス判定（Pythonと同じ基準日） ---- */
function _rebalCheck2(){
  var el=document.getElementById('taRebal'); if(!el) return;
  var due=(window.CALC&&window.CALC.next_rebal)||'', today=sessionDate(), done='';
  try{done=localStorage.getItem('rebalDoneDate')||'';}catch(e){}
  if(due===today&&done!==today){
    el.style.display=''; var _bn=Number(window.CALC&&window.CALC.n), n=(_bn>0?_bn:null), c=(window.CALC&&window.CALC.color)||'';
    el.innerHTML='📅 隔週リバランス日 → '+((c==='Yellow'||c==='Red')?'継続条件を外れた保有を売るのみ':('最新トップ'+(n!=null?n:'')+'へ組み直し'))+' <button class="nqb b-clear" onclick="rebalDone()" style="margin-left:6px">完了</button>';
  }else el.style.display='none';
}
function rebalDone(){try{localStorage.setItem('rebalDoneDate',sessionDate());}catch(e){} _rebalCheck2();}
if(document.readyState!=='loading'){_rebalCheck2();}else{document.addEventListener('DOMContentLoaded',_rebalCheck2);}
function tkSearch(q){
  var box=document.getElementById('tkresults'); if(!box) return;
  q=(q||'').trim().toUpperCase();
  if(q.length<1){ box.innerHTML=''; return; }
  var D=window.DET||{}, out=[];
  for(var k in D){
    if(k.indexOf(q)>-1){ out.push(k); }
    if(out.length>200) break;
  }
  out.sort(function(a,b){
    var pa=a.indexOf(q)===0?0:1, pb=b.indexOf(q)===0?0:1;
    if(pa!==pb) return pa-pb; return a<b?-1:1;
  });
  if(out.length===0){ box.innerHTML='<div class="tkno">該当なし</div>'; return; }
  box.innerHTML=out.slice(0,20).map(function(k){
    var d=D[k];
    return '<div class="tkr" data-tkone="'+k+'"><span class="tkr-s">'+k+'</span>'
      +'<span class="tkr-rs">RS '+(d.rs==null?'—':d.rs)+'</span></div>';
  }).join('');
}
/* ---- 資金配分・株数計算＋建値/売却メモリ（localStorage） ---- */
function ccKey(){return 'cc_entries_v1';}
function ccPeakKey(){return 'cc_peak_v1';}
function ccTakenKey(){return 'cc_taken_v1';}
function ccLoad(k){try{return JSON.parse(localStorage.getItem(k)||'{}')||{};}catch(e){return {};}}
function ccSet(k,o){try{localStorage.setItem(k,JSON.stringify(o));}catch(e){}}
function ccPeak(key,px,entry){
  /* #7 実保有ピーク: tradeId単位で管理し、実建値をフロアに現在値で前進蓄積する。
     ティッカー単位だと同一銘柄の再購入で前回トレードのピークを引き継ぐため、必ずtradeId等の一意キーで呼ぶ。 */
  if(!entry||!key) return (px>0?px:(entry||null));
  var o=ccLoad(ccPeakKey()); var cur=o[key]; if(!(cur>0)) cur=entry; if(px>cur)cur=px; o[key]=cur; ccSet(ccPeakKey(),o); return cur;
}
function takenLoad(){return ccLoad(ccTakenKey());}
/* ===== Core 12の実建値・約定・決済は v38_holdings(strat=core) を唯一のソースにする ===== */
function _coreLatestRec(tk){
  var a=hldLoad(); tk=String(tk).toUpperCase();
  for(var i=a.length-1;i>=0;i--){ if(a[i].strat==='core' && String(a[i].t).toUpperCase()===tk) return i; }
  return -1;
}
function _coreRec(tk){
  var a=hldLoad(); tk=String(tk).toUpperCase();
  for(var i=a.length-1;i>=0;i--){ if(a[i].strat==='core' && String(a[i].t).toUpperCase()===tk && a[i].status!=='closed') return i; }
  return -1;
}
function _coreEnsure(tk){
  var i=_coreRec(tk); if(i>=0) return i;
  var a=hldLoad(), h=_hldNewTrade(String(tk).toUpperCase(),'core',_hldToday());
  h.filled=false; h.coreSold=false; h.plannedEntry=null;
  a.push(h); hldSave(a); return a.length-1;
}
function _corePrune(tk){
  var i=_coreRec(tk); if(i<0) return; var a=hldLoad(), h=a[i];
  if(!(h.plannedEntry>0) && !(h.px>0) && !h.filled && !h.coreSold && !(h.exits&&h.exits.length) && !h.memo && !h.setup && !(h.remainingShares>0)){
    a.splice(i,1); hldSave(a);
  }
}
function coreEntry(tk){
  var i=_coreRec(tk); if(i<0) return null; var h=hldLoad()[i];
  return (h.filled && h.entryAvg>0)?h.entryAvg:(h.plannedEntry||h.avgPx||h.px||null);
}
function coreSetEntry(tk,px){
  var i=(px>0)?_coreEnsure(tk):_coreRec(tk); if(i<0) return;
  var a=hldLoad(), h=a[i];
  if(h.filled && h.remainingShares>0){ return; }  // 約定済みの実建値はPositionsの編集からのみ変更
  h.plannedEntry=(px>0?px:null); h.px=(px>0?px:null); h.avgPx=(px>0?px:null);
  a[i]=h; hldSave(a); if(!(px>0)) _corePrune(tk);
}
function coreSold(tk){
  var i=_coreLatestRec(tk); if(i<0) return false; var h=hldLoad()[i];
  return !!(h.coreSold || h.status==='closed');
}
function coreFilled(tk){
  var i=_coreRec(tk); if(i<0) return false; var h=hldLoad()[i];
  return !!(h.filled && h.remainingShares>0 && h.entryAvg>0);
}
function coreMarkFilled(tk,suggestedShares){
  var i=_coreEnsure(tk), a=hldLoad(), h=a[i], D=window.DET||{};
  if(h.filled && h.remainingShares>0){ try{alert('約定済みです。建値・株数の訂正はPositionsの「編集」を使ってください。');}catch(e){} return; }
  try{
    var defPx=coreEntry(tk)||((D[tk]||{}).px)||'';
    var pr=window.prompt('【'+tk+'】実約定価格',defPx); if(pr===null) return;
    var price=parseFloat(pr); if(!(price>0)){ alert('価格が不正です'); return; }
    var shr=window.prompt('【'+tk+'】実約定株数',suggestedShares>0?suggestedShares:''); if(shr===null) return;
    var shares=parseFloat(shr); if(!(shares>0)){ alert('株数が不正です'); return; }
    var date=window.prompt('【'+tk+'】約定日(YYYY-MM-DD)',_hldToday()); if(date===null) return;
    if(!_hldValidDate(date)){ alert('日付が不正です'); return; }
    h=_hldInitFilled(h,price,shares,date);
    h.initialStop=price*0.75; h.stop=h.initialStop; h.initialRiskTotal=(price-h.initialStop)*shares;
    h.filled=true; h.coreSold=false; h.plannedEntry=price;
    a[i]=h; hldSave(a); hldRender();
  }catch(e){}
}
function coreToggleFilled(tk,suggestedShares){ coreMarkFilled(tk,suggestedShares); }
function coreToggleSold(tk){
  var i=_coreEnsure(tk), a=hldLoad(), h=a[i];
  h.coreSold=!h.coreSold; a[i]=h; hldSave(a); if(!h.coreSold) _corePrune(tk);
}
function coreCloseTrade(tk){
  var i=_coreRec(tk), a=hldLoad();
  if(i>=0){
    var h=a[i];
    if(h.filled && h.remainingShares>0){ hldClose(null,i); return; }
    coreToggleSold(tk); return;
  }
  var li=_coreLatestRec(tk);
  if(li>=0){
    var last=a[li];
    if(last.status==='closed' || last.coreSold){
      try{ if(!window.confirm('【'+tk+'】売却済み表示を解除し、再エントリー準備へ戻しますか？')) return; }catch(e){}
      var ni=_coreEnsure(tk), a2=hldLoad(); a2[ni].coreSold=false; hldSave(a2); calcRun(); return;
    }
  }
  coreToggleSold(tk);
}
function coreHeldTickers(){
  return hldLoad().filter(function(h){return h.strat==='core' && h.status!=='closed' && h.filled && h.remainingShares>0;})
    .map(function(h){return String(h.t).toUpperCase();});
}
function _coreMigrate(){
  try{
    if(localStorage.getItem('v38_core_migrated')==='1') return;
    var ent=ccLoad(ccKey()), sold=takenLoad(), filled=_entLoad(), keys={};
    [ent,sold,filled].forEach(function(o){Object.keys(o||{}).forEach(function(k){keys[k]=1;});});
    Object.keys(keys).forEach(function(tk){
      if(_coreLatestRec(tk)>=0) return;
      var px=parseFloat((ent||{})[tk]), i=_coreEnsure(tk), a=hldLoad(), h=a[i];
      if(px>0){ h.plannedEntry=px; h.px=px; h.avgPx=px; }
      h.coreSold=!!(sold||{})[tk]; h.legacyFilled=!!(filled||{})[tk]; // 株数不明の旧「済」は実約定扱いにしない
      a[i]=h; hldSave(a); _corePrune(tk);
    });
    localStorage.setItem('v38_core_migrated','1');
  }catch(e){}
}
function toggleTaken(t){ coreCloseTrade(t); try{calcRun();}catch(e){} }
function plHtml(n,e,tk){
  if(!e) return '<span class="mut">建値未入力</span>';
  var pl=(n.px/e-1)*100;                       // 損益は実建値ベース
  // #7 出口も【実保有】基準に統一。ピークはtradeId単位・実建値フロアの実保有ピーク（モデル値sysPeakとは混ぜない：
  //    モデルは実約定前の高値を含み得てトレールが不正に厳しくなるため）。実保有レコードが無い時のみ実建値ストップ。
  var initial=e*0.75;
  var _ci=(typeof _coreLatestRec==='function')?_coreLatestRec(n.t||tk):-1;
  var _tid=(_ci>=0)?(hldLoad()[_ci]||{}).tradeId:null;
  var pk=_tid?ccPeak(_tid,n.px,e):null;
  var trailing=pk?pk*0.70:initial;
  var stop=Math.max(initial,trailing);
  var which=(trailing>=initial)?'ピーク×0.70':'実建値×0.75';
  var brk=n.px<=stop?' <span class="neg">割れ→売り</span>':'';
  var _mdl=(n.sysPeak!=null&&Math.abs(n.sysPeak-(pk||e))/(pk||e)>0.03)?(' <span class="mut" style="font-size:9px">｜モデル出口 $'+Number(Math.max(initial,n.sysPeak*0.70)).toFixed(2)+'</span>'):'';
  return '<span class="'+(pl>=0?'pos':'neg')+'" style="font-weight:700">'+(pl>=0?'+':'')+pl.toFixed(1)+'%</span>'
       + '<div class="mut" style="font-size:10px">出口 $'+Number(stop).toFixed(2)+' ('+which+'・実保有基準)'+brk+_mdl+'</div>';
}
function entSave(el){
  var t=el.getAttribute('data-t'), v=parseFloat(el.value);
  coreSetEntry(t, v>0?v:0);
  var C=window.CALC||{}, n=(C.names||[]).find(function(x){return x.t===t;}); if(!n)return;
  var tr=el.closest('tr'), c=tr&&tr.querySelector('.pl-cell'); if(c)c.innerHTML=plHtml(n,v>0?v:null,coreSold(t));
  rebalCheck();
}
function _swv(id){var el=document.getElementById(id);return el?el.value:'';}
function _swfmt(n){return Math.round(n).toLocaleString();}
function swInit(){
  var dl=document.getElementById('swList');
  if(dl && !dl._done){ dl._done=1;
    (window.SWING||[]).forEach(function(c){
      var o=document.createElement('option'); o.value=c.t; o.label=c.t+' ($'+c.px.toFixed(2)+' / RS'+Math.round(c.rs)+')'; dl.appendChild(o);
    });
  }
  var hl=document.getElementById('hldTkList');
  if(hl && !hl._done){ hl._done=1;
    Object.keys(window.DET||{}).sort().forEach(function(t){ var o=document.createElement('option'); o.value=t; hl.appendChild(o); });
  }
  try{ var a=localStorage.getItem('eqLast'); var el=document.getElementById('swAsset');
       if(a&&el&&!el.value) el.value=a; }catch(e){}
  swingCalc();
}
function _swCand(){ var el=document.getElementById('swPick'); var t=(el?el.value:'').trim().toUpperCase(); return (window.SWING||[]).find(function(x){return String(x.t).toUpperCase()===t;}); }
/* ---- 保有記録（手入力・端末ローカル） ---- */
function hldKey(){ return 'v38_holdings'; }
var HLD_SCHEMA=3;
function _hldNewId(){
  try{ if(window.crypto&&window.crypto.randomUUID) return window.crypto.randomUUID(); }catch(e){}
  return 'tr-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10);
}
function _hldHash(s){ var h=2166136261; s=String(s||''); for(var i=0;i<s.length;i++){ h^=s.charCodeAt(i); h+=(h<<1)+(h<<4)+(h<<7)+(h<<8)+(h<<24); } return (h>>>0).toString(36); }
function _hldSig(h){
  return [String(h.t||'').toUpperCase(),h.strat||'',h.dt||'',h.entryAvg||h.avgPx||h.px||'',h.filledSharesTotal||h.sh||'',h.closeDate||'',JSON.stringify(h.exits||[])].join('|');
}
function hldLoad(){
  var raw=null;
  try{ raw=localStorage.getItem(hldKey()); if(!raw) return []; var a=JSON.parse(raw); if(!Array.isArray(a)) throw new Error('not array'); return a.map(_hldNormalize).filter(function(x){return x;}); }
  catch(e){
    try{
      var prev=localStorage.getItem(hldKey()+'_prev');
      if(prev){ var b=JSON.parse(prev); if(Array.isArray(b)){ if(!window._hldWarned){window._hldWarned=1;alert('トレードノートの現行データを読めなかったため、直前バックアップを復元表示します。JSONバックアップも確認してください。');} return b.map(_hldNormalize).filter(function(x){return x;}); } }
      if(!window._hldWarned){window._hldWarned=1;alert('トレードノートの保存データを読み込めません。JSONバックアップから復元してください。');}
    }catch(e2){}
    return [];
  }
}
function hldSave(a){
  try{
    var cur=localStorage.getItem(hldKey());
    if(cur){ try{ JSON.parse(cur); localStorage.setItem(hldKey()+'_prev',cur); }catch(e0){} }
    localStorage.setItem(hldKey(),JSON.stringify(a)); return true;
  }catch(e){ try{alert('保存に失敗しました（容量超過など）。JSONバックアップで退避してください。');}catch(e2){} return false; }
}
function _hldNum(v){ if(v===null||v===undefined||v==='') return null; var n=Number(v); return isFinite(n)?n:null; }
function _hldValidDate(s){ if(!/^\d{4}-\d{2}-\d{2}$/.test(String(s||''))) return false; var d=new Date(String(s)+'T00:00:00'); return !isNaN(d.getTime()); }
function _hldDateOnOrAfter(s,base){ return _hldValidDate(s)&&(!base||!_hldValidDate(base)||new Date(s+'T00:00:00')>=new Date(base+'T00:00:00')); }
function _daysBetween(start,end){ try{ if(!_hldValidDate(start)||!_hldValidDate(end)) return null; var a=new Date(start+'T00:00:00'),b=new Date(end+'T00:00:00'); return Math.max(0,Math.floor((b-a)/86400000)); }catch(e){return null;} }
function _hldToday(){
  try{ var a=window.CALC&&window.CALC.asof; if(a&&_hldValidDate(String(a).slice(0,10))) return String(a).slice(0,10); }catch(e){}
  try{return (new Date()).toLocaleDateString('sv-SE');}catch(e2){return '';}
}
function sessionDate(){
  /* 米国確定営業日(=ビルドのas-of)を唯一の基準日にする。JST端末日と米国セッション日のズレを防ぐ(#9) */
  try{ var a=window.CALC&&window.CALC.asof; if(a) return String(a).slice(0,10); }catch(e){}
  try{ return (new Date()).toLocaleDateString('sv-SE'); }catch(e2){ return ''; }
}
function _hldDays(d){ return _daysBetween(d,_hldToday()); }
function _hldStratVal(){ var b=document.querySelector('#hldStratSeg .stratbtn.on'); return (b&&b.getAttribute('data-strat'))||'core'; }
function hldStratPick(b){ var seg=b.parentElement; if(seg){[].forEach.call(seg.querySelectorAll('.stratbtn'),function(x){x.classList.remove('on');});} b.classList.add('on'); }
function _hldStratMeta(s){ return s==='swing'?{lab:'裁量',cls:'strat-swing',exit:'+25%で1/3利確 → 残りは21EMA Low/10日線でトレール'}:{lab:'Core 12',cls:'strat-core',exit:'ピーク×0.70 または 建値×0.75（途中利確しない）'}; }
function _hldNoteIn(){var g=function(id){var e=document.getElementById(id);return e?(e.value||''):'';};return {setup:g('hldSetup'),conv:g('hldConv'),memo:g('hldMemo')};}
function _hldEnv(tk){var C=window.CALC||{},D=window.DET||{},d=D[tk]||{};return {envColor:(C.color||''),eRS63:(d.rs!=null?d.rs:null),eRS189:(d.rs189!=null?d.rs189:null),theme:(d.sth||d.sec||''),entryPx:(d.px!=null?d.px:null),envAsOf:_hldToday()};}
function _hldClearNote(){['hldSetup','hldConv','hldMemo'].forEach(function(id){var e=document.getElementById(id);if(e)e.value='';});}
function _hldNewTrade(tk,strat,date){ return {tradeId:_hldNewId(),schemaVersion:HLD_SCHEMA,t:String(tk||'').toUpperCase(),strat:(strat==='core'?'core':'swing'),status:'open',dt:date||_hldToday(),fills:[],exits:[],leg2:'none',filled:false,coreSold:false,remainingShares:0,remainingCost:0,filledSharesTotal:0,entryCostTotal:0,entryAvg:null,avgPx:null,px:null,initialStop:null,initialRiskTotal:null,stop:null,stopOverride:null,partialDone:false}; }
function _hldRiskTotal(h,stop){
  if(!(stop>0)) return null; var fills=h.fills||[], total=0, used=false;
  fills.forEach(function(f){var p=_hldNum(f.price),sh=_hldNum(f.shares);if(p!=null&&sh>0){total+=Math.max(0,p-stop)*sh;used=true;}});
  if(used) return total;
  var av=_hldNum(h.entryAvg||h.avgPx||h.px), n=_hldNum(h.filledSharesTotal||h.sh); return (av!=null&&n>0)?Math.max(0,av-stop)*n:null;
}
function _hldInitFilled(h,price,shares,date){
  h.fills=[{leg:1,date:date,price:price,shares:shares}]; h.leg2='none'; h.px1=price; h.sh1=shares; h.px2=null; h.sh2=null; h.leg2Date=null;
  h.filled=true; h.dt=date; h.filledSharesTotal=shares; h.entryCostTotal=price*shares; h.entryAvg=price;
  h.remainingShares=shares; h.remainingCost=price*shares; h.sh=shares; h.px=price; h.avgPx=price; h.status='open'; h.closeDate=null; h.heldDays=null;
  return h;
}
function _hldNormalize(src){
  if(!src||typeof src!=='object'||!src.t) return null; var h=Object.assign({},src);
  h.t=String(h.t).toUpperCase(); if(h.strat!=='core'&&h.strat!=='swing') h.strat='swing'; if(h.status!=='closed') h.status='open';
  if(!Array.isArray(h.exits)) h.exits=[]; h.exits=h.exits.map(function(x){return Object.assign({},x);}); if(!h.leg2)h.leg2='none';
  if(!Array.isArray(h.fills)){
    h.fills=[];
    if(_hldNum(h.px1)>0&&_hldNum(h.sh1)>0) h.fills.push({leg:1,date:h.dt||'',price:+h.px1,shares:+h.sh1});
    if(h.leg2==='filled'&&_hldNum(h.px2)>0&&_hldNum(h.sh2)>0) h.fills.push({leg:2,date:h.leg2Date||h.dt||'',price:+h.px2,shares:+h.sh2});
    if(!h.fills.length&&_hldNum(h.avgPx||h.px)>0&&_hldNum(h.sh)>0) h.fills.push({leg:1,date:h.dt||'',price:+(h.avgPx||h.px),shares:+h.sh});
  }
  var fillSh=h.fills.reduce(function(s,f){return s+(_hldNum(f.shares)||0);},0), fillCost=h.fills.reduce(function(s,f){var p=_hldNum(f.price),n=_hldNum(f.shares);return s+((p!=null&&n>0)?p*n:0);},0);
  h.filledSharesTotal=(_hldNum(h.filledSharesTotal)>0)?+h.filledSharesTotal:(fillSh>0?fillSh:(_hldNum(h.sh)||0));
  var _ect=_hldNum(h.entryCostTotal); h.entryCostTotal=(_ect!=null&&_ect>=0)?_ect:(fillCost>0?fillCost:((_hldNum(h.entryAvg||h.avgPx||h.px)||0)*h.filledSharesTotal));
  h.entryAvg=h.filledSharesTotal>0?h.entryCostTotal/h.filledSharesTotal:(_hldNum(h.entryAvg||h.avgPx||h.px));
  var exited=h.exits.reduce(function(s,x){return s+(_hldNum(x.shares)||0);},0);
  if(h.remainingShares==null) h.remainingShares=h.status==='closed'?0:Math.max(0,h.filledSharesTotal-exited); else h.remainingShares=Math.max(0,+h.remainingShares||0);
  if(h.remainingCost==null){
    var rc=h.entryCostTotal;
    h.exits.forEach(function(x){var n=_hldNum(x.shares)||0,cb=_hldNum(x.costBasis);rc-=n*(cb!=null?cb:(h.entryAvg||0));});
    h.remainingCost=Math.max(0,rc);
  }else h.remainingCost=Math.max(0,+h.remainingCost||0);
  if(h.status==='closed'){h.remainingShares=0;h.remainingCost=0;}
  h.avgPx=h.remainingShares>0?h.remainingCost/h.remainingShares:h.entryAvg; h.px=h.entryAvg; h.sh=h.filledSharesTotal;
  if(h.initialRiskTotal==null) h.initialRiskTotal=_hldRiskTotal(h,_hldNum(h.initialStop));
  if(!h.tradeId) h.tradeId='legacy-'+_hldHash(_hldSig(h)); h.schemaVersion=HLD_SCHEMA;
  h.filled=!!(h.filled||h.filledSharesTotal>0); h.partialDone=_hldTpRemaining(h)===0 && h.exits.some(function(x){return x.type==='partial';});
  return h;
}
function _hldEff(h){
  h=_hldNormalize(h)||h;
  if(h.status==='closed') return {sh:h.filledSharesTotal||null,avg:h.entryAvg||null};
  var sh=_hldNum(h.remainingShares),cost=_hldNum(h.remainingCost); return {sh:(sh>0?sh:null),avg:(sh>0&&cost!=null?cost/sh:(h.entryAvg||null))};
}
function _hldOrigSh(h){ h=_hldNormalize(h)||h; return h.filledSharesTotal||0; }
function _hldPartialExited(h){return (h.exits||[]).filter(function(x){return x.type==='partial';}).reduce(function(s,x){return s+(_hldNum(x.shares)||0);},0);}
function _hldTpRemaining(h){
  var total=_hldNum(h.filledSharesTotal)||0, frac=_hldNum(h.tpFraction)||33; if(!(total>0)) return 0;
  var target=Math.floor(total*frac/100); return Math.max(0,target-_hldPartialExited(h));
}
function currentSwingStop(h){ var d=(window.DET||{})[h.t]||{}; if(h.stopOverride!=null) return h.stopOverride; if(h.exitType==='e21l'&&d.e21l!=null)return d.e21l; if(h.exitType==='s10'&&d.s10!=null)return d.s10; return h.stop!=null?h.stop:null; }
function hldAdd(){
  var tkEl=document.getElementById('hldTk'); if(!tkEl)return; var tk=(tkEl.value||'').trim().toUpperCase(); if(!tk)return;
  var sh=parseFloat((document.getElementById('hldSh')||{}).value),px=parseFloat((document.getElementById('hldPx')||{}).value),date=((document.getElementById('hldDt')||{}).value)||_hldToday(),strat=_hldStratVal();
  if(!(sh>0&&px>0)){alert('実保有として登録するには株数と建値が必要です。');return;} if(!_hldValidDate(date)){alert('取得日が不正です');return;}
  var stop=null;
  if(strat==='swing'){var sv=window.prompt('【'+tk+'】初期ストップ（R計算に必須）','');if(sv===null)return;stop=parseFloat(sv);if(!(stop>0&&stop<px)){alert('初期ストップは建値より下の正の値を入力してください');return;}}
  else stop=px*0.75;
  var a=hldLoad(),dup=a.filter(function(x){return String(x.t).toUpperCase()===tk&&x.status!=='closed'&&x.strat===strat;}).length;
  if(dup>0&&!window.confirm(tk+' は同じ戦略で保有中です。別ロットとして追加しますか？'))return;
  var h=_hldInitFilled(_hldNewTrade(tk,strat,date),px,sh,date); h.initialStop=stop;h.stop=stop;h.initialRiskTotal=_hldRiskTotal(h,stop);h=Object.assign(h,_hldNoteIn(),_hldEnv(tk));
  a.push(h);hldSave(a);tkEl.value='';['hldSh','hldPx','hldDt'].forEach(function(id){var e=document.getElementById(id);if(e)e.value='';});_hldClearNote();hldRender();
}
function hldDel(ev,i){if(ev&&ev.stopPropagation)ev.stopPropagation();var a=hldLoad();if(i<0||i>=a.length)return;var h=a[i];if(!window.confirm('【'+(h.t||'?')+'】の記録を削除します。元に戻せません（決済履歴も消えます）。よろしいですか？'))return;a.splice(i,1);hldSave(a);hldRender();}
function hldFromPlan(){
  var p=window._lastPlan||{};if(!p||!(p.px1>0)){alert('有効なプランがありません。上で再計算してください。');return;}
  var tk=(p.t||'').trim().toUpperCase();if(!tk){alert('上のプランで銘柄を入力してください');return;}
  var pxDef=parseFloat((document.getElementById('hldPx')||{}).value)||p.px1,shDef=parseFloat((document.getElementById('hldSh')||{}).value)||p.sh1;
  var fp=window.prompt('【'+tk+'】第1脚の実約定価格',pxDef);if(fp===null)return;var price=parseFloat(fp);if(!(price>0)){alert('価格が不正です');return;}
  var fs=window.prompt('【'+tk+'】第1脚の実約定株数',shDef);if(fs===null)return;var shares=parseFloat(fs);if(!(shares>0)){alert('株数が不正です');return;}
  var date=window.prompt('【'+tk+'】第1脚の約定日(YYYY-MM-DD)',((document.getElementById('hldDt')||{}).value)||_hldToday());if(date===null)return;if(!_hldValidDate(date)){alert('日付が不正です');return;}
  if(!(p.stop>0)&&!window.confirm(tk+'：初期ストップ未設定のためRを計算できません。このまま記録しますか？'))return;
  var h=_hldInitFilled(_hldNewTrade(tk,'swing',date),price,shares,date);h.initialStop=p.stop>0?p.stop:null;h.stop=p.stop>0?p.stop:null;h.exitType=p.exitType;h.exitLabel=p.exitLabel;h.tpPct=p.tpPct||25;h.tpFraction=p.tpFraction||33;
  var plannedSh=_hldNum(p.plannedSh2!=null?p.plannedSh2:p.sh2); if(plannedSh>0){h.leg2='planned';h.sh2=plannedSh;h.px2=_hldNum(p.plannedPx2!=null?p.plannedPx2:p.px2);}
  h.initialRiskTotal=_hldRiskTotal(h,h.initialStop);h.tpPrice=h.entryAvg*(1+h.tpPct/100);h.tpShares=_hldTpRemaining(h);h=Object.assign(h,_hldNoteIn(),_hldEnv(tk));
  var a=hldLoad(),dup=a.filter(function(x){return String(x.t).toUpperCase()===tk&&x.status!=='closed';}).length;if(dup>0&&!window.confirm(tk+' は既に'+dup+'件の保有中記録があります。別記録として追加しますか？'))return;
  a.push(h);hldSave(a);var tkIn=document.getElementById('hldTk');if(tkIn)tkIn.value='';['hldSh','hldPx','hldDt'].forEach(function(id){var e=document.getElementById(id);if(e)e.value='';});_hldClearNote();hldRender();
}
function _hldApplyFill(h,leg,date,price,shares){
  h=_hldNormalize(h)||h;h.fills=h.fills||[];h.fills.push({leg:leg,date:date,price:price,shares:shares});h.filledSharesTotal+=shares;h.entryCostTotal+=price*shares;h.entryAvg=h.entryCostTotal/h.filledSharesTotal;h.remainingShares+=shares;h.remainingCost+=price*shares;h.avgPx=h.remainingCost/h.remainingShares;h.px=h.entryAvg;h.sh=h.filledSharesTotal;h.filled=true;
  if(h.initialStop!=null)h.initialRiskTotal=(h.initialRiskTotal||0)+Math.max(0,price-h.initialStop)*shares;else h.initialRiskTotal=null;
  return h;
}
function hldFillLeg2(ev,i){
  if(ev&&ev.stopPropagation)ev.stopPropagation();var a=hldLoad();if(i<0||i>=a.length)return;var h=a[i];if(h.leg2!=='planned')return;
  try{var pr=window.prompt('【'+h.t+'】第2脚の実約定価格'+(h.px2?'（予定 $'+h.px2+'）':''),h.px2||'');if(pr===null)return;var price=parseFloat(pr);if(!(price>0)){alert('価格が不正です');return;}
    var sr=window.prompt('【'+h.t+'】第2脚の実約定株数（予定 '+(h.sh2||0)+'株）',h.sh2||'');if(sr===null)return;var shares=parseFloat(sr);if(!(shares>0)){alert('株数が不正です');return;}
    var date=window.prompt('【'+h.t+'】第2脚の約定日(YYYY-MM-DD)',_hldToday());if(date===null)return;if(!_hldDateOnOrAfter(date,h.dt)){alert('第2脚日は第1脚の約定日以降にしてください');return;}
    h=_hldApplyFill(h,2,date,price,shares);h.px2=price;h.sh2=shares;h.leg2Date=date;h.leg2='filled';if(h.tpPct!=null)h.tpPrice=h.avgPx*(1+h.tpPct/100);h.tpShares=_hldTpRemaining(h);h.partialDone=h.tpShares===0&&_hldPartialExited(h)>0;
    a[i]=h;hldSave(a);hldRender();
  }catch(e){}
}
function _hldRecordExit(h,o){
  h=_hldNormalize(h)||h;var rem=h.remainingShares||0;if(!(o.shares>0)||o.shares>rem)throw new Error('exit shares');var cb=rem>0?h.remainingCost/rem:null,pnl=(cb!=null&&o.price!=null)?(o.price-cb)*o.shares:null;
  h.exits=h.exits||[];h.exits.push({exitId:_hldNewId(),type:o.type||'partial',date:o.date,price:o.price,shares:o.shares,reason:o.reason||'',costBasis:cb,initialStopAt:h.initialStop,realizedPnl:pnl});
  h.remainingCost=Math.max(0,h.remainingCost-(cb||0)*o.shares);h.remainingShares=Math.max(0,rem-o.shares);h.avgPx=h.remainingShares>0?h.remainingCost/h.remainingShares:h.entryAvg;h.tpShares=_hldTpRemaining(h);h.partialDone=h.tpShares===0&&_hldPartialExited(h)>0;return h;
}
function _hldRealized(h){
  h=_hldNormalize(h)||h;var pnl=0,shExited=0;(h.exits||[]).forEach(function(x){var xp=_hldNum(x.realizedPnl);if(xp==null&&x.costBasis!=null&&x.price!=null&&x.shares!=null)xp=(x.price-x.costBasis)*x.shares;if(xp!=null)pnl+=xp;shExited+=_hldNum(x.shares)||0;});
  var risk=_hldNum(h.initialRiskTotal),R=(risk!=null&&risk>0)?pnl/risk:null;return {pnl:pnl,shExited:shExited,R:R,orig:_hldOrigSh(h)};
}
function _hldFinalize(h,closeDate){var r=_hldRealized(h);h.realizedPnl=r.pnl;h.realizedR=r.R;h.status='closed';h.remainingShares=0;h.remainingCost=0;h.closeDate=closeDate||h.closeDate||_hldToday();h.heldDays=_daysBetween(h.dt,h.closeDate);if(h.strat==='core')h.coreSold=true;}
function hldTakePartial(ev,i){
  if(ev&&ev.stopPropagation)ev.stopPropagation();var a=hldLoad();if(i<0||i>=a.length)return;var h=a[i],e=_hldEff(h),defShares=_hldTpRemaining(h),D=window.DET||{},cur=(D[h.t]&&D[h.t].px!=null)?D[h.t].px:'';
  if(!(defShares>0)){alert('ルール上の部分利確目標はすでに完了しています');return;}
  try{var pr=window.prompt('【'+h.t+'】部分利確：約定価格',h.tpPrice?(+h.tpPrice).toFixed(2):cur);if(pr===null)return;var price=parseFloat(pr);if(!(price>0)){alert('価格が不正です');return;}
    var rem=h.remainingShares||0,sr=window.prompt('【'+h.t+'】部分利確：株数（残 '+rem+'株／目標残り '+defShares+'株）',Math.min(defShares,rem));if(sr===null)return;var shares=parseFloat(sr);if(!(shares>0)){alert('株数が不正です');return;}if(shares>=rem){if(!window.confirm('残株すべて（'+rem+'株）を売却＝全決済になります。よろしいですか？'))return;shares=rem;}
    var date=window.prompt('【'+h.t+'】決済日(YYYY-MM-DD)',_hldToday());if(date===null)return;if(!_hldDateOnOrAfter(date,h.dt)){alert('決済日は取得日以降にしてください');return;}
    var closing=shares>=rem,rsn=window.prompt('【'+h.t+'】'+(closing?'手仕舞い理由':'理由（TP1/利確 等・任意）'),closing?(h.exitReason||''):'TP');if(rsn===null)rsn='';h=_hldRecordExit(h,{type:closing?'final':'partial',date:date,price:price,shares:shares,reason:rsn});
    if(closing){h.exitReason=rsn;var ls=window.prompt('【'+h.t+'】学び・次に活かす1点（任意）',h.lesson||'');if(ls!==null)h.lesson=ls;_hldFinalize(h,date);}a[i]=h;hldSave(a);hldRender();
  }catch(e2){alert('決済記録に失敗しました');}
}
function hldClose(ev,i){
  if(ev&&ev.stopPropagation)ev.stopPropagation();var a=hldLoad();if(i<0||i>=a.length)return;var h=a[i],rem=h.remainingShares||0,D=window.DET||{},cur=(D[h.t]&&D[h.t].px!=null)?D[h.t].px:'';
  try{var date=h.closeDate||_hldToday();if(rem>0){var pr=window.prompt('【'+h.t+'】全決済：約定価格（残 '+rem+'株）',cur);if(pr===null)return;var price=parseFloat(pr);if(!(price>0)){alert('価格が不正です');return;}date=window.prompt('【'+h.t+'】決済日(YYYY-MM-DD)',_hldToday());if(date===null)return;if(!_hldDateOnOrAfter(date,h.dt)){alert('決済日は取得日以降にしてください');return;}var rsn=window.prompt('【'+h.t+'】手仕舞い理由（ストップ/利確/21EMA割れ/裁量 等）',h.exitReason||'');if(rsn===null)rsn='';h=_hldRecordExit(h,{type:'final',date:date,price:price,shares:rem,reason:rsn});h.exitReason=rsn;}var ls=window.prompt('【'+h.t+'】学び・次に活かす1点（任意）',h.lesson||'');if(ls!==null)h.lesson=ls;_hldFinalize(h,date);a[i]=h;hldSave(a);hldRender();try{calcRun();}catch(e0){}
  }catch(e2){alert('全決済の記録に失敗しました');}
}
function hldEditClosed(ev,i){
  if(ev&&ev.stopPropagation)ev.stopPropagation();var a=hldLoad();if(i<0||i>=a.length)return;var h=a[i],ex=h.exits||[];if(!ex.length){alert('決済履歴がありません');return;}
  try{var pick=0;if(ex.length>1){var menu=ex.map(function(x,j){return (j+1)+'. '+(x.date||'')+' '+(x.type==='final'?'全決済':'部分')+' '+x.shares+'株@$'+x.price;}).join('\n');var v=window.prompt('編集する決済番号を入力\n'+menu,String(ex.length));if(v===null)return;pick=parseInt(v,10)-1;if(!(pick>=0&&pick<ex.length)){alert('番号が不正です');return;}}var x=ex[pick];
    var pr=window.prompt('【'+h.t+'】約定価格を訂正（株数は履歴整合のため固定）',x.price!=null?x.price:'');if(pr===null)return;var price=parseFloat(pr);if(!(price>0)){alert('価格が不正です');return;}
    var date=window.prompt('【'+h.t+'】決済日を訂正(YYYY-MM-DD)',x.date||'');if(date===null)return;if(!_hldDateOnOrAfter(date,h.dt)){alert('決済日は取得日以降にしてください');return;}
    var reason=window.prompt('【'+h.t+'】決済理由を訂正',x.reason||'');if(reason===null)reason=x.reason||'';x.price=price;x.date=date;x.reason=reason;if(x.costBasis!=null)x.realizedPnl=(price-x.costBasis)*x.shares;
    if(x.type==='final'){h.closeDate=date;h.exitReason=reason;h.heldDays=_daysBetween(h.dt,date);}var r=_hldRealized(h);h.realizedPnl=r.pnl;h.realizedR=r.R;a[i]=h;hldSave(a);hldRender();
  }catch(e){}
}
function hldNote(ev,i){if(ev&&ev.stopPropagation)ev.stopPropagation();var a=hldLoad();if(i<0||i>=a.length)return;var h=a[i];try{var memo=window.prompt('【'+h.t+'】エントリー理由・見立て（なぜ今か／トリガー／想定リスク）',h.memo||'');if(memo===null)return;h.memo=memo;var ls=window.prompt('【'+h.t+'】学び・次に活かす1点（任意）',h.lesson||'');if(ls!==null)h.lesson=ls;a[i]=h;hldSave(a);hldRender();}catch(e){}}
function hldEdit(ev,i){
  if(ev&&ev.stopPropagation)ev.stopPropagation();var a=hldLoad();if(i<0||i>=a.length)return;var h=a[i]=_hldNormalize(a[i]),hasExits=!!(h.exits&&h.exits.length),eff=_hldEff(h);
  try{
    if(!hasExits){
      var pv=window.prompt('【'+h.t+'】現在保有の平均建値を修正',eff.avg!=null?eff.avg:'');if(pv===null)return;var px=parseFloat(pv);
      var sv=window.prompt('【'+h.t+'】現在保有株数を修正',eff.sh!=null?eff.sh:'');if(sv===null)return;var sh=parseFloat(sv);if(!(px>0&&sh>0)){alert('建値・株数が不正です');return;}
      var pchg=eff.avg==null||Math.abs(px-eff.avg)>0.005,schg=eff.sh==null||Math.abs(sh-eff.sh)>0.001;
      if(pchg||schg){
        if(h.leg2==='filled'&&!window.confirm('建値または株数を変更すると、2脚の履歴を単一の約定へ統合します。続けますか？'))return;
        if(h.leg2==='planned'){
          h.fills=[{leg:1,date:h.dt,price:px,shares:sh}];h.px1=px;h.sh1=sh;h.filledSharesTotal=sh;h.entryCostTotal=px*sh;h.entryAvg=px;h.remainingShares=sh;h.remainingCost=px*sh;h.avgPx=px;h.px=px;h.sh=sh;
        }else h=_hldInitFilled(h,px,sh,h.dt||_hldToday());
      }
    }else alert('決済履歴があるため、建値・株数はこの画面では変更しません。決済価格は「決済編集」、その他の訂正はJSONバックアップ後に行ってください。');
    var date=window.prompt('【'+h.t+'】取得日を修正(YYYY-MM-DD)',h.dt||'');if(date===null)return;if(!_hldValidDate(date)){alert('日付が不正です');return;}h.dt=date;if(h.fills&&h.fills[0])h.fills[0].date=date;
    var iv=window.prompt('【'+h.t+'】初期ストップ＝R計算基準（訂正。空欄可）',h.initialStop!=null?h.initialStop:'');if(iv===null)return;var ist=parseFloat(iv);h.initialStop=ist>0?ist:null;h.initialRiskTotal=_hldRiskTotal(h,h.initialStop);
    if(h.strat==='swing'&&(h.exitType==='e21l'||h.exitType==='s10')){var ov=window.prompt('【'+h.t+'】現在撤退線の手動上書き（空欄＝'+(h.exitType==='s10'?'10日線':'21EMA Low')+'自動）',h.stopOverride!=null?h.stopOverride:'');if(ov===null)return;var on=parseFloat(ov);h.stopOverride=on>0?on:null;}
    else {var cv=window.prompt('【'+h.t+'】現在ストップ（空欄可）',h.stop!=null?h.stop:'');if(cv===null)return;var cn=parseFloat(cv);h.stop=cn>0?cn:null;}
    var setup=window.prompt('【'+h.t+'】セットアップ',h.setup||'');if(setup!==null)h.setup=setup;var conv=window.prompt('【'+h.t+'】確信度',h.conv||'');if(conv!==null)h.conv=conv;
    if(h.tpPct!=null&&h.remainingShares>0)h.tpPrice=(h.remainingCost/h.remainingShares)*(1+h.tpPct/100);h.tpShares=_hldTpRemaining(h);a[i]=h;hldSave(a);hldRender();
  }catch(e2){}
}
function _mdRow(h){
  h=_hldNormalize(h)||h;var e=_hldEff(h),avg=h.status==='closed'?h.entryAvg:e.avg,sh=h.status==='closed'?h.filledSharesTotal:e.sh,orig=_hldOrigSh(h),D=window.DET||{},cur=(D[h.t]&&D[h.t].px!=null)?D[h.t].px:null,closed=h.status==='closed',L=[];
  L.push('## '+h.t+(h.strat==='core'?'（Core 12）':'（裁量スイング）')+(h.dt?'  ['+h.dt+']':'')+(closed?'  ✅決済済み':''));var l1=[];if(h.setup)l1.push('セットアップ: '+h.setup);if(h.conv)l1.push('確信度: '+h.conv);if(h.envColor)l1.push('環境(NQ): '+h.envColor);if(l1.length)L.push('- '+l1.join(' ／ '));
  var l2=[];if(avg!=null)l2.push('平均建値: $'+(+avg).toFixed(2));if(sh!=null)l2.push((closed?'総約定株数: ':'残株数: ')+sh);if(h.leg2==='planned')l2.push('第2脚 未約定（予定 '+(h.sh2||0)+'株'+(h.px2?'@$'+h.px2:'・価格未設定')+'）');if(h.eRS63!=null||h.eRS189!=null)l2.push('入口RS63/189: '+(h.eRS63!=null?h.eRS63:'—')+'/'+(h.eRS189!=null?h.eRS189:'—'));if(h.theme)l2.push('テーマ: '+h.theme);if(l2.length)L.push('- '+l2.join(' ／ '));
  if(h.fills&&h.fills.length){L.push('- **約定履歴**:');h.fills.forEach(function(f){L.push('  - '+(f.date||'')+' 第'+(f.leg||'')+'脚 '+f.shares+'株 @ $'+(+f.price).toFixed(2));});}
  var stopNow=closed?null:currentSwingStop(h),l3=[];if(h.initialStop!=null)l3.push('初期ストップ: $'+(+h.initialStop).toFixed(2));if(stopNow!=null&&stopNow!==h.initialStop)l3.push('現在撤退線: $'+(+stopNow).toFixed(2)+'（'+_hldToday()+'時点）');if(l3.length)L.push('- '+l3.join(' ／ '));if(h.memo)L.push('- **理由/見立て**: '+h.memo);
  if(h.exits&&h.exits.length){L.push('- **決済履歴**:');h.exits.forEach(function(x){L.push('  - '+(x.date||'')+' '+(x.type==='final'?'全決済':'部分')+' '+(x.shares||0)+'株 @ $'+(x.price!=null?(+x.price).toFixed(2):'—')+(x.reason?'（'+x.reason+'）':''));});}
  if(closed){var r=_hldRealized(h);L.push('- **実現損益（株ベース）**: '+(r.pnl>=0?'+':'')+'$'+r.pnl.toFixed(2)+(r.R!=null?'（'+(r.R>=0?'+':'')+r.R.toFixed(2)+'R）':'（R=初期ストップ未設定）'));if(h.heldDays!=null)L.push('- 経過日数: '+h.heldDays+'日（暦日）');if(h.exitReason)L.push('- **手仕舞い**: '+h.exitReason);}
  else{if(h.remainingShares!=null&&orig!=null&&h.remainingShares!==orig)L.push('- 残株: '+h.remainingShares+'/'+orig);if(cur!=null){var pl=avg!=null?(cur/avg-1)*100:null;L.push('- 現在値: $'+cur+(pl!=null?'（'+(pl>=0?'+':'')+pl.toFixed(1)+'%）':''));}}
  if(h.lesson)L.push('- **学び**: '+h.lesson);return L.join('\n');
}
function hldExport(){var a=hldLoad();if(!a.length){alert('記録がありません。');return;}var today=_hldToday(),open=a.filter(function(h){return h.status!=='closed';}),closed=a.filter(function(h){return h.status==='closed';}),md='# トレードノート（書き出し '+today+'）\n\n記録はこの端末にのみ保存。環境（NQ/RS/テーマ）は記録日時点のスナップショットです。\n\n';md+='# ■ 保有中（'+open.length+'件）\n\n'+(open.length?open.map(_mdRow).join('\n\n---\n\n'):'なし')+'\n\n';md+='# ■ 決済済み（'+closed.length+'件）\n\n'+(closed.length?closed.map(_mdRow).join('\n\n---\n\n'):'なし')+'\n';if(closed.length){var rs=closed.map(function(h){return _hldRealized(h).R;}).filter(function(x){return x!=null;});if(rs.length){var wins=rs.filter(function(x){return x>0;}).length,sum=rs.reduce(function(s,x){return s+x;},0);md+='\n# ■ 集計（R計算できた決済 '+rs.length+'件）\n- 勝率: '+(100*wins/rs.length).toFixed(0)+'%（'+wins+'/'+rs.length+'）\n- 合計R: '+(sum>=0?'+':'')+sum.toFixed(2)+'R ／ 平均R: '+(sum/rs.length>=0?'+':'')+(sum/rs.length).toFixed(2)+'R\n';}}var done=false;try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(md);}}catch(e){}window.prompt('下記をコピー／保存してください（クリップボードにも自動でコピーを試みています）：',md);}
function hldExportJSON(){var a=hldLoad(),payload=JSON.stringify({schemaVersion:HLD_SCHEMA,exportedAt:(new Date()).toISOString(),trades:a});try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(payload);}}catch(e){}window.prompt('このJSONを保存すると復元できます（クリップボードにも自動でコピーを試みています）：',payload);}
function hldImportJSON(){
  try{var s=window.prompt('バックアップJSONを貼り付けてください（現在の記録に追加）','');if(!s)return;var obj=JSON.parse(s),sv=(obj&&!Array.isArray(obj))?obj.schemaVersion:null;if(sv!=null&&Number(sv)>HLD_SCHEMA){alert('このバックアップは新しい形式（schema v'+sv+'）のため取り込めません');return;}var incoming=Array.isArray(obj)?obj:(obj&&Array.isArray(obj.trades)?obj.trades:null);if(!incoming){alert('形式が不正です（trades配列が見つかりません）');return;}
    var norm=incoming.map(_hldNormalize).filter(function(x){return x;}),a=hldLoad(),ids={};a.forEach(function(h){ids[h.tradeId]=1;});var fresh=norm.filter(function(h){return !ids[h.tradeId];}),skipped=incoming.length-fresh.length;if(!fresh.length){alert('追加できる新しい記録はありません（重複または不正）');return;}if(!window.confirm(fresh.length+'件を追加しますか？'+(skipped>0?'（重複/不正 '+skipped+'件はスキップ）':'')))return;a=a.concat(fresh);if(hldSave(a)){hldRender();alert(fresh.length+'件を取り込みました');}
  }catch(e){alert('JSONの解析に失敗しました');}
}
function _escH(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function _hldOpenRow(h,i){
  h=_hldNormalize(h)||h;var D=window.DET||{},e=_hldEff(h),avg=e.avg,sh=e.sh,orig=_hldOrigSh(h),days=_hldDays(h.dt),cur=(D[h.t]&&D[h.t].px!=null)?D[h.t].px:null,pl=(cur!=null&&avg!=null)?(cur/avg-1)*100:null,plc=pl==null?'mut':(pl>=0?'pos':'neg'),plHtml=pl!=null?'<div class="'+plc+'" style="font-size:10px">'+(pl>=0?'+':'')+pl.toFixed(1)+'%'+(cur!=null?' ・現在$'+cur:'')+'</div>':'',meta=_hldStratMeta(h.strat),swx='';
  if(h.leg2==='planned')swx+='<div class="hld-leg"><b class="warnc">第2脚 未約定</b>（予定 '+(h.sh2||0)+'株'+(h.px2?'@$'+h.px2:'・価格未設定')+'）</div><button class="tkbtn hld-legb" onclick="hldFillLeg2(event,'+i+')">第2脚を約定にする</button>';
  if(h.strat==='swing'){var lines=[],st=currentSwingStop(h);if(st!=null&&cur!=null){if(cur<=st)lines.push('<b class="neg">撤退ライン割れ</b> $'+(+st).toFixed(2));else lines.push('撤退（現在）$'+(+st).toFixed(2)+'まで '+((st/cur-1)*100).toFixed(1)+'%');}if(h.initialStop!=null)lines.push('<span class="mut">初期$'+(+h.initialStop).toFixed(2)+'＝R基準（固定）</span>');if(h.tpPrice&&cur!=null&&h.remainingShares>0&&_hldTpRemaining(h)>0){if(cur>=h.tpPrice)lines.push('<b class="pos">部分利確ライン到達</b> $'+(+h.tpPrice).toFixed(2));else lines.push('利確 $'+(+h.tpPrice).toFixed(2)+'まで +'+((h.tpPrice/cur-1)*100).toFixed(1)+'%');}if(lines.length)swx+='<div class="mut hld-plan">'+lines.join('<br>')+'</div>';}
  else if(h.initialStop!=null)swx+='<div class="mut hld-plan"><span class="mut">初期$'+(+h.initialStop).toFixed(2)+'＝R基準（固定）</span></div>';
  var partialCount=(h.exits||[]).filter(function(x){return x.type==='partial';}).length;if(partialCount)swx+='<div class="mut hld-plan">部分決済済 '+partialCount+'回 → 残'+h.remainingShares+'/'+orig+'株</div>';
  var bits=[];if(h.setup)bits.push('<span class="hld-setup">'+_escH(h.setup)+'</span>');if(h.conv)bits.push('<span class="hld-conv">確信'+_escH(h.conv)+'</span>');if(h.envColor)bits.push('<span class="mut">環境'+_escH(h.envColor)+'</span>');if(h.eRS63!=null||h.eRS189!=null)bits.push('<span class="mut">入RS '+(h.eRS63!=null?h.eRS63:'—')+'/'+(h.eRS189!=null?h.eRS189:'—')+'</span>');var note=bits.length?'<div class="hld-note">'+bits.join(' ')+'</div>':'',memo=h.memo?'<div class="hld-memo">📝 '+_escH(h.memo)+'</div>':'',canPartial=h.strat==='swing'&&h.remainingShares>0&&_hldTpRemaining(h)>0;
  return '<tr data-tkone="'+_escH(h.t)+'"><td class="l tk">'+_escH(h.t)+' <span class="stratbadge '+meta.cls+'">'+meta.lab+'</span>'+plHtml+'<div class="mut hld-exit">出口: '+meta.exit+'</div>'+swx+note+memo+'<div class="hld-btns">'+(canPartial?'<button class="tkbtn hld-pt" onclick="hldTakePartial(event,'+i+')">部分決済</button>':'')+'<button class="tkbtn hld-close" onclick="hldClose(event,'+i+')">全決済</button><button class="tkbtn hld-noteb" onclick="hldNote(event,'+i+')">✎ノート</button><button class="tkbtn hld-noteb" onclick="hldEdit(event,'+i+')">編集</button><button class="tkbtn" onclick="hldDel(event,'+i+')">削除</button></div></td><td>'+(sh!=null?sh:'—')+(h.remainingShares!==orig?'<div class="mut" style="font-size:9px">残'+h.remainingShares+'</div>':'')+'</td><td>'+(avg!=null?'$'+(+avg).toFixed(2):'—')+'</td><td><b>'+(days!=null?days+'日':'—')+'</b><div class="mut" style="font-size:9px">'+_escH(h.dt||'')+'</div></td></tr>';
}
function _hldClosedRow(h,i){var r=_hldRealized(h),meta=_hldStratMeta(h.strat),rtxt=r.R!=null?'<b class="'+(r.R>=0?'pos':'neg')+'">'+(r.R>=0?'+':'')+r.R.toFixed(2)+'R</b>':'<span class="mut">R—</span>',ptxt='<span class="'+(r.pnl>=0?'pos':'neg')+'">'+(r.pnl>=0?'+':'')+'$'+r.pnl.toFixed(0)+'</span>',exsum=(h.exits||[]).map(function(x){return (x.date||'')+' '+x.shares+'株@$'+(+x.price).toFixed(2);}).join(' / ');return '<tr><td class="l tk">'+_escH(h.t)+' <span class="stratbadge '+meta.cls+'">'+meta.lab+'</span><div class="hld-note">'+rtxt+' '+ptxt+(h.heldDays!=null?' <span class="mut">'+h.heldDays+'日</span>':'')+(h.setup?' <span class="hld-setup">'+_escH(h.setup)+'</span>':'')+'</div>'+(exsum?'<div class="mut hld-plan">'+_escH(exsum)+'</div>':'')+(h.exitReason?'<div class="hld-memo"><b>手仕舞い</b>：'+_escH(h.exitReason)+'</div>':'')+(h.lesson?'<div class="hld-memo"><b>学び</b>：'+_escH(h.lesson)+'</div>':'')+'<div class="hld-btns"><button class="tkbtn hld-noteb" onclick="hldNote(event,'+i+')">✎ノート</button><button class="tkbtn hld-noteb" onclick="hldEditClosed(event,'+i+')">決済編集</button><button class="tkbtn" onclick="hldDel(event,'+i+')">削除</button></div></td><td colspan="3">'+_escH(h.dt||'')+' → '+_escH(h.closeDate||'')+'</td></tr>';}
function hldRender(){var box=document.getElementById('hldList');if(!box)return;var a=hldLoad(),actions='<div class="ci-row2" style="margin-top:8px;gap:6px;flex-wrap:wrap"><button class="memx" onclick="hldExport()">📤 ノート書き出し(MD)</button><button class="memx" onclick="hldExportJSON()">💾 JSONバックアップ</button><button class="memx" onclick="hldImportJSON()">📥 JSON復元</button></div>';if(!a.length){box.innerHTML='<div class="mut" style="font-size:11px;padding:8px 0">まだ記録なし。買った銘柄を上で追加。</div>'+actions;return;}var open=[],closed=[];a.forEach(function(h,i){if(h.status==='closed')closed.push([h,i]);else open.push([h,i]);});var ob=open.map(function(x){return _hldOpenRow(x[0],x[1]);}).join(''),ot=open.length?'<table class="ptab calc-tab"><thead><tr><th class="l">銘柄</th><th>残株</th><th>残株平均</th><th>経過日数</th></tr></thead><tbody>'+ob+'</tbody></table>':'<div class="mut" style="font-size:11px;padding:6px 0">保有中なし。</div>',ch='';if(closed.length){var rs=closed.map(function(x){return _hldRealized(x[0]).R;}).filter(function(v){return v!=null;}),sm='';if(rs.length){var w=rs.filter(function(v){return v>0;}).length,sum=rs.reduce(function(s,v){return s+v;},0);sm='勝率 '+(100*w/rs.length).toFixed(0)+'%（'+w+'/'+rs.length+'）・合計'+(sum>=0?'+':'')+sum.toFixed(1)+'R・平均'+(sum/rs.length>=0?'+':'')+(sum/rs.length).toFixed(2)+'R';}ch='<details class="cxpl" style="margin-top:10px"><summary>決済済み '+closed.length+'件'+(sm?'（'+sm+'）':'')+'</summary><div class="cxpl-b"><table class="ptab calc-tab"><tbody>'+closed.map(function(x){return _hldClosedRow(x[0],x[1]);}).join('')+'</tbody></table></div></details>';}box.innerHTML=ot+ch+actions+'<div class="mut" style="font-size:10.5px;margin-top:4px">実効建値は<b>残存原価÷残株</b>。決済損益は決済時点の原価で固定し、Rは<b>総実現損益÷総初期リスク</b>。第2脚は約定日・実約定価格・株数を記録。Core 12は部分決済なし。記録はこの端末に保存＝<b>JSONバックアップ</b>推奨。</div>';}
if(document.readyState!=='loading'){try{hldRender();}catch(e){}}else{document.addEventListener('DOMContentLoaded',function(){try{hldRender();}catch(e){}});}
function _swFillStop(){
  var c=_swCand(), exel=document.getElementById('swExit'), ex=exel?exel.value:'e21l';
  var sh=document.getElementById('swStopHint'), si=document.getElementById('swStop');
  if(ex==='manual'){ if(sh)sh.textContent='手入力'; return; }
  var lab=(ex==='s10')?'10日線':'21EMA安値';
  if(!c){ if(si)si.value=''; if(sh)sh.textContent=lab+'（候補を選ぶと自動）'; return; }
  var line=(ex==='s10')?c.s10:c.e21l;
  if(line!=null && si){ si.value=(+line).toFixed(2); if(sh)sh.textContent='自動: '+lab+' $'+(+line).toFixed(2)+'（裁量ツール・正式出口とは別）'; }
  else { if(si)si.value=''; if(sh)sh.textContent=lab+'が取得できず・手入力を'; }
}
function swPickFill(){
  var c=_swCand();
  var e1=document.getElementById('swEntry'), e2=document.getElementById('swEntry2');
  var st=document.getElementById('swStop'), sh=document.getElementById('swStopHint');
  // 銘柄を変えたら前銘柄の値（Entry①②・Stop）を必ず一度クリアしてから新銘柄を入れる
  if(e2)e2.value=''; if(st)st.value='';
  if(c){ if(e1)e1.value=c.px.toFixed(2); _swFillStop(); }
  else {
    // 自動候補にない銘柄は前銘柄の数値を引き継がない。DETに現在値があれば取得
    var t=((document.getElementById('swPick')||{}).value||'').trim().toUpperCase();
    var d=(window.DET||{})[t];
    if(d&&d.px!=null){ if(e1)e1.value=(+d.px).toFixed(2); if(sh)sh.textContent='撤退線は手入力'; }
    else { if(e1)e1.value=''; if(sh)sh.textContent='価格・撤退線を手入力'; }
  }
  swingCalc();
}
function swExitChange(){ _swFillStop(); swingCalc(); }
function swStopManual(){ var ex=document.getElementById('swExit'); if(ex)ex.value='manual'; var sh=document.getElementById('swStopHint'); if(sh)sh.textContent='手入力'; swingCalc(); }
(function(){var _fxset=function(){var f=document.getElementById('swFx'); if(f&&!f.value&&window.CALC&&Number(window.CALC.fx)>0)f.value=Number(window.CALC.fx).toFixed(2);}; if(document.readyState!=='loading')_fxset(); else document.addEventListener('DOMContentLoaded',_fxset);})();
function swingCalc(){
  var out=document.getElementById('swOut'); if(!out) return;
  window._lastPlan=null;   // 全検証通過後にのみ再セット（古いプランの保存事故を防ぐ）
  var asset=parseFloat(_swv('swAsset'))||0;
  var sizePct=parseFloat(_swv('swRisk')); if(!(sizePct>0)) sizePct=8;   // 銘柄サイズ %（総資産比）
  var e1=parseFloat(_swv('swEntry'))||0, e2=parseFloat(_swv('swEntry2'))||0, s=parseFloat(_swv('swStop'))||0;
  var fx=(window.CALC&&Number(window.CALC.fx)>0)?Number(window.CALC.fx):parseFloat((document.getElementById('swFx')||{}).value);
  var tpPct=parseFloat(_swv('swTp')); if(!(tpPct>0)) tpPct=25;
  var tpF=parseFloat(_swv('swTpf')); if(!(tpF>0)) tpF=33; if(tpF>100) tpF=100;
  var exel=document.getElementById('swExit'), exSel=exel?exel.value:'e21l';
  var exLab=(exSel==='s10')?'10日線':(exSel==='manual')?'ハードストップ':'21EMA安値';
  var hasE2=e2>0;
  if(!(fx>0)){
    out.innerHTML='<div class="neg" style="padding:10px 0">ドル円を取得できません。上の<b>USD/JPY欄</b>に入力してください（固定150円での計算はしません）。</div>';
    window._lastPlan=null; return;
  }
  if(!(e1>0&&asset>0)){
    out.innerHTML='<div class="mut" style="padding:10px 0">総資産・エントリー①を入れると、'
      +'<b>総資産'+(sizePct||8)+'%サイズの2分割株数</b>が円と%で出ます（ストップ未入力でも株数は出ます）。候補を選ぶと自動入力。</div>'; return;
  }
  // 銘柄サイズ＝総資産の sizePct%。2分割で①今すぐ50%・②押し目/ブレイク50%。ストップは株数に影響しない。
  var budgetYen=asset*(sizePct/100), budgetUsd=budgetYen/fx;
  var p2=hasE2?e2:e1;
  var sh1=Math.max(0,Math.floor((budgetUsd*0.5)/e1)), sh2=Math.max(0,Math.floor((budgetUsd*0.5)/p2));
  var shares=sh1+sh2;
  var eAvg=shares>0?(sh1*e1+sh2*p2)/shares:e1;   // 加重平均建値（①②は金額50/50＝株数が異なるので株数加重が正）
  var cost1=sh1*e1*fx, cost2=sh2*p2*fx, cost=cost1+cost2, costPct=asset?cost/asset*100:0;
  var tpPx=eAvg*(1+tpPct/100), shTp=Math.floor(shares*tpF/100), shTrail=shares-shTp;
  var hasStop=(s>0&&s<eAvg);                                            // ハードストップは参考の損失計算だけに使う
  var lossYen=hasStop?shares*(eAvg-s)*fx:0, lossPct=(hasStop&&asset)?lossYen/asset*100:0, stopDrop=hasStop?((s/eAvg-1)*100):0;
  var box=function(lab,px,pct,cls,sub){return '<div class="swb '+cls+'"><div class="swbl">'+lab+'</div>'
    +'<div class="swbp">'+(px!=null?'$'+px.toFixed(2):'—')+'</div><div class="swbc">'+pct+'</div>'+(sub?'<div class="swbs">'+sub+'</div>':'')+'</div>';};
  var ladder='<div class="swladder">'
    +box('ハードストップ',(hasStop?s:null),(hasStop?stopDrop.toFixed(1)+'%':'未設定'),'swb-stop',(hasStop?'−¥'+_swfmt(lossYen):exLab))
    +box('①今すぐ',e1,'50%','swb-ent',sh1+'株')
    +box('②押し目/ブレイク',p2,'50%','swb-ent',sh2+'株')
    +box('部分利確 +'+tpPct.toFixed(0)+'%',tpPx,tpF.toFixed(0)+'%','swb-t3',shTp+'株利確')
    +'</div>';
  out.innerHTML=
    '<div class="swkey">買う株数（合計） <b>'+shares+' 株</b>'
      +'<span class="mut"> ・ 2分割 '+sh1+' + '+sh2+'株 ・ 投入 ¥'+_swfmt(cost)+'（総資産の'+costPct.toFixed(1)+'%＝目標'+sizePct+'%）</span></div>'
    +ladder
    +'<div class="swline"><span>① 今すぐ（50%）</span><b>'+sh1+'株 @ $'+e1.toFixed(2)+'</b><span class="mut">¥'+_swfmt(cost1)+'</span></div>'
    +'<div class="swline"><span>② 押し目/ブレイク（50%）</span><b>'+sh2+'株 @ $'+p2.toFixed(2)+'</b><span class="mut">'+(hasE2?('¥'+_swfmt(cost2)):'②未入力＝①と同値で計算')+'</span></div>'
    +'<div class="swline"><span>銘柄サイズ（総資産の'+sizePct+'%）</span><b>¥'+_swfmt(budgetYen)+'</b><span class="mut">平均建値$'+eAvg.toFixed(2)+'</span></div>'
    +(hasStop
        ? '<div class="swline"><span>ハードストップ $'+s.toFixed(2)+'（'+exLab+'・'+stopDrop.toFixed(1)+'%）に当たると</span><b class="neg">−¥'+_swfmt(lossYen)+'</b><span class="mut">総資産の−'+lossPct.toFixed(2)+'%</span></div>'
        : '<div class="swline"><span>ハードストップ</span><b class="mut">未設定</b><span class="mut">撤退ラインを選ぶか手入力（'+exLab+'）</span></div>')
    +'<div class="swline"><span>+'+tpPct.toFixed(0)+'%（$'+tpPx.toFixed(2)+'）到達で</span>'
      +'<b class="pos">'+shTp+'株（'+tpF.toFixed(0)+'%）利確</b><span class="mut">残り'+shTrail+'株</span></div>'
    +'<div class="swline"><span>部分利確のあと 残り'+shTrail+'株は</span><b>'+exLab+'割れで手仕舞い</b></div>'
    +'<div class="mut" style="font-size:11px;margin-top:8px"><b>裁量ツール（正式出口 max(建値×0.75, ピーク×0.70) とは別ルール）</b>。'
      +'株数は<b>総資産の'+sizePct+'%を2分割</b>（①今すぐ50%＋②押し目/ブレイク50%）で決定。'
      +'<b>ハードストップ（'+exLab+'）はサイズ計算に使わず</b>、そこに当たったら撤退。'
      +'<b>+'+tpPct.toFixed(0)+'%で'+tpF.toFixed(0)+'%利確 → 残りは'+exLab+'割れでトレール</b>（建値移動なし）。</div>';
  var _pk=document.getElementById('swPick');
  window._lastPlan={t:(_pk?(_pk.value||'').trim().toUpperCase():''), sh:shares, sh1:sh1, px1:e1,
    sh2:sh2, px2:(hasE2?p2:null), plannedSh2:sh2, plannedPx2:(hasE2?p2:null), hasLeg2:true, leg2PriceSet:hasE2,
    px:eAvg, avgPx:eAvg, stop:(hasStop?s:null), exitType:exSel, exitLabel:exLab,
    tpPct:tpPct, tpFraction:tpF, tpPrice:tpPx, tpShares:shTp, remainingShares:shares, partialDone:false};
}
function rsPeriod(btn){
  var cur=btn.getAttribute('data-cur')||'189';
  var nxt = (cur==='189')?'63':(cur==='63')?'21':'189';
  btn.setAttribute('data-cur',nxt);
  var lab={'189':'189日','63':'63日','21':'21日'}[nxt];
  btn.innerHTML='RS期間: <b>'+lab+'</b> ▾（タップで切替・全表連動）';
  document.querySelectorAll('.rsv').forEach(function(el){
    var v=el.getAttribute('data-p'+nxt); if(v!=null) el.textContent=v;
  });
  document.querySelectorAll('.rsc th, .rshdr').forEach(function(el){ el.textContent='RS'+lab; });
}
function soxlTrGet(){ try{var v=parseInt(localStorage.getItem('v38_soxl_tr')||'0',10); return (v>=0&&v<=3)?v:0;}catch(e){return 0;} }
function soxlTrSet(v){ try{localStorage.setItem('v38_soxl_tr',String(Math.max(0,Math.min(3,v))));}catch(e){} try{calcRun();}catch(e){} }
function calcRun(){
  var C=window.CALC||{}, out=document.getElementById('calcOut'), sum=document.getElementById('calcSum');
  if(!out) return;
  var jpy=parseFloat((document.getElementById('jpyIn')||{}).value)||0;
  var fx=parseFloat((document.getElementById('fxIn')||{}).value)||C.fx||0;
  _coreMigrate();   // #6 旧cc_*/v38_entered を v38_holdings へ一回だけ移行
  var has=jpy>0&&fx>0;
  var _n=Number(C.n);
  if(!(_n>0)){ out.innerHTML='<span class="neg">保有銘柄数設定(CALC.n)を取得できません。株数計算を停止しました。</span>'; if(sum)sum.innerHTML=''; return; }
  var usd=has?jpy/fx:0, indPool=usd*(C.alloc_ind/100)*C.e_ind, levPool=usd*(C.alloc_lev/100)*C.e_lev, per=indPool/_n;
  if(C.color==='Yellow'||C.color==='Red'){ try{localStorage.setItem('v38_soxl_tr','0');}catch(e){} }
  var _noEntry=(C.color==='Yellow'||C.color==='Red');   // 黄/赤＝新規エントリー停止中
  var soldCt=0, rows='';
  (C.names||[]).forEach(function(n){
    var tk=coreSold(n.t); if(tk)soldCt++;
    var _held=(coreEntry(n.t)!=null || coreFilled(n.t));   // 実際に保有中か
    var drop=(n.drop&&!tk), clx=(n.clx&&!tk);
    var wait=(drop&&!clx), okentry=(drop&&clx);
    var base=(has&&!tk)?Math.floor(per/n.px):null;
    var sh=base, doll=(sh!=null)?sh*n.px:0;   // 半分サイズ・ルールは削除済み（half参照を撤去）
    var shCell;
    if(!has){ shCell='<span class="mut">—</span>'; }
    else if(tk){ shCell='<span class="mut">売却済</span>'; }
    else if(_noEntry && !_held){ shCell='<span class="mut kf-skip" style="font-size:10px">新規停止</span>'; }   // 黄/赤で未保有は買える株数を出さない
    /* 急落注意は情報バッジのみ。バックテスト同様に株数は満額表示し、機械的な除外はしない。 */
    else { shCell='<b>'+sh+'</b><div class="mut" style="font-size:10px">$'+doll.toFixed(0)+(_noEntry?'・維持':'')+'</div>'; }
    var tkBtn='<button class="tkbtn'+(tk?' on':'')+'" onclick="toggleTaken(\''+n.t+'\')">'+(tk?'売却済':'売却')+'</button>';
    var isEnt=coreFilled(n.t);
    var entBtn='<button class="entb2'+(isEnt?' ent-on':'')+'" data-tk="'+n.t+'" data-sh="'+(sh!=null?sh:'')+'" onclick="entToggle(event,this)">'+(isEnt?'済':'未')+'</button>';
    var rkb='<span class="rkb">#'+n.rk+'</span>';
    var flg='';
    if(wait) flg+='<span class="kflag kf-skip">急落注意</span>';
    if(okentry) flg+='<span class="kflag kf-ok">投げ確認</span>';
    if(n.d52!=null && n.d52>=-10) flg+='<span class="chaseb" title="52週高値-10%以内。検証: 追いかけは-0.28R。指値は下で待つ">⚠ 高値圏</span>';
    var sub='RS'+n.rs+' ・ $'+n.px.toFixed(2)+((n.r5!=null)?' ・ 5日'+(n.r5>=0?'+':'')+n.r5+'%':'');
    var _ce=coreEntry(n.t);
    rows+='<tr><td class="l tk">'+rkb+' '+n.t+' '+flg+'<div class="mut" style="font-size:10px">'+sub+'</div></td>'
       +'<td>'+shCell+'</td>'
       +'<td><input class="entIn" type="number" inputmode="decimal" value="'+(_ce||'')+'" placeholder="建値" data-t="'+n.t+'" oninput="entSave(this)"'+(isEnt?' readonly title="約定済み。訂正はPositionsの編集を使用"':'')+'>'+entBtn+tkBtn+'</td>'
       +'<td class="pl-cell">'+plHtml(n,_ce,tk)+'</td></tr>';
  });
  var tab='<table class="ptab calc-tab"><thead><tr><th class="l">銘柄</th><th>株数</th><th>建値 / 売却</th><th>損益</th></tr></thead><tbody>'+rows+'</tbody></table>';
  var lev='';
  if(has&&levPool>0){
    var sw=(C.soxl_w!=null)?C.soxl_w:0.5;
    var tq=C.tqqq, sx=C.soxl;
    var trendOk=(C.soxl_trend_ok!==false), bandOk=!!C.soxl_entry_ok;
    var tr=soxlTrGet();                                            // 段階投入 0〜3（端末保存）
    if(C.color==='Yellow' || C.color==='Red' || !trendOk){ try{localStorage.setItem('v38_soxl_tr','0');}catch(e){} tr=0; }
    var sFull=levPool*0.5, sNow=0, sWait=0, tPool=levPool, mode='tqqq';
    if(sw>0 && trendOk && bandOk){
      mode='band'; sNow=sFull*(tr/3); sWait=sFull-sNow; tPool=levPool-sFull;
    } else if(trendOk && tr>0){
      mode='hold'; sNow=sFull*(tr/3); tPool=levPool-sNow;          // 既存SOXL分をTQQQから控除し枠超過を防止
    }
    var th=tq?Math.floor(tPool/tq):null, sxh=(sx&&sNow>0)?Math.floor(sNow/sx):null;
    var hdr=(mode==='band')?('TQQQ 50% / SOXL 50%（段階 '+tr+'/3）・寄り執行')
            :(mode==='hold'?('既存SOXL '+tr+'/3 継続・TQQQは残額（枠内）')
                           :('TQQQ 100%・SOXL見送り（'+((C.soxl_reason)||'投入帯外')+'）'));
    lev='<div class="lev-box"><div class="lev-h">レバ枠（'+hdr+'）</div>'
      +'<div class="lev-r"><span>TQQQ</span><b>'+(th!=null?th+' 株':'価格不明')+'</b><span class="mut">$'+tPool.toFixed(0)+(tq?' / @$'+tq.toFixed(2):'')+'</span></div>';
    if(mode==='band'){
      // 投入帯：段階投入トラッカー
      lev+='<div class="lev-r"><span>SOXL <span class="mut">'+tr+'/3</span></span><b>'+(sxh!=null?sxh+' 株':(tr>0?'価格不明':'0 株'))+'</b><span class="mut">$'+sNow.toFixed(0)+'（満額$'+sFull.toFixed(0)+'）'+(sx?' / @$'+sx.toFixed(2):'')+'</span></div>';
      lev+='<div class="soxl-tr"><span class="mut">段階投入 '+tr+'/3';
      if(tr<3){ lev+='・投入帯なので今日 <b>+1/3（$'+(sFull/3).toFixed(0)+'）</b> 追加可'; }
      else { lev+='・満額（3/3）到達'; }
      lev+='</span><span class="soxl-btns">';
      if(tr<3){ lev+='<button class="nqb b-green" onclick="soxlTrSet('+(tr+1)+')">＋1/3 投入</button>'; }
      lev+='<button class="nqb b-clear" onclick="soxlTrSet(0)">リセット</button></span></div>';
      if(sWait>0.5){ lev+='<div class="lev-r" style="opacity:.7"><span>未投入(待機)</span><b class="mut">現金</b><span class="mut">$'+sWait.toFixed(0)+'／次の投入帯日に +1/3</span></div>'; }
    } else if(mode==='hold'){
      lev+='<div class="lev-r"><span>SOXL <span class="mut">既存 '+tr+'/3</span></span><b>'+(sxh!=null?sxh+' 株':'価格不明')+'</b><span class="mut">$'+sNow.toFixed(0)+(sx?' / @$'+sx.toFixed(2):'')+'</span></div>';
      lev+='<div class="soxl-tr"><span class="mut">投入帯外なので買い増し停止。既存SOXL評価額をTQQQ目標から控除済み（レバ枠を超えない）。</span><span class="soxl-btns"><button class="nqb b-clear" onclick="soxlTrSet(0)">SOXL売却済みにする</button></span></div>';
    } else {
      lev+='<div class="lev-r" style="opacity:.75"><span>SOXL</span><b class="neg">見送り</b><span class="mut">'+((C.soxl_reason)||'50MA帯外')+'／新規停止</span></div>';
    }
    lev+='</div>';
  }
  if(has){
    var freed=per*soldCt;                            // 売却(トレール/ストップ全量退出)で空いた個別枠
    var cash=usd-indPool-levPool;                    // 構造的な現金（ゲート由来）
    var s='<div class="cs-row"><span>USD換算</span><b>$'+usd.toFixed(0)+'</b></div>'
      +'<div class="cs-row"><span>個別枠 '+C.alloc_ind+'%×'+(C.e_ind*100).toFixed(0)+'%</span><b>$'+indPool.toFixed(0)+'</b></div>'
      +'<div class="cs-row"><span>レバ枠 '+C.alloc_lev+'%×'+(C.e_lev*100).toFixed(0)+'%'+((C.emergency_mult||1)<1?'（非常口）':'')+'</span><b>$'+levPool.toFixed(0)+'</b></div>'
      +'<div class="cs-row cs-cash"><span>残り現金（ゲート/非常口由来）</span><b>$'+cash.toFixed(0)+' ・ ¥'+Math.round(cash*fx).toLocaleString()+'</b></div>';
    if((C.emergency_mult||1)<1){
      s+='<div class="cs-row" style="color:#fca5a5"><span>非常口 発動中</span><b>レバ枠を自動で50%へ縮小</b></div>';
    }
    if(freed>0){
      s+='<div class="cs-row"><span>売却で空いた枠（'+soldCt+'銘柄）</span><b>$'+freed.toFixed(0)+'</b></div>';
    }
    sum.innerHTML=s;
    if(C.color==='Yellow'){
      sum.innerHTML+='<div class="cs-row cs-cash" style="color:#eab308"><span>⚠ 黄＝新規停止</span><b>下の株数は既存保有の管理用。新規に買い増さない</b></div>';
    } else if(C.color==='Red'){
      sum.innerHTML+='<div class="cs-row cs-cash" style="color:#f87171"><span>⚠ 赤＝撤退</span><b>個別0%・全て現金</b></div>';
    }
    // 月中の売却枠は再投下せず現金で保持し、次の隔週(月曜)トゥルーアップで吸収。
    if(freed>0){
      lev+='<div class="redep mut" style="padding:8px 10px">売却で空いた $'+freed.toFixed(0)+' は<b>現金のまま保持</b>し、次の隔週トゥルーアップ（月曜）で新Core 12へ均等配分。期中の再投下はしない。</div>';
    }
  } else { sum.innerHTML=''; }
  out.innerHTML = lev + tab;
  rebalCheck();
}
function rebalCheck(){
  var box=document.getElementById('rebalBox'); if(!box) return;
  var C=window.CALC||{}, D=window.DET||{};
  var held=coreHeldTickers();
  if(!held.length){ box.innerHTML='<div class="mut" style="font-size:12px">建値を入れた保有銘柄が、ここに点検対象として表示されます。</div>'; return; }
  var floor=Number(C.floor_rs189);
  if(!(floor>0)){ box.innerHTML='<div class="neg" style="font-size:12px">継続順位データ不足（候補が2N未満）。自動の継続/売り判定を停止しました。</div>'; return; }
  var picks=(C.names||[]).map(function(n){return n.t;});
  var sell=[], hold=0;
  held.forEach(function(t){
    var d=D[t];
    if(!d){ sell.push({t:t,why:'データ無（ユニバース外）'}); return; }
    var okMA=!!d.ma5020, okRs=(d.rs189!=null&&d.rs189>=floor);
    if(okMA&&okRs){ hold++; return; }
    var why=[]; if(!okMA)why.push('50日線<200日線'); if(!okRs)why.push('RS<'+floor.toFixed(0));
    sell.push({t:t,why:why.join('・')});
  });
  var add=picks.filter(function(t){return held.indexOf(t)<0;});
  var _nqcol=(window.CALC&&window.CALC.color)||'';
  var _noEntry=(_nqcol==='Yellow'||_nqcol==='Red');
  var h='<div class="rc-h">継続OK '+hold+' ／ 売り候補 '+sell.length+' ／ 組み入れ候補 '+(_noEntry?'停止中':add.length)+'（継続床 RS≥'+floor.toFixed(0)+'）</div>';
  if(sell.length){
    h+='<div class="rc-sec"><div class="rc-l rc-sl">売り候補（継続条件を外れた保有）</div>'
      + sell.map(function(x){return '<div class="rc-row"><b>'+x.t+'</b><span class="mut">'+x.why+'</span></div>';}).join('')+'</div>';
  }
  if(_noEntry){
    h+='<div class="rc-sec"><div class="rc-l rc-ad">組み入れ（新規）</div>'
      + '<div class="rc-row"><span class="mut">NQ'+(_nqcol==='Yellow'?'黄':'赤')+'＝新規エントリー停止中。空き枠は現金で保持し、保有はピーク×0.70トレールのまま継続。青/緑に戻ってから組み入れる。</span></div></div>';
  } else if(add.length){
    h+='<div class="rc-sec"><div class="rc-l rc-ad">組み入れ候補（新トップ'+picks.length+'で未保有）</div>'
      + add.map(function(t){var d=D[t]||{};return '<div class="rc-row"><b>'+t+'</b><span class="mut">RS'+(d.rs189!=null?d.rs189:'—')+' / $'+(d.px!=null?d.px:'—')+'</span></div>';}).join('')+'</div>';
  }
  if(!sell.length&&!add.length&&!_noEntry){ h+='<div class="rc-okall">保有はすべて継続条件を満たし、新トップ'+picks.length+'と一致。入替なし。</div>'; }
  box.innerHTML=h;
}
function memExport(){ if(typeof hldExportJSON==='function'){ hldExportJSON(); return; } var s=JSON.stringify({entries:ccLoad(ccKey()),taken:takenLoad(),peak:ccLoad(ccPeakKey())}); try{window.prompt('保存用JSON（コピーして保管）',s);}catch(e){} }
function memImport(){ if(typeof hldImportJSON==='function'){ hldImportJSON(); return; } var s=null; try{s=window.prompt('JSONを貼り付け');}catch(e){} if(s){try{var o=JSON.parse(s); if(o.entries)ccSet(ccKey(),o.entries); if(o.taken)ccSet(ccTakenKey(),o.taken); if(o.peak)ccSet(ccPeakKey(),o.peak); calcRun();}catch(e){alert('JSONが不正です');}}}
if(document.readyState!=='loading'){ try{calcRun();}catch(e){} }
else { document.addEventListener('DOMContentLoaded',function(){ try{calcRun();}catch(e){} }); }

// --- エントリー済みトグル（指値運用の執行ズレを手動マーク・localStorage永続） ---
function _entKey(){ return 'v38_entered'; }
function _entLoad(){ try{ return JSON.parse(localStorage.getItem(_entKey())||'{}'); }catch(e){ return {}; } }
function _entSave(o){ try{ localStorage.setItem(_entKey(), JSON.stringify(o)); }catch(e){} }
function entToggle(ev, b){
  try{ ev.stopPropagation(); }catch(e){}
  var tk=b.getAttribute('data-tk'), sh=parseFloat(b.getAttribute('data-sh')); coreToggleFilled(tk,sh); _entApply();
  try{ if(typeof calcRun==='function') calcRun(); }catch(e){}
}
function _entApply(){
  document.querySelectorAll('.entb2').forEach(function(b){
    var tk=b.getAttribute('data-tk');
    if(coreFilled(tk)){ b.textContent='済'; b.classList.add('ent-on'); }
    else { b.textContent='未'; b.classList.remove('ent-on'); }
  });
}
if(document.readyState!=='loading'){ _entApply(); }
else { document.addEventListener('DOMContentLoaded',_entApply); }

// --- 個別ティッカーのコピー（リスト用copyTkとは別・イベント伝播を止める） ---
var _EN_MAP={
 "今日のマーケット":"Market Summary","マーケットステータス推移":"Regime History",
 "マーケット・パフォーマンス":"Performance","先導株モメンタム・ラン":"Leader Momentum",
 "リーダーの強さ":"Leader Temperature","セクター温度マップ":"Sector Heatmap",
 "セクターETF強弱":"Sector ETF Strength","レジーム警戒灯":"Regime Early-Warning",
 "リーダー・ブレッドス警戒灯":"Leader Breadth","転換初動リーダーボード":"Reversal Leaders",
 "フォロースルー・デイ":"Follow-Through Day","VIX期間構造（1M÷3M）":"VIX Term Structure",
 "センチメント（群衆温度計）":"Sentiment","エクイティカーブ×21EMA":"Equity Curve",
 "金利":"Yields","広域ブレッドス":"Market Breadth","データ品質":"Data Quality",
 "指数の200日線乖離":"Index vs 200DMA","前回からの変化":"Change Log",
 "圧縮コイル（VCP）ウォッチ":"VCP Watch","テクニカル・パターン別":"Chart Patterns",
 "本日のピックアップ":"Todays Setups","リーダー監視":"Leaders","銘柄検索":"Ticker Search",
 "コンフルエンス・ボード":"Confluence Board","ポケットピボット（10D）":"Pocket Pivots (10D)","新規参入":"New Entrants",
 "業種ローテ（定点観測）":"Sector Rotation","強い業種の主導株":"Leaders in Strong Groups",
 "テーマ・ドリルダウン":"Theme Drilldown","マーケット感応度（β vs QQQ）":"Beta vs QQQ",
 "システムルール（v2・確定）":"System Rules","資金配分・株数計算":"Position Sizing",
 "エクイティ記録":"Equity Log","隔週リバランス点検（月曜）":"Rebalance Check",
 "順位落ち保有（出口監視）":"Demoted Holdings","RSリーダー控え":"Bench",
 "本日の新高値圏":"New Highs","本日の押し目シグナル":"Pullback Signals",
 "テンバガー・レーダー":"Moonshot Radar","押し目質スクリーナー":"Pullback Quality",
 "オプション想定変動幅":"Expected Move","クレジット推移":"Credit Spread",
 "サブテーマ別RS":"Sub-Theme RS","スイング・プランナー":"Trade Planner",
 "テーマ・ローテーション":"Theme Rotation (RRG)","ディストリビューション・デイ":"Distribution Days",
 "ブレッドス推移":"Breadth Trend","ポートフォリオ":"Portfolio",
 "レバレッジ・コンディション":"Leverage Conditions","売買代金 参加度":"Volume Participation",
 "広がりの勢い":"McClellan Oscillator","攻守ローテーション":"Risk-On/Off Rotation",
 "集積／分散":"Accumulation/Distribution","ポジション・サイザー":"Position Sizer",
 "本日の新高値圏":"New Highs","本日の押し目シグナル":"Pullback Signals",
 "指数の200日線乖離":"Index vs 200DMA","テーマ・ドリルダウン":"Theme Drilldown",
 "マーケット感応度":"Beta vs QQQ","業種ローテ":"Sector Rotation"
};
function enLabels(){
  try{
    document.querySelectorAll(".card h2").forEach(function(h){
      if(h.querySelector(".h2en")) return;
      var base=h.childNodes[0] && h.childNodes[0].nodeType===3 ? h.childNodes[0].textContent.trim() : h.textContent.trim();
      for(var k in _EN_MAP){
        if(base.indexOf(k)===0){
          var sp=document.createElement("span"); sp.className="h2en"; sp.textContent=_EN_MAP[k];
          h.appendChild(sp); break;
        }
      }
    });
  }catch(e){}
}
if(document.readyState!=="loading"){ enLabels(); } else { document.addEventListener("DOMContentLoaded",enLabels); }
function rrgDesc(el){
  try{
    var d=el.closest(".card").querySelector(".rrg-desc");
    if(!d) return;
    var open=d.style.display==="none";
    d.style.display=open?"block":"none";
    el.textContent=open?"▾ 折りたたむ":"▸ 詳しく";
  }catch(e){}
}
function rrgPer(b, pk){
  try{
    var card=b.closest(".card");
    card.querySelectorAll(".rrgtog .rtg").forEach(function(x){ x.classList.remove("on"); });
    b.classList.add("on");
    card.querySelectorAll(".rrg-per").forEach(function(v){
      v.style.display = (v.getAttribute("data-per")===pk) ? "" : "none";
    });
  }catch(e){}
}
function regTog(hd){
  try{
    var card=hd.closest(".reg-card"); card.classList.toggle("folded");
    var t=hd.querySelector(".reg-tog");
    if(t){ t.textContent = card.classList.contains("folded") ? "タップで開く ▸" : "タップで閉じる ▾"; }
  }catch(e){}
}
function msecTog(el){
  try{
    el.classList.toggle("open");
    var m=el.querySelector(".msec-more");
    if(m){ m.textContent = el.classList.contains("open") ? "▾ 折りたたむ" : "▸ 詳しく"; }
  }catch(e){}
}
function hmPer(b, p){
  var card = b.closest('.card');
  card.querySelectorAll('.hmp').forEach(function(x){ x.classList.remove('on'); });
  b.classList.add('on');
  card.querySelector('.hmg-d').style.display = (p==='d')?'':'none';
  card.querySelector('.hmg-w').style.display = (p==='w')?'':'none';
  card.querySelector('.hmg-m').style.display = (p==='m')?'':'none';
}
function copyOne(ev, tk){
  try{ ev.stopPropagation(); }catch(e){}
  var b=ev.currentTarget || ev.target;
  _copyText(tk, function(){
    if(b){ b.classList.add('cp-done'); var o=b.innerHTML; b.innerHTML='✓';
           setTimeout(function(){ b.innerHTML=o; b.classList.remove('cp-done'); }, 900); }
  });
}

// --- エッジ秘匿: 算出方法/検証値の詳細のみ「算出方法 ▸」に折りたたむ。
//     カードが何を示すか(.sub)と結論値・基準は常時表示。式や検証数値(.note/.lbnote)だけ隠す。 ---
function foldCalc(){
  try{
    var sels=['.note','.lbnote','.note.rk-note'];
    document.querySelectorAll(sels.join(',')).forEach(function(el){
      if(el.closest('details')) return;
      if(el.getAttribute('data-fold')==='0') return;
      var d=document.createElement('details'); d.className='calcfold';
      var s=document.createElement('summary'); s.className='calcsum'; s.textContent='算出方法・根拠';
      el.parentNode.insertBefore(d,el); d.appendChild(s); d.appendChild(el);
    });
  }catch(e){}
}
if(document.readyState!=='loading'){ foldCalc(); }
else { document.addEventListener('DOMContentLoaded',foldCalc); }

// --- ローテーション時間軸テーブルの列ソート ---
var _rotDir={};
function rotSort(key,th){
  try{
    var tbl=document.getElementById('rottbl'); if(!tbl) return;
    var rows=Array.prototype.slice.call(tbl.querySelectorAll('tr')).filter(function(r){return r.querySelector('td');});
    var asc=(key==='rot'); // 状態は初動が上(昇順)、他は強い順(降順)
    if(_rotDir[key]!==undefined) asc=_rotDir[key];
    rows.sort(function(a,b){
      var va=parseFloat(a.getAttribute('data-'+key)), vb=parseFloat(b.getAttribute('data-'+key));
      if(isNaN(va))va=-1e9; if(isNaN(vb))vb=-1e9;
      return asc?(va-vb):(vb-va);
    });
    _rotDir[key]=!asc;
    var parent=rows[0].parentNode;
    rows.forEach(function(r){parent.appendChild(r);});
    tbl.querySelectorAll('th.rsort').forEach(function(h){h.classList.remove('act');});
    if(th) th.classList.add('act');
  }catch(e){}
}



"""

def _cp(tickers):
    """Copy button for a list of tickers (comma-separated to clipboard)."""
    if not tickers:
        return ""
    data = ",".join(tickers)
    return (f'<button class="cp" data-tk="{data}" onclick="copyTk(event,this)">'
            f'コピー <span class="n">{len(tickers)}</span></button>')

def _build_det_extra(m, s2t, s2i, e2j, picks, deck, buys, nh_list, where, hold=None):
    """タップ詳細用の集約：セクター/サブテーマ/時価総額/登場箇所（保有・控え・ピックアップ・新高値・ウォッチ）。"""
    loc = {}
    def add(t, lab):
        if t:
            loc.setdefault(t, []).append(lab)
    for i, (t, _, _) in enumerate(picks, 1):
        add(t, f"Core 12 #{i}")
    try:
        for rk, t in enumerate(list(deck.index), N_PORT + 1):
            add(t, f"控え #{rk}")
    except Exception:
        pass
    for b in buys:
        add(b.get("t"), "ピックアップ")
    for t in nh_list:
        add(t, "新高値圏")
    for t, nm in (where or {}).items():
        add(t, "ウォッチ:" + "・".join(nm))
    caps = m["tier_lab"].to_dict() if "tier_lab" in m.columns else {}
    hold = hold or {}
    def _since(t):
        h = hold.get(t) or {}
        ed = h.get("ed")
        if not ed:
            return None
        try:
            dd = _session_days(ed)                   # #8 壁時計でなく分析基準日までの実取引セッション数
            return {"d": str(ed), "n": dd}
        except Exception:
            return {"d": str(ed), "n": None}
    extra = {}
    for t in m.index:
        _hh = hold.get(t) or {}
        try:
            _hep = float(_hh["ep"]) if _hh.get("ep") is not None else None
        except Exception:
            _hep = None
        extra[t] = {"sec": _h(theme_of(t, s2t)),
                    "sth": _h(subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))),
                    "cap": caps.get(t),
                    "loc": [_h(x) for x in (loc.get(t, []) or [])],
                    "since": _since(t),
                    "hep": _hep}
    return extra

def _det_json(m, names, tapset, extra=None):
    """§4: compact per-ticker data for the tap-to-detail panel (displayed tickers only)."""
    import json as _json
    extra = extra or {}
    def _r(x, n=2):
        try:
            if x is None or (isinstance(x, float) and np.isnan(x)):
                return None
            return round(float(x), n)
        except Exception:
            return None
    def _p(r, k, n=1):  # percent field
        v = r.get(k)
        return _r(v * 100, n) if v is not None and pd.notna(v) else None
    out = {}
    for t in sorted(tapset):        # #13 set反復順はPYTHONHASHSEED依存→sortedで決定的に
        if t not in m.index:
            continue
        r = m.loc[t]
        is_l, code, lab, reason = leader_state(r)
        nu_tag, nu_note, nu_cls = momentum_nuance(r)
        ex = extra.get(t, {})
        _r5v = r.get("ret5"); _r5v = float(_r5v) if (_r5v is not None and _r5v == _r5v) else None
        _dropv = bool(r.get("lo20_break")) or (_r5v is not None and _r5v <= -0.15)
        _clxv = 2 if (_dropv and bool(r.get("capit5"))) else (1 if _dropv else 0)
        out[t] = {"rs": _r(r.get("rs"), 0), "rs189": _r(r.get("rs189"), 0),
                  "rs21": _r(r.get("rs21"), 0),
                  "e21l": _r(r.get("ema21l"), 2), "s10": _r(r.get("sma10"), 2),
                  "clx": _clxv, "hep": ex.get("hep"),
                  "px": _r(r.get("close"), 2), "ch": _p(r, "pchg", 2),
                  "v50": _p(r, "vs50"), "v200": _p(r, "vs200"), "d21": _p(r, "dma21"),
                  "adr": _p(r, "adr"), "rv": _r(r.get("rvol_pre"), 1), "pb": _p(r, "pb"),
                  "p52": _r(r.get("pos52"), 0), "d52": _p(r, "dist52"),
                  "dvol": _r((r.get("dvol") or 0) / 1e6, 1),
                  "pivot": _r(r.get("pivot40"), 2), "pdist": _p(r, "pivot_dist", 1),
                  "vcpq": _r(r.get("vcp_score"), 0), "contract": _r(r.get("contractions"), 0),
                  "hl": 1 if r.get("higher_lows") else 0, "rsline": 1 if r.get("rsline_newhigh") else 0,
                  "vdry": _r(r.get("vdry_pre"), 2),
                  "truebr": 1 if r.get("true_breakout") else 0,
                  "cup": 1 if (r.get("cup_ready") or r.get("cup_breakout")) else 0,
                  "turn": 1 if r.get("trend_change") else 0,
                  "p204": 1 if r.get("power20_4") else 0,
                  "sec": ex.get("sec"), "sth": ex.get("sth"),
                  "cap": ex.get("cap"), "loc": ex.get("loc") or [], "since": ex.get("since"),
                  "ld": 1 if is_l else 0, "stc": code, "stl": lab, "rsn": reason,
                  "beta": _r(r.get("beta"), 2),
                  "ma5020": 1 if (r.get("sma50") is not None and r.get("sma200") is not None
                                  and r["sma50"] == r["sma50"] and r["sma200"] == r["sma200"]
                                  and r["sma50"] > r["sma200"]) else 0,
                  "sarb": 1 if r.get("sar_bull") else 0,
                  "wst": (int(r["wst"]) if pd.notna(r.get("wst")) else None),
                  "wstw": (int(r["wstw"]) if pd.notna(r.get("wstw")) else None),
                  "wsb": (int(r["wsb"]) if pd.notna(r.get("wsb")) else None),
                  "wsbf": (int(r["wsbf"]) if pd.notna(r.get("wsbf")) else 0),
                  "nut": nu_tag, "nucls": nu_cls,
                  "flags": [{"type": _h(f.get("type", "")), "sev": f.get("sev"), "note": _h(f.get("note", ""))}
                            for f in risk_flags_for(t, r.get("close"))]}   # #1 外部note/typeをエスケープ（JS innerHTML XSS対策）
    return _json.dumps(out, ensure_ascii=False, separators=(",", ":"))

def color_pct(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return "mut"
    return "pos" if x > 0 else ("neg" if x < 0 else "mut")

def _svg_inner(ys, accent, gid, gridvals, suffix, lo_pad=4, hi_pad=4, ymin=0, ymax=100, zero_ref=False):
    """Return inner SVG (area+line) for a value series. zero_ref=Trueで y=0 に破線基準。"""
    n = len(ys)
    Wd, Ht, pad = 680, 180, 6
    lo, hi = min(ys), max(ys)
    lo = max(ymin, lo - lo_pad); hi = min(ymax, hi + hi_pad)
    rng = (hi - lo) or 1
    def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo)/rng) * (Ht - 2*pad)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    area = (f"M{X(0):.1f},{Y(ys[0]):.1f} "
            + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
            + f" L{X(n-1):.1f},{Ht-pad:.1f} L{X(0):.1f},{Ht-pad:.1f} Z")
    gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" '
                 f'stroke="#1c2533" stroke-width="1"/>'
                 f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" '
                 f'text-anchor="end">{g}{suffix}</text>'
                 for g in gridvals if lo <= g <= hi)
    zr = ""
    if zero_ref and lo <= 0 <= hi:
        zr = (f'<line x1="{pad}" y1="{Y(0):.1f}" x2="{Wd-pad}" y2="{Y(0):.1f}" '
              f'stroke="#3b4b63" stroke-width="1" stroke-dasharray="4 3"/>')
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{accent}" stop-opacity="0.35"/>'
            f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/></linearGradient></defs>'
            f'{gl}{zr}<path d="{area}" fill="url(#{gid})"/>'
            f'<polyline points="{pts}" fill="none" stroke="{accent}" stroke-width="2"/>'
            f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="{accent}"/></svg>')

def _date_axis(ts):
    """チャート下端に半年ごとの日付ラベル（yy/m）を等間隔で並べる。"""
    if not ts or len(ts) < 2:
        return ""
    seen, labs = set(), []
    for d, _ in ts:
        dt = pd.Timestamp(d)
        h = 1 if dt.month <= 6 else 7
        key = (dt.year, h)
        if key not in seen:
            seen.add(key)
            labs.append(f'<span>{dt.year % 100}/{h}</span>')
    if len(labs) < 2:
        labs = [f'<span>{pd.Timestamp(ts[0][0]).strftime("%y/%-m")}</span>',
                f'<span>{pd.Timestamp(ts[-1][0]).strftime("%y/%-m")}</span>']
    return '<div class="dax">' + "".join(labs) + '</div>'

def _span_label(ts):
    """推移データの実期間を'○年○ヶ月'で返す（表記と実データのズレ防止）。"""
    if not ts or len(ts) < 2:
        return "—"
    try:
        d0 = pd.Timestamp(ts[0][0]); d1 = pd.Timestamp(ts[-1][0])
        months = round((d1 - d0).days / 30.44)
        yy = months // 12; mm = months % 12
        if yy and mm: return f"{yy}年{mm}ヶ月"
        if yy: return f"{yy}年"
        return f"{mm}ヶ月"
    except Exception:
        return "—"

def _expl(text):
    """推移チャートの読み方を折りたたみ表示（既定は閉じる）。冗長な解説で画面を占有しない。"""
    if not text:
        return ""
    return (f'<details class="cxpl" open><summary>読み方</summary>'
            f'<div class="cxpl-b">{text}</div></details>')


def _svg_breadth(ts, n_uni=None):
    """Breadth time series (S5TH analog)."""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    svg = _svg_inner(ys, "#58a6ff", "bg", [20,40,50,60,80], "%")
    uni_txt = f"約{round(n_uni,-1):,.0f}銘柄" if n_uni else "ユニバース"
    return (f'<div class="card"><div class="chd"><h2>ブレッドス推移（200日線上の割合）</h2><div class="chd-now" style="color:#9ecbff"><b>{last:.0f}%</b><span>200日線上</span></div></div>'
            f'<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">200日線を上回る銘柄の割合（{uni_txt}・{_span_label(ts)}）</div></details>'
            f'<div class="chart">{svg}'
            f'{_date_axis(ts)}</div></div>')

def _fmt_usd_big(v):
    v = float(v)
    if v >= 1e12: return f"${v/1e12:.2f}T"
    if v >= 1e9:  return f"${v/1e9:.0f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"

def _dollarvol_card(dv):
    """売買代金 参加度: ユニバース合算/QQQ/SPY を各自の200日平均比（1.0=平常）で重ねた足元感応チャート。"""
    if not dv or not dv.get("series"):
        return ""
    dates = dv["dates"]; n = len(dates)
    if n < 5:
        return ""
    allv = [y for s in dv["series"] for y in s["ys"] if y is not None]
    if len(allv) < 5:
        return ""
    lo, hi = min(allv), max(allv); lo = min(lo, 0.9); hi = max(hi, 1.1); rng = (hi - lo) or 1
    lo2, hi2 = lo - rng * 0.08, hi + rng * 0.08; rng2 = (hi2 - lo2) or 1
    Wd, Ht, pad = 680, 180, 6
    def X(i): return pad + i * (Wd - 2 * pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo2) / rng2) * (Ht - 2 * pad)
    gl = ""
    for g in (0.8, 1.0, 1.2, 1.4):
        if not (lo2 <= g <= hi2):
            continue
        is1 = abs(g - 1.0) < 1e-9
        stroke = "#33415a" if is1 else "#1c2533"
        dash = ' stroke-dasharray="3 3"' if is1 else ""
        gl += (f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" '
               f'stroke="{stroke}" stroke-width="1"{dash}/>'
               f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" '
               f'font-weight="600" text-anchor="end">{g:.1f}</text>')
    lines = ""
    for s in dv["series"]:
        ys = s["ys"]
        seg = [(i, v) for i, v in enumerate(ys) if v is not None]
        if len(seg) < 2:
            continue
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in seg)
        wdt = 2.4 if s["name"] == "ユニバース合算" else 1.6
        lines += f'<polyline points="{pts}" fill="none" stroke="{s["color"]}" stroke-width="{wdt}"/>'
        li, lv = seg[-1]
        lines += f'<circle cx="{X(li):.1f}" cy="{Y(lv):.1f}" r="3" fill="{s["color"]}"/>'
    svg = f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">{gl}{lines}</svg>'
    legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
        f'<span style="width:10px;height:3px;background:{s["color"]};display:inline-block;border-radius:2px"></span>'
        f'<span style="color:#c7d2fe;font-size:11px">{s["name"]}</span></span>' for s in dv["series"])
    uni = next((s for s in dv["series"] if s["name"] == "ユニバース合算"), dv["series"][0])
    ut = dv.get("uni_trend") or {}
    tcol = "#7ff0a8" if ut.get("dir") == "拡大" else "#fca5a5" if ut.get("dir") == "縮小" else "#9fb0c5"
    tclause = (f'・<b style="color:{tcol}">{ut["dir"]}</b>（3ヶ月{ut["pct"]:+.0f}%）' if ut else "")
    ur = uni.get("last_ratio")
    urtxt = f'参加度 {ur:.2f}倍' if (ur is not None and ur == ur) else "—"
    _dv_now = (f'<div class="chd-now" style="color:{tcol}"><b>{ur:.2f}<span style="font-size:11px">倍</span></b><span>参加度</span></div>'
               if (ur is not None and ur == ur) else "")
    return (f'<div class="card"><div class="chd"><h2>売買代金 参加度（200日平均比）</h2>{_dv_now}</div>'
            f'<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">売買代金（終値×出来高・21日平滑）÷各自の200日平均・{dv["span"]}。1.0=平常／超=資金厚い／割れ=細り<span style="margin-left:6px">{legend}</span></div></details>'
            f'<div class="chart">{svg}'
            f'<div class="cap cap-c"><span style="color:#7dd3fc;font-weight:700">'
            f'現在 {_fmt_usd_big(uni["last_abs"])}（20日前比 {uni["chg20"]:+.0f}%）{tclause}</span></div>'
            f'{_date_axis([(d, 0.0) for d in dates])}</div></div>')

def _trend_state(ys, up_label, dn_label, win=50, slope_lb=10):
    """系列自身のトレンドでラベル：50日平均より上か下か＋平均の向き。
       リベース/累積系列のように『自然な原点』が無い系列は基準日を借りず必ずこれで判定。"""
    s = pd.Series(ys)
    if len(s) < win + slope_lb:
        return ("中立", "#9aa4b2")
    ma = s.rolling(win).mean()
    above = s.iloc[-1] > ma.iloc[-1]
    slope = ma.iloc[-1] - ma.iloc[-1 - slope_lb]
    if above and slope >= 0:
        return (up_label, "#7ff0a8")
    if (not above) and slope < 0:
        return (dn_label, "#fca5a5")
    return ("中立", "#9aa4b2")

def _svg_ratio_card(ts, title, sub, up_label, dn_label, accent, gid, show_value=True,
                    zero_ref=False, unit=""):
    """推移カード。zero_ref=Trueで0基準線＋σ表示（z-score系列用）。ラベルは系列自身のトレンドで判定。"""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    lo, hi = min(ys), max(ys)
    pad = max(0.4, (hi - lo) * 0.12)
    grid = sorted(set(round(x, 1) for x in ([lo, 0.0, hi] if zero_ref else [lo, (lo + hi) / 2, hi])))
    svg = _svg_inner(ys, accent, gid, grid, "", lo_pad=pad, hi_pad=pad, ymin=-1e9, ymax=1e9,
                     zero_ref=zero_ref)
    state, col = _trend_state(ys, up_label, dn_label)
    _v = (f'{last:+.1f}{unit}' if zero_ref else f'{last:.1f}')
    _now = (f'<div class="chd-now" style="color:{col}"><b>{_v}</b><span>{state}</span></div>'
            if show_value else f'<div class="chd-now" style="color:{col}"><b>{state}</b></div>')
    return (f'<div class="card"><div class="chd"><h2>{title}</h2>{_now}</div>'
            f'<div class="chart">{svg}'
            f'{_date_axis(ts)}</div>{_expl(sub)}</div>')

def _svg_vixterm_card(ts):
    """B-4a: VIX期間構造(1M÷3M)の推移・生比率。1.0=バックワーデーション線（構造的原点ありで水準ラベル可）。"""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    dlo, dhi = min(ys), max(ys)
    # 1.0基準線が常に見えるよう上端を≥1.02に（_svg_innerのpadで調整）
    svg = _svg_inner(ys, "#c4b5fd", "vt", [0.90, 0.95, 1.00, 1.05], "",
                     lo_pad=0.03, hi_pad=max(0.03, 1.02 - dhi), ymin=0, ymax=100)
    if last < 0.95:
        state, col = "コンタンゴ（平穏）", "#7ff0a8"
    elif last <= 1.00:
        state, col = "フラット（要観察）", "#fcd34d"
    else:
        state, col = "バックワーデーション（ストレス）", "#fca5a5"
    return (f'<div class="card"><div class="chd"><h2>VIX期間構造（1M÷3M）</h2><div class="chd-now" style="color:{col}"><b>{last:.2f}</b><span>{state}</span></div></div>'
            f'<div class="sub">VIX 1カ月物 ÷ 3カ月物（1.0超でカーブ逆転）</div>'
            f'<div class="chart">{svg}'
            f'{_date_axis(ts)}</div></div>')

def _mkt_section(label, q, guide=None, en=None):
    """マーケットタブのストーリー章ヘッダ（章タイトル＋一言＋タップで詳細解説を開閉）。"""
    e = f'<span class="msec-en">{en}</span>' if en else ""
    if guide:
        g = (f'<div class="msec-q">{q} <span class="msec-more">▾ 折りたたむ</span></div>'
             f'<div class="msec-g">{guide}</div>')
        return (f'<div class="msec msec-x open" onclick="msecTog(this)"><div class="msec-l">{label}{e}</div>{g}</div>')
    return (f'<div class="msec"><div class="msec-l">{label}{e}</div>'
            + (f'<div class="msec-q">{q}</div>' if q else "") + "</div>")

def _svg_mri(ts):
    """Market-status time series, ~6 months, with regime-zone shading (帯域塗り)."""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    hl = sum(ys[-3:]) / 3 if len(ys) >= 3 else last
    band_lab = mri_band(hl)[0].replace("（過熱・反落注意⚠）", "")
    # zone-shaded custom svg (same geometry as _svg_inner)
    n = len(ys); Wd, Ht, pad = 680, 180, 6
    lo, hi = min(ys), max(ys)
    lo = max(0, lo - 4); hi = min(100, hi + 4)
    rng = (hi - lo) or 1
    def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo)/rng) * (Ht - 2*pad)
    zones = [(0, 25, "#ef4444"), (25, 40, "#f97316"), (40, 55, "#64748b"),
             (55, 70, "#22c55e"), (70, 100, "#16a34a")]
    zr = ""
    for z0, z1, zc in zones:
        a, b = max(z0, lo), min(z1, hi)
        if b <= a:
            continue
        zr += (f'<rect x="{pad}" y="{Y(b):.1f}" width="{Wd-2*pad}" '
               f'height="{max(0.0, Y(a)-Y(b)):.1f}" fill="{zc}" opacity="0.07"/>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="#1c2533" stroke-width="1"/>' 
                 f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g}</text>'
                 for g in (25, 40, 55, 70) if lo <= g <= hi)
    svg = (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
           f'<defs><linearGradient id="mg" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="#34d399" stop-opacity="0.30"/>'
           f'<stop offset="1" stop-color="#34d399" stop-opacity="0"/></linearGradient></defs>'
           f'{zr}{gl}'
           f'<polyline points="{pts}" fill="none" stroke="#34d399" stroke-width="2"/>'
           f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="#34d399"/></svg>')
    return (f'<div class="card"><div class="chd"><h2>マーケットステータス推移</h2><div class="chd-now" style="color:#7ff0a8"><b>{last:.0f}</b><span>{band_lab}</span></div></div>'
            f'<details class="cxpl" open><summary>読み方</summary><div class="cxpl-b">地合いスコアの推移・{_span_label(ts)}（70強気/55やや強気/40中立/25弱含み）</div></details>'
            f'<div class="chart">{svg}'
            f'{_date_axis(ts)}</div></div>')

def _sec_rows(recs, tf, topbottom=False):
    rs = [x for x in recs if x.get(tf) is not None and not (isinstance(x[tf], float) and np.isnan(x[tf]))]
    rs.sort(key=lambda x: x[tf], reverse=True)
    def row(i, s):
        cells = ""
        for k in ("d1", "w1", "m1"):
            hl = " hl" if k == tf else ""
            cells += f'<td class="{color_pct(s[k])}{hl}">{fmt_pct(s[k])}</td>'
        return (f'<tr><td class="l mut">{i}</td>'
                f'<td class="l tk" style="font-size:12px">{_h(s["ja"])}'
                f'<span class="mut" style="font-size:10px"> {s["tk"]}</span></td>{cells}</tr>')
    if topbottom and len(rs) > 10:
        top, bot = rs[:5], rs[-5:]
        h = lambda lab: f'<tr class="secsub"><td colspan="5" class="l">{lab}</td></tr>'
        return (h("強い") + "".join(row(i + 1, s) for i, s in enumerate(top))
                + h("弱い") + "".join(row(len(rs) - 4 + i, s) for i, s in enumerate(bot)))
    return "".join(row(i + 1, s) for i, s in enumerate(rs))

def _rotation_card(sectors, m):
    """ローテーション時間軸: どの詳細サブテーマに資金が来ているか（短期1wk・中期1mo・長期RS）。
       初動（短期加速×広がり×非集中）を先頭に。まだ追っても遅くないテーマを上に。"""
    if not sectors:
        return ""
    order = {"初動": 0, "改善": 1, "強い継続": 2, "監視": 3, "弱い": 4}
    ranked = sorted(sectors, key=lambda s: (order.get(s.get("rot", "弱い"), 4), -s.get("d_w1", 0)))
    scol = {"初動": "#4ade80", "改善": "#7dd3fc", "強い継続": "#a78bfa", "監視": "#9fb0c5", "弱い": "#6b7280"}
    def arr(v):
        if v >= 4: return f'<span class="pos">▲{v:+.0f}</span>'
        if v <= -4: return f'<span class="neg">▼{v:+.0f}</span>'
        return f'<span class="mut">{v:+.0f}</span>'
    rows = ""
    for s in ranked[:12]:
        rot = s.get("rot", "弱い"); col = scol.get(rot, "#9fb0c5")
        leads = []
        for t, _ in (s.get("members") or []):
            if t in m.index and (m.at[t, "rs189"] == m.at[t, "rs189"]) and m.at[t, "rs189"] >= 80:
                leads.append(t)
            if len(leads) >= 2:
                break
        lead_html = "".join(f'<span class="chip hot" data-liq="{(m.at[t,"dvol"] or 0)/1e6:.1f}" data-tkone="{t}">{t}</span>' for t in leads) or '<span class="mut">—</span>'
        conc = '<span class="mut" title="上位1-2銘柄依存＝単独材料株寄り"> 集中</span>' if s.get("top2", 0) >= 0.70 else ""
        _ord = order.get(rot, 4)
        rows += (f'<tr data-tkone="{leads[0] if leads else ""}" '
                 f'data-rot="{_ord}" data-w1="{s.get("d_w1",0):.1f}" data-m1="{s.get("d_m1",0):.1f}" '
                 f'data-l189="{s.get("med189",0):.1f}" data-brd="{s.get("breadth21",0)*100:.1f}">'
                 f'<td class="l"><b>{_h(s["ja"])}</b>{conc}<div class="mut" style="font-size:10px">{_h(s.get("parent","—"))}</div></td>'
                 f'<td><span class="rotb" style="color:{col};border-color:{col}66">{rot}</span></td>'
                 f'<td>{arr(s.get("d_w1",0))}</td><td>{arr(s.get("d_m1",0))}</td>'
                 f'<td>{s.get("med189",0):.0f}</td>'
                 f'<td>{s.get("breadth21",0)*100:.0f}%</td>'
                 f'<td class="l">{lead_html}</td></tr>')
    return (f'<div class="card"><h2>ローテーション時間軸（どこに資金が来ているか）</h2>'
            f'<div class="sub"><b>初動</b>（短期加速×広がり×非集中）を上に＝まだ追っても遅くないテーマ。'
            f'短期＝1週・中期＝1ヶ月のRS順位変化、長期＝189日RS中央値、広がり＝21EMA上の銘柄比率。行タップで主導株の詳細。</div>'
            f'<table class="rottbl" id="rottbl"><tr><th class="l">サブテーマ</th>'
            f'<th class="rsort act" onclick="rotSort(\'rot\',this)">状態</th>'
            f'<th class="rsort" onclick="rotSort(\'w1\',this)">短期</th>'
            f'<th class="rsort" onclick="rotSort(\'m1\',this)">中期</th>'
            f'<th class="rsort" onclick="rotSort(\'l189\',this)">長期</th>'
            f'<th class="rsort" onclick="rotSort(\'brd\',this)">広がり</th>'
            f'<th class="l">主導株</th></tr>{rows}</table></div>')


def _sector_rank_card(ranks):
    if not ranks or not (ranks.get("macro") or ranks.get("micro")):
        return ""
    tbls = ""
    for grp in ("macro", "micro"):
        recs = ranks.get(grp, [])
        tb = (grp == "micro")
        for tf in ("d1", "w1", "m1"):
            disp = "" if (grp == "macro" and tf == "d1") else "display:none"
            head = ('<table><tr><th class="l">#</th><th class="l">セクター</th>'
                    '<th>日</th><th>週</th><th>月</th></tr>')
            tbls += (f'<div class="sectbl" id="sec-{grp}-{tf}" style="{disp}">'
                     f'{head}{_sec_rows(recs, tf, tb)}</table></div>')
    return (f'<div class="card"><h2>セクターETF強弱</h2>'
            f'<div class="sub">S&amp;P500の11セクターETFと業種テーマETFの騰落率（下のサブテーマ別RSは個別株のRS中央値・別物）</div>'
            f'<div class="sectog">'
            f'<button class="stg-g active" onclick="secG(\'macro\',this)">大分類</button>'
            f'<button class="stg-g" onclick="secG(\'micro\',this)">小分類</button>'
            f'<span class="stg-sep">|</span>'
            f'<button class="stg-t active" onclick="secT(\'d1\',this)">日</button>'
            f'<button class="stg-t" onclick="secT(\'w1\',this)">週</button>'
            f'<button class="stg-t" onclick="secT(\'m1\',this)">月</button>'
            f'</div>{tbls}</div>'
            f'<script>var _sg="macro",_st="d1";'
            f'function _secShow(){{document.querySelectorAll(".sectbl").forEach(function(e){{e.style.display="none"}});'
            f'var el=document.getElementById("sec-"+_sg+"-"+_st);if(el)el.style.display="";}}'
            f'function secG(g,b){{_sg=g;document.querySelectorAll(".stg-g").forEach(function(e){{e.classList.remove("active")}});b.classList.add("active");_secShow();}}'
            f'function secT(t,b){{_st=t;document.querySelectorAll(".stg-t").forEach(function(e){{e.classList.remove("active")}});b.classList.add("active");_secShow();}}</script>')

def _liq_bar():
    """Slim sticky liquidity (avg daily $ volume) filter toolbar — works in any tab via liqFilter()."""
    return (
        '<div class="card liqstick"><div class="liqrow">'
        '<span class="liqlab">流動性<span class="liqsub">日次$出来高</span></span>'
        '<button class="lqf-b" onclick="liqFilter(-1,this)">全て</button>'
        '<button class="lqf-b lqf-rec active" onclick="liqFilter(10,this)">≥$10M<span class="lqf-tag">推奨</span></button>'
        '<button class="lqf-b" onclick="liqFilter(20,this)">≥$20M</button>'
        '<button class="lqf-b" onclick="liqFilter(50,this)">≥$50M</button>'
        '</div></div>')

def gate_coeffs(color):
    """NQ4色 → (E_ind, E_lev)。個別 青100/緑100/黄=保有100%継続だが新規停止(トレール0.70のまま変更なし)/赤0、レバ 青100/緑50/黄0/赤0。
       不明/無判定は安全側で(0,0)＝赤扱い。"""
    return {"Blue": (1.0, 1.0), "Green": (1.0, 0.5),
            "Yellow": (1.0, 0.0), "Red": (0.0, 0.0)}.get(color, (0.0, 0.0))

def _sleeve_mult(p, n):
    """前回露出p→今回露出n の月中アクションを倍率で表現。建値は価格でlocalStorage保持なので
       株数を増減してもストップ/トレール表示は崩れない。0から増やす時だけ絶対株数が必要。"""
    if n <= 0:
        return "全部売り" if p > 0 else "なし"
    if p <= 0:
        return "Positionsの株数で新規"
    r = n / p
    if abs(r - 1) < 1e-6:
        return "変更なし"
    if abs(r - 0.5) < 1e-6:
        return "半分売り（×0.5）"
    if abs(r - 2) < 1e-6:
        return "倍に買い増し（×2）"
    return f"×{r:.2g}"

def _data_health_banner(mkt):
    """日次で確認する指標の取得失敗を検知し、ページ最上部に警告を出す。
       取得できなかった指標は各所で「—」表示にする方針の補助（固定値・古い値を出さない）。"""
    try:
        fails = []
        mc = mkt.get("fred_all") or {}   # カード・OVと同じ全系列ソースで判定（誤検知を防ぐ）
        _fred_chk = [("DGS2", "米2年金利"), ("DFII10", "10年実質金利"), ("T10YIE", "期待インフレ"),
                     ("T10Y2Y", "イールドカーブ"), ("BAMLH0A0HYM2", "HY OAS"), ("BAMLC0A0CM", "IG OAS"),
                     ("NFCI", "金融環境"), ("DTWEXBGS", "広義ドル")]
        for sid, lab in _fred_chk:
            d = mc.get(sid) or {}
            if not (d.get("vals") or []):
                fails.append(lab)
        if not (mkt.get("senti") or {}):
            fails.append("センチメント(F&G)")
        if not mkt.get("net_liq"):
            fails.append("ネット流動性")
        if not fails:
            return ""
        uniq = list(dict.fromkeys(fails))
        shown = "・".join(uniq[:10]) + ("　ほか" if len(uniq) > 10 else "")
        return (f'<div class="dhbanner">⚠ <b>本日取得できなかった指標があります</b>'
                f'（該当箇所は「—」表示・古い固定値は出しません）：{shown}。'
                f'FRED／データ提供元の一時的な障害の可能性で、次回ビルドで自動復帰します。</div>')
    except Exception:
        return ""


def build_today_action(sar, mkt, asof):
    """最上部の『今日の運用』。色→露出→今日の引き金（赤明け>色変化>通常）＋隔週月曜リバランス旗。"""
    color, src = sar
    prev = mkt.get("trend_prev")
    e_ind, e_lev = gate_coeffs(color)
    _em = mkt.get("emergency") or {}
    _em_mult = float(_em.get("mult", 1.0) or 1.0)
    e_lev *= _em_mult
    cj = _COLOR_JP.get(color, "—")
    ccls = (color or "gray").lower()

    # 露出文言
    if color is None:
        expo = "NQ未取得 → 安全側で露出0%。TradingViewで確認を"
    elif color == "Red":
        expo = "個別 0% ／ レバ 0% ・ 全現金"
    elif color == "Yellow":
        expo = "個別 保有継続（トレール0.70のまま）・新規エントリーは停止 ／ レバ 0% ・ 空き枠は現金"
    else:
        cash = "残りは現金（ゲート/非常口由来）" if (e_ind < 1 or e_lev < 1) else "フル投資"
        _emtxt = "（非常口で半減）" if _em_mult < 1 else ""
        expo = f"個別 {e_ind*100:.0f}% ／ レバ {e_lev*100:.0f}%{_emtxt} ・ {cash}"

    # リバランス日判定はクライアント側（隔週・月曜／localStorage・_rebalCheck2）に移管

    # 引き金（優先順）
    if color and prev == "Red" and color != "Red":
        acls = "alert"
        act = f"⚠ 赤明け！翌寄りで最新トップ{N_PORT}を新規選定して即入り（次回リバランスを待たない）"
    elif color and prev and prev != color:
        up = _COLOR_RANK.get(color, -1) > _COLOR_RANK.get(prev, -1)
        tag = "攻め強化" if up else "守りへ"
        acls = "change-up" if up else "change-dn"
        ei_p, el_p = gate_coeffs(prev)
        ei_n, el_n = gate_coeffs(color)
        act = (f"{_COLOR_JP.get(prev, prev)}→{cj}（{tag}）→ 翌寄りで "
               f"個別：{_sleeve_mult(ei_p, ei_n)}／レバ：{_sleeve_mult(el_p, el_n)}")
    elif color is None:
        acls = "alert"
        act = "地合いが未取得。手動で地合いを確認してから動く"
    else:
        acls = "normal"
        act = "色変化なし → 新規アクションなし（保有維持。トレール・ストップのみ対応）"

    if _em_mult < 1 and color not in (None, "Yellow", "Red"):
        act += " ／ 非常口発動中のためレバ枠は自動で50%"

    est = ('<span class="ta-est">推定・要TradingView確認</span>'
           if (src == "estimate" and color in ("Yellow", "Red")) else "")

    open_more = acls in ("alert", "change-up", "change-dn")
    more_sty = "" if open_more else ' style="display:none"'
    tog = "▴" if open_more else "▾"
    return (f'<div class="todayact ta-{ccls}" id="taCard" data-srv="{color or ""}">'
            f'<div class="ta-top"><span class="ta-h">今日の運用</span>'
            f'<span class="ta-col" id="taCol">{cj}</span>'
            f'<span class="ta-expo" id="taExpo"><span class="mut" style="font-weight:600">目標露出：</span>{expo}</span>'
            f'<span id="taEst">{est}</span><span id="taManual"></span>'
            f'<span class="ta-tog" id="taTog" onclick="taToggle()">{tog}</span></div>'
            f'<div class="ta-more" id="taMore"{more_sty}>'
            f'<div class="ta-act ta-{acls}" id="taAct">{act}</div>'
            f'<div class="ta-rebal" id="taRebal" style="display:none"></div>'
            f'<div class="ta-rec"><span class="ta-reclab">記録</span>'
            f'<button class="nqb b-blue" onclick="setNQ(\'Blue\')">青</button>'
            f'<button class="nqb b-green" onclick="setNQ(\'Green\')">緑</button>'
            f'<button class="nqb b-yellow" onclick="setNQ(\'Yellow\')">黄</button>'
            f'<button class="nqb b-red" onclick="setNQ(\'Red\')">赤</button>'
            f'<button class="nqb b-clear" onclick="clearNQ()">推定に戻す</button>'
            f'<span class="ta-go" onclick="goTab(\'t-alloc\')">Positionsで点検 ›</span>'
            f'<span class="ta-recst" id="nqRecSt"></span></div></div></div>')


def build_calc_extras(picks, color, cand=None):
    """円→株数計算機＋配分表示に渡すデータ。FX(JPY=X)とレバ価格(TQQQ/SOXL)はライブ取得・失敗時None。
    各銘柄にRSランク順位＋急落局面フラグを付与する。
    急落・セリングクライマックスは急落局面の確認用。
    """
    e_ind, e_lev = gate_coeffs(color)
    names = []
    for i, (t, _, r) in enumerate(picks, 1):
        r5 = r.get("ret5")
        r5 = float(r5) if (r5 is not None and r5 == r5) else None
        _d52 = r.get("dist52")
        _d52 = round(float(_d52) * 100, 1) if (_d52 is not None and _d52 == _d52) else None
        names.append({"t": t,
                      "rk": i,                                    # RS189ランク（1=最強）
                      "rs": int(round(float(r.get("rs189", 0) or 0))),
                      "px": round(float(r.get("close", 0) or 0), 2),
                      "r5": round(r5 * 100, 1) if r5 is not None else None,
                      "d52": _d52,                                # 52週高値差%（追いすぎ警告用）
                      "drop": 1 if (bool(r.get("lo20_break")) or (r5 is not None and r5 <= -0.15)) else 0,  # 急落局面
                      "clx": 1 if bool(r.get("capit5")) else 0})  # セリングクライマックス(投げ)確認済みの情報タグ
    # 継続RS床: 候補が2N未満/データ不足なら 0 でなく None（0だと全銘柄が継続OK扱いになり危険）
    floor_rs189 = None
    try:
        if cand is not None and len(cand) >= CONTINUE_TOP_N:
            floor_rs189 = float(cand.iloc[CONTINUE_TOP_N - 1]["rs189"])
    except Exception:
        floor_rs189 = None
    fx = tqqq = soxl = None
    if _net_ok():
        try:
            import yfinance as yf
            d = yf.download(["JPY=X", "TQQQ", "SOXL"], period="5d",
                            progress=False, auto_adjust=True)
            cl = d["Close"] if "Close" in getattr(d, "columns", []) else d
            def last(k):
                try:
                    return round(float(cl[k].dropna().iloc[-1]), 2)
                except Exception:
                    return None
            fx, tqqq, soxl = last("JPY=X"), last("TQQQ"), last("SOXL")
        except Exception as e:
            sys.stderr.write("[calc_extras] %s\n" % e)
    return {"color": color or None, "e_ind": e_ind, "e_lev": e_lev, "n": N_PORT,
            "alloc_ind": ALLOC[0], "alloc_lev": ALLOC[1],
            "fx": fx, "tqqq": tqqq, "soxl": soxl, "names": names,
            "floor_rs189": (round(floor_rs189, 1) if floor_rs189 is not None else None)}

def _alloc_tab(calc, eq=None):
    """配分・株数計算タブ（静的スケルトン。明細はJSがwindow.CALCから生成）。"""
    c = calc or {}
    color = c.get("color")
    cj = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}.get(color, "—")
    ccls = (color or "gray").lower()
    e_ind = c.get("e_ind", 0.0); e_lev = c.get("e_lev", 0.0)
    _em_mult = float(c.get("emergency_mult", 1.0) or 1.0)
    _em_note = ('<div class="em-note">非常口発動中：NQゲート適用後のレバ枠をさらに50%へ縮小</div>'
                if _em_mult < 1 else '')
    fx = c.get("fx")
    fx_disp = ("%.2f" % fx) if fx else ""
    fx_note = "" if fx else "自動取得できず・手入力を"
    nq_warn = "" if color else '<div class="mut" style="font-size:11px;margin-top:4px">⚠ 地合いが未取得。安全側で露出0%。手動で確認を</div>'
    # 末尾行アンカー: 既知の記録数(=eq['n'])＋ヘッダ1行 → 編集画面をその行に飛ばす（末尾＝入力位置）
    _eq_n = int((eq or {}).get("n") or 0)
    _last_line = _eq_n + 1 if _eq_n else 0                         # header + records
    _edit_href = "https://github.com/thanzo12wizu-stack/v38-watchlist/edit/main/equity.csv"
    if _last_line:
        _edit_href += f"#L{_last_line}"
    eqlog = (
        _mkt_section("記録", "今日の総資産を残す（週1でOK）", en="Equity Log")
        + '<div class="card">'
        '<div class="hdr"><h2>エクイティ記録</h2></div>'
        '<details class="mut" style="margin:4px 0 8px"><summary style="font-size:11px;cursor:pointer">使い方</summary><div class="sub">総資産（＋任意で米株比率%）を入れて<b>コピー</b> → equity.csv <b>末尾</b>に貼り付け（週1でOK）。区切りは既存ファイルに自動で合わせ、リンクは最終行に飛ぶ。カーブはこの下に表示。</div></details>'
        '<div class="calc-in">'
        '<div class="ci-row"><span class="ci-pre">¥</span>'
        '<input id="eqIn" type="number" inputmode="numeric" placeholder="今日の総資産（例 6742525）"></div>'
        '<div class="ci-row" style="margin-top:6px"><span class="ci-pre" style="font-size:12px">米株%</span>'
        '<input id="eqUsIn" type="number" inputmode="decimal" placeholder="任意（例 76.5）・空欄OK"></div>'
        '<div class="ci-row2" style="margin-top:6px">'
        '<button class="memx" id="eqCopyBtn" onclick="copyEquityRow()">📋 <span id="eqDate">今日</span> の1行をコピー</button>'
        f'<a class="memx" style="text-decoration:none" href="{_edit_href}" target="_blank" rel="noopener">✏️ 末尾を開いて追記</a>'
        '</div>'
        '<div class="mut" style="font-size:11px;margin-top:4px">流れ: 📋コピー → ✏️（最終行付近で開く）→ 一番下に貼り付け → Commit（3タップ）。日付は自動で付く。</div>'
        '</div></div>'
        )
    body = (
        _mkt_section("① 配分計算", "地合い → 今日の株数に落とす", en="Position Sizing")
        + '<div class="card">'
        '<div class="hdr"><h2>資金配分・株数計算</h2></div>'
        '<div class="sub">円の総資産から、現在の地合いに応じた各銘柄の買付株数を出す。'
        '<b>隔週リバランス時点の計画値</b>（金曜クローズ判定→月曜寄りで執行）（実約定はギャップ・手数料でズレる）。<b>#</b>=RSランク・<b class="kf-skip" style="padding:0 4px">急落注意</b>=情報バッジのみ・<b class="kf-ok" style="padding:0 4px">投げ確認</b>=セリングクライマックス確認済み。<b>レバ枠のTQQQ/SOXL比はSOXL投入帯（SOXX 50MA +0〜3%）に自動連動</b>——帯外は全額TQQQ。</div>'
        # 現在の色＋係数
        '<div class="gatebox">'
        f'<div class="gate-c sar-{ccls}" id="calcGateC">{cj}</div>'
        '<div class="gate-meta">'
        f'<span id="calcExpo">個別 露出 <b>{e_ind*100:.0f}%</b> ／ レバ 露出 <b>{e_lev*100:.0f}%</b></span>'
        '<div class="mut" style="font-size:11px">青100·100／緑100·50／黄100·0／赤0·0（個別·レバ）。非常口発動時は、このレバ露出に×0.50を自動適用。</div>'
        f'{_em_note}{nq_warn}</div></div>'
        # 入力
        '<div class="calc-in">'
        '<div class="ci-row"><span class="ci-pre">¥</span>'
        '<input id="jpyIn" type="number" inputmode="numeric" placeholder="円の総資産（例 10000000）" oninput="calcRun()"></div>'
        '<div class="ci-row2"><span class="ci-fxl">USD/JPY</span>'
        f'<input id="fxIn" type="number" inputmode="decimal" value="{fx_disp}" placeholder="150" oninput="calcRun()">'
        f'<span class="mut ci-fxn" style="font-size:11px">{fx_note}</span></div>'
        '</div>'
        # サマリ＋明細（JSが描画）
        '<div id="calcSum" class="calc-sum"></div>'
        '<div id="calcOut"><div class="calc-empty">金額を入れると株数を計算します</div></div>'
        '<div class="calc-mem">'
        '<button class="memx" onclick="memExport()">建値を書き出し</button>'
        '<button class="memx" onclick="memImport()">読み込み</button>'
        '<span class="mut" style="font-size:11px">建値はこの端末（ブラウザ）に保存。機種変・データ消去前に書き出しを</span>'
        '</div></div>'
        # 隔週リバランス点検（月曜）（P3）
        + _mkt_section("② リバランス点検", "隔週月曜のチェックリスト", en="Rebalance Check")
        + '<div class="card"><div class="hdr"><h2>隔週リバランス点検（月曜）</h2></div>'
        f'<div class="sub">建値を入れた保有を継続条件（<b>50日線&gt;200日線・189日RS上位{CONTINUE_TOP_N}</b>）と突合。'
        f'外れた銘柄＝売り候補、新{CORE_BRAND}で未保有＝組み入れ候補。該当の月曜に確認する。</div>'
        '<div id="rebalBox"></div></div>'
        # 補足
        '<div class="card"><div class="sub">'
        f'この計算機は各銘柄を<b>個別枠÷{N_PORT}</b>で均等配分（端数は切り捨て）。建値を入れると保有ごとに'
        '<b>現在損益・正式出口線 max(建値×0.75, ピーク×0.70)</b>を表示する。'
        'トレールまたはストップに当たった銘柄は<b>「売却済」</b>を押すと、その枠を空けて集計する。'
        '空いた枠は<b>次回リバランスまで再投下せず現金で保持</b>し、次の隔週トゥルーアップ（月曜）で新Core 12へ均等配分する。'
        '建値・利確の記録はこの端末に残り、次回も覚えている。</div></div>')
    return body, eqlog


def build_ema21_touch(m, W, s2t, cap=12, out=None):
    """21EMAタッチ・ピックアップ。
       母集団=リーダー（RS63≥LEADER_RS & 200日線上）かつRS189≥80。
       条件=EMA21が上向き（5営業日前比+）・終値がEMA21〜+4%・直近3営業日内に安値がEMA21×1.005以下（ヒゲでタッチ）。
       oratnek式の押し目定位置。売買ゲート・正式選定には接続しない。"""
    try:
        C = W.get("Close"); L = W.get("Low")
        if C is None or L is None or len(C) < 30 or m is None or m.empty:
            return ""
        _adr_col = m["adr"] if "adr" in m.columns else 0
        _adr_frac = _adr_col.where(_adr_col < 1, _adr_col / 100.0) if hasattr(_adr_col, "where") else _adr_col
        lead = m[setup_eligible(m)
                 & (m.get("rs", 0) >= LEADER_RS)
                 & (m.get("rs189", 0) >= 90)                       # エントリー基準: 長期RSもきつめ
                 & (m["close"] > m["sma200"])
                 & (m.get("mcap", 0).fillna(0) >= 1e9)             # 時価総額 ≥ $1B
                 & (m.get("dvol", 0).fillna(0) >= 10e6)            # $vol ≥ $10M/日
                 & (_adr_frac >= 0.03)]                            # ADR% ≥ 3%
        if lead.empty:
            return ""
        ema = C.ewm(span=21, adjust=False).mean()
        H = W.get("High"); Lo = W.get("Low")
        atr = None
        try:
            cols = [t for t in lead.index if t in C.columns]
            _c, _h, _l = C[cols], H[cols], Lo[cols]
            _pc = _c.shift(1)
            _tr = pd.concat([(_h - _l), (_h - _pc).abs(), (_l - _pc).abs()]).groupby(level=0).max() if False else None
            _tr = np.maximum(_h - _l, np.maximum((_h - _pc).abs(), (_l - _pc).abs()))
            atr = pd.DataFrame(_tr, index=_c.index, columns=cols).rolling(14).mean()
        except Exception:
            atr = None
        rows = []
        for t in lead.index:
            if t not in C.columns:
                continue
            e_now = float(ema[t].iloc[-1]); e_prev = float(ema[t].iloc[-6])
            c_now = float(C[t].iloc[-1])
            if not (np.isfinite(e_now) and np.isfinite(e_prev) and np.isfinite(c_now)):
                continue
            if e_now <= e_prev:                       # EMA21が上向きでない＝押し目でなく崩れ
                continue
            r0 = lead.loc[t]
            _adr_raw = float(r0.get("adr", 0) or 0)
            adr_frac = _adr_raw if _adr_raw < 1 else _adr_raw / 100.0   # 小数/百分率の両格納に対応
            dev = c_now / e_now - 1.0
            cap_dev = max(0.02, adr_frac)              # 上限=+1×ADR（最低2%は確保）
            if dev < -0.01 or dev > cap_dev:           # EMA割れ〜ADR超の伸びは除外
                continue
            atr_mult = None
            try:
                sma50 = float(r0.get("sma50"))
                a_now = float(atr[t].iloc[-1]) if atr is not None else float("nan")
                if np.isfinite(sma50) and np.isfinite(a_now) and a_now > 0 and sma50 > 0:
                    B = (c_now - sma50) / sma50        # 50MAからの上昇率
                    A = a_now / c_now                  # ATR% = ATR / 現在値
                    atr_mult = B / A if A > 0 else None
            except Exception:
                atr_mult = None
            touch_day = None
            for k in range(3):                        # 直近3営業日内のタッチ
                lo = float(L[t].iloc[-1 - k]); ek = float(ema[t].iloc[-1 - k])
                if np.isfinite(lo) and np.isfinite(ek) and lo <= ek * 1.005:
                    touch_day = k
                    break
            if touch_day is None:
                continue
            rows.append((t, (s2t.get(t) or ["—"])[0],
                         float(r0.get("rs189", 0) or 0), float(r0.get("rs", 0) or 0),
                         dev * 100, touch_day, atr_mult,
                         (dev / adr_frac) if adr_frac > 0 else None))
        if not rows:
            return ('<div class="card"><h2>21EMAタッチ <span class="h2en">21EMA Touch</span></h2>'
                    '<div class="sub">条件を満たす銘柄なし（リーダーがEMA21の定位置まで押していない）。</div></div>')
        rows.sort(key=lambda x: (-x[2], x[4]))
        def _tr(t, th, r189, r63, dv, td, am, xadr):
            am_txt = "—" if am is None else f"{am:.1f}×"
            am_cls = "neg" if (am is not None and am > 8) else "mut"
            xat = "" if xadr is None else f" title=\"{xadr:.1f}×ADR\""
            tdl = "今" if td == 0 else f"{td}d"
            return (f'<tr data-rs="{r189:.0f}" data-dev="{dv:.2f}" data-td="{td}" data-atr="{(am if am is not None else 999):.2f}">'
                    f'<td><b data-tkone="{t}">{t}</b></td>'
                    f'<td class="l" style="font-size:10.5px;color:#94a3b8;white-space:normal;max-width:120px">{_h(th)}</td>'
                    f'<td>{r189:.0f}/{r63:.0f}</td><td{xat}>{dv:+.1f}%</td>'
                    f'<td class="{am_cls}">{am_txt}</td>'
                    f'<td class="mut" style="font-size:10.5px">{tdl}</td></tr>')
        trs = "".join(_tr(*r) for r in rows[:cap])
        _ettk = [x[0] for x in rows[:cap]]
        if out is not None: out.extend(_ettk)
        return (f'<div class="card"><div class="hdr"><h2>21EMAタッチ <span class="h2en">21EMA Touch</span></h2>{_cp(_ettk)}</div>'
                f'<div class="sub">エントリー基準（RS63≥{LEADER_RS}・RS189≥90・時価総額≥$1B・$vol≥$10M・ADR%≥3%・200日線上）を満たすリーダーのうち、<b>上向きEMA21の定位置に押した</b>銘柄。'
                f'<details class="mut" style="margin:2px 0 6px"><summary style="font-size:11px;cursor:pointer">条件の定義</summary>'
                f'<div class="sub">直近3営業日内に安値がEMA21タッチ・終値はEMA21〜<b>+1×ADR%</b>（銘柄のボラに適応）。50MA(ATR)=50日線からのATR%倍率〔(50MA比%上昇)÷(ATR÷現在値)〕で、7〜10倍超は伸び切りの目安。</div></details>'
                f'<table class="tbl"><thead><tr><th>銘柄</th><th>テーマ</th>'
                f'<th class="sortable act" onclick="rowSort(\'rs\',this)">RS189/63</th>'
                f'<th class="sortable" data-asc="1" onclick="rowSort(\'dev\',this)">EMA21乖離</th>'
                f'<th class="sortable" data-asc="1" onclick="rowSort(\'atr\',this)">50MA(ATR)</th>'
                f'<th class="sortable" data-asc="1" onclick="rowSort(\'td\',this)">タッチ</th></tr></thead>'
                f'<tbody>{trs}</tbody></table>'
                f'<div class="mut" style="font-size:10px;margin-top:3px">見出しタップで並べ替え（乖離・タッチは小さい順から）</div></div>')
    except Exception as e:
        sys.stderr.write("[ema_touch] %r\n" % repr(e)[:100])
        return ""


def build_weekly_unique(W, m, s2t, picks, eq_s, macro, mkt, rates_ctx, press_ctx):
    """Weeklyタブ固有の3カード（今週の変化 / 週次騰落ボード / 自分vsQQQ円建て）。
       すべて手元データの週次再計算のみ。新指標・売買接続なし。"""
    diff_html = board_html = acct_html = ""
    try:
        C = W.get("Close") if isinstance(W, dict) else None
        items = []
        # 地合いスコア(5営業日差)
        ts = mkt.get("mri_ts") or []
        if len(ts) >= 6:
            v0, v5 = float(ts[-1][1]), float(ts[-6][1])
            items.append(f"地合いスコア <b>{v0:.0f}</b>（週 {v0-v5:+.0f}）")
        # NQ色
        th = mkt.get("trend_hist") or []
        if len(th) >= 6 and th[-1] and th[-6]:
            c0, c5 = th[-1][1], th[-6][1]
            items.append(f"地合い {_COLOR_JP.get(c5, c5)} → <b>{_COLOR_JP.get(c0, c0)}</b>" if c0 != c5
                         else f"地合い <b>{_COLOR_JP.get(c0, c0)}</b>のまま")
        # 50MA上比率
        if C is not None and len(C) >= 60:
            ma = C.rolling(50).mean()
            p0 = float((C.iloc[-1] > ma.iloc[-1]).mean() * 100)
            p5 = float((C.iloc[-6] > ma.iloc[-6]).mean() * 100)
            items.append(f"50MA上比率 <b>{p0:.0f}%</b>（週 {p0-p5:+.0f}pt）")
        # OAS / 実質金利（5観測差）
        for sid, lab, ctx, bp in (("BAMLH0A0HYM2", "HY OAS", press_ctx, True),
                                   ("DFII10", "実質金利", rates_ctx, False)):
            vals = ((ctx or {}).get(sid) or {}).get("vals") or []
            if len(vals) >= 6:
                d = (float(vals[-1][1]) - float(vals[-6][1])) * 100
                items.append(f"{lab} 週 <b>{d:+.0f}bp</b>")
        # リーダーTop24入替
        try:
            if m is not None and "rs189" in m.columns and "rs189_l5" in m.columns:
                now24 = set(m["rs189"].nlargest(24).index)
                prev24 = set(m["rs189_l5"].dropna().nlargest(24).index)
                ins = sorted(now24 - prev24); outs = sorted(prev24 - now24)
                if ins or outs:
                    t_in = "・".join(ins[:4]) + ("…" if len(ins) > 4 else "")
                    t_out = "・".join(outs[:4]) + ("…" if len(outs) > 4 else "")
                    items.append(f"リーダーTop24 入替 <b>{len(ins)}</b>（IN {t_in or '—'} ／ OUT {t_out or '—'}）")
                else:
                    items.append("リーダーTop24 入替なし（顔ぶれ固定）")
        except Exception:
            pass
        if items:
            lis = "".join(f'<div class="kv" style="font-size:12.5px;line-height:1.8">{x}</div>' for x in items)
            diff_html = (f'<div class="card"><h2>今週の変化 <span class="h2en">Weekly Diff</span></h2>'
                         f'<div class="sub">先週比（5営業日）。日次タブでは見えない週の歩幅。</div>{lis}</div>')
    except Exception as e:
        sys.stderr.write("[wk_diff] %r\n" % repr(e)[:100])
    try:
        C = W.get("Close") if isinstance(W, dict) else None
        if C is not None and len(C) >= 6:
            r5 = (C.iloc[-1] / C.iloc[-6] - 1.0) * 100
            r5 = r5.dropna()
            th_map = {t: (s2t.get(t) or ["—"])[0] for t in r5.index}
            import collections
            g = collections.defaultdict(list)
            for t, v in r5.items():
                g[th_map.get(t, "—")].append(float(v))
            rows = [(k, float(pd.Series(v).median()), len(v)) for k, v in g.items() if len(v) >= 3 and k != "—"]
            rows.sort(key=lambda x: -x[1])
            def _line(k, v, n):
                cls = "pos" if v > 0 else "neg"
                return (f'<div style="display:flex;justify-content:space-between;padding:4px 2px;'
                        f'border-bottom:1px solid rgba(255,255,255,.05)"><span style="font-size:12px;color:#cbd5e1">{_h(k)}'
                        f'<span class="mut" style="font-size:10px">　n={n}</span></span>'
                        f'<b class="{cls}">{v:+.1f}%</b></div>')
            top = "".join(_line(*r) for r in rows[:5])
            bot = "".join(_line(*r) for r in rows[-5:][::-1]) if len(rows) > 5 else ""
            hold = ""
            try:
                tks = [p[0] for p in (picks or []) if p and p[0] in r5.index]
                if tks:
                    hs = sorted(((t, float(r5[t])) for t in tks), key=lambda x: -x[1])
                    hold = ('<div class="mut" style="font-size:10.5px;margin:8px 0 4px;font-weight:800">保有12の週次</div>'
                            + '<div style="display:flex;flex-wrap:wrap;gap:6px">'
                            + "".join(f'<span class="chip" style="padding:5px 9px;font-size:11.5px">{t} <b class="{"pos" if v>0 else "neg"}">{v:+.1f}%</b></span>' for t, v in hs)
                            + '</div>')
            except Exception:
                pass
            board_html = (f'<div class="card"><h2>週次騰落ボード <span class="h2en">Weekly Movers</span></h2>'
                          f'<div class="sub">テーマ内中央値の5営業日リターン。RRG（中期RS）とのズレを見る。</div>'
                          f'<div class="mut" style="font-size:10.5px;font-weight:800;margin-bottom:3px">強かった5テーマ</div>{top}'
                          + (f'<div class="mut" style="font-size:10.5px;font-weight:800;margin:8px 0 3px">弱かった5テーマ</div>{bot}' if bot else "")
                          + hold + '</div>')
    except Exception as e:
        sys.stderr.write("[wk_board] %r\n" % repr(e)[:100])
    try:
        if eq_s is not None and len(eq_s) >= 2 and isinstance(macro, dict):
            q = macro.get("QQQ")
            fx = macro.get("JPY=X")
            if isinstance(q, pd.DataFrame) and isinstance(fx, pd.DataFrame):
                qc = q.get("Close")
                fc = fx.get("Close")
            else:
                qc = fc = None
            if qc is not None and fc is not None:
                qj = (qc.squeeze() * fc.squeeze().reindex(qc.index).ffill()).dropna()
                rows = []
                idx = eq_s.index
                for k in range(min(4, len(idx) - 1)):
                    d1, d0 = idx[-1 - k], idx[-2 - k]
                    me = float(eq_s.iloc[-1 - k] / eq_s.iloc[-2 - k] - 1) * 100
                    try:
                        q1 = float(qj[qj.index <= pd.Timestamp(d1)].iloc[-1])
                        q0 = float(qj[qj.index <= pd.Timestamp(d0)].iloc[-1])
                        bench = (q1 / q0 - 1) * 100
                    except Exception:
                        bench = None
                    ex = (me - bench) if bench is not None else None
                    rows.append((str(d0)[:10], str(d1)[:10], me, bench, ex))
                trs = "".join(
                    f'<tr><td class="mut" style="font-size:10.5px">{a}→{b}</td>'
                    f'<td><b class="{"pos" if r>0 else "neg"}">{r:+.1f}%</b></td>'
                    f'<td class="mut">{("%+.1f%%" % q) if q is not None else "—"}</td>'
                    f'<td><b class="{"pos" if (e or 0)>0 else "neg"}">{("%+.1f" % e) + "pt" if e is not None else "—"}</b></td></tr>'
                    for a, b, r, q, e in rows)
                acct_html = (f'<div class="card"><h2>自分 vs QQQ円建て <span class="h2en">My Week</span></h2>'
                             f'<div class="sub">equity.csvの記録間リターンと、同区間のQQQ円建て・超過。10月のペーパー判定と同じ物差し。</div>'
                             f'<table class="tbl"><thead><tr><th>区間</th><th>自分</th><th>QQQ円</th><th>超過</th></tr></thead><tbody>{trs}</tbody></table></div>')
        if not acct_html:
            acct_html = ('<div class="card"><h2>自分 vs QQQ円建て <span class="h2en">My Week</span></h2>'
                         '<div class="sub mut">equity.csvの記録が2行以上たまると、記録間リターン・QQQ円建て比較・超過をここに表示。</div></div>')
    except Exception as e:
        sys.stderr.write("[wk_acct] %r\n" % repr(e)[:100])
    return diff_html, board_html, acct_html


def render(names, m, mri, breakdown, dropped, aux, setups, picks, cand,
           sectors, breadth, yields, asof, sar, mkt, leaders, s2i, e2j, s2t, W=None):
    band_lab, band_cls = mri_band(aux["hl"])
    mk = max(0, min(100, aux["cur"]))
    # ---- トレンド判定 pill (file=確定 / live=推定 / none=無判定グレー). logic hidden
    sar_color, sar_src = sar
    if sar_color is None:                       # everything failed -> gray no-judgment
        s_lab, s_jud, s_lot, s_cls = "—", "判定不可", "データ取得不可", "sar-gray"
    else:
        s_lab, s_jud, s_lot, s_cls = SAR_JUDGMENT.get(sar_color, SAR_JUDGMENT["Blue"])
    if sar_src == "file":
        badge = '<span class="sar-badge ok">確定</span>'
    elif sar_src in ("estimate", "nq_csv"):
        badge = '<span class="sar-badge est">CSV推定</span>' if sar_src == "nq_csv" else '<span class="sar-badge est">推定</span>'
        if sar_color in ("Yellow", "Red"):
            s_lot = "推定・要TradingView確認"
    else:
        badge = '<span class="sar-badge none">無判定</span>'
    sar_pill = f"""
    <div class="sar {s_cls}" id="sarPill">
      <div class="lhs">
        <span class="dot"></span>
        <div>
          <div class="lab">トレンド判定 <span id="sarBadge">{badge}</span></div>
          <div class="col" id="sarCol">{s_lab}</div>
        </div>
      </div>
      <div class="rhs">
        <div class="jud" id="sarJud">{s_jud}</div>
        <div class="lot" id="sarLot">{s_lot}</div>
      </div>
    </div>"""
    # ---- status banner + ⑥ tappable breakdown panel
    drop_note = ""
    if dropped:
        drop_note = f'<div class="note">注記：データ未取得のため除外し残り指標で100点満点に再正規化 → {", ".join(dropped)}</div>'
    _kj = {"trend":"トレンド","breadth":"広がり","risk":"ボラティリティ","credit":"信用"}
    _gj = {"market":"4本柱"}
    def _mraw(k, v):
        if v is None or (isinstance(v, float) and np.isnan(v)): return "—"
        if k in ("trend", "breadth", "risk", "credit"): return f"{v:.0f}"
        return f"{v:.2f}"
    _bd_rows = []; _seen_grp = None
    for b in breakdown:
        if b["group"] != _seen_grp:
            _seen_grp = b["group"]
            _bd_rows.append(f'<div class="mgrp">{_gj.get(_seen_grp, _seen_grp)}</div>')
        _bd_rows.append(
            f'<div class="mrow"><span class="mk2">{_kj.get(b["key"], b["key"])}</span>'
            f'<span class="mraw">{_mraw(b["key"], b["raw"])}</span>'
            f'<span class="mbar"><i style="width:{100*b["frac"]:.0f}%"></i></span>'
            f'<span class="mpts">{b["pts"]:.1f}/{b["ptsmax"]}</span></div>')
    # ベア警戒：点灯中の要因を明示（点灯=赤、非点灯=グレー）
    _bf = aux.get("bear_flags", [])
    _blit = [lab for lab, on in _bf if on]
    _boff = [lab for lab, on in _bf if not on]
    _bchips = ("".join(f'<span class="bfl on">{lab}</span>' for lab in _blit)
               + "".join(f'<span class="bfl off">{lab}</span>' for lab in _boff))
    bear_sec = (f'<div class="mgrp">警戒 {aux["bear_n"]}/4</div>'
                f'<div class="bflags">{_bchips or "<span class=bfl off>—</span>"}</div>')
    mri_bd = (f'<div id="mri-bd" class="mri-bd" onclick="event.stopPropagation()">'
              f'<div class="mbd-h">地合いスコアの内訳（4本柱）</div>'
              + "".join(_bd_rows) + bear_sec
              + '<div class="mnote">赤=点灯中のベア要因。もう一度タップで閉じる ▴</div></div>')
    banner = sar_pill + _ribbon(mkt.get("trend_hist")) + f"""
    <div class="banner b-{band_cls}" onclick="toggleMri()">
      <div class="lab">マーケットステータス（地合いスコア）<span class="lab-en">MARKET STATUS</span><span class="tap">タップで内訳 ▾</span></div>
      <div class="val">{aux['cur']:.0f}<span style="font-size:15px;font-weight:600">/100</span></div>
      <div class="st">{band_lab}</div>
      <div class="gauge"><div class="mk" style="left:{mk}%"></div></div>
      <div class="aux">
        <div class="a">傾き <b>{aux['slope']}</b></div>
        <div class="a">警戒 <b>{aux['bear_n']}</b>/4 {_led(aux['bear_n'], 4)}</div>
      </div>
      {mri_bd}
      {drop_note}
    </div>"""

    # ---- TAB 今日 — procedure-aligned (本日◎押し目 ③ + リーダー監視 ①〜⑤)
    try:
        cat_commentary = build_categorized_commentary(mkt, m, breadth, sar, aux)
    except Exception as _e:
        sys.stderr.write("[cat_commentary] failed: %r\n" % (repr(_e)[:200]))
        cat_commentary = ""
    try:
        comment = _market_comment(aux, mkt, sar, breadth, cat_commentary)
    except Exception as _e:
        sys.stderr.write("[market_comment] failed: %r\n" % (repr(_e)[:200]))
        comment = '<div class="card cmt mkt20"><h2>今日のマーケット</h2><div class="sub">コメント生成でエラー（データ確認中）</div></div>'
    rotation = _rotation_comment(mkt)
    pick_set = {t for t, _, _ in picks}
    buytoday = build_buy_today(m, s2i, e2j, s2t, pick_set=pick_set)
    vcp_rows = build_vcp(m, s2i, e2j, s2t)
    patterns = build_patterns(m, s2i, e2j, s2t)
    # スイング・プランナー候補（保有＋控え＋VCP・各自の確定ストップ付き）
    _sw_seen = set(); swing_data = []
    for _src in ([t for t, _, _ in picks], list(cand.index[N_PORT:N_PORT + 15]), [r["t"] for r in vcp_rows]):
        for t in _src:
            if t in _sw_seen or t not in m.index:
                continue
            _sw_seen.add(t)
            _r = m.loc[t]; _px = _r.get("close"); _ema = _r.get("ema21"); _lo = _r.get("lo10")
            if _px is None or _px != _px:
                continue
            _px = float(_px)
            _cands = []
            if _lo == _lo: _cands.append(float(_lo) * 0.998)
            if _ema == _ema: _cands.append(float(_ema) * 0.99)
            _cands = [x for x in _cands if x < _px]          # 現値より下の線だけ（新規ロングの有効ストップ）
            _stop = max(_cands) if _cands else _px * 0.93
            _e21l = _r.get("ema21l"); _s10 = _r.get("sma10")   # 撤退セレクタ用: 21EMA安値 / 10日線
            swing_data.append(dict(t=t, px=round(_px, 2), stop=round(_stop, 2),
                                   e21l=(round(float(_e21l), 2) if (_e21l is not None and _e21l == _e21l) else None),
                                   s10=(round(float(_s10), 2) if (_s10 is not None and _s10 == _s10) else None),
                                   rs=round(float(_r.get("rs") or 0), 0)))
    by_state, buys = leaders
    leaders_card = _leaders_card(by_state)
    # new 52w-high breakouts — 強い銘柄のみに厳選（RS90以上・$10M以上）
    nh = m[(m["dist52"] >= -0.005) & (m["rs"] >= 90) & (m["dvol"] >= DVOL_FLOOR)].sort_values("rs", ascending=False)
    nh_list = list(nh.index)
    nh_chips = "".join(
        f'<span class="chip hot" data-liq="{(m.at[t,"dvol"] or 0)/1e6:.1f}" data-tkone="{t}">{t}</span>' for t in nh_list)
    newhigh_card = (
        f'<div class="card"><div class="hdr"><h2>本日の新高値圏</h2>{_cp(nh_list)}</div>'
        f'<div class="sub">52週高値まで0.5%以内・<b>RS90以上かつ$10M以上の強い銘柄のみ</b>・RS順（{len(nh_list)}銘柄）</div>'
        f'<div class="chips">{nh_chips or "<span class=empty>該当なし</span>"}</div></div>')
    # ピックアップtab（旧ウォッチと統合）は、検索/セットアップ等のカード生成後に下でまとめて組み立てる。

    # ---- TAB ポートフォリオ
    per = ALLOC[0] / N_PORT
    _raw_rank = {t: i + 1 for i, t in enumerate(cand.index)}   # 全候補内の189RS順位（控えと共通の通し番号）
    _hv = mkt.get("hold") or {}
    _er = mkt.get("er") or {}
    def _trail_cell(t):
        h = _hv.get(t)
        if not h or h.get("dist") is None or h["dist"] != h["dist"]:
            return '<td class="mut">—</td>'
        d = h["dist"]
        w = h.get("which", "")
        # 想定変動幅(ADR実現ボラ・約1ヶ月1σ)と出口距離を並記＝タイトさが一目
        adr = (m.at[t, "adr"] if (t in m.index and pd.notna(m.at[t, "adr"])) else None)
        em = (float(adr) * 0.55 * float(np.sqrt(21))) if adr is not None else None
        shallow = (em is not None and d < em)                 # 出口が1σより内＝ノイズで振られやすい
        cls = "neg" if (d < 0.05 or shallow) else ("mut" if d < 0.10 else "pos")
        r3 = '<span class="r3b">+3R到達</span>' if h.get("hit3") else ""
        flag = '<span class="shallow">浅</span>' if shallow else ""
        emtxt = f'・想定±{em*100:.0f}%' if em is not None else ""
        return (f'<td class="{cls}">{d*100:.0f}%{flag}{r3}'
                f'<div class="tday">保有{h.get("days",1)}日{("・"+w) if w else ""}{emtxt}</div></td>')
    # 保有テーブル = RS上位から連番で、選定12(=リーダーのみ)が埋まるまでの全銘柄
    #   (選外=出遅れ/小型創薬/リーダー外 もバッジ付きで同じ表にRS順表示・買わない)。
    _pick_set = set(t for t, _, _ in picks)
    # 表示=固定36行(3N)。選定が36位より深い場合のみ最後の選定まで延長。
    _pick_pos = [pos for pos, t in enumerate(cand.index, 1) if t in _pick_set]
    _disp_cap = max((_pick_pos[-1] if _pick_pos else 0), min(len(cand), 3 * N_PORT))
    rows = []
    for i, (t, r) in enumerate(cand.iterrows(), 1):
        if i > _disp_cap:
            break
        if i == 2 * N_PORT + 1:
            rows.append(f'<tr class="bdry"><td colspan="9">── 継続境界（上位{CONTINUE_TOP_N}＝2N）ここまで継続保有OK・以下は監視ゾーン ──</td></tr>')
        sth = subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))
        is_l, code, _lab, _rsn = leader_state(r)
        nu_tag, _nun, nu_cls = momentum_nuance(r)
        _selected = t in _pick_set
        _exq = bool(r.get("excluded_theme")); _lag = bool(r.get("laggard")); _nl = bool(r.get("nonleader"))
        _lag_tag = '<span class="lagb">出遅れ</span>' if _lag else ''   # 買う対象・タグのみ
        # 選外バッジ / 急落情報バッジ
        if _exq:
            _badge = '<span class="exq">除外（小型創薬）</span>'; _trcls = ' class="row-excluded"'
        elif _nl and not _selected:
            _badge = '<span class="lagb">リーダー外（選外）</span>'; _trcls = ' class="row-excluded"'
        else:
            _r5 = r.get("ret5"); _r5 = float(_r5) if (_r5 is not None and _r5 == _r5) else None
            _drop = bool(r.get("lo20_break")) or (_r5 is not None and _r5 <= -0.15)
            _clx = bool(r.get("capit5"))
            _wait = ('<span class="waitb">急落注意</span>' if (_drop and not _clx) else
                     '<span class="okb">投げ確認</span>' if (_drop and _clx) else "")
            _badge = _lag_tag + _wait                                  # 出遅れタグ＋（あれば）急落状態
            _trcls = ""                         # 急落は情報バッジのみ。グレーアウト・選定除外しない
        _th = theme_of(t, s2t)
        rows.append(
            f'<tr{_trcls} data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}"><td class="l mut">{i}</td>'
            f'<td class="l tk">{t}{_risk_flag_badge(t, r.get("close"))}{_badge}'
            f'<div class="rowsec">{_h(_th)} ・ {_h(sth)}</div>'
            f'<div class="rowbadges">'
            f'<span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span>'
            f'{_state_badge(code, nu_tag, nu_cls, _rsn)}{_new_entry_badge(r)}{_rank_in_badge(t, mkt.get("hold"), _selected)}{_er_badge(t, _er, mkt.get("asof_bar"))}{_adr_badge(r.get("adr"))}{_fade_badge(r)}{_chase_alert(r)}{_ent_btn(t)}</div></td>'
            f'<td class="rsc">{_rs_cell(r)}</td>'
            f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
            f'<td class="{color_pct(r["vs200"])}">{fmt_pct(r["vs200"])}</td>'
            f'<td class="{color_pct(r["dist52"])}">{fmt_pct(r["dist52"])}</td></tr>')
    alloc_bar = (f'<div class="alloc">'
                 f'<div class="a-ind" style="width:{ALLOC[0]}%">個別 {ALLOC[0]}</div>'
                 f'<div class="a-lev" style="width:{ALLOC[1]}%">レバ {ALLOC[1]}</div>'
                 + (f'<div class="a-cash" style="width:{ALLOC[2]}%">現金 {ALLOC[2]}</div>' if ALLOC[2] > 0 else "")
                 + '</div>')
    port = (f'<div class="card"><div class="hdr"><h2>個別株スリーブ <span class="h2en">Core 12</span></h2>'
            f'{_cp([t for t, _, _ in picks])}</div>'
            + alloc_bar +
            f'<details class="rk-leg"><summary>凡例（バッジの意味）</summary>'
            f'<div class="note rk-note"><b>買うのは189日RS≥85＆200MA上のリーダーから、63日RS≥85のもの上位{N_PORT}だけ・位置不問</b>（エントリーの精緻化は成績を改善しない）。'
            f'<b>出口</b>＝初期ストップ建値×0.75（ワイド）→伸びたらピーク×0.70トレール（黄も0.70）。'
            f'<b>赤明けは青/緑復帰の翌寄りに即再構築</b>・黄は締めず保有継続。'
            f'<b class="chaseb">⚠ 高値圏</b>＝52週高値−10%以内の追いかけは−0.28R（唯一生き残った入口注意）＝指値で下に置き1-2日待ってよい／'
            f'<b class="newb">NEW</b>＝36位圏に新しく入ってきた銘柄（今週/今月）＝ランキングの新陳代謝／'
            f'<b class="entb2">未/済</b>＝指値運用の執行ズレを手動マーク（端末に保存）／'
            f'<b class="fadeb fade-lo">勢い細り</b>＝189は強いが短期RS低下＝降りどき警戒／'
            f'<b>選外（小型創薬/リーダー外/勢い落ち）</b>＝グレーアウト。</div></details>'
            f'<table><tr><th class="l">#</th><th class="l">銘柄</th><th>RS</th>'
            f'<th>前日比</th><th class="th-w">200MA<br>乖離</th><th class="th-w">52週<br>高値差</th></tr>'
            + "".join(rows) + '</table>'
            + _risk_note(mkt) +
            f'<div class="note">1銘柄あたり{per:.2f}%（各1/{N_PORT}等分）。トレンド悪化時は{N_PORT}銘柄が揃わず現金が増えるのが正常。<b>急落注意／投げ確認</b>は急落局面の確認用。詳しいルールはルールタブへ。</div></div>')
    # RSリーダー控え（15社）は下でdeck_card構築後に port へ追加



    # ---- TAB ウォッチ — watchlist: 複数ヒット overlap + セットアップ別 + RSリーダー控え
    from collections import Counter
    # 詳細モーダルの「登場箇所」は【実際に表示中のカードの実条件】から作る。
    # 旧build_setups由来の探せないカテゴリ（押し目/モメンタム/深押し等）は使わない。
    where = {}
    def _wadd(_tks, _lab):
        for _t in _tks:
            if _t:
                where.setdefault(_t, []).append(_lab)
    _elig = setup_eligible(m)
    try:
        _ne_map = {t: cand.at[t, "new_entry"] for t in cand.index} if ("new_entry" in getattr(cand, "columns", [])) else {}
    except Exception:
        _ne_map = {}
    try: _wadd([x["t"] for x in buytoday], "本日ブレイク")
    except Exception: pass
    try: _wadd([x["t"] for x in vcp_rows], "VCP")
    except Exception: pass
    try:   # 底打ち: カードと同じ適格＋上位24件（出来高減優先→RS63）に一致させる
        _sp = [t for t in m.index[_elig] if isinstance(m.at[t, "sp"], dict)]
        _sp.sort(key=lambda t: (0 if (m.at[t, "sp"] or {}).get("vdry") else 1,
                                -(float(m.at[t, "rs63"]) if ("rs63" in m.columns and m.at[t, "rs63"] == m.at[t, "rs63"]) else -1)))
        _wadd(_sp[:24], "底打ち")
    except Exception: pass
    try: _wadd(list(m.index[_elig & m["pp_days"].notna() & (m["close"] > m["sma200"]) & (m["rs189"] >= LEADER_RS)]), "ポケット")
    except Exception: pass
    try:   # 重なり: コンフルエンスの実条件（8兆候のうちCONFLUENCE_MIN以上）で判定＝過大表示を防ぐ
        _cf = []
        for _t, _r in m[_elig & (m["sma50"] > m["sma200"]) & (m["rs189"] >= 95)].iterrows():
            if len(_signals_of(_r, _ne_map.get(_t))) >= CONFLUENCE_MIN:
                _cf.append(_t)
        _wadd(_cf, "重なり")
    except Exception: pass
    try:
        if "w30x" in m.columns:
            _wadd([t for t in m.index if bool(m.at[t, "w30x"])], "W30")
    except Exception: pass
    try:   # パターン: 各パターンの実条件の和集合
        _up50 = m["close"] > m["sma50"]; _near = m["dist52"] >= -0.25
        _pat = ((_elig & (m["ucr"] == True) & _up50 & (m["rs189"] >= 70))
                | (_elig & (m["tc3"] <= 0.015) & (m["vdry_pre"] <= 0.90) & _up50 & _near & (m["rs189"] >= 80))
                | (_elig & (m["stage2"] == True) & _near & (m["base_depth25"] <= 0.15) & (m["range20"] <= 0.15) & (m["vdry_pre"] <= 0.95) & (m["rs189"] >= 80))
                | (_elig & ((m["cup_ready"] == True) | (m["cup_breakout"] == True)) & (m["rs189"] >= 80))
                | (_elig & (m["ret20"] >= 0.20) & (m["ret63"] >= 0.70) & (m["base_depth25"] <= 0.20) & _up50 & (m["rs189"] >= 85)))
        _wadd(list(m.index[_pat.fillna(False)]), "パターン")
    except Exception: pass
    try: _wadd(mkt.get("ema_touch_tk") or [], "21EMA")
    except Exception: pass
    # 複数ヒット: 【現在表示中】のセットアップ元が3つ以上（旧build_setupsの複数ヒットではない）
    _srccnt = Counter()
    for _t, _s in where.items():
        _srccnt[_t] = len(set(_s))
    multi_tk = [t for t, n in _srccnt.items() if n >= 3]
    for _t in multi_tk:
        where.setdefault(_t, []).append("複数ヒット")
    # 控え = 保有テーブル(選定が埋まるまでのRS順)に出た範囲より下＝真に次の繰上げ候補。
    _pick_set = set(t for t, _, _ in picks)
    # 保有テーブルの最終行の位置(最下位選定銘柄のcand内index位置)を求める（12未満でも正しく動く）
    _last_pos = 0
    for _pos, _tk in enumerate(cand.index):
        if _tk in _pick_set:
            _last_pos = _pos
    deck = cand.iloc[_last_pos+1:_last_pos+1+15]   # 保有表の下から15(次の繰上げ候補)
    wrows = []
    for rank, (t, r) in enumerate(deck.iterrows(), start=_last_pos+2):
        _sth = subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))
        _il, _code, _l, _rsn = leader_state(r)
        _nt, _nn, _nc = momentum_nuance(r)
        _exq = bool(r.get("excluded_theme"))
        _lag = bool(r.get("laggard"))
        _nl = bool(r.get("nonleader"))
        _lag_tag = '<span class="lagb">出遅れ</span>' if _lag else ''
        _exbadge = ('<span class="exq">除外（小型創薬）</span>' if _exq else
                    '<span class="lagb">リーダー外（選外）</span>' if _nl else _lag_tag)
        _trcls = ' class="row-excluded"' if (_exq or _nl) else ""      # 出遅れはグレーアウトしない（買う）
        wrows.append(
            f'<tr{_trcls} data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}"><td class="l mut">{rank}</td>'
            f'<td class="l tk">{t}{_risk_flag_badge(t, r.get("close"))}{_exbadge}{_chase_alert(r)}'
            f'<div class="rowsec">{_h(_sth)}</div>'
            f'<div class="rowbadges">'
            f'<span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span>'
            f'{_state_badge(_code, _nt, _nc, _rsn)}{_entry_badge(r.get("rs"), r.get("close"), r.get("ema21"))}</div></td>'
            f'<td class="rsc">{_rs_cell(r)}</td>'
            f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
            f'<td class="{color_pct(r["ret63"])}">{fmt_pct(r["ret63"])}</td>'
            f'<td class="{color_pct(r["dist52"])}">{fmt_pct(r["dist52"])}</td></tr>')
    deck_card = (f'<div class="card"><div class="hdr"><h2>RSリーダー控え</h2>{_cp(list(deck.index))}</div>'
             f'<div class="sub">保有（上位{N_PORT}リーダー）に次ぐRS順の繰上げ候補。次の隔週入替（月曜）で<b>リーダー化した順に</b>繰り上がる。'
             f'並びでどの業種が強いかも分かる。<b class="lagb" style="padding:0 4px">出遅れ</b>＝業種内−20%劣後だが<b>買う対象（タグのみ）</b>。<b class="lagb" style="padding:0 4px">リーダー外（選外）</b>＝63日RS&lt;85 or 200MA下・<b>除外（小型創薬）</b>＝臨床段階バイオ、この2つはグレーアウト＝選定/繰上げ対象外（大手バイオ/製薬/GLP-1/手術ロボは対象）。</div>'
             f'<table><tr><th class="l">#</th><th class="l">銘柄</th><th>RS</th>'
             f'<th>前日比</th><th>63日</th><th>52週高値差</th></tr>'
             + "".join(wrows) + '</table></div>')
    # 順位落ち保有カード（Core 12外だが継続条件OK＝月曜まで出口監視）
    _carry = mkt.get("carry") or []
    carry_card = ""
    if _carry:
        _TQMAP = theme_quad_map(m, s2t)
        crows = []
        for t in _carry:
            if t not in m.index:
                continue
            r = m.loc[t]
            _rk = {tk: i + 1 for i, tk in enumerate(cand.index)}.get(t, "—")
            _sth = subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))
            _il, _code, _l, _rsn = leader_state(r)
            _nt, _nn, _nc = momentum_nuance(r)
            _th = theme_of(t, s2t)
            _hh = _hv.get(t) or {}
            _due = bool(_hh.get("sell_due"))
            _due_date = _hh.get("sell_due_date")
            _carry_badge = (f'<span class="exq">売却予定 {(_due_date or "次回月曜")}</span>' if _due
                            else '<span class="carryb">順位落ち・保有中</span>')
            crows.append(
                f'<tr class="row-carry" data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}">'
                f'<td class="l mut">{_rk}</td>'
                f'<td class="l tk">{t}{_risk_flag_badge(t, r.get("close"))}{_carry_badge}'
                f'<div class="rowsec">{_h(_th)}<span class="mut" style="font-size:9px">（{_h(_TQMAP.get(_th, "—"))}）</span> ・ {_h(_sth)}</div>'
                f'<div class="rowbadges"><span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span>'
                f'{_state_badge(_code, _nt, _nc, _rsn)}{_adr_badge(r.get("adr"))}{_fade_badge(r)}</div></td>'
                f'<td class="rsc">{_rs_cell(r)}</td>'
                f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
                f'<td class="{color_pct(r["vs200"])}">{fmt_pct(r["vs200"])}</td>'
                    f'<td class="{color_pct(r["dist52"])}">{fmt_pct(r["dist52"])}</td></tr>')
        if crows:
            carry_card = (
                f'<div class="card"><div class="hdr"><h2>順位落ち保有（出口監視）</h2>{_cp(_carry)}</div>'
                f'<div class="note">トップ{N_PORT}外の前回保有を出口監視。<b>継続条件（50&gt;200MA かつ 189日RS上位{2*N_PORT}）を満たす銘柄は保有継続</b>。'
                f'条件を外した銘柄は<b>売却予定日まで建値・ピーク・正式出口を追跡</b>し、予定日後に追跡から外す。</div>'
                f'<table><tr><th class="l">#</th><th class="l">銘柄</th><th>RS</th>'
                f'<th>前日比</th><th class="th-w">200MA<br>乖離</th><th class="th-w">52週<br>高値差</th></tr>'
                + "".join(crows) + '</table></div>')
    _carry_sec = (_mkt_section("② 順位落ち保有", "継続OK／売却予定を分けて監視", en="Demoted Holdings") + carry_card) if carry_card else ""
    _deck_num = "③" if carry_card else "②"
    _rst = compute_regime_state(m, hist=mkt.get("reg_hist"))
    _regime_panel = build_regime_alerts(m, _rst, collapsible=True, hist=mkt.get("reg_hist"))
    _defense = build_defense_checklist(_rst)
    _tenbagger = build_tenbagger_l1(m)
    # 転換初動ボード: レジームが緑復帰しDD回復を検出した時のみポート前面に出す（通常はマーケット④に常設）
    _tl = mkt.get("transition_leaders")
    _surface_transition = ""
    if _tl and _tl.get("active"):
        _surface_transition = _transition_leaders_card(_tl)
    _newboard = build_new_entrants(cand)
    port = (_regime_panel
            + _defense
            + _surface_transition
            + _liq_bar()
            + (_mkt_section("① 新規参入", "36位圏外から30位以内へ飛び込んだ銘柄（今日/今週/今月）", en="New Entrants") + _newboard if _newboard else "")
            + _mkt_section("② 現在の構成", f"個別株スリーブ（N={N_PORT}・等ウェイト）", en="Current Holdings")
            + '<div class="rspbar"><button class="rsper" data-cur="189" onclick="rsPeriod(this)">RS期間: <b>189日</b> ▾（タップで63/21に切替・全表連動）</button></div>'
            + port
            + _carry_sec
            + _mkt_section(f"{_deck_num} 控え", "次の入替で上がってくる候補", en="Bench") + deck_card
            + _tenbagger)
    search_card = (
        '<div class="card"><h2>銘柄検索</h2>'
        '<div class="sub">ティッカーで全ユニバースを検索（タップで詳細）</div>'
        '<input id="tksearch" class="tksearch" type="text" inputmode="search" autocomplete="off" '
        'placeholder="例: NVDA" oninput="tkSearch(this.value)">'
        '<div id="tkresults" class="tkresults"></div></div>')
    # ---- TAB ピックアップ：初期の構成へ復帰。
    #   絞り込み順に、重なり → 単独シグナル → 圧縮・ベース → リーダー母集団 → 道具。
    today = (search_card
        + _liq_bar()
        + (mkt.get("ema_touch") or "")
             + _mkt_section("① 重なりで絞る", "兆候が4つ以上そろった銘柄", en="Signal Confluence")
             + build_confluence_watch(m, cand)
             + _mkt_section("② 単独シグナル", "ポケットピボット・押し目・パターン", en="Single Signals")
             + build_pocket_pivots(m) + _buy_today_card(buytoday) + _patterns_card(patterns)
             + _mkt_section("③ 圧縮・ベース", "VCP・保ち合い・ブレイク近", en="VCP / Base")
             + _vcp_card(vcp_rows)
             + _mkt_section("④ 底打ち（構造ピボット）", "安値切り上げ＋出来高減で下げ止まり。RS63主軸・構造のみ", en="Structure Pivot")
             + build_structure_pivot_screen(m, s2t)
             + _mkt_section("⑤ W30ブレイク（30週線）", "金曜クローズ確定→翌週寄り。◎本格が本線・△ギリ抜けは警戒", en="W30 Breakout")
             + build_w30_breakouts(m, e2j=e2j)
             + _mkt_section("⑥ リーダー母集団", "RS≥85・200MA上を状態別に", en="Leaders")
             + leaders_card)

    # ---- §4: collect every displayed ticker + build compact detail data (DET)
    tapset = set()
    for _t, _, _ in picks: tapset.add(_t)
    for _lst in setups.values(): tapset.update(_lst)
    for _st in by_state.values():
        for _x in _st: tapset.add(_x["t"])
    for _x in buys: tapset.add(_x["t"])
    for _x in buytoday: tapset.add(_x["t"])
    for _x in vcp_rows: tapset.add(_x["t"])
    tapset.update(nh_list); tapset.update(multi_tk); tapset.update(list(deck.index))
    tapset.update(where.keys())   # 詳細モーダルの登場箇所に出る全銘柄はスパークライン対象に
    try:   # RSタブの各期間Top10（rs_pool内）もスパークライン対象に
        _pooldf = m[m["rs_pool"].fillna(False)] if ("rs_pool" in m.columns) else m
        for _col in ("rs63", "rs126", "rs189"):
            if _col in _pooldf.columns:
                tapset.update(_pooldf.sort_values(_col, ascending=False).head(10).index)
    except Exception:
        pass
    try:   # Movers表示分（値動き上位/下位20）もスパークライン対象に
        _mv = m[setup_eligible(m)]
        for _col in ("ret1", "ret5", "ret21"):
            if _col in _mv.columns:
                _sv = _mv[_col].dropna().sort_values()
                tapset.update(_sv.head(20).index); tapset.update(_sv.tail(20).index)
    except Exception:
        pass
    try:   # 各セットアップカードの表示銘柄もスパークライン対象に（タップ詳細でチャートを出す）
        if hasattr(m, "index"):
            if "sp" in m.columns:
                tapset.update([t for t in m.index if isinstance(m.at[t, "sp"], dict)])           # 底打ち構造ピボット
            if "pp_days" in m.columns:
                tapset.update([t for t in m.index if (m.at[t, "pp_days"] == 0)])                 # ポケットピボット
            if "w30x" in m.columns:
                tapset.update([t for t in m.index if bool(m.at[t, "w30x"])])                     # W30ブレイク
    except Exception:
        pass
    det_json = _det_json(m, names, set(m.index), _build_det_extra(m, s2t, s2i, e2j, picks, deck, buytoday, nh_list, where, mkt.get("hold")))   # 全ユニバース（検索＆タップ詳細）
    # タップ詳細に出す簡易チャート（スパークライン）を tapset ぶん生成
    spark_map = {}
    try:
        if W is not None and isinstance(W.get("Close"), pd.DataFrame):
            _C = W["Close"]
            for _tk in sorted(tapset):        # #13 生成順=gid(spkN)割当順。setだとPYTHONHASHSEED依存→sortedで決定的
                if _tk not in _C.columns:
                    continue
                _s = _C[_tk].dropna()
                if len(_s) < 20:
                    continue
                _vals = list(_s.items())
                _col = "#1E7A4D" if float(_s.iloc[-1]) >= float(_s.iloc[-min(len(_s), 126)]) else "#C2453A"
                _sv = _spark(_vals, days=126, color=_col)
                if _sv:
                    spark_map[_tk] = _sv
    except Exception:
        pass
    mkt["_spark_map"] = spark_map
    dov = ('<div id="dov-bg" class="dov-bg"><div class="dov" onclick="event.stopPropagation()">'
           '<div class="dov-h"><span id="dov-tk" class="dov-tk"></span>'
           '<span style="display:flex;gap:8px;align-items:center"><button class="cp cp-one" onclick="copyOne(event, document.getElementById(\'dov-tk\').textContent)" title="銘柄コードをコピー">コピー</button>'
           '<a id="dov-tv" class="dov-tv" target="_blank" rel="noopener" title="TradingViewで開く">TV↗</a>'
           '<span class="dov-x" onclick="hideDet()">✕</span></span></div>'
           '<div id="dov-spark" class="dov-spark empty"></div>'
           '<div id="dov-status" class="dov-status"></div>'
           '<div id="dov-meta" class="dov-meta"></div>'
           '<div id="dov-loc" class="dov-loc"></div>'
           '<div id="dov-body" class="dov-grid"></div>'
           '<div class="dov-note">タップした銘柄のデータ（全リスト共通）</div>'
           '</div></div>')

    # ---- TAB 業種RS（サブテーマ単位）
    def _chip(t, rs):
        _ok = (rs == rs)
        _rs = f'{rs:.0f}' if _ok else '—'
        _hot = ' hot' if (_ok and rs >= 90) else ''
        return (f'<span class="chip{_hot}" data-tkone="{t}">{t}'
                f'<span class="rsb">{_rs}</span></span>')
    def _dz(x): return f'{x:.5f}' if (x is not None and x == x) else 'nan'
    _rotcol = {"初動": "#4ade80", "改善": "#7dd3fc", "強い継続": "#a78bfa", "監視": "#9fb0c5", "弱い": "#6b7280"}
    srows = []
    for i, s in enumerate(sectors, 1):
        chips = "".join(_chip(t, rs) for t, rs in s.get("members", []))
        _rot = s.get("rot", "弱い"); _rc = _rotcol.get(_rot, "#9fb0c5")
        _rotord = {"初動": 5, "改善": 4, "強い継続": 3, "監視": 2, "弱い": 1}.get(_rot, 0)
        srows.append(
            f'<tbody class="secgrp" data-score="{s["score"]:.3f}" data-d1="{_dz(s.get("d1"))}" '
            f'data-w1="{_dz(s.get("w1"))}" data-m1="{_dz(s.get("m1"))}" data-rot="{_rotord}">'
            f'<tr class="secrow" onclick="secToggle(\'sec{i}\')">'
            f'<td class="l mut secnum">{i}</td>'
            f'<td class="l tk" style="font-size:12px">{_h(s["ja"])} <span class="secx">▾</span>'
            f'<span class="mut" style="font-size:10px;font-weight:400"> {s["n"]}社・RS{s["score"]:.0f}</span>{_rs_arrow(s.get("drs"), th=3)}'
            f'<div class="secparent">{_h(s.get("parent","—"))}</div></td>'
            f'<td><span class="rotb" style="color:{_rc};border-color:{_rc}66">{_rot}</span></td>'
            f'<td class="{color_pct(s.get("d1"))}">{fmt_pct(s.get("d1"))}</td>'
            f'<td class="{color_pct(s.get("w1"))}">{fmt_pct(s.get("w1"))}</td>'
            f'<td class="{color_pct(s.get("m1"))}">{fmt_pct(s.get("m1"))}</td></tr>'
            f'<tr id="sec{i}" class="secsub"><td></td>'
            f'<td colspan="5"><div class="secchips">{_cp([t for t, _ in s.get("members", [])])}{chips}</div></td></tr>'
            f'</tbody>')
    _imp = sorted([x for x in sectors if x.get("drs", 0) >= 5], key=lambda x: -x["drs"])[:5]
    _wor = sorted([x for x in sectors if x.get("drs", 0) <= -5], key=lambda x: x["drs"])[:5]
    _shift = ""
    if _imp or _wor:
        _shift = ('<div class="shiftrow">'
                  + (('<span class="shl">改善</span>' + "".join(f'<span class="chip shp">{_h(x["ja"])} <b>+{x["drs"]:.0f}</b></span>' for x in _imp)) if _imp else "")
                  + (('<span class="shl shl-n">悪化</span>' + "".join(f'<span class="chip shn">{_h(x["ja"])} <b>{x["drs"]:.0f}</b></span>' for x in _wor)) if _wor else "")
                  + '</div>')
    sector = (f'<div class="card"><h2>サブテーマ別RS（ユニバース内）</h2>'
              f'<div class="sub">構成銘柄の<b>63日RS×189日RS</b>（中央値・均等ブレンド）をサブテーマ単位で0-100ランク（≥2社）。'
              f'<b>状態</b>＝ローテの局面（初動→改善→強い継続→監視→弱い）。▲▼＝約1ヶ月前との差＝資金の向き。'
              f'<b>見出しタップで並べ替え</b>・行タップで構成銘柄。市場全体の強弱</div>'
              + _shift +
              f'<table class="secrs"><thead><tr><th class="l">#</th>'
              f'<th class="l sortable act" onclick="secSort(\'score\',this)">サブテーマ <span class="so">⇅RS</span></th>'
              f'<th class="sortable" onclick="secSort(\'rot\',this)">状態</th>'
              f'<th class="sortable" onclick="secSort(\'d1\',this)">日</th>'
              f'<th class="sortable" onclick="secSort(\'w1\',this)">週</th>'
              f'<th class="sortable" onclick="secSort(\'m1\',this)">月</th></tr></thead>'
              + "".join(srows) + '</table></div>')

    # 強い業種の主導株（強いグループ×その中で個別も強い銘柄＝O'Neil「強い株を強いグループで」）
    _sl_rows = ""
    _sl_all = []
    for s in sectors[:8]:                          # 強さ上位8サブテーマ
        leads = []
        for t, _rs63 in (s.get("members") or []):
            if t not in m.index:
                continue
            rr = m.loc[t]
            rs189 = rr.get("rs189"); cl = rr.get("close"); s200 = rr.get("sma200")
            if (rs189 == rs189 and rs189 >= 85 and cl == cl and s200 == s200 and cl > s200):
                leads.append((t, float(rs189), float(rr.get("dvol") or 0)))
            if len(leads) >= 3:
                break
        if not leads:
            continue
        chips = "".join(
            f'<span class="chip hot" data-liq="{dv/1e6:.1f}" data-tkone="{t}">{t} '
            f'<span class="mut" style="font-size:10px">RS{rs:.0f}</span></span>' for t, rs, dv in leads)
        _sl_all += [t for t, _, _ in leads]
        _sl_rows += (f'<div class="slrow"><div class="slname">{_h(s["ja"])}'
                     f'<span class="mut" style="font-size:11px">（{_h(s.get("parent","—"))}・強さ{s.get("score",0):.0f}）</span></div>'
                     f'<div class="chips">{chips}</div></div>')
    sector_leaders = ("" if not _sl_rows else
        f'<div class="card"><div class="hdr"><h2>強い業種の主導株</h2>{_cp(_sl_all)}</div>'
        f'<div class="sub"><b>強い業種（RS上位サブテーマ）× その中で個別も強い銘柄</b>（189日RS≥85・200MA上）＝'
        f'O\'Neil「強い株を、強いグループで」。上位8業種の主導株を最大3つずつ・タップで詳細。'
        f'業種の強さと個別の強さが揃った所が、順張りの一等地。</div>{_sl_rows}</div>')

    # ---- TAB マーケット
    market = (
        # ═══ 5章構成: 結論と行動 / 温度計 / 先行灯 / 転換 / 口座と参考 ═══
        _mkt_section("① 結論と行動", "今日・1週間・1カ月・ローテを一画面", en="Verdict & Action")
        + banner
        + comment
        + rotation
        + _changelog_card(mkt.get("chlog"), mkt.get("chref"))
        + _mkt_section("② 相場の強さ", "広がり・参加度・主導株", en="Market Strength")
        + _svg_mri(mkt.get("mri_ts", []))
        + _perf_card(mkt.get("perf", {}))
        + _svg_breadth(mkt.get("breadth_ts", []), breadth["n"])
        + _dollarvol_card(mkt.get("dollarvol_ts"))
        + _updown_vol_card(mkt.get("updown_ts"))
        + _leader_temp_card(mkt.get("leader_temp"))
        + _leader_run_card(mkt.get("leader_run"))
        + _svg_ratio_card(mkt.get("adline_ts", []),
                          "騰落ライン（マクレラン・オシレーター）",
                          "0超＝買いが広い／0割れ＝売りが広い。株価と逆行なら内部の崩れ（マクレラン・オシレーター）",
                          "広がり加速（内部良好）", "広がり失速（内部悪化・要警戒）",
                          "#58a6ff", "ad", show_value=True, zero_ref=True)
        + _svg_ratio_card(mkt.get("defensive_ts", []),
                          "攻守ローテーション（一般消費財 / ディフェンシブ）",
                          "一般消費財÷ディフェンシブのσ。プラス＝攻め優勢／マイナス＝守り優勢",
                          "攻め優勢", "守り優勢", "#a78bfa", "dg", zero_ref=True, unit="σ")
        + _mkt_section("③ 崩れの兆し", "リーダー脱落・勢い・下落余地", en="Warning Signs")
        + build_regime_alerts(m, mkt.get("regime_state"), hist=mkt.get("reg_hist"))
        + (mkt.get("net_liq_card") or "")
        + (mkt.get("macro_pulse") or "")
        + _svg_ratio_card(mkt.get("credit_ts", []),
                          ("クレジット推移（HYG / IEI）" if mkt.get("credit_den") == "IEI"
                           else "クレジット推移（HYG / LQD）"),
                          ("HYG÷米国債(IEI)のσ。プラス＝リスクオン／マイナス＝信用警戒。"
                           if mkt.get("credit_den") == "IEI"
                           else "HYG÷投資適格債のσ。プラス＝リスクオン／マイナス＝信用警戒"),
                          "リスクオン", "信用悪化・警戒", "#fbbf24", "cg", zero_ref=True, unit="σ")
        + _svg_vixterm_card(mkt.get("vixterm_ts", []))
        + _expected_move_card(mkt.get("expmove"))
        + _dd_card(mkt.get("distrib", {}))
        + _sentiment_card(mkt.get("senti"))
        + _mkt_section("④ 反転の確認", "FTDと復帰候補（調整中のみ）", en="Reversal")
        + _transition_leaders_card(mkt.get("transition_leaders"))
        + _ftd_card(mkt.get("ftd", []))
        )

    _wk_stance = {"Blue": "攻め継続", "Green": "攻め", "Yellow": "維持・守り寄り", "Red": "守り・現金化"}.get(sar[0], "—")
    _wk_gate = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}.get(sar[0], "—")
    _wk_em = bool((mkt.get("emergency") or {}).get("active"))
    _bd_pa50  = (f'{breadth["pa50"]:.0f}%'  if _finite(breadth.get("pa50"))  else "—")
    _bd_adpct = (f'{breadth["adpct"]:.0f}%' if _finite(breadth.get("adpct")) else "—")
    _bd_pnh   = (f'{breadth["pnh"]:.1f}%'   if _finite(breadth.get("pnh"))   else "—")
    _wk_concl = ('<div class="card" style="border:1.5px solid rgba(56,189,248,.35)">'
                 '<h2>今週の結論 <span class="h2en">This Week</span></h2>'
                 f'<div style="font-size:13px;line-height:1.7"><b>ゲート基準の来週姿勢</b>（NQトレンド色）：<b>{_wk_stance}</b>（{_wk_gate}）</div>'
                 f'<div class="mut" style="font-size:11px;margin-top:3px">環境確認（露出判断の補助）：50日線上 <b>{_bd_pa50}</b>　・　非常口 <b>{"発動中" if _wk_em else "未発動"}</b></div>'
                 '<div class="sub" style="margin:6px 0 0">①で来週のイベント、②で今週の地合いと騰落、'
                 '③でブレッドスとレバ環境、④で口座の結果を確認。この4点で来週の基本姿勢（攻め/維持/守り）を決める。</div></div>')
    _alloc_body, eqlog = _alloc_tab(mkt.get("calc"), mkt.get("equity"))
    equity_tab = (
        eqlog
        + _equity_card(mkt.get("equity"), mkt.get("eq_attrib"))
        + _emergency_card(mkt.get("emergency"))
    )

    mkt_weekly = (
        _wk_concl

        + _mkt_section("① 来週の準備", "週末に確認する経済指標と構造マクロ（低頻度で効く）", en="Week Ahead")
        + (mkt.get("econ_cal") or "")
        + (mkt.get("weekly_macro") or "")
        + (mkt.get("rates_card") or '<div class="card"><h2>金利レジーム</h2><div class="sub">FRED未取得</div></div>')
        + (mkt.get("pressure_card") or "")
        + (mkt.get("wk_diff") or "")
        + _mkt_section("② 今週の地合い", "地合いの帯で1週間を振り返る（詳細な推移はDaily）", en="Market Week")
        + '<div class="card"><h2>地合いの帯 <span class="h2en">Regime History</span></h2>'
        + _ribbon(mkt.get("trend_hist"))
        + '</div>'
        + (mkt.get("wk_board") or "")
        + _mkt_section("③ 環境の質", "広がり・データ品質・レバ環境", en="Environment Quality")
        + f'<div class="card"><h2>広域ブレッドス</h2>'
        f'<div class="sub">50日線上の比率・当日の騰落・52週高値圏（200日線上の比率はDailyのブレッドス推移を参照）</div>'
        f'<div class="kv"><span class="k">50MA上</span><span class="v">{_bd_pa50}</span></div>'
        f'<div class="kv"><span class="k">上昇/下落</span><span class="v">{breadth["adv"]} / {breadth["dec"]} '
        f'<span class="mut" style="font-size:11px">({_bd_adpct} up)</span></span></div>'
        f'<div class="kv"><span class="k">52週高値圏</span><span class="v">{breadth["nh"]} '
        f'<span class="mut" style="font-size:11px">({_bd_pnh})</span></span></div></div>'
        + _quality_card(mkt.get("quality"))
        + _lev_env_card(mkt.get("lev_env"), mkt.get("rrg"))
        + _mkt_section("④ 口座の答え合わせ", "カーブ×21EMA（残高・非常口・資産曲線はPositions）", en="Account Review")
        + (mkt.get("wk_acct") or ""))

    # ---- TAB RS比較（RS189主軸・RS63/126は補助監視）
    rs_compare = _rs_compare_tab(m, picks, s2i, e2j, s2t, mkt.get("rs_continuity"))

    # ---- TAB ルール (確定版 2026-06-26)
    cur_jp = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}.get(sar[0])
    exp_rows = [("青", "c-bl", "100%", "100%"), ("緑", "c-gr", "100%", "50%"),
                ("黄", "c-yl", "100%（新規停止）", "0%（撤退）"), ("赤", "c-rd", "0%（全現金）", "0%（全撤退）")]
    nq_rows = ""
    for cj, cls, indv, lev in exp_rows:
        hl = ' class="hl"' if cj == cur_jp else ""
        nq_rows += (f'<tr{hl}><td class="l"><span class="nqd {cls}"></span>{cj}'
                    f'{"（現在）" if cj == cur_jp else ""}</td><td>{indv}</td><td>{lev}</td></tr>')
    cur_line = ""
    if cur_jp:
        em = {"青": ("100%", "100%"), "緑": ("100%", "50%"),
              "黄": ("100%（新規停止・既存0.70）", "0%"), "赤": ("0%", "0%")}[cur_jp]
        cur_line = (f'<div class="sub" style="margin-top:8px">現在の地合い：<b style="color:#e6edf3">{cur_jp}</b>'
                    f' → 個別 {em[0]} ／ レバ {em[1]}</div>')
    rules = (
        f'<div class="card"><h2>Core 12 システムルール（v2・確定） <span class="h2en">Core 12 Rules</span></h2>'
        f'<div class="sub" style="color:#c7d2fe">相場の方向でリスク量を4段階に調整し、その中で最も強い{N_PORT}銘柄を等分で持つ。負けは早く小さく、勝ちは伸ばす。ルールは事前に固定し、その日の気分で動かさない。</div>'
        f'<div class="mut" style="font-size:11px;margin:4px 0 0;padding:6px 9px;background:#3d2a08;color:#fde68a;border:1px solid #ca8a04;border-radius:7px">これは<b>Core 12（システム選定）専用</b>のルール。裁量スイングは別ルール（+25%で1/3利確・21EMA割れ撤退）で、Positionsの各保有に戦略別の出口を表示。</div>'
        f'<div class="rh">配分</div>'
        f'<div class="sub">個別株 <b>{ALLOC[0]}%</b> ／ レバレッジ <b>{ALLOC[1]}%</b>'
        + (f' ／ 現金 <b>{ALLOC[2]}%</b>' if ALLOC[2] > 0 else '')
        + f'。総資産の<b>76%以上</b>をこのシステムに置く。想定ドローダウンは中央値<b>−37〜44%</b>。これに耐えるサイズにし、恐怖で減らさず強気でも増やさない。</div>'
        f'<div class="rh">土台：4色の地合いゲートで露出を調整</div>'
        f'<div class="sub">毎日トレンドの色を確認し、変わったら翌日の寄りで露出を下表に合わせる（前日終値で確定）。色は手動（TradingView）で読むのが正。</div>'
        f'<table class="nqt"><tr><th class="l">色</th><th>個別株</th><th>レバ(TQQQ/SOXL)</th></tr>{nq_rows}</table>'
        + cur_line +
        f'<div class="sub mut" style="margin-top:6px">黄：個別は持ち続ける（出口は max(建値×0.75, ピーク×0.70) のまま変更なし）。レバは黄で撤退。</div>'
        f'<div class="rh">個別株スリーブ（{ALLOC[0]}%）</div>'
        f'<ul class="rules">'
        f'<li><b>選定</b>（隔週・月曜）：<b>189日RS</b>（≒9ヶ月の相対的な強さの順位）の上位{N_PORT}銘柄。条件は 50日線&gt;200日線・売買代金$10M/日以上・株価$5以上。<b>買うのはリーダー（63日RS≥85 かつ 200MA上）の中だけ</b>——リーダー外は買わない。<b>出遅れ（業種内−20%劣後）は買う</b>（タグのみ）。小型創薬（臨床段階バイオ）は対象外。<b>各1/{N_PORT}を等分</b>、テーマ上限なし。</li>'
        f'<li><b>継続</b>（隔週トゥルーアップ・月曜）：50日線&gt;200日線・<b>189日RS上位{2*N_PORT}</b>を満たす限り保有。崩れた枠だけ売り、新しいトップRSで{N_PORT}に補充。ランクが下がっただけでは即売りしない。</li>'
        f'<li><b>出口</b>：<b>初期ストップ = 建値×0.75</b> → 伸びたら<b>ピーク×0.70トレール</b>（黄も0.70）。<b>Core 12は途中利確なし</b>（固定利確ライン・二層出口＝+3R部分利確は不採用）。'
        f'<span class="mut">52週高値−10%以内は追いが−0.28Rの傾向のため⚠表示するが、機械選定は続行（指値で待つのは裁量の任意）。黄=新規停止・保有継続、赤=全撤退。</span></li>'
        f'<li><b>初期ストップ</b>：建値<b>×0.75（−25%）</b>で全売り。<b>クールダウンなし</b>——切られてもRS上位12・適格なら次の隔週で即復帰。</li>'
        f'</ul>'
        f'<div class="rh">レバレッジスリーブ（{ALLOC[1]}%）</div>'
        f'<ul class="rules">'
        f'<li><b>構成</b>：TQQQ 50 ： SOXL 50。ただし<b>SOXXの50日線&lt;100日線</b>の間はSOXLを外し全額TQQQ（半導体の下落トレンドで3xを回避）。</li>'
        f'<li><b>SOXL投入帯</b>：SOXLは<b>SOXXが50MAの+0〜3%上</b>にある日だけ新規投入する（青/緑の日）。この帯は建て直後の逆行が最も浅く、<b>−25%級の大事故がおよそ半分</b>に減る。支持線がすぐ下にあり、割れたら即撤退できるため深傷になりにくい。'
        f'<b>投入は1/3ずつ×3トランシェ</b>（各サイズはボラターゲットでスケール）。<b>撤退の目安＝SOXXが50MAを終値で割ったら新規投入を止める</b>（保有は地合いルールに従う）。'
        f'<b>50MA割れ・+3%超乖離の日はSOXLを入れずTQQQのみ</b>。距離で削れるのは大事故の確率まで。最良の帯でも平均−11%・3割で−15%の初期逆行は覚悟してサイズを決める。0〜+3%帯は青緑日の約17%＝月3〜4回来るので待機は長くない。</li>'
        f'<li><b>ゲート</b>：両ETFとも地合いで露出を＝<b>青100 ／ 緑50 ／ 黄0 ／ 赤0</b>。執行は翌寄り・確認日数ゼロ（3xは執行の遅れがドローダウンを増幅するため即応）。</li>'
        f'</ul>'
        f'<div class="rh">リバランスと例外</div>'
        f'<ul class="rules">'
        f'<li>能動的に動くのは基本<b>地合いの色</b>だけ。変われば翌寄りで%を合わせる（同じ銘柄のまま増減）。</li>'
        f'<li><b>スリーブ配分（{ALLOC[0]}/{ALLOC[1]}・TQQQ:SOXL比）のリセットは隔週月曜</b>（銘柄入替と同日）。ゲート露出とSOXL除外の切替は<b>即日</b>（別サイクル）。</li>'
        f'<li><b>赤入り</b>＝両スリーブ全現金。<b>赤明けは翌寄りで即、最新トップ{N_PORT}を選び直す</b>（次回リバランスを待たない）。<b>SOXLは投入帯（SOXX 50MAの+0〜3%）から段階1/3×3で入り直し</b>（赤で段階カウンタは0にリセット・帯外ならTQQQのみ）。</li>'
        f'<li>ストップ／トレールで出た現金は<b>次回リバランスまで現金で保持</b>（期中に再投下しない）。</li>'
        f'<li>保有株が弱っても<b>トレール・ストップ以外では動かさない</b>（SAR弱気・200日割れ・RS低下だけでは売らず、隔週月曜で処理）。</li>'
        f'</ul>'
        f'<div class="rh">非常口（ジリ下げ相場の安全弁）</div>'
        f'<ul class="rules">'
        f'<li><b>自動化済み</b>：equity.csvの口座NAVが過去ピークから<b>−28%</b>以下、<b>かつ</b>QQQ円建てに対する12ヶ月相対が<b>−12%</b>以下で<b>レバ枠を自動半減</b>。両方が回復（DD&gt;−20% かつ 相対&gt;−8%）するまで維持し、状態はstate.jsonに保存。データ不足時、すでに発動中なら安全側で半減を維持する。</li>'
        f'</ul>'
        f'<div class="rh">やらないこと</div>'
        f'<ul class="rules">'
        f'<li>その日の裁量で仕掛けない（エントリーは事前ルールのみ・押し目／ブレイク待ちの裁量はしない）。</li>'
        f'<li>途中の値動きで利確しない（利確はトレールに任せる）。</li>'
        f'<li>業績（EPS・売上）や業種で銘柄を絞らない（選定は価格の強さ＝RSのみ）。</li>'
        f'<li>地合いの色を自動推定で代用しない（手動が正）。赤明け・色変化で確認日数を置かない。</li>'
        f'</ul>'
        f'<div class="warn">⚠ 数字の読み方：個別のCAGRは<b>生存バイアス</b>で上振れ（最大の割引要因）、レバは強気相場で上振れ。全数字は「どの構成が優れているか」の相対比較であり、絶対リターンの予測ではない（主指標はSharpeと最大DD）。'
        f'公称成績は「どの月曜から数えるか」で<b>+5pt CAGR相当の運</b>を含む（位相平均でCAGR2〜3pt・Sharpe0.05〜0.07を割り引いて読む）。'
        f'地合いの色は手動が正で、自動推定は復元FSM＝<b>方向は99.04%一致（±2日以内97%）</b>。'
        f'真のドローダウンは<b>−37〜44%級・テール（最悪5%）は−73%〜</b>を想定してサイズを決める。</div></div>')

    body = (_data_health_banner(mkt)
            + build_today_action(sar, mkt, asof)
            + '<nav>'
            '<a class="tabx on" href="#t-market" onclick="tab(\'t-market\',this);return false;">Daily</a>'
            '<a class="tabx" href="#t-alloc" onclick="tab(\'t-alloc\',this);return false;">Positions</a>'
            '<a class="tabx" href="#t-port" onclick="tab(\'t-port\',this);return false;">Core 12</a>'
            '<a class="tabx" href="#t-today" onclick="tab(\'t-today\',this);return false;">Setups</a>'
            '<a class="tabx" href="#t-rotation" onclick="tab(\'t-rotation\',this);return false;">Rotation</a>'
            '<a class="tabx" href="#t-movers" onclick="tab(\'t-movers\',this);return false;">Movers</a>'
            '<a class="tabx" href="#t-rs" onclick="tab(\'t-rs\',this);return false;">RS</a>'
            '<a class="tabx" href="#t-weekly" onclick="tab(\'t-weekly\',this);return false;">Weekly</a>'
            '<a class="tabx" href="#t-post1" onclick="tab(\'t-post1\',this);return false;">Publish</a>'
            '<a class="tabx" href="#t-rules" onclick="tab(\'t-rules\',this);return false;">Rules</a></nav>'
            f'<section id="t-market" class="on">{market}</section>'
            f'<section id="t-rotation">'
            + _mkt_section("① ローテーションの向き（RRG）", "改善→主導→弱化→停滞の時計回り（視覚的な全体像）", en="Rotation Direction (RRG)")
            + f'{_rrg_card(mkt.get("rrg_etf"), None, mkt.get("etf_hier"), 100, "セクター・ローテーション（テーマETF）", _RRG_ETF_DESC)}'
            + _mkt_section("② 強い業種の主導株", "強いグループ×個別も強い＝順張りの一等地", en="Leaders in Strong Groups")
            + f'{sector_leaders}'
            + _mkt_section("③ 大枠（セクターETF）", "市場全体のセクター資金フロー・大分類", en="Sector ETFs")
            + f'{_heatmap_card(mkt.get("sector_ranks"))}'
            + f'{_sector_rank_card(mkt.get("sector_ranks"))}'
            + _mkt_section("④ サブテーマ別RS（詳細）", "見出しタップで並べ替え・行タップで構成銘柄", en="Sub-Theme RS")
            + f'{sector}</section>'
            f'<section id="t-movers">{build_movers_tab(m, s2t)}</section>'
            f'<section id="t-rs">{rs_compare}</section>'
            f'<section id="t-today">{today}</section>'
            f'<section id="t-port">{port}</section>'
            f'<section id="t-alloc">'
            + _mkt_section("トレード計画・保有記録", "買う前に株数・撤退・部分利確を決め、そのまま保有に記録", en="Plan & Holdings")
            + _swing_planner_card()
            + _alloc_body
            + _mkt_section("資産推移・口座", "資産曲線・要因分解・非常口ブレーキ", en="Equity & Account")
            + equity_tab + '</section>'
            f'<section id="t-weekly">{mkt_weekly}</section>'
            f'<section id="t-rules">{rules}</section>'
            f'<section id="t-post1">'
            + _mkt_section("マーケット概略", "SNS共有用カード", en="Market Overview")
            + '__POSTCARD1__'
            + _mkt_section("セクター・ローテーション", "SNS共有用カード", en="Sector Rotation")
            + '__POSTCARD2__</section>')

    # #10 分析用の唯一の基準日は asof_bar（価格DataFrameの実確定営業日）。ヘッダもこれを表示する。
    #   生metadataのasof（キャッシュ取得時刻。2099等の誤値が入り得る）は「取得」として別表示にし、分析日とは混同しない。
    _an_asof = None
    try:
        _ab = (mkt or {}).get("asof_bar")
        if _ab is not None:
            _an_asof = pd.Timestamp(_ab).strftime("%Y-%m-%d")
    except Exception:
        _an_asof = None
    _fetch_disp = ""
    if asof:
        try:
            _ts = pd.Timestamp(asof)
            if _ts.tzinfo is None:
                _ts = _ts.tz_localize("UTC")
            _fetch_disp = _ts.tz_convert("Asia/Tokyo").strftime("%Y-%m-%d %H:%M JST")
        except Exception:
            _fetch_disp = ""
    if _an_asof:
        asof_disp = "分析基準日 " + _an_asof + (f"　取得 {_fetch_disp}" if (_fetch_disp and not _fetch_disp.startswith(_an_asof)) else "")
    else:
        asof_disp = ("更新 " + _fetch_disp) if _fetch_disp else ""
    _thex = {"Blue": "#1d4ed8", "Green": "#16a34a", "Yellow": "#ca8a04", "Red": "#dc2626"}.get(sar[0], "#0b0f17")
    html = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='theme-color' content='" + _thex + "'>"
            "<meta name='apple-mobile-web-app-capable' content='yes'>"
            "<meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'>"
            "<title>Command Center</title><meta name=\"color-scheme\" content=\"dark\"><style>" + CSS + "</style></head><body>"
            "<div class='wrap'><header><h1>Command Center</h1>"
            f"<div class='asof'>{asof_disp}</div></header>"
            + body + dov
            + "<div id='hierModal' class='hier-modal' onclick=\"this.classList.remove('on')\"><div class='hier-box' onclick='event.stopPropagation()'></div></div>"
            + "<footer class='disc'>※個人の研究用ダッシュボードであり、投資助言ではありません</footer>"
            + "</div>"
            + "<script>window.DET=" + _json_for_script(det_json) + ";</script>"
            + "<script>window.HIER=" + _json_for_script(mkt.get("etf_hier") or {}) + ";</script>"
            + "<script>window.CALC=" + _json_for_script(mkt.get("calc") or {}) + ";</script>"
            + "<script>window.SWING=" + _json_for_script(swing_data) + ";</script>"
            + "<script>" + JS + "</script></body></html>")
    html = _inject_en_titles(html)
    html = _lightpass(html)
    # 投稿カードはAlmanacライトで生成済みのため、lightpass後に注入して二重変換を防ぐ
    html = html.replace('</head>', '<style>' + POST_CSS + '</style></head>', 1)
    html = html.replace('</body>', '<script>' + POST_JS + '</script></body>', 1)
    html = html.replace('__POSTCARD1__', _post_iframe(mkt.get('post1_html')), 1)
    html = html.replace('__POSTCARD2__', _post_iframe(mkt.get('post2_html')), 1)
    # タップ詳細の簡易チャート（スパークライン）。lightpass後に注入して色変換を回避
    try:
        _spark_json = _json_for_script(mkt.get("_spark_map") or {})
    except Exception:
        _spark_json = "{}"
    html = html.replace('</body>', '<script>window.SPARK=' + _spark_json + ';</script></body>', 1)
    return html

# ============================================================================= Almanacライトテーマ変換（ビルド時パス）
#   ロジックはダーク正本と完全同一のまま、最終HTMLの配色だけをライトへ変換する。
#   ① 無彩色（低彩度）は明度を反転して暖色紙トーンへ（ダーク背景→紙色／明色文字→濃インク）
#   ② 有彩色（意味色: 緑/赤/琥珀/青）は色相・彩度を保持し、紙面で読めるよう明るすぎる色だけ暗くする
#   ③ CSSルール単位・インラインstyle単位で文字色と背景のコントラストを検査し、4.0未満を自動補正
#   ④ rgba()の無彩色サーフェス（nav等）を反転、カラー・スキームをlightへ
import colorsys as _cs

_LP_PAPER = "#eceae3"          # 紙色（実効背景・デプロイ済みライト版の実測値）
_LP_WARM_H = 47 / 360.0        # 暖色の色相（実測紙色に一致）

def _lp_hx2rgb(hx):
    hx = hx.lstrip("#")
    if len(hx) == 3:
        hx = "".join(c * 2 for c in hx)
    return tuple(int(hx[i:i+2], 16) for i in (0, 2, 4))

def _lp_rgb2hx(r, g, b):
    return "#%02x%02x%02x" % (max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))

def _lp_lum(hx):
    def lin(u):
        u /= 255.0
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    r, g, b = _lp_hx2rgb(hx)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

def _lp_ct(fg, bg):
    l1, l2 = _lp_lum(fg), _lp_lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

def _lp_map_hex(hx):
    """1色のダーク→ライト写像。無彩色判定はクロマ（チャンネル差）基準
       ※HLS彩度は淡色・濃色で跳ね上がり #0b0f17 / #e6edf3 を誤って有彩色扱いするため不採用。"""
    r, g, b = _lp_hx2rgb(hx)
    h, l, s = _cs.rgb_to_hls(r / 255, g / 255, b / 255)
    chroma = (max(r, g, b) - min(r, g, b)) / 255.0
    cool = 0.52 <= h <= 0.75                      # 190-270°: ダークUIの構造色（濃紺グレー/青グレー）
    if chroma < 0.09 or (cool and chroma < 0.20):
        # 無彩色・構造色: 端の明度は反転、中間明度は保持し、いずれも暖色トーンへ
        if l < 0.35 or l > 0.65:
            nl = 1.03 - l
        else:
            nl = l
        nl = max(0.10, min(0.94, nl))
        ns = 0.13 if nl > 0.55 else 0.06
        rr, gg, bb = _cs.hls_to_rgb(_LP_WARM_H, nl, ns)
        return _lp_rgb2hx(rr * 255, gg * 255, bb * 255)
    # 有彩色（意味色）: 色相は基本保持しつつ、アルマナック紙面に馴染む彩度へ丸める
    nl = max(0.33, l - 0.33) if l > 0.66 else l   # 紙面で飛ぶ明るい色だけ暗く
    ns, nh = min(s, 0.68), h
    if 0.55 <= h <= 0.66 and s > 0.55:            # 電光ブルー → アルマナックの藍（#2456A6系）へ
        nh, ns = 0.602, min(s, 0.64)
    if (nh, nl, ns) == (h, l, s):
        return hx
    rr, gg, bb = _cs.hls_to_rgb(nh, nl, ns)
    return _lp_rgb2hx(rr * 255, gg * 255, bb * 255)

def _lp_adjust_for_contrast(fg, bg, target=4.0):
    """fgの明度だけを動かして bg に対して target 以上のコントラストへ。"""
    if _lp_ct(fg, bg) >= target:
        return fg
    r, g, b = _lp_hx2rgb(fg)
    h, l, s = _cs.rgb_to_hls(r / 255, g / 255, b / 255)
    bl = _lp_lum(bg)
    # 背景が明るければ暗い方向へ、暗ければ明るい方向へ探索
    seq = [x / 100 for x in range(30, 3, -2)] + [0.02] if bl > 0.35 else [x / 100 for x in range(70, 99, 2)] + [0.985]
    best, bestct = fg, _lp_ct(fg, bg)
    for nl in seq:
        rr, gg, bb = _cs.hls_to_rgb(h, nl, s)
        cand = _lp_rgb2hx(rr * 255, gg * 255, bb * 255)
        ct = _lp_ct(cand, bg)
        if ct >= target:
            return cand
        if ct > bestct:
            best, bestct = cand, ct
    return best

def _lp_map_rgba(mo):
    r, g, b = int(mo.group(1)), int(mo.group(2)), int(mo.group(3))
    a = mo.group(4)
    mx, mn = max(r, g, b), min(r, g, b)
    chroma = (mx - mn) / 255.0
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    _h, _l, _s = _cs.rgb_to_hls(r / 255, g / 255, b / 255)
    _cool = 0.52 <= _h <= 0.75
    if chroma < 0.09 or (_cool and chroma < 0.20):
        try:
            af = float(a)
        except Exception:
            af = 1.0
        if lum < 0.45:
            if max(r, g, b) <= 8:                # ほぼ純黒＝スクリム・影 → 保持（ライトでも暗幕が正）
                return mo.group(0)
            # 濃紺・グラファイト・低α含む暗いサーフェス → 紙色サーフェス
            # （αで分岐するとグラデーションの片側だけ暗く残り“謎グラデ”になるため一律変換）
            return f"rgba(242,240,233,{a})"
        else:                                    # 明るい無彩色（境界・ホバー・白文字）→ インク系
            return f"rgba(27,29,28,{a})"
    return mo.group(0)                           # 有彩色rgba（チップ地等）は保持

_LP_KEEP = set()                                  # 変換除外（必要時に追加）

def _lightpass(html):
    import re as _re
    # --- ① 全hexの写像（CSS・インライン・SVG共通）---
    cache = {}
    def _m(mo):
        hx = mo.group(0).lower()
        if hx in _LP_KEEP:
            return hx
        if hx not in cache:
            try:
                cache[hx] = _lp_map_hex(hx)
            except Exception:
                cache[hx] = hx
        return cache[hx]
    html = _re.sub(r"#[0-9a-fA-F]{6}\b", _m, html)
    html = _re.sub(r"#[0-9a-fA-F]{3}\b", _m, html)
    # --- ② rgba()の無彩色反転 ---
    html = _re.sub(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)", _lp_map_rgba, html)
    # --- ③ CSSルール単位のコントラスト補正 ---
    def _fix_css(css):
        def _rule(mo):
            sel, body = mo.group(1), mo.group(2)
            bgm = (_re.search(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{6})", body)
                   or _re.search(r"gradient\([^)]*?(#[0-9a-fA-F]{6})", body))
            ebg = bgm.group(1) if bgm else _LP_PAPER
            def _col(cm):
                fg = cm.group(1)
                return "color:" + _lp_adjust_for_contrast(fg, ebg, 4.0)
            body2 = _re.sub(r"color\s*:\s*(#[0-9a-fA-F]{6})\b", _col, body)
            return sel + "{" + body2 + "}"
        return _re.sub(r"([^{}]+)\{([^{}]*)\}", _rule, css)
    html = _re.sub(r"(<style>)(.*?)(</style>)", lambda mo: mo.group(1) + _fix_css(mo.group(2)) + mo.group(3),
                   html, flags=_re.S)
    # --- ④ インラインstyleのコントラスト補正 ---
    def _fix_inline(mo):
        st = mo.group(1)
        bgm = _re.search(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{6})", st)
        if bgm:
            ebg, target = bgm.group(1), 4.0
        else:
            ebg, target = _LP_PAPER, 2.6          # クラス背景の可能性があるため保守的に
        def _col(cm):
            return "color:" + _lp_adjust_for_contrast(cm.group(1), ebg, target)
        return 'style="' + _re.sub(r"color\s*:\s*(#[0-9a-fA-F]{6})\b", _col, st) + '"'
    html = _re.sub(r'style="([^"]*)"', _fix_inline, html)
    # --- ⑤ メタ・上書きCSS ---
    html = html.replace('content="dark"', 'content="light"')
    html = html.replace("color-scheme:dark", "color-scheme:light")
    light_fix = ("<style>"
                 "html,body{background:#eceae3;color:#1b1d1c}"
                 # 一部のアプリ内プレビューは body 背景を透過扱いにして暗い地が透ける。
                 # 固定下地レイヤなら body{background:transparent!important} を注入されても紙色が残る。
                 'body::before{content:"";position:fixed;inset:0;background:#eceae3;z-index:-1;pointer-events:none}'
                 "nav{background:rgba(236,234,227,.93);border-bottom:1px solid #d6d2c5}"
                 ".card{background:#f6f4ef;border-color:#dedacd}"
                 # 定点観測（X共有）カード: 濃紺グラデを廃し、カードに馴染むフラットな紙パネルに
                 ".mkt-post{background:#f1efe7;border:1px solid #e3e0d5}"
                 ".mkt-post-hook{border-bottom-color:#e3e0d5}"
                 "</style>")
    html = html.replace("</head>", light_fix + "</head>", 1)
    return html

_EN_TITLE_MAP = {
    "今日のマーケット": "Market Summary", "マーケットステータス推移": "Regime History",
    "マーケット・パフォーマンス": "Performance", "先導株モメンタム・ラン": "Leader Momentum",
    "リーダーの強さ": "Leader Temperature", "セクター温度マップ": "Sector Heatmap",
    "セクターETF強弱": "Sector ETF Strength", "レジーム警戒灯": "Regime Early-Warning",
    "リーダー・ブレッドス警戒灯": "Leader Breadth", "転換初動リーダーボード": "Reversal Leaders",
    "フォロースルー・デイ": "Follow-Through Day", "VIX期間構造": "VIX Term Structure",
    "センチメント": "Sentiment", "エクイティカーブ": "Equity Curve", "金利": "Yields",
    "広域ブレッドス": "Market Breadth", "データ品質": "Data Quality",
    "指数の200日線乖離": "Index vs 200DMA", "前回からの変化": "Change Log",
    "圧縮コイル": "VCP Watch", "テクニカル・パターン別": "Chart Patterns",
    "本日のピックアップ": "Today's Setups", "リーダー監視": "Leaders", "銘柄検索": "Ticker Search",
    "業種ローテ": "Sector Rotation", "強い業種の主導株": "Leaders in Strong Groups",
    "テーマ・ドリルダウン": "Theme Drilldown", "マーケット感応度": "Beta vs QQQ",
    "システムルール": "System Rules", "資金配分・株数計算": "Position Sizing",
    "エクイティ記録": "Equity Log", "隔週リバランス点検": "Rebalance Check",
    "非常口": "Emergency Brake", "RS189 継続性": "Leadership Persistence",
    "順位落ち保有": "Demoted Holdings", "RSリーダー控え": "Bench",
    "本日の新高値圏": "New Highs", "本日の押し目シグナル": "Pullback Signals",
    "テンバガー・レーダー": "Moonshot Radar", "押し目質スクリーナー": "Pullback Quality",
    "オプション想定変動幅": "Expected Move", "クレジット推移": "Credit Spread",
    "サブテーマ別RS": "Sub-Theme RS", "スイング・プランナー": "Trade Planner",
    "テーマ・ローテーション": "Theme Rotation (RRG)", "ディストリビューション・デイ": "Distribution Days",
    "ブレッドス推移": "Breadth Trend", "ポートフォリオ": "Portfolio",
    "レバレッジ・コンディション": "Leverage Conditions", "売買代金 参加度": "Volume Participation",
    "広がりの勢い": "McClellan Oscillator", "攻守ローテーション": "Risk-On/Off Rotation",
    "集積／分散": "Accumulation/Distribution", "ポジション・サイザー": "Position Sizer",
    "コンフルエンス・ボード": "Confluence Board", "セクター・ローテーション": "Sector Rotation (RRG)", "ポケットピボット": "Pocket Pivots (10D)",
    "新規参入": "New Entrants", "兆候の重なり": "Signal Confluence",
}

def _inject_en_titles(html):
    """全<h2>タイトルにサーバー側で英語併記を注入（JS非依存で確実）。"""
    import re as _re
    keys = sorted(_EN_TITLE_MAP.keys(), key=len, reverse=True)
    def _rep(mobj):
        inner = mobj.group(1)
        if "h2en" in inner:
            return mobj.group(0)
        # 先頭の日本語テキスト（タグ前）で前方一致
        head = _re.sub(r"<[^>]+>.*$", "", inner).strip()
        for k in keys:
            if head.startswith(k):
                return f'<h2>{inner}<span class="h2en">{_EN_TITLE_MAP[k]}</span></h2>'
        return mobj.group(0)
    return _re.sub(r"<h2>(.*?)</h2>", _rep, html, flags=_re.S)

# ----------------------------------------------------------------------------- selftest
def selftest(html, picks, setups, sectors, mkt=None, W=None, cutdate=None):
    errs = []
    warns = []          # #10 非致命（ビルドは通すが注意喚起）。critical=errs はビルド停止。
    if os.environ.get("V38_FORCE_SELFTEST_FAIL") == "1":
        errs.append("forced failure (test hook)")   # 受入テスト用: 通常ビルドで失敗時に本番stateを触らないことの検証
    if os.environ.get("V38_FORCE_SELFTEST_WARN") == "1":
        warns.append("forced warning (test hook)")
    # データ鮮度・カバレッジは劣化warning（機能はする）: 時価総額カバー率、マクロ欠損
    try:
        if mkt is not None:
            _q = mkt.get("quality") or {}
            _cov = _q.get("mcap_cov")
            if _cov is not None and _cov < 0.95:
                warns.append(f"mcap coverage low: {_cov*100:.0f}% (<95%)")
            _pcov = _q.get("price_cov")
            if _pcov is not None and _pcov < 0.95:
                warns.append(f"price coverage low: {_pcov*100:.0f}% of universe has price data (<95%)")
            _rcov = _q.get("rs189_cov")
            if _rcov is not None and _rcov < 0.80:
                warns.append(f"RS189 coverage low: {_rcov*100:.0f}% (<80%)")
            _mm = _q.get("macro_missing") or []
            if len(_mm) >= 3:
                warns.append(f"macro series missing: {len(_mm)}")
    except Exception:
        pass
    # -- #3/#4 XSS検査: 外部文字列(テーマ/社名/業種/note/日付)からの実注入だけを検出する。
    #   重要: エスケープ済み外部文字列を「属性値」に入れると、値内の > は &gt; になりリテラル > が消える。
    #   そのため素朴な `<[^>]*onerror=` は、安全にエスケープされた属性内テキストまで誤検知する（実害無しでビルドを止める）。
    #   → 検出は「リテラル<タグ かつ 実ハンドラ(値が & で始まらない=エスケープされていない)」に限定する。
    try:
        import re as _re4
        # 開発者由来の<script>...</script>（CALC/DET/SPARK等の埋め込みJS・中身はエスケープ済みデータ）は除外して本文だけ見る
        _body_only = _re4.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=_re4.S | _re4.I)
        # (a) 自動発火するイベントハンドラを持つリテラルタグ。値が & で始まる(=エスケープ済み属性内)ものは除く。
        #     onclick/oninput等の開発者ハンドラは対象外（本ダッシュボードが正規に使う）。onerror/onload等の自動発火のみ。
        _auto = r'on(?:error|load|mouseover|mouseenter|focus|toggle|animationstart|pointerenter|begin|abort|scroll|wheel)'
        if _re4.search(r'<\s*[a-zA-Z][^>]*?\b' + _auto + r'\s*=\s*[^&\s>]', _body_only, _re4.I):
            errs.append("HTML contains a literal tag with auto-firing event handler (external-string injection)")
        # (a2) onclick/oninput等も含め、ハンドラ値に「正規ハンドラが使わない危険パターン」が入っていれば注入。
        #      正規は copyOne(event, document.getElementById(...)) 等の名前付き関数呼び出し。
        #      document.getElementById は正規なので除外し、dataset./cookie/eval/alert/globalThis/innerHTML= 等のみを注入とみなす。
        _inj = r'(?:\.dataset\.|\.cookie\b|eval\s*\(|alert\s*\(|globalThis\.|document\.write|\.innerHTML\s*=|document\.body\b)'
        if _re4.search(r'<\s*[a-zA-Z][^>]*?\bon[a-z]+\s*=\s*["\']?[^"\'>]*?' + _inj, _body_only, _re4.I):
            errs.append("HTML contains an event handler with injection markers (dataset./cookie/eval/innerHTML etc.)")
        # (b) 本文中のリテラル <script>/<iframe>/<svg on...>/<img ...> と javascript: URL（外部データがエスケープされていれば &lt; になり非マッチ）
        if _re4.search(r'<\s*script\b', _body_only, _re4.I):
            errs.append("HTML body contains a literal <script> outside developer blocks (injection)")
        if _re4.search(r'<\s*iframe\b(?![^>]*\bsrcdoc=)', _body_only, _re4.I):
            errs.append("HTML body contains a literal <iframe> (injection)")
        if _re4.search(r'<\s*img\b', _body_only, _re4.I):
            errs.append("HTML body contains a literal <img> (injection; dashboard uses no <img>)")
        if _re4.search(r'javascript:', _body_only, _re4.I):
            errs.append("HTML contains a javascript: URL (injection)")
        # (c) <script>ブロックのbreakout検査。_json_for_scriptは < を \u003c に落とすので、
        #     script中身に生の </script や <script が出たら早期クローズ=注入。開始/終了数の不一致も検出。
        _sc_open = len(_re4.findall(r'<script\b', html, _re4.I))
        _sc_close = len(_re4.findall(r'</script\s*>', html, _re4.I))
        if _sc_open != _sc_close:
            errs.append("HTML <script> open/close mismatch (possible breakout): %d/%d" % (_sc_open, _sc_close))
        for _sc in _re4.findall(r'<script\b[^>]*>(.*?)</script\s*>', html, flags=_re4.S | _re4.I):
            if _re4.search(r'</\s*script', _sc, _re4.I) or _re4.search(r'<\s*script\b', _sc, _re4.I):
                errs.append("nested/raw <script> inside a script block (injection/breakout)")
                break
        # 重複ID（従来はshare HTMLのみ→メインにも）。srcdoc内(エスケープ済み)は id=&quot; なので非マッチ。
        _ids = _re4.findall(r'\bid="([^"]+)"', html)
        _seen, _dups = set(), set()
        for _i in _ids:
            if _i in _seen: _dups.add(_i)
            _seen.add(_i)
        if _dups:
            errs.append("HTML duplicate id: " + repr(sorted(_dups)[:6]))
    except Exception as _e:
        errs.append("xss/id check raised: " + repr(_e)[:80])
    # -- Overview注入ミス: テンプレ変更等でスカラー/配列注入やサンプル残留があればselftestで失敗扱い --
    if _OV_INJECT_MISSES:
        errs.append("Overview injection missed: " + repr(sorted(set(_OV_INJECT_MISSES))))
    # -- Publish(Overview)生成成功を必須化: 例外で落ちてNoneでも他画面が正常ならOKになる穴を塞ぐ --
    if mkt is not None:
        # -- Weekly口座比較(自分 vs QQQ円建て): equity>=2件あるのにカードが無い＝例外で消えている（SELFTEST OKの穴）--
        if mkt.get("_wk_acct_expected"):
            _wa = mkt.get("wk_acct") or ""
            if not _wa:
                errs.append("Weekly account comparison was not generated")
            elif "自分 vs QQQ円建て" not in _wa:
                errs.append("Weekly account comparison card missing")
        _p1 = mkt.get("post1_html"); _p2 = mkt.get("post2_html")
        if not _p1:
            errs.append("Publish overview 1 was not generated")
        if not _p2:
            errs.append("Publish overview 2 was not generated")
        for _key in ('id="d_br"', 'id="d_f1"', 'id="d_f2"', 'id="d_f3"'):
            if _key not in (_p1 or ""):
                errs.append(f"Publish chart missing: {_key}")
    # -- W30確定版ガード(合成データ検証済み) --
    try:
        _idx = pd.bdate_range("2023-01-02", periods=420)
        _mk = lambda d: pd.Series(d, index=_idx[:len(d)])
        _sy = lambda lo, j: _mk(list(np.linspace(100, lo, 200)) + [lo] * 150 + [j] * 5)
        _r = w30_breakout(_sy(60, 93.0))
        assert _r["w30x_grade"] == "FULL" and _r["w30x_tier"] in ("S", "A", "B") and _r["w30x_status"] == "NEW"
        assert w30_breakout(_sy(80, 88.0))["w30x_grade"] == "PARTM"
        assert w30_breakout(_sy(80, 80.24))["w30x_grade"] == "WEAK"
        assert w30_breakout(_sy(80, 83.0))["w30x_grade"] == "CROSS"
        _pos = (list(np.linspace(100, 55, 150)) + [55] * 20 + list(np.linspace(55, 90, 130))
                + list(np.linspace(90, 78, 30)) + [78] * 80 + [84.5] * 5)
        assert w30_breakout(_mk(_pos))["w30x_grade"] == "POS"
        assert w30_breakout(_mk(list(np.linspace(100, 200, 420))))["w30x_grade"] is None
        print("[selftest] W30 v3 OK")
    except AssertionError:
        errs.append("W30 v3 selftest failed")
    # --- 構造ガード: main()が呼ぶ主要ビルダーが全て関数として存在するか。
    #     （編集事故でdef行が消え、コードが前の関数の到達不能領域に埋まる事故を検出。実例2026-07）
    for _fn in ("build_breadth_ts", "build_distribution", "build_ftd", "build_yields",
                "build_rates_card", "build_macro_pressure", "fetch_fred_context",
                "build_updown_vol_ts", "build_dollarvol_ts", "build_rrg",
                "compute_regime_state", "compute_regime_history", "track_holdings",
                "guard_last_bar", "cut_to_completed", "build_breadth",
                "_fred_metrics", "_pressure_metrics", "_fred_fetch_one",
                "_bondvol_from_macro", "_dollar_from_macro_or_fred",
                "build_emergency_brake", "build_rs_continuity", "build_structure_scanner",
                "_trend_change_confirmed", "_recent_breakout_stats", "_cup_handle_metrics"):
        if not callable(globals().get(_fn)):
            errs.append(f"構造: {_fn} が定義されていない（def行の消失・編集事故の可能性）")
    # --- 2026-07 監査で直した箇所の回帰ガード ---
    if cutdate is not None and W is not None:
        try:
            if W["Close"].index[-1] > cutdate:
                errs.append("unconfirmed bar leaked past last completed session")
        except Exception:
            pass
    if mkt:
        _f = mkt.get("ftd") or []
        for _x in _f:
            if _x.get("state") not in ("NO_CORRECTION","CORRECTION","RALLY_ATTEMPT","FTD_ACTIVE","FTD_FAILED"):
                errs.append(f"{_x['tk']}: unknown FTD state {_x.get('state')}")
            if _x.get("state") == "FTD_ACTIVE" and not _x.get("ftd_date"):
                errs.append(f"{_x['tk']}: FTD_ACTIVE without ftd_date")
        for _tk, _d in (mkt.get("distrib") or {}).items():
            if _d.get("alert_basis") != "classic_only":
                errs.append(f"{_tk}: distribution alert must use classic days only")
            if _d.get("n") != _d.get("cl"):
                errs.append(f"{_tk}: stall leaked into alert count")
        _rh = mkt.get("reg_hist") or {}
        if _rh:
            if "f1_now" not in _rh:
                errs.append("F1 history did not expose f1_now")
            if _rh.get("f1_status") == "OK":
                if _rh.get("f1_num", 0) != _rh.get("f1_rank_drop", 0) + _rh.get("f1_elig_drop", 0):
                    errs.append("F1 numerator != rank_drop + elig_drop (unknown leaked in)")
                if (_rh.get("f1_coverage") or 0) < 0.90:
                    errs.append("F1 reported OK below 90% coverage")
        _b = mkt.get("breadth_ts")
        if isinstance(_b, list) and _b and any(v > 100.0001 or v < -0.0001 for _, v in _b):
            errs.append("breadth_ts out of [0,100]")
        _em = mkt.get("emergency") or {}
        if _em.get("active") and abs(float(_em.get("mult", 0)) - 0.5) > 1e-9:
            errs.append("emergency active but multiplier is not 0.5")
        _cc = mkt.get("calc") or {}
        if _cc and abs(float(_cc.get("e_lev", 0)) - float(_cc.get("e_lev_base", _cc.get("e_lev", 0))) * float(_cc.get("emergency_mult", 1))) > 1e-9:
            errs.append("emergency multiplier is not reflected in leverage allocation")
        _rc = mkt.get("rs_continuity") or {}
        if _rc and len(_rc.get("rows") or []) > 24:
            errs.append("RS continuity exceeds Top24")
    # 表示文言と隔週サイクルの回帰ガード
    _rx = __import__("re")
    _visible = _rx.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=_rx.S | _rx.I)
    for _bad in ("表示専用", "表示だけ", "非連動", "裁量参考", "（参考）", "参考表示", "参考指標", "参考", "執行ゾーン", "正式選定には使わない", "研究・観測用", "候補観察と学習", "jfsrev", "NQ色"):
        if _bad in _visible:
            errs.append(f"冗長な注記が画面に残存: {_bad}")
    if mkt:
        _cc2 = mkt.get("calc") or {}
        try:
            if _cc2.get("next_rebal") and _cc2.get("rebal_anchor") and not is_rebalance_date(_cc2["next_rebal"], _cc2["rebal_anchor"]):
                errs.append("次回リバランス日が隔週アンカーと不整合")
        except Exception:
            errs.append("リバランス日検証に失敗")
    for sid in ["t-today","t-movers","t-market","t-weekly","t-port","t-alloc","t-rs","t-rotation","t-rules","t-post1"]:
        if f'id="{sid}"' not in html:
            errs.append(f"missing tab {sid}")
    for _lab in ("① 重なりで絞る", "② 単独シグナル", "③ 圧縮・ベース", "④ 底打ち（構造ピボット）", "⑤ W30ブレイク（30週線）", "⑥ リーダー母集団"):
        if _lab not in html:
            errs.append(f"pickup section missing: {_lab}")
    if "Setups</button>" not in html and "Setups</a>" not in html:
        errs.append("setups(pickup) tab label missing")
    if "RSマルチタイムフレーム比較" not in html: errs.append("RS comparison tab missing")
    for _lab in ("RS63 Top10", "RS126 Top10", "RS189 Top10"):
        if _lab not in html: errs.append(f"RS comparison ranking missing: {_lab}")
    if "Top10 IN / OUT履歴" not in html: errs.append("RS Top10 IN/OUT history missing")
    if "RS189 継続性" not in html: errs.append("RS continuity card missing")
    if "非常口" not in html: errs.append("emergency brake card/rule missing")
    for _win in ("前営業日", "約5営業日前", "約21営業日前"):
        if _win not in html: errs.append(f"RS history window missing: {_win}")
    if "マーケットステータス（地合いスコア）" not in html: errs.append("status banner missing")
    if 'id="mktPostText"' not in html or "定点観測" not in html: errs.append("market digest missing")
    if 'class="mkt-fold"' not in html: errs.append("market explanation fold missing")
    if "トレンド判定" not in html: errs.append("trend pill missing")
    if not any(c in html for c in ["sar-blue","sar-green","sar-yellow","sar-red"]):
        errs.append("NQ-SAR color class missing")
    if len(picks) > N_PORT: errs.append(f"portfolio exceeds N={N_PORT} (got {len(picks)})")
    if "None" in html: errs.append("literal 'None' in html")
    # --- 仕様ガード(回帰防止・最終確定2026-07-05) ---
    if gate_coeffs("Yellow") != (1.0, 0.0): errs.append("gate: 黄=保有露出100(新規停止・既存はピーク×0.70)が正")
    if gate_coeffs("Red")    != (0.0, 0.0): errs.append("gate: 赤=撤退0が正")
    if gate_coeffs("Green")  != (1.0, 0.5): errs.append("gate: 緑")
    if "建値×0.70（−30" in html or "−30%初期" in html: errs.append("旧stop30が残存")
    if "落ちるナイフ" in html or "刃物" in html: errs.append("旧・ナイフ用語が残存")
    if "セリングクライマックス" not in html and "投げ" not in html: print("[warn] 投げ確認ルールの説明が見当たらない")
    if "出遅れ" not in html and "業種内" not in html: print("[warn] 出遅れ株除外の説明が見当たらない")
    if "新規停止" not in html and "新規エントリーは停止" not in html: print("[warn] 黄=新規停止の表示が見当たらない(黄以外の日は正常)")
    if "小型創薬" not in html: print("[warn] 小型創薬除外の説明が見当たらない")
    if EXCLUDE_SUBTHEMES != ("臨床段階・中小型バイオ",): errs.append("バイオ除外サブテーマが変更されている")
    if ">nan<" in html or " nan%" in html or "nan/100" in html: errs.append("literal nan in html")
    if "リーダー監視" not in html: errs.append("leaders card missing")
    if "本日のピックアップ" not in html: errs.append("pickup card missing")
    if not sectors: errs.append("sector RS empty")
    if "VIX期間構造" not in html: errs.append("VIX term chart missing")
    if "todayact" not in html: errs.append("today action header missing")
    if "騰落ライン" not in html: errs.append("A/D line chart missing")
    if f"上位{N_PORT}" not in html: errs.append("N reflected text missing")
    # --- v3 additions
    if "センチメント（群衆温度計）" not in html: errs.append("sentiment card missing")
    if ("エクイティカーブ×2" not in html): errs.append("equity card missing")
    if "前回からの変化" not in html: errs.append("changelog card missing")
    if "データ品質" not in html: errs.append("quality card missing")
    if "セクター温度マップ" not in html and "hmgrid" not in html: errs.append("sector heatmap missing")
    if "トレール" not in html: errs.append("trail column missing")
    if "先導株の強さ" not in html: print("[warn] leader temp gauge missing (データ不足の可能性)")
    if "theme-color" not in html: errs.append("theme meta missing")
    if "テーマ・ローテーション" not in html: errs.append("RRG card missing")
    if "ステージ2" not in html: errs.append("stage analysis (DET) missing")
    if "Day4以降" not in html: errs.append("FTD canonical text missing")
    if "レバレッジ・コンディション" not in html: errs.append("lev-env panel missing")
    # --- FRED金利カードの回帰ガード ---
    # 1) Market Health v2の4本柱と重みを固定
    try:
        _fp = tuple((k, w, lo, hi, g) for k, w, lo, hi, g in STATUS_DEF)
        _EXPECT = (("trend",30,0.0,1.0,"market"),("breadth",30,0.0,1.0,"market"),
                   ("risk",20,0.0,1.0,"market"),("credit",20,0.0,1.0,"market"))
        if _fp != _EXPECT:
            errs.append("地合いスコア4本柱の定義または重みが変更されている")
        _mri_keys = {k for k, *_ in STATUS_DEF}
        if _mri_keys & set(FRED_SERIES.keys()):
            errs.append("FRED系列が地合いスコアへ混入している")
    except Exception as _e:
        errs.append(f"market score fingerprint check raised: {repr(_e)[:60]}")
    # 3) 旧5年・10年・30年カードが残っていない
    if "米5年" in html or "米30年" in html:
        errs.append("旧・金利カード(5年/30年)が残存")
    if '<h2>金利</h2>' in html:
        errs.append("旧・金利カード見出しが残存")
    # 4) 金利カード本体と各系列に観測日・経過日数・bp表示があるか（FRED取得成功時のみ厳格）
    if mkt is not None:
        _mc = mkt.get("macro_context") or {}
        _got = any((_mc.get(s, {}).get("last") is not None) for s in ("DGS2", "DFII10", "T10YIE", "T10Y2Y"))
        if "金利レジーム" not in html:
            errs.append("金利レジームカードが無い")
        if _got:
            if "観測 " not in html:
                errs.append("金利カードに観測日が無い（週次を日次の新規値として誤表示していないか要確認）")
            if "bp" not in html:
                errs.append("金利カードのbp換算表示が無い")
        else:
            print("[warn] FRED未取得のため金利カードは欠損表示（HTML生成は継続・想定内）")
        # 6) FRED取得層の機能テスト（★実取得の成否と無関係に常に実行。
        #    本物のFREDが全滅した日こそ、フォールバック合成テストが必要）
        if True:
            try:
                import tempfile as _tf, os as _os
                _saved = _os.environ.get("V38_FRED_CACHE")
                _os.environ["V38_FRED_CACHE"] = _tf.mktemp(suffix=".json")
                _real = _fred_fetch_one
                _dates = [f"2026-06-{(i%28)+1:02d}" for i in range(60)]

                # (a) bp換算: 20日変化×100 = +18bp
                _ser = [(_dates[i], 1.00) for i in range(21)]; _ser[-1] = (_ser[-1][0], 1.18)
                _l, _c, _p, _s, _e = _fred_metrics(_ser, _ser[-1][0])
                if _c is None or abs(_c * 100 - 18.0) > 1e-6:
                    errs.append(f"FRED-test bp換算が不正: 期待+18bp 実際{None if _c is None else _c*100:.1f}")

                # (b) asofより未来のFRED値を使わない + 経過日数が負にならない
                _future = [("2026-01-10", 1.0), ("2026-01-15", 1.1), ("2026-02-12", 9.9)]
                _l, _c, _p, _s, _e = _fred_metrics(_future, "2026-02-12", asof=pd.Timestamp("2026-01-15"))
                if _e is None or pd.Timestamp(_e).date() > dt.date(2026, 1, 15):
                    errs.append("FRED-test: asofより未来の観測が使われている")
                if _l != 1.1:
                    errs.append(f"FRED-test: asof以前の最終値でない (got {_l})")
                if _s is not None and _s < 0:
                    errs.append("FRED-test: 経過日数が負")

                # (c) API失敗→CSV成功で src='csv'（api誤表示しない）
                globals()["_fred_fetch_one"] = lambda sid, api_key=None, timeout=9, start=None, retry=True, deadline=None: (
                    [(_dates[i], 4.0 + i * 0.001) for i in range(40)], "csv")
                _os.environ["FRED_API_KEY"] = "dummy"      # キーありでもCSV成功ならcsv
                _ctx = fetch_fred_context({"DGS2": "米2年"})
                if (_ctx.get("DGS2") or {}).get("src") != "csv":
                    errs.append(f"FRED-test: CSV成功をsrc={(_ctx.get('DGS2') or {}).get('src')}と誤表示")

                # (d) 取得失敗→キャッシュ成功、かつ cached_at を上書きしない
                _cp = _os.environ["V38_FRED_CACHE"]
                json.dump({"DGS2": {"vals": [(_dates[i], 4.0) for i in range(30)],
                                    "cached_at": "2025-01-03", "src": "csv",
                                    "last_date": _dates[29], "last": 4.0}}, open(_cp, "w"))
                globals()["_fred_fetch_one"] = lambda sid, api_key=None, timeout=9, start=None, retry=True, deadline=None: (None, None)
                _ctx2 = fetch_fred_context({"DGS2": "米2年"})
                if (_ctx2.get("DGS2") or {}).get("src") != "cache":
                    errs.append("FRED-test: 取得失敗時にキャッシュへ退避していない")
                if (_ctx2.get("DGS2") or {}).get("cached_at") != "2025-01-03":
                    errs.append(f"FRED-test: キャッシュ取得日が上書きされた ({(_ctx2.get('DGS2') or {}).get('cached_at')})")

                # (e) 全滅→src=none だが例外は出ない（HTML生成継続）
                _os.environ["V38_FRED_CACHE"] = _tf.mktemp(suffix=".json")
                _ctx3 = fetch_fred_context({"DGS2": "米2年"})
                if (_ctx3.get("DGS2") or {}).get("src") != "none":
                    errs.append("FRED-test: 全滅時にsrc=noneにならない")

                globals()["_fred_fetch_one"] = _real
                if _saved is None:
                    _os.environ.pop("V38_FRED_CACHE", None); _os.environ.pop("FRED_API_KEY", None)
                else:
                    _os.environ["V38_FRED_CACHE"] = _saved
            except Exception as _e:
                # FRED取得層(ネットワーク依存)のテスト基盤の例外はコアselftestから分離し警告に留める
                print(f"[warn] FRED functional-test skipped (infra): {repr(_e)[:70]}")

        # --- 第2段階 マクロ圧力パネルの回帰ガード ---
        if "マクロ圧力" not in html:
            errs.append("マクロ圧力パネルが無い")
        # 総合判定ワードを出していない（ルール未固定なので判定は作らない約束）
        # ★検査はマクロ圧力カードの範囲に限定（SOXLカード等の既存「追い風/逆風」チップは対象外）
        _mp_i = html.find("マクロ圧力")
        if _mp_i >= 0:
            _mp_end = html.find("<h2", _mp_i + 1)
            _mp_seg = html[_mp_i:_mp_end if _mp_end > 0 else _mp_i + 20000]
            if "'15%'" in html or "トレール15" in html:
                errs.append("黄トレール15%の残骸(JS結合含む)")
            for _bad in ("総合判定", "追い風", "逆風でNAV", "圧力スコア"):
                if _bad in _mp_seg:
                    errs.append(f"マクロ圧力に未固定の総合判定が混入: {_bad}")
        # 圧力系列(OAS/ドル/NFCI)がMRIに入っていない
        _mri_keys2 = {k for k, *_ in STATUS_DEF}
        if _mri_keys2 & set(FRED_PRESSURE_SERIES.keys()):
            errs.append("マクロ圧力のFRED系列がMRIに混入")
        # DTWEXBGSとDXYを同名で混同していない（フォールバック時は別名表示）
        _pc = mkt.get("macro_pressure_ctx") or {}
        _dollar_got = bool((_pc.get("DTWEXBGS") or {}).get("last"))
        if "DTWEXBGS" in html and "DXY" in html and _dollar_got:
            # 両方の実データが同時に主指標として出るのは想定外（片方はフォールバック名のみ）
            if "広義ドル・日次" in html and "ドル指数・日次・別系列" in html:
                pass  # ラベルで区別されていればOK
        # DTWEXBGSはFRED公式上「日次」。旧い週次ラベルを残さない。
        if "DTWEXBGS（広義ドル・週次）" in html:
            errs.append("DTWEXBGSを週次と誤表示している（公式系列は日次）")
        if set(FRED_ALL_SERIES) != (set(FRED_SERIES) | set(FRED_PRESSURE_SERIES)
                                    | set(FRED_LIQUIDITY_SERIES) | set(FRED_WEEKLY_SERIES)):
            errs.append("FRED_ALL_SERIESが全系列(金利+圧力+流動性+週末)の和集合になっていない")
        # MOVEフォールバック名がMOVEと区別されている
        if "TLT 20日実現ボラ" in html and "MOVE代替" not in html:
            errs.append("MOVE代替(TLT実現ボラ)がMOVEと区別表示されていない")


    if "ト15%" in html or "trail(15" in html or "×0.85" in html:
        errs.append("黄15%トレールの文言が残存（0.70に統一されていない）")
    if "個別枠 40%" in html or "レバ枠 60%" in html:
        errs.append("配分表示が40/60ハードコードのまま（ALLOCと不一致）")
    if "half" in html and "is not defined" not in html:
        # JS内に未定義halfが残っていないか（下のJS構文チェックでも捕捉する）
        if "var sh=(base!=null&&half)" in html:
            errs.append("配分計算機に未定義変数 half が残存")

    # --- 出口ロジックの単体テスト（Python: track_holdings が仕様 max(建値×0.75, ピーク×0.70) か）---
    try:
        _prev = {"hold": {"ZZ": {"ed": "2024-01-01", "ep": 100.0, "peak": 110.0, "istop": 75.0}}}
        _picks = [("ZZ", "t", {"close": 105.0, "ema21": 103.0, "lo10": 102.2})]
        _h, _hv, _heat, _tf, _c = track_holdings(_prev, _picks, "Yellow", "2024-02-01")
        _stop = _hv["ZZ"]["stop"]
        if abs(_stop - 77.0) > 1e-6:
            errs.append(f"exit: 出口が仕様(77.0)と不一致 → {_stop:.2f}（10日安値/21EMAが混入）")
        # 現値が出口以下なら割れ判定
        _picks2 = [("ZZ", "t", {"close": 76.0, "ema21": 74.0, "lo10": 74.0})]
        _h2, _hv2, *_ = track_holdings(_prev, _picks2, "Yellow", "2024-02-01")
        if not (76.0 <= _hv2["ZZ"]["stop"]):
            errs.append("exit: 現値<出口でも割れ判定にならない")
        if _tf != 0.70:
            errs.append(f"exit: 黄トレール係数が0.70でない → {_tf}")
    except Exception as _e:
        errs.append(f"exit self-test raised: {repr(_e)[:80]}")

    # --- #1/#2: 実保有の状態遷移（非リバランス日は追加しない／赤は撤退／リバランス日は取込） ---
    try:
        _pvh = {"hold": {"AA": {"ed": "2026-06-01", "ep": 100.0, "peak": 100.0},
                         "BB": {"ed": "2026-06-01", "ep": 50.0, "peak": 50.0}}, "gate": "Blue"}
        _mnr = pd.DataFrame({"close": [110.0, 55.0, 200.0], "sma50": [1.0, 1.0, 1.0],
                             "sma200": [0.0, 0.0, 0.0], "rs189": [90.0, 88.0, 99.0]},
                            index=["AA", "BB", "CC"])
        _pk = [("CC", "t", {"close": 200.0})]
        _hnr, *_ = track_holdings(_pvh, _pk, "Blue", "2026-07-15", _mnr, rebal_anchor="2026-07-13")
        if set(_hnr.keys()) != {"AA", "BB"}:
            errs.append(f"holdings: 非リバランス日に保有が変化 → {sorted(_hnr.keys())}（AA/BB継続のはず）")
        _hred, *_ = track_holdings(_pvh, _pk, "Red", "2026-07-15", _mnr, rebal_anchor="2026-07-13")
        if _hred:
            errs.append(f"holdings: 赤で保有が残る → {sorted(_hred.keys())}（撤退のはず）")
        _hrb, *_ = track_holdings(_pvh, _pk, "Blue", "2026-07-27", _mnr, rebal_anchor="2026-07-13")
        if "CC" not in _hrb:
            errs.append("holdings: リバランス日に新候補が取り込まれない")
        # リバランス日に13銘柄以上へ増えない（継続旧保有＋空き枠補充で最大N_PORT）
        _names = list("ABCDEFGHIJKL")
        _prevh = {"hold": {t: {"ed": "2026-06-01", "ep": 100.0, "peak": 100.0} for t in _names}, "gate": "Blue"}
        _mrb = pd.DataFrame({"close": [100.0] * 13, "sma50": [1.0] * 13, "sma200": [0.0] * 13,
                             "rs189": [99.0 - i for i in range(13)]}, index=list("ABCDEFGHIJKLM"))
        _picksrb = [(t, "t", {"close": 100.0}) for t in list("BCDEFGHIJKLM")]
        _hrb2, *_ = track_holdings(_prevh, _picksrb, "Blue", "2026-07-27", _mrb, rebal_anchor="2026-07-13")
        if len(_hrb2) > N_PORT:
            errs.append(f"holdings: リバランス日に{len(_hrb2)}銘柄へ増加（最大{N_PORT}のはず）")
        if set(_hrb2.keys()) != set(_names):
            errs.append(f"holdings: リバランス継続で保有集合が不正 → {sorted(_hrb2.keys())}（A〜L継続のはず）")
    except Exception as _e:
        errs.append(f"holdings self-test raised: {repr(_e)[:80]}")

    # --- 修正回帰ガード ---
    if "残り2/3は10日安値割れ" in html or "出口線（10日安値" in html:
        errs.append("正式出口の説明に旧10日安値ルールが残存")
    if ("一服待ち=見送り" in html or "組み込み待ち＝枠は現金" in html
            or "急落局面で投げ未確認・枠は現金" in html or "新規は一服待ち" in html):
        errs.append("急落バッジが機械的見送りとして残存")
    if "C.color==='Yellow'||C.color==='Red'" not in JS:
        errs.append("黄/赤でSOXL段階投入トラッカーがリセットされない")
    try:
        _idx = [f"Q{i:02d}" for i in range(30)]
        _mm = pd.DataFrame(index=_idx, data={"rs189": np.linspace(100, 71, 30),
                                             "sma50": 200.0, "sma200": 100.0,
                                             "close": 100.0, "ema21": 95.0, "lo10": 90.0})
        _t = _idx[-1]
        _pv = {"date":"2026-07-10", "hold":{_t:{"ed":"2026-07-01","ep":100.0,"peak":110.0,
                                                         "istop":75.0,"sell_due":True,"sell_due_date":"2026-07-13"}}}
        _hh, _vv, *_ = track_holdings(_pv, [], "Blue", "2026-07-13", _mm)
        if _t in _hh or _t in _vv:
            errs.append("sell_due保有が予定日を迎えても追跡から外れない")
    except Exception as _e:
        errs.append(f"sell_due self-test raised: {repr(_e)[:80]}")

    # --- 非常口の発動・解除・欠損時fail-safe単体テスト ---
    try:
        _di = pd.bdate_range("2025-01-02", periods=300)
        _q = pd.Series(np.linspace(100, 150, len(_di)), index=_di)
        _fx = pd.Series(np.linspace(140, 150, len(_di)), index=_di)
        _mac = {"QQQ": pd.DataFrame({"Close": _q}), "JPY=X": pd.DataFrame({"Close": _fx})}
        # ベンチが約+60%の間にNAVが高値から-35%・12Mも劣後 → 発動
        _nav = pd.Series(np.linspace(100, 160, len(_di)), index=_di)
        _nav.iloc[-40:] = np.linspace(158, 100, 40)
        _em1 = build_emergency_brake(_nav, _mac, {}, asof=_di[-1])
        if not _em1.get("available") or not _em1.get("active") or _em1.get("mult") != 0.5:
            errs.append("emergency self-test: trigger failed")
        # データ欠損でも発動済みなら半減を維持
        _em2 = build_emergency_brake(None, {}, {"emergency": _em1}, asof=_di[-1])
        if not _em2.get("active") or _em2.get("mult") != 0.5:
            errs.append("emergency self-test: fail-safe did not preserve active state")
        # NAVを新高値・対QQQ相対も回復させる → 解除
        _nav2 = pd.Series(np.linspace(100, 190, len(_di)), index=_di)
        _em3 = build_emergency_brake(_nav2, _mac, {"emergency": _em1}, asof=_di[-1])
        if _em3.get("active") or _em3.get("mult") != 1.0:
            errs.append("emergency self-test: release failed")
    except Exception as _e:
        errs.append(f"emergency self-test raised: {repr(_e)[:80]}")

    # --- JavaScript 構文チェック + calcRun() ヘッドレス実行（Nodeがあれば）---
    _js_check_completed = False
    try:
        import shutil, subprocess, re, tempfile, json as _json
        if not shutil.which("node"):
            warns.append("REQUIRED-CHECK-SKIPPED: Node unavailable, JS syntax/execution tests were NOT run")   # #5/#9 必須検査未実行→非0
        if shutil.which("node"):
            # メインのJS(グローバル関数群)だけを対象にする。window.CALC=... 等の小さな
            # データ埋め込みscriptや、DOM前提の初期化scriptは対象外（構文検査の誤検出を避ける）。
            _js = JS
            if _js.strip():
                # 1) 構文チェック（実行はしない）
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as _f:
                    _f.write(_js); _jsp = _f.name
                _r = subprocess.run(["node", "--check", _jsp], capture_output=True, text=True, timeout=30)
                if _r.returncode != 0:
                    _msg = (_r.stderr or _r.stdout).strip().splitlines()
                    errs.append("JS構文エラー: " + (_msg[-1] if _msg else "unknown"))
                else:
                    # 2) calcRun() 簡易実行: DOM/localStorage を最小スタブして未定義参照を検出
                    _harness = r"""
                    const store={};
                    global.localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v)},removeItem:k=>{delete store[k]}};
                    // 資産額を入れた状態(has=true)を再現し、株数計算の分岐まで実際に到達させる
                    const _vals={jpyIn:"3000000",fxIn:"150"};
                    function _mk(id){return {value:(id in _vals?_vals[id]:""),innerHTML:"",style:{},
                      getAttribute:()=>"",setAttribute:()=>{},closest:()=>null,querySelector:()=>null,
                      addEventListener:()=>{},appendChild:()=>{},classList:{add:()=>{},remove:()=>{},toggle:()=>{}}};}
                    global.document={getElementById:_mk,querySelector:_mk,querySelectorAll:()=>[],
                      createElement:_mk,addEventListener:()=>{},body:_mk("body")};
                    global.window=global;
                    global.location=global.location||{hash:"",href:"",replace:()=>{}};
                    __JS__
                    try{
                      window.CALC={color:"Yellow",fx:150,e_ind:1.0,e_lev:0.5,alloc_ind:70,alloc_lev:30,n:12,
                        names:[{t:"AAA",px:100,rs:95,rk:1,d52:-5,r5:1.2,drop:false,clx:false},
                               {t:"BBB",px:50,rs:90,rk:2,d52:-12,r5:-1.0,drop:true,clx:false}]};
                      if(typeof calcRun==="function"){calcRun();}
                      // トレードノート回帰: 50@100→10@110利確→50@120追加→90@130全決済
                      let h=_hldInitFilled(_hldNewTrade("TST","swing","2026-07-01"),100,50,"2026-07-01");
                      h.initialStop=90; h.initialRiskTotal=_hldRiskTotal(h,90); h.tpFraction=33; h.tpPct=25;
                      h=_hldRecordExit(h,{type:"partial",date:"2026-07-02",price:110,shares:10,reason:"TP"});
                      h=_hldApplyFill(h,2,"2026-07-03",120,50);
                      const av=h.remainingCost/h.remainingShares;
                      if(Math.abs(av-111.1111111111)>1e-6) throw new Error("remaining avg "+av);
                      h=_hldRecordExit(h,{type:"final",date:"2026-07-04",price:130,shares:90,reason:"close"});
                      _hldFinalize(h,"2026-07-04");
                      const rr=_hldRealized(h);
                      if(Math.abs(rr.pnl-1800)>1e-6) throw new Error("pnl "+rr.pnl);
                      if(Math.abs(rr.R-0.9)>1e-6) throw new Error("R "+rr.R);
                      console.log("CALCRUN_OK"); console.log("TRADELEDGER_OK");
                    }catch(e){console.log("CALCRUN_ERR:"+(e&&e.message||e));}
                    """.replace("__JS__", _js)
                    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as _f2:
                        _f2.write(_harness); _hp = _f2.name
                    _r2 = subprocess.run(["node", _hp], capture_output=True, text=True, timeout=20)
                    _out = (_r2.stdout or "") + (_r2.stderr or "")
                    if "CALCRUN_ERR:" in _out:
                        errs.append("calcRun実行エラー: " + _out.split("CALCRUN_ERR:")[1].strip().splitlines()[0])
                    elif "CALCRUN_OK" not in _out:
                        print("[warn] calcRunの実行結果を確認できず（DOMスタブ不足の可能性）")
                    if "TRADELEDGER_OK" not in _out:
                        errs.append("トレードノート回帰テスト失敗: 残存原価/実現損益/R")
                # 3) #7 最終HTML中の「全<script>ブロック」を抽出し個別に構文検査する。
                #    POST_JS / セクターinline / Overview / DET・HIER・CALC・SWING・SPARK 等の埋め込みも対象。
                #    データ埋め込み(window.X=...JSON)も構文としては妥当でなければならない。
                _blocks = re.findall(r'<script\b[^>]*>(.*?)</script\s*>', html, flags=re.S | re.I)
                _bad = 0
                for _bi, _blk in enumerate(_blocks):
                    if not _blk.strip():
                        continue
                    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as _bf:
                        _bf.write(_blk); _bp = _bf.name
                    _br = subprocess.run(["node", "--check", _bp], capture_output=True, text=True, timeout=20)
                    if _br.returncode != 0:
                        _bad += 1
                        _bm = (_br.stderr or _br.stdout).strip().splitlines()
                        errs.append(f"embedded <script>#{_bi} 構文エラー: " + (_bm[-1] if _bm else "unknown"))
                        if _bad >= 3:
                            break
                _js_check_completed = True
        else:
            # Node無しは上でREQUIRED-CHECK-SKIPPED済み。completedにはしない（未実行を明示）。
            pass
    except Exception as _e:
        # #7 例外(タイムアウト/subprocess失敗/一時ファイル失敗等)で握り潰さない。必須検査未実行として非0にする。
        warns.append("REQUIRED-CHECK-SKIPPED: JS syntax/execution test raised and did NOT complete: " + repr(_e)[:100])
    if shutil_which_safe("node") and not _js_check_completed and not any(str(w).startswith("REQUIRED-CHECK-SKIPPED") for w in warns):
        warns.append("REQUIRED-CHECK-SKIPPED: JS checks did not complete")
    return errs, warns

def shutil_which_safe(name):
    try:
        import shutil
        return shutil.which(name)
    except Exception:
        return None

def selftest_share(share_html):
    """シェアHTML(1200x675カード)の検査: HTML非空・重複ID・SVG内NaN・空d=""パス・<script>構文。"""
    errs = []
    try:
        if not share_html or len(share_html) < 200:
            errs.append("share HTML empty/too short"); return errs
        import re as _r
        # 重複 id
        _ids = _r.findall(r'\bid="([^"]+)"', share_html)
        _dups = sorted({x for x in _ids if _ids.count(x) > 1})
        if _dups:
            errs.append("share duplicate id: " + repr(_dups[:5]))
        # SVG内 NaN / 空パス
        if "NaN" in share_html:
            errs.append("share contains NaN")
        if _r.search(r'\bd="\s*"', share_html) or _r.search(r'\bd="M?\s*"', share_html):
            errs.append("share has empty SVG path")
        # <script> 構文（あれば node --check）
        _m = _r.search(r'<script[^>]*>(.*?)</script>', share_html, _r.S)
        if _m and _m.group(1).strip():
            import tempfile as _tf, subprocess as _sp
            with _tf.NamedTemporaryFile("w", suffix=".js", delete=False) as _f:
                _f.write(_m.group(1)); _jp = _f.name
            try:
                _r2 = _sp.run(["node", "--check", _jp], capture_output=True, text=True, timeout=15)
                if _r2.returncode != 0:
                    _msg = (_r2.stderr or _r2.stdout).strip().splitlines()
                    errs.append("share JS syntax: " + (_msg[-1] if _msg else "unknown"))
            except Exception:
                pass
    except Exception as _e:
        errs.append("share selftest raised: " + repr(_e)[:80])
    return errs

# ----------------------------------------------------------------------------- main
def main():
    _reset_build_globals()          # #17 前回build()の蓄積状態を持ち越さない
    diag = "--diag" in sys.argv
    integration = "--integration-test" in sys.argv
    do_self = "--selftest" in sys.argv or not diag
    # 副作用(state/履歴/ログ/Webhook/本番キャッシュ)は「通常ビルドのみ」。--diag/--selftest/--integration-test では書かない。
    # これによりテストが後段で失敗しても本番stateだけ更新される事故を防ぐ。
    global _ALLOW_NETWORK
    global _PERSIST_CACHES
    offline_selftest = ("--selftest" in sys.argv) and not integration
    explicit_test = ("--selftest" in sys.argv) or integration
    production_run = (not diag) and (not explicit_test)
    _PERSIST_CACHES = production_run     # テスト(selftest/integration)時はmcap/earnings/FRED等のキャッシュを書かない
    if offline_selftest:
        # オフラインselftestは価格/FRED/出力先も固定fixture必須（デフォルトの本番パスへ落とさない）。
        _missing = []
        for _lab, _pth, _need_env in (("V38_UNIVERSE_CSV", UNIVERSE_CSV, False),
                                      ("V38_SECTOR_JSON", SECTOR_JSON, False),
                                      ("V38_CACHE", CACHE, False),
                                      ("V38_FRED_CACHE", os.environ.get("V38_FRED_CACHE"), True),
                                      ("V38_OUT_HTML", os.environ.get("V38_OUT_HTML"), True)):
            if _need_env:
                if not _pth:
                    _missing.append(f"{_lab}=<selftest専用>")
            elif not _pth or not os.path.exists(_pth):
                _missing.append(f"{_lab}={_pth}")
        if _missing:
            raise SystemExit(
                "[selftest] オフラインfixture/出力先が不足しています（--selftestは完全オフライン前提・本番と分離）:\n  "
                + "\n  ".join(_missing) + "\n"
                "  例:\n"
                "    V38_UNIVERSE_CSV=<universe.csv> V38_SECTOR_JSON=<sector.json> \\\n"
                "    V38_CACHE=<prices.pkl(固定)> V38_FRED_CACHE=<fred.json(専用)> V38_OUT_HTML=<out(専用)> \\\n"
                "    python build_dashboard.py --selftest\n"
                "  実データ/実ネットワークで検証する場合は --integration-test を付けてください。")
        _ALLOW_NETWORK = False
        print("[selftest] offline mode: 全ネットワーク停止・本番state/履歴/キャッシュは読み書きしない（strict fixture）")
    elif do_self and not integration and not os.path.exists(UNIVERSE_CSV):
        raise SystemExit(
            "[selftest] universe が見つかりません: %s\n"
            "  実データ/実ネットワークで検証する場合は --integration-test を付けてください。" % UNIVERSE_CSV)
    load_risk_flags(strict=offline_selftest)
    names, order, s2i, s2t, e2j, W, macro, asof = load_inputs()
    W, macro, _cutdate = cut_to_completed(W, macro)   # A5-2: 株式・マクロを同一の確定営業日で切る
    W = guard_last_bar(W)
    # #5 本番の大規模ユニバースでは一部銘柄・日付にyfinance由来の局所異常(0/負/Inf/OHLC不整合)が必ず混じる。
    #   まず局所異常セル/薄い銘柄を隔離(NaN化/列除外)して残りで続行する。数銘柄の異常で全ビルドを止めない。
    W, _san = _sanitize_price_body(W)
    if _san.get("bad_price_cells") or _san.get("incoherent_cells") or _san.get("dropped_tickers"):
        sys.stderr.write("[sanitize] 局所異常を隔離: 非正/非有限セル=%d, OHLC不整合セル=%d, 除外銘柄=%d (%s), 残銘柄=%d\n" % (
            _san.get("bad_price_cells", 0), _san.get("incoherent_cells", 0),
            len(_san.get("dropped_tickers") or []), ",".join((_san.get("dropped_tickers") or [])[:8]), _san.get("kept", 0)))
    # 隔離してもデータ全体が使えない場合(有効銘柄0/最終日全欠測)＝壊滅的なので停止。
    if _san.get("fatal"):
        _fm = "[FATAL] 価格本体(OHLCV)が壊滅的に劣化: " + _san["fatal"]
        if diag and not explicit_test:
            sys.stderr.write(_fm + "（--diagのため続行）\n")
        else:
            raise SystemExit(_fm + " — ビルドを中止します。")
    # 隔離後に残る『構造的』問題のみFATAL（列欠落・軸ズレ・全銘柄で最終行欠測 など少数銘柄では直せないもの）。
    _pb_probs = _validate_price_body(W)
    if _pb_probs:
        _msg = "[FATAL] 価格本体(OHLCV)が構造的に不正です: " + "; ".join(_pb_probs[:6])
        if diag and not explicit_test:
            sys.stderr.write(_msg + "（--diagのため続行）\n")
        else:
            raise SystemExit(_msg + " — 劣化データでのビルドを中止します。")
    try:
        _wlast = W["Close"].index[-1]
        macro = {k: (v[v.index <= _wlast] if hasattr(v, "index") else v) for k, v in macro.items()}   # guardが1日落とした場合の再ズレ防止（監査#次点2）
    except Exception as _e:
        print("[warn] macro re-cut failed:", _e)                        # A5: 部分/不完全な最終バーを落としてから計算
    m, asof_bar = compute_metrics(W, order, s2i, macro=macro)
    global _ANALYSIS_ASOF, _SESSION_INDEX
    _ANALYSIS_ASOF = asof_bar.date()                 # #8 分析用の唯一の基準日
    try:
        _SESSION_INDEX = W["Close"].index            # 実取引セッション（日数計算の基準・祝日反映）
    except Exception:
        _SESSION_INDEX = None
    m["beta"] = build_betas(W, macro)
    # 時価総額: 価格キャッシュの有無に依存せず、ネット可なら欠損/null分だけ補充（#3）。offline時はstrict。
    mcaps = load_market_caps(list(m.index), live=(_net_ok() and not offline_selftest), strict=offline_selftest)
    m["mcap"] = m.index.map(lambda t: mcaps.get(t))
    _mcap_cov = (sum(1 for t in m.index if _valid_mcap(mcaps.get(t))) / len(m.index)) if len(m.index) else 1.0
    m["excluded_theme"] = [is_excluded_theme(t, s2t) for t in m.index]   # 全タブ共通の除外テーマ列（Movers/Setups/Structure Pivot等で効かせる）
    _tier = m["mcap"].map(cap_tier)
    m["tier_key"]  = _tier.map(lambda x: x[0])
    m["tier_lab"]  = _tier.map(lambda x: x[1])
    m["tier_rank"] = _tier.map(lambda x: x[2])
    mri, breakdown, dropped, active, vals = mri_frame(macro, W)
    aux = mri_auxiliary(mri, vals, m)
    setups = build_setups(m)
    picks, cand = build_portfolio(m, s2t)
    leaders = build_leaders(m, s2i, e2j, s2t)
    sectors = build_sector_rs(m, s2i, e2j, s2t)
    breadth = build_breadth(m)
    yields = build_yields(macro)
    # 金利＋圧力系列を1回で取得し、50秒の全体予算を共有する。
    # 以前の2回呼び出し（50秒×2）による最大100秒超の停止を防ぐ。
    _fred_all = fetch_fred_context(FRED_ALL_SERIES, history_days=1200, time_budget=50.0, persist_cache=production_run)
    macro_context = {sid: _fred_all[sid] for sid in FRED_SERIES if sid in _fred_all}
    macro_pressure_ctx = {sid: _fred_all[sid] for sid in FRED_PRESSURE_SERIES if sid in _fred_all}
    sar = read_sar_state(asof_date=asof_bar.date(), strict=offline_selftest)
    _prev_state = load_state(strict=offline_selftest, fail_closed=production_run)   # 破損時は本番のみ停止/復元。offline時は明示env以外読まない
    _rebal_anchor = resolve_rebal_anchor(_prev_state, asof_bar.date())
    _rebal_next = next_rebalance_date(asof_bar.date(), _rebal_anchor, include_today=is_rebalance_date(asof_bar.date(), _rebal_anchor))
    _thist, _tprev = load_trend_history(sar[0], asof_bar.date(), persist=False, strict=offline_selftest, fail_closed=production_run)   # 破損時は本番停止/復元。保存はcommit段で
    _extras = load_market_extras(asof_date=asof_bar.date())
    mkt = {"distrib": build_distribution(macro), "ftd": build_ftd(macro), "perf": build_perf(macro, _extras),
           "sector_ranks": build_sector_ranks(macro, _extras),
           "breadth_ts": build_breadth_ts(W),
           "dollarvol_ts": build_dollarvol_ts(W, macro, lookback=CHART_LB),
           "updown_ts": build_updown_vol_ts(W, macro),
           "credit_ts": build_ratio_ts(macro, "HYG", ["IEI"]) if (macro.get("IEI") is not None) else build_ratio_ts(macro, "HYG", ["LQD"]),
           "credit_den": ("IEI" if (macro.get("IEI") is not None) else "LQD"),
           "defensive_ts": build_ratio_ts(macro, "RSPD", ["RSPS", "RSPU"]),
           "vixterm_ts": build_vix_term_ts(macro),
           "expmove": build_expected_move(macro, m, picks),
           "adline_ts": build_adline_ts(W),
           "trend_prev": _tprev,
           "trend_hist": _thist,
           "asof_bar": asof_bar,
           "mri_ts": [(d.strftime("%Y-%m-%d"), float(v)) for d, v in mri.iloc[-CHART_LB:].items()],
           "leader_temp": build_leader_temp(W),
           "leader_run": build_leader_run(m),
           "leader_breadth": build_leader_breadth(m, macro),
           "transition_leaders": build_transition_leaders(m, macro)}
    mkt["rrg"] = build_rrg(m, s2t)
    mkt["macro_context"] = macro_context
    mkt["fred_all"] = _fred_all            # OVの値注入・データ健全性バナーの統一データ源（全系列）
    mkt["rates_card"] = build_rates_card(macro_context, asof=asof_bar)
    mkt["macro_pulse"] = build_macro_pulse(macro_context, macro_pressure_ctx, asof=asof_bar)
    mkt["rates_card"] += (build_rates_insight(macro_context, asof=asof_bar) or "")
    mkt["macro_pressure_ctx"] = macro_pressure_ctx
    mkt["pressure_card"] = build_macro_pressure(macro_pressure_ctx, macro, asof=asof_bar)
    # ネット流動性（マーケットタブ）＋経済カレンダー・構造マクロ（ウィークリータブ）
    try:
        mkt["net_liq"] = compute_net_liquidity(_fred_all, asof=asof_bar)
    except Exception as _e:
        sys.stderr.write("[net_liq] failed: %r\n" % (repr(_e)[:200])); mkt["net_liq"] = None
    try:
        mkt["net_liq_card"] = build_net_liquidity_card(mkt.get("net_liq"), asof=asof_bar)
    except Exception as _e:
        sys.stderr.write("[net_liq_card] failed: %r\n" % (repr(_e)[:200])); mkt["net_liq_card"] = ""
    try:
        mkt["econ_cal"] = build_econ_calendar(asof=asof_bar)
    except Exception as _e:
        sys.stderr.write("[econ_cal] failed: %r\n" % (repr(_e)[:200])); mkt["econ_cal"] = ""
    try:
        mkt["weekly_macro"] = build_weekly_macro_board(_fred_all, mkt.get("net_liq"), asof=asof_bar)
    except Exception as _e:
        sys.stderr.write("[weekly_macro] failed: %r\n" % (repr(_e)[:200])); mkt["weekly_macro"] = ""
    mkt["reg_hist"] = compute_regime_history(W)
    mkt["regime_state"] = compute_regime_state(m, hist=mkt["reg_hist"])
    try:
        # レジーム履歴(分布/連続/日次バー)は現在色の取得経路に依存させない。
        # 優先順: (1)既に生成済みの日次系列 (2)ローカルNQ CSVの全EXP_STATE_ID履歴 (3)ライブNQ推定。
        _hist_series = _LAST_ONIMINE_SERIES
        if not _hist_series:
            try:
                _csv_series = _sar_series_from_nq_export(asof_date=asof_bar.date(), strict=offline_selftest)   # yfinance不可でもCSVがあれば復元
            except Exception:
                _csv_series = None
            if _csv_series:
                _hist_series = _csv_series
            else:
                try:
                    _estimate_sar_from_live(asof_date=asof_bar.date())   # 最終手段: ライブNQ。副作用で _LAST_ONIMINE_SERIES を設定（as-of切り#7）
                    _hist_series = _LAST_ONIMINE_SERIES
                except Exception:
                    _hist_series = None
        mkt["regime_days"] = _regime_color_stats(_hist_series)
    except Exception:
        mkt["regime_days"] = None
    mkt["rs_continuity"] = build_rs_continuity(W, m, top_n=CONTINUE_TOP_N)
    mkt["lead_pulse"] = build_leadership_pulse(m, mkt["rs_continuity"], s2t)
    mkt["rrg_etf"] = build_rrg_etf(macro, _extras, themes=MICRO_ETFS)
    mkt["etf_hier"] = build_etf_hier(m, s2t)
    mkt["sectors_rs"] = sectors
    mkt["theme_hier"] = build_theme_hierarchy(m, s2t)
    mkt["lev_env"] = build_lev_env(macro)
    mkt["calc"] = build_calc_extras(picks, sar[0], cand)
    if mkt.get("calc") is not None:
        mkt["calc"]["asof"] = str(asof_bar.date())
    # SOXL投入帯 → 配分計算のTQQQ:SOXL比に自動反映（投入帯なら50/50、帯外は全額TQQQ）
    _le = mkt["lev_env"] or {}
    if mkt["calc"] is not None:
        _trend_ok = bool(_le.get("up"))
        _entry_ok = bool(_le.get("entry_ok"))
        _ok = bool(_trend_ok and _entry_ok)
        mkt["calc"]["soxl_w"] = 0.5 if _ok else 0.0
        mkt["calc"]["soxl_trend_ok"] = _trend_ok
        mkt["calc"]["soxl_entry_ok"] = _entry_ok
        if not _trend_ok:
            mkt["calc"]["soxl_reason"] = "SOXX MA50<MA100：既存SOXLも売却し、全額TQQQ"
        elif not _entry_ok:
            mkt["calc"]["soxl_reason"] = (_le.get("entry_txt") or "投入帯外") + "：新規停止、既存分はTQQQ目標から控除"
        else:
            mkt["calc"]["soxl_reason"] = _le.get("entry_txt") or "投入帯"
    mkt["broad_note"] = broad_vs_cap_note(vals)

    # --- v3: sentiment / equity / state+changelog / trail / corr / earnings / quality
    _live = not os.path.exists(CACHE) or os.environ.get("V38_FORCE_LIVE") == "1"
    try:
        mkt["senti"] = build_sentiment(macro, W, live=_live or os.environ.get("V38_SENTI_LIVE") == "1", asof_date=asof_bar.date())
    except Exception as _e:
        sys.stderr.write("[senti] build failed: %r\n" % repr(_e)[:120]); mkt["senti"] = None
    try:
        _eq_s = load_equity(strict=offline_selftest)
        mkt["_wk_acct_expected"] = bool(_eq_s is not None and hasattr(_eq_s, "__len__") and len(_eq_s) >= 2)
        mkt["equity"] = build_equity_view(_eq_s)
        mkt["eq_attrib"] = build_equity_attrib(_eq_s, macro)
        mkt["emergency"] = build_emergency_brake(_eq_s, macro, _prev_state, asof=asof_bar)
        _ema_tk = []
        mkt["ema_touch"] = build_ema21_touch(m, W, s2t, out=_ema_tk); mkt["ema_touch_tk"] = _ema_tk
        mkt["wk_diff"], mkt["wk_board"], mkt["wk_acct"] = build_weekly_unique(
            W, m, s2t, picks, _eq_s, macro, mkt, macro_context, macro_pressure_ctx)
    except Exception as _e:
        sys.stderr.write("[equity] build failed: %r\n" % repr(_e)[:120])
        mkt["equity"] = None
        mkt["emergency"] = build_emergency_brake(None, macro, _prev_state, asof=asof_bar)
    # 非常口はNQゲート後のレバ露出だけに乗算。個別株スリーブは変更しない。
    if mkt.get("calc") is not None:
        _em = mkt.get("emergency") or {}
        _em_mult = float(_em.get("mult", 1.0) or 1.0)
        mkt["calc"]["e_lev_base"] = float(mkt["calc"].get("e_lev", 0.0) or 0.0)
        mkt["calc"]["emergency_mult"] = _em_mult
        mkt["calc"]["emergency_active"] = bool(_em.get("active"))
        mkt["calc"]["e_lev"] = mkt["calc"]["e_lev_base"] * _em_mult
        mkt["calc"]["eq_delim"] = (mkt.get("equity") or {}).get("delim") or ","
        mkt["calc"]["rebal_anchor"] = str(_rebal_anchor)
        mkt["calc"]["next_rebal"] = str(_rebal_next)
    _hold, _hv, _heat, _tf, _carry = track_holdings(_prev_state, picks, sar[0], asof_bar.date(), m, rebal_anchor=_rebal_anchor, closes=W.get("Close"))
    # 表示用hv(dist/sell_due等)に、hold側のed(ランキング入り起点日)をマージ
    try:
        for _t, _hh in (_hv or {}).items():
            if isinstance(_hh, dict) and _t in (_hold or {}):
                _hh["ed"] = (_hold[_t] or {}).get("ed")
    except Exception:
        pass
    mkt["hold"], mkt["heat"] = _hv, _heat
    # #3: Core 12出口はPython(track_holdings)が唯一の仕様。JSのクライアント追跡ピーク再計算をやめ、
    #     Pythonのstop/peakをcalc.namesへ注入してJSはそれを表示するだけにする（乖離を根絶）。
    try:
        _hold_full = _hold or {}
        for _nm in ((mkt.get("calc") or {}).get("names") or []):
            _hd = (_hv or {}).get(_nm["t"]); _hf = _hold_full.get(_nm["t"])
            if _hd:
                _st = _hd.get("stop")
                _nm["sysStop"] = round(float(_st), 2) if (_st is not None and _st == _st) else None
                _nm["sysWhich"] = _hd.get("which")
            if _hf:
                _pk = _hf.get("peak"); _ep = _hf.get("ep")
                _nm["sysPeak"] = round(float(_pk), 2) if (_pk is not None and _pk == _pk) else None
                _nm["sysEntry"] = round(float(_ep), 2) if (_ep is not None and _ep == _ep) else None
    except Exception as _e:
        sys.stderr.write("[calc] core exit inject failed: %r\n" % (_e,))
    mkt["carry"] = _carry                         # 順位落ちだが継続条件を満たす保有（出口監視継続）
    mkt["corr"] = portfolio_corr(W, [t for t, _, _ in picks])
    # レジーム値（changelog＋状態保存用）: SOXL投入帯 / 売買代金トレンド / 集積分散
    _soxl_ok = bool((mkt.get("lev_env") or {}).get("up") and (mkt.get("lev_env") or {}).get("entry_ok"))
    _dvts = mkt.get("dollarvol_ts") if isinstance(mkt.get("dollarvol_ts"), dict) else None
    _turn_dir = ((_dvts or {}).get("uni_trend") or {}).get("dir")
    _udts = mkt.get("updown_ts")
    _ud_reg = _updown_state(_udts[-1][1])[2] if _udts else None
    _chlog, _chref, _major = build_changelog(_prev_state, sar[0], aux, mkt["senti"], picks, asof_bar.date(),
                                             soxl_ok=_soxl_ok, turnover_dir=_turn_dir, updown_reg=_ud_reg,
                                             emergency_active=bool((mkt.get("emergency") or {}).get("active")))
    mkt["chlog"], mkt["chref"] = _chlog, _chref
    _er_tickers = [t for t, _, _ in picks] + list(cand.index[N_PORT:N_PORT + 15])
    mkt["er"] = load_earnings(_er_tickers, live=(_net_ok() and not offline_selftest), strict=offline_selftest)
    # #19 カバー率: universe(order) のうち価格Close列に存在する率・RS189算出可能率。「候補なし」と「データ欠損」を区別。
    try:
        _price_cols = set(W["Close"].columns) if isinstance(W, dict) and hasattr(W.get("Close"), "columns") else set()
    except Exception:
        _price_cols = set()
    _uni_n = len(order) if order else 0
    _price_cov = (sum(1 for t in order if t in _price_cols) / _uni_n) if _uni_n else 1.0
    _rs189_cov = (int(m["rs189"].notna().sum()) / len(m)) if ("rs189" in m and len(m)) else 0.0
    _missing_tk = [t for t in order if t not in _price_cols][:20]
    mkt["quality"] = dict(
        uni_total=len(order), uni_ok=len(m),
        mcap_cov=_mcap_cov, price_cov=_price_cov, rs189_cov=_rs189_cov,
        missing_tickers=_missing_tk,
        split_suspect=int(m["split_suspect"].sum()) if "split_suspect" in m else 0,
        rs_pool=int(m["rs_pool"].sum()) if "rs_pool" in m else len(m),
        nq_src=sar[1],
        next_rebal=f"{_rebal_next}（隔週・月曜）",
        macro_missing=[k for k in MACRO_TICKERS if k not in macro],
        mri_dropped=list(dropped),
        senti_src=(mkt["senti"] or {}).get("avail") or [],
        er_n=len(mkt["er"] or {}), eq=bool(mkt["equity"]),
        emergency_available=bool((mkt.get("emergency") or {}).get("available")),
        emergency_active=bool((mkt.get("emergency") or {}).get("active")),
        state=_chref)
    # persist state (prevdayは直近の別日サマリを保持) + 日次ログ + 通知
    _today = str(asof_bar.date())
    _prevday = (_summ(_prev_state) if (_prev_state.get("date") and _prev_state["date"] != _today)
                else _prev_state.get("prevday"))
    # state/log/Webhookはここでは実行しない。selftest成功→両HTML出力成功の後に production_run のときだけcommitする。
    _pending_state = dict(date=_today, gate=sar[0], mri=round(aux["cur"], 1),
                        bear_lit=[lab for lab, on in aux["bear_flags"] if on],
                        senti=(round(mkt["senti"]["cur"], 1) if mkt["senti"] else None),
                        senti_flags=[l for l, on in (mkt["senti"] or {}).get("flags", []) if on],
                        soxl_band=("投入帯" if _soxl_ok else "帯外"), turnover=_turn_dir, updown=_ud_reg,
                        emergency=mkt.get("emergency"),
                        picks=[t for t, _, _ in picks], hold=_hold, rebal_anchor=str(_rebal_anchor), prevday=_prevday)

    if diag:
        print("=== DIAG ===")
        print(f"metrics tickers: {len(m)} | asof bar: {asof_bar.date()}")
        _sj = SAR_JUDGMENT.get(sar[0], ("", "判定不可"))[1] if sar[0] else "判定不可(無判定)"
        print(f"Trend(SAR): {sar[0]}  判定={_sj}  source={sar[1]}")
        print(f"地合いスコア now: {aux['cur']:.1f}  band: {mri_band(aux['cur'])[0]}")
        print(f"  slope {aux['slope']} | warning {aux['bear_n']}/4 | peak {aux['peak']} (drop {aux['drop']:.1f} from {aux['hi20']:.1f})")
        print(f"  dropped indicators: {dropped or 'none'} | active weights sum: {sum(w for _,w,_,_,_ in active)}")
        print("  breakdown (key: pts/max  raw):")
        for b in breakdown:
            print(f"    {b['key']:12s} {b['pts']:5.1f}/{b['ptsmax']:<3d} raw={b['raw']:.4f}")
        print(f"\nPortfolio N={len(picks)} (no theme cap):")
        for t,th,r in picks:
            print(f"  {t:6s} RS{r['rs']:3.0f}  d%{r['pchg']*100:+5.1f}  v200{r['vs200']*100:+6.1f}  [{th}]")
        print(f"\nSetup counts:")
        for k,v in setups.items():
            print(f"  {k:8s} {len(v):4d}   {', '.join(v[:8])}{' ...' if len(v)>8 else ''}")
        bs, bys = leaders
        ltot = sum(len(v) for v in bs.values())
        print(f"\nLeaders (RS>=85 & >200MA): {ltot} total")
        for code, lab, _ in STATE_DEF:
            print(f"  {code} {lab:14s} {len(bs.get(code,[])):4d}")
        print(f"本日◎押し目 (③ buys): {len(bys)}  " +
              ", ".join(b['t'] for b in bys[:12]) + (' ...' if len(bys) > 12 else ''))
        print(f"\nSector RS top8:")
        for s in sectors[:8]:
            print(f"  {s['score']:5.1f}  {s['ja'][:24]:24s} (n={s['n']})")
        print(f"Sector RS bottom5:")
        for s in sectors[-5:]:
            print(f"  {s['score']:5.1f}  {s['ja'][:24]:24s} (n={s['n']})")
        _d200 = (f"{breadth['pa200']:.0f}%" if _finite(breadth.get('pa200')) else "—")
        _d50  = (f"{breadth['pa50']:.0f}%"  if _finite(breadth.get('pa50'))  else "—")
        print(f"\nBreadth: >200MA {_d200} | >50MA {_d50} | adv/dec {breadth['adv']}/{breadth['dec']} | 52wH {breadth['nh']}")
        print(f"Yields(yf互換): " + " | ".join(f"{k} {d['y']:.2f}%({d['chg']:+.2f})" for k,d in yields.items()))
        print("FRED rates:")
        for _sid in ("DGS2", "DFII10", "T10YIE", "T10Y2Y"):
            _d = (macro_context or {}).get(_sid, {})
            _lvl, _c20, _pct, _stale, _eff = _fred_metrics(_d.get("vals"), _d.get("last_date"), asof=asof_bar)
            if _lvl is None:
                print(f"  {_sid:8s} {_d.get('lab','')}: 取得不可 (src={_d.get('src')})")
            else:
                _bp = "—" if _c20 is None else f"{_c20*100:+.0f}bp"
                print(f"  {_sid:8s} {_d.get('lab',''):12s} {_lvl:.2f}  20日{_bp}  %ile{('' if _pct is None else f'{_pct:.0f}%')}  観測{_d.get('last_date')}({_stale}営業日前) src={_d.get('src')}")
        print("Macro pressure:")
        for _sid in ("BAMLH0A0HYM2", "DTWEXBGS", "NFCI"):
            _d = (macro_pressure_ctx or {}).get(_sid, {})
            _lvl, _c20, _pct, _stale, _eff = _pressure_metrics(_d.get("vals"), _d.get("last_date"), asof=asof_bar)
            if _lvl is None:
                print(f"  {_sid:14s} {_d.get('lab','')}: 取得不可 (src={_d.get('src')})")
            else:
                print(f"  {_sid:14s} {_d.get('lab',''):12s} {_lvl:.3f}  20日{('—' if _c20 is None else f'{_c20:+.3f}')}  3年%ile{('' if _pct is None else f'{_pct:.0f}%')}  観測{_eff} src={_d.get('src')}")
        _bv, _bsrc, _bunit = _bondvol_from_macro(macro)
        print(f"  bondvol       {_bsrc}: " + (f"{_bv[-1][1]:.1f}{_bunit} 観測{_bv[-1][0]}" if _bv else "取得不可"))
        dd = mkt["distrib"]; pf = mkt["perf"]
        print("Distribution days: " + (", ".join(f"{k} {v['n']}({v['st']})" for k,v in dd.items()) or "n/a"))
        if pf and pf.get("indices"):
            for ix in pf["indices"]:
                print(f"{ix['label']} perf: YTD {fmt_pct(ix['ytd'])} 1W {fmt_pct(ix['w1'])} "
                      f"1M {fmt_pct(ix['m1'])} 1Y {fmt_pct(ix['y1'])} | 52w-pos "
                      f"{(ix['pos52'] if ix.get('pos52') is not None else float('nan')):.0f}%")
            if pf.get("vix") is not None:
                print(f"VIX {pf['vix']:.1f} | curve {pf.get('vixcurve')}")
            print(f"divergence: {pf.get('divergence')}")
        sr = mkt["sector_ranks"]
        for grp, lab in [("macro", "大分類"), ("micro", "小分類")]:
            rr = sorted(sr.get(grp, []), key=lambda x: (-(x["d1"] if x["d1"] == x["d1"] else -9)))
            print(f"\nSector {lab} ({len(rr)}) by 1d:")
            for s in rr:
                print(f"  {s['ja']:10s} {s['tk']:5s}  d{fmt_pct(s['d1'])} w{fmt_pct(s['w1'])} m{fmt_pct(s['m1'])}")
        bts = mkt["breadth_ts"]
        if bts:
            print(f"Breadth TS (>200MA): {len(bts)} pts, {bts[0][1]:.0f}% -> {bts[-1][1]:.0f}%")
        print(f"SAR-bullish count: {(m['sar_bull']==True).sum()} / {m['sar_bull'].notna().sum()} valid")
        return

    # Overview投稿カード（実データ）: サンプル数値の静的カードを廃止し、毎ビルドで自動生成
    try:
        _asof_ts = pd.Timestamp(asof)
        if _asof_ts.tzinfo is None:
            _asof_ts = _asof_ts.tz_localize('UTC')
        _ov_asof = _asof_ts.tz_convert('Asia/Tokyo').strftime('%Y-%m-%d %H:%M JST')
    except Exception:
        _ov_asof = str(asof or '')
    try:
        mkt['post1_html'], mkt['post2_html'] = build_overview_cards(dict(
            aux=aux, sar=sar, macro=macro, extras=_extras, mkt=mkt,
            breadth=breadth, sectors=sectors, m=m, asof_disp=_ov_asof))
    except Exception as _e:
        sys.stderr.write('[overview] build failed: %r\n' % repr(_e)[:200])
        mkt['post1_html'] = mkt['post2_html'] = None
    html = render(names, m, mri, breakdown, dropped, aux, setups, picks, cand,
                  sectors, breadth, yields, asof, sar, mkt, leaders, s2i, e2j, s2t, W=W)
    # シェアHTMLもselftest前に生成し、両方を検査する（#17）
    try:
        _ts2 = pd.Timestamp(asof)
        if _ts2.tzinfo is None:
            _ts2 = _ts2.tz_localize("UTC")
        _ad = _ts2.tz_convert("Asia/Tokyo").strftime("%Y-%m-%d")
    except Exception:
        _ad = str(asof_bar.date())
    share = build_share_html(aux, sar, mkt, picks, mkt.get("senti"), _ad)
    # シェアHTML出力先: 拡張子が無い/ディレクトリ名に.htmlを含むケースでメインを上書きしないよう pathlib で厳密化（#18）
    _op = _Path(OUT_HTML)
    share_path = str(_op.with_name(_op.stem + "_share" + (_op.suffix or ".html")))
    assert share_path != OUT_HTML, "share_path が OUT_HTML と衝突"

    _selftest_partial = False
    if do_self:
        errs, warns = selftest(html, picks, setups, sectors, mkt=mkt, W=W, cutdate=_cutdate)
        errs += selftest_share(share)           # シェアHTMLも検査（JS構文/重複ID/SVG NaN/必須要素）
        bs_, bys_ = leaders
        _req_missing = [w for w in warns if str(w).startswith("REQUIRED-CHECK-SKIPPED")]   # 必須検査未実行
        _quality_warns = [w for w in warns if not str(w).startswith("REQUIRED-CHECK-SKIPPED")]
        _release = ("--release" in sys.argv) or (os.environ.get("V38_RELEASE") == "1")
        # --- 最終判定は必ず1つだけ出す（FAILED / PARTIAL / OK[/ with warnings]）---
        if errs:
            print("SELFTEST FAILED:")
            for e in errs: print("  -", e)
            for w in warns: print("  ! " + str(w))
            sys.exit(1)
        elif _req_missing:
            # 必須検査(Node等)が実行できていない→OKにしない。常に非0（検証不完全）。
            print("SELFTEST PARTIAL (必須検査が未実行・検証不完全):")
            for w in _req_missing: print("  ! " + str(w))
            for w in _quality_warns: print("  - " + str(w))
            sys.exit(3)
        elif _quality_warns and _release:
            print("SELFTEST PARTIAL (releaseではデータ品質注意も非合格):")
            for w in _quality_warns: print("  - " + str(w))
            sys.exit(3)
        elif _quality_warns:
            _selftest_partial = True
            print("SELFTEST OK WITH WARNINGS (N=%d, leaders=%d, buys=%d, sectors=%d): %s" %
                  (len(picks), sum(len(v) for v in bs_.values()), len(bys_), len(sectors), "; ".join(str(w) for w in _quality_warns)))
        else:
            print("SELFTEST OK (10 tabs consolidated, restored pickup layout, X-ready market digest, market health v2, emergency brake, RS compare+IN/OUT+continuity, N=%d, leaders=%d, buys=%d, sectors=%d, no None/nan)" %
                  (len(picks), sum(len(v) for v in bs_.values()), len(bys_), len(sectors)))

    # 両HTMLを原子的に書き出し（途中終了で半端ファイルを残さない・#20）
    atomic_write_text(OUT_HTML, html)
    print("WROTE", OUT_HTML, f"({len(html)//1024} KB)")
    atomic_write_text(share_path, share)
    print("WROTE", share_path, "(X投稿用シェアカード 1200x675・スクショして使う)")

    # ここまで全て成功して初めて本番stateをcommit（テスト失敗時は本番stateを一切触らない）
    if production_run:
        _manifest = {"html": "ok", "share": "ok", "state": "pending", "trend": "pending", "log": "pending", "webhook": "skipped", "caches": "pending"}
        _critical_fail = []
        # #5 state/trend/log はトランザクションで一括commit（全tmp成功時のみ置換・部分commitを残さない）
        try:
            _logc = _build_log_csv_content(
                (os.environ.get("V38_LOG_CSV") or os.path.join(os.path.dirname(CACHE), "daily_log.csv")),
                asof_bar.date(), sar[0], aux, mkt["senti"], picks)
            _commit_state_trend_log(_pending_state, _thist, _logc)   # 確定した_thistを保存（commitで再読込しない・#3）
            _manifest["state"] = _manifest["trend"] = _manifest["log"] = "ok"
        except Exception as _e:
            _manifest["state"] = _manifest["trend"] = _manifest["log"] = "failed"
            _critical_fail.append("state/trend/log transaction: " + repr(_e)[:140])
        # #8 critical(state/trend/log)が失敗したら、cache/webhook/backtest manifestは一切更新しない。
        if not _critical_fail:
            _cres = _flush_pending_caches()                      # #6/#8 selftest後にここで初めて反映・per-file結果
            _manifest["caches"] = ("ok" if all(v == "ok" for v in _cres.values()) else _cres) if _cres else "ok"
            if _major:                                           # #8 webhookは非critical・戻り値で成否
                _wr = post_webhook(_chlog, sar[0])
                _manifest["webhook"] = _wr if _wr in ("ok", "failed", "skipped") else "unknown"
            try:                                                 # #12/#13 検証manifest（critical成功時のみ・testedハッシュは書き換えない）
                _bm = dict(BACKTEST_MANIFEST); _bm["current_build_hash"] = LOGIC_HASH
                atomic_write_json(os.path.join(os.path.dirname(OUT_HTML) or ".", "backtest_manifest.json"), _bm)
            except Exception:
                pass
        else:
            _manifest["caches"] = "skipped(critical-fail)"; _manifest["webhook"] = "skipped(critical-fail)"
        try:
            atomic_write_json(os.path.join(os.path.dirname(OUT_HTML) or ".", "commit_manifest.json"), _manifest)
        except Exception:
            pass
        print("COMMIT", _manifest)
        if _critical_fail:
            print("COMMIT FAILED (critical):")
            for e in _critical_fail: print("  -", e)
            sys.exit(2)

if __name__ == "__main__":
    main()
