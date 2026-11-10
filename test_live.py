import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import live


def test_public_status_disconnected_no_fabricated_live_values(monkeypatch):
    monkeypatch.delenv('ALPACA_PAPER_KEY_ID',raising=False)
    monkeypatch.delenv('ALPACA_PAPER_SECRET_KEY',raising=False)
    payload=live.get_public_status()
    assert not payload['connected']
    assert payload['quotes']==[]
    assert payload['account'] is None
    assert payload['orders']==[]
    assert payload['mode']=='NOT CONNECTED'


def test_market_quote_is_explicitly_sourced_and_timed():
    p=live.parse_snapshot({'latestTrade':{'p':621.37,'t':'2026-11-10T15:31:00Z'},'latestQuote':{'bp':621.3,'ap':621.4}},'SPY')
    assert p['symbol']=='SPY'
    assert p['price']==621.37
    assert p['source'].startswith('IEX')
    assert p['observed_at']=='2026-11-10T15:31:00Z'


def test_insufficient_data_blocks_trading():
    assert live.compute_momentum([100.0]*20)=='INSUFFICIENT DATA'
    assert live.compute_momentum([100.0]*20+[100.12])=='LONG'
    assert live.compute_momentum([100.0]*20+[99.88])=='FLAT'
    assert live.compute_momentum([100.0]*20+[100.0])=='HOLD'


def test_no_automatic_orders_without_opt_in(monkeypatch):
    monkeypatch.delenv('PAPER_AUTO_TRADE',raising=False)
    def fail(*a,**k):raise AssertionError('should not call API')
    monkeypatch.setattr(live,'_request',fail)
    live.scan_once()
    assert live._bot_state['signal']=='DISABLED'


def test_public_endpoint_read_only():
    from main import app
    routes=[(next(iter(r.methods)),r.path) for r in app.routes if hasattr(r,'methods')]
    assert ('GET','/api/live') in routes
    assert not any(method in ('POST','PUT','DELETE','PATCH') for method,path in routes if path.startswith('/api/'))
    assert live.PAPER_HOST=='https://paper-api.alpaca.markets'


def test_connected_status_uses_broker_values(monkeypatch):
    monkeypatch.setenv('ALPACA_PAPER_KEY_ID','MOCK_PAPER_KEY')
    monkeypatch.setenv('ALPACA_PAPER_SECRET_KEY','MOCK_PAPER_SECRET')
    monkeypatch.setenv('PAPER_AUTO_TRADE','false')
    live._cached.update(time=0,payload=None)
    def fake(path,**kwargs):
        if path=='/v2/account':return {'equity':'100123.25','cash':'95000.00','buying_power':'95000.00','portfolio_value':'100123.25','last_equity':'100000.00'}
        if path=='/v2/clock':return {'is_open':False,'timestamp':'2026-11-10T21:00:00Z','next_open':'2026-11-11T14:30:00Z'}
        if path=='/v2/positions':return [{'symbol':'SPY','qty':'5','side':'long','unrealized_pl':'123.25'}]
        if path=='/v2/orders':return []
        if path=='/v2/stocks/snapshots':return {'SPY':{'latestTrade':{'p':600.12,'t':'2026-11-10T20:59:00Z'}}}
        if path=='/v2/account/portfolio/history':return {'timestamp':[1794355200,1794441600],'equity':[100000,100123.25]}
        raise AssertionError(path)
    monkeypatch.setattr(live,'_request',fake)
    item=live.get_public_status()
    assert item['connected']
    assert item['account']['equity']==100123.25
    assert item['quotes'][0]['price']==600.12
    assert not item['quotes'][0]['fresh']  # Market closed, don't mark last price live
    assert item['orders']==[]


def test_no_order_when_market_closed_even_if_automation_enabled(monkeypatch):
    monkeypatch.setenv('ALPACA_PAPER_KEY_ID','MOCK_PAPER_KEY')
    monkeypatch.setenv('ALPACA_PAPER_SECRET_KEY','MOCK_PAPER_SECRET')
    monkeypatch.setenv('PAPER_AUTO_TRADE','true')
    def fake(path,**kwargs):
        if path=='/v2/clock':return {'is_open':False}
        raise AssertionError('Should not request market orders or bars on closed market')
    monkeypatch.setattr(live,'_request',fake)
    live.scan_once()
    assert live._bot_state['signal']=='MARKET CLOSED'
