"""Paleta neon e opcoes de grafico, num lugar so.

Tema escuro com dois neons: ciano para o que e do sistema (entrada, equity,
foco) e violeta para o secundario. Verde e rosa neon so para dinheiro -
cor de P&L nao e cor de marca, e nunca deve competir com ela.

O fundo e azul-preto, nao preto puro: preto absoluto faz o neon vibrar e
cansa em tela grande.
"""

GROUND = "#06080F"
SURFACE = "#0B0F1A"
SURFACE_2 = "#111726"
SURFACE_3 = "#182033"

INK = "#EAF1FF"
INK_2 = "#C3CEE4"
MUTED = "#8494B3"

LINE = "#1E2740"
LINE_SOFT = "#161D30"

ACCENT = "#22E4FF"        # ciano neon
ACCENT_2 = "#B96BFF"      # violeta neon
ACCENT_DIM = "#1C5A72"

POS = "#00F5A0"           # verde neon
NEG = "#FF4D7D"           # rosa neon
WARN = "#FFC93C"

UP = POS
DOWN = NEG

CHART_OPTIONS = {
    "layout": {
        "background": {"type": "solid", "color": SURFACE},
        "textColor": MUTED,
        "fontFamily": "'JetBrains Mono','IBM Plex Mono',ui-monospace,Consolas,monospace",
        "fontSize": 12,
        # exigencia da licenca Apache 2.0 da TradingView - nao desligar
        "attributionLogo": True,
        "panes": {"separatorColor": LINE, "separatorHoverColor": ACCENT_DIM},
    },
    "grid": {
        "vertLines": {"color": LINE_SOFT},
        "horzLines": {"color": LINE_SOFT},
    },
    "rightPriceScale": {"borderColor": LINE,
                        "scaleMargins": {"top": .08, "bottom": .08}},
    "timeScale": {"borderColor": LINE, "timeVisible": True,
                  "secondsVisible": False, "rightOffset": 6},
    "crosshair": {
        "mode": 0,
        "vertLine": {"color": ACCENT_DIM, "width": 1, "style": 2,
                     "labelBackgroundColor": ACCENT},
        "horzLine": {"color": ACCENT_DIM, "width": 1, "style": 2,
                     "labelBackgroundColor": ACCENT},
    },
    "autoSize": True,
}

CANDLE_OPTIONS = {
    "upColor": UP, "downColor": DOWN,
    "borderUpColor": UP, "borderDownColor": DOWN,
    "wickUpColor": UP, "wickDownColor": DOWN,
    "priceFormat": {"type": "price", "precision": 0, "minMove": 5},
}
