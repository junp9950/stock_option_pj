"""Daily, isolated research signals. No orders, notifications, or production price writes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import logging
import re
import threading

import numpy as np
import pandas as pd
import requests
from sqlalchemy import text

from backend.services.quant_features import FEATURES, FLOW, features, export_model, predict
from backend.utils.dates import get_calendar

ROOT=Path(__file__).resolve().parents[2]/'data'/'quant_strategy'
LOCK=threading.Lock()
LOG=logging.getLogger(__name__)


def is_trading_day(day):
    calendar=get_calendar()
    if calendar is None: raise RuntimeError('KRX calendar unavailable')
    return bool(calendar.is_session(pd.Timestamp(day)))


def save_json(path, payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def completed_session():
    now=datetime.now(ZoneInfo('Asia/Seoul'))
    day=now.date() if now.hour>=16 else now.date()-timedelta(days=1)
    while not is_trading_day(day): day-=timedelta(days=1)
    return day


def scheduled_dates(signal_date):
    cursor=date.fromisoformat(str(signal_date)); sessions=[]
    while len(sessions)<11:
        cursor+=timedelta(days=1)
        if is_trading_day(cursor): sessions.append(str(cursor))
    return sessions[0],sessions[10]


def read_snapshot():
    path=ROOT/'latest.json'
    result=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status':'preparing','candidates':[]}
    try: result['expected_date']=str(completed_session())
    except Exception:
        result.update(expected_date=None,stale=True,calendar_error=True)
        return result
    result['stale']=result.get('signal_date')!=result['expected_date']
    result['updating']=LOCK.locked()
    error=ROOT/'update_status.json'
    if error.exists(): result['update']=json.loads(error.read_text(encoding='utf-8'))
    return result


def publish(f, model, names):
    day=max(f.trading_date)
    today=f[f.trading_date.eq(day)&f.eligible].copy()
    today['prediction']=predict(model,today)
    # The original account assumes 100m KRW and rejects allocations below1% NAV.
    today['capacity']=np.minimum(10_000_000,today.tv20*.001)
    today=today[(today.prediction>0)&(today.capacity>=1_000_000)]
    today=today.sort_values(['prediction','stock_code'],ascending=[False,True])
    entry,exit_day=scheduled_dates(day)
    candidates=[]
    for rank,row in enumerate(today.head(30).itertuples(),1):
        candidates.append(dict(rank=rank,code=row.stock_code,name=names.get(row.stock_code,row.stock_code),
            market_cap=float(row.market_cap),close=float(row.raw_close),score=float(row.prediction),
            turnover20=float(row.tv20),max_order=float(row.capacity),ret20=float(row.ret20*100),
            atr=float(row.atr*100),volume_ratio=float(row.vol_ratio),
            flow_available=bool(np.isfinite(getattr(row,'foreign_net_20')))))
    payload=dict(status='ready',signal_date=str(day),generated_at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                 entry_date=entry,exit_date=exit_day,candidates=candidates,eligible_count=int((f.trading_date.eq(day)&f.eligible).sum()),
                 model=model['metadata'],strategy='quant10-v3',
                 backtest=dict(start='2025-10-01',end='2026-09-23',return_pct=30.2133,mdd_pct=21.1690,double_cost_return_pct=25.4582))
    save_json(ROOT/'latest.json',payload)
    archive=ROOT/'signals'/f'{day}.json'
    if not archive.exists(): save_json(archive,payload)
    return payload


def _price(code):
    response=requests.get('https://fchart.stock.naver.com/sise.nhn',
        params=dict(timeframe='day',count=180,requestType=0,symbol=code),timeout=20)
    response.raise_for_status()
    values=re.findall(r'<item data="(.*?)"',response.text)
    if not values: raise ValueError('empty price history')
    g=pd.read_csv(StringIO('\n'.join(values)),sep='|',header=None,dtype={0:str})
    g.columns=['trading_date','open_price','high_price','low_price','close_price','volume']
    g['trading_date']=pd.to_datetime(g.trading_date,format='%Y%m%d').dt.date
    g['stock_code']=code
    for event_code,factor in [('007460',15),('003060',15)]:
        if code==event_code:
            g.loc[g.trading_date<date(2026,5,8),['open_price','high_price','low_price','close_price']]*=factor
    return g.drop(columns='volume')


def refresh():
    if not LOCK.acquire(blocking=False): return
    try:
        expected=completed_session()
        current=read_snapshot()
        if current.get('signal_date')==str(expected): return
        save_json(ROOT/'update_status.json',dict(status='running',started_at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()))
        cutoff=expected-timedelta(days=300)
        frames=[]
        for year in range(cutoff.year,expected.year+1):
            r=requests.get(f'https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet',timeout=90)
            r.raise_for_status();frames.append(pd.read_parquet(BytesIO(r.content)))
        cap=pd.concat(frames,ignore_index=True)
        cap['trading_date']=pd.to_datetime(cap.Date).dt.date
        cap=cap[cap.trading_date.between(cutoff,expected)].copy()
        if max(cap.trading_date)!=expected: raise ValueError('historical cap source not updated')
        if not np.allclose(cap.Marcap,cap.Close*cap.Stocks): raise ValueError('market cap unit mismatch')
        codes=sorted(cap.loc[cap.Marcap>=200e9,'Code'].unique())
        with ThreadPoolExecutor(max_workers=3) as pool: prices=list(pool.map(_price,codes))
        cap=cap.rename(columns={'Code':'stock_code','Marcap':'market_cap','Amount':'actual_amount','Volume':'raw_volume','Close':'raw_close'})
        raw=pd.concat(prices,ignore_index=True).merge(cap[['stock_code','trading_date','market_cap','actual_amount','raw_volume','raw_close']],
                   on=['stock_code','trading_date'],validate='one_to_one')
        latest=raw[raw.trading_date.eq(expected)]
        expected_codes=set(cap.loc[cap.trading_date.eq(expected)&cap.market_cap.ge(200e9),'stock_code'])
        if not expected_codes.issubset(set(latest.stock_code)): raise ValueError('incomplete price universe')
        from backend.db.database import engine
        with engine.connect() as conn:
            flow=pd.read_sql(text('SELECT trading_date,stock_code,'+','.join(FLOW)+' FROM investor_flow_toss WHERE trading_date>=:d'),conn,params={'d':cutoff})
            stock_names=pd.read_sql(text('SELECT code,name FROM stocks'),conn)
        flow['trading_date']=pd.to_datetime(flow.trading_date).dt.date
        previous=sorted(raw.trading_date.unique())[-2]
        if flow.empty or max(flow.trading_date)<previous: raise ValueError('lagged flow source not updated')
        raw=raw.merge(flow,on=['stock_code','trading_date'],how='left',validate='one_to_one')
        raw['unit_scale']=raw.raw_close/raw.close_price
        raw['volume']=raw.raw_volume*raw.unit_scale
        f=features(raw)
        update_training(f)
        model=json.loads((ROOT/'model.json').read_text(encoding='utf-8'))
        quarter=f'{expected.year}-{((expected.month-1)//3)*3+1:02d}-01'
        if model['metadata']['quarter']!=quarter:
            model=train_quarter(quarter)
            save_json(ROOT/'model.json',model)
        publish(f,model,dict(zip(stock_names.code,stock_names.name)))
        save_json(ROOT/'update_status.json',dict(status='completed',completed_at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()))
    except Exception:
        LOG.exception('Quant strategy refresh failed; retaining dated prior snapshot')
        save_json(ROOT/'update_status.json',dict(status='delayed',message='자료 갱신 또는 검증 지연. 이전 기준일 결과를 유지합니다.'))
    finally: LOCK.release()


def update_training(f):
    """Append only observed executable outcomes. Never label unfinished trades as zero."""
    dates=sorted(f.trading_date.unique())
    calendar=json.loads((ROOT/'sessions.json').read_text())
    calendar=sorted(set(calendar)|{str(d) for d in dates})
    global_index={d:i for i,d in enumerate(calendar)}
    records=[]
    for code,g in f.groupby('stock_code',sort=True):
        g=g.set_index('trading_date').reindex(dates)
        for i in range(len(dates)-11):
            row=g.iloc[i]
            if row.get('eligible')!=True or global_index[str(dates[i])]%3: continue
            entry=g.iloc[i+1].open_price
            if not np.isfinite(entry) or entry<=0: continue
            for j in range(i+11,len(dates)):
                future=g.iloc[j]
                if not future.volume>0: continue
                price=future.open_price if future.open_price>0 else future.close_price
                if not np.isfinite(price) or price<=0: continue
                records.append(dict(stock_code=code,trading_date=str(dates[i]),maturity=str(dates[j]),
                    target=(price/entry*.99875/1.00125-1)*100,**{k:row[k] for k in FEATURES}))
                break
    old=pd.read_parquet(ROOT/'training.parquet')
    if records:
        data=pd.concat([old,pd.DataFrame(records)],ignore_index=True).drop_duplicates(['stock_code','trading_date'],keep='last')
        temporary=ROOT/'training.tmp.parquet';data.to_parquet(temporary,index=False);temporary.replace(ROOT/'training.parquet')
    save_json(ROOT/'sessions.json',calendar)


def train_quarter(quarter):
    from sklearn.ensemble import HistGradientBoostingRegressor
    import sklearn
    data=pd.read_parquet(ROOT/'training.parquet')
    earliest=str((pd.Timestamp(quarter)-pd.DateOffset(months=18)).date())
    fit=data[data.maturity.lt(quarter)&data.trading_date.ge(earliest)&np.isfinite(data.target)]
    if len(fit)<1000: raise ValueError('insufficient matured training observations')
    weights=1/fit.groupby('trading_date').target.transform('size').to_numpy();weights/=weights.mean()
    model=HistGradientBoostingRegressor(max_iter=60,max_leaf_nodes=7,learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=20260927)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        model.fit(fit[FEATURES],np.clip(fit.target,-30,30),sample_weight=weights)
    return export_model(model,dict(quarter=quarter,training_end=str(fit.maturity.max()),training_rows=len(fit),library=sklearn.__version__))
