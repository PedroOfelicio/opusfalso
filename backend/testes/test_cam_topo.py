"""
Testes do formato pessoal: webcam em cima e gameplay embaixo ("cam_topo"), com o retângulo da webcam marcado em
Configurações, e dos textos de publicação do modo volume (Claude simulado). Sem rede. Rodar de dentro de backend/:
    C:\\opusfalso-dados\\venv\\Scripts\\python.exe -m unittest discover -s testes -v
"""
import unittest
from unittest import mock

import numpy as np

import config
import pipeline
import planejador_llm as llm
import reenquadramento as rq
from modelos import Corte, RespostaTextos


def _com_webcam(regiao):
    return mock.patch.object(config, "carregar", return_value={**config.PADRAO, "webcam": regiao})


class Webcam(unittest.TestCase):
    def test_retangulo_marcado_em_pixels(self):
        with _com_webcam({"x": 0.75, "y": 0.7, "w": 0.25, "h": 0.3}):
            self.assertEqual(rq.webcam_marcada(1920, 1080), (1440, 756, 1920, 1080))
        with _com_webcam(None):
            self.assertIsNone(rq.webcam_marcada(1920, 1080))
        with _com_webcam({"x": 0.5}):  # incompleto
            self.assertIsNone(rq.webcam_marcada(1920, 1080))

    def test_layout_automatico_no_gameplay(self):
        analise = rq.Analise(largura=1920, altura=1080, fps=30, total_frames=30, tempos=[0.0], trilhas=[])
        opc = rq.OpcoesRender(modo="gameplay")
        with _com_webcam({"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.25}):
            self.assertEqual(rq.escolher_layout(opc, analise), "cam_topo")
            self.assertEqual(pipeline._layout_previsto(opc, analise), "cam_topo")
        with _com_webcam(None):  # sem webcam marcada nem facecam achada: gameplay em destaque
            self.assertEqual(rq.escolher_layout(opc, analise), "jogo")
            self.assertEqual(pipeline._layout_previsto(rq.OpcoesRender(modo="gameplay", layout="cam_topo"), analise),
                             "jogo")

    def test_quadro_tem_cam_em_cima_e_jogo_embaixo(self):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[:, :] = (0, 0, 255)               # jogo vermelho
        frame[800:1080, 1500:1920] = (255, 0, 0)  # webcam azul no canto de baixo à direita
        quadro = rq.quadro_cam_topo(frame, ("marcada", (1500, 800, 1920, 1080)), 1080, 1920, borda=(255, 255, 255))
        self.assertEqual(quadro.shape, (1920, 1080, 3))
        alto_cam = int(1920 * rq.FRACAO_CAM) // 2 * 2
        self.assertEqual(tuple(quadro[alto_cam // 2, 540]), (255, 0, 0))     # em cima, a webcam
        self.assertEqual(tuple(quadro[1500, 540]), (0, 0, 255))               # embaixo, o centro do jogo
        self.assertEqual(tuple(quadro[alto_cam, 540]), (255, 255, 255))      # faixa na divisa


class TextosVolume(unittest.TestCase):
    def test_claude_escreve_os_textos_e_respeita_o_clipe(self):
        cortes = [Corte(inicio=10, fim=40, titulo="Momento 1"), Corte(inicio=50, fim=80, titulo="Momento 2")]
        resposta = RespostaTextos.model_validate({"clipes": [
            {"id": 0, "titulo": "I can't believe this worked", "legenda_post": "Would you try it?",
             "hashtags": ["#roblox"], "reacoes": [{"t": 20, "texto": "NO WAY"}, {"t": 11, "texto": "CEDO DEMAIS"}]},
            {"id": 1, "titulo": "", "reacoes": [{"t": 60, "texto": "TEXTO LONGO DEMAIS PARA A TELA"}]},
        ]})
        transcricao = {"palavras": [], "segmentos": []}
        with mock.patch.object(llm, "textos_clipes", return_value=resposta) as chamada:
            pipeline._textos_volume(cortes, transcricao, {"nome": "obby"}, "pid", lambda *a: None)
        self.assertEqual(chamada.call_count, 1)
        self.assertEqual(cortes[0].titulo, "I can't believe this worked")
        self.assertEqual(cortes[0].legenda_post, "Would you try it?")
        self.assertEqual([r.texto for r in cortes[0].reacoes], ["NO WAY"])  # 11 s cai nos 4 s iniciais
        self.assertEqual(cortes[1].titulo, "Momento 2")                       # título vazio: fica o local
        self.assertEqual(cortes[1].reacoes, [])                               # reação inválida descartada

    def test_falha_do_claude_mantem_titulos_locais(self):
        cortes = [Corte(inicio=10, fim=40, titulo="Momento 1")]
        with mock.patch.object(llm, "textos_clipes", side_effect=llm.ErroClaude("sem créditos")), \
                mock.patch.object(pipeline, "_aviso") as aviso:
            pipeline._textos_volume(cortes, {"palavras": [], "segmentos": []}, {"nome": "x"}, "pid", lambda *a: None)
        self.assertEqual(cortes[0].titulo, "Momento 1")
        aviso.assert_called_once()

    def test_regra_de_idioma_no_prompt(self):
        with mock.patch.object(config, "carregar", return_value={**config.PADRAO, "idioma_post": "en"}):
            self.assertIn("inglês", llm._regra_idioma("titulo"))
        with mock.patch.object(config, "carregar", return_value={**config.PADRAO, "idioma_post": ""}):
            self.assertEqual(llm._regra_idioma("titulo"), "")


if __name__ == "__main__":
    unittest.main()
