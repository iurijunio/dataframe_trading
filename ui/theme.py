"""Paleta neon e opcoes de grafico, num lugar so.

Tema escuro com dois neons: ciano para o que e do sistema (entrada, equity,
foco) e violeta para o secundario. Verde e rosa neon so para dinheiro -
cor de P&L nao e cor de marca, e nunca deve competir com ela.

O fundo e preto com neutros cinza, sem tom azulado: o usuario preferiu
assim (16/10/2026). Os mesmos valores estao no :root do style.css; mudou
um, mude o outro.
"""

GROUND = "#000000"
SURFACE = "#0A0A0B"
SURFACE_2 = "#111113"
SURFACE_3 = "#18181B"

INK = "#E7E7EA"
INK_2 = "#C4C4CA"
MUTED = "#8B8B93"

LINE = "#232326"
LINE_SOFT = "#19191C"

ACCENT = "#22E4FF"        # ciano neon
ACCENT_2 = "#B96BFF"      # violeta neon
ACCENT_DIM = "#164A57"

# As fontes moram em ui/assets/fontes (fontes.css). Os graficos Plotly e o
# lightweight-charts nao leem o CSS, por isso o nome vem daqui.
FONTE_SANS = "Poppins, system-ui, 'Segoe UI', Arial, sans-serif"
FONTE_MONO = "'JetBrains Mono', ui-monospace, Consolas, monospace"

POS = "#00F5A0"           # verde neon
NEG = "#FF4D7D"           # rosa neon
WARN = "#FFC93C"

UP = POS
DOWN = NEG

# Uma cor por variante nos marcadores do papel (Ao vivo › Operação). Fora
# do verde e do rosa de propósito: são as cores dos candles, e um marcador
# verde sumiria em cima de um candle de alta. Com mais de 8 variantes as
# cores repetem e a tela troca a forma do marcador de saída.
CORES_VARIANTE = ["#22E4FF", "#B96BFF", "#FF9F43", "#F7F06D",
                  "#7C9CFF", "#FF7AE0", "#F2F5FA", "#D4A373"]
# operação fora do período ligado: aparece, mas não chama atenção
CINZA_FORA = "#5A5A62"

CHART_OPTIONS = {
    "layout": {
        "background": {"type": "solid", "color": SURFACE},
        "textColor": MUTED,
        "fontFamily": FONTE_MONO,
        "fontSize": 11,
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
