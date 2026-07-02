"""Тесты для ключевой бизнес-логики INVESTMIND AI."""

from collections import namedtuple

import pytest

from handlers.portfolio import score_to_profile
from handlers.journal import _compute_positions
from utils.helpers import is_crypto_ticker, format_currency, format_number
from utils.text import esc, md_to_html

Trade = namedtuple("Trade", ["ticker", "type", "quantity", "price"])


def _trade(ticker, trade_type, quantity, price):
    return {"ticker": ticker, "type": trade_type, "quantity": quantity, "price": price}


class TestScoreToProfile:
  def test_conservative(self):
      assert score_to_profile(5, 10) == "conservative"

  def test_moderate(self):
      assert score_to_profile(25, 10) == "moderate"

  def test_aggressive(self):
      assert score_to_profile(35, 10) == "aggressive"


class TestComputePositions:
  def test_single_buy(self):
      trades = [_trade("AAPL", "BUY", 10, 100.0)]
      pos = _compute_positions(trades)
      assert pos["AAPL"]["quantity"] == 10
      assert pos["AAPL"]["cost_basis"] == 1000.0

  def test_buy_and_partial_sell(self):
      trades = [
          _trade("AAPL", "BUY", 10, 100.0),
          _trade("AAPL", "SELL", 4, 120.0),
      ]
      pos = _compute_positions(trades)
      assert abs(pos["AAPL"]["quantity"] - 6) < 1e-9
      assert abs(pos["AAPL"]["cost_basis"] - 600.0) < 1e-9

  def test_closed_position_excluded(self):
      trades = [
          _trade("AAPL", "BUY", 5, 100.0),
          _trade("AAPL", "SELL", 5, 110.0),
      ]
      pos = _compute_positions(trades)
      assert "AAPL" not in pos


class TestHelpers:
  def test_is_crypto_ticker(self):
      assert is_crypto_ticker("BTC") is True
      assert is_crypto_ticker("BTC-USD") is True
      assert is_crypto_ticker("AAPL") is False

  def test_format_currency(self):
      assert "$" in format_currency(1234.5, "USD")
      assert "₽" in format_currency(1234.5, "RUB")

  def test_format_number_none(self):
      assert format_number(None) == "н/д"


class TestText:
  def test_esc_html(self):
      assert esc("<script>") == "&lt;script&gt;"

  def test_md_to_html_bold(self):
      assert "<b>test</b>" in md_to_html("*test*")
