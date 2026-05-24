# Material das aulas — Asteroids Multiplayer

Esta pasta é a trilha didática do projeto. Cada arquivo cobre uma fase do desenvolvimento, na ordem em que as fases vão acontecendo no repositório.

A proposta é simples: o projeto serve como veículo para ensinar três coisas amarradas — programação em Python moderno, princípios de sistemas distribuídos, e os padrões clássicos de arquitetura de jogos multiplayer. Cada aula traz a teoria que você precisa, mostra as decisões de projeto que tomamos para chegar onde chegamos, e caminha pelo código entregue na fase.

## Pré-requisitos

- Python 3.10 ou mais novo (3.13 recomendado, fixado via `.python-version`).
- Familiaridade com programação orientada a objetos e tipagem básica.
- Noção de TCP/IP — o que é um socket, o que é uma porta, o que é cliente e servidor.
- O jogo single-player do repositório [asteroids_single-player](https://github.com/jucimarjr/asteroids_single-player) rodando localmente. É o ponto de partida congelado.

## Ordem das aulas

| Arquivo | Fase | Conteúdo principal |
|---|---|---|
| [00-overview.md](00-overview.md) | — | Visão geral do projeto, os dois repositórios, o roteiro das cinco fases |
| [01-foundation.md](01-foundation.md) | F1 | Desacoplar `core/` de pygame, separar mundo de viewport, criar câmera, montar testes e CI |
| [02-server-lonely.md](02-server-lonely.md) | F2 | Servidor headless com WebSocket via `asyncio`, primeiro cliente conecta |
| `03-multi-player.md` | F3 | Vários jogadores numa sala, deathmatch, respawn |
| `04-match-lifecycle.md` | F4 | Tempo de partida, frag limit, fim de match, espectador |
| `05-multi-room.md` | F5 | Servidor hospeda várias salas em paralelo, sistema de tokens |

Aulas com nome em itálico ainda não foram escritas. Cada uma será publicada quando a fase correspondente for entregue.

## Como acompanhar

A trilha funciona em duas leituras: rápida e profunda.

**Leitura rápida** (45 min por fase): conceitos teóricos + decisões de projeto + diagrama de execução. Suficiente para entender o porquê e a forma do que foi feito.

**Leitura profunda** (2-3 h por fase): adiciona o passo a passo pelo código entregue, os testes que verificam o comportamento, e os exercícios sugeridos. Exige checar arquivos no repositório enquanto lê.

Cada arquivo deixa explícito o link entre o texto e os PRs do GitHub que materializaram aquela fase. Quem quiser pode ler PR por PR e seguir o pensamento na ordem real em que foi escrito.
