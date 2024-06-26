import os
import sys
from typing import List, Tuple, Optional
from analysis.statistical_methods import collect_metrics_for_pair
from analysis.visualisation import (
    spread_visualisation,
    zscored_spread,
    visualise_returns,
)
from analysis.errors import NoSuitablePairsError
from analysis.stock_data import StockData
from utils.formatting_and_logs import green_bold_print, blue_bold_print, red_bold_print
from utils.formatting_and_logs import CustomFormatter
import logging

from trading.alpaca_functions import Alpaca

# Configure logging with a custom formatter
logging.basicConfig(level=logging.INFO)
formatter = CustomFormatter("%(asctime)s - %(levelname)s - %(message)s")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.handlers = [handler]


def read_tickers_from_file(path: str) -> Optional[List[str]]:
    """
    Reads ticker symbols from a file and returns them as a list.
    Args:
    path (str): File path to read ticker symbols.
    Returns:
    Optional[List[str]]: List of ticker symbols, or None if file not found.
    """
    try:
        with open(path, "r") as file:
            return [
                ticker.strip().upper()
                for ticker in file.read().split(",")
                if len(ticker.strip()) > 1
            ]
    except FileNotFoundError:
        logging.error("File not found. Please try again.")
        return None


def process_stock_data(symbols_list: List[str]) -> Optional[Tuple[str, str]]:
    """
    Processes stock symbols to find the most suitable pair for analysis.
    Args:
    symbols_list (List[str]): List of stock ticker symbols.
    Returns:
    Optional[Tuple[str, str]]: Most suitable pair of stocks, or None if no suitable pair is found.
    """
    try:
        stock_data = StockData(asset_list=symbols_list, bypass_adf_test=False)
        red_bold_print("Most Suitable Pair: " + stock_data.most_suitable_pair)
        return stock_data.most_suitable_pair
    except NoSuitablePairsError:
        logging.warning(
            "No suitable pairs found. Option to bypass adf_test is available but not recommended (y/n): "
        )
        bypass_adf_test = input()
        if bypass_adf_test.lower() == "y":
            stock_data = StockData(asset_list=symbols_list, bypass_adf_test=True)
            red_bold_print(
                "Most Suitable Pair: {}, {}".format(
                    stock_data.most_suitable_pair[0], stock_data.most_suitable_pair[1]
                )
            )
            return stock_data.most_suitable_pair
        else:
            print("There are no suitable pairs and you wont bypass the adf test.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")


def run_analysis() -> None:
    """
    Initiates the stock analysis process by reading ticker symbols and processing them.
    """
    while True:
        try:
            blue_bold_print(
                "Ticker symbols list must be in a csv file.\n"
                "Please enter the absolute path to a csv file containing a list of ticker symbols, "
                "leaving this blank will use the default symbols.csv or enter b to go back:"
            )
            path = input()
            if path.lower() == "b":
                break
            if not path:
                root_dir = os.path.dirname(os.path.abspath(__file__))
                print(f"No path supplied looking in {root_dir} for symbols.csv")
                path = os.path.join(root_dir, "symbols.csv")

            symbols_list = read_tickers_from_file(path)
            logging.info("Tickers to analyse: " + str(symbols_list))
            most_suitable_pair = process_stock_data(symbols_list)

            if symbols_list and most_suitable_pair:
                strategy_info = collect_metrics_for_pair(
                    most_suitable_pair[0], most_suitable_pair[1]
                )
                print(strategy_info)
                hedge_ratio = strategy_info["hedge_ratio"].iloc[0]
                print("Hedge Ratio: " + str(hedge_ratio))
                blue_bold_print(
                    "Would you like to visualise/backtest this strategy? type(y/n) "
                )

                if input().lower() == "y":
                    backtest_strategy(most_suitable_pair)

                break

        except Exception as e:
            print(e)


def get_user_input_for_pairs_strategy() -> dict:
    blue_bold_print(
        "Please enter the pair you would like use in the format stock_1, stock_2:"
    )
    pair_input = input()
    pair = [pair.strip() for pair in pair_input.split(",")]
    logging.info(f"Tickers to execute strategy are: {pair[0]} and {pair[1]}")
    strategy_info = collect_metrics_for_pair(pair[0], pair[1])
    hedge_ratio = strategy_info["hedge_ratio"].iloc[0]
    logging.info("The hedge ratio for this pair is: " + str(hedge_ratio))
    leverage = float(input("Please enter your selected leverage:"))
    red_bold_print(
        "Enter your take profit and stop loss in the following format: \n 0.1, 0.05"
    )
    tp, sl = input().split(",")
    tp = float(tp.strip())
    sl = float(sl.strip())

    return {
        "tp": tp,
        "sl": sl,
        "leverage": leverage,
        "hedge_ratio": hedge_ratio,
        "pair": pair,
    }


def check_signal(pair: List):
    strategy_info = collect_metrics_for_pair(pair[0], pair[1])
    signal = strategy_info.tail(1)["signal"].item()
    match signal:
        case 1:
            signal_string = "Long"
        case -1:
            signal_string = "Short"
        case _:
            signal_string = "Neutral"

    red_bold_print(f"The signal is {signal_string} on this pair.")
    return signal


def create_pairs_strategy():
    try:
        alpaca = Alpaca()
        if alpaca.in_position:
            red_bold_print(
                "Please exit current positions before executing a new strategy."
            )

        else:

            strategy_info = get_user_input_for_pairs_strategy()
            tp = strategy_info["tp"]
            sl = strategy_info["sl"]
            hedge_ratio = strategy_info["hedge_ratio"]
            leverage = strategy_info["leverage"]
            pair = strategy_info["pair"]

            confirmed = (
                input(
                    "Type confirm to execute the strategy, type anything else to abort and return "
                    "to main menu "
                ).lower()
                == "confirm"
            )
            if confirmed:
                while True:
                    # Profit and loss monitoring
                    if alpaca.check_and_stop_loss(sl) or alpaca.check_and_take_profit(
                        tp
                    ):
                        "This strategy has exited due to take profit or stop loss."
                        break

                    enact_pairs_strategy(pair, hedge_ratio, leverage, alpaca)
                    # Displaying live profit and sleeping for 30 seconds
                    alpaca.live_profit_monitor(30)

    except Exception as e:
        print(e)


def enact_pairs_strategy(pair, hedge_ratio, leverage, alpaca):
    signal = check_signal(pair)

    if alpaca.in_position:
        logging.info("You are currently in a position so will not execute a new trade.")
        if signal == 0:
            logging.info("Analysis wants to exit positions.")
            for symbol in pair:
                alpaca.close_position_for_symbol(symbol)

    elif not alpaca.in_position:
        match signal:
            case 1:
                logging.info(
                    "Analysis has deemed an opportunity for a long hedge position"
                )
                alpaca.enter_hedge_position(
                    pair[0],
                    pair[1],
                    stock_1_side="buy",
                    hr=hedge_ratio,
                    leverage=leverage,
                )
            case -1:
                logging.info(
                    "Analysis has deemed an opportunity for a short hedge position"
                )
                alpaca.enter_hedge_position(
                    pair[0],
                    pair[1],
                    stock_1_side="sell",
                    hr=hedge_ratio,
                    leverage=leverage,
                )


def take_user_input_for_pair_and_clean() -> [str, str]:
    """
    Cleans the pair input for spaces and caps
    """
    while True:
        try:
            pair_input = input()
            pair = [pair.strip() for pair in pair_input.split(",")]
            if len(pair) == 2:
                print(f"You have selected {pair}")
                return pair
        except Exception as e:
            print(e)


def backtest_menu() -> str:
    """
    Shows backtest options and returns user choice.
    Returns:
    str: User's menu choice.
    """
    blue_bold_print("1: Visualise Spread")
    blue_bold_print("2: Visualise Z-Scored Spread")
    blue_bold_print("3: Visualise Returns")
    return (
        input("Please select an option or type 'b' to return to the main menu: ")
        .strip()
        .lower()
    )


def backtest_strategy(pair: List = None) -> None:
    """
    Backtest a trading strategy based on user choices and stock pairs.
    """
    if not pair:
        blue_bold_print(
            "Please enter the stock tickers to backtest in the format stock_1, stock_2:"
        )
        pair = take_user_input_for_pair_and_clean()

    strategy_info = collect_metrics_for_pair(pair[0], pair[1])

    while True:
        try:
            choice = backtest_menu()
            match choice:
                case "1":
                    spread_visualisation(strategy_info)
                case "2":
                    zscored_spread(strategy_info)
                case "3":
                    blue_bold_print("You have selected to visualise the returns.")
                    blue_bold_print(
                        "Specify a take profit and stop loss percentage in the format 0.05, 0.05:"
                    )
                    tp_sl = input()
                    tp, sl = tp_sl.split(",")
                    tp, sl = float(tp.strip()), float(sl.strip())
                    visualise_returns(strategy_info, tp, sl)
                case "b":
                    break
                case _:
                    raise ValueError
        except Exception as e:
            print(e)
