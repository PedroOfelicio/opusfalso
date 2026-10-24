# Clipador — editor de vídeo local com IA

Ferramenta **pessoal e local** que transforma vídeos longos (podcast, aula, talking head, gameplay)
em clipes curtos prontos para TikTok, Reels e Shorts. Ela gera legenda palavra por palavra,
reenquadra para 9:16 seguindo o rosto de quem fala e aplica zoom nos momentos de ênfase,
título gancho e barra de progresso.

- Roda em **localhost**: sem login, sem pagamento, sem banco de dados externo.
- Todo o processamento pesado é local: transcrição, análise de áudio, detecção de rosto e render.
- A **API do Claude** só entra para entender a instrução em linguagem natural e escolher os melhores trechos.
  Se ela não estiver disponível, um planejador local assume.
- Tem três formas de uso: **interface web** (React), **API** (FastAPI) e **terminal** (`editar.py`).
- Além dos clipes curtos, a aba **Vídeos longos** edita para o YouTube: o vídeo inteiro mais enxuto ou uma
  compilação dos melhores momentos, com capítulos, legenda .srt, títulos, descrição e tags.

> Visual e fluxo inspirados no OpusClip, sem usar logo, nome ou marca dele.

---

## Sumário

1. [Como funciona](#como-funciona)
2. [Recursos](#recursos)
3. [Arquitetura](#arquitetura)
4. [Requisitos](#requisitos)
5. [Instalação](#instalação)
6. [Como rodar](#como-rodar)
7. [Interface web](#interface-web)
8. [Uso pelo terminal](#uso-pelo-terminal)
9. [O plano de edição (contrato Claude → código)](#o-plano-de-edição-contrato-claude--código)
10. [Modo Falado × Modo Gameplay](#modo-falado--modo-gameplay)
    - [Vídeos longos (YouTube)](#vídeos-longos-youtube)
11. [Reenquadramento e layouts](#reenquadramento-e-layouts)
12. [Legendas e estilos](#legendas-e-estilos)
13. [API HTTP](#api-http)
14. [Dados em disco](#dados-em-disco)
15. [Configuração](#configuração)
16. [Custos da API](#custos-da-api)
17. [Solução de problemas](#solução-de-problemas)
18. [Limitações conhecidas](#limitações-conhecidas)
19. [Histórico do desenvolvimento](#histórico-do-desenvolvimento)

---

## Como funciona

1. Você envia um vídeo (mp4, mov, mkv) ou cola o caminho local dele.
2. Escreve o que quer em português, por exemplo:
   *"5 melhores momentos, vertical, legenda amarela, zoom nas kills, sem música"*.
3. Escolhe o modo: **Falado** ou **Gameplay**.
4. O Claude converte a instrução num **plano de edição em JSON**, com uma lista fechada de ações.
   O código valida esse plano e o executa.

```
vídeo ─► Transcrevendo ─► Analisando ─► Escolhendo trechos ─► Cortando ─► Legendando ─► clip_01.mp4 …
         (Whisper, GPU)   (plano + picos   (Claude ou             (FFmpeg)   (reenquadra +
                           de áudio)        planejador local)                 legenda + título)
```

Tudo que é pedido e não existe na lista de ações (ex.: "coloca um meme") é **ignorado e avisado**
na tela, na seção "Não atendido".

---

## Recursos

**Pipeline**
- Transcrição local com **faster-whisper** e timestamp por palavra. Usa a GPU quando há
  (`large-v3-turbo` em `int8_float16` cabe em 4 GB) e cai sozinha para um modelo menor e depois para a CPU.
- **Cache por hash do vídeo**: o mesmo arquivo nunca é transcrito nem analisado duas vezes,
  mesmo se for enviado de novo.
- Remoção de **silêncios longos** e de **vícios de linguagem** ("hum", "ãh"; "é", "tipo" e "né" só quando isolados por pausas).
- **Normalização de áudio** para -14 LUFS e **música de fundo** com *ducking* (abaixa sozinha quando há voz).
- **Melhorar a voz** (automático na fala, local): passa-alta contra ronco/zumbido, redução de ruído, expansor
  suave nas pausas, EQ de presença, de-esser e compressão leve. Num teste com ruído de sala, o ruído nas pausas
  caiu de -29 dB para -55 dB depois da normalização, com a fala no mesmo nível.
- **Biblioteca de áudio local**: músicas separadas por clima (o Claude escolhe o clima de cada clipe), com
  um **pacote grátis de 16 faixas CC0** para baixar em Configurações, e **efeitos sonoros** automáticos (whoosh
  no título, impacto nas kills, pop nos zooms). O volume de cada faixa é igualado e, nos clipes, a introdução
  quieta da música é pulada.
- **Diretor de arte (IA)**: na mesma chamada que escolhe os cortes, o Claude define o visual de cada clipe
  pelo clima do trecho, numa lista fechada (`backend/direcao.py`): estilo e cor da legenda, look de cor
  (natural, vibrante, cinema, quente, frio, dramático, preto e branco, retrô; filtros do FFmpeg aplicados
  antes da legenda), transição nos cortes grandes (flash, zoom rápido, desfoque, tremor, glitch ou só o pulso
  de zoom; os cortes de silêncio não ganham transição), força do zoom e efeito no pico de ação do gameplay.
  Sem o Claude, vale o padrão do clima. Escolher um template desliga o diretor (visual fixo); no editor, a aba
  Enquadramento mostra e deixa trocar cada escolha. Custo: ~US$ 0,001 por clipe.
- **B-roll** (fala, clipes e vídeos longos): o Claude marca onde a fala cita algo que dá para mostrar e o
  que buscar; o app baixa do Pixabay (ou Pexels), confere as etiquetas (pelo menos 2 palavras da busca, senão
  fica sem B-roll) e cobre a tela por 2-4 s com fusão. Chave grátis em Configurações. `backend/broll.py`.
- **Textos de reação** ("QUE ISSO?!", "KKKKK") que pulam na tela no pico, desenhados pelo app (sem imagem de
  fora). **Capa vertical** 1080x1920 de cada clipe (melhor quadro + título), no card e no zip. `enfeites.py`.
- **Legenda traduzida** (inglês, espanhol, português...): frases traduzidas pelo Claude no tempo da fala
  original, com a ênfase preservada; ~US$ 0,005 por clipe. `traducao.py`.
- **Vídeo longo**: cor pelo clima (look escolhido pelo Claude) e B-roll, aplicados no render dos blocos.
- **Link do YouTube** em vez do arquivo (clipes curtos e vídeos longos): o app baixa com o `yt-dlp` (até
  1080p), processa e **apaga o original no fim**, então o bruto da live não fica ocupando o disco. Se depois
  for preciso de novo (reexportar um clipe, regenerar, revisar ou remontar o vídeo longo), ele é baixado de
  novo pelo link, sozinho; a transcrição e as análises continuam no cache (indexadas pelo caminho). A opção
  `apagar_original: false` mantém o arquivo. Live ainda no ar, playlist e vídeo privado dão mensagem clara.
- **Muitos clipes** (até 100, ex.: 70 clipes de uma live de 2 h): acima de 8, a escolha é feita por janelas
  do vídeo (~6 clipes por janela de igual duração), então cada pedido ao Claude fica pequeno e os clipes saem
  espalhados pela live inteira; parte fraca da live simplesmente não dá clipe. O corte e o render são feitos um
  clipe de cada vez, apagando os intermediários logo em seguida (os primeiros clipes já ficam prontos para
  ver). Acima de 20, a tela troca para a legenda simples (~4x mais rápida que a animada).
- **Clipes mais leves**: o clipe final sai com teto de 8 Mbps (NVENC cq 23; Remotion crf 22), que em
  1080x1920 é de sobra para as redes; um clipe de 34 s caiu de ~50 MB para ~20-30 MB.
- **Continuar de onde parou**: depois de um erro, de um cancelamento ou do servidor reiniciado, "Tentar de
  novo" reaproveita as respostas do Claude que já chegaram (sem pagar de novo), os clipes já prontos e os
  cortes já feitos; no vídeo longo, remonta com a edição salva e os blocos em cache. "Refazer" um projeto
  pronto pede uma edição nova ao Claude.
- **Texto para postar**: cada clipe vem com legenda do post e 3 a 5 hashtags (na mesma chamada que escolhe
  os cortes), com botão de copiar no card. Tudo vai também para `posts.txt`, na pasta dos clipes e no zip.
- **Reenquadramento 9:16 / 1:1 / 16:9** seguindo o rosto de quem fala, com câmera suave e sem tremer.
- **Zoom automático** sutil nas palavras de ênfase e nos picos do gameplay, e **pulsos de zoom** nos cortes
  secos (o enquadramento alterna a cada jump cut, o que esconde o pulo).
- **Abertura com o clímax**: 1,2-4 s do melhor momento antes do contexto (no gameplay, o segundo de mais
  energia; na fala, a frase "gancho" que o Claude marca). O título gancho, 35% maior, fica 4 s na tela
  por cima dessa abertura. Desliga com "sem teaser" ou na opção "Abrir com o clímax".
- **Efeitos sonoros de fábrica** (whoosh, impacto, pop) sintetizados e sem direitos autorais, em
  `backend/recursos/efeitos`; entram na biblioteca quando a pasta do efeito está vazia.
- **Sem tela preta**: no gameplay, quadros escuros nas pontas (morte, respawn, transição) são aparados
  medindo o brilho, sem custo de API.
- Encode por **NVENC** (GPU NVIDIA) quando disponível; senão, libx264.

**Legendas**
- Grupos de 2 a 4 palavras, quebrados por pausa natural e pontuação.
- A palavra falada muda de cor e dá um **pop** de escala (100% → 115% → 100%, ~120 ms).
- Duas saídas:
  - **Simples**: ASS queimado pelo FFmpeg/libass. É rápida e já tem destaque e pop.
  - **Animada**: Remotion (React). Tem animações mais suaves e **emoji** nas palavras-chave.
- **Presets** editáveis em `estilos.json` (opus, hormozi, minimalista) ou pela tela Estilos.
- **Título gancho** nos primeiros 2,8 s com fundo destacado e **barra de progresso** no topo.

**Interface**
- Home com drag & drop, chips de exemplo e opções rápidas.
- Tela de progresso real com etapas, porcentagem, tempo estimado e botão de cancelar.
- Resultados com preview ao passar o mouse, nota viral, título editável e ajustes em linguagem natural.
- Editor de clipe com linha do tempo, legenda editável palavra por palavra, enquadramento, título e áudio.
- Telas de Estilos (preview ao vivo) e Configurações (chave, modelo, GPU, biblioteca de áudio com botão para
  ouvir e apagar cada faixa, armazenamento, custo acumulado).
- Projeto com erro ou cancelado: **Tentar de novo / Continuar** (de onde parou, sem pagar de novo) ou
  **Recomeçar do zero** (o Claude decide tudo de novo, para quando o problema foi a própria decisão).

---

## Arquitetura

```
opusfalso/
├── backend/                 Python (pipeline + API)
│   ├── config.py            caminhos, config.json, utilitários de JSON
│   ├── modelos.py           modelos pydantic (o "contrato" com o Claude)
│   ├── transcricao.py       faster-whisper + cache + fallback GPU→CPU
│   ├── analise_audio.py     picos de energia (volume + fluxo espectral)
│   ├── planejador_llm.py    chamadas ao Claude → JSON validado (1 nova tentativa)
│   ├── planejador_local.py  reserva sem API (regras + heurísticas)
│   ├── editor_ffmpeg.py     sondar, extrair áudio/frames, cortar, silêncios, loudnorm, música
│   ├── reenquadramento.py   detecção/rastreio de rosto, câmera suave, zoom, layouts
│   ├── legendas.py          agrupamento, ASS, ponte com o Remotion
│   ├── pipeline.py          orquestra as etapas (usado pela API e pelo CLI)
│   ├── longo.py             vídeos longos para o YouTube (enxugar / melhores momentos)
│   ├── biblioteca_audio.py  músicas por clima e efeitos sonoros (pastas locais)
│   ├── projetos.py          projetos em disco (meta.json)
│   ├── jobs.py              fila de jobs em background (1 por vez, com cancelamento)
│   ├── custos.py            estimativa de custo por chamada
│   ├── api.py               FastAPI
│   ├── editar.py            CLI
│   ├── estilos.json         presets de legenda
│   ├── requirements.txt
│   └── recursos/            fontes (OFL) e modelos de rosto (YuNet, BlazeFace)
├── frontend/                React 19 + Vite + Tailwind 4 + lucide-react
│   └── src/
│       ├── api.js           cliente da API
│       ├── components/      Sidebar, VideoCard, ScoreBadge, StepProgress, PreviewLegenda, ui.jsx
│       └── pages/           Home, Projetos, Projeto (Processando/Resultados), Editor, Estilos, Configuracoes
├── remotion/                legenda animada (composição "Clip")
│   └── src/                 index.ts, Raiz.tsx, Clip.tsx, tipos.ts
├── iniciar.bat              sobe a API e abre o navegador
└── README.md
```

**Stack:** Python 3.12 · FFmpeg · faster-whisper · SDK `anthropic` · OpenCV (YuNet) + MediaPipe ·
NumPy · Pydantic · FastAPI/Uvicorn · React + Vite + Tailwind · Remotion (Node).

---

## Requisitos

| Item | Observação |
|---|---|
| Windows 10/11 | Testado no Windows 11 |
| **Python 3.12** | O MediaPipe ainda não é garantido no 3.13 |
| **FFmpeg** no PATH | Build "full" recomendada (com libass e NVENC) |
| **Node 18+** | Para a interface e o Remotion |
| GPU NVIDIA (opcional) | Acelera Whisper e encode; 4 GB de VRAM é suficiente |
| Chave da Anthropic | Em `ANTHROPIC_API_KEY` ou salva na tela Configurações; **precisa ter créditos** |

---

## Instalação

```powershell
# 1. Ambiente Python (fora do OneDrive, para não sincronizar milhares de arquivos)
py -3.12 -m venv C:\opusfalso-dados\venv
C:\opusfalso-dados\venv\Scripts\pip install -r backend\requirements.txt

# 2. Interface
cd frontend
npm install
npm run build      # necessário para o iniciar.bat
cd ..

# 3. Legenda animada
cd remotion
npm install
cd ..
```

Na primeira execução:
- o Whisper baixa o modelo `large-v3-turbo` (~1,6 GB) em `C:\opusfalso-dados\modelos\whisper`;
- o Remotion baixa um Chrome headless (~100 MB);
- fontes e modelos de rosto são copiados de `backend/recursos/` para a pasta de dados.

Sem GPU NVIDIA, as linhas `nvidia-*` do `requirements.txt` podem ser removidas.

---

## Como rodar

### Uso diário
Dê dois cliques em **`iniciar.bat`**. Ele sobe a API em http://127.0.0.1:8000, que também serve a
interface compilada (`frontend/dist`), e abre o navegador.

### Desenvolvimento (dois terminais)

```powershell
# terminal 1 – API
cd backend
C:\opusfalso-dados\venv\Scripts\python -m uvicorn api:app --port 8000 --no-access-log

# terminal 2 – interface com recarga automática
cd frontend
npm run dev        # http://localhost:5173 (o Vite faz proxy de /api para a porta 8000)
```

### Testes automáticos

```powershell
cd backend
C:\opusfalso-dados\venv\Scripts\python -m unittest discover -s testes -v
```

`backend/testes/test_essenciais.py` cobre as partes delicadas em menos de 1 s, sem rede, sem GPU e sem
chamar o Claude: cortes na grade de quadros (nenhum quadro a mais ou a menos), mapeamento de tempos com a
abertura repetida, correções da transcrição, regras de capítulos do YouTube, respostas do Claude guardadas
(mesma pergunta não paga duas vezes; resposta inválida não fica guardada), "continuar de onde parou", textos
do post, validação tolerante, biblioteca de áudio, as travas de caminho (servir/apagar só dentro da pasta
certa) e a medição de volume e do início útil da música (com o ffmpeg).

Para ver/ajustar a composição da legenda animada: `cd remotion && npm run studio`.

---

## Interface web

| Tela | O que faz |
|---|---|
| **Início** | "O que vamos criar hoje?": drag & drop ou caminho local, instrução com chips clicáveis, seletor Falado/Gameplay, nº de clipes, duração (15-30 / 30-60 / 60-90 s), formato, preset, legenda animada e opções avançadas (layout, música, vídeo de apoio, refino por imagens). **Ctrl+Enter** gera. |
| **Vídeos longos** | Caminho local (recomendado) ou upload, Falado/Gameplay, modo **Enxugar o vídeo inteiro** ou **Melhores momentos** (3-20 min), instrução opcional e opções (abertura, zoom nos cortes, erros de gravação, imagens, tempo parado, legenda na tela, música, efeitos). O resultado mostra o vídeo, capítulos clicáveis, títulos, descrição e tags com botão de copiar, thumbnails e os arquivos (.mp4, .srt, .txt). |
| **Projetos** | Grade de cards (thumbnail, nome, data, status, nº de clipes, melhor nota), busca e filtro por status, exclusão com opção de apagar os clipes exportados. |
| **Processando** | Etapas (Transcrevendo → Analisando → Escolhendo trechos → Cortando → Legendando) com tempo de cada uma, % real, tempo estimado, cancelar e recomeçar. Mostra o que não foi atendido e os avisos. |
| **Resultados** | Grade de clipes com player (preview ao passar o mouse), nota viral em círculo colorido (verde ≥ 80, amarelo ≥ 60, vermelho abaixo) com a justificativa no tooltip, título editável inline, Baixar/Editar/Regenerar/Excluir. Ordenar por nota, ordem ou duração; filtrar por duração; seleção múltipla; **Baixar todos (ZIP)**; campo de **ajuste em linguagem natural** aplicado aos selecionados ("deixa mais curto", "troca a legenda pra verde"). |
| **Editor de clipe** | Player grande (clipe exportado ou vídeo original), linha do tempo com alças arrastáveis para início/fim, abas **Legendas** (estilo, preset, cor, texto editável por palavra), **Enquadramento** (formato, layout, deslocamento, zoom), **Título** e **Áudio** (normalizar, silêncios, música). Botões Salvar e Exportar. **Espaço** = play/pause. |
| **Estilos** | Lista de presets com preview ao vivo; criar, duplicar, editar (fonte, tamanho, cores, contorno, sombra, posição, palavras por vez, animação, título, barra) e excluir. |
| **Configurações** | Chave da API (mascarada), modelo, pasta de saída, GPU, modelo/idioma do Whisper, status do CUDA/Remotion e custo acumulado com histórico. |

A sidebar mostra a GPU, o estado do Claude ("configurado", "sem chave" ou "sem créditos") e o gasto acumulado.

---

## Uso pelo terminal

```powershell
cd backend
C:\opusfalso-dados\venv\Scripts\python editar.py video.mp4 "5 melhores momentos, legenda amarela, zoom" --modo falado
C:\opusfalso-dados\venv\Scripts\python editar.py jogo.mkv "3 clipes curtos, zoom nas kills" --modo gameplay
```

| Opção | Valores | Padrão |
|---|---|---|
| `--modo` | `falado`, `gameplay` | `falado` |
| `--clips` | número | 3 |
| `--duracao` | `15-30`, `30-60`, `60-90` | `30-60` |
| `--formato` | `9:16`, `1:1`, `16:9` | `9:16` |
| `--preset` | qualquer preset de `estilos.json` | `opus` |
| `--animada` | legenda animada (Remotion) | desligado |
| `--layout` | `auto`, `rosto`, `dupla`, `centro`, `inteiro`, `split` | `auto` |
| `--musica` | arquivo de música de fundo | — |
| `--apoio` | vídeo para a metade de baixo (gameplay sem facecam) | — |
| `--refinar` | gameplay: confirmar momentos enviando frames ao Claude | desligado |

A instrução em linguagem natural tem prioridade sobre as opções. O projeto criado pelo CLI também aparece na
interface. No fim, o terminal mostra os clipes com nota e justificativa, o que não foi atendido, os avisos
e o **custo estimado** da execução.

---

## O plano de edição (contrato Claude → código)

O Claude recebe uma **lista fechada** de campos e responde **apenas JSON**. O código valida com
pydantic (`modelos.PlanoEdicao`), aplica padrões ao que não foi pedido, corrige valores fora do intervalo
e, se o JSON vier inválido, **tenta de novo uma vez**, mandando o erro de volta.

```json
{
  "num_clips": 5,
  "duracao_min": 15,
  "duracao_max": 30,
  "formato": "9:16",
  "legenda": { "ativa": true, "estilo": "animada", "preset": "opus", "cor": "#FFE600" },
  "zoom_em_enfase": true,
  "remover_silencios": false,
  "musica_fundo": false,
  "musica_caminho": null,
  "musica_clima": null,
  "efeitos_sonoros": false,
  "normalizar_audio": true,
  "titulo_gancho": true,
  "nao_atendido": ["coloca um meme no final"]
}
```

- `legenda.cor = null` usa a cor de destaque do preset.
- Cores por nome ("amarelo", "verde"…) viram hex.
- Pedir música sem informar o arquivo sorteia uma faixa da [biblioteca de áudio](#biblioteca-de-áudio).
  Se a biblioteca estiver vazia, a música é desligada e o motivo vai para `nao_atendido`.

A **escolha de trechos** é uma segunda chamada, que devolve para cada clipe: início, fim, título gancho,
nota viral (0-100), justificativa curta, palavras de ênfase e emojis sugeridos. O código então
**encaixa os cortes nas bordas das palavras**, procura fins de frase para respeitar a duração pedida e
descarta sobreposições.

Outras chamadas usam o mesmo mecanismo: **ajustes em linguagem natural** (`AjusteClips`) e **refino por
frames** do gameplay (`ConfirmacaoFrames`).

### Planejador local (reserva)
Quando a API falha (sem chave, sem créditos, sem internet), `planejador_local.py` assume
automaticamente e um aviso aparece no projeto:
- **instrução → plano** por regras (números, faixas de duração, formatos, cores, presets, palavras-chave);
  cada trecho da frase que não casa com nenhuma regra vai para "não atendido";
- **escolha de trechos** por heurística: frases de gancho, palavras de impacto, números, tom emocional e
  ritmo de fala;
- no gameplay, escolhe só pela energia do áudio.

É bem mais simples que o Claude, mas mantém a ferramenta funcionando.

---

## Modo Falado × Modo Gameplay

### Falado (podcast, aula, talking head)
1. Transcreve com o Whisper e salva palavras com tempos.
2. O Claude escolhe os melhores trechos na duração pedida (título, nota, justificativa) e, na mesma
   chamada, marca **trechos para remover** dentro do clipe (frase repetida, começo em falso, desvio de
   assunto) e **corrige erros de transcrição** pelo contexto.
3. O FFmpeg corta, removendo silêncios e vícios se isso foi pedido, e o que o Claude marcou.
4. Reenquadra seguindo o rosto de quem fala.
5. Aplica a legenda por palavra e o título gancho.

### Gameplay
1. **Picos de energia no áudio**: combinação de volume (gritos, momentos intensos) e fluxo espectral
   (tiros, explosões), com no mínimo 6 s entre picos. Cada pico vira uma janela um pouco maior que o clipe.
2. **Transcrição da voz** do jogador, se houver comentário, com o segundo de cada frase.
3. **Escolha com imagens** (padrão; `--sem-imagens` desliga): cada candidato vai ao Claude com uma folha
   de 8 quadros (~600 tokens). Ele descarta menus e tempo morto, apara início e fim, marca buracos para
   remover e corrige a transcrição ("meu jeep" → "meu Deus").
4. **Revisão fina** de cada clipe escolhido: ~1 quadro por segundo, cada um rotulado como ação, reação,
   morto ou menu. O **código** (não o modelo) monta o clipe: preparação → ação → reação, sem fase de compra
   nem telas de fim de round, com jump cuts nos buracos. Se um lance não basta para a duração mínima,
   amplia a janela (até 2 x 30 s para cada lado, sem invadir outros clipes) e emenda os lances vizinhos
   numa **montagem**; movimentação só entra quando falta ação.
5. Com "remover silêncios", corta também o tempo morto pelo áudio (energia baixa e ninguém falando).

O layout padrão é **jogo** (recorte 4:5 grande no centro da mira, ~70% da tela) ou **split** quando há
**facecam** (detectada quando um rosto fica parado no mesmo lugar) ou **vídeo de apoio**.

**Custo típico** (Sonnet 5.5, esforço baixo): ~US$ 0,02 na escolha + ~US$ 0,005 por clipe na revisão,
ou seja ~US$ 0,035 para 3 clipes. Em Configurações, "Modelo da revisão fina" = Haiku corta a revisão pela
metade, mas deixa passar inimigos pequenos. Respostas com um item fora do formato (ex.: `"word"` em vez de
`"palavra"`) são aproveitadas, sem repetir a chamada.

---

### Vídeos longos (YouTube)

A aba **Vídeos longos** (`longo.py`) tem dois modos:

| | Fala (podcast, aula, vlog) | Gameplay (live, gravação) |
|---|---|---|
| **Enxugar o vídeo inteiro** | Tira silêncios e vícios e, numa chamada com a transcrição inteira, o Claude marca **erros de gravação** (frase repetida: fica a última tentativa; começo em falso; "corta isso"; desvios) e os **capítulos** | O Claude rotula 1 quadro a cada 3 s (folhas de 32, 3 em paralelo) e saem **menus, loading, fase de compra, telas de fim de round** e **tempo parado** (15 s+); sem imagens, corta pelo áudio. Capítulos nas pausas longas (entre partidas), com nomes dados pelo Claude pela narração |
| **Melhores momentos** | O Claude escolhe trechos autocontidos de 30 s a 4 min que somam a duração pedida | Os mesmos passos dos clipes (picos de áudio → folhas de quadros → revisão fina), com 20-45 s por momento |

Nos dois modos:
- **Abertura com o melhor momento**: teaser de 5-25 s antes de começar (fala: a frase mais forte; gameplay:
  o pico de energia).
- **Zoom nos cortes** com moderação: punch-in de 15% (fala) ou 10% (gameplay) alternado nos cortes secos,
  trocando no máximo a cada 6 s (zoom em toda frase cansa quem assiste vídeo longo).
- Na compilação, cada momento abre com **flash branco**, **título na tela** e (opcional) **whoosh**.
- Com música e mais de uma faixa no clima, a **faixa troca no começo dos capítulos** (crossfade de 3 s,
  capítulos de 45 s ou mais): uma faixa só em loop por meia hora cansa.
- Saída em `<pasta de saída>/<nome>/`: `<nome>_editado.mp4` (16:9, até 1080p, **capítulos dentro do MP4**),
  `<nome>_editado.srt` (legenda para subir no YouTube) e `<nome>_youtube.txt` (3 títulos, descrição com os
  capítulos no formato do YouTube e tags), mais 3 sugestões de thumbnail.
- Capítulos seguem as regras do YouTube: o primeiro em 0:00, cada um com 10 s ou mais.

**Revisar a edição.** As decisões ficam salvas no projeto (`edicao`: o que saiu e por quê, capítulos,
momentos, ritmo, abertura, correções da transcrição). Na página do vídeo, "Revisar a edição" lista cada trecho
removido com o motivo ("take repetido", "desvio de assunto", "bastidor", "menu, loading ou fase de compra",
"tempo parado", "tela preta"), a fala (ou uma miniatura, no gameplay) e uma prévia do original. Dá para devolver
trechos, mudar o **ritmo** (natural/dinâmico/rápido: quanto de pausa fica entre as frases), tirar a abertura e
renomear/remover capítulos ou momentos. "Aplicar e remontar" monta de novo **sem chamar o Claude** e só
re-renderiza os blocos que mudaram (os outros vêm do cache em `projetos/<id>/tmp/longo`).

**Também sai:** legenda .srt **corrigida** (o Claude corrige a transcrição na mesma chamada; no gameplay, uma
chamada só com o texto da narração), 3 thumbnails 1280x720 com o texto de impacto em Anton (quadros do vídeo
original, sem legenda queimada; na fala, com o rosto grande e o texto do lado oposto) e o botão **Gerar
clipes curtos**, que abre a tela inicial com o mesmo vídeo (a transcrição já está em cache).

Teste de referência (podcast sintético com 5 problemas plantados): o Claude achou os 5 (take repetido,
"vou falar de novo", começo em falso, desvio de assunto, "corta essa parte") sem remover nada do conteúdo, por
US$ 0,01. Um vídeo de 1 h (720p) foi processado em 11,5 min (4,4 de transcrição, 6,6 de render).

**Render em blocos** (`editor_ffmpeg.renderizar_bloco` + `juntar_blocos`): cada bloco é um pedaço contínuo
do original (até ~6 min, sem atravessar buracos grandes), com os cortes secos feitos por `select` na grade
de quadros de 1/30 s e o áudio fatiado em pacotes de exatamente 1 quadro (1600 amostras): vídeo e áudio
cortam nos mesmos pontos e **não dessincronizam**, mesmo com centenas de cortes. Os blocos saem em MKV com
áudio PCM e são juntados **sem recodificar o vídeo**; só o áudio é mixado no fim (-14 LUFS, música com
ducking, efeitos). Os filtros vão num arquivo (`-/filter_complex`), então não esbarram no limite de linha de
comando do Windows.

---

## Reenquadramento e layouts

Em duas passadas sobre o clipe cortado:
1. **Análise**: detecta rostos ~6× por segundo (YuNet do OpenCV; troca sozinho para MediaPipe e depois
   Haar se acertar pouco), liga as detecções em "trilhas" (pessoas) e mede o **movimento da boca** de cada
   uma para saber quem está falando. A troca de falante tem histerese de ~0,8 s.
2. **Render**: a câmera virtual passa por mediana, **zona morta** (não se mexe por pouco), aproximação
   suave e filtro gaussiano. Na troca de falante há um corte seco. Os frames vão direto para o FFmpeg, que
   junta o áudio e queima a legenda ASS.

| Layout | Uso |
|---|---|
| `auto` | Escolhe conforme o modo e os rostos encontrados |
| `rosto` | Segue quem fala (alterna entre pessoas) |
| `dupla` | Duas pessoas: uma em cima, outra embaixo (split-screen) |
| `centro` | Recorte fixo, com deslocamento horizontal manual |
| `inteiro` | Vídeo inteiro no meio, fundo desfocado |
| `split` | Gameplay em cima, facecam ou vídeo de apoio embaixo |

Saída: 1080×1920 (9:16), 1080×1080 (1:1) ou 1920×1080 (16:9), sempre a **30 fps**.

### Templates visuais

Na tela inicial, a seção **Template visual** tem cartões com prévia animada. Clicar num template
preenche de uma vez: estilo e cor da legenda, legenda animada, formato, enquadramento, duração, título
gancho, barra de progresso, zoom, remoção de silêncios, música (clima) e efeitos sonoros. Dá para ajustar
qualquer opção depois; a instrução em texto continua valendo por cima de tudo.

| Template | Legenda | Destaques |
|---|---|---|
| Podcast viral | Hormozi, animada | rosto, zoom, sem pausas, música calma, efeitos |
| Gameplay insano | Gamer, animada | 15-30 s, zoom e impacto nas kills, música energética |
| Storytime | Cinema, animada | legenda dourada discreta, música tensa |
| Meme / reação | Neon, animada | palavras no meio da tela, música engraçada, efeitos |
| Aula / tutorial | Minimalista, simples | 60-90 s, sem música nem efeitos |
| YouTube horizontal | Minimalista, simples | 16:9, sem título |

Os templates ficam em `backend/templates.json`. **"Salvar opções atuais como template"** cria um novo
com o que está no formulário; a lixeira no cartão exclui.

### Biblioteca de áudio

Pastas em `C:\opusfalso-dados\audio` (criadas na primeira execução, com um `LEIAME.txt`). Basta soltar
arquivos `mp3`, `wav`, `m4a` ou `ogg`. Para começar sem procurar música, **Configurações → Biblioteca de
áudio → Baixar** coloca 16 faixas instrumentais (111 MB) nas pastas de clima, 3 ou 4 por clima, de
HoliznaCC0, Komiku e Loyalty Freak Music (Free Music Archive). Todas são **CC0** (domínio público, licença
conferida na página de cada faixa): podem ir em vídeo monetizado, sem pedir licença nem dar crédito. A lista
fica em `backend/recursos/pacote_musicas.json` e os créditos, em `audio\musica\CREDITOS.txt`.

| Pasta | Uso |
|---|---|
| `musica\energetica`, `tensa`, `calma`, `engracada`, `epica` | Música de fundo. O Claude escolhe o clima de cada clipe; o planejador local usa `energetica` no gameplay e `calma` na fala. Se o clima estiver vazio, vale qualquer faixa. |
| `efeitos\whoosh` | Entrada do título gancho |
| `efeitos\impacto` | Pico do gameplay (kill, explosão) |
| `efeitos\pop` | Zoom nas palavras de ênfase |

- A faixa é sorteada **por clipe** e é sempre a mesma para o mesmo clipe (re-renderizar não troca a música).
  No editor, a aba **Áudio** permite trocar a faixa ou ligar/desligar os efeitos.
- **Volume igualado**: cada faixa é medida uma vez (EBU R128, cache em `cache\musicas.json`) e levada a
  -14 LUFS antes do volume de fundo (35% nos clipes, 22% no vídeo longo). Faixas de fontes diferentes chegam
  a variar 20 dB entre si; sem isso, umas estouravam e outras sumiam. Medido no mix: a música fica ~13 dB
  abaixo do som do jogo e ~25 dB abaixo da fala (o *ducking* abaixa mais quando há voz).
- **Cortes na batida** (gameplay com música): cada corte seco da montagem é puxado para a batida mais
  próxima da faixa, mexendo só no fim do trecho anterior (no máximo meio tempo e 0,35 s, sem cortar palavra
  e sem invadir o trecho seguinte). As batidas são achadas uma vez por faixa, por programação dinâmica sobre o
  fluxo espectral (o método do librosa); faixa com batida pouco marcada (confiança < 0,3) não mexe nos cortes.
  Em cliques sintéticos de 95 a 174 BPM, o andamento sai certo e o erro fica abaixo de 25 ms (menos de 1 quadro).
- **Início útil**: nos clipes, a música começa no primeiro ponto em que fica "cheia" por 3 s seguidos
  (pula introdução quieta: num clipe de 30 s, 20 s de introdução seriam o clipe inteiro sem música), com
  fade de entrada e de saída.
- Os efeitos ficam a pelo menos 2,5 s um do outro, no máximo 6 por clipe, e cada um é cortado em 2 s.
- Fontes grátis: Pixabay Music / Sound Effects, YouTube Audio Library, Freesound.org (confira a licença
  de cada som). Evite música famosa: as redes silenciam ou derrubam o vídeo.

---

## Legendas e estilos

- **Simples (ASS)**: gerada em `legendas.gerar_ass()` e queimada pelo libass. Já inclui destaque da
  palavra falada, pop de escala e título com caixa colorida. É a opção rápida.
- **Animada (Remotion)**: `legendas.renderizar_remotion()` chama `remotion render` com as props em JSON
  (grupos de palavras, estilo, título, barra) sobre o vídeo já reenquadrado. Tem entrada com *spring*,
  emoji animado e contorno com `paint-order`. Leva cerca de 3× a duração do clipe. Se falhar, o clipe sai
  com a legenda simples e um aviso.

### Presets (`backend/estilos.json`)

```json
"opus": {
  "nome": "Opus",
  "fonte": "Montserrat Black", "arquivo_fonte": "Montserrat-Black.ttf",
  "tamanho": 88, "maiusculas": true,
  "cor_texto": "#FFFFFF", "cor_destaque": "#FFE600", "cor_contorno": "#000000",
  "contorno": 9, "sombra": 5, "posicao_y": 0.68,
  "palavras_por_vez": 3,
  "animacao": "pop", "escala_pop": 1.15, "duracao_pop_ms": 120,
  "titulo": { "cor_fundo": "#FFE600", "cor_texto": "#000000", "tamanho": 64 },
  "barra_progresso": { "ativa": true, "cor": "#FFE600", "altura": 10 }
}
```

| Preset | Estilo |
|---|---|
| **opus** | Montserrat Black, amarelo, pop, 3 palavras |
| **hormozi** | Anton gigante, verde, pop forte, 2 palavras |
| **minimalista** | Poppins SemiBold, sem maiúsculas, revelar suave, 4 palavras |

- **Novo preset**: copie um bloco no JSON ou use a tela Estilos.
- `animacao` aceita `pop`, `fade` (revelar) ou `nenhuma` (só cor).
- **Nova fonte**: coloque o `.ttf` em `C:\opusfalso-dados\fontes\`. Ela aparece na tela Estilos com o
  nome lido do próprio arquivo, que é o mesmo nome usado pelo libass.

A legenda fica centralizada no terço inferior (`posicao_y` ≈ 0,64-0,72), longe das áreas de interface do
TikTok/Reels.

---

## API HTTP

Base: `http://127.0.0.1:8000`. Documentação interativa em `/docs`.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/sistema` | GPU, CUDA, Remotion, chave, fila, último erro do Claude |
| GET/PUT | `/api/config` | Configurações (a chave volta mascarada) |
| GET/DELETE | `/api/custos` | Custo acumulado e histórico / zerar |
| GET | `/api/estilos` | Presets |
| PUT/DELETE | `/api/estilos/{nome}` | Criar/editar ou excluir preset |
| GET | `/api/fontes`, `/api/fontes/{arquivo}` | Fontes disponíveis (com nome interno) |
| GET | `/api/projetos` | Lista resumida |
| POST | `/api/projetos` | Cria projeto (multipart: `arquivo` **ou** `caminho`, que também aceita um link do YouTube; `instrucao`, `modo`, `opcoes` em JSON, com `num_clips` até 100) e enfileira |
| POST | `/api/longos` | Cria vídeo longo (mesmo formato; `opcoes`: `modo_longo` enxugar/melhores, `alvo_min`, `abertura`, `zoom`, `legenda`, `preset`, `musica`, `efeitos`, `ver_imagens`, `cortar_parado`, `remover_erros`) |
| GET | `/api/projetos/{id}/longo/video` · `/longo/srt` · `/longo/texto` · `/longo/thumb/{k}` | Arquivos do vídeo longo |
| PUT | `/api/projetos/{id}/edicao` | Revisão do vídeo longo (`ritmo`, `abertura_ativa`, `remocoes`, `capitulos`, `momentos`) e remontagem |
| GET | `/api/projetos/{id}/previa?inicio&fim` · `/quadro?t` | Prévia MP4 de um trecho do original / miniatura de um quadro |
| POST | `/api/projetos/{id}/refazer-arquivos` | Refaz os vídeos que sumiram da pasta de saída (sem chamar o Claude) |
| GET | `/api/armazenamento` | Espaço livre e uso por parte (vídeos, temporários, saídas, modelos) |
| POST | `/api/armazenamento/juntar` · `/limpar` | Junta vídeos repetidos / apaga temporários |
| GET/DELETE | `/api/projetos/{id}` | Detalhes (com % e tempo restante) / excluir (`?apagar_saida=true`) |
| POST | `/api/projetos/{id}/cancelar` · `/reprocessar` · `/abrir-pasta` | Controle do projeto (`/reprocessar` continua de onde parou se o projeto está com erro ou cancelado; num projeto pronto, ou com `?do_zero=true`, refaz do zero) |
| POST | `/api/audio/pacote` | Baixa em segundo plano o pacote de músicas CC0 (progresso em `GET /api/audio`, campo `pacote`) |
| GET · DELETE | `/api/audio/arquivo?caminho=` | Toca / apaga uma faixa (só arquivos de áudio dentro da biblioteca; faixa do pacote apagada não é oferecida de novo) |
| GET | `/api/projetos/{id}/thumb` · `/video` · `/palavras?inicio&fim&cid` | Miniatura, vídeo original, palavras do trecho |
| GET | `/api/projetos/{id}/clips/{cid}/video` (`?download=true`) · `/thumb` | Clipe (com suporte a Range) |
| PATCH | `/api/projetos/{id}/clips/{cid}` | Edita título, início/fim, config, palavras editadas |
| POST | `/api/projetos/{id}/clips/{cid}/renderizar` · `/regenerar` | Exportar de novo / trocar por outro momento |
| DELETE | `/api/projetos/{id}/clips/{cid}` | Exclui clipe |
| POST | `/api/projetos/{id}/ajustar` | `{pedido, clips}`: ajuste em linguagem natural |
| GET | `/api/projetos/{id}/zip?clips=a,b` | ZIP com os clipes |

Jobs longos rodam numa **fila de uma thread**: um por vez, porque a GPU de 4 GB não aguenta dois
Whispers/renders em paralelo. A interface acompanha o progresso por **polling**: 1 s enquanto algo roda,
8 s parado. Se o servidor reiniciar no meio de um job, o projeto fica marcado como interrompido, com o
botão "Tentar de novo".

---

## Dados em disco

Tudo fica em `C:\opusfalso-dados` (troque com a variável `OPUSFALSO_DADOS`), fora do OneDrive:

| O quê | Onde |
|---|---|
| Clipes prontos | `saida\<nome_do_video>\clip_01.mp4 …` (pasta configurável; `_2`, `_3` se o nome já existir) |
| Projeto | `projetos\<id>\meta.json`, `thumb.jpg`, `thumbs\`, `tmp\` (cortes, .ass), `original.<ext>` se veio por upload |
| Cache | `cache\<hash>\transcricao.json`, `audio.json` |
| Configurações | `config.json` |
| Custos | `custos.json` |
| Fontes / modelos | `fontes\`, `modelos\` (inclui o Whisper) |
| Venv | `venv\` |
| Temporários do Remotion | `remotion_public\` |
| Biblioteca de áudio | `audio\musica\<clima>\`, `audio\efeitos\<tipo>\` |

Vídeos enviados por **caminho local** não são copiados: o processamento lê direto do lugar onde eles estão.
Vídeos enviados pela interface ficam em `videos\<hash>.<ext>`, **um arquivo por conteúdo**: enviar o mesmo
vídeo de novo não ocupa espaço outra vez, e o arquivo só é apagado quando o último projeto que o usa sai.

### Armazenamento

Em **Configurações → Armazenamento**: espaço livre, quanto ocupam vídeos, temporários, saídas e modelos, e
dois botões: **Juntar vídeos repetidos** (cópias antigas iguais, comparadas byte a byte, viram um arquivo só)
e **Limpar temporários** (cortes intermediários, blocos em cache e prévias; são refeitos sozinhos quando
precisar). Com menos de 5 GB livres aparece um aviso (na barra lateral e no projeto); com menos de 2 GB o app
não começa projetos novos. Ao excluir um projeto com "apagar os arquivos exportados", só é apagada a pasta de
saída que está dentro da pasta configurada **e** tem a marca `.projeto` daquele projeto.

Se os arquivos da pasta de saída forem apagados ou movidos, o projeto mostra **Refazer os arquivos**: clipes
são renderizados de novo e o vídeo longo é remontado com a edição salva, sem custo na API.

---

## Configuração

Tela **Configurações** ou `C:\opusfalso-dados\config.json`:

| Chave | Padrão | Descrição |
|---|---|---|
| `api_key` | `""` | Vazio = usa `ANTHROPIC_API_KEY` |
| `modelo` | `claude-sonnet-5-5` | Também: `claude-sonnet-4-6`, `claude-opus-5-5`, `claude-haiku-4-5` |
| `pasta_saida` | `C:\opusfalso-dados\saida` | Onde os clipes são salvos |
| `usar_gpu` | `true` | CUDA na transcrição |
| `modelo_whisper` | `large-v3-turbo` | `medium`, `small`… |
| `idioma` | `""` | Vazio = detectar; ou `pt`, `en`, `es` |

---

## Custos da API

Cada chamada registra tokens de entrada e saída × preço do modelo (tabela em `custos.py`). O total
aparece na sidebar, em Configurações, no card do projeto e no fim do CLI.

**Vídeos longos:** fala ~US$ 0,05-0,08 por hora de vídeo (uma chamada com a transcrição inteira);
gameplay enxugado ~US$ 0,20 por hora com imagens (~US$ 0,01 sem); compilação de gameplay ~US$ 0,15-0,25.
Um vídeo de 5 min custou US$ 0,01 (fala), US$ 0,03 (gameplay enxugado) e US$ 0,05 (melhores momentos).

Cada resposta válida do Claude fica guardada no projeto (`projetos\<id>\respostas`), pela impressão digital
do pedido: continuar um processamento interrompido não paga de novo o que já foi respondido.

Um projeto típico faz 2 chamadas: plano + escolha de trechos. Com o Sonnet 5.5, isso custa **centavos de
dólar** (a legenda do post e as hashtags acrescentam ~US$ 0,001 por clipe); o maior peso é o tamanho da transcrição. Uma instrução vazia pula a primeira chamada. O refino por
frames é opcional porque envia imagens.

---

## Solução de problemas

| Sintoma | Causa / solução |
|---|---|
| "API key is not scoped to a workspace" (400) | Chave criada no nível da organização: informe o ID do workspace (`wrkspc_...`) em Configurações. |
| Aviso "Claude sem créditos" | Conta da Anthropic sem saldo. Adicione créditos em console.anthropic.com; enquanto isso, o planejador local é usado. |
| "Chave da API inválida (401)" | Confira a chave em Configurações. |
| Transcrição lenta | Veja em Configurações se o CUDA está ativo. Sem GPU, use `medium` ou `small`. |
| Erro de memória na GPU | O código já tenta `medium` e depois a CPU; feche outros programas que usam a GPU. |
| Legenda animada falhou | Rode `npm install` em `remotion/`. O clipe sai com a legenda simples e um aviso. |
| Rosto não encontrado | Use o layout `inteiro` ou `centro` (com deslocamento) no Editor. |
| Interface em branco em :8000 | Rode `npm run build` em `frontend/`. |
| Servidor offline na sidebar | A API não está rodando: use `iniciar.bat` ou o uvicorn. |

Logs: o terminal do uvicorn mostra cada etapa (detector de rosto usado, layout, tokens, custo…).

---

## Limitações conhecidas

- O **tempo estimado** subestima quando a legenda é animada (o Remotion é a etapa mais lenta).
- A **troca de falante** entre duas pessoas usa uma heurística de movimento da boca e ainda não foi validada
  com vídeos reais de duas pessoas.
- O modelo de curta distância do MediaPipe falha com rostos pequenos; por isso o YuNet é o detector principal.
- Emojis só aparecem na legenda **animada**, porque o libass não desenha emoji colorido.

---

## Histórico do desenvolvimento

Construído em etapas, cada uma testada com vídeos sintéticos (fala gerada por TTS em pt-BR com um rosto em
movimento; gameplay com explosões e facecam):

1. Modo falado: transcrever, escolher cortes, cortar ✅
2. Instrução em linguagem natural → plano JSON (pydantic, nova tentativa, "não atendido") ✅
3. Modo gameplay com picos de áudio ✅
4. Reenquadramento vertical + legenda simples (ASS) ✅
5. Backend FastAPI + projetos em disco + fila de jobs ✅
6. Interface: layout, Home com upload, Processando com progresso real ✅
7. Tela de Resultados ✅
8. Meus Projetos e Configurações ✅
9. Legenda animada com Remotion, zoom automático, presets de estilo ✅
10. Editor de clipe e tela Estilos ✅
11. Refino com frames enviados ao Claude ✅ (implementado; depende de créditos na API)

Extras adicionados no caminho: planejador local de reserva, fallback automático de detector de rosto, NVENC,
ajustes em linguagem natural, regenerar clipe por outro momento e aviso de estado do Claude na interface.
