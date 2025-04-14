# llm_resource_manager.py - Manages LLM budget and resource allocation

import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("ResourceManager")

class LLMResourceManager:
    """Manages LLM resource allocation, budgeting, and optimization."""
    
    def __init__(self, storage_path="data", daily_budget=20.0):
        """Initialize the resource manager."""
        self.storage_path = storage_path
        self.daily_budget = float(os.getenv("DAILY_LLM_BUDGET", daily_budget))
        self.usage_log_path = f"{storage_path}/usage_log.jsonl"
        self.allocation_path = f"{storage_path}/resource_allocation.json"
        
        # Initialize OpenAI for resource management
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        openai.api_key = self.openai_api_key
        
        # Cost per 1K tokens for different models
        self.token_costs = {
            "gpt-3.5-turbo": {"input": 0.0015, "output": 0.002},
            "gpt-4": {"input": 0.03, "output": 0.06}
        }
        
        # Initial tier configurations
        self.tier_configs = {
            "scanner": {
                "model": "gpt-3.5-turbo",
                "base_frequency_minutes": 5,
                "min_frequency_minutes": 3,
                "max_frequency_minutes": 15,
                "estimated_tokens_per_run": {"input": 2000, "output": 500}
            },
            "analyzer": {
                "model": "gpt-4",
                "base_frequency_minutes": 30,
                "min_frequency_minutes": 15,
                "max_frequency_minutes": 60,
                "estimated_tokens_per_run": {"input": 4000, "output": 1000}
            },
            "decision": {
                "model": "gpt-4",
                "base_frequency_minutes": 30,
                "min_frequency_minutes": 15,
                "max_frequency_minutes": 60,
                "estimated_tokens_per_run": {"input": 5000, "output": 1200}
            }
        }
        
        # Load existing usage or create new for today
        self._init_usage_tracking()
        
        # Load or create resource allocation plan
        self._init_allocation_plan()
    
    def _init_usage_tracking(self):
        """Initialize usage tracking for today."""
        self.today = datetime.now(timezone.utc).date().isoformat()
        self.usage_today = self._load_usage_for_today()
    
    def _load_usage_for_today(self):
        """Load usage data for today or create new tracking."""
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self.usage_log_path), exist_ok=True)
        
        # Check if we have today's usage data
        if os.path.exists(self.usage_log_path):
            with open(self.usage_log_path, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("date") == self.today:
                            return entry
                    except json.JSONDecodeError:
                        continue
        
        # Create new usage entry for today
        new_usage = {
            "date": self.today,
            "total_cost": 0.0,
            "tiers": {
                "scanner": {"runs": 0, "cost": 0.0, "tokens": {"input": 0, "output": 0}},
                "analyzer": {"runs": 0, "cost": 0.0, "tokens": {"input": 0, "output": 0}},
                "decision": {"runs": 0, "cost": 0.0, "tokens": {"input": 0, "output": 0}}
            },
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
        # Write initial entry
        with open(self.usage_log_path, "a") as f:
            f.write(json.dumps(new_usage) + "\n")
        
        return new_usage
    
    def _init_allocation_plan(self):
        """Initialize or load resource allocation plan."""
        # Create directory if needed
        os.makedirs(os.path.dirname(self.allocation_path), exist_ok=True)
        
        # Try to load existing allocation
        if os.path.exists(self.allocation_path):
            try:
                with open(self.allocation_path, "r") as f:
                    self.allocation = json.load(f)
                    # Check if it's for today
                    if self.allocation.get("date") != self.today:
                        self.allocation = self._create_initial_allocation()
            except:
                self.allocation = self._create_initial_allocation()
        else:
            self.allocation = self._create_initial_allocation()
        
        # Save allocation plan
        with open(self.allocation_path, "w") as f:
            json.dump(self.allocation, f, indent=2)
    
    def _create_initial_allocation(self):
        """Create initial allocation of resources across the day."""
        current_hour = datetime.now(timezone.utc).hour
        
        # Determine which trading session we're starting in
        current_session = self._get_trading_session(current_hour)
        
        return {
            "date": self.today,
            "daily_budget": self.daily_budget,
            "tier_frequencies": {
                "scanner": self.tier_configs["scanner"]["base_frequency_minutes"],
                "analyzer": self.tier_configs["analyzer"]["base_frequency_minutes"],
                "decision": self.tier_configs["decision"]["base_frequency_minutes"]
            },
            "pair_allocation": {
                "percent_to_analyze": 30,  # % of pairs that can proceed to analysis
                "min_pairs_to_analyze": 3,  # Minimum pairs to analyze regardless of %
                "max_pairs_to_analyze": 8   # Maximum pairs to analyze regardless of %
            },
            "session_budget_allocation": {
                "london_open": 0.30,     # 30% of budget (8-11 UTC)
                "ny_open": 0.30,         # 30% of budget (13-16 UTC)
                "overlap": 0.15,         # 15% of budget (12 UTC)
                "asian_session": 0.15,   # 15% of budget (0-7 UTC)
                "quiet_hours": 0.10      # 10% of budget (17-23 UTC)
            },
            "session_budget_remaining": {
                "london_open": self.daily_budget * 0.30,
                "ny_open": self.daily_budget * 0.30,
                "overlap": self.daily_budget * 0.15,
                "asian_session": self.daily_budget * 0.15,
                "quiet_hours": self.daily_budget * 0.10
            },
            "current_session": current_session,
            "last_optimized": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    
    def _get_trading_session(self, hour):
        """Determine current trading session based on UTC hour."""
        if 0 <= hour <= 7:
            return "asian_session"
        elif 8 <= hour <= 11:
            return "london_open"
        elif hour == 12:
            return "overlap"
        elif 13 <= hour <= 16:
            return "ny_open"
        else:  # 17-23
            return "quiet_hours"
    
    def update_usage(self, tier, tokens_input, tokens_output, actual_cost=None):
        """Update usage tracking with a new run."""
        # Check if we need to reset for a new day
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self.today:
            self.today = today
            self._init_usage_tracking()
            self._init_allocation_plan()
        
        # Get model for this tier
        model = self.tier_configs[tier]["model"]
        
        # Calculate cost if not provided
        if actual_cost is None:
            input_cost = (tokens_input / 1000) * self.token_costs[model]["input"]
            output_cost = (tokens_output / 1000) * self.token_costs[model]["output"]
            cost = input_cost + output_cost
        else:
            cost = actual_cost
        
        # Update usage data
        self.usage_today["tiers"][tier]["runs"] += 1
        self.usage_today["tiers"][tier]["cost"] += cost
        self.usage_today["tiers"][tier]["tokens"]["input"] += tokens_input
        self.usage_today["tiers"][tier]["tokens"]["output"] += tokens_output
        self.usage_today["total_cost"] += cost
        self.usage_today["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Update session budget
        current_hour = datetime.now(timezone.utc).hour
        current_session = self._get_trading_session(current_hour)
        
        # Update current session if it changed
        if current_session != self.allocation["current_session"]:
            self.allocation["current_session"] = current_session
        
        # Deduct from session budget
        self.allocation["session_budget_remaining"][current_session] -= cost
        if self.allocation["session_budget_remaining"][current_session] < 0:
            self.allocation["session_budget_remaining"][current_session] = 0
        
        # Save updated usage
        self._save_usage()
        
        # Save updated allocation
        with open(self.allocation_path, "w") as f:
            json.dump(self.allocation, f, indent=2)
        
        # Log the usage
        logger.info(f"LLM usage: {tier} - {tokens_input} in, {tokens_output} out, ${cost:.4f}")
        
        return cost
    
    def _save_usage(self):
        """Save current usage data to log file."""
        # Read existing log
        entries = []
        if os.path.exists(self.usage_log_path):
            with open(self.usage_log_path, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("date") != self.today:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        
        # Add today's entry
        entries.append(self.usage_today)
        
        # Write back to file
        with open(self.usage_log_path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
    
    def get_run_frequency(self, tier, market_activity="normal"):
        """Get the optimal frequency to run each tier based on budget and market activity."""
        # Get base frequency
        base_frequency = self.allocation["tier_frequencies"][tier]
        
        # Current session
        current_hour = datetime.now(timezone.utc).hour
        current_session = self._get_trading_session(current_hour)
        
        # Check remaining budget
        total_spent = self.usage_today["total_cost"]
        remaining_budget = self.daily_budget - total_spent
        budget_percent_remaining = (remaining_budget / self.daily_budget) * 100
        
        # Adjust frequency based on budget and market activity
        if market_activity == "high" and budget_percent_remaining > 50:
            # More frequent during high activity if budget allows
            adjustment = 0.7  # Run 30% faster
        elif market_activity == "low" or budget_percent_remaining < 20:
            # Less frequent during low activity or low budget
            adjustment = 1.5  # Run 50% slower
        elif budget_percent_remaining < 10:
            # Much less frequent if budget almost depleted
            adjustment = 2.0  # Run 100% slower
        else:
            adjustment = 1.0  # No change
        
        # Calculate adjusted frequency
        adjusted_frequency = base_frequency * adjustment
        
        # Ensure within allowed range
        min_freq = self.tier_configs[tier]["min_frequency_minutes"]
        max_freq = self.tier_configs[tier]["max_frequency_minutes"]
        
        if adjusted_frequency < min_freq:
            return min_freq
        elif adjusted_frequency > max_freq:
            return max_freq
        else:
            return adjusted_frequency
    
    def can_run_tier(self, tier):
        """Check if we have budget to run a specific tier."""
        # Get model and estimated cost
        model = self.tier_configs[tier]["model"]
        tokens_in = self.tier_configs[tier]["estimated_tokens_per_run"]["input"]
        tokens_out = self.tier_configs[tier]["estimated_tokens_per_run"]["output"]
        
        estimated_cost = ((tokens_in / 1000) * self.token_costs[model]["input"] +
                          (tokens_out / 1000) * self.token_costs[model]["output"])
        
        # Check remaining budget
        current_hour = datetime.now(timezone.utc).hour
        current_session = self._get_trading_session(current_hour)
        session_budget = self.allocation["session_budget_remaining"][current_session]
        
        return estimated_cost <= session_budget
    
    def get_pairs_to_analyze(self, scanner_results, total_pairs):
        """Determine how many pairs should proceed to deeper analysis."""
        # Get allocation settings
        percent = self.allocation["pair_allocation"]["percent_to_analyze"]
        min_pairs = self.allocation["pair_allocation"]["min_pairs_to_analyze"]
        max_pairs = self.allocation["pair_allocation"]["max_pairs_to_analyze"]
        
        # Calculate how many pairs based on percentage
        pairs_by_percent = max(int(total_pairs * (percent / 100)), 1)
        
        # Ensure within limits
        if pairs_by_percent < min_pairs:
            return min(min_pairs, len(scanner_results))
        elif pairs_by_percent > max_pairs:
            return min(max_pairs, len(scanner_results))
        else:
            return min(pairs_by_percent, len(scanner_results))
    
    def optimize_allocation(self, performance_metrics=None):
        """Use LLM to optimize resource allocation based on performance."""
        # Skip if recently optimized (every 4 hours)
        last_optimized = datetime.fromisoformat(self.allocation["last_optimized"])
        hours_since_optimization = (datetime.now(timezone.utc) - last_optimized).total_seconds() / 3600
        
        if hours_since_optimization < 4:
            return self.allocation
        
        try:
            # Current usage and budget status
            remaining_budget = self.daily_budget - self.usage_today["total_cost"]
            hours_remaining = 24 - datetime.now(timezone.utc).hour
            
            prompt = f"""
# LLM Forex Trading System Resource Optimization

## Current Status
- Daily Budget: ${self.daily_budget:.2f}
- Spent So Far: ${self.usage_today["total_cost"]:.2f}
- Remaining: ${remaining_budget:.2f}
- Hours Remaining Today: {hours_remaining}

## Current Tier Usage
- Scanner (GPT-3.5): {self.usage_today["tiers"]["scanner"]["runs"]} runs, ${self.usage_today["tiers"]["scanner"]["cost"]:.2f}
- Analyzer (GPT-4): {self.usage_today["tiers"]["analyzer"]["runs"]} runs, ${self.usage_today["tiers"]["analyzer"]["cost"]:.2f}
- Decision (GPT-4): {self.usage_today["tiers"]["decision"]["runs"]} runs, ${self.usage_today["tiers"]["decision"]["cost"]:.2f}

## Current Allocation
```json
{json.dumps(self.allocation["tier_frequencies"], indent=2)}
```

## Pair Selection
```json
{json.dumps(self.allocation["pair_allocation"], indent=2)}
```

## Session Budget Allocation
```json
{json.dumps(self.allocation["session_budget_allocation"], indent=2)}
```

## Task
Optimize the resource allocation based on current usage and remaining budget. Update:
1. The tier frequencies (in minutes between runs)
2. The pair allocation percentages
3. The session budget allocation

Ensure we have enough budget to last the whole day while maximizing trading opportunities.

## Response Format
Respond ONLY with a valid JSON object containing the updated allocation:
```json
{
  "tier_frequencies": {
    "scanner": 5,
    "analyzer": 30,
    "decision": 30
  },
  "pair_allocation": {
    "percent_to_analyze": 30,
    "min_pairs_to_analyze": 3,
    "max_pairs_to_analyze": 8
  },
  "session_budget_allocation": {
    "london_open": 0.30,
    "ny_open": 0.30,
    "overlap": 0.15,
    "asian_session": 0.15,
    "quiet_hours": 0.10
  }
}
```
"""
            
            # Call LLM API with GPT-3.5
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an AI resource optimization expert that manages LLM usage for a forex trading system."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            response_content = response.choices[0].message.content
            new_allocation = json.loads(response_content)
            
            # Update allocation plan
            self.allocation["tier_frequencies"] = new_allocation["tier_frequencies"]
            self.allocation["pair_allocation"] = new_allocation["pair_allocation"]
            self.allocation["session_budget_allocation"] = new_allocation["session_budget_allocation"]
            
            # Update last optimized timestamp
            self.allocation["last_optimized"] = datetime.now(timezone.utc).isoformat()
            self.allocation["last_updated"] = datetime.now(timezone.utc).isoformat()
            
            # Save updated allocation
            with open(self.allocation_path, "w") as f:
                json.dump(self.allocation, f, indent=2)
                
            # Update session budget remaining based on new allocation
            total_spent = self.usage_today["total_cost"]
            remaining = self.daily_budget - total_spent
            
            # Redistribute remaining budget according to new allocation
            for session, percentage in self.allocation["session_budget_allocation"].items():
                self.allocation["session_budget_remaining"][session] = remaining * percentage
            
            logger.info(f"Resource allocation optimized. New scanner frequency: {self.allocation['tier_frequencies']['scanner']} min")
            
            return self.allocation
            
        except Exception as e:
            logger.error(f"Error optimizing resource allocation: {e}")
            return self.allocation
    
    def get_estimated_run_cost(self, tier):
        """Get estimated cost for running a tier."""
        model = self.tier_configs[tier]["model"]
        tokens_in = self.tier_configs[tier]["estimated_tokens_per_run"]["input"]
        tokens_out = self.tier_configs[tier]["estimated_tokens_per_run"]["output"]
        
        estimated_cost = ((tokens_in / 1000) * self.token_costs[model]["input"] +
                          (tokens_out / 1000) * self.token_costs[model]["output"])
        
        return estimated_cost
    
    def get_total_spent(self):
        """Get total amount spent today."""
        return self.usage_today["total_cost"]
    
    def get_remaining_budget(self):
        """Get remaining budget for today."""
        return self.daily_budget - self.usage_today["total_cost"]
    
    def get_budget_status(self):
        """Get complete budget status information."""
        remaining = self.daily_budget - self.usage_today["total_cost"]
        percent_used = (self.usage_today["total_cost"] / self.daily_budget) * 100
        
        return {
            "daily_budget": self.daily_budget,
            "total_spent": self.usage_today["total_cost"],
            "remaining": remaining,
            "percent_used": percent_used,
            "tier_usage": self.usage_today["tiers"],
            "can_run": {
                "scanner": self.can_run_tier("scanner"),
                "analyzer": self.can_run_tier("analyzer"),
                "decision": self.can_run_tier("decision")
            }
        }