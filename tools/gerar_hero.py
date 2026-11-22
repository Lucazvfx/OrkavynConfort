"""Gera a paisagem do hero: chapadas em camadas + pasto, pontilhado P&B (Floyd–Steinberg)."""
import sys
import numpy as np
from PIL import Image

rng = np.random.default_rng(7)
W, H = 1800, 780
S = 2                      # pontilhado calculado em meia resolução e ampliado (grão visível)
w, h = W // S, H // S
x = np.linspace(0, 1, w)

def fbm1d(n, octaves=6, base=3.0, seed=0):
    r = np.random.default_rng(seed)
    out = np.zeros(n)
    t = np.linspace(0, 1, n)
    amp, freq = 1.0, base
    for _ in range(octaves):
        phase = r.uniform(0, 2 * np.pi, 3)
        out += amp * (np.sin(2*np.pi*freq*t + phase[0]) * 0.6 + np.sin(2*np.pi*freq*1.7*t + phase[1]) * 0.4)
        amp *= 0.5; freq *= 2.1
    return out

def fbm2d(shape, octaves=5, seed=1):
    r = np.random.default_rng(seed)
    out = np.zeros(shape)
    amp = 1.0
    for o in range(octaves):
        cell = max(2, int(64 / (2 ** o)))
        gh, gw = shape[0] // cell + 2, shape[1] // cell + 2
        g = r.random((gh, gw))
        img = Image.fromarray((g * 255).astype(np.uint8)).resize((gw * cell, gh * cell), Image.BICUBIC)
        out += amp * (np.asarray(img, dtype=float)[: shape[0], : shape[1]] / 255.0 - 0.5)
        amp *= 0.5
    return out

yy = np.linspace(0, 1, h)[:, None]
# céu noturno/crepúsculo: bem escuro em cima, leve claridade no horizonte
img = 0.04 + 0.30 * (yy ** 2.0) * np.ones((h, w))
img += 0.035 * fbm2d((h, w), 4, seed=3)

def mesa_profile(n, seed, n_mesas, rim, low, steep=60.0):
    """Topos planos (chapadas) com escarpas íngremes e vales entre elas."""
    r = np.random.default_rng(seed)
    t = np.linspace(0, 1, n)
    prof = np.full(n, low, dtype=float)
    centers = np.sort(r.uniform(0.05, 0.95, n_mesas))
    for c in centers:
        half = r.uniform(0.06, 0.16)
        edge = 1 / (1 + np.exp(-steep * (t - (c - half)))) * (1 / (1 + np.exp(steep * (t - (c + half)))))
        prof = np.minimum(prof, low - (low - rim) * edge)  # y menor = mais alto
    prof += 0.006 * fbm1d(n, 5, 14, seed + 7)            # irregularidade da borda
    return prof

layers = [  # (seed, nº chapadas, y do topo, y do vale, tom da face, brilho da escarpa, textura)
    (11, 5, 0.40, 0.54, 0.46, 0.20, 0.04),   # distante: clara, enevoada
    (12, 4, 0.49, 0.64, 0.27, 0.34, 0.07),
    (13, 3, 0.60, 0.76, 0.11, 0.48, 0.09),   # mais próxima: escura, borda bem iluminada
]
tex = fbm2d((h, w), 6, seed=21)
for seed, n_m, rim, low, tone, glow, tcon in layers:
    top = mesa_profile(w, seed, n_m, rim, low)
    topi = np.clip((top * h).astype(int), 0, h - 1)
    for c in range(w):
        t0 = topi[c]
        depth = np.linspace(0, 1, h - t0)
        # paredão iluminado logo abaixo da borda, escurecendo para a base
        shade = tone + glow * np.exp(-depth * 45) - 0.06 * depth
        img[t0:, c] = shade + tcon * tex[t0:, c]
    # névoa suave na linha de base da camada (só soma brilho numa faixa estreita)
    band = np.clip(1 - np.abs(yy - low) / 0.03, 0, 1) * 0.03
    img = img + band

# pasto em primeiro plano, escuro, com textura de capim
field_top = 0.86
F = yy >= field_top
grass = fbm2d((h, w), 6, seed=31)
field = 0.07 + 0.06 * (1 - (yy - field_top) / (1 - field_top)) + 0.16 * np.clip(grass, -0.18, 0.4)
img = np.where(F, field, img)

img = np.clip(img, 0, 1)
# pontilhado Floyd–Steinberg
a = img.copy()
for yv in range(h):
    for xv in range(w):
        old = a[yv, xv]
        new = 1.0 if old > 0.5 else 0.0
        a[yv, xv] = new
        err = old - new
        if xv + 1 < w: a[yv, xv + 1] += err * 7 / 16
        if yv + 1 < h:
            if xv > 0: a[yv + 1, xv - 1] += err * 3 / 16
            a[yv + 1, xv] += err * 5 / 16
            if xv + 1 < w: a[yv + 1, xv + 1] += err * 1 / 16
# 1 bit -> tons de cinza suaves (preto não absoluto, branco levemente apagado)
out = np.where(a > 0.5, 228, 14).astype(np.uint8)
Image.fromarray(out).resize((W, H), Image.NEAREST).convert("L").save(sys.argv[1], optimize=True)
print("ok", W, H)
