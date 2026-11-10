"""QuantLab public research demo. No endpoints can send orders."""
import os
from pathlib import Path
from contextlib import asynccontextmanager
from live import get_public_status, start_worker, stop_worker, configured, auto_enabled
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from engine import backtest, black_scholes

@asynccontextmanager
async def lifespan(app):
    start_worker()
    yield
    stop_worker()

app=FastAPI(title='QuantLab Research & Paper Trading API',version='2.0.0',lifespan=lifespan)
BASE=Path(__file__).parent
app.mount('/assets',StaticFiles(directory=BASE/'site'),name='assets')

@app.get('/')
def index():
    return FileResponse(BASE/'site'/'index.html')

@app.get('/api/health')
def health():
    return {'status':'ok','environment':'paper-trading-capable','paper_credentials_configured':configured(),'automatic_paper_orders_enabled':auto_enabled(),'live_money_orders_possible':False}

@app.get('/api/backtest')
def research(lookback:int=Query(40,ge=20,le=100),entry:float=Query(2,ge=.8,le=3.5),exit:float=Query(.4,ge=.1,le=3),cost_bps:float=Query(3,ge=0,le=50)):
    try: return backtest(lookback=lookback,entry=entry,exit_z=exit,cost_bps=cost_bps)
    except ValueError as ex: raise HTTPException(422,str(ex))

@app.get('/api/options')
def options(spot:float=Query(100,gt=0,le=1000000),strike:float=Query(100,gt=0,le=1000000),t:float=Query(1,gt=0,le=50),rate:float=Query(.04,ge=-.2,le=1),sigma:float=Query(.25,gt=0,le=5),kind:str='call'):
    try: return black_scholes(spot,strike,t,rate,sigma,kind)
    except ValueError as ex: raise HTTPException(422,str(ex))

@app.get('/api/live')
def live_dashboard():
    return get_public_status()

@app.get('/api/integration')
def integration():
    return {'provider':'Alpaca','connected':configured(),'paper_order_automation':auto_enabled(),'live_money_orders_possible':False,'message':'Alpaca Paper Trading only; credentials are configured on the server, never supplied through this public endpoint.'}
