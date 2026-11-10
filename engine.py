"""Educational reproducible synthetic-market backtester. No live trading or real data."""
import math
from datetime import date, timedelta
import numpy as np

STARTING_CAPITAL = 100_000.0

def synthetic_prices(n=520, seed=47):
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0.00035, 0.012, n))
    spread = np.zeros(n)
    for i in range(1,n):
        spread[i] = 0.94*spread[i-1] + rng.normal(0,0.011)
    a = 102*np.exp(common + spread/2)
    b = 99*np.exp(common - spread/2)
    dates = [(date(2024, 10, 1)+timedelta(days=i)).isoformat() for i in range(n*2) if (date(2024, 10, 1)+timedelta(days=i)).weekday()<5][:n]
    return np.array(a),np.array(b),dates

def backtest(lookback=40,entry=2.0,exit_z=0.4,cost_bps=3):
    if not (20 <= lookback <= 100 and 0.8 <= entry <= 3.5 and 0.1 <= exit_z < entry and 0 <= cost_bps <= 50):
        raise ValueError('Invalid backtest settings')
    a,b,dates=synthetic_prices()
    log_spread=np.log(a)-np.log(b)
    z=np.zeros(len(a))
    for i in range(lookback,len(a)):
        window=log_spread[i-lookback:i]
        sd=np.std(window,ddof=1)
        z[i]=(log_spread[i]-np.mean(window))/sd if sd>1e-10 else 0
    # Decisions based on close t, applied to next close-to-close return (no look-ahead).
    positions=np.zeros(len(a))
    trades=[]
    pos=0
    eq=STARTING_CAPITAL
    equity=[eq]
    benchmark=[STARTING_CAPITAL]
    daily=[]
    for i in range(1,len(a)):
        prev=positions[i-1]
        ra=a[i]/a[i-1]-1
        rb=b[i]/b[i-1]-1
        ret=prev * (ra-rb)/2
        eq *= 1+ret
        benchmark.append(STARTING_CAPITAL*a[i]/a[0])
        if i >= lookback:
            old=pos
            if pos == 0:
                if z[i] > entry: pos=-1
                elif z[i] < -entry: pos=1
            elif (pos==1 and z[i] >= -exit_z) or (pos==-1 and z[i] <= exit_z):
                pos=0
            if old != pos:
                # One-way turnover: opening or closing a 50/50 long-short basket charges 1x capital.
                turn=abs(pos-old)
                fee=turn*cost_bps/10000
                eq *= (1-fee)
                trades.append({'date':dates[i], 'action':'OPEN LONG SPREAD' if old==0 and pos==1 else 'OPEN SHORT SPREAD' if old==0 else 'CLOSE POSITION', 'z':round(float(z[i]),2), 'cost':round(eq*fee,2),'position':int(pos)})
        positions[i]=pos
        equity.append(eq)
        daily.append(eq/equity[-2]-1)
    curve=np.array(equity)
    returns=np.array(daily)
    dd=curve/np.maximum.accumulate(curve)-1
    volatility=float(np.std(returns,ddof=1)*np.sqrt(252))
    sharpe=float(np.mean(returns)/np.std(returns,ddof=1)*np.sqrt(252)) if np.std(returns,ddof=1)>1e-10 else 0.
    years=(len(curve)-1)/252
    annual=(curve[-1]/curve[0])**(1/years)-1
    # VaR / ES on daily historical simulated strategy returns, not market forecast.
    var=float(-np.percentile(returns,5))
    es=float(-np.mean(returns[returns<=np.percentile(returns,5)]))
    return {
        'mode':'SYNTHETIC BACKTEST — NOT LIVE TRADING', 'initial_capital':STARTING_CAPITAL,
        'metrics':{'equity':round(float(curve[-1]),2),'total_return':round(float(curve[-1]/curve[0]-1)*100,2),'annual_return':round(float(annual)*100,2),'sharpe':round(sharpe,2),'volatility':round(volatility*100,2),'max_drawdown':round(float(min(dd))*100,2),'var95':round(var*100,2),'expected_shortfall95':round(es*100,2),'trades':len(trades)},
        'curve':[{'date':dates[i],'equity':round(float(curve[i]),2),'benchmark':round(float(benchmark[i]),2),'drawdown':round(float(dd[i])*100,2)} for i in range(0,len(curve),3)],
        'recent_trades':trades[-12:][::-1],
        'current_signal':{'z_score':round(float(z[-1]),2),'position':int(pos),'spread':round(float(log_spread[-1]),4)},
        'settings':{'lookback':lookback,'entry':entry,'exit':exit_z,'cost_bps':cost_bps},
        'notes':['All asset prices are synthetic and reproducible.','A signal observed at close t earns returns starting after close t.','Trading cost is deducted for each opening and closing turnover.','This is an illustrative backtest, not evidence of investment skill.']
    }

def norm_cdf(x):
    return 0.5*(1+math.erf(x/math.sqrt(2)))

def norm_pdf(x):
    return math.exp(-0.5*x*x)/math.sqrt(2*math.pi)

def black_scholes(spot=100,strike=100,t=1,rate=.04,sigma=.25,kind='call'):
    if spot<=0 or strike<=0 or t<=0 or sigma<=0 or not (-.2<=rate<=1) or kind not in ['call','put']:
        raise ValueError('Invalid option inputs')
    d1=(math.log(spot/strike)+(rate+sigma*sigma/2)*t)/(sigma*math.sqrt(t))
    d2=d1-sigma*math.sqrt(t)
    call=spot*norm_cdf(d1)-strike*math.exp(-rate*t)*norm_cdf(d2)
    put=call-spot+strike*math.exp(-rate*t)
    delta=norm_cdf(d1) if kind=='call' else norm_cdf(d1)-1
    gamma=norm_pdf(d1)/(spot*sigma*math.sqrt(t))
    vega=spot*norm_pdf(d1)*math.sqrt(t)/100
    theta=-(spot*norm_pdf(d1)*sigma)/(2*math.sqrt(t)) - rate*strike*math.exp(-rate*t)*norm_cdf(d2) if kind=='call' else -(spot*norm_pdf(d1)*sigma)/(2*math.sqrt(t))+rate*strike*math.exp(-rate*t)*norm_cdf(-d2)
    rho=(strike*t*math.exp(-rate*t)*norm_cdf(d2))/100 if kind=='call' else -(strike*t*math.exp(-rate*t)*norm_cdf(-d2))/100
    return {'price':round(call if kind=='call' else put,4),'delta':round(delta,5),'gamma':round(gamma,6),'vega':round(vega,4),'theta':round(theta/365,4),'rho':round(rho,4),'d1':round(d1,4),'d2':round(d2,4),'kind':kind,'note':'European option, no dividends. Vega and rho per 1 percentage-point change; theta per calendar day.'}
