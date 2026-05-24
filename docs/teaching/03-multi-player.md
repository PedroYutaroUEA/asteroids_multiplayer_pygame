# 03 — Multi-player 1 room

A terceira fase tira o servidor da solidão. Os jogadores começam a se ver. Bullet de um pode matar a nave do outro. Cada frag vale +100. Morrer não é mais o fim, é um intervalo: três segundos depois a nave reaparece numa posição segura e a partida continua. O score acumula sem teto e ninguém vence ainda — fim de partida fica para a F4.

A fase fecha o gameplay essencial do deathmatch. Single-player não mexeu — `python main.py` continua dando três vidas, game over no fim e extra life a cada cinco mil pontos. O modo deathmatch é uma flag opt-in no construtor do `World`, ligada só pelo servidor.

Os quatro pull requests entregues:

| PR | Branch | Conteúdo |
|---|---|---|
| #12 | `feat/pvp-collision` | `_bullets_vs_ships` no `CollisionManager`, frag score, filtro de auto-kill |
| #13 | `feat/respawn-loop` | `World(deathmatch=True)`, dicts `respawning` e `deaths`, `_update_respawns` e `_respawn_player` |
| #14 | `feat/snapshot-events` | Snapshot ganha `respawning`, `deaths` e `events`; particles do cliente em rede voltam |
| #15 | `feat/scoreboard-hud` | `multiplayer/hud.py` com HUD local e scoreboard de todos; server envia `names` |

## 1. Conceitos teóricos

### Identidade do projétil

Num jogo single-player, todo projétil em cena é amigo. Os asteroides são alvos, os UFOs são inimigos, mas a bullet em si nunca tem dúvida sobre seu papel. Em deathmatch, a mesma bullet voadora pode matar você ou pode te dar um frag, dependendo de quem disparou.

A solução é dar identidade ao projétil. Cada `Bullet` carrega um `owner_id`. Quando uma bullet acerta uma nave, o resolvedor de colisão precisa de duas perguntas:

1. A bullet é de UFO? (`owner_id == UFO_BULLET_OWNER`, que vale `-10`.) Se sim, despacha pra rota antiga (`_ship_vs_ufo_bullets`). UFOs não dão frag para ninguém.
2. A bullet é de um jogador? (`owner_id > 0`.) Se sim, o atirador é o jogador identificado. Mas falta um filtro: a bullet pode estar no ar da própria nave que atirou. Atravessa sem ferir.

Esse último ponto é onde mora a maior parte das histórias de bug em jogos de tiro. "Por que minha bullet me matou?" geralmente é uma chamada de checagem mal escrita. O filtro `if bullet.owner_id == ship.player_id: continue` resolve para o nosso caso. O custo é um `continue` por par bullet/ship. O ganho é a coerência mental do código.

Existem variações. Em alguns jogos, a bullet do próprio jogador sai com `alive=False` para a própria ship por algumas dezenas de milissegundos; quando a bullet sai do raio da própria nave, vira `alive=True` novamente. O Asteroids original (1979) usava isso porque o jogador atirava do nariz da nave e a bullet começava colidindo consigo mesmo. No nosso caso, o `BULLET_SPAWN_OFFSET` em `core/entities.py:Ship._try_fire` já tira a bullet do volume da nave no instante do tiro; o filtro por `owner_id` resolve só o caso multiplayer.

### Respawn como reset parcial

Quando uma nave morre em deathmatch, o jogo precisa decidir o que fica e o que volta ao zero.

Fica: o score (o que você ganhou continua seu), o slot na partida (sua conexão permanece, sua linha no scoreboard permanece, seu nome permanece). Volta ao zero: posição (random safe), velocidade (parado), ângulo (canônico), cooldowns visuais (invuln pulsa pra te dar tempo de orientar).

Esse "reset parcial" é o motivo pelo qual respawn não é a mesma coisa que spawn. `World.spawn_player(pid)` zera score e dá lives — comportamento do jogador novo entrando. `_respawn_player(pid)` cria uma nave nova mas mantém o que já estava lá. As duas funções convivem dentro do `World` e cada uma serve a um momento.

Game over não existe em deathmatch. Single-player perde quando todas as vidas vão a zero; deathmatch não tem essa condição porque a contagem de vidas não está em jogo. O servidor passa `deathmatch=True` para o `World`, o construtor sabe que não vai gerenciar lives, e o método `_maybe_award_extra_life` ganha um guard `if self.deathmatch: return` logo no topo. A mesma classe atende os dois modos sem hierarquia.

### Estados ausentes vs estados marcados

Uma decisão de modelagem que aparece nesta fase: a nave esperando respawn **some** do dicionário `world.ships`. Não fica lá com uma flag `dead=True`.

A alternativa seria deixar a nave no dict e marcar:

```python
class Ship:
    ...
    dead: bool
    respawn_remaining: float
```

E o renderer precisaria de:

```python
for ship in world.ships.values():
    if ship.dead:
        continue
    draw(ship)
```

Por que escolhemos o oposto? Três razões:

1. **`client/renderer.py` continua intocado.** O renderer já itera por `world.ships.values()` e desenha tudo que está lá. Se uma nave saiu do dict, ela some da tela sem precisar de branch novo. A regra de "não modificar `client/`" preserva o single-player.
2. **Snapshot fica menor.** Uma nave morta carrega zero bytes de payload (não está em `ships`). Em vez dela, há uma entrada em `respawning: [{player_id, remaining}]` com 30 bytes. Em condições onde meia partida está em respawn, o snapshot é mais leve.
3. **Estado é mais expressivo.** "Não está em `ships`, está em `respawning`" carrega significado sem precisar olhar flags. Cada estrutura responde por uma coisa.

O custo é ter duas estruturas em vez de uma. Quando a fase precisa fazer cleanup numa desconexão, são dois `pop` em vez de um. Trade-off pequeno pelo isolamento de responsabilidades.

### Eventos transitórios vs estado contínuo

O snapshot que chega no cliente descreve o estado *agora*. Quem está vivo, onde, com que velocidade. Aplique o snapshot e o cliente sabe pintar o frame seguinte.

O que o snapshot **não** descreve é o que mudou. Se uma nave morreu entre o snapshot anterior e o novo, o snapshot novo só mostra que ela não está mais em `ships`. Para o jogador, o evento "explosão de nave aqui" é parte do conteúdo da partida — o cliente precisa pintar as partículas no ponto exato onde a nave morreu, e o cliente não tem como deduzir isso do snapshot sozinho (o snapshot anterior já não estava acessível, e a posição da morte pode ter sido em qualquer lugar do mundo).

O `World` do servidor mantém um buffer de eventos de spawn de partículas — `particle_events: list[tuple[str, Vec]]`. Toda vez que `_spawn_particles(pos, kind)` é chamado, antes de spawnar as partículas locais, o buffer ganha uma entrada `(kind, pos)`. O snapshot serializa esse buffer como `events: [{kind, x, y}, ...]` e o cliente, ao decodificar, chama `world._spawn_particles(Vec(x, y), kind)` para cada um.

A separação entre estado contínuo (snapshot) e eventos transitórios (events) é um padrão geral em networking de jogos. Estado contínuo é idempotente: chegou um snapshot, perdeu um, chega o próximo, tanto faz — o jogador vê o estado atual. Eventos transitórios são informativos: chegou um, perdeu um, chega o próximo, mas o que aconteceu naquela janela é perdido. Para particles, perda é invisível (uma explosão a menos no canto do mundo, ninguém nota). Para algo crítico como "match end" ou "wave start", a perda seria fatal — esses eventos teriam que ter persistência no estado para garantir entrega.

Carregamos os events embebidos no snapshot. Uma mensagem por broadcast. Em redes com perda alta, isso significa que se um snapshot é dropado, todos os events daquele tick somem junto. Em LAN, perda é negligível. Em F5 ou em produção real, a decisão pode voltar a ser revisitada.

### Scoreboard como projeção pura

Cada cliente vê o score de todos os jogadores. Isso é possível porque o servidor manda `scores: dict[pid, int]` no snapshot, e o snapshot é entregue para todo cliente conectado.

Não é decisão "porque dá", é decisão "porque escolhemos". Existem jogos onde score (ou outros agregados) são privados — cada jogador vê só o próprio, e o ranking aparece no fim. Em deathmatch clássico, a competição é visível em tempo real: você vê quem está liderando, quem está atrás, quem você passou recentemente. A tensão da partida vive nesse feedback contínuo.

A consequência arquitetural é que o servidor não censura o snapshot por destinatário. Todos recebem o mesmo `scores`, `names`, `respawning`, `deaths`. Em jogos com fog of war (a posição dos oponentes só é visível se eles estão no seu raio de visão), o servidor envia snapshots **customizados** por cliente, com o que aquele cliente tem direito de ver. Aqui não. Em mapa pequeno, sem cobertura, sem inimigo invisível, a transparência total casa com o ritmo do jogo.

A função `scoreboard_lines(world, local_player_id)` em `multiplayer/hud.py` é pura: dado o estado do `world` e o pid do jogador local, retorna a lista de linhas. Sem pygame. Sem state interno. O `draw_scoreboard` que vem depois é o casamento dessa função pura com a tela. Separa lógica de pintura — o teste exercita só a primeira.

## 2. Decisões e trade-offs

### +100 fixo por frag

Frag vale 100 pontos. Sem multiplicador, sem combo, sem bônus por headshot (não existe headshot em Asteroids). É a regra mais simples que faz o scoreboard ser coerente: maior número de frags → maior score.

A alternativa imediata seria "+50 × wave atual" (matar um oponente na wave 5 vale +250, na wave 1 vale +50). Daria à wave um peso que ela hoje não tem em deathmatch, e poderia gerar bolões de "matar tarde vale mais". Vai ficar como exercício. Outra alternativa seria diferenciar frag e suicídio (sair atravessando asteroide para evitar dar +100 ao oponente teria um custo). Hoje, o `_ship_vs_asteroids` não premia ninguém pela morte da nave — o atirador (ninguém) não ganha 100. O suicida só ganha um respawn.

A regra "100 fixo, sem variantes" tem outro mérito: o cliente que vê o `score` no scoreboard sobe sempre em múltiplos de 20 (asteroide L), 50 (M), 100 (S e frag), 200 (UFO grande) ou 1000 (UFO pequeno). O número fala por si.

### Respawn de 3 segundos

A janela de respawn é o castigo natural do deathmatch. Curta demais e o jogo vira "atira no mesmo lugar até acertar"; longa demais e o jogador fica entediado na tela esperando.

Três segundos é uma janela que dá tempo de a explosão acontecer visualmente, do scoreboard atualizar, e do oponente reposicionar a nave para o próximo ataque. Em jogos com mapas grandes e movimento lento (Battlefield: 10s), respawn é maior; em jogos rápidos com mapas pequenos (Quake III: 1.6s), é menor. Asteroids está mais perto do segundo grupo — o mundo é grande, mas a nave acelera rápido e a tela cobre 1280×720 dele a qualquer momento. Três segundos balanceia o "respira" com o "volta logo".

O número é uma constante em `core/config.py` (`RESPAWN_DELAY = 3.0`). Mudar é uma linha — ajuste por sentimento na hora do playtest.

### Posição segura no respawn

Reaproveitamos `_find_safe_hyperspace_pos`. A função foi escrita na F1 para o hyperspace do jogador (botão `Shift` teleporta para uma posição random sem asteroide em cima). O respawn precisa exatamente disso: pegar uma posição livre.

A função recebe um `Ship` para extrair o raio. No respawn, ainda não temos a nave nova — ela vai ser criada com a posição que a função retornar. Solução simples: criar uma nave temporária só pelo raio, descartar logo:

```python
def _respawn_player(self, pid: PlayerId) -> None:
    temp = Ship(pid, Vec(0, 0))
    pos = self._find_safe_hyperspace_pos(temp)
    ship = Ship(pid, pos)
    ship.invuln.reset(C.SAFE_SPAWN_TIME)
    self.ships[pid] = ship
```

Não é elegante, mas é honesto: a função foi pensada para o caso "tem uma nave, achar onde colocar". Mudar a assinatura para `_find_safe_hyperspace_pos(radius: float)` seria mais limpo, mas pegaria também o site de chamada do hyperspace. R2 — abstração antes da segunda repetição. Quando aparecer um terceiro chamador (espectador retomando, talvez), refatorar.

### Lives sumiram em DM, deaths apareceram

Em single-player, `lives` é o recurso finito que termina o jogo. Você começa com 3, ganha 1 a cada 5000 pontos, morre quando todas se esgotam. Em deathmatch, respawn é infinito, então `lives` perdeu o papel.

Trocamos por `deaths`. Cada jogador acumula um contador de mortes. O scoreboard mostra K/D natural: score (proxy de kills) e D (deaths). O servidor envia `deaths: {pid: count}` no snapshot, o cliente popula `world.deaths`, o scoreboard lê.

Para preservar single-player, `world.lives` continua existindo. Em deathmatch ele só nunca é decrementado. O dict fica preso no valor inicial e o snapshot transmite mesmo assim — três bytes de payload extra por jogador, irrelevante. Manter o campo é mais simples do que removê-lo condicionalmente do snapshot.

### Embed de events no snapshot

Considerei mandar events como mensagem separada (constante `EVENT` que a F2 deixou definida mas não usava). Vantagens: separação semântica forte entre "estado" e "transição", possibilidade de mandar events fora dos broadcasts de snapshot, controle independente sobre frequência.

Desvantagens: dobra o trabalho do cliente (duas filas para drenar), dobra o trabalho do servidor (duas envelopes por broadcast), e introduz a pergunta "events antes ou depois do snapshot?" — que tem resposta certa em LAN (qualquer ordem funciona) mas vira problema em redes reais (snapshot pode chegar antes do event que descreve a transição para aquele snapshot, e o cliente teria que reordenar).

Embed dentro do snapshot é a versão mais simples. Uma mensagem, um lugar para olhar, sem coordenação. O preço é semântico: events agora são uma propriedade do snapshot, não uma mensagem própria. Para deathmatch local de LAN, o preço é trivial. A constante `EVENT` ficou morta e saiu — código que ninguém usa só atrapalha.

### HUD do cliente em rede vive em `multiplayer/`

O HUD do cliente em rede tem três linhas no canto esquerdo (`SCORE`, `DEATHS`, `WAVE`) e um scoreboard no canto direito (todos os jogadores). O single-player tem uma linha no canto esquerdo (`SCORE`, `LIVES`, `WAVE`) e nenhum scoreboard.

Dois HUDs diferentes para dois modos diferentes. Como evitar que mudar um quebre o outro?

A escolha foi isolar. `client/renderer.py` continua dono do HUD single-player (`draw_hud(score, lives, wave, ...)`). Não tocamos nele. O HUD do cliente em rede vive em `multiplayer/hud.py`, com suas próprias funções. O cliente em rede importa `from multiplayer.hud import draw_local_hud, draw_scoreboard` e usa.

A duplicação aqui é mínima — duas linhas de `font.render` em cada lado. Quando os HUDs convergirem em padrão (digamos, em F5 quando o espectador também precisar de uma versão), aí faz sentido extrair um `hud_common.py`. Hoje, dois lugares pequenos resolvem mais do que um lugar grande com flags.

## 3. Walkthrough do código entregue

### `core/collisions.py:_bullets_vs_ships`

O novo método dispara o PvP:

```python
def _bullets_vs_ships(self, ships, bullets, result):
    for ship in ships.values():
        if ship.invuln.active:
            continue
        for bullet in bullets:
            if not bullet.alive or bullet.owner_id <= 0:
                continue
            if bullet.owner_id == ship.player_id:
                continue
            if (bullet.pos - ship.pos).length() < (bullet.r + ship.r):
                bullet.kill()
                if ship.shield.active:
                    continue
                result.score_deltas[bullet.owner_id] = (
                    result.score_deltas.get(bullet.owner_id, 0) + C.FRAG_SCORE
                )
                result.ship_deaths.append(ship.player_id)
                break
```

A estrutura espelha `_ship_vs_ufo_bullets` (modelo da F1) com três diferenças. Primeira: o filtro `owner_id <= 0` em vez de `owner_id != UFO_BULLET_OWNER`. UFOs continuam tratados pelo handler antigo; aqui só player bullets entram. Segunda: o filtro `bullet.owner_id == ship.player_id` — auto-kill. A bullet do próprio jogador atravessa sem ser consumida (`continue` mantém ela viva no loop). Terceira: `break` no fim em vez de `return`. Várias naves podem morrer no mesmo tick em deathmatch, e cada uma precisa receber a chance de processar suas bullets.

A ordem no `resolve()` é importante para uma sutileza: o método entra **depois** de `_ufo_vs_player_bullets` (que processa bullets contra UFOs primeiro — UFOs morrem antes de bullets considerarem naves) e **antes** de `_ship_vs_asteroids`. Em colisões simultâneas (asteroide e bullet acertando a mesma nave no mesmo frame), o `ship_deaths` pode ganhar o mesmo pid duas vezes. O `_ship_die` lida com isso: a segunda chamada encontra o pid já fora de `ships`, o `pop` é no-op e o contador de `deaths` sobe uma vez a mais. É consequência aceita.

### `core/world.py:_ship_die` com dois branches

A função de morte agora ramifica:

```python
def _ship_die(self, ship: Ship) -> None:
    pid = ship.player_id
    self.events.append("ship_explosion")

    if self.deathmatch:
        self.deaths[pid] = self.deaths.get(pid, 0) + 1
        self.ships.pop(pid, None)
        self.respawning[pid] = Countdown(C.RESPAWN_DELAY)
        return

    # Single-player: respawn-in-place with a life consumed.
    self.lives[pid] = self.lives[pid] - 1
    ship.pos.xy = (C.WORLD_WIDTH / 2, C.WORLD_HEIGHT / 2)
    ship.vel.xy = (0, 0)
    ship.angle = -90.0
    ship.invuln.reset(C.SAFE_SPAWN_TIME)

    if all(v <= 0 for v in self.lives.values()):
        self.game_over = True
```

O evento `ship_explosion` é emitido em ambos os modos — single-player toca o som de explosão local, deathmatch transmite via `world.events` para futuro consumo de áudio em rede (não está em F3). O resto bifurca: deathmatch incrementa deaths, tira do dict, agenda respawn. Single-player decrementa lives, reposiciona no centro, checa game over.

A reposição manual no branch single-player ocorre **no objeto que já existe** (`ship.pos.xy = (...)`). É o comportamento exato da F1, intencionalmente preservado. O branch deathmatch troca por uma nova instância de `Ship` quando o respawn dispara — uma decisão deliberada (a Ship velha some, o estado da Ship velha não interessa).

### `core/world.py:_update_respawns` e `_respawn_player`

O ciclo de vida do timer:

```python
def _update_respawns(self, dt: float) -> None:
    for pid, timer in list(self.respawning.items()):
        if timer.tick(dt):
            self._respawn_player(pid)
            self.respawning.pop(pid, None)

def _respawn_player(self, pid: PlayerId) -> None:
    temp = Ship(pid, Vec(0, 0))
    pos = self._find_safe_hyperspace_pos(temp)
    ship = Ship(pid, pos)
    ship.invuln.reset(C.SAFE_SPAWN_TIME)
    self.ships[pid] = ship
```

`_update_respawns` é chamado dentro de `World.update`, junto com os outros loops de timer. O `list(self.respawning.items())` é defensivo — modificar o dict durante a iteração causa `RuntimeError`. O `Countdown.tick(dt)` retorna `True` no tick em que o tempo esgota; aí o método para o ciclo (`pop` do dict) e instancia a nave nova com invuln pulsando.

O `temp` em `_respawn_player` é só descartável. A nave criada em seguida (linha 4) é a que vai pra `world.ships[pid]`. O `temp` foi necessário porque `_find_safe_hyperspace_pos` espera receber uma `Ship` para ler o raio. Refatorar a assinatura para receber `radius` seria mais limpo mas tocaria o site de hyperspace também — duas mudanças por uma. Adiamos.

### `server/protocol.py:world_to_snapshot` com os campos novos

O serializador ganhou três campos novos e o parâmetro `names`:

```python
def world_to_snapshot(world, names=None):
    return {
        ...
        "deaths": {str(pid): n for pid, n in world.deaths.items()},
        "respawning": [
            {"player_id": pid, "remaining": cd.remaining}
            for pid, cd in world.respawning.items()
        ],
        "events": [
            {"kind": kind, "x": pos.x, "y": pos.y}
            for kind, pos in world.particle_events
        ],
        "names": {str(pid): name for pid, name in (names or {}).items()},
        ...
    }
```

`deaths` é dict (igual a `scores` e `lives`). `respawning` é lista de objetos — escolha consciente para emparelhar bem com JSON, onde objetos com chaves dinâmicas exigem `str(pid)` e listas de objetos lêem natural. `events` é lista pura. `names` é dict — segue o padrão dos outros agregados por pid.

O parâmetro `names` é opcional. Os testes da F2 que chamam `world_to_snapshot(world)` direto continuam funcionando; o servidor passa `names=self._names_by_player_id` explicitamente. Em `tests/test_protocol.py:test_event_constant_removed_from_protocol` há um guard que valida a remoção da constante `EVENT` — se alguém tentar recolocar, o teste vermelha.

### `multiplayer/snapshot.py` ganha o reverso

A função `snapshot_to_world` agora lê os campos novos:

```python
world.deaths = {int(pid): n for pid, n in snap.get("deaths", {}).items()}
world.respawning = {
    int(entry["player_id"]): Countdown(entry["remaining"])
    for entry in snap.get("respawning", [])
}
world.names = {int(pid): name for pid, name in snap.get("names", {}).items()}
...
# Particles are spawned locally from events.
for ev in snap.get("events", []):
    world._spawn_particles(Vec(ev["x"], ev["y"]), ev["kind"])
```

`.get(..., default)` em vez de `snap[...]` porque os campos são adições back-compat: um snapshot sem `events` (vindo de testes mais antigos ou de um servidor mais velho) continua decodificando sem crashar. O Countdown é recriado com o `remaining` que o servidor mandou.

A parte interessante é a última: o cliente chama `world._spawn_particles` exatamente como o servidor chamou. O método é o mesmo arquivo, mesmo código, mesma definição de `PARTICLE_ASTEROID / PARTICLE_UFO / PARTICLE_SHIP`. O servidor decide "uma explosão de asteroide aqui", o cliente, ao receber o evento, decide a forma — exatamente como a regra da F2 já dizia. A diferença é que agora a entrega é dentro do mesmo pacote de snapshot.

### `multiplayer/hud.py` com funções puras

O coração testável do HUD:

```python
def scoreboard_lines(world, local_player_id):
    sorted_pids = sorted(world.scores.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = []
    for pid, score in sorted_pids:
        marker = "> " if pid == local_player_id else "  "
        name = world.names.get(pid, f"P{pid}")[:_NAME_WIDTH]
        deaths = world.deaths.get(pid, 0)
        timer = world.respawning.get(pid)
        status = f"RESPAWN {timer.remaining:.1f}s" if timer is not None else ""
        lines.append(f"{marker}{name:<{_NAME_WIDTH}} {score:>6} D{deaths:02d} {status}".rstrip())
    return lines
```

Ordenação por `(-score, pid)` é o truque idiomático: tupla com sinal negativo no primeiro elemento faz Python ordenar score descendente; pid ascendente desempata. O `[:10]` no nome protege contra apelidos maliciosos longos. O `.rstrip()` no fim remove o espaço trailing quando o jogador não está em respawn.

`draw_scoreboard` é o casamento com pygame:

```python
def draw_scoreboard(screen, font, world, local_player_id, color):
    lines = scoreboard_lines(world, local_player_id)
    if not lines:
        return
    max_w = max(font.size(line)[0] for line in lines)
    x = screen.get_width() - max_w - _PADDING
    y = _PADDING
    for line in lines:
        label = font.render(line, True, color)
        screen.blit(label, (x, y))
        y += font.get_height() + _LINE_GAP
```

A largura é calculada na hora porque o nome pode variar — sem hardcode de "vai caber em 300px". O ponto âncora é o canto superior direito (`screen.get_width() - max_w - padding`).

### `server/main.py` rastreia nomes

O `_handshake` retornou de `int | None` para `tuple[int, str] | None`:

```python
async def _handshake(self, ws):
    ...
    player_id = self._next_player_id
    self._next_player_id += 1

    raw_name = msg["data"].get("name", "")
    name = (raw_name if isinstance(raw_name, str) else "").strip()[:16]
    if not name:
        name = f"P{player_id}"

    await ws.send(envelope(WELCOME, self.tick, 0, {"player_id": player_id}))
    return player_id, name
```

Sanitiza o nome: aceita só `str`, faz `strip()` para tirar espaços nas pontas, corta em 16 caracteres, e cai em `P{pid}` se o resultado é vazio. O cleanup no `finally` do `_handle_connection` adicionou `self._names_by_player_id.pop(player_id, None)` e `self.world.respawning.pop(player_id, None)` e `self.world.deaths.pop(player_id, None)`. Sair do server limpa tudo.

## 4. Exercícios e referências

### Exercícios

1. **Score variável por wave.** Mude `FRAG_SCORE` para virar uma função: `frag_score_for(wave)` que retorne `100 * max(1, wave // 2)`. Onde fica essa função? Como evitar que ela afete single-player (que não tem deathmatch)? Quais testes precisam atualizar? Dica: o ponto único de leitura é o `score_deltas[bullet.owner_id] += ...` em `_bullets_vs_ships`. Mover para `core/config.py` como callable é uma opção; passar via `World` é outra.

2. **Espectador.** Faça o jogador morto entrar em "modo espectador" durante os 3s de respawn em vez de só sumir da tela. A câmera precisa ficar fixa no último ponto de morte (ou seguir outro jogador automaticamente). Que campo precisa entrar no snapshot? (Pista: o `respawning` já tem `player_id`; falta a câmera do espectador saber onde olhar.) Onde mora a lógica de câmera espectadora — em `multiplayer/player.py` ou em `client/camera.py`?

3. **Medir bandwidth do snapshot com N jogadores.** Use o exercício 2 da F2 como base (`len(envelope_string)` por broadcast somado). Conecte 1, 2, 4, 8 clientes idle (use Python para abrir várias conexões simulando handshake sem render). Reporte: bytes/s por cliente em cada cenário. A 30 Hz de broadcast e 8 clientes, qual o consumo total de banda do servidor? Compare com o limite de uma LAN Wi-Fi típica (~50 Mbps). Quando full-state JSON começa a doer?

4. **Por que `events` no snapshot e não num canal separado.** Repensar a decisão. Que cenário concreto faria a separação valer a pena? Liste pelo menos três. Pista: pense em replay, em anti-cheat, em UDP com perda controlada, em jogos com event log persistente para análise pós-partida.

5. **Auto-kill literal.** Mude o filtro de `_bullets_vs_ships` para *permitir* auto-kill (remova o `if bullet.owner_id == ship.player_id: continue`). Jogue um pouco. Por que o jogo fica injogável? O `BULLET_SPAWN_OFFSET` em `core/entities.py:Ship._try_fire` resolve completamente? Por que ou por que não? (Resposta esperada: a bullet sai à frente da nave, mas a nave continua acelerando atrás da bullet com `SHIP_THRUST > BULLET_SPAWN_OFFSET / SHIP_FIRE_RATE` em alguns regimes, e o teste de colisão por raio agarra de volta.)

### Referências

- **Glenn Fiedler, *State Synchronization*** ([gafferongames.com](https://gafferongames.com/post/state_synchronization/)). A teoria por trás de "snapshot full-state vs delta vs event-based" é dele. A F3 sustenta o full-state; o autor descreve quando cada abordagem é a certa.
- **Tom Forsyth, *Networking for Game Programmers*** (capítulo em livros coletivos como *Game Programming Gems*). Aborda PvP determinístico, autoridade, anti-cheat. Útil para entender o motivo de `_bullets_vs_ships` rodar só no servidor (e nunca no cliente).
- **Quake III source code** ([github.com/id-Software/Quake-III-Arena](https://github.com/id-Software/Quake-III-Arena)). Para deathmatch real com respawn, frag count e scoreboard, o `q3_ui` e o `game/g_combat.c` continuam sendo leitura clássica. Mostra o respawn de 1.7s, a invulnerabilidade pós-respawn (3s), e o sistema de Player_Killed.
- **Discussões sobre "respawn duration" em Reddit/Game Design SE.** Pesquise "deathmatch respawn timer" — a faixa entre 1s e 5s aparece em quase todo jogo de tiro, e o número está sempre justificado pelo ritmo do mapa.

## 5. Para a próxima fase

A F4 vai fechar o ciclo da partida. As peças que ela vai mexer:

- **Match start.** Hoje a partida começa quando um cliente conecta. A F4 vai introduzir "match início quando ≥ 2 jogadores conectados" como decisão default. O servidor precisa de uma fase de lobby antes de simular o `World`.
- **Match end.** Vai entrar timer (3 minutos) e frag limit (10 frags). O primeiro a chegar termina a partida. O snapshot vai ganhar `time_remaining` e `frag_limit`. A mensagem `match_end` vai entrar com `{"winner_id", "scores"}`.
- **Espectador.** Quando a partida acaba, todos viram espectadores. O cliente precisa de um modo onde a câmera pode escolher quem seguir. O exercício 2 desta fase já adianta isso.
- **Score reset.** Match nova zera scores. O `World.reset()` que já preserva `deathmatch` agora vai ser chamado pelo servidor entre matches.

A F3 deixa o gameplay essencial pronto. A F4 envelopa esse gameplay num formato de partida. Snapshot full-state continua adequado — o tamanho cresce com `time_remaining` e mais um par de campos, nada que justifique delta ainda. A medição do exercício 3 desta fase é o que pode ou não justificar essa decisão na hora da F4.
