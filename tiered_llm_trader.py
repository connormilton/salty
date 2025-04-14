# tiered_llm_trader.py - Three-tier LLM-based forex trading system with memory and budget management

import os
import time
import json
import logging
import pandas as pd
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import openai
from trading_ig import IGService
from trading_ig.rest import ApiExceededException
from polygon import RESTClient

# Import resource manager
from llm_resource_manager import LLMResourceManager

# --- Setup ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ForexTrader")
os.makedirs("data", exist_ok=True)

# --- Configuration ---
FOREX_PAIRS = [
    # Core major pairs
    "CS.D.EURUSD.TODAY.IP",  # The benchmark forex pair
    "CS.D.USDJPY.TODAY.IP",   # Key for risk sentiment analysis
    "CS.D.GBPUSD.TODAY.IP",   # High volatility opportunities
    "CS.D.AUDUSD.TODAY.IP",   # Commodity currency insights
    "CS.D.USDCAD.TODAY.IP",   # Oil correlation potential
    
    # Cross pairs with unique characteristics
    "CS.D.GBPJPY.TODAY.IP",   # "The Dragon" - extreme volatility
    "CS.D.EURJPY.TODAY.IP",   # Complex correlations with other pairs
    "CS.D.AUDJPY.TODAY.IP",   # Risk barometer cross
    "CS.D.EURGBP.TODAY.IP",   # European economic divergence plays
    
    # Proxies for regional economies
    "CS.D.USDCHF.TODAY.IP",   # Safe haven flows
    "CS.D.NZDUSD.TODAY.IP",   # Agricultural commodity proxy
    "CS.D.AUDNZD.TODAY.IP",   # Regional economic divergence
    
    # Interesting correlations
    "CS.D.CADJPY.TODAY.IP",   # Oil/risk sentiment combination
    "CS.D.AUDCAD.TODAY.IP",   # Commodity currency correlations
    
    # One exotic for diversification
    "CS.D.USDSGD.TODAY.IP"    # Asian market proxy
]

# --- API Connections ---
def get_ig_service():
    """Connect to IG API."""
    try:
        ig = IGService(
            username=os.getenv("IG_USERNAME"),
            password=os.getenv("IG_PASSWORD"),
            api_key=os.getenv("IG_API_KEY"),
            acc_type=os.getenv("IG_ACC_TYPE", "DEMO")
        )
        ig.create_session()
        
        # Set account if specified
        target_account_id = os.getenv("IG_ACCOUNT_ID")
        if target_account_id:
            accounts = ig.fetch_accounts()
            current_account_id = accounts.iloc[0]['accountId'] if not accounts.empty else None
            
            try:
                # Only attempt to switch if current account is not already the target
                if current_account_id != target_account_id:
                    ig.switch_account(target_account_id, False)
                else:
                    logger.info(f"Account {target_account_id} already active, continuing without switching.")
            except Exception as switch_err:
                err_str = str(switch_err)
                # If the account is already active, IG might return this error
                if "error.switch.accountId-must-be-different" in err_str:
                    logger.info("Account already active, continuing without switching.")
                else:
                    # For other errors, re-raise
                    raise switch_err
        
        logger.info("IG API connected successfully")
        return ig
    except Exception as e:
        logger.error(f"IG connection error: {e}")
        return None

def get_polygon_client():
    """Get Polygon API client."""
    return RESTClient(os.getenv("POLYGON_API_KEY"))

# --- Data Collection ---
def collect_market_data(polygon, epic, timeframes=None):
    """Collect market data for multiple timeframes."""
    if timeframes is None:
        timeframes = {
            "m1": {"timeframe": "1:minute", "lookback_days": 0.2},
            "m5": {"timeframe": "5:minute", "lookback_days": 0.5},
            "m15": {"timeframe": "15:minute", "lookback_days": 1},
            "h1": {"timeframe": "hour", "lookback_days": 2},
            "h4": {"timeframe": "4:hour", "lookback_days": 5}
        }
    
    results = {}
    
    # Convert IG epic to Polygon ticker
    ticker_map = {
        "CS.D.EURUSD.TODAY.IP": "C:EURUSD",
        "CS.D.USDJPY.TODAY.IP": "C:USDJPY",
        "CS.D.GBPUSD.TODAY.IP": "C:GBPUSD",
        "CS.D.AUDUSD.TODAY.IP": "C:AUDUSD",
        "CS.D.USDCAD.TODAY.IP": "C:USDCAD",
        "CS.D.USDCHF.TODAY.IP": "C:USDCHF",
        "CS.D.NZDUSD.TODAY.IP": "C:NZDUSD",
        "CS.D.EURJPY.TODAY.IP": "C:EURJPY",
        "CS.D.EURGBP.TODAY.IP": "C:EURGBP",
        "CS.D.GBPJPY.TODAY.IP": "C:GBPJPY",
        "CS.D.AUDJPY.TODAY.IP": "C:AUDJPY",
        "CS.D.EURCHF.TODAY.IP": "C:EURCHF",
        "CS.D.AUDNZD.TODAY.IP": "C:AUDNZD",
        "CS.D.CADJPY.TODAY.IP": "C:CADJPY",
        "CS.D.AUDCAD.TODAY.IP": "C:AUDCAD",
        "CS.D.USDSGD.TODAY.IP": "C:USDSGD"
    }
    
    ticker = ticker_map.get(epic)
    if not ticker:
        logger.warning(f"No ticker mapping for {epic}")
        return results
    
    for key, config in timeframes.items():
        try:
            timeframe = config["timeframe"]
            lookback_days = config["lookback_days"]
            
            # Parse timeframe
            if ":" in timeframe:
                parts = timeframe.split(":")
                multiplier = int(parts[0])
                timespan = parts[1]
            else:
                multiplier = 1
                timespan = timeframe
            
            # Get data from Polygon
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=lookback_days)
            
            aggs = polygon.get_aggs(
                ticker=ticker,
                multiplier=multiplier,
                timespan=timespan,
                from_=start.strftime("%Y-%m-%d"),
                to=end.strftime("%Y-%m-%d"),
                limit=500  # Reduced limit to save on data size
            )
            
            if not aggs:
                logger.debug(f"No data for {ticker} on {timeframe}")
                continue
            
            # Convert to standardized format
            data = [{
                "timestamp": datetime.fromtimestamp(a.timestamp/1000, tz=timezone.utc).isoformat(),
                "open": a.open,
                "high": a.high,
                "low": a.low,
                "close": a.close,
                "volume": a.volume
            } for a in aggs]
            
            results[key] = data
            logger.debug(f"Collected {len(data)} {key} data points for {epic}")
            
        except Exception as e:
            logger.error(f"Error getting {key} data for {epic}: {e}")
    
    return results

def get_account_data(ig):
    """Get account information."""
    try:
        accounts = ig.fetch_accounts()
        if os.getenv("IG_ACCOUNT_ID"):
            account = accounts[accounts['accountId'] == os.getenv("IG_ACCOUNT_ID")]
        else:
            account = accounts.iloc[[0]]
        
        return account.iloc[0].to_dict()
    except Exception as e:
        logger.error(f"Error getting account: {e}")
        return {}

def get_positions(ig):
    """Get open positions."""
    try:
        return ig.fetch_open_positions()
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return pd.DataFrame()

def get_snapshot(ig, epic):
    """Get current market price snapshot."""
    try:
        response = ig.fetch_market_by_epic(epic)
        if response and 'snapshot' in response:
            snapshot = response['snapshot']
            
            # Get raw values first
            raw_bid = snapshot.get('bid')
            raw_offer = snapshot.get('offer')
            
            # Determine the divisor based on the currency pair
            divisor = 100.0 if "JPY" in epic else 10000.0
            
            # Convert points to decimal format
            bid = raw_bid / divisor if raw_bid is not None else None
            offer = raw_offer / divisor if raw_offer is not None else None
            
            return {
                "raw_bid": raw_bid,
                "raw_offer": raw_offer,
                "bid": bid,
                "offer": offer,
                "epic": epic,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        return None
    except Exception as e:
        logger.error(f"Error getting snapshot for {epic}: {e}")
        return None

def get_recent_trades(limit=10):
    """Get recent trade history."""
    try:
        trade_log_file = "data/trade_log.jsonl"
        
        if not os.path.exists(trade_log_file):
            return []
        
        trades = []
        with open(trade_log_file, "r") as f:
            for line in f:
                try:
                    trade = json.loads(line.strip())
                    trades.append(trade)
                except:
                    continue
        
        # Sort by timestamp (newest first) and limit
        trades.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return trades[:limit]
        
    except Exception as e:
        logger.error(f"Error getting recent trades: {e}")
        return []

# --- Memory System ---
class TradingMemory:
    """Maintains persistent memory between LLM calls for continuous learning."""
    
    def __init__(self, storage_path="data"):
        """Initialize the trading memory system."""
        self.storage_path = storage_path
        self.system_memory_path = f"{storage_path}/system_memory.json"
        self.pair_memory_path = f"{storage_path}/pair_memory.json"
        self.market_context_path = f"{storage_path}/market_context.json"
        
        # Initialize all memory stores
        self._init_memory()
    
    def _init_memory(self):
        """Initialize all memory systems."""
        # Create directory if it doesn't exist
        os.makedirs(self.storage_path, exist_ok=True)
        
        # Load or create system memory
        if os.path.exists(self.system_memory_path):
            with open(self.system_memory_path, "r") as f:
                self.system_memory = json.load(f)
        else:
            self.system_memory = {
                "created": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "last_n_trades": [],
                "performance_by_pair": {},
                "performance_by_pattern": {},
                "risk_management": {
                    "base_risk": 1.0,  # % of account to risk per trade
                    "current_risk": 1.0,
                    "risk_multiplier": 1.0  # Adjusts dynamically based on performance
                }
            }
            self._save_system_memory()
        
        # Load or create pair memory
        if os.path.exists(self.pair_memory_path):
            with open(self.pair_memory_path, "r") as f:
                self.pair_memory = json.load(f)
        else:
            self.pair_memory = {
                "created": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "pairs": {}
            }
            self._save_pair_memory()
        
        # Load or create market context
        if os.path.exists(self.market_context_path):
            with open(self.market_context_path, "r") as f:
                self.market_context = json.load(f)
        else:
            self.market_context = {
                "created": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "overall_condition": "unknown",
                "overall_bias": "neutral",
                "key_levels": {},
                "recent_developments": [],
                "correlations": {}
            }
            self._save_market_context()
    
    def _save_system_memory(self):
        """Save system memory to disk."""
        with open(self.system_memory_path, "w") as f:
            json.dump(self.system_memory, f, indent=2)
    
    def _save_pair_memory(self):
        """Save pair memory to disk."""
        with open(self.pair_memory_path, "w") as f:
            json.dump(self.pair_memory, f, indent=2)
    
    def _save_market_context(self):
        """Save market context to disk."""
        with open(self.market_context_path, "w") as f:
            json.dump(self.market_context, f, indent=2)
    
    def update_system_memory(self, trade_result=None):
        """Update system memory with a new trade result."""
        if trade_result:
            # Update trade statistics
            self.system_memory["trade_count"] += 1
            
            # Determine if win or loss
            outcome = trade_result.get("outcome", "").upper()
            if "WIN" in outcome or "PROFIT" in outcome:
                self.system_memory["win_count"] += 1
            elif "LOSS" in outcome or "STOPPED" in outcome:
                self.system_memory["loss_count"] += 1
            
            # Update last_n_trades (keep last 20)
            self.system_memory["last_n_trades"].append(trade_result)
            if len(self.system_memory["last_n_trades"]) > 20:
                self.system_memory["last_n_trades"] = self.system_memory["last_n_trades"][-20:]
            
            # Update pair performance
            pair = trade_result.get("epic")
            if pair:
                if pair not in self.system_memory["performance_by_pair"]:
                    self.system_memory["performance_by_pair"][pair] = {
                        "trades": 0, "wins": 0, "losses": 0
                    }
                
                self.system_memory["performance_by_pair"][pair]["trades"] += 1
                if "WIN" in outcome or "PROFIT" in outcome:
                    self.system_memory["performance_by_pair"][pair]["wins"] += 1
                elif "LOSS" in outcome or "STOPPED" in outcome:
                    self.system_memory["performance_by_pair"][pair]["losses"] += 1
            
            # Update pattern performance if available
            pattern = trade_result.get("pattern")
            if pattern:
                if pattern not in self.system_memory["performance_by_pattern"]:
                    self.system_memory["performance_by_pattern"][pattern] = {
                        "trades": 0, "wins": 0, "losses": 0
                    }
                
                self.system_memory["performance_by_pattern"][pattern]["trades"] += 1
                if "WIN" in outcome or "PROFIT" in outcome:
                    self.system_memory["performance_by_pattern"][pattern]["wins"] += 1
                elif "LOSS" in outcome or "STOPPED" in outcome:
                    self.system_memory["performance_by_pattern"][pattern]["losses"] += 1
        
        # Update last updated timestamp
        self.system_memory["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Save to disk
        self._save_system_memory()
    
    def update_pair_memory(self, pair, analysis_result):
        """Update memory for a specific currency pair."""
        if pair not in self.pair_memory["pairs"]:
            self.pair_memory["pairs"][pair] = {
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "key_levels": [],
                "patterns": [],
                "analysis_history": []
            }
        
        # Update analysis history (keep last 10)
        self.pair_memory["pairs"][pair]["analysis_history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis": analysis_result
        })
        
        if len(self.pair_memory["pairs"][pair]["analysis_history"]) > 10:
            self.pair_memory["pairs"][pair]["analysis_history"] = self.pair_memory["pairs"][pair]["analysis_history"][-10:]
        
        # Update key levels if provided
        if "key_levels" in analysis_result:
            self.pair_memory["pairs"][pair]["key_levels"] = analysis_result["key_levels"]
        
        # Update patterns if provided
        if "patterns" in analysis_result:
            for pattern in analysis_result["patterns"]:
                if pattern not in self.pair_memory["pairs"][pair]["patterns"]:
                    self.pair_memory["pairs"][pair]["patterns"].append(pattern)
        
        # Update last updated timestamp
        self.pair_memory["pairs"][pair]["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.pair_memory["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Save to disk
        self._save_pair_memory()
    
    def update_market_context(self, context_update):
        """Update overall market context."""
        # Update fields that are provided
        if "overall_condition" in context_update:
            self.market_context["overall_condition"] = context_update["overall_condition"]
        
        if "overall_bias" in context_update:
            self.market_context["overall_bias"] = context_update["overall_bias"]
        
        if "key_levels" in context_update:
            self.market_context["key_levels"].update(context_update["key_levels"])
        
        # Add new developments
        if "developments" in context_update:
            for dev in context_update["developments"]:
                self.market_context["recent_developments"].insert(0, {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "development": dev
                })
            
            # Keep only most recent 20 developments
            self.market_context["recent_developments"] = self.market_context["recent_developments"][:20]
        
        # Update correlations if provided
        if "correlations" in context_update:
            self.market_context["correlations"].update(context_update["correlations"])
        
        # Update last updated timestamp
        self.market_context["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Save to disk
        self._save_market_context()
    
    def get_system_memory_summary(self):
        """Get a summary of system memory for LLM prompt."""
        if not self.system_memory:
            return "No system memory available."
        
        win_rate = 0
        if self.system_memory["trade_count"] > 0:
            win_rate = (self.system_memory["win_count"] / self.system_memory["trade_count"]) * 100
        
        return f"""
## System Memory Summary
- Total Trades: {self.system_memory["trade_count"]}
- Win Rate: {win_rate:.1f}%
- Current Risk Multiplier: {self.system_memory["risk_management"]["risk_multiplier"]:.2f}

### Top Performing Pairs:
{self._format_top_performers("pair", 3)}

### Top Performing Patterns:
{self._format_top_performers("pattern", 3)}

### Recent Trade Outcomes:
{self._format_recent_trades(5)}
"""
    
    def _format_top_performers(self, category_type, limit=3):
        """Format top performing pairs or patterns."""
        if category_type == "pair":
            items = self.system_memory["performance_by_pair"].items()
        else:  # pattern
            items = self.system_memory["performance_by_pattern"].items()
        
        # Filter to items with at least 3 trades
        filtered_items = [(k, v) for k, v in items if v["trades"] >= 3]
        
        if not filtered_items:
            return "Not enough data"
        
        # Calculate win rates
        with_win_rates = [(k, v, (v["wins"] / v["trades"]) * 100 if v["trades"] > 0 else 0) 
                         for k, v in filtered_items]
        
        # Sort by win rate descending
        sorted_items = sorted(with_win_rates, key=lambda x: x[2], reverse=True)
        
        # Format output
        result = ""
        for i, (name, stats, win_rate) in enumerate(sorted_items[:limit]):
            result += f"- {name}: {win_rate:.1f}% win rate ({stats['wins']}/{stats['trades']})\n"
        
        return result
    
    def _format_recent_trades(self, limit=5):
        """Format recent trade results."""
        trades = self.system_memory["last_n_trades"][-limit:]
        if not trades:
            return "No recent trades"
        
        result = ""
        for trade in reversed(trades):  # Newest first
            outcome = trade.get("outcome", "UNKNOWN")
            epic = trade.get("epic", "UNKNOWN")
            direction = trade.get("direction", "UNKNOWN")
            
            # Format timestamp to just show date and time
            timestamp = "Unknown time"
            if "timestamp" in trade:
                try:
                    dt = datetime.fromisoformat(trade["timestamp"])
                    timestamp = dt.strftime("%m-%d %H:%M")
                except:
                    pass
            
            result += f"- {timestamp}: {direction} {epic} - {outcome}\n"
        
        return result
    
    def get_pair_memory(self, pair):
        """Get memory for a specific currency pair."""
        if pair not in self.pair_memory["pairs"]:
            return None
        
        return self.pair_memory["pairs"][pair]
    
    def get_market_context_summary(self):
        """Get a summary of market context for LLM prompt."""
        if not self.market_context:
            return "No market context available."
        
        # Recent developments
        recent_devs = ""
        for dev in self.market_context["recent_developments"][:5]:
            # Format timestamp to just show date and time
            timestamp = "Unknown time"
            if "timestamp" in dev:
                try:
                    dt = datetime.fromisoformat(dev["timestamp"])
                    timestamp = dt.strftime("%m-%d %H:%M")
                except:
                    pass
            
            recent_devs += f"- {timestamp}: {dev['development']}\n"
        
        if not recent_devs:
            recent_devs = "No recent developments recorded.\n"
        
        # Key levels for major pairs
        key_levels = ""
        major_pairs = ["CS.D.EURUSD.TODAY.IP", "CS.D.USDJPY.TODAY.IP", "CS.D.GBPUSD.TODAY.IP"]
        for pair in major_pairs:
            if pair in self.market_context["key_levels"]:
                key_levels += f"- {pair}: {self.market_context['key_levels'][pair]}\n"
        
        if not key_levels:
            key_levels = "No key levels recorded.\n"
        
        return f"""
## Market Context Summary
- Overall Condition: {self.market_context["overall_condition"]}
- Overall Bias: {self.market_context["overall_bias"]}

### Recent Market Developments:
{recent_devs}

### Key Levels:
{key_levels}
"""
    
    def adjust_risk_based_on_performance(self):
        """Dynamically adjust risk multiplier based on recent performance."""
        # Need at least 5 trades to adjust risk
        if self.system_memory["trade_count"] < 5:
            return
        
        # Get most recent 10 trades (or fewer if not available)
        recent_trades = self.system_memory["last_n_trades"][-10:]
        
        if not recent_trades:
            return
        
        # Count wins and losses
        wins = sum(1 for trade in recent_trades if "WIN" in trade.get("outcome", "").upper() or "PROFIT" in trade.get("outcome", "").upper())
        losses = sum(1 for trade in recent_trades if "LOSS" in trade.get("outcome", "").upper() or "STOPPED" in trade.get("outcome", "").upper())
        
        # Calculate win rate for recent trades
        recent_win_rate = wins / len(recent_trades) if recent_trades else 0
        
        # Adjust risk multiplier based on recent performance
        if recent_win_rate >= 0.7:  # 70%+ win rate
            # Increase risk, but cap at 1.5x base risk
            new_multiplier = min(self.system_memory["risk_management"]["risk_multiplier"] * 1.1, 1.5)
        elif recent_win_rate <= 0.3:  # 30% or worse win rate
            # Decrease risk to 75% of current
            new_multiplier = max(self.system_memory["risk_management"]["risk_multiplier"] * 0.75, 0.5)
        else:
            # Keep same risk level
            new_multiplier = self.system_memory["risk_management"]["risk_multiplier"]
        
        # Update risk multiplier
        self.system_memory["risk_management"]["risk_multiplier"] = new_multiplier
        self.system_memory["risk_management"]["current_risk"] = self.system_memory["risk_management"]["base_risk"] * new_multiplier
        
        # Save to disk
        self._save_system_memory()
        
        logger.info(f"Risk multiplier adjusted to {new_multiplier:.2f} based on recent win rate of {recent_win_rate:.1%}")

# --- Three-Tier LLM System ---
class ThreeTierLLMSystem:
    """Implements the three-tier LLM trading system with market scanner, analyzer, and decision maker."""
    
    def __init__(self, resource_manager, memory_system):
        """Initialize the three-tier LLM system."""
        self.resource_manager = resource_manager
        self.memory = memory_system
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        openai.api_key = self.openai_api_key
    
    def run_market_scanner(self, context):
        """Run Tier 1: Market Scanner using GPT-3.5 to quickly identify opportunities."""
        try:
            # Check if we have budget to run this tier
            if not self.resource_manager.can_run_tier("scanner"):
                logger.warning("Insufficient budget to run market scanner")
                return {"opportunities": [], "market_assessment": {"overall_condition": "unknown", "overall_bias": "neutral"}}
            
            # Build the prompt
            prompt = self._build_scanner_prompt(context)
            
            # Estimate tokens
            tokens_in = len(prompt) / 4  # Rough estimate
            
            # Call LLM API with GPT-3.5
            logger.info(f"Running market scanner (~{int(tokens_in)} tokens)")
            
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a forex market scanner that identifies high-probability trading opportunities across multiple currency pairs."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            # Get token usage
            usage = response.usage
            tokens_in = usage.prompt_tokens
            tokens_out = usage.completion_tokens
            
            # Update budget usage
            self.resource_manager.update_usage("scanner", tokens_in, tokens_out)
            
            # Parse response
            response_content = response.choices[0].message.content
            result = json.loads(response_content)
            
            # Log the result
            with open("data/scanner_results.jsonl", "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "result": result
                }) + "\n")
            
            # Update market context
            self.memory.update_market_context({
                "overall_condition": result.get("market_assessment", {}).get("overall_condition", "unknown"),
                "overall_bias": result.get("market_assessment", {}).get("overall_bias", "neutral"),
                "developments": [f"Scanner: {result.get('market_assessment', {}).get('summary', 'No summary')}"]
            })
            
            logger.info(f"Market scanner found {len(result.get('opportunities', []))} potential opportunities")
            
            return result
            
        except Exception as e:
            logger.error(f"Market scanner error: {e}")
            return {"opportunities": [], "market_assessment": {"overall_condition": "unknown", "overall_bias": "neutral"}}
    
    def run_analysis_engine(self, context, opportunities):
        """Run Tier 2: Analysis Engine using GPT-4 to deeply analyze selected opportunities."""
        try:
            # Check if we have budget to run this tier
            if not self.resource_manager.can_run_tier("analyzer"):
                logger.warning("Insufficient budget to run analysis engine")
                return {"analysis_results": []}
            
            # Determine how many pairs to analyze
            total_pairs = len(FOREX_PAIRS)
            pairs_to_analyze = self.resource_manager.get_pairs_to_analyze(opportunities, total_pairs)
            
            # Take top opportunities based on conviction
            sorted_opps = sorted(opportunities, key=lambda x: x.get("conviction", 0), reverse=True)
            selected_opportunities = sorted_opps[:pairs_to_analyze]
            
            # Get epics to analyze
            epics_to_analyze = [opp.get("epic") for opp in selected_opportunities]
            
            if not epics_to_analyze:
                logger.info("No opportunities to analyze")
                return {"analysis_results": []}
            
            # Build the prompt
            prompt = self._build_analyzer_prompt(context, selected_opportunities)
            
            # Estimate tokens
            tokens_in = len(prompt) / 4  # Rough estimate
            
            # Call LLM API with GPT-4
            logger.info(f"Running analysis engine on {len(epics_to_analyze)} pairs (~{int(tokens_in)} tokens)")
            
            response = openai.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a forex analysis engine that performs detailed technical analysis on selected currency pairs."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            # Get token usage
            usage = response.usage
            tokens_in = usage.prompt_tokens
            tokens_out = usage.completion_tokens
            
            # Update budget usage
            self.resource_manager.update_usage("analyzer", tokens_in, tokens_out)
            
            # Parse response
            response_content = response.choices[0].message.content
            result = json.loads(response_content)
            
            # Log the result
            with open("data/analyzer_results.jsonl", "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "result": result
                }) + "\n")
            
            # Update pair memory for analyzed pairs
            for analysis in result.get("analysis_results", []):
                pair = analysis.get("epic")
                if pair:
                    self.memory.update_pair_memory(pair, analysis)
            
            # Update market context with key levels
            key_levels = {}
            for analysis in result.get("analysis_results", []):
                pair = analysis.get("epic")
                if pair and "key_levels" in analysis:
                    key_levels[pair] = analysis["key_levels"]
            
            if key_levels:
                self.memory.update_market_context({"key_levels": key_levels})
            
            logger.info(f"Analysis engine completed analysis of {len(result.get('analysis_results', []))} pairs")
            
            return result
            
        except Exception as e:
            logger.error(f"Analysis engine error: {e}")
            return {"analysis_results": []}
    
    def run_decision_maker(self, context, analysis_results):
        """Run Tier 3: Decision Maker using GPT-4 to make final trading decisions."""
        try:
            # Check if we have budget to run this tier
            if not self.resource_manager.can_run_tier("decision"):
                logger.warning("Insufficient budget to run decision maker")
                return {"trade_actions": [], "position_actions": [], "analysis": {}}
            
            # Skip if no analysis results
            if not analysis_results:
                logger.info("No analysis results to make decisions on")
                return {"trade_actions": [], "position_actions": [], "analysis": {}}
            
            # Build the prompt
            prompt = self._build_decision_prompt(context, analysis_results)
            
            # Estimate tokens
            tokens_in = len(prompt) / 4  # Rough estimate
            
            # Call LLM API with GPT-4
            logger.info(f"Running decision maker (~{int(tokens_in)} tokens)")
            
            response = openai.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a forex trading decision maker that determines precise trade entries, exits, and position management."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            # Get token usage
            usage = response.usage
            tokens_in = usage.prompt_tokens
            tokens_out = usage.completion_tokens
            
            # Update budget usage
            self.resource_manager.update_usage("decision", tokens_in, tokens_out)
            
            # Parse response
            response_content = response.choices[0].message.content
            result = json.loads(response_content)
            
            # Log the result
            with open("data/decision_results.jsonl", "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "result": result
                }) + "\n")
            
            # Update market context with any new developments
            if "market_commentary" in result.get("analysis", {}):
                self.memory.update_market_context({
                    "developments": [f"Decision: {result['analysis']['market_commentary']}"]
                })
            
            logger.info(f"Decision maker generated {len(result.get('trade_actions', []))} trades and {len(result.get('position_actions', []))} position actions")
            
            return result
            
        except Exception as e:
            logger.error(f"Decision maker error: {e}")
            return {"trade_actions": [], "position_actions": [], "analysis": {}}
    
    def _build_scanner_prompt(self, context):
        """Build the prompt for the market scanner tier."""
        # Get basic account info for context
        account_info = f"""
## Account Information
Account Balance: {context.get('account', {}).get('balance')}
Available Funds: {context.get('account', {}).get('available')}
"""

        # Build a summarized market data section with current prices
        market_data_summary = ""
        for epic, data in context.get('market_data', {}).items():
            # Get current price
            current_price = data.get('current_price', {})
            
            # Get latest price info from timeframes
            price_data = data.get('price_data', {})
            h1_data = price_data.get('h1', [])
            last_h1 = h1_data[-1] if h1_data and len(h1_data) > 0 else {}
            
            # Include just current price and last hourly close to keep prompt small
            market_data_summary += f"""
{epic}:
- Bid/Ask: {current_price.get('bid')}/{current_price.get('offer')}
- Last H1: C={last_h1.get('close', 'N/A')}
"""

        # Check if we have open positions to include
        positions_info = "No open positions"
        if not context.get('positions').empty:
            positions_info = context.get('positions').to_string()
        
        # Get market context from memory
        market_context = self.memory.get_market_context_summary()
        
        return f"""
# Forex Market Scanner

## Task
Quickly analyze all currency pairs to identify the most promising trading opportunities.
Focus on finding clear technical patterns, strong trends, or high-probability setups.

{account_info}

## Open Positions
{positions_info}

{market_context}

## Current Market Prices
{market_data_summary}

## What to Look For
- Clear trend directions
- Recent breakouts or reversals
- Key support/resistance levels
- Unusual volatility
- Correlation opportunities

## Response Format
Respond in this JSON format:
```
{{
  "market_assessment": {{
    "overall_condition": "trending/ranging/volatile/uncertain",
    "overall_bias": "bullish/bearish/neutral",
    "summary": "Brief 1-2 sentence market summary"
  }},
  "opportunities": [
    {{
      "epic": "CS.D.EURUSD.TODAY.IP",
      "pattern": "breakout/reversal/trend continuation/etc",
      "direction": "BUY or SELL",
      "conviction": 1-10,
      "timeframe": "short-term/medium-term/long-term",
      "reasoning": "Brief explanation of why this is a good opportunity"
    }}
  ],
  "watchlist": [
    {{
      "epic": "CS.D.GBPJPY.TODAY.IP",
      "note": "Approaching key resistance, might become opportunity soon"
    }}
  ]
}}
```
"""
    
    def _build_analyzer_prompt(self, context, opportunities):
        """Build the prompt for the analysis engine tier."""
        # Get basic account and position info
        account_info = f"""
## Account Information
Account Balance: {context.get('account', {}).get('balance')}
Available Funds: {context.get('account', {}).get('available')}
"""

        # Check if we have open positions to include
        positions_info = "No open positions"
        if not context.get('positions').empty:
            positions_info = context.get('positions').to_string()
        
        # Get market context from memory
        market_context = self.memory.get_market_context_summary()
        
        # Build opportunity section
        opportunities_section = "## Selected Opportunities\n"
        for opp in opportunities:
            epic = opp.get("epic")
            pattern = opp.get("pattern")
            direction = opp.get("direction")
            conviction = opp.get("conviction")
            reasoning = opp.get("reasoning", "No reasoning provided")
            
            opportunities_section += f"""
### {epic}
- Pattern: {pattern}
- Direction: {direction}
- Conviction: {conviction}/10
- Initial Assessment: {reasoning}
"""
            
            # Add pair memory if available
            pair_memory = self.memory.get_pair_memory(epic)
            if pair_memory:
                opportunities_section += f"""
- Key Levels (from memory): {pair_memory.get('key_levels', [])}
- Historical Patterns: {pair_memory.get('patterns', [])}
"""
        
        # Build detailed market data for selected pairs
        market_data_detail = "## Detailed Market Data\n"
        
        for opp in opportunities:
            epic = opp.get("epic")
            data = context.get('market_data', {}).get(epic, {})
            
            if not data:
                continue
                
            # Get current price
            current_price = data.get('current_price', {})
            
            # Get price data from multiple timeframes
            price_data = data.get('price_data', {})
            
            # Extract M15 data from price_data if available
            m15_data = price_data.get('m15', [])
            
            # H1 data - last 5 candles
            h1_data = price_data.get('h1', [])
            h1_candles = h1_data[-5:] if len(h1_data) >= 5 else h1_data
            
            # H4 data - last 3 candles
            h4_data = price_data.get('h4', [])
            h4_candles = h4_data[-3:] if len(h4_data) >= 3 else h4_data
            
            # Add detailed information for this pair
            market_data_detail += f"""
### {epic} Market Data
Current Bid/Ask: {current_price.get('bid')}/{current_price.get('offer')}

#### M15 Chart (recent candles):
"""
            
            # Add M15 candles
            for i, candle in enumerate(reversed(m15_data)):  # newest first
                dt = datetime.fromisoformat(candle.get('timestamp', ''))
                time_str = dt.strftime("%H:%M")
                market_data_detail += f"- {time_str}: O={candle.get('open'):.5f} H={candle.get('high'):.5f} L={candle.get('low'):.5f} C={candle.get('close'):.5f}\n"
            
            # Add H1 candles
            market_data_detail += f"\n#### H1 Chart (recent candles):\n"
            for i, candle in enumerate(reversed(h1_candles)):  # newest first
                dt = datetime.fromisoformat(candle.get('timestamp', ''))
                time_str = dt.strftime("%H:%M")
                market_data_detail += f"- {time_str}: O={candle.get('open'):.5f} H={candle.get('high'):.5f} L={candle.get('low'):.5f} C={candle.get('close'):.5f}\n"
            
            # Add H4 candles
            market_data_detail += f"\n#### H4 Chart (recent candles):\n"
            for i, candle in enumerate(reversed(h4_candles)):  # newest first
                dt = datetime.fromisoformat(candle.get('timestamp', ''))
                time_str = dt.strftime("%m-%d %H:%M")
                market_data_detail += f"- {time_str}: O={candle.get('open'):.5f} H={candle.get('high'):.5f} L={candle.get('low'):.5f} C={candle.get('close'):.5f}\n"
        
        return f"""
# Forex Analysis Engine

## Task
Perform detailed technical analysis on the selected high-opportunity currency pairs.
Identify precise entry points, stop levels, and take profits with a focus on risk management.

{account_info}

## Open Positions
{positions_info}

{market_context}

{opportunities_section}

{market_data_detail}

## Response Format
Respond in this JSON format:
```
{{
  "analysis_results": [
    {{
      "epic": "CS.D.EURUSD.TODAY.IP",
      "direction": "BUY/SELL",
      "pattern": "Pattern identified",
      "timeframe": "short-term/medium-term/long-term",
      "confidence": 1-10,
      "risk_reward": 1.5,
      "key_levels": {{
        "support": [1.2345, 1.2300],
        "resistance": [1.2400, 1.2450]
      }},
      "entry_zone": {{
        "ideal": 1.2350,
        "range_low": 1.2340,
        "range_high": 1.2360
      }},
      "stop_loss": {{
        "price": 1.2300,
        "pips": 50
      }},
      "take_profit": {{
        "price": 1.2450,
        "pips": 100
      }},
      "trading_plan": "Detailed explanation of the setup and trading plan",
      "technical_indicators": "Summary of key technical indicators"
    }}
  ],
  "market_insights": "Overall insights from detailed analysis of these pairs"
}}
```
"""
    
    def _build_decision_prompt(self, context, analysis_results):
        """Build the prompt for the decision maker tier."""
        # Get basic account and position info
        account_info = f"""
## Account Information
Account Balance: {context.get('account', {}).get('balance')}
Available Funds: {context.get('account', {}).get('available')}
"""

        # Check if we have open positions to include
        positions_info = "No open positions"
        if not context.get('positions').empty:
            positions_info = context.get('positions').to_string()
        
        # Get system memory summary
        system_memory = self.memory.get_system_memory_summary()
        
        # Get market context from memory
        market_context = self.memory.get_market_context_summary()
        
        # Get current risk settings
        current_risk = self.memory.system_memory["risk_management"]["current_risk"]
        
        # Build analysis results section
        analysis_section = "## Analysis Results\n"
        for result in analysis_results.get("analysis_results", []):
            epic = result.get("epic")
            direction = result.get("direction")
            confidence = result.get("confidence")
            risk_reward = result.get("risk_reward")
            entry = result.get("entry_zone", {}).get("ideal", "N/A")
            stop = result.get("stop_loss", {}).get("price", "N/A")
            target = result.get("take_profit", {}).get("price", "N/A")
            
            analysis_section += f"""
### {epic}
- Direction: {direction}
- Confidence: {confidence}/10
- Risk-Reward: {risk_reward}
- Entry: {entry}
- Stop: {stop}
- Target: {target}
- Trading Plan: {result.get("trading_plan", "No trading plan provided")}
"""
        
        # Get recent trades for context
        recent_trades = get_recent_trades(5)
        recent_trades_section = "## Recent Trades\n"
        
        if recent_trades:
            for trade in recent_trades:
                epic = trade.get("epic", "Unknown")
                direction = trade.get("direction", "Unknown")
                outcome = trade.get("outcome", "Unknown")
                timestamp = trade.get("timestamp", "Unknown time")
                
                recent_trades_section += f"- {epic} {direction}: {outcome} ({timestamp})\n"
        else:
            recent_trades_section += "No recent trades found.\n"
        
        return f"""
# Forex Trading Decision Maker

## Task
Make final trading decisions based on detailed analysis results.
Determine which trades to execute, how to manage existing positions, and calculate precise position sizing.

{account_info}

## Current Risk Parameters
- Base Risk Per Trade: {self.memory.system_memory["risk_management"]["base_risk"]}% of account
- Risk Multiplier: {self.memory.system_memory["risk_management"]["risk_multiplier"]:.2f}x
- Current Risk Setting: {current_risk:.2f}% of account per trade

## Open Positions
{positions_info}

{system_memory}

{market_context}

{recent_trades_section}

{analysis_section}

## Stop Loss Strategies Available
1. FIXED STOP - Traditional fixed stop loss placement
2. TRAILING STOP - Stop follows price at a fixed distance as it moves in your favor
3. BREAKEVEN STOP - Move stop to entry once trade has moved a certain distance in your favor
4. PARTIAL PROFIT PROTECTION - Move stop to lock in a percentage of current profit

## Response Format
Respond in this JSON format:
```
{{
  "trade_actions": [
    {{
      "action_type": "OPEN",
      "epic": "CS.D.EURUSD.TODAY.IP",
      "direction": "BUY or SELL",
      "size": 0.50,
      "entry_price": 1.2350,
      "initial_stop_loss": 1.2300,
      "take_profit": 1.2450,
      "risk_percent": 1.0,
      "pattern": "breakout",
      "stop_management": [
        {{
          "type": "TRAILING_STOP",
          "distance_pips": 15,
          "activation_condition": "immediate"
        }},
        {{
          "type": "BREAKEVEN_STOP",
          "activation_profit_pips": 20,
          "pips_above_entry": 5
        }}
      ],
      "reasoning": "Specific reasoning for this trade decision"
    }}
  ],
  "position_actions": [
    {{
      "action_type": "CLOSE",
      "epic": "CS.D.GBPUSD.TODAY.IP",
      "dealId": "DEAL_ID",
      "reason": "Explanation"
    }},
    {{
      "action_type": "UPDATE_STOP",
      "epic": "CS.D.USDJPY.TODAY.IP",
      "dealId": "DEAL_ID",
      "new_stop_level": 142.50,
      "reason": "Moving stop to breakeven"
    }}
  ],
  "analysis": {{
    "market_commentary": "Brief commentary on current market conditions",
    "risk_assessment": "Assessment of current risk levels and position sizing"
  }}
}}
```
"""

# --- Trade Execution ---
def execute_trade(ig, trade):
    """Execute a new trade."""
    try:
        logger.info(f"Executing {trade.get('direction')} {trade.get('epic')} | Size: {trade.get('size')}")
        
        response = ig.create_open_position(
            epic=trade["epic"],
            direction=trade["direction"],
            size=float(trade["size"]),
            order_type="MARKET",
            currency_code=os.getenv("ACCOUNT_CURRENCY", "GBP"),
            expiry="DFB",
            force_open=True,
            guaranteed_stop=False,
            stop_level=float(trade["initial_stop_loss"]) if "initial_stop_loss" in trade else None,
            limit_level=float(trade["take_profit"]) if "take_profit" in trade else None
        )
        
        # Log the trade
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epic": trade["epic"],
            "direction": trade["direction"],
            "size": trade["size"],
            "entry_price": trade.get("entry_price"),
            "stop_loss": trade.get("initial_stop_loss"),
            "take_profit": trade.get("take_profit"),
            "risk_percent": trade.get("risk_percent"),
            "pattern": trade.get("pattern"),
            "stop_management": trade.get("stop_management", []),
            "reasoning": trade.get("reasoning", ""),
            "outcome": "EXECUTED" if response.get("dealStatus") == "ACCEPTED" else "FAILED",
            "deal_id": response.get("dealId"),
            "reason": response.get("reason", "")
        }
        
        with open("data/trade_log.jsonl", "a") as f:
            f.write(json.dumps(log_data) + "\n")
        
        return True, response.get("dealId"), log_data
    except Exception as e:
        logger.error(f"Trade execution error: {e}")
        return False, None, {"outcome": "ERROR", "reason": str(e)}

def close_position(ig, position_action):
    """Close an existing position."""
    try:
        deal_id = position_action.get("dealId")
        epic = position_action.get("epic")
        
        logger.info(f"Closing position {deal_id} | {epic}")
        
        # Find position details
        positions = get_positions(ig)
        position = positions[positions["dealId"] == deal_id]
        
        if position.empty:
            logger.warning(f"Position not found for close: {deal_id}")
            return False, {"outcome": "FAILED", "reason": "Position not found"}
            
        # Get position details
        direction = position.iloc[0].get("direction")
        size = position.iloc[0].get("size")
        
        # Execute close
        close_direction = "SELL" if direction == "BUY" else "BUY"
        
        response = ig.close_open_position(
            deal_id=deal_id,
            direction=close_direction,
            size=float(size),
            order_type="MARKET"
        )
        
        # Log the close
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epic": epic,
            "direction": "CLOSE",
            "outcome": "CLOSED" if response.get("dealStatus") == "ACCEPTED" else "FAILED",
            "deal_id": deal_id,
            "reason": position_action.get("reason", "")
        }
        
        with open("data/trade_log.jsonl", "a") as f:
            f.write(json.dumps(log_data) + "\n")
        
        return True, log_data
    except Exception as e:
        logger.error(f"Close position error: {e}")
        return False, {"outcome": "ERROR", "reason": str(e)}

def update_stop_level(ig, position_action):
    """Update stop loss level for a position."""
    try:
        deal_id = position_action.get("dealId")
        new_stop = position_action.get("new_stop_level")
        
        logger.info(f"Updating stop for {deal_id} to {new_stop}")
        
        response = ig.update_open_position(
            deal_id=deal_id,
            stop_level=float(new_stop)
        )
        
        # Log the update
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": "UPDATE_STOP",
            "deal_id": deal_id,
            "new_stop": new_stop,
            "outcome": "UPDATED" if response.get("dealStatus") == "ACCEPTED" else "FAILED",
            "reason": position_action.get("reason", "")
        }
        
        with open("data/stop_updates.jsonl", "a") as f:
            f.write(json.dumps(log_data) + "\n")
        
        return True, log_data
    except Exception as e:
        logger.error(f"Update stop error: {e}")
        return False, {"outcome": "ERROR", "reason": str(e)}

def implement_stop_management(ig, deal_id, position_data, stop_management, memory):
    """Implement stop management strategies for a position."""
    if not stop_management:
        return
    
    try:
        # Store stop management settings
        with open(f"data/stop_management/{deal_id}.json", "w") as f:
            json.dump({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "position": position_data,
                "stop_management": stop_management
            }, f, indent=2)
        
        for strategy in stop_management:
            strategy_type = strategy.get("type", "").upper()
            
            if strategy_type == "TRAILING_STOP" and strategy.get("activation_condition") == "immediate":
                # Implement immediate trailing stop
                distance_pips = strategy.get("distance_pips", 15)
                direction = position_data.get("direction")
                epic = position_data.get("epic")
                
                # Get current price
                snapshot = get_snapshot(ig, epic)
                if not snapshot:
                    continue
                    
                current_price = snapshot.get("bid") if direction == "SELL" else snapshot.get("offer")
                
                if current_price:
                    # Calculate new stop based on current price and direction
                    pip_value = 0.0001 if "JPY" not in epic else 0.01
                    new_stop = current_price - (distance_pips * pip_value) if direction == "BUY" else current_price + (distance_pips * pip_value)
                    
                    # Format to 5 decimal places
                    new_stop = float(f"{new_stop:.5f}")
                    
                    # Update the stop
                    ig.update_open_position(
                        deal_id=deal_id,
                        stop_level=new_stop
                    )
                    
                    logger.info(f"Implemented trailing stop for {deal_id} at {new_stop}")
                    
                    # Log the update
                    log_data = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "direction": "UPDATE_STOP",
                        "deal_id": deal_id,
                        "new_stop": new_stop,
                        "strategy": "TRAILING_STOP",
                        "outcome": "UPDATED"
                    }
                    
                    with open("data/stop_updates.jsonl", "a") as f:
                        f.write(json.dumps(log_data) + "\n")
    except Exception as e:
        logger.error(f"Stop management error: {e}")

# --- Main Function ---
def main():
    """Main trading loop."""
    logger.info("Starting Budget-Aware LLM Forex Trading Bot")
    print("\nSTARTING BUDGET-AWARE LLM FOREX TRADING BOT")
    
    # Initialize API connections
    ig = get_ig_service()
    polygon = get_polygon_client()
    
    if not ig or not polygon:
        logger.error("Failed to initialize APIs. Exiting.")
        return
    
    # Initialize resource manager
    resource_manager = LLMResourceManager(storage_path="data", daily_budget=20.0)
    
    # Initialize memory system
    memory = TradingMemory()
    
    # Initialize three-tier LLM system
    llm_system = ThreeTierLLMSystem(resource_manager, memory)
    
    # Display budget status
    budget_status = resource_manager.get_budget_status()
    print(f"Daily budget: ${budget_status['daily_budget']:.2f}")
    print(f"Available: ${budget_status['remaining']:.2f} ({100-budget_status['percent_used']:.1f}% remaining)")
    
    # Trading loop
    while True:
        try:
            cycle_start_time = time.time()
            
            # Determine if we should run the full cycle or just position management
            scanner_frequency = resource_manager.get_run_frequency("scanner")
            
            # Check if we're due for a scanning cycle
            if (cycle_start_time % (scanner_frequency * 60)) < 60:
                # Full trading cycle
                logger.info(f"Starting full trading cycle (scanner frequency: {scanner_frequency} min)")
                
                # 1. Collect account and position data
                account = get_account_data(ig)
                positions = get_positions(ig)
                
                # 2. Collect market data for all pairs
                market_data = {}
                for epic in FOREX_PAIRS:
                    # Get price history and current price
                    data = collect_market_data(polygon, epic)
                    snapshot = get_snapshot(ig, epic)
                    
                    if data and snapshot:
                        market_data[epic] = {
                            "price_data": data,
                            "current_price": snapshot
                        }
                
                # 3. Run Tier 1: Market Scanner - if budget allows
                if resource_manager.can_run_tier("scanner"):
                    scanner_result = llm_system.run_market_scanner({
                        "account": account,
                        "positions": positions,
                        "market_data": market_data
                    })
                    
                    opportunities = scanner_result.get("opportunities", [])
                    
                    # If we have opportunities and budget, run Tier 2: Analysis Engine
                    if opportunities and resource_manager.can_run_tier("analyzer"):
                        analyzer_result = llm_system.run_analysis_engine({
                            "account": account,
                            "positions": positions,
                            "market_data": market_data
                        }, opportunities)
                        
                        analysis_results = analyzer_result.get("analysis_results", [])
                        
                        # If we have analysis results and budget, run Tier 3: Decision Maker
                        if analysis_results and resource_manager.can_run_tier("decision"):
                            decision_result = llm_system.run_decision_maker({
                                "account": account,
                                "positions": positions,
                                "market_data": market_data
                            }, analysis_results)
                            
                            # Execute trade actions
                            trade_actions = decision_result.get("trade_actions", [])
                            for trade in trade_actions:
                                if trade.get("action_type") == "OPEN":
                                    success, deal_id, trade_result = execute_trade(ig, trade)
                                    
                                    # If trade successful and has stop management instructions
                                    if success and deal_id and "stop_management" in trade:
                                        # Implement stop management strategies
                                        implement_stop_management(ig, deal_id, trade, trade["stop_management"], memory)
                                        
                                    # Update memory with trade result
                                    memory.update_system_memory(trade_result)
                            
                            # Execute position actions
                            position_actions = decision_result.get("position_actions", [])
                            for action in position_actions:
                                action_type = action.get("action_type", "").upper()
                                
                                if action_type == "CLOSE":
                                    success, result = close_position(ig, action)
                                    # Update memory with close result
                                    if success:
                                        memory.update_system_memory(result)
                                        
                                elif action_type == "UPDATE_STOP":
                                    update_stop_level(ig, action)
                
                # 4. Optimize resource allocation periodically
                resource_manager.optimize_allocation()
                
                # 5. Adjust risk based on performance
                memory.adjust_risk_based_on_performance()
                
            else:
                # Position management only cycle
                logger.info("Running position management cycle")
                
                # Get open positions
                positions = get_positions(ig)
                
                # Check trailing stops and other position management strategies
                if not positions.empty:
                    for _, pos in positions.iterrows():
                        deal_id = pos.get("dealId")
                        
                        # Check if we have stop management settings for this position
                        stop_mgmt_file = f"data/stop_management/{deal_id}.json"
                        if os.path.exists(stop_mgmt_file):
                            with open(stop_mgmt_file, "r") as f:
                                stop_data = json.load(f)
                                
                            # Implement position management
                            implement_stop_management(ig, deal_id, pos.to_dict(), stop_data.get("stop_management", []), memory)
            
            # Calculate cycle duration and sleep time
            cycle_duration = time.time() - cycle_start_time
            
            # Determine sleep time based on whether this was a full cycle or just position management
            if (cycle_start_time % (scanner_frequency * 60)) < 60:
                # After full cycle, sleep until next position check (30 seconds)
                sleep_time = 30
            else:
                # After position check, sleep until next position check (30 seconds)
                sleep_time = 30
            
            logger.info(f"Cycle complete. Sleeping for {sleep_time:.1f}s until next check.")
            
            # Display budget status every few cycles
            if cycle_start_time % 300 < 60:  # Every ~5 minutes
                budget_status = resource_manager.get_budget_status()
                logger.info(f"Budget status: ${budget_status['remaining']:.2f} remaining ({100-budget_status['percent_used']:.1f}%)")
            
            time.sleep(sleep_time)
            
        except ApiExceededException:
            logger.warning("IG API rate limit exceeded. Waiting longer.")
            time.sleep(300)  # 5 minutes if rate limited
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(60)  # 1 minute on general error

if __name__ == "__main__":
    main()