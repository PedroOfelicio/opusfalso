"""
Testes da aba Métricas (YouTube Data API simulada, sem rede): retrato do dia, duração, tipo short/longo, ligação
com a aba Prontos pelo título e marcar como postado o que já está no canal. Rodar de dentro de backend/:
    C:\\opusfalso-dados\\venv\\Scripts\\python.exe -m unittest discover -s testes -v
"""
import base64
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import metricas

UC = "UC" + "a1B2c3D4e5F6g7H8i9J0kL"


def _api_falsa(rota, **params):
    if rota == "channels":
        return {"items": [{"id": UC, "snippet": {"title": "Meu canal", "thumbnails": {}},
                           "statistics": {"subscriberCount": "1200", "viewCount": "50000", "videoCount": "3"},
                           "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]}
    if rota == "playlistItems":
        return {"items": [{"contentDetails": {"videoId": v}} for v in ("v1", "v2", "v3")]}
    if rota == "videos":
        return {"items": [
            {"id": "v1", "snippet": {"title": "I can't believe this worked？", "publishedAt": "2026-10-30T12:00:00Z"},
             "statistics": {"viewCount": "900", "likeCount": "40", "commentCount": "3"}, "contentDetails": {"duration": "PT28S"}},
            {"id": "v2", "snippet": {"title": "Full gameplay", "publishedAt": "2026-10-20T12:00:00Z"},
             "statistics": {"viewCount": "300"}, "contentDetails": {"duration": "PT1H2M5S"}},
            {"id": "v3", "snippet": {"title": "Not from the app", "publishedAt": "2026-10-31T12:00:00Z"},
             "statistics": {"viewCount": "10"}, "contentDetails": {"duration": "PT59S"}},
        ]}
    raise AssertionError(rota)


class Metricas(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="metricas_teste_"))
        self.prontos = [
            {"chave": "p1/clip_01", "titulo": "I can't believe this worked?", "estado": "pendente", "projeto": "P", "nota": 90},
            {"chave": "p1/clip_02", "titulo": "Another one", "estado": "pendente", "projeto": "P", "nota": 70},
        ]
        self.patches = [
            mock.patch.object(metricas, "ARQ", self.tmp / "metricas.json"),
            mock.patch.object(metricas, "ARQ_TOKEN", self.tmp / "token.json"),
            mock.patch.object(metricas, "ARQ_CLIENTE", self.tmp / "cliente.json"),
            mock.patch.object(metricas, "_get", side_effect=_api_falsa),
            mock.patch.object(metricas, "chave", return_value="AIza-teste"),
            mock.patch.object(metricas.postagem, "_ler", return_value={"canal": {"url": "x", "channel_id": UC}}),
            mock.patch.object(metricas.postagem, "itens", side_effect=lambda: [dict(i) for i in self.prontos]),
            mock.patch.object(metricas.postagem, "marcar", side_effect=self._marcar),
        ]
        for p in self.patches:
            p.start()

    def _marcar(self, chave, estado):
        next(i for i in self.prontos if i["chave"] == chave)["estado"] = estado

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_duracao_iso(self):
        self.assertEqual(metricas.segundos("PT1H2M5S"), 3725)
        self.assertEqual(metricas.segundos("PT28S"), 28)
        self.assertEqual(metricas.segundos("P1DT1S"), 86401)
        self.assertEqual(metricas.segundos(""), 0)

    def test_retrato_e_ligacao_com_prontos(self):
        metricas.atualizar()
        e = metricas.estado()
        self.assertEqual(e["canal"]["inscritos"], 1200)
        self.assertEqual(e["serie"], [{"dia": date.today().isoformat(), "inscritos": 1200, "views": 50000}])
        por_id = {v["id"]: v for v in e["videos"]}
        self.assertEqual([v["id"] for v in e["videos"]], ["v3", "v1", "v2"])  # mais novos primeiro
        self.assertEqual((por_id["v1"]["tipo"], por_id["v2"]["tipo"]), ("short", "longo"))
        self.assertEqual(por_id["v1"]["app"]["chave"], "p1/clip_01")         # "？" do nome do arquivo bate com "?"
        self.assertIsNone(por_id["v3"]["app"])
        self.assertEqual(por_id["v1"]["historico"], {date.today().isoformat(): 900})
        self.assertEqual(e["pendentes_no_ar"], 1)

        self.assertEqual(metricas.marcar_publicados(), 1)
        self.assertEqual(self.prontos[0]["estado"], "postado")
        self.assertEqual(self.prontos[1]["estado"], "pendente")
        self.assertEqual(metricas.estado()["pendentes_no_ar"], 0)

    def test_erro_fica_guardado_sem_derrubar(self):
        with mock.patch.object(metricas, "_get", side_effect=metricas.ErroYoutube("Cota esgotada")):
            metricas.atualizar_se_preciso()  # automático: não levanta
            self.assertEqual(metricas.estado()["erro"], "Cota esgotada")
            with self.assertRaises(metricas.ErroYoutube):
                metricas.atualizar_se_preciso(forcar=True)


    def _cliente_oauth(self, tipo="installed"):
        arq = self.tmp / "client_secret_teste.json"
        arq.write_text(json.dumps({tipo: {"client_id": "id.apps", "client_secret": "segredo", "redirect_uris": ["http://localhost"],
                                          "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                          "token_uri": "https://oauth2.googleapis.com/token"}}), encoding="utf-8")
        return arq

    def test_cliente_oauth_precisa_ser_desktop(self):
        with self.assertRaises(metricas.ErroYoutube):
            metricas.salvar_cliente(str(self._cliente_oauth("web")))
        metricas.salvar_cliente(str(self._cliente_oauth()))
        self.assertEqual(metricas.cliente()["client_id"], "id.apps")
        self.assertFalse(metricas.conectado())

    def test_login_pkce_troca_codigo_e_renova(self):
        metricas.salvar_cliente(str(self._cliente_oauth()))
        url = metricas.url_login("http://localhost:8000/api/metricas/oauth/retorno")
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["access_type"], ["offline"])
        self.assertIn("yt-analytics.readonly", q["scope"][0])
        with self.assertRaises(metricas.ErroYoutube):
            metricas.concluir_login("codigo", "estado-errado")

        respostas = [{"access_token": "a1", "refresh_token": "r1", "expires_in": 3600},
                     {"access_token": "a2", "expires_in": 3600}]
        with mock.patch.object(metricas, "_post_token", side_effect=respostas) as post:
            metricas.concluir_login("codigo", q["state"][0])
            verificador = post.call_args_list[0].args[0]["code_verifier"]
            desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
            self.assertEqual(desafio, q["code_challenge"][0])  # PKCE: o verificador bate com o desafio da URL
            self.assertTrue(metricas.conectado())
            self.assertEqual(metricas._token_acesso(), "a1")
            t = json.loads((self.tmp / "token.json").read_text(encoding="utf-8"))
            t["expira"] = 0  # venceu: renova com o refresh_token
            (self.tmp / "token.json").write_text(json.dumps(t), encoding="utf-8")
            self.assertEqual(metricas._token_acesso(), "a2")
            self.assertEqual(post.call_args_list[1].args[0], {"refresh_token": "r1", "grant_type": "refresh_token"})

    def test_com_login_busca_analytics_pelo_canal_da_conta(self):
        def api(rota, **params):
            if rota.startswith("http"):  # Analytics
                if params["dimensions"] == "day":
                    return {"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": [["2026-10-30", 120], ["2026-10-31", 80]]}
                return {"columnHeaders": [{"name": "video"}, {"name": "views"}, {"name": "averageViewPercentage"}],
                        "rows": [["v1", 900, 87.5]]}
            if rota == "channels":
                self.assertEqual(params.get("mine"), "true")  # com login não precisa do link
                r = _api_falsa(rota)
                r["items"][0]["id"] = UC
                return r
            return _api_falsa(rota, **params)
        with mock.patch.object(metricas, "conectado", return_value=True), mock.patch.object(metricas, "_get", side_effect=api), \
                mock.patch.object(metricas.postagem, "_ler", return_value={"canal": {"url": "", "channel_id": None}}), \
                mock.patch.object(metricas.postagem, "salvar_canal") as salvar:
            metricas.atualizar()
        salvar.assert_called_once_with(f"https://www.youtube.com/channel/{UC}")
        a = metricas.estado()["analytics"]
        self.assertEqual(a["dias"], [{"day": "2026-10-30", "views": 120}, {"day": "2026-10-31", "views": 80}])
        self.assertEqual(a["videos"]["30"]["v1"], {"views": 900, "averageViewPercentage": 87.5})
        self.assertEqual(sorted(a["videos"]), ["0", "30", "7", "90"])


if __name__ == "__main__":
    unittest.main()
