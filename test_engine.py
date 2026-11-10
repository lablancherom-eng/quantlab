import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import backtest,black_scholes

def test_backtest_reproducible():
    a=backtest();b=backtest()
    assert a==b
    assert len(a['curve'])>100
    assert a['metrics']['equity']>0

def test_option_atm():
    a=black_scholes(100,100,1,.05,.2,'call')
    p=black_scholes(100,100,1,.05,.2,'put')
    assert abs(a['price']-10.4506)<.001
    assert abs(a['price']-p['price']-(100-100*__import__('math').exp(-.05)))<.001

def test_costs_reduce_results():
    low=backtest(cost_bps=0)['metrics']['equity']
    high=backtest(cost_bps=40)['metrics']['equity']
    assert high < low
