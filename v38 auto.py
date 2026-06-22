#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V38 リーダー監視 — 毎朝自動更新版（GitHub Actions 等のスケジューラで実行）
=====================================================================
やること（手間ゼロ運用）:
  1) ユニバース(universe.csv) のティッカーを yfinance で自動取得
  2) 高RS×上昇のリーダーを抽出し、状態タグ①〜⑤を判定
  3) Google Sheet の「リーダー監視」「本日◎押し目」タブを上書き更新（色分け付）
データは yfinance が毎回取りに行くので、日々の手作業は不要。

環境変数（GitHub Secrets 等で設定）:
  GOOGLE_CREDS      … サービスアカウント鍵 JSON の中身（文字列まるごと）  ※必須
  OUTPUT_SHEET_ID   … 出力先 Google Sheet の ID                          ※必須
  SECTOR_SHEET_ID   … 業種状況シートの ID（業種RSを生で読む。任意）       ※任意
                      未設定なら同梱 sector_snapshot.json を使用
"""
import os, json, datetime as dt, warnings
import pandas as pd, numpy as np
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_CSV = os.path.join(HERE, 'universe.csv')
SNAPSHOT     = os.path.join(HERE, 'sector_snapshot.json')
LEADER_RS    = 0.85
HIGH_LB      = 40

STATE_ORDER = ['①伸び過ぎ(待ち)', '②新高値圏/継続', '③◎押し目(買い)', '④深押し/ベース', '⑤割れ/様子見']
STATE_RGB = {  # 0-1 RGB
    '①伸び過ぎ(待ち)': (1.000, 0.949, 0.800), '②新高値圏/継続': (0.886, 0.937, 0.855),
    '③◎押し目(買い)': (0.663, 0.816, 0.557), '④深押し/ベース': (0.988, 0.894, 0.839),
    '⑤割れ/様子見':   (0.949, 0.863, 0.859),
}

# ---------------- セクター RS（任意で生読み、無ければスナップショット） ----------------
def load_sector(gc):
    sid = os.environ.get('SECTOR_SHEET_ID', '').strip()
    if sid and gc is not None:
        try:
            sh = gc.open_by_key(sid)
            def grab(tab):
                return sh.worksheet(tab).get_all_values()
            si = grab('業種セクタ'); s2i = {r[0]: r[1] for r in si if len(r) > 1 and r[0] and r[0] != 'Symbol' and r[1]}
            rk = grab('ランク推移'); e2j = {r[0]: r[1] for r in rk[1:] if len(r) > 1 and r[0] and r[1]}
            rs = grab('業種RS');   j2rs = {r[0]: float(r[1]) for r in rs if len(r) > 1 and r[0] and str(r[1]).replace('-', '').replace('.', '').isdigit()}
            dj = grab('独自業種');  s2t = {r[0]: (r[2] if len(r) > 2 else None, r[3] if len(r) > 3 else None) for r in dj[1:] if r and r[0]}
            print(f'  セクターRS: 業種状況シートから生読み（{len(j2rs)} 業種）')
            return s2i, e2j, j2rs, s2t
        except Exception as e:
            print(f'  セクターRS 生読み失敗→スナップショット使用: {e}')
    d = json.load(open(SNAPSHOT, encoding='utf-8'))
    print(f'  セクターRS: 同梱スナップショット（{len(d["j2rs"])} 業種）')
    return d['s2i'], d['e2j'], d['j2rs'], {k: tuple(v) for k, v in d['s2t'].items()}

# ---------------- OHLCV 自給（yfinance） ----------------
def fetch_ohlcv(uni):
    import yfinance as yf
    yf2disp = dict(zip(uni['YF_Ticker'].astype(str), uni['Ticker'].astype(str)))
    tickers = sorted(set(uni['YF_Ticker'].dropna().astype(str)))
    print(f'  yfinance 取得: {len(tickers)} 銘柄 …')
    raw = yf.download(tickers, period='400d', auto_adjust=True, progress=False, threads=True)
    frames = []
    for field in ['Open', 'High', 'Low', 'Close', 'Volume']:
        sub = raw[field] if isinstance(raw.columns, pd.MultiIndex) else raw[[field]].rename(columns={field: tickers[0]})
        sub = sub.copy(); sub.index.name = 'Date'
        frames.append(sub.reset_index().melt(id_vars='Date', var_name='YF', value_name=field).set_index(['Date', 'YF']))
    df = pd.concat(frames, axis=1).reset_index().dropna(subset=['Close'])
    df['Ticker'] = df['YF'].map(yf2disp).fillna(df['YF'])
    return df.sort_values(['Ticker', 'Date'])

# ---------------- 特徴量・状態 ----------------
def feat(g):
    g = g.tail(260); c = g['Close'].values; h = g['High'].values; l = g['Low'].values; v = g['Volume'].values; n = len(c)
    if n < 70: return None
    cur = c[-1]; ma21 = c[-21:].mean(); ma50 = c[-50:].mean() if n >= 50 else np.nan
    ma200 = c[-200:].mean() if n >= 200 else np.nan; hi = h[-HIGH_LB:].max(); avgv = np.mean(v[-50:]) if n >= 50 else np.nan
    return pd.Series(dict(cur=cur, ma21=ma21, ma50=ma50, ma200=ma200, hi=hi, pb=cur/hi-1, dma21=cur/ma21-1,
        dma50=(cur/ma50-1 if not np.isnan(ma50) else np.nan), ret5=(cur/c[-6]-1 if n >= 6 else np.nan),
        ret20=(cur/c[-21]-1 if n >= 21 else np.nan), adr=float(np.mean(h[-20:]/l[-20:]-1)),
        r63=(cur/c[-64]-1 if n >= 64 else np.nan), rvol=float(v[-1]/avgv) if (avgv and avgv > 0) else np.nan))

def tag(r):
    if (not np.isnan(r.dma50) and r.cur < r.ma50) or r.dma21 < -0.06: return '⑤割れ/様子見'
    if r.pb < -0.08: return '④深押し/ベース'
    if -0.08 <= r.pb <= -0.02 and -0.05 <= r.dma21 <= 0.05 and r.ret5 > -0.03: return '③◎押し目(買い)'
    if r.dma21 > 0.10: return '①伸び過ぎ(待ち)'
    return '②新高値圏/継続'

# ---------------- Sheet 書き込み ----------------
def write_sheet(gc, lead, buy):
    sid = os.environ['OUTPUT_SHEET_ID'].strip()
    sh = gc.open_by_key(sid)
    HDR_FMT = {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
               'backgroundColor': {'red': 0.122, 'green': 0.306, 'blue': 0.373}, 'horizontalAlignment': 'CENTER'}

    def put(name, header, rows, state_col=None):
        try: ws = sh.worksheet(name)
        except Exception: ws = sh.add_worksheet(title=name, rows=len(rows)+20, cols=len(header)+2)
        ws.clear()
        body = [header] + rows
        try: ws.update(range_name='A1', values=body)
        except TypeError: ws.update('A1', body)
        try:
            ws.freeze(rows=1)
            ws.format(f'A1:{chr(64+len(header))}1', HDR_FMT)
            if state_col is not None:
                batch = []
                for i, rrow in enumerate(rows):
                    col = STATE_RGB.get(rrow[state_col])
                    if col: batch.append({'range': f'A{i+2}', 'format': {'backgroundColor': {'red': col[0], 'green': col[1], 'blue': col[2]}}})
                if batch: ws.batch_format(batch)
        except Exception as e:
            print(f'  ({name} 書式は一部スキップ: {e})')

    h1 = ['状態', 'Ticker', '銘柄名', 'テーマ', '業種', '業種RS', 'RS', '押し目%', '21MA乖離%', '20日%', 'ADR%', 'RVOL', '現在値']
    r1 = [[r['state'], r['Ticker'], (str(r['name'])[:28] if pd.notna(r['name']) else ''),
           (str(r['theme'])[:18] if pd.notna(r['theme']) else ''), (str(r['jp'])[:20] if pd.notna(r['jp']) else ''),
           (int(r['secRS']) if pd.notna(r['secRS']) else ''), int(round(r['rs63_q']*100)),
           round(r['pb']*100, 1), round(r['dma21']*100, 1), round(r['ret20']*100, 1), round(r['adr']*100, 1),
           (round(r['rvol'], 2) if pd.notna(r['rvol']) else ''), round(r['cur'], 2)] for _, r in lead.iterrows()]
    put('リーダー監視', h1, r1, state_col=0)

    h2 = ['Ticker', 'テーマ', '業種', '業種RS', 'RS', '押し目%', 'ADR%', 'RVOL', '現在値', 'ｴﾝﾄﾘｰ下限', 'ｴﾝﾄﾘｰ上限', '+15%目標', '+30%目標']
    r2 = [[r['Ticker'], (str(r['theme'])[:18] if pd.notna(r['theme']) else ''), (str(r['jp'])[:18] if pd.notna(r['jp']) else ''),
           (int(r['secRS']) if pd.notna(r['secRS']) else ''), int(round(r['rs63_q']*100)), round(r['pb']*100, 1),
           round(r['adr']*100, 1), (round(r['rvol'], 2) if pd.notna(r['rvol']) else ''), round(r['cur'], 2),
           round(r['lo'], 2), round(r['hiR'], 2), round((r['lo']+r['hiR'])/2*1.15, 2), round((r['lo']+r['hiR'])/2*1.30, 2)]
          for _, r in buy.iterrows()]
    put('本日◎押し目', h2, r2)
    print(f'  → Google Sheet 更新完了: {sh.title}')

# ---------------- MAIN ----------------
def main():
    today = dt.date.today().isoformat()
    print(f'=== V38 自動更新 {today} ===')
    import gspread
    gc = gspread.service_account_from_dict(json.loads(os.environ['GOOGLE_CREDS']))

    uni = pd.read_csv(UNIVERSE_CSV)
    s2i, e2j, j2rs, s2t = load_sector(gc)
    def look(s):
        e = s2i.get(s); jp = e2j.get(e, e) if e else None; big, sub = s2t.get(s, (None, None))
        return jp, (j2rs.get(jp) if jp else None), big, sub

    df = fetch_ohlcv(uni)
    F = df.groupby('Ticker').apply(feat).dropna(how='all').reset_index()
    F['rs63_q'] = F['r63'].rank(pct=True)
    F = F.merge(uni[['Ticker', 'name']], on='Ticker', how='left')
    F[['jp', 'secRS', 'theme', 'sub']] = F['Ticker'].apply(lambda s: pd.Series(look(s)))

    lead = F[(F.ma200.notna()) & (F.cur > F.ma200) & (F.rs63_q >= LEADER_RS)].copy()
    lead['state'] = lead.apply(tag, axis=1); lead['secRS_s'] = lead['secRS'].fillna(-1)
    lead = lead.sort_values(['secRS_s', 'rs63_q'], ascending=False).reset_index(drop=True)

    buy = lead[lead.state == '③◎押し目(買い)'].copy(); buy['adr_d'] = buy.cur*buy.adr
    buy['lo'] = np.maximum(buy.ma21-0.5*buy.adr_d, buy.hi*0.92); buy['hiR'] = buy.cur
    b = buy.lo >= buy.hiR; buy.loc[b, 'lo'] = buy.loc[b, 'hiR']*0.985
    buy = buy.sort_values(['secRS_s', 'rs63_q'], ascending=False).reset_index(drop=True)

    cnt = lead['state'].value_counts()
    print('  リーダー %d:' % len(lead), ' / '.join(f'{s.split("(")[0]}={cnt.get(s,0)}' for s in STATE_ORDER))
    write_sheet(gc, lead, buy)

if __name__ == '__main__':
    main()
