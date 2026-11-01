"""
Testes da aba Prontos (um canal, sem a API do YouTube): lista dos cortes e vídeos longos prontos, ordem, marcar
postado/descartado, editar título e descrição e pasta com nome de arquivo = título. Sem rede. Rodar de dentro de
backend/:
    C:\\opusfalso-dados\\venv\\Scripts\\python.exe -m unittest discover -s testes -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import postagem


class NomesELinks(unittest.TestCase):
    def test_nome_do_arquivo_vira_o_titulo(self):
        usados = set()
        self.assertEqual(postagem.nome_arquivo('He did WHAT?! "no way" 1/2', usados),
                         "He did WHAT？! ''no way'' 1／2.mp4")
        self.assertEqual(postagem.nome_arquivo("Same", usados), "Same.mp4")
        self.assertEqual(postagem.nome_arquivo("same", usados), "same (2).mp4")
        self.assertEqual(postagem.nome_arquivo("", usados), "video.mp4")

    def test_id_do_canal_pelo_link(self):
        uc = "UC" + "a1B2c3D4e5F6g7H8i9J0kL"
        self.assertEqual(postagem.id_do_canal(f"https://www.youtube.com/channel/{uc}"), uc)
        self.assertIsNone(postagem.id_do_canal("qualquer coisa"))
        self.assertIn(uc, postagem.url_studio({"channel_id": uc}))
        self.assertEqual(postagem.url_studio({"channel_id": None}), "https://studio.youtube.com/")

    def test_descricao_sempre_com_shorts(self):
        self.assertEqual(postagem.descricao({"legenda_post": "Look at this", "hashtags": ["roblox", "#Shorts"]}),
                         "Look at this\n\n#roblox #Shorts")
        self.assertEqual(postagem.descricao({}), "#shorts")


class Prontos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prontos_teste_"))
        metas = []
        for p in range(2):
            clips = []
            for c in range(3):
                arq = self.tmp / f"p{p}c{c}.mp4"
                arq.write_bytes(b"video")
                capa = self.tmp / f"p{p}c{c}_capa.jpg"
                capa.write_bytes(b"jpg")
                clips.append({"id": f"clip_0{c}", "status": "pronto", "arquivo": str(arq), "capa": str(capa),
                              "nota": 70 + 10 * c, "titulo": f"Title {p}{c}", "hashtags": ["roblox"],
                              "legenda_post": "Would you do it?"})
            clips.append({"id": "clip_09", "status": "erro", "arquivo": None})
            clips.append({"id": "clip_08", "status": "pronto", "arquivo": str(self.tmp / "sumiu.mp4")})
            metas.append({"id": f"proj{p}aaaaaa", "tipo": "curto", "nome": f"P{p}", "criado_em": p, "clips": clips})
        longo = self.tmp / "longo.mp4"
        longo.write_bytes(b"video")
        thumbs = []
        for k in range(3):
            t = self.tmp / f"longo_{k}.jpg"
            t.write_bytes(b"jpg")
            thumbs.append(str(t))
        metas.append({"id": "longoaaaaaaa", "tipo": "longo", "nome": "L", "criado_em": 1, "longo": {
            "arquivo": str(longo), "thumbs": thumbs, "titulos": ["Best title", "Other"], "tags": ["roblox", "obby game"],
            "descricao_completa": "A long video.\n\nChapters:\n0:00 Start"}})
        self.patches = [mock.patch.object(postagem, "ARQ", self.tmp / "postagem.json"),
                        mock.patch.object(postagem, "PASTA", self.tmp / "postar"),
                        mock.patch.object(postagem.projetos, "listar", return_value=metas)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lista_e_ordem(self):
        e = postagem.estado()
        chaves = [i["chave"] for i in e["itens"]]
        # mais novos primeiro; no mesmo projeto, o longo antes e os curtos pela nota
        self.assertEqual(chaves, ["longoaaaaaaa", "proj1aaaaaa/clip_02", "proj1aaaaaa/clip_01", "proj1aaaaaa/clip_00",
                                  "proj0aaaaaa/clip_02", "proj0aaaaaa/clip_01", "proj0aaaaaa/clip_00"])
        self.assertEqual(e["contagem"], {"pendente": 7, "postado": 0, "descartado": 0})
        longo = e["itens"][0]
        self.assertEqual(longo["titulo"], "Best title")
        self.assertIn("#roblox #obbygame", longo["descricao"])
        self.assertEqual(len(longo["thumbs_url"]), 3)
        self.assertNotIn("arquivo", longo)  # caminhos internos não vão para a interface
        self.assertIn("/capa", e["itens"][1]["thumbs_url"][0])

    def test_marcar_e_editar(self):
        postagem.marcar("proj0aaaaaa/clip_00", "postado")
        e = postagem.marcar("proj0aaaaaa/clip_01", "descartado")
        self.assertEqual(e["contagem"], {"pendente": 5, "postado": 1, "descartado": 1})
        e = postagem.marcar("proj0aaaaaa/clip_00", "pendente")
        self.assertEqual(e["contagem"]["postado"], 0)
        with self.assertRaises(ValueError):
            postagem.marcar("proj0aaaaaa/clip_00", "talvez")
        with self.assertRaises(KeyError):
            postagem.marcar("proj0aaaaaa/clip_08", "postado")  # arquivo sumiu: não está pronto

        e = postagem.editar_textos("proj1aaaaaa/clip_02", "New title", "New text #shorts")
        item = next(i for i in e["itens"] if i["chave"] == "proj1aaaaaa/clip_02")
        self.assertEqual((item["titulo"], item["descricao"], item["editado"]), ("New title", "New text #shorts", True))
        e = postagem.editar_textos("proj1aaaaaa/clip_02", "")  # título vazio volta ao do projeto
        item = next(i for i in e["itens"] if i["chave"] == "proj1aaaaaa/clip_02")
        self.assertEqual(item["titulo"], "Title 12")

    def test_pasta_com_nome_do_titulo(self):
        pasta = postagem.preparar_pasta("proj0aaaaaa/clip_02")
        self.assertEqual(sorted(p.name for p in pasta.iterdir()), ["Title 02.mp4", "descricao.txt", "thumbnail.jpg"])
        self.assertIn("#shorts", (pasta / "descricao.txt").read_text(encoding="utf-8-sig"))
        postagem.marcar("proj0aaaaaa/clip_02", "postado")
        self.assertFalse(pasta.exists())  # postado: a pasta some

        pasta = postagem.preparar_pasta("longoaaaaaaa")
        nomes = sorted(p.name for p in pasta.iterdir())
        self.assertEqual(nomes, ["Best title.mp4", "descricao.txt", "thumbnail_1.jpg", "thumbnail_2.jpg",
                                 "thumbnail_3.jpg"])
        self.assertIn("TAGS\nroblox, obby game", (pasta / "descricao.txt").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
