"""
Testes rápidos das partes delicadas: cortes na grade de quadros, mapeamento de tempos, correções da
transcrição, capítulos, respostas do Claude guardadas, "continuar de onde parou", textos do post,
biblioteca de áudio e as travas que impedem apagar/servir arquivo fora do lugar.

Não usam rede nem GPU e não chamam o Claude. Rodar de dentro de backend/:
    C:\\opusfalso-dados\\venv\\Scripts\\python.exe -m unittest discover -s testes -v
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import biblioteca_audio as bib
import config
import editor_ffmpeg as ef
import longo
import pipeline
import planejador_llm as llm
import projetos
from modelos import Corte, Correcoes, hashtags_validas, intervalos_validos, texto_post_valido


class Temporario(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="clipador_teste_"))

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)


# ---------------------------------------------------------------- tempos e cortes

class GradeDeQuadros(unittest.TestCase):
    def test_arredonda_para_a_grade_de_30_fps(self):
        self.assertAlmostEqual(ef.na_grade(1.016), 1.0)
        self.assertAlmostEqual(ef.na_grade(1.02), 31 / 30)

    def test_descarta_trecho_menor_que_um_quadro(self):
        self.assertEqual(ef.trechos_na_grade([(0.0, 0.01), (1.0, 2.0)]), [(1.0, 2.0)])

    def test_selecao_pega_exatamente_os_quadros_do_trecho(self):
        # quadros k/30 com 1,0 <= t < 2,0: 30 quadros, nem um a mais, nem um a menos
        expr = ef._expr_trechos([(1.0, 2.0)], 0.0)
        a, b = (float(x) for x in expr[len("between(t,"):-1].split(","))
        quadros = [k for k in range(120) if a <= k / 30 <= b]
        self.assertEqual(quadros, list(range(30, 60)))

    def test_mapear_intervalo_com_abertura_repetida(self):
        partes = [(15.0, 17.0), (8.0, 20.0)]  # teaser 15-17 antes do corpo 8-20
        self.assertEqual(ef.mapear_intervalo(15.5, 16.0, partes), [(0.5, 1.0), (9.5, 10.0)])
        self.assertEqual(ef.mapear_intervalo(10.0, 12.0, [(0.0, 5.0), (8.0, 20.0)]), [(7.0, 9.0)])

    def test_subtrair_remove_e_descarta_sobras_minusculas(self):
        self.assertEqual(pipeline._subtrair([(0.0, 30.0)], [(10.0, 12.0)]), [(0.0, 10.0), (12.0, 30.0)])
        self.assertEqual(pipeline._subtrair([(0.0, 30.0)], [(0.1, 5.0)]), [(5.0, 30.0)])
        # sobraria menos de 3 s: mantém o original
        self.assertEqual(pipeline._subtrair([(0.0, 4.0)], [(1.0, 3.9)]), [(0.0, 4.0)])


PALAVRAS = [{"p": "meu", "i": 1.0, "f": 1.2}, {"p": "jeep", "i": 1.2, "f": 1.5},
            {"p": "cara", "i": 1.6, "f": 1.9}, {"p": "meu", "i": 2.0, "f": 2.2}, {"p": "jeep!", "i": 2.2, "f": 2.6}]


class Transcricao(unittest.TestCase):
    def test_correcao_no_clipe_troca_a_primeira_ocorrencia(self):
        r = pipeline._aplicar_correcoes(PALAVRAS, [{"de": "meu jeep", "para": "meu Deus"}], 0.0, 10.0)
        self.assertEqual([w["p"] for w in r], ["meu", "Deus", "cara", "meu", "jeep!"])
        self.assertEqual((r[1]["i"], r[1]["f"]), (1.25, 1.5))

    def test_correcao_do_video_longo_troca_todas(self):
        r = longo._corrigir_todas(PALAVRAS, [{"de": "meu jeep", "para": "meu Deus"}])
        self.assertEqual([w["p"] for w in r], ["meu", "Deus", "cara", "meu", "Deus"])

    def test_correcao_so_de_maiuscula_e_ignorada(self):
        palavras = [{"p": "deus", "i": 0.0, "f": 0.4}]
        self.assertEqual(longo._corrigir_todas(palavras, [{"de": "deus", "para": "Deus"}]), palavras)

    def test_encaixar_nao_corta_palavra(self):
        self.assertEqual(longo._encaixar(1.05, 1.95, PALAVRAS), (0.95, 1.98))
        self.assertIsNone(longo._encaixar(5.0, 6.0, PALAVRAS))


class Capitulos(unittest.TestCase):
    def test_regras_do_youtube(self):
        capitulos = [{"t_origem": 3.0, "titulo": "Intro"}, {"t_origem": 50.0, "titulo": "A"},
                     {"t_origem": 55.0, "titulo": "Perto demais"}, {"t_origem": 200.0, "titulo": "C"},
                     {"t_origem": 245.0, "titulo": "No fim"}]
        blocos = [{"tipo": "corpo", "trechos": [(0.0, 100.0), (150.0, 250.0)]}]
        finais = longo._capitulos_finais(capitulos, blocos, [0.0], 200.0)
        self.assertEqual([(c["t"], c["titulo"]) for c in finais], [(0.0, "Intro"), (50.0, "A"), (150.0, "C")])

    def test_tempo_no_formato_do_youtube(self):
        self.assertEqual(longo._tempo_yt(65), "01:05")
        self.assertEqual(longo._tempo_yt(3725.9), "1:02:05")

    def test_partidas_nas_pausas_longas(self):
        self.assertEqual(longo._partidas([(0.0, 100.0), (200.0, 300.0), (400.0, 500.0)]), [0.0, 200.0, 400.0])

    def test_partidas_por_tempo_sem_pausas(self):
        self.assertEqual(longo._partidas([(0.0, 1800.0)]), [0.0, 300.0, 600.0, 900.0, 1200.0, 1500.0])


# ---------------------------------------------------------------- respostas do Claude guardadas

def _resposta_falsa(texto):
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5), stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=texto)])


class RespostasGuardadas(Temporario):
    def test_extrair_json_ignora_cercas_e_texto_depois(self):
        self.assertEqual(llm._extrair_json('```json\n{"a": 1}\n```\nE mais {"b": 2}'), '{"a": 1}')

    def test_mesma_pergunta_nao_paga_duas_vezes(self):
        cliente = mock.Mock()
        cliente.messages.create.return_value = _resposta_falsa('{"correcoes": [{"de": "meu jeep", "para": "meu Deus"}]}')
        with mock.patch.object(config, "PASTA_PROJETOS", self.pasta), \
                mock.patch.object(llm, "_cliente", return_value=cliente), \
                mock.patch.object(llm.custos, "registrar", return_value=0.0):
            r1 = llm._chamar_json("sistema", "transcrição X", Correcoes, "p1", "teste")
            r2 = llm._chamar_json("sistema", "transcrição X", Correcoes, "p1", "teste")
            self.assertEqual(cliente.messages.create.call_count, 1)
            self.assertEqual(r1, r2)
            llm._chamar_json("sistema", "transcrição Y", Correcoes, "p1", "teste")  # pedido diferente
            self.assertEqual(cliente.messages.create.call_count, 2)
            llm.esquecer_respostas("p1")  # "Refazer": pergunta de novo
            llm._chamar_json("sistema", "transcrição X", Correcoes, "p1", "teste")
            self.assertEqual(cliente.messages.create.call_count, 3)

    def test_resposta_invalida_nao_fica_guardada(self):
        cliente = mock.Mock()
        cliente.messages.create.side_effect = [_resposta_falsa("não sei"), _resposta_falsa('{"correcoes": []}')]
        with mock.patch.object(config, "PASTA_PROJETOS", self.pasta), \
                mock.patch.object(llm, "_cliente", return_value=cliente), \
                mock.patch.object(llm.custos, "registrar", return_value=0.0):
            llm._chamar_json("sistema", "t", Correcoes, "p1", "teste")
            guardadas = list((self.pasta / "p1" / "respostas").glob("*.json"))
            self.assertEqual(len(guardadas), 1)
            self.assertIn('{"correcoes": []}', json.loads(guardadas[0].read_text(encoding="utf-8"))["texto"])

    def test_sem_projeto_nao_guarda(self):
        self.assertIsNone(llm._arquivo_resposta(None, "m", "s", "c", 100, {}, Correcoes))


class ContinuarDeOndeParou(Temporario):
    def _clipes(self):
        novo = pipeline._novo_clip("clip_01", Corte(inicio=1, fim=40, remover=[(5, 7)], gancho=(10, 12), titulo="T"))
        arquivo = self.pasta / "clip_01.mp4"
        arquivo.write_bytes(b"x")
        antigo = {**json.loads(json.dumps(novo)), "status": "pronto", "arquivo": str(arquivo),
                  "corte_assinatura": "sig", "versao": 7}
        return novo, antigo

    def test_clipe_igual_e_reaproveitado(self):
        novo, antigo = self._clipes()  # tuplas no novo, listas no salvo: tem que dar igual
        self.assertTrue(pipeline._reaproveitar(novo, antigo))
        self.assertEqual((novo["status"], novo["versao"], novo["corte_assinatura"]), ("pronto", 7, "sig"))

    def test_clipe_editado_a_mao_nao_e_reaproveitado(self):
        novo, antigo = self._clipes()
        antigo["config"] = {"preset": "neon"}
        self.assertFalse(pipeline._reaproveitar(novo, antigo))
        self.assertEqual(novo["status"], "fila")

    def test_decisao_diferente_nao_e_reaproveitada(self):
        novo, antigo = self._clipes()
        antigo["fim"] = 41
        self.assertFalse(pipeline._reaproveitar(novo, antigo))

    def test_sem_arquivo_final_reaproveita_so_o_corte(self):
        novo, antigo = self._clipes()
        Path(antigo["arquivo"]).unlink()
        self.assertFalse(pipeline._reaproveitar(novo, antigo))
        self.assertEqual((novo["status"], novo.get("corte_assinatura")), ("fila", "sig"))


# ---------------------------------------------------------------- links e muitos clipes

class LinksEMuitosClipes(Temporario):
    def test_reconhece_link(self):
        import youtube
        self.assertTrue(youtube.e_link(" https://youtu.be/abc "))
        self.assertFalse(youtube.e_link("C:/videos/live.mp4"))
        self.assertFalse(youtube.e_link("https://a.com/x y"))

    def test_janelas_dividem_a_live(self):
        partes = pipeline.janelas(7200, 70)
        self.assertEqual(len(partes), 12)
        self.assertEqual(sum(q for *_, q in partes), 70)
        self.assertEqual((partes[0][0], partes[-1][1]), (0.0, 7200.0))
        self.assertEqual(pipeline.janelas(300, 5), [(0.0, 300.0, 5)])

    def test_apaga_o_original_so_sem_trabalho_pendente(self):
        import youtube
        video = self.pasta / "links" / "Youtube_x.mp4"
        video.parent.mkdir()
        video.write_bytes(b"x")
        meta = {"id": "p1", "video": str(video), "origem_url": "https://youtu.be/x", "opcoes": {}}
        with mock.patch.object(youtube, "PASTA", video.parent),                 mock.patch.object(youtube.projetos, "ler", return_value=meta),                 mock.patch.object(youtube.armazenamento, "em_uso", return_value=False):
            youtube.liberar_video("p1", pendentes=1)
            self.assertTrue(video.exists())  # ainda há job na fila do projeto
            meta["opcoes"]["apagar_original"] = False
            youtube.liberar_video("p1")
            self.assertTrue(video.exists())  # o usuário pediu para manter
            meta["opcoes"]["apagar_original"] = True
            youtube.liberar_video("p1")
            self.assertFalse(video.exists())


# ---------------------------------------------------------------- textos e validação

class TextosDoPost(unittest.TestCase):
    def test_hashtags(self):
        self.assertEqual(hashtags_validas("#Valorant #clutch, fps #valorant"), ["#Valorant", "#clutch", "#fps"])
        self.assertEqual(hashtags_validas(["dica de estudo", "#Foco!"]), ["#dicadeestudo", "#Foco"])
        self.assertEqual(len(hashtags_validas([f"t{k}" for k in range(10)])), 6)

    def test_legenda_do_post(self):
        self.assertEqual(texto_post_valido("  Você   faria\nisso?  "), "Você faria isso?")
        self.assertEqual(texto_post_valido(None), "")

    def test_posts_txt(self):
        clips = [{"id": "clip_01", "arquivo": "C:/x/clip_01.mp4", "nota": 88, "titulo": "Olha isso",
                  "legenda_post": "Você faria?", "hashtags": ["#a", "#b"]}]
        self.assertEqual(pipeline.texto_dos_posts(clips),
                         "clip_01.mp4  (nota 88)\nTítulo: Olha isso\nVocê faria?\n#a #b\n")


class Validacao(unittest.TestCase):
    def test_intervalos_tolerantes(self):
        v = [[1, 2], {"inicio": 3, "fim": 3.1}, "lixo", {"inicio": 5, "fim": 9}]
        self.assertEqual(intervalos_validos(v), [(1.0, 2.0), (5.0, 9.0)])

    def test_item_invalido_nao_derruba_a_resposta(self):
        c = Corte.model_validate({"inicio": 0, "fim": 10, "emojis": [{"word": "fogo", "emoji": "🔥"}, {"x": 1}]})
        self.assertEqual([(e.palavra, e.emoji) for e in c.emojis], [("fogo", "🔥")])


# ---------------------------------------------------------------- biblioteca de áudio e travas de arquivos

class BibliotecaDeAudio(Temporario):
    def setUp(self):
        super().setUp()
        self.audio = self.pasta / "audio"
        for nome in ("a.mp3", "b.mp3", "c.mp3"):
            (self.audio / "musica" / "calma").mkdir(parents=True, exist_ok=True)
            (self.audio / "musica" / "calma" / nome).write_bytes(b"x")
        self.patches = [mock.patch.object(bib, "PASTA_AUDIO", self.audio),
                        mock.patch.object(bib, "PASTA_MUSICA", self.audio / "musica"),
                        mock.patch.object(bib, "_ARQ_RECUSADAS", self.audio / ".pacote_removidas.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_so_serve_arquivo_de_audio_de_dentro_da_biblioteca(self):
        dentro = self.audio / "musica" / "calma" / "a.mp3"
        (self.pasta / "segredo.json").write_text("{}")
        self.assertEqual(bib.arquivo_da_biblioteca(str(dentro)), dentro.resolve())
        self.assertIsNone(bib.arquivo_da_biblioteca(str(self.pasta / "segredo.json")))
        self.assertIsNone(bib.arquivo_da_biblioteca(str(self.audio / ".." / "segredo.json")))
        self.assertIsNone(bib.arquivo_da_biblioteca(str(self.audio / "musica" / "calma" / "nao_existe.mp3")))

    def test_sequencia_de_faixas_estavel_e_completa(self):
        s1 = bib.sequencia_musicas("calma", "projeto1")
        self.assertEqual(s1, bib.sequencia_musicas("calma", "projeto1"))
        self.assertEqual(sorted(p.name for p in s1), ["a.mp3", "b.mp3", "c.mp3"])

    def test_faixa_do_pacote_apagada_nao_volta(self):
        pacote = self.pasta / "pacote.json"
        pacote.write_text(json.dumps({"faixas": [
            {"clima": "calma", "arquivo": "a.mp3", "titulo": "A", "artista": "X"},
            {"clima": "calma", "arquivo": "z.mp3", "titulo": "Z", "artista": "X"}]}), encoding="utf-8")
        with mock.patch.object(bib, "PACOTE", pacote):
            self.assertEqual([f["arquivo"] for f in bib.pacote_faltando()], ["z.mp3"])
            self.assertTrue(bib.excluir(str(self.audio / "musica" / "calma" / "a.mp3")))
            self.assertEqual([f["arquivo"] for f in bib.pacote_faltando()], ["z.mp3"])  # "a" foi apagada de propósito


class TravaDaPastaDeSaida(Temporario):
    def test_so_apaga_pasta_marcada_dentro_da_saida(self):
        base = self.pasta / "saida"
        dono = base / "meu_video"
        dono.mkdir(parents=True)
        (dono / ".projeto").write_text("abc123")
        outro = self.pasta / "fora"
        outro.mkdir()
        (outro / ".projeto").write_text("abc123")
        with mock.patch.object(config, "pasta_saida", return_value=base):
            self.assertTrue(projetos._saida_do_projeto(dono, "abc123"))
            self.assertFalse(projetos._saida_do_projeto(dono, "outro_id"))
            self.assertFalse(projetos._saida_do_projeto(base, "abc123"))
            self.assertFalse(projetos._saida_do_projeto(outro, "abc123"))


# ---------------------------------------------------------------- música (usa o ffmpeg)

@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg não encontrado")
class Musica(Temporario):
    def test_mede_volume_e_pula_a_introducao_quieta(self):
        faixa = self.pasta / "faixa.wav"
        # 6 s de silêncio + 10 s de tom (pico 0,5)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=6",
                        "-f", "lavfi", "-i", "sine=f=440:r=44100:d=10", "-filter_complex",
                        "[1:a]volume=4[t];[0:a][t]concat=n=2:v=0:a=1", str(faixa)], check=True)
        with mock.patch.object(ef, "_ARQ_MEDIDAS", self.pasta / "medidas.json"):
            m = ef.medir_musica(faixa)
            self.assertAlmostEqual(m["inicio"], 6.0, delta=0.5)
            self.assertLess(abs(ef._ganho_musica(faixa) - (ef.ALVO_MUSICA_LUFS - m["lufs"])), 0.01)
            medidas = json.loads((self.pasta / "medidas.json").read_text(encoding="utf-8"))
            self.assertEqual(list(medidas.values()), [m])  # medido uma vez, guardado no cache

    def test_acha_as_batidas(self):
        import numpy as np
        taxa = 11025
        for bpm, fase in ((95, 0.37), (128, 0.11), (174, 0.3)):
            x = np.zeros(taxa * 30, dtype=np.float32)
            rng = np.random.default_rng(1)
            verdade = np.arange(fase, 29.5, 60 / bpm)
            for t in verdade:  # bumbo forte na batida e chimbal fraco no contratempo
                i = int(t * taxa)
                x[i:i + 300] += rng.normal(0, 0.5, 300) * np.exp(-np.arange(300) / 60)
                j = int((t + 30 / bpm) * taxa)
                x[j:j + 100] += rng.normal(0, 0.1, 100) * np.exp(-np.arange(100) / 30)
            r = ef._batida(x, taxa)
            self.assertAlmostEqual(60 / r["periodo"], bpm, delta=1.5)
            batidas = np.array(r["batidas"])
            erros = [abs(batidas - v).min() for v in verdade[2:-2]]
            self.assertLess(max(erros), 0.025)  # menos de 1 quadro a 30 fps

    def test_cortes_puxados_para_a_batida(self):
        medida = {"inicio": 1.0, "periodo": 0.5, "confianca": 0.8, "batidas": [1.0 + 0.5 * k for k in range(200)]}
        with mock.patch.object(ef, "medir_musica", return_value=medida):
            # corte cairia em 2,8 s no clipe: vai para a batida de 3,0 s (fim do 1º trecho: 12,8 -> 13,0)
            self.assertEqual(pipeline._cortes_na_batida([(10.0, 12.8), (20.0, 25.0)], 0.0, "m.mp3", []),
                             [(10.0, 13.0), (20.0, 25.0)])
            # mas não corta palavra no meio
            palavra = [{"p": "boa", "i": 12.9, "f": 13.2}]
            self.assertEqual(pipeline._cortes_na_batida([(10.0, 12.8), (20.0, 25.0)], 0.0, "m.mp3", palavra),
                             [(10.0, 12.8), (20.0, 25.0)])
            # nem invade o trecho seguinte
            self.assertEqual(pipeline._cortes_na_batida([(10.0, 12.8), (12.9, 25.0)], 0.0, "m.mp3", []),
                             [(10.0, 12.8), (12.9, 25.0)])
        with mock.patch.object(ef, "medir_musica", return_value={**medida, "confianca": 0.1}):
            self.assertEqual(pipeline._cortes_na_batida([(10.0, 12.8), (20.0, 25.0)], 0.0, "m.mp3", []),
                             [(10.0, 12.8), (20.0, 25.0)])  # batida pouco marcada: não mexe

    def test_trilha_troca_de_faixa_com_crossfade(self):
        entradas, filtros = [], []
        with mock.patch.object(ef, "medir_musica", return_value={"lufs": -10.0, "inicio": 2.0}):
            ef._cama_musical(entradas, filtros, [(0.0, "a.mp3"), (60.0, "b.mp3")], 0.22, 120.0)
        self.assertEqual(entradas.count("-i"), 2)
        self.assertIn("atrim=start=2.00:duration=63.000", filtros[0])  # 60 s + o crossfade
        self.assertIn("atrim=start=2.00:duration=60.000", filtros[1])
        self.assertIn("acrossfade=d=3.0", filtros[2])
        self.assertTrue(filtros[-1].endswith("[mus]"))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- direção de arte

class DirecaoDeArte(unittest.TestCase):
    def test_valida_so_o_que_existe_no_catalogo(self):
        import direcao
        v = direcao.valida({"preset": "Gamer", "cor": "#ff0000", "look": "Dramático", "transicao": "explosao",
                            "zoom": "forte", "impacto": "tremor"}, ["gamer", "cinema"])
        self.assertEqual(v, {"preset": "gamer", "cor": "#FF0000", "look": "dramatico", "zoom": "forte", "impacto": "tremor"})
        self.assertEqual(direcao.valida("lixo", ["gamer"]), {})

    def test_padrao_do_clima_completa_a_escolha(self):
        import direcao
        d = direcao.efetiva({"look": "frio"}, "energetica")
        self.assertEqual((d["look"], d["transicao"], d["preset"]), ("frio", "zoom_rapido", "gamer"))
        self.assertEqual(direcao.efetiva(None, None)["transicao"], "pulso")

    def test_transicao_so_nos_cortes_grandes(self):
        import direcao
        # abertura (2 s) + trechos com pulo curto (0,4 s, silêncio) e pulo grande (10 s, outro lance)
        partes = [(50.0, 52.0), (10.0, 20.0), (20.4, 30.0), (40.0, 45.0)]
        self.assertEqual(direcao.cortes_grandes(partes, True), [2.0, 21.6])

    def test_efeitos_nao_quebram_o_quadro(self):
        import numpy as np
        import reenquadramento as rq
        q = np.full((1920, 1080, 3), 100, dtype=np.uint8)
        for tipo in ("flash", "desfoque", "tremor", "glitch"):
            saida = rq._aplicar_efeito(q, tipo, 0.8, 7)
            self.assertEqual(saida.shape, q.shape)
        self.assertGreater(rq._aplicar_efeito(q, "flash", 1.0, 0).mean(), 200)


# ---------------------------------------------------------------- B-roll

class BRollDeApoio(unittest.TestCase):
    def test_valida_e_limita_a_duracao(self):
        c = Corte.model_validate({"inicio": 0, "fim": 40, "broll": [
            {"inicio": 10, "fim": 18, "busca": "sports car"},   # longo demais: corta em 4 s
            {"inicio": 20, "fim": 20.5, "busca": "beach"},      # curto demais: sai
            {"inicio": 30, "fim": 32, "busca": ""}]})            # sem busca: sai
        self.assertEqual([(b.inicio, b.fim, b.busca) for b in c.broll], [(10, 14, "sports car")])

    def test_escolhe_arquivo_leve_e_na_orientacao(self):
        import broll
        video = {"video_files": [
            {"link": "a", "width": 2160, "height": 3840}, {"link": "b", "width": 1080, "height": 1920},
            {"link": "c", "width": 720, "height": 1280}, {"link": "d", "width": 1280, "height": 720},
            {"link": "e", "width": 360, "height": 640}]}
        self.assertEqual(broll.escolher_arquivo(video, "portrait")["link"], "c")
        self.assertEqual(broll.escolher_arquivo(video, "landscape")["link"], "d")

    def test_sobrepoe_com_fusao(self):
        import numpy as np
        import reenquadramento as rq
        fundo = np.zeros((1920, 1080, 3), dtype=np.uint8)
        cap = mock.Mock()
        cap.read.return_value = (True, np.full((720, 1280, 3), 200, dtype=np.uint8))
        abertos = {0: cap}
        lista = [(5.0, 7.0, "x.mp4")]
        self.assertEqual(rq._sobrepor_broll(fundo, 4.0, lista, abertos, 1080, 1920).mean(), 0)      # antes
        self.assertAlmostEqual(rq._sobrepor_broll(fundo, 6.0, lista, abertos, 1080, 1920).mean(), 200, delta=1)
        self.assertLess(rq._sobrepor_broll(fundo, 5.05, lista, abertos, 1080, 1920).mean(), 100)    # entrando


# ---------------------------------------------------------------- reações, capa, tradução, bloco longo

class EnfeitesETraducao(Temporario):
    def test_figurinha_e_pop(self):
        import numpy as np
        import enfeites
        fig = enfeites.figurinha_reacao("QUE ISSO?!", 1080)
        self.assertEqual(fig.shape[2], 4)
        self.assertLess(fig.shape[1], 1080)
        quadro = np.zeros((1920, 1080, 3), dtype=np.uint8)
        self.assertEqual(enfeites.compor_reacao(quadro, fig, 0.5, 2.0).max(), 0)   # antes: nada
        self.assertGreater(enfeites.compor_reacao(quadro, fig, 2.5, 2.0).max(), 200)  # durante: aparece
        self.assertEqual(enfeites.compor_reacao(quadro, fig, 3.5, 2.0).max(), 0)   # depois de 1,4 s: some

    def test_capa_vertical(self):
        import numpy as np
        import enfeites
        quadro = np.full((720, 1280, 3), 90, dtype=np.uint8)
        capa = enfeites.capa_vertical(quadro, "Clutch na faca que ninguém esperava", 0.3)
        self.assertEqual(capa.size, (1080, 1920))

    def test_frases_e_tempo_da_traducao(self):
        import traducao
        palavras = [{"p": "Eu", "i": 0.0, "f": 0.2}, {"p": "ganhei.", "i": 0.2, "f": 0.6, "enfase": True},
                    {"p": "Depois", "i": 2.0, "f": 2.3}, {"p": "perdi", "i": 2.3, "f": 2.8}]
        grupos = traducao.frases(palavras)
        self.assertEqual([len(g) for g in grupos], [2, 2])
        novas = traducao.redistribuir(grupos[0], "I *won*.")
        self.assertEqual([w["p"] for w in novas], ["I", "won."])
        self.assertEqual((novas[0]["i"], novas[-1]["f"]), (0.0, 0.6))
        self.assertTrue(novas[1]["enfase"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg não encontrado")
    def test_bloco_longo_com_cor_e_broll(self):
        import direcao
        video, apoio, saida = self.pasta / "v.mp4", self.pasta / "b.mp4", self.pasta / "bloco.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8", "-f", "lavfi",
                        "-i", "sine=f=300:d=8", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=25:d=2",
                        "-c:v", "libx264", str(apoio)], check=True)
        info = ef.sondar(video)
        dur = ef.renderizar_bloco(video, [(0.0, 3.0), (4.0, 7.0)], saida, info, look=direcao.filtro_look("cinema"),
                                  brolls=[(1.0, 3.5, str(apoio))])
        self.assertAlmostEqual(dur, 6.0, delta=0.05)
        self.assertAlmostEqual(ef.sondar(saida)["duracao"], 6.0, delta=0.1)
        quadro = self.pasta / "q.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2.0", "-i", str(saida), "-frames:v", "1", str(quadro)], check=True)
        from PIL import Image
        r, g, b = Image.open(quadro).convert("RGB").resize((1, 1)).getpixel((0, 0))
        self.assertGreater(r, 120)  # no meio do B-roll a tela é o vídeo vermelho
        self.assertLess(g, 80)


# ---------------------------------------------------------------- replay, som e posição da legenda

class PacoteDeEdicao(Temporario):
    def test_trecho_do_replay_fica_dentro_do_clipe(self):
        self.assertEqual(pipeline._trecho_replay({"pico": 20.0}, [(10.0, 30.0)]), (18.8, 20.8))
        self.assertEqual(pipeline._trecho_replay({"pico": 10.3}, [(10.0, 30.0)]), (10.0, 12.0))  # completa para frente
        # pico num pedaço cortado, colado no trecho: usa a ponta do trecho
        self.assertEqual(pipeline._trecho_replay({"pico": 32.0}, [(10.0, 30.0), (40.0, 50.0)]), (28.0, 30.0))
        self.assertIsNone(pipeline._trecho_replay({"pico": None}, [(10.0, 30.0)]))
        self.assertIsNone(pipeline._trecho_replay({"pico": 50.0}, [(10.0, 30.0)]))

    def test_riser_antes_e_grave_na_kill(self):
        with mock.patch.object(pipeline.biblioteca, "escolher_efeito", side_effect=lambda tipo, s: f"{tipo}.wav"):
            efeitos = pipeline._efeitos_sonoros("x", False, [], [10.0], 30.0)
        tipos = {Path(arq).stem: t for t, arq, _ in efeitos}
        self.assertAlmostEqual(tipos["grave"], 9.95)
        self.assertAlmostEqual(tipos["riser"], 8.55)
        self.assertNotIn("impacto", tipos)  # o grave ocupa o lugar do impacto

    def test_legenda_por_enquadramento(self):
        est = {"posicao_y": 0.66}
        self.assertEqual(pipeline._posicao_legenda("split", est), 0.57)
        self.assertEqual(pipeline._posicao_legenda("jogo", est), 0.885)
        self.assertEqual(pipeline._posicao_legenda("rosto", est), 0.66)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg não encontrado")
    def test_corte_com_replay_em_camera_lenta(self):
        video, saida = self.pasta / "v.mp4", self.pasta / "c.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=12", "-f", "lavfi",
                        "-i", "sine=f=440:d=12", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
        ef.cortar(video, [(1.0, 5.0), (6.0, 9.0)], saida, normalizar=False, replay=(3.0, 4.5), loop=True)
        self.assertAlmostEqual(ef.sondar(saida)["duracao"], 7.0 + 3.0, delta=0.15)  # 7 s + 1,5 s a meia velocidade


# ---------------------------------------------------------------- modo sem IA

class SemIA(Temporario):
    def _projeto(self, opcoes: dict) -> str:
        (self.pasta / "p1").mkdir()
        (self.pasta / "p1" / "meta.json").write_text(json.dumps({"opcoes": opcoes}), encoding="utf-8")
        return "p1"

    def test_projeto_sem_ia_nunca_chama_a_api(self):
        with mock.patch.object(config, "PASTA_PROJETOS", self.pasta), \
                mock.patch.object(llm, "_cliente", side_effect=AssertionError("chamou a API")):
            pid = self._projeto({"sem_ia": True})
            with self.assertRaises(llm.IaDesligada):
                llm._chamar_json("s", "c", Correcoes, pid, "teste")

    def test_sem_ia_nao_vira_aviso_de_falha_nem_monta_folhas(self):
        with mock.patch.object(pipeline, "_aviso") as aviso:
            pipeline._claude_falhou("p1", llm.IaDesligada("IA desligada neste projeto"))
        aviso.assert_not_called()
        self.assertFalse(pipeline._ver_imagens({"sem_ia": True, "ver_imagens": True}))
        self.assertTrue(pipeline._ver_imagens({}))
        self.assertFalse(longo._opcoes({"modo": "gameplay", "opcoes": {"sem_ia": True}})["ver_imagens"])
