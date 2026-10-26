"""
Testes do modo volume (o vídeo inteiro em clipes curtos diferentes): pedaços sem sobreposição, na duração pedida,
sem cortar palavra, tela parada fora e notas espalhadas. Sem rede, sem GPU. Rodar de dentro de backend/:
    C:\\opusfalso-dados\\venv\\Scripts\\python.exe -m unittest discover -s testes -v
"""
import unittest
from unittest import mock

import volume


def _fala(inicio: float, fim: float, passo: float = 0.5, pausa_a_cada: int = 12) -> list[dict]:
    """Palavras de 0,4 s com uma pausa de 0,6 s (e ponto final) a cada `pausa_a_cada` palavras."""
    palavras, t, k = [], inicio, 0
    while t + 0.4 < fim:
        k += 1
        fim_frase = k % pausa_a_cada == 0
        palavras.append({"p": "palavra." if fim_frase else "palavra", "i": round(t, 2), "f": round(t + 0.4, 2)})
        t += passo + (0.6 if fim_frase else 0)
    return palavras


class Fatiar(unittest.TestCase):
    def test_pedacos_seguidos_na_duracao_e_em_pausas(self):
        palavras = _fala(0, 300)
        pedacos = volume.fatiar((0.0, 300.0), palavras, [50] * 300, 15, 30)
        self.assertEqual(pedacos[0][0], 0.0)
        for (a, b), (c, _) in zip(pedacos, pedacos[1:]):
            self.assertEqual(b, c)                       # seguidos, sem buraco nem sobreposição
        for a, b in pedacos[:-1]:
            self.assertTrue(15 <= b - a <= 30, (a, b))
            self.assertFalse(any(w["i"] < b < w["f"] for w in palavras), b)  # nunca no meio de palavra
        self.assertGreaterEqual(pedacos[-1][1], 290)     # a sobra vai para o último

    def test_trecho_curto_demais_nao_vira_clipe(self):
        self.assertEqual(volume.fatiar((10.0, 20.0), [], [0] * 30, 15, 30), [])
        self.assertEqual(volume.fatiar((10.0, 35.0), [], [0] * 40, 15, 30), [(10.0, 35.0)])


class TelaParada(unittest.TestCase):
    def test_quadros_iguais_por_4s_saem(self):
        mov = [[0.0, 99.0], [2.0, 30.0], [4.0, 0.5], [6.0, 0.4], [8.0, 0.3], [10.0, 25.0], [12.0, 0.2], [14.0, 40.0]]
        self.assertEqual(volume.trechos_parados(mov, 20.0), [(2.0, 8.0)])  # 12 s sozinho dura só 2 s: fica

    def test_quadros_chave_espacados_nao_contam_como_parado(self):
        mov = [[0.0, 99.0], [4.0, 35.0], [8.0, 41.0], [12.0, 38.0]]
        self.assertEqual(volume.trechos_parados(mov, 12.0), [])


class VideoInteiro(unittest.TestCase):
    def test_cortes_sem_repetir_com_notas_espalhadas(self):
        duracao = 600.0
        palavras = _fala(0, 200) + _fala(260, 600)                   # 200-260 s: ninguém fala
        curva = [80 if 400 <= s < 430 else 30 for s in range(600)]     # um lance forte em 400-430 s
        analise = {"duracao": duracao, "curva": curva, "ataques": [0] * 600}
        mov = [[t, 0.3 if 100 <= t <= 140 else 20.0] for t in range(0, 600, 2)]  # tela parada em 100-140 s
        with mock.patch.object(volume, "movimento", return_value=mov):
            cs = volume.cortes("x.mp4", {"palavras": palavras}, analise, 15, 30)
        intervalos = sorted((c.inicio, c.fim) for c in cs)
        self.assertFalse(any(b[0] < a[1] - 0.01 for a, b in zip(intervalos, intervalos[1:])))
        self.assertFalse(any(a < 130 < b for a, b in intervalos))     # a tela parada ficou de fora
        self.assertGreater(len(cs), 15)
        self.assertEqual(cs[0].nota, 98)                               # ordenados do melhor ao pior
        self.assertEqual(cs[-1].nota, 20)
        self.assertTrue(400 <= cs[0].pico <= 430)                      # o melhor é o do lance forte
        self.assertTrue(all(c.gancho and c.inicio <= c.gancho[0] < c.gancho[1] <= c.fim for c in cs))
        self.assertTrue(all(c.titulo for c in cs))
