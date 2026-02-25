"""
agents/trading_agent.py

Financial data analysis and trading signal generation.
NOTE: This agent ANALYZES and REPORTS — never executes real trades automatically.
All trade execution requires human approval (requires_human=True tasks).
"""

import json
import logging
import re
from datetime import datetime, timezone

import httpx

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

TRADING_SYSTEM_PROMPT = """You are a quantitative financial analyst for an AI agent farm.
Your role is to analyze data and generate insights — NOT to execute trades automatically.

Specialties:
- Technical analysis (MA, RSI, MACD, support/resistance)
- Fundamental analysis summaries
- Crypto market analysis
- Arbitrage opportunity detection
- Options strategy analysis
- Risk assessment

Always:
- Express uncertainty clearly (never guarantee profits)
- Provide specific entry/exit levels with stop losses
- Include risk/reward ratios
- Note when data is outdated
- Flag high-risk situations prominently
- Output structured JSON for signals, prose for analysis

IMPORTANT: Always set requires_human=true for any actual trade recommendation."""


class TradingAgent(BaseAgent):
    AGENT_TYPE = "trading"
    DEFAULT_LLM_LEVEL = "complex"

    def _default_system_prompt(self) -> str:
        return TRADING_SYSTEM_PROMPT

    def _execute(self, task: dict) -> dict:
        instructions = task.get("instructions", "")
        instructions_upper = instructions.upper()

        if "ANALYZE_CRYPTO" in instructions_upper:
            return self._analyze_crypto(task)
        elif "ARBITRAGE_SCAN" in instructions_upper:
            return self._scan_arbitrage(task)
        elif "MARKET_SUMMARY" in instructions_upper:
            return self._market_summary(task)
        elif "BACKTEST" in instructions_upper:
            return self._describe_backtest(task)
        else:
            return self._general_analysis(task)

    def _analyze_crypto(self, task: dict) -> dict:
        """Fetch market data and analyze a crypto asset."""
        instructions = task.get("instructions", "")
        symbol = self._extract_symbol(instructions) or "BTC"

        # Fetch price data (CoinGecko free API)
        market_data = self._fetch_coingecko_data(symbol)

        prompt = f"""Analyze this cryptocurrency and provide a trading analysis report.

Asset: {symbol}
Market Data: {json.dumps(market_data, indent=2)}

Provide:
1. Current market context (trend, momentum)
2. Key support/resistance levels
3. Short-term outlook (1-7 days)
4. Risk factors
5. Trading signal (if any): direction, entry zone, stop loss, take profit
6. Confidence level (0-100%)

Format as structured markdown. Include a JSON signal block at the end:
```json
{{
  "signal": "long|short|neutral",
  "entry_zone": [min, max],
  "stop_loss": price,
  "take_profit": [tp1, tp2],
  "confidence": 0-100,
  "requires_human_approval": true
}}
```"""

        response = self._call_llm(prompt, max_tokens=2000, level="complex")

        # Mark result as requiring human review
        result = f"⚠️ HUMAN REVIEW REQUIRED before any trade execution.\n\n{response['result']}"
        response["result"] = result

        # If task requires_human is not set, ensure it gets set
        if not task.get("requires_human"):
            self.notion.update_task(task["id"], "needs_human", result=result)
            return {**response, "result": result}

        return response

    def _scan_arbitrage(self, task: dict) -> dict:
        """Describe potential arbitrage opportunities based on current data."""
        prompt = f"""Identify potential arbitrage opportunities in cryptocurrency markets.

Context: {task.get('instructions', 'General crypto arbitrage scan')}

Analyze:
1. CEX-DEX price differences (BTC, ETH, major alts)
2. Triangular arbitrage paths
3. Funding rate arbitrage (perps vs spot)
4. Cross-chain bridge opportunities

For each opportunity provide:
- Assets involved
- Estimated spread %
- Required capital
- Execution complexity (1-5)
- Risk level

Format as a prioritized list. Flag anything requiring >$1000 capital as requiring human review."""
        return self._call_llm(prompt, max_tokens=2000, level="complex")

    def _market_summary(self, task: dict) -> dict:
        """Generate a market summary report."""
        # Fetch BTC/ETH data for context
        btc_data = self._fetch_coingecko_data("bitcoin")
        eth_data = self._fetch_coingecko_data("ethereum")

        prompt = f"""Write a concise crypto market summary report.

Current Data:
BTC: {json.dumps(btc_data, indent=2)}
ETH: {json.dumps(eth_data, indent=2)}

Context: {task.get('instructions', '')}

Include:
- Overall market sentiment
- BTC and ETH key metrics
- Notable movers (based on your knowledge)
- Key events to watch
- Risk-off vs risk-on assessment

Keep it under 500 words. Professional tone."""
        return self._call_llm(prompt, max_tokens=1500, level="complex")

    def _describe_backtest(self, task: dict) -> dict:
        """Describe a trading strategy and what backtesting would reveal."""
        prompt = f"""Describe a trading strategy and analyze its theoretical performance.

Strategy to evaluate: {task.get('instructions', '')}

Provide:
1. Strategy description (clear rules)
2. Historical performance characteristics (typical for this type of strategy)
3. Market conditions where it performs best/worst
4. Key parameters to optimize
5. Risk considerations
6. Suggested backtesting approach (tools, timeframes, metrics)

NOTE: This is theoretical analysis, not actual backtested results."""
        return self._call_llm(prompt, max_tokens=2000, level="complex")

    def _general_analysis(self, task: dict) -> dict:
        """Handle general financial analysis tasks."""
        return self._call_llm(
            task.get("instructions", ""),
            max_tokens=2000,
            level="complex",
        )

    def _fetch_coingecko_data(self, coin_id: str) -> dict:
        """Fetch basic market data from CoinGecko (free, no API key needed)."""
        coin_map = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "DOGE": "dogecoin", "ADA": "cardano",
        }
        cg_id = coin_map.get(coin_id.upper(), coin_id.lower())
        try:
            r = httpx.get(
                f"https://api.coingecko.com/api/v3/coins/{cg_id}",
                params={"localization": "false", "tickers": "false",
                        "community_data": "false", "developer_data": "false"},
                timeout=10,
                headers={"User-Agent": "AgentFarm/1.0"},
            )
            r.raise_for_status()
            data = r.json()
            md = data.get("market_data", {})
            return {
                "name": data.get("name"),
                "symbol": data.get("symbol", "").upper(),
                "price_usd": md.get("current_price", {}).get("usd"),
                "market_cap_usd": md.get("market_cap", {}).get("usd"),
                "volume_24h": md.get("total_volume", {}).get("usd"),
                "price_change_24h_pct": md.get("price_change_percentage_24h"),
                "price_change_7d_pct": md.get("price_change_percentage_7d"),
                "ath": md.get("ath", {}).get("usd"),
                "ath_change_pct": md.get("ath_change_percentage", {}).get("usd"),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning(f"CoinGecko fetch failed for {coin_id}: {e}")
            return {"error": str(e), "coin": coin_id}

    @staticmethod
    def _extract_symbol(text: str) -> str:
        """Extract crypto symbol from instructions."""
        match = re.search(r'\b(BTC|ETH|SOL|DOGE|ADA|BNB|XRP|USDT|bitcoin|ethereum)\b',
                          text, re.IGNORECASE)
        return match.group(1).upper() if match else ""
