# Clipador — editor de vídeo local com IA

Transforma vídeos longos (podcast, aula, gameplay) em clipes curtos com legenda,
reenquadramento no rosto e título gancho. Roda 100% no seu PC (localhost); só a
escolha dos trechos usa a API do Claude.

## Requisitos

- Windows com **Python 3.12**, **FFmpeg** no PATH e **Node 18+**
- GPU NVIDIA é opcional: acelera a transcrição e o encode (NVENC)
- Chave da API Anthropic em `ANTHROPIC_API_KEY`, ou salva na tela Configurações

## Instalação

```powershell
# 1. Python (o venv fica fora do OneDrive)
py -3.12 -m venv C:\opusfalso-dados\venv
C:\opusfalso-dados\venv\Scripts\pip install -r backend\requirements.txt

# 2. Interface e legenda animada
cd frontend;  npm install;  cd ..
cd remotion;  npm install;  cd ..
```

Na primeira execução o Whisper baixa o modelo (~1,6 GB) e o Remotion baixa um
Chrome headless (~100 MB).

## Como rodar

**Desenvolvimento** (dois terminais):

```powershell
# terminal 1 – API
cd backend
C:\opusfalso-dados\venv\Scripts\python -m uvicorn api:app --port 8000 --no-access-log

# terminal 2 – interface
cd frontend
npm run dev          # abre em http://localhost:5173
```

**Uso diário**: rode `npm run build` uma vez dentro de `frontend/` e depois
dê dois cliques em **`iniciar.bat`**. A API serve a interface em http://127.0.0.1:8000.

**Pelo terminal**:

```powershell
cd backend
C:\opusfalso-dados\venv\Scripts\python editar.py video.mp4 "5 melhores momentos, legenda amarela, zoom" --modo falado
C:\opusfalso-dados\venv\Scripts\python editar.py jogo.mkv "3 clipes curtos, zoom nas kills" --modo gameplay
```

Opções úteis: `--clips N`, `--duracao 15-30|30-60|60-90`, `--formato 9:16|1:1|16:9`,
`--preset opus|hormozi|minimalista`, `--animada`, `--layout rosto|dupla|centro|inteiro|split`,
`--musica arquivo.mp3`, `--apoio video.mp4` (gameplay sem facecam), `--refinar` (manda frames ao Claude).

## Onde ficam as coisas

| O quê | Onde |
|---|---|
| Clipes prontos | `C:\opusfalso-dados\saida\<nome_do_video>\clip_01.mp4` (configurável) |
| Projetos (meta.json, thumbs, temporários) | `C:\opusfalso-dados\projetos\<id>\` |
| Cache de transcrição e áudio (por hash do vídeo) | `C:\opusfalso-dados\cache\` |
| Configurações e custo acumulado | `C:\opusfalso-dados\config.json`, `custos.json` |
| Presets de legenda | `backend\estilos.json` (ou tela **Estilos**) |
| Fontes | `C:\opusfalso-dados\fontes\` (coloque um .ttf aqui para usá-lo nos estilos) |

Para trocar a pasta de dados, defina a variável `OPUSFALSO_DADOS`.

## Módulos (backend/)

`transcricao.py` (faster-whisper + cache) · `analise_audio.py` (picos de energia) ·
`planejador_llm.py` (Claude → JSON validado) · `planejador_local.py` (reserva sem API) ·
`editor_ffmpeg.py` (cortes, silêncios, loudnorm, música) · `reenquadramento.py` (rosto, zoom, layouts) ·
`legendas.py` (ASS e ponte para o Remotion) · `pipeline.py` (orquestra tudo) ·
`projetos.py` / `jobs.py` / `api.py` (FastAPI) · `editar.py` (CLI)

## Observações

- Se a API do Claude falhar (sem chave, sem créditos ou sem internet), o
  **planejador local** assume e um aviso aparece no projeto. Ele é bem mais
  simples: regras para a instrução e heurísticas para escolher os trechos.
- Legenda **simples** (ASS/FFmpeg) é rápida. A **animada** (Remotion) tem emoji e
  animações mais suaves, mas leva cerca de 3× a duração do clipe para renderizar.
- Vídeos de teste gerados durante o desenvolvimento: `C:\opusfalso-dados\testes\`.
