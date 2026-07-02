# handlers/__init__.py
"""Собирает все роутеры хендлеров в один список для подключения к диспетчеру."""

from . import start, learn, analyse, news, portfolio, journal, settings, voice

all_routers = [
    start.router,
    learn.router,
    analyse.router,
    news.router,
    portfolio.router,
    journal.router,
    settings.router,
    voice.router,  # должен идти после текстовых команд, но voice-фильтр не пересекается с ними
]
