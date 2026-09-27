"""Shared numerical feature contract for the experimental ten-session strategy."""
import numpy as np
import pandas as pd

PRICE_FEATURES = ['ret1','ret3','ret5','ret10','ret20','ret60','atr','gap','body','upper_wick','lower_wick','location','vol_ratio','vol_dry','range_ratio','ma20_gap','ma60_gap','rs20','market20']
FLOW = ['foreign_net','inst_net','indiv_net','pension_net','trust_net','pef_net','fin_invest_net']
FEATURES = PRICE_FEATURES + [f'{c}_{n}' for c in FLOW for n in (1,5,20)] + ['foreign_response','institution_response']


def features(raw):
    frames=[]
    for _,g in raw.groupby('stock_code',sort=True):
        g=g.sort_values('trading_date').copy().reset_index(drop=True)
        c,o,h,l,v=[g[k] for k in ('close_price','open_price','high_price','low_price','volume')]
        for n in (1,3,5,10,20,60): g[f'ret{n}']=c/c.shift(n)-1
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        g['atr']=tr.rolling(14).mean()/c
        g['gap']=o/c.shift()-1;g['body']=(c-o)/c
        g['upper_wick']=(h-pd.concat([o,c],axis=1).max(axis=1))/c
        g['lower_wick']=(pd.concat([o,c],axis=1).min(axis=1)-l)/c
        g['location']=((c-l)/(h-l).replace(0,np.nan)).fillna(.5)
        g['vol_ratio']=v/v.shift().rolling(20).mean()
        g['vol_dry']=v.rolling(5).mean()/v.rolling(20).mean()
        g['range_ratio']=tr.rolling(5).mean()/tr.rolling(20).mean()
        g['ma20_gap']=c/c.rolling(20).mean()-1;g['ma60_gap']=c/c.rolling(60).mean()-1
        valid=np.isfinite(g[['open_price','high_price','low_price','close_price']]).all(axis=1)
        valid&=(g[['open_price','high_price','low_price','close_price','volume']]>0).all(axis=1)
        valid&=h>=pd.concat([o,c],axis=1).max(axis=1)
        valid&=l<=pd.concat([o,c],axis=1).min(axis=1)
        g['eligible']=(valid.rolling(61).sum()==61)&(g.ret1.abs().rolling(60).max()<=.35)&g.market_cap.ge(200e9)
        g['tv20']=g.actual_amount.rolling(20).mean()
        for col in FLOW:
            normalized=g[col]*g.unit_scale
            for n in (1,5,20): g[f'{col}_{n}']=(normalized.rolling(n).sum()/v.rolling(n).sum()).shift(1)
        g['foreign_response']=g.foreign_net_1*g.ret1.shift(1)
        g['institution_response']=g.inst_net_1*g.ret1.shift(1)
        frames.append(g)
    f=pd.concat(frames,ignore_index=True)
    f['rs20']=f.ret20.where(f.eligible).groupby(f.trading_date).rank(pct=True)
    med=f.ret1.where(f.eligible).groupby(f.trading_date).median().fillna(0)
    level=(1+med).cumprod()
    f['market20']=f.trading_date.map(level/level.shift(20)-1)
    return f


def export_model(model, metadata):
    trees=[]
    for predictors in model._predictors:
        nodes=predictors[0].nodes
        trees.append([{k:float(row[k]) if k in ('value','num_threshold') else int(row[k])
                       for k in ('value','feature_idx','num_threshold','missing_go_to_left','left','right','is_leaf')}
                      for row in nodes])
    return dict(metadata=metadata,features=FEATURES,baseline=float(model._baseline_prediction[0,0]),trees=trees)


def predict(model, frame):
    x=frame[model['features']].to_numpy(dtype=float)
    answer=np.full(len(x),model['baseline'])
    for nodes in model['trees']:
        for i,row in enumerate(x):
            node=nodes[0]
            while not node['is_leaf']:
                value=row[node['feature_idx']]
                left=bool(node['missing_go_to_left']) if np.isnan(value) else value<=node['num_threshold']
                node=nodes[node['left'] if left else node['right']]
            answer[i]+=node['value']
    return answer
