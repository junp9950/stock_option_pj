import json
from datetime import date
import numpy as np
import pandas as pd
from backend.services import quant_strategy as service
from backend.services.quant_features import features, predict, FEATURES, FLOW


def test_feature_prefix_does_not_use_future_prices_or_cap():
    dates=pd.bdate_range('2025-01-01',periods=100).date
    price=np.arange(100,dtype=float)+100
    raw=pd.DataFrame(dict(stock_code='A',trading_date=dates,open_price=price,
        high_price=price+2,low_price=price-2,close_price=price,volume=10000.,
        market_cap=200e9,actual_amount=2e9,unit_scale=1.,**{c:100. for c in FLOW}))
    long=features(raw);short=features(raw.iloc[:90])
    pd.testing.assert_frame_equal(long.iloc[:90][FEATURES+['eligible']],short[FEATURES+['eligible']])
    assert short.eligible.iloc[-1]
    raw.loc[89,'market_cap']=200e9-1
    assert not features(raw.iloc[:90]).eligible.iloc[-1]


def test_portable_model_missing_direction():
    nodes=[dict(is_leaf=0,feature_idx=0,num_threshold=3,missing_go_to_left=1,left=1,right=2),
           dict(is_leaf=1,value=2),dict(is_leaf=1,value=-1)]
    model=dict(features=['x'],baseline=.5,trees=[nodes])
    np.testing.assert_allclose(predict(model,pd.DataFrame({'x':[np.nan,2,4]})),[2.5,2.5,-.5])


def test_old_snapshot_remains_explicitly_stale(tmp_path,monkeypatch):
    monkeypatch.setattr(service,'ROOT',tmp_path)
    monkeypatch.setattr(service,'completed_session',lambda:date(2026,9,28))
    service.save_json(tmp_path/'latest.json',{'signal_date':'2026-09-23','candidates':[],'status':'ready'})
    result=service.read_snapshot()
    assert result['stale'] and result['expected_date']=='2026-09-28'


def test_schedule_is_next_session_and_ten_sessions_later(monkeypatch):
    monkeypatch.setattr(service,'is_trading_day',lambda d:d.weekday()<5)
    assert service.scheduled_dates('2026-09-25')==('2026-09-28','2026-10-12')


def test_existing_signal_archive_is_immutable(tmp_path,monkeypatch):
    monkeypatch.setattr(service,'ROOT',tmp_path)
    monkeypatch.setattr(service,'scheduled_dates',lambda d:('2026-09-28','2026-10-14'))
    frame=pd.DataFrame(dict(trading_date=[date(2026,9,23)],eligible=[True],stock_code=['A'],
        tv20=[2e9],market_cap=[200e9],raw_close=[100],ret20=[.1],atr=[.02],vol_ratio=[1.],foreign_net_20=[.01],x=[1.]))
    model=dict(features=['x'],baseline=1.,trees=[],metadata={'quarter':'2026-07-01'})
    service.publish(frame,model,{'A':'example'})
    archived=(tmp_path/'signals'/'2026-09-23.json').read_text(encoding='utf-8')
    model['baseline']=2.
    service.publish(frame,model,{'A':'example'})
    assert (tmp_path/'signals'/'2026-09-23.json').read_text(encoding='utf-8')==archived
    assert json.loads((tmp_path/'latest.json').read_text(encoding='utf-8'))['candidates'][0]['score']==2.
