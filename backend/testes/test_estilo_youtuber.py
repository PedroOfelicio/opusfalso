"""
Testes do estilo "YouTuber de Roblox": legenda elástica, textos de impacto, zoom lento, risco branco,
facecam no canto e memes da pasta do usuário. Sem rede, sem GPU. Rodar de dentro de backend/:
    C:\\opusfalso-dados\\venv\\Scripts\\python.exe -m unittest discover -s testes -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import enfeites
import legendas
import memes
import pipeline
import planejador_local as local
import reenquadramento as rq
from modelos import Reacao


def _palavras(texto: str, inicio: float = 0.0, passo: float = 0.4) -> list[dict]:
    return [{"p": p, "i": round(inicio + k * passo, 2), "f": round(inicio + k * passo + 0.3, 2)}
            for k, p in enumerate(texto.split())]


class TextosDeImpacto(unittest.TestCase):
    def test_palavras_chave_viram_textos_com_estilo(self):
        pal = _palavras("cara corre que ele vai te pegar " + "bla " * 10 + "meu Deus ele foi banido")
        r = local.reacoes_por_palavras(pal, 0, 100)
        self.assertEqual([(x["texto"], x["estilo"]) for x in r], [("CORRE!!", "etiqueta"), ("MEU DEUS!", "impacto")])

    def test_espacadas_e_sem_repetir(self):
        pal = _palavras("corre corre corre preso")  # tudo em 1,6 s
        r = local.reacoes_por_palavras(pal, 0, 100)
        self.assertEqual([x["texto"] for x in r], ["CORRE!!"])

    def test_sem_palavra_chave_usa_o_pico(self):
        r = local.reacoes_por_palavras(_palavras("nada demais aqui"), 0, 100, pico=12.0)
        self.assertEqual(r, [{"t": 12.0, "texto": "QUE ISSO?!", "estilo": "impacto"}])
        self.assertEqual(local.reacoes_por_palavras(_palavras("nada"), 0, 100), [])

    def test_estilo_desconhecido_vira_padrao(self):
        self.assertIsNone(Reacao(t=1, texto="OI", estilo="explosivo").estilo)
        self.assertEqual(Reacao(t=1, texto="OI", estilo="Carimbo").estilo, "carimbo")

    def test_figurinhas_de_cada_estilo(self):
        for estilo in (*enfeites.ESTILOS_REACAO, 0, 1, None):
            fig = enfeites.figurinha_reacao("EXPOSED", 1080, estilo)
            self.assertEqual(fig.shape[2], 4, estilo)
            self.assertGreater((fig[:, :, 3] > 0).mean(), 0.1, estilo)
            self.assertLess(fig.shape[1], 1080, estilo)


class LegendaElastica(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ass_do_preset_roblox(self):
        est = legendas.estilo("roblox")
        pal = _palavras("today I'm going, trolling.")
        pal[3]["enfase"] = True
        arq = legendas.gerar_ass(pal, est, self.tmp / "l.ass", 1080, 1920, 5.0)
        texto = arq.read_text(encoding="utf-8-sig")
        dialogos = [l for l in texto.splitlines() if l.startswith("Dialogue: 0")]
        self.assertTrue(all(r"\fscx40\fscy40\blur4" in d for d in dialogos))   # todo grupo entra elástico
        self.assertIn("going,", texto)                                          # mantém a pontuação
        self.assertEqual(texto.count(r"\c&H"), 1)                               # só a palavra de ênfase colorida
        self.assertIn("{\\c&H0000D4FF}trolling.", texto)
        self.assertIn(",&H00000000,0,0,0,0,100,100,1,0,1,", texto)              # sombra dura (opaca)

    def test_outros_presets_continuam_iguais(self):
        est = legendas.estilo("hormozi")
        arq = legendas.gerar_ass(_palavras("isso muda tudo"), est, self.tmp / "h.ass", 1080, 1920, 3.0)
        texto = arq.read_text(encoding="utf-8-sig")
        self.assertNotIn(r"\blur4", texto)
        self.assertIn("&H96000000", texto)
        self.assertIn("MUDA", texto)


class ZoomETransicoes(unittest.TestCase):
    def test_zoom_lento_sobe_e_volta_no_corte(self):
        z = rq.zoom_por_frame(180, 30, [], deriva=[(0, 3), (3, 6)], forca_deriva=0.08)
        self.assertAlmostEqual(z[0], 1.0)
        self.assertTrue(np.all(np.diff(z[:90]) >= 0))
        self.assertGreater(z[89], 1.07)
        self.assertAlmostEqual(z[90], 1.0)  # novo trecho: volta ao enquadramento normal
        self.assertTrue(np.all(rq.zoom_por_frame(60, 30, [], deriva=[(0, 2)]) == 1.0))  # força 0 = desligado

    def test_risco_cruza_a_tela(self):
        q = np.zeros((1920, 1080, 3), np.uint8)
        brancos = [(rq._risco(q, p) == 255).all(axis=2).mean() for p in (0.0, 0.5, 1.0)]
        self.assertEqual(brancos[2], 0.0)
        self.assertGreater(brancos[1], 0.03)

    def test_blur_zoom_e_risco_nos_cortes(self):
        opc = rq.OpcoesRender(transicao="risco", cortes=[1.0])
        z = np.ones(90)
        ef = rq._efeitos_por_quadro(opc, 90, 30, z)
        self.assertEqual({v[0] for v in ef.values()}, {"risco"})
        opc = rq.OpcoesRender(transicao="blur_zoom", cortes=[1.0])
        ef = rq._efeitos_por_quadro(opc, 90, 30, z)
        self.assertGreater(z[30], 1.1)
        saida = rq._aplicar_efeito(np.random.randint(0, 255, (64, 36, 3), np.uint8), "blur_zoom", 1.0, 30)
        self.assertEqual(saida.shape, (64, 36, 3))

    def test_whoosh_nas_transicoes(self):
        com = pipeline._efeitos_sonoros("x", False, [], [], 20.0, cortes=[5.0, 12.0])
        sem = pipeline._efeitos_sonoros("x", False, [], [], 20.0)
        self.assertEqual(len(sem), 0)
        self.assertEqual([round(t, 2) for t, _, _ in com], [4.85, 11.85])


class FacecamNoCanto(unittest.TestCase):
    def test_pip_com_borda_colorida(self):
        frame = np.full((1080, 1920, 3), 90, np.uint8)
        frame[100:300, 100:300] = (0, 0, 255)  # "rosto" vermelho na facecam do canto
        LW, LH = 1080, 1920
        n = 1
        cx, cy, z = np.array([960.0]), np.array([540.0]), np.ones(n)
        q = rq._compor(frame, "pip", 0, LW, LH, LW / LH, cx, cy, z, (200, 200, 120, 120), None, None,
                       rq._hex_bgr("#1EA7FF"))
        self.assertEqual(q.shape, (LH, LW, 3))
        alto = int(min(LH, LW * 1.25))
        y = int((LH - alto) * 0.45) + int(LH * 0.06)
        x = int(LW * 0.035)
        self.assertEqual(tuple(q[y + 1, x + 100]), rq._hex_bgr("#1EA7FF"))  # borda
        pw, ph = int(LW * 0.36) // 2 * 2, int(int(LW * 0.36) // 2 * 2 * 0.8) // 2 * 2
        self.assertEqual(tuple(q[y + ph // 2, x + pw // 2]), (0, 0, 255))   # rosto dentro do quadro


class PastaDeMemes(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        img = np.zeros((100, 200, 4), np.uint8)
        img[20:80, 50:150] = (0, 200, 0, 255)
        cv2.imwrite(str(self.pasta / "rindo_kkk.png"), img)
        (self.pasta / "susto").mkdir()
        (self.pasta / "susto" / "qualquer.mp4").write_bytes(b"x")
        (self.pasta / "LEIAME.txt").write_text("ignorar")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_lista_pelo_nome_e_subpasta(self):
        itens = {Path(m["arquivo"]).name: m for m in memes.listar(self.pasta)}
        self.assertEqual(set(itens), {"rindo_kkk.png", "qualquer.mp4"})
        self.assertEqual(itens["rindo_kkk.png"]["palavras"], ["kkk", "rindo"])
        self.assertIn("susto", itens["qualquer.mp4"]["palavras"])
        self.assertEqual(itens["qualquer.mp4"]["tipo"], "video")

    def test_escolhe_pelas_palavras_do_clipe(self):
        pal = _palavras("ele levou um SUSTO e eu fiquei rindo muito", inicio=2.0, passo=1.0)
        r = memes.escolher(pal, "p/c", duracao=30, pasta=self.pasta)
        self.assertEqual([(t, Path(a).name, tipo) for t, a, tipo in r],
                         [(5.0, "qualquer.mp4", "video"), (9.0, "rindo_kkk.png", "imagem")])
        self.assertEqual(memes.escolher(pal, "p/c", duracao=30, pasta=self.pasta / "vazia"), [])

    def test_figurinha_com_contorno_branco(self):
        fig = memes.figurinha(str(self.pasta / "rindo_kkk.png"), 1080)
        self.assertEqual(fig.shape[2], 4)
        self.assertLessEqual(fig.shape[1], int(1080 * 0.55) + 2 * 9 + 2)
        self.assertTrue((fig[:, :, :3] == 255).all(axis=2).any())  # contorno branco


if __name__ == "__main__":
    unittest.main()
