from huobi.HuobiDMService import HuobiDM

import os
import time
import numpy as np
import json
import pandas as pd
import redis
import datetime
import decimal
import inspect
import sys


def round_down(value, decimals):
    with decimal.localcontext() as ctx:
        d = decimal.Decimal(value)
        ctx.rounding = decimal.ROUND_DOWN
        return float(round(d, decimals))

        
class liveTrading():
    def __init__(self, exchange, symbol='BTC/USD', testnet=True, lev=20, stop=0.96):
        self.symbol = symbol
        self.lev = lev
        self.symbol_here = ""
        self.exchange_name = exchange
        self.stop=stop
        
        if exchange == 'huobi_swap':
            if testnet == True:
                sys.exit("Testnet is not available for this exchange")
            else:
                apiKey = os.getenv('HUOBI_ID')
                apiSecret = os.getenv('HUOBI_SECRET')
                self.exchange = HuobiDM("https://api.hbdm.com", apiKey, apiSecret)

            if self.symbol == "BTC-USD":
                self.symbol_here = "BTC-USD"

            self.increment = 0.1
            self.lev = 20
                        

        self.r = redis.Redis(host='localhost', port=6379, db=0)            
    
    def change_leverage(self):
        while True:
            if self.exchange_name == 'huobi_swap':
                try:
                    stats = self.exchange.send_post_request('/swap-api/v1/swap_switch_lever_rate', {'contract_code': self.symbol, 'lever_rate': self.lev}) 
                    break
                except Exception as e:
                    break

            
    def close_open_orders(self, close_stop=False):
        done = False
        
        while not done:
            try:
                if self.exchange_name == 'huobi_swap':
                    if close_stop == True:
                        self.exchange.send_post_request('/swap-api/v1/swap_trigger_cancelall', {'contract_code': self.symbol})

                    self.exchange.send_post_request('/swap-api/v1/swap_cancelall', {'contract_code': self.symbol})
                    orders = []

            except Exception as e:
                if "many requests" in str(e).lower():
                    print("Too many requests in {}".format(inspect.currentframe().f_code.co_name))
                    break

                print(e)
                pass

    def close_stop_order(self):
        self.close_open_orders(close_stop=True)
    
    def get_orderbook(self):
        orderbook = {}
        orderbook['best_ask'] = float(self.r.get('{}_best_ask'.format(self.exchange_name)).decode())
        orderbook['best_bid'] = float(self.r.get('{}_best_bid'.format(self.exchange_name)).decode())

        return orderbook

    def get_position(self):
        '''
        Returns position (LONG, SHORT, NONE), average entry price and current quantity
        '''

        while True:
            try:
                if self.exchange_name == 'huobi_swap':
                    pos = pd.DataFrame(self.exchange.send_post_request('/swap-api/v1/swap_position_info', {'contract_code': self.symbol})['data'])
                    if len(pos) > 0:
                        pos = pos[pos['contract_code'] == self.symbol_here].iloc[0]
                        return "LONG", float(pos['cost_open']), int(pos['available'])
                    else:
                        return 'NONE', 0, 0

            except Exception as e:
                if "many requests" in str(e).lower():
                    print("Too many requests in {}".format(inspect.currentframe().f_code.co_name))
                    break

                print(e)
                time.sleep(1)
                pass

    def set_position(self):
        while True:
            try:
                current_pos, avgEntryPrice, amount = self.get_position()

                if current_pos == 'NONE':
                    self.r.set('{}_position_since'.format(self.exchange_name), 0)

                try:
                    self.r.get('{}_position_since'.format(self.exchange_name)).decode()
                except:
                    print("Error getting position since. Setting to ten")
                    self.r.set('{}_position_since'.format(self.exchange_name), 10)
        
                self.r.set('{}_avgEntryPrice'.format(self.exchange_name), avgEntryPrice)
                self.r.set('{}_current_pos'.format(self.exchange_name), current_pos)
                self.r.set('{}_pos_size'.format(self.exchange_name), amount)

                balance = self.get_balance()
                self.r.set('{}_balance'.format(self.exchange_name), balance)
                break

            except Exception as e:
                if "many requests" in str(e).lower():
                    print("Too many requests in {}".format(inspect.currentframe().f_code.co_name))
                    break

                print(e)
                time.sleep(1)
                pass

    def get_stop(self):
        start_time = time.time()

        while True:
            try:
                if self.exchange_name == 'huobi_swap':
                    orders = self.exchange.send_post_request('/swap-api/v1/swap_trigger_openorders', {'contract_code': self.symbol})['data']['orders']

                if len(orders) > 0:
                    for order in orders:
                        if self.exchange_name == 'huobi_swap':
                            return [order['trigger_price']]
                    
                    return []
                else:
                    return []
            except Exception as e:
                if "many requests" in str(e).lower():
                    print("Too many requests in {}".format(inspect.currentframe().f_code.co_name))
                    break

                print(e)
                time.sleep(1)
                pass

    def add_stop_loss(self):
        while True:
            try:
                current_pos, avgEntryPrice, amount = self.get_position()
                close_at = int(avgEntryPrice * self.stop)


                if self.exchange_name == 'huobi_swap':
                    order = self.exchange.send_post_request('/swap-api/v1/swap_trigger_order', {'contract_code': self.symbol, 'trigger_type': 'le', 'trigger_price': close_at, 'order_price': close_at-1000, 'volume': amount, 'direction': 'sell', 'offset': 'close'})
                    return order
            except Exception as e:
                if "many requests" in str(e).lower():
                    print("Too many requests in {}".format(inspect.currentframe().f_code.co_name))
                    break
                
                print(str(e))
                pass

    def update_stop(self):
        current_pos = self.r.get('{}_current_pos'.format(self.exchange_name)).decode()

        if current_pos == "LONG":
            stop = self.get_stop()
            if len(stop) == 0:
                self.add_stop_loss()
            else:
                pos, entryPrice, amount = self.get_position()
                close_at = int(entryPrice * self.stop)

                ratio = float(stop[0]) / close_at
    
                if (ratio <= 1.01 and ratio >= 0.99):
                    pass
                else:
                    print("Removing stop at {} to add stop at {}".format(stop[0], close_at))
                    self.close_stop_order()
                    self.add_stop_loss()


    def get_balance(self):
        if self.exchange_name == 'huobi_swap':
            return float(self.exchange.send_post_request('/swap-api/v1/swap_account_position_info', {'contract_code': self.symbol})['data'][0]['margin_available'])

    def get_max_amount(self, order_type):
        '''
        Get the max buyable/sellable amount
        '''
        orderbook = self.get_orderbook()

        if order_type == 'buy':
            price = orderbook['best_ask'] - self.increment
            balance = self.get_balance()

            if self.exchange_name == 'huobi_swap':
                amount = int((balance * self.lev * price) // 100)
                return amount, round(price, 1)

        elif order_type == 'sell':
            price = orderbook['best_bid'] + self.increment
            current_pos, avgEntryPrice, amount = self.get_position()

            if self.exchange_name == 'huobi_swap':
                return int(amount), float(round(price,1))
            else:
                return float(amount), float(price)

    def limit_trade(self, order_type, amount, price):
        '''
        Performs limit trade detecting exchange for the given amount
        '''
        if amount > 0:
            print("Sending limit {} order for {} of size {} @ {} on {} in {}".format(order_type, self.symbol, amount, price, self.exchange_name, datetime.datetime.now()))

            if self.exchange_name == 'huobi_swap':
                
                if order_type == 'buy':
                    order = self.exchange.send_post_request('/swap-api/v1/swap_order', {'contract_code': self.symbol, 'price': price, 'volume': int(amount), 'direction': 'buy', 'offset': 'open', 'order_price_type': 'post_only', 'lever_rate': self.lev})
                elif order_type == 'sell':
                    order = self.exchange.send_post_request('/swap-api/v1/swap_order', {'contract_code': self.symbol, 'price': price, 'volume': int(amount), 'direction': 'sell', 'offset': 'close', 'order_price_type': 'post_only', 'lever_rate': self.lev})

                try:
                    order_id = order['data']['order_id']
                except:
                    order_id = order['data'][0]['order_id']

                order = self.exchange.send_post_request('/swap-api/v1/swap_order_info', {'contract_code': self.symbol, 'order_id': order_id})

                if order['data'][0]['status'] == 7:
                    return []

                return order
        else:
            print("Doing a zero trade")
            return []

    def send_limit_order(self, order_type):
        '''
        Detects amount and sends limit order for that amount
        '''
        while True:
            try:
                amount, price = self.get_max_amount(order_type)

                if amount == 0:
                    return [], 0

                order = self.limit_trade(order_type, amount, price)

                return order, price
            except Exception as e:
                print(e)
                pass

    
    def market_trade(self, order_type, amount):
        '''
        Performs market trade detecting exchange for the given amount
        '''

        if amount > 0:
            print("Sending market {} order for {} of size {} on {} in {}".format(order_type, self.symbol, amount, self.exchange_name, datetime.datetime.now()))

            if self.exchange_name == 'huobi_swap':
                
                if order_type == 'buy':
                    order = self.exchange.send_post_request('/swap-api/v1/swap_order', {'contract_code': self.symbol, 'volume': int(amount), 'direction': 'buy', 'offset': 'open', 'order_price_type': 'optimal_20', 'lever_rate': int(self.lev)})
                elif order_type == 'sell':
                    order = self.exchange.send_post_request('/swap-api/v1/swap_order', {'contract_code': self.symbol, 'volume': int(amount), 'direction': 'sell', 'offset': 'close', 'order_price_type': 'optimal_20', 'lever_rate': int(self.lev)})
                
                return order
        else:
            print("Doing a zero trade")
            return []

    def send_market_order(self, order_type):
        '''
        Detects amount and market buys/sells the amount
        '''
        while True:
            try:
                self.close_open_orders()
                amount, price = self.get_max_amount(order_type)
                order = self.market_trade(order_type, amount)     
                return order, price      
            except Exception as e:
                print(e)
                pass

    def fill_order(self, order_type, method='attempt_limit'):
        '''
        Parameters:
        ___________

        order_type (string):
        buy or sell

        method (string):
        What to of strategy to use for selling. Strategies:

        attempt_limit: Tries selling limit with best price for 2 mins. Sells at market price if not sold
        5sec_average: Divides into 24 parts and makes market order of that every 5 second
        now: Market buy instantly
        take_biggest: Takes the biggest. If not filled, waits 30 second and takes it again. If not filled by end, takes at market.

        '''

        print("Time at filling order is: {}".format(datetime.datetime.now()))
        # self.close_open_orders()

        while True:         
            
            curr_pos = self.r.get('{}_current_pos'.format(self.exchange_name)).decode()

            if curr_pos == "NONE" and order_type=='sell': #to fix issue caused by backtrader verification idk why tho.
                print("Had to manually prevent sell order")
                break
                
                
            if method == "attempt_limit":
                try:
                    order, limit_price = self.send_limit_order(order_type)

                    if len(order) == 0:
                        print("Wants to close a zero position lol")
                        self.set_position()
                        return

                    while True:

                        if self.exchange_name == 'huobi_swap':
                            try:
                                order_id = order['data']['order_id']
                            except:
                                order_id = order['data'][0]['order_id']
                            order = self.exchange.send_post_request('/swap-api/v1/swap_order_info', {'contract_code': self.symbol, 'order_id': order_id})
                            order_status = order['data'][0]['status']
                            filled_string = 6


                        if order_status != filled_string:
                            time.sleep(.5) 
                            orderbook = self.get_orderbook()
                            print("Best Bid is {} and Best Ask is {}".format(orderbook['best_ask'], orderbook['best_bid']))

                            if order_type == 'buy':
                                current_full_time = str(datetime.datetime.now().minute)
                                current_time_check = current_full_time[1:]

                                if ((current_full_time == '9' or current_time_check == '9') and (datetime.datetime.now().second > 50)) or ((current_full_time == '0' or current_time_check == '0')):
                                    print("Time at sending market order is: {}".format(datetime.datetime.now()))
                                    order = self.send_market_order(order_type)
                                    break

                                current_match = orderbook['best_bid']

                                if current_match >= (limit_price + self.increment):
                                    print("Current price is much better, closing to open new one")
                                    self.close_open_orders()
                                    order, limit_price = self.send_limit_order(order_type)

                            elif order_type == 'sell':
                                current_full_time = str(datetime.datetime.now().minute)
                                current_time_check = current_full_time[1:]

                                if ((current_full_time == '9' or current_time_check == '9') and (datetime.datetime.now().second > 50)) or ((current_full_time == '0' or current_time_check == '0')):
                                    print("Time at sending market order is: {}".format(datetime.datetime.now()))
                                    order = self.send_market_order(order_type)
                                    break

                                current_match = orderbook['best_ask']

                                if current_match <= (limit_price - self.increment):
                                    print("Current price is much better, closing to open new one")
                                    self.close_open_orders()
                                    order, limit_price = self.send_limit_order(order_type)


                        else:
                            print("Order has been filled. Exiting out of loop")
                            self.close_open_orders()
                            break

                    return
                except Exception as e:
                    print(e)
                    pass
            
            elif method == "now":
                amount, price = self.get_max_amount(order_type)
                order = self.market_trade(order_type, amount)
                break
