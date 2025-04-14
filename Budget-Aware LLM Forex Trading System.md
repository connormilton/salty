# Budget-Aware LLM Forex Trading System

A sophisticated, self-optimizing forex trading system that leverages tiered LLM analysis with budget management, memory, and continuous learning.

## Overview

This system employs a three-tier LLM approach that maximizes efficiency by using different models for different tasks, all while managing a daily budget and learning from past trades. The system's core innovation is letting LLMs manage their own resource allocation while focusing on the most promising trading opportunities.

## Key Components

### 1. LLM Resource Manager (`llm_resource_manager.py`)
- Tracks and manages the daily LLM budget
- Dynamically adjusts frequency of analysis based on market conditions and remaining budget
- Self-optimizes resource allocation throughout the trading day
- Ensures budget is preserved for high-opportunity market sessions

### 2. Three-Tier LLM System (`tiered_llm_trader.py`)
- **Tier 1: Market Scanner** (GPT-3.5 Turbo)
  - Quickly scans all currency pairs for potential opportunities
  - Uses a cheaper, faster model to identify promising setups
  - Runs more frequently but uses fewer tokens

- **Tier 2: Analysis Engine** (GPT-4)
  - Performs detailed analysis on only the top opportunities
  - Conducts deep technical analysis and identifies precise entry/exit points
  - Determines key support/resistance levels and patterns

- **Tier 3: Decision Maker** (GPT-4)
  - Makes final trading decisions with position sizing
  - Manages risk based on system's historical performance
  - Implements sophisticated stop management strategies

### 3. Trading Memory System
- Maintains persistent memory between trading sessions
- Learns which pairs and patterns perform best
- Automatically adjusts risk based on recent performance
- Builds a knowledge base of key market levels and characteristics

## Features

- **Budget-Aware Operation**: Stays within a specified daily budget by dynamically adjusting analysis frequency and depth
- **Continuous Learning**: Builds knowledge about what works and automatically adjusts strategies
- **Self-Optimization**: LLMs optimize their own resource allocation based on opportunity and performance
- **Adaptive Risk Management**: Dynamically adjusts position sizing based on recent performance
- **Sophisticated Stop Management**: Implements trailing stops, breakeven stops, and profit protection

## Setup

### Prerequisites

- Python 3.8+
- IG Trading API access
- Polygon.io API for market data
- OpenAI API key

### Environment Variables

Create a `.env` file with:

```
# API Keys
IG_USERNAME=your_username
IG_PASSWORD=your_password
IG_API_KEY=your_ig_api_key
IG_ACC_TYPE=DEMO
IG_ACCOUNT_ID=your_account_id
POLYGON_API_KEY=your_polygon_key
OPENAI_API_KEY=your_openai_key

# Budget Settings
DAILY_LLM_BUDGET=20.0
ACCOUNT_CURRENCY=GBP
```

### Installation

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run the system: `python tiered_llm_trader.py`

## Data Storage

The system maintains several data stores:

- `data/usage_log.jsonl`: Tracks LLM API usage and costs
- `data/resource_allocation.json`: Current resource allocation plan
- `data/system_memory.json`: Trading system memory
- `data/pair_memory.json`: Memory specific to each currency pair
- `data/market_context.json`: Current market context and insights
- `data/trade_log.jsonl`: Record of all trades executed
- `data/stop_management/`: Stop management settings for each position

## Currency Pairs

The system trades a diverse set of forex pairs:

- Major pairs: EUR/USD, USD/JPY, GBP/USD, AUD/USD, USD/CAD
- Cross-currency pairs: GBP/JPY, EUR/JPY, AUD/JPY, EUR/GBP
- Regional economy proxies: USD/CHF, NZD/USD, AUD/NZD
- Correlation pairs: CAD/JPY, AUD/CAD
- Exotic: USD/SGD

## Budget Management

The system allocates budget among different market sessions for optimal usage:
- London open: 30% of budget
- NY open: 30% of budget
- Session overlap: 15% of budget
- Asian session: 15% of budget
- Quiet hours: 10% of budget

## Disclaimer

This system is for educational purposes only. Trading forex involves significant risk of loss and is not suitable for all investors. Past performance is not indicative of future results.