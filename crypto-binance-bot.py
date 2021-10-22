import os
import time
import math
import random
from binance.client import Client


class CryptoBinanceBot():
    def __init__(self, secret_key, api_key, crypto_markets, interval):
        self.client = Client(api_key, secret_key)
        self.interval = interval
        conv1 = {'1m': 1440, '3m': 480, '5m': 288, '15m': 96, '30m': 48, '1h': 24, '2h': 12, '4h': 6, '8h': 3, '12h': 2, '1d': 1}
        self.sma_interval_amount = conv1[interval]
        self.ema_interval_amount = conv1[interval]

        self.crypto_markets = [CryptoMarket(crm, 
                                            interval,
                                            self.client.get_klines(symbol=crm.split(sep='-')[0].replace('/',''), interval=interval, limit=2000),
                                            crm.split(sep='-')[3], 
                                            self.is_bought(crm.split(sep='-')[0].replace('/',''), crm.split(sep='-')[0].split(sep='/')[0]),
                                            [f["stepSize"] for f in self.client.get_symbol_info(crm.split(sep='-')[0].replace('/',''))["filters"] if f["filterType"]=="LOT_SIZE"][0],
                                            self.sma_interval_amount,
                                            self.ema_interval_amount,
                                            crm.split(sep='-')[1],
                                            crm.split(sep='-')[2])
                               for crm in crypto_markets]
        self.update_in = 0

    def run(self):
        while 1:
            print("Waiting for {} seconds until next kline processing.\n{}".format(self.update_in, "Current balances:"))
            for i in range(len(self.crypto_markets)):
                if i==0:
                    usdt_balance = float(self.client.get_asset_balance(asset="USDT")["free"])
                    print("USDT: ${}\n{}".format(round(usdt_balance, 4),"-"*40))
                cm = self.crypto_markets[i]
                cm.show_stats(float(self.client.get_asset_balance(asset=cm.base_asset)["free"]))

            for i in range(6):
                time.sleep(self.update_in/6.0)
                #if i%2 == 0:
                #    print("{}".format(["I like trains.", "I play pokemon every day.", 
                #                        "Who you play with?", "Come on bull run!", 
                #                        "Data is everywhere.", "Hack me papa.", 
                #                        "I'm a crypto bot, sucker.", "I'm most of the time profitable."][random.randint(0, 7)]))
            for cm in self.crypto_markets:
                if (cm.update_time() - self.client.get_server_time()["serverTime"]) / 1000 <= 0:
                    spam_check = 0
                    while 1:
                        klines = self.client.get_klines(symbol=cm.symbol, interval=cm.interval, limit=2)
                        if not cm.is_live_kline(klines[1]):
                            cm.update_klines(klines)
                            update_in = (cm.update_time() - self.client.get_server_time()["serverTime"]) / 1000
                            if update_in < self.update_in: self.update_in = update_in
                            decision = cm.algorithm_decision()
                            if decision in (-1, 1):
                                if decision == 1:
                                    bought_perc = 0
                                    for m in self.crypto_markets: bought_perc += m.percent if m.bought else 0
                                    asset_balance = cm.percent/(1-bought_perc) * float(self.client.get_asset_balance(asset=cm.quote_asset)["free"])
                                    value = math.floor(asset_balance * 10 ** 8) / 10 ** 8.0
                                else:
                                    asset_balance = float(self.client.get_asset_balance(asset=cm.base_asset)["free"])
                                    if cm.base_asset == "BNB":
                                        # cisto da stoje $2 uvijek za lower fees kad se placa sa BNB
                                        asset_balance -= 2.0/float(self.client.get_klines(symbol=cm.symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=1)[0][4])
                                    tick_decimals = self.tick_decimal_place(cm.tick_size)
                                    value = math.floor(asset_balance * 10 ** tick_decimals) / 10 ** tick_decimals

                                try:
                                    self.place_order(cm.symbol, Client.SIDE_BUY if decision == 1 else Client.SIDE_SELL,
                                                     Client.ORDER_TYPE_MARKET,
                                                     value, Client.ORDER_RESP_TYPE_FULL)
                                    cm.bought = True if decision == 1 else False
                                except Exception as e:
                                    print(e)
                                    print("Couldn't make an order!")
                                    return 0
                            break
                        else:
                            time.sleep(0.2)
                            spam_check += 1
                            if spam_check == 8:
                                return 0
            server_time = self.client.get_server_time()["serverTime"]
            self.update_in = (self.crypto_markets[0].update_time() - server_time)/1000
            for cm in self.crypto_markets:
                tx = (cm.update_time() - server_time)/1000
                if tx < self.update_in: self.update_in = tx

    def place_order(self, symbol, side, type, value, response_type):
        if side == Client.SIDE_BUY:
            order = self.client.create_order(
                symbol=symbol,
                side=side,
                type=type,
                quoteOrderQty=value,
                newOrderRespType=response_type)
        else:
            order = self.client.create_order(
                symbol=symbol,
                side=side,
                type=type,
                quantity=value,
                newOrderRespType=response_type)
        print("Order made:\n{}".format(order))

    def is_bought(self, symbol, asset):
        asset_balance = float(self.client.get_asset_balance(asset=asset)["free"])
        return asset_balance * float(self.client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=1)[0][4]) > 10
        # ako je veci od $10 znaci da je kupljen jer se moze minimum prodati i kupiti $10 bilo kojeg asseta, a i dobro je zbog BNB steka za fees
    
    def tick_decimal_place(self, tick):
        cs = tick.split('.')[1]
        counter = 0
        for c in cs:
            counter += 1
            if c == '1': break
        if counter>8: counter = 8
        return counter

class CryptoMarket:
    def __init__(self, market, interval, recent_klines, percent, bought, tick_size, sma_interval_amount, ema_interval_amount, ema_mod_plus, perc_close):
        self.symbol = market.split(sep='-')[0].replace('/','')
        print("Fetched recent data for {}".format(self.symbol))
        m = market.split(sep='-')[0].split(sep='/')
        self.base_asset = m[0]
        self.quote_asset = m[1]
        self.bought = bought
        self.tick_size = tick_size
        self.interval = interval
        self.interval_ms = {"1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "2h": 2*3600000, "4h": 4*3600000, "8h": 8*3600000, "12h": 12*3600000, "1d": 24*3600000}
        self.percent = float(percent)
        self.live_kline = recent_klines.pop(len(recent_klines)-1)
        self.recent_klines = recent_klines
        self.sma_interval_amount = sma_interval_amount
        self.ema_interval_amount = ema_interval_amount
        self.ema_mod_plus = int(ema_mod_plus)
        self.perc_close = float(perc_close)
        self.prepare_ema()
        self.prepare_ema_mod()

    def show_stats(self, balance):
        print("{}: {} = ${}\n{}={}, {}={}, {}={}, ({}%/{}%)\n{}".format(self.base_asset, balance, 
                                                    round(balance*float(self.live_kline[4]), 4), 
                                                    "ema", round(self.ema, 4), 
                                                    "ema_mod", round(self.ema_mod, 4),
                                                    "sma", round(self.SMA(self.recent_klines, self.sma_interval_amount), 4),
                                                    round(abs(self.SMA_close(self.recent_klines, 24)/float(self.recent_klines[-1][4]) - 1)*100, 3), self.perc_close,
                                                    "-"*40))

    def algorithm_decision(self):
        sma = self.SMA(self.recent_klines, self.sma_interval_amount)
        ema_previous = self.ema
        self.ema = self.EMA(self.recent_klines[-1], self.ema_interval_amount, ema_previous)
        ema_mod_previous = self.ema_mod
        self.ema_mod = self.EMA(self.recent_klines[-1], self.ema_interval_amount+self.ema_mod_plus, ema_mod_previous)

        pos = 1 if self.ema >= sma else -1
        if abs(self.SMA_close(self.recent_klines, 24)/float(self.recent_klines[-1][4]) - 1)*100 > self.perc_close:
            pos = 1 if self.ema_mod >= sma else -1

        if not self.bought and pos == 1:
            return 1
        elif self.bought and pos == -1:
            return -1
        else:
            return 0

    def prepare_ema(self):
        self.ema = float(self.recent_klines[0][4])
        for kline in self.recent_klines:
            self.ema = self.EMA(kline, self.ema_interval_amount, self.ema)
    
    def prepare_ema_mod(self):
        self.ema_mod = float(self.recent_klines[0][4])
        for kline in self.recent_klines:
            self.ema_mod = self.EMA(kline, self.ema_interval_amount+self.ema_mod_plus, self.ema_mod)

    def SMA(self, klines, intervals):
        sum = 0
        for i in range(intervals): sum += (2*float(klines[-(i + 1)][2]) + float(klines[-(i + 1)][4])) / 3.0
        return sum / intervals

    def SMA_close(self, klines, intervals):
        sum = 0
        for i in range(intervals): sum += float(klines[-(i + 1)][4])
        return sum / intervals

    def EMA(self, kline, intervals, last_ema, smoothing=2):
        return ((2*float(kline[2]) + float(kline[4])) / 3.0) * (smoothing / (1 + intervals)) + last_ema * (
                    1 - smoothing / (1 + intervals))

    def is_live_kline(self, kline):
        return self.kline_update_time(kline) == self.kline_update_time(self.live_kline)

    def update_time(self):
        return self.kline_update_time(self.live_kline)

    def kline_update_time(self, kline):
        return kline[0] + self.interval_ms[self.interval]

    def update_klines(self, klines):
        self.recent_klines.pop(0)
        self.recent_klines.append(klines[0])
        self.live_kline = klines[1]

if __name__ == '__main__':
    #DIVERSIFICATION, SEASONS (BITCOIN - MID - ALTCOIN)
    season = ["BTC", "MID", "ALT"].index(os.environ.get("SEASON"))
    #primjer 2-0.75/0.63/0.6-0.67/0.33-0.525/0.475-0.417/0.583 Season members-btc/mid/alt-btcbtc/ethbtc-btcmid/ethmid-btcalt/ethalt
    bm_coins = os.environ.get("BM_COINS")
    #primjer 4/0.15/0.22/0.22 Season members/btc/mid/alt
    mm_coins = os.environ.get("MM_COINS")
    sm_coins = os.environ.get("SM_COINS")
    #primjer nekadasnji "BTCUSDT-BTC/USDT-0.21-2-6,..."
    #primjer recent "BTC/USDT-2-6,..." i doda na kraj tipa "BTC/USDT-2-6-0.37",...
    markets = os.environ.get("MARKETS").split(sep=',')
    
    market_lengths = [int(bm_coins.split('-')[0])]
    market_lengths.append(market_lengths[0] + int(mm_coins.split('/')[0]))
    market_lengths.append(market_lengths[1] + int(sm_coins.split('/')[0]))

    for i in range(len(markets)):
        markets[i] += '-'
        if i < market_lengths[0]:
            bm_vars = bm_coins.split('-')
            markets[i] += str(float(bm_vars[1].split('/')[season]) * float(bm_vars[2 + season].split('/')[i]))
        elif i < market_lengths[1]:
            mm_vars = mm_coins.split('/')
            markets[i] += str(float(mm_vars[1 + season]) / int(mm_vars[0]))
        elif i < market_lengths[2]:
            sm_vars = sm_coins.split('/')
            markets[i] += str(float(sm_vars[1 + season]) / int(sm_vars[0]))
    

    binance_bot = CryptoBinanceBot(
        os.environ.get("SCRK"), os.environ.get("APIK"),
        markets,
        os.environ.get("KLINE_INTERVAL"))
    binance_bot.run()
