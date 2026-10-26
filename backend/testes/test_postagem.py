"""
Testes da fila de postagem nos canais (sem a API do YouTube): distribuição em serpentina, nenhum clipe em dois
canais, pasta com nome de arquivo = título e marcar como postado. Sem rede. Rodar de dentro de backend/:
    C:\\opusfalso-dados\\venv\\Scripts\\python.exe -m unittest discover -s testes -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import postagem


class Distribuicao(unittest.TestCase):
    def test_serpentina_equilibra_os_canais(self):
        canais = [{"id": "a", "por_dia": 2}, {"id": "b", "por_dia": 2}, {"id": "c", "por_dia": 2}]
        r = postagem.distribuir([f"k{i}" for i in range(1, 8)], canais)
        self.assertEqual(r, {"a": ["k1", "k6"], "b": ["k2", "k5"], "c": ["k3", "k4"]})  # k7 sobra

    def test_por_dia_diferente_e_poucos_clipes(self):
        canais = [{"id": "a", "por_dia": 1}, {"id": "b", "por_dia": 3}]
        self.assertEqual(postagem.distribuir(["1", "2", "3"], canais), {"a": ["1"], "b": ["2", "3"]})
        self.assertEqual(postagem.distribuir([], canais), {"a": [], "b": []})


class NomesELinks(unittest.TestCase):
    def test_nome_do_arquivo_vira_o_titulo(self):
        usados = set()
        self.assertEqual(postagem.nome_arquivo('He did WHAT?! "no way" 1/2', usados),
                         "He did WHAT？! ''no way'' 1／2.mp4")
        self.assertEqual(postagem.nome_arquivo("Same", usados), "Same.mp4")
        self.assertEqual(postagem.nome_arquivo("same", usados), "same (2).mp4")
        self.assertEqual(postagem.nome_arquivo("", usados), "short.mp4")

    def test_id_do_canal_pelo_link(self):
        uc = "UC" + "a1B2c3D4e5F6g7H8i9J0kL"
        self.assertEqual(postagem.id_do_canal(f"https://www.youtube.com/channel/{uc}"), uc)
        self.assertIsNone(postagem.id_do_canal("qualquer coisa"))
        self.assertIn(uc, postagem.url_studio({"channel_id": uc}))
        self.assertEqual(postagem.url_studio({"channel_id": None}), "https://studio.youtube.com/")

    def test_descricao_sempre_com_shorts(self):
        self.assertEqual(postagem.descricao({"legenda_post": "Olha isso", "hashtags": ["roblox", "#Shorts"]}),
                         "Olha isso\n\n#roblox #Shorts")
        self.assertEqual(postagem.descricao({}), "#shorts")


class FilaDoDia(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="postagem_teste_"))
        metas = []
        for p in range(2):
            clips = []
            for c in range(3):
                arq = self.tmp / f"p{p}c{c}.mp4"
                arq.write_bytes(b"video")
                clips.append({"id": f"clip_0{c}", "status": "pronto", "arquivo": str(arq), "nota": 90 - 10 * c - p,
                              "titulo": f"Titulo {p}{c}", "hashtags": ["roblox"]})
            clips.append({"id": "clip_09", "status": "erro", "arquivo": None})
            metas.append({"id": f"proj{p}aaaaaa", "tipo": "curto", "nome": f"P{p}", "criado_em": p, "clips": clips})
        metas.append({"id": "longoaaaaaaa", "tipo": "longo", "nome": "L", "clips": [
            {"id": "clip_01", "status": "pronto", "arquivo": str(self.tmp / "p0c0.mp4"), "nota": 99}]})
        self.patches = [mock.patch.object(postagem, "ARQ", self.tmp / "postagem.json"),
                        mock.patch.object(postagem, "PASTA", self.tmp / "postar"),
                        mock.patch.object(postagem.projetos, "listar", return_value=metas)]
        for p in self.patches:
            p.start()
        for nome in ("A", "B"):
            postagem.salvar_canal({"nome": nome, "url": "", "por_dia": 2})

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fila_pasta_e_postado(self):
        e = postagem.montar_fila()
        chaves = [[c["chave"] for c in i["clips"]] for i in e["fila"]]
        self.assertEqual(len(e["fila"]), 2)
        todos = sum(chaves, [])
        self.assertEqual(len(todos), len(set(todos)))                 # nenhum clipe em dois canais
        self.assertNotIn("longoaaaaaaa/clip_01", todos)               # vídeo longo não entra
        self.assertEqual(chaves[0][0], "proj0aaaaaa/clip_00")         # o melhor vai para o 1º canal
        self.assertEqual(e["disponiveis"], 2)

        canal_a = e["fila"][0]["canal"]["id"]
        pasta = postagem.preparar_pasta(canal_a)
        nomes = sorted(p.name for p in pasta.glob("*.mp4"))
        self.assertEqual(len(nomes), 2)
        self.assertTrue(all(n.startswith("Titulo") for n in nomes))
        self.assertIn("#shorts", (pasta / "descricoes.txt").read_text(encoding="utf-8-sig"))

        e = postagem.marcar_postado(canal_a)
        self.assertFalse(pasta.exists())
        self.assertEqual(e["postados_total"], 2)
        e = postagem.montar_fila()                                    # refazer não mexe no canal já postado
        self.assertEqual([c["chave"] for c in e["fila"][0]["clips"]], chaves[0])
        self.assertTrue(e["fila"][0]["postado"])
        self.assertNotIn(chaves[0][0], sum([[c["chave"] for c in i["clips"]] for i in e["fila"][1:]], []))

    def test_pular_tira_da_fila_para_sempre(self):
        e = postagem.montar_fila()
        chave = e["fila"][0]["clips"][0]["chave"]
        postagem.pular(chave)
        e = postagem.montar_fila()
        self.assertNotIn(chave, [c["chave"] for i in e["fila"] for c in i["clips"]])
        self.assertEqual(e["postados_total"], 0)  # pulado não conta como postado
