# 02 — Server lonely

A segunda fase tira o motor de jogo de dentro do processo do jogador. Um processo separado, sem janela e sem teclado, vira o dono da simulação. O jogador roda um cliente que conecta nesse processo, recebe o estado do mundo em pacotes JSON, manda comandos de volta, e desenha. Quando essa fase termina, o gameplay continua igual ao do single-player, mas a peça que decide o que acontece está do outro lado de um socket.

A fase entrega o caminho ponta a ponta na sua forma mais simples. Um jogador, um servidor, um mundo. Sem deathmatch ainda (vem na F3), sem fim de partida (F4), sem múltiplas salas (F5).

Os três pull requests entregues:

| PR | Branch | Conteúdo |
|---|---|---|
| #8 | `feat/server-skeleton` | Pacote `server/`, envelope JSON, handshake `hello`/`welcome`/`reject` |
| #9 | `feat/server-tick-loop` | `World` no servidor, tick 60 Hz, push de snapshot 30 Hz |
| #10 | `feat/client-player-network` | Cliente em rede + servidor passa a aplicar input |

## 1. Conceitos teóricos

### Servidor autoritativo

Num jogo monoprocesso, o jogo é o processo do jogador. Tudo acontece em memória local: o input vai direto para o motor, o motor calcula o próximo frame, o renderer pinta na tela. Não há ambiguidade sobre o "estado real", porque só existe um.

Quando a partida envolve mais de um jogador, surge a primeira pergunta de sistema distribuído: quem decide o que aconteceu? Duas famílias de resposta:

- **Peer-to-peer determinístico** (lockstep). Todos os processos rodam a mesma simulação. Cada um envia só seus inputs, os processos sincronizam os inputs por tick e simulam idêntico em todos os pontos. Funciona em jogos de estratégia. Em jogos de ação, lockstep é frágil: precisa de determinismo perfeito (mesmas operações de ponto flutuante, mesmas ordens, mesmos `random` seeds), e o tick mais lento dita o tick global.
- **Cliente-servidor autoritativo.** Um processo central guarda o estado real. Os jogadores enviam input para ele, ele simula, e devolve o estado resultante para todos. Se cliente e servidor discordam, o servidor vence.

Escolhemos cliente-servidor autoritativo. O servidor é o único processo que aplica colisões, conta score, decide quem morreu. O cliente é um terminal: lê teclas, envia comandos, recebe estado, desenha. Anti-cheat fica natural (o cliente nem sabe a posição do oponente antes do servidor mandar), o gameplay fica estável (uma simulação só), e a lógica de jogo continua morando num lugar só.

### Três relógios

A fase introduz três frequências distintas no mesmo programa, e vale separar:

- **Tickrate de simulação** (60 Hz no nosso caso). O servidor avança o `World` 60 vezes por segundo. É a granularidade da física, das colisões, dos timers.
- **Snapshot rate** (30 Hz). O servidor manda um pacote por cliente a cada 33 ms. A metade da resolução do tick é suficiente para parecer fluido na tela e custa metade do tráfego.
- **Framerate do cliente** (60 Hz). O cliente desenha 60 vezes por segundo, igual ao tick do servidor. Como recebe snapshot a 30 Hz, metade dos frames usa o snapshot mais recente sem refresh. Isso causa um leve "jitter" perceptível em monitor de 144 Hz, irrelevante na nossa LAN com olho humano.

Os três relógios precisam ser desacoplados porque cumprem propósitos diferentes. Misturar tick com framerate amarra a simulação ao hardware do cliente. Misturar tick com snapshot rate dobra a banda sem ganho visual. Cada relógio responde por uma coisa.

### Por que WebSocket

WebSocket é uma camada por cima do TCP. Você abre uma conexão HTTP, faz upgrade para WebSocket, e a partir daí o servidor e o cliente trocam mensagens nos dois sentidos sem reabrir conexão. O que pesou na escolha:

- Atravessa firewall e proxies HTTP transparentemente.
- Framing é built-in. Você manda uma mensagem, o outro lado recebe uma mensagem; sem reinventar delimitadores.
- A biblioteca [`websockets`](https://websockets.readthedocs.io/) é pequena, idiomática, e roda sobre `asyncio` da stdlib. Sem framework de aplicação grande.
- Se um dia quisermos um cliente que rode no navegador, o navegador já fala WebSocket nativo.

A alternativa óbvia seria UDP. UDP entrega cada datagrama separado, sem retransmissão, ideal para jogos com 30 ms de latência. Em LAN a vantagem some, e em troca o programador precisa cuidar de framing, ordering e perda. Para um projeto didático, o overhead conceitual de UDP não compensa.

### Por que JSON

A escolha do formato segue a mesma lógica: legibilidade primeiro, performance só com medição.

JSON tem `json.dumps` e `json.loads` na stdlib. Você abre um log de mensagens e lê a olho nu. Quando um campo está errado, o erro fica óbvio. Quando o snapshot inteiro tem 800 bytes e o cliente recebe 30 deles por segundo, o tráfego total é de 24 KB por segundo por jogador. Em LAN, ruído.

Quando algum dia o tráfego incomodar, a otimização natural é encoding binário (msgpack, protobuf) e/ou delta encoding (mandar só o que mudou desde o último snapshot). Nenhuma das duas faz sentido enquanto a medição não mostrar que JSON full-state é o gargalo.

## 2. Decisões e trade-offs

### Envelope único

Toda mensagem na fio tem o mesmo formato:

```json
{"type": "snapshot", "tick": 1234, "seq": 56, "data": {...}}
```

Quatro campos. `type` diz que tipo de mensagem é. `tick` é o tick da simulação no momento em que o servidor emitiu. `seq` é um contador por conexão, útil para detectar perda ou reordenação. `data` carrega o que aquele tipo de mensagem precisa carregar.

Um envelope único significa que `parse()` é uma função só, e o handler pode despachar por `msg["type"]`. Alternativa seria ter classes diferentes para cada tipo, com schemas formais. Adia, por enquanto. Quando o protocolo crescer ao ponto de o despacho manual ficar caótico, a hora de schemas é essa.

### Particles locais

O servidor não manda partículas no snapshot. Partículas são puramente visuais — fragmentos de explosão de asteroide, faíscas de morte de nave. Elas não interagem com nada, vivem ~1 segundo, e desaparecem.

A regra que adotamos: o servidor manda *causa*, o cliente decide *forma*. Quando um asteroide explode no servidor, o snapshot daquele tick não tem mais o asteroide e a próxima mensagem `event` carrega `"asteroid_explosion"` com a posição. O cliente recebe o evento e instancia partículas localmente.

Vantagem direta de banda: 12 partículas a 200 bytes cada são 2400 bytes que não vão pelo socket por explosão. Vantagem indireta de coesão: o servidor não precisa simular efeitos visuais.

### Reconstrução total do World no cliente

O cliente mantém um `World` local que ele nunca simula. Cada snapshot que chega substitui as listas de bullets, asteroides e UFOs por listas novas. Para ships ele reaproveita os objetos existentes (porque a câmera tem uma referência ao ship local), só sobrescrevendo posição, velocidade, ângulo e flags.

Essa estratégia tem uma consequência visível: entre dois snapshots, o ship não se move sozinho na tela. Quando o snapshot chega a 30 Hz, isso vira um leve "stutter" porque os frames intermediários redesenham na mesma posição. A correção clássica é *snapshot interpolation*: o cliente guarda os dois últimos snapshots e interpola posições entre eles, atrasando o render por uma janela de 33 ms. Ganha suavidade, paga latência.

Não fizemos. Em LAN com 1 ms de ping e RTT pequeno, o jitter é discreto e o ganho de complexidade não compensa para uma fase introdutória. Quando o jogo ficar online e o jitter aparecer, interpolation entra como PR próprio, medido contra a sensação anterior.

### Sticky inputs no servidor

O cliente manda input a 60 Hz, um por frame local. O servidor armazena o último comando recebido de cada jogador num dicionário `_inputs_by_player_id`. Em cada tick, o dicionário inteiro é passado para `world.update(dt, ...)`.

Não consumimos o dicionário depois de aplicar. Se o cliente parou de mandar (lag de rede de 200 ms, por exemplo), o servidor continua aplicando o último comando conhecido até receber um novo. Isso evita "stutter" de input quando a rede engasga.

O lado ruim: se o cliente trava sem desconectar, a nave continua acelerando para sempre. Mitigamos pela parte: na desconexão da WebSocket o slot é limpo. Para travadas sem desconexão, a F4 vai introduzir timeout de inatividade.

### Onde mora o `protocol.py`

O arquivo que define as constantes de mensagem e as funções de envelope/parse mora em `server/`. O cliente em `multiplayer/` importa `from server.protocol import ...`.

Isso é um pequeno acoplamento cruzado entre pacotes. Em projeto maduro o protocolo viraria um terceiro pacote, algo como `shared/protocol.py`, sem dependência nem do servidor nem do cliente. Não fizemos isso porque criar um pacote só com um arquivo, só porque "deveria", é o tipo de abstração prematura que a regra de overengineering proíbe. Quando aparecer um segundo módulo dentro de `server/` que o cliente precise importar, a hora de extrair `shared/` é essa.

### Opt-out para inicialização do servidor

`World.__init__` e `UFO.__init__` ganharam parâmetros booleanos com default `True`: `spawn_default_player` no World e `setup_position` no UFO. Os defaults preservam o comportamento que o single-player já dependia.

`spawn_default_player=False` faz o World começar vazio — sem o ship implícito do `LOCAL_PLAYER_ID`. O servidor usa esse modo, e o cliente em rede também (porque o servidor é quem cria as ships quando os clientes conectam). `setup_position=False` faz o UFO pular a randomização inicial de posição e velocidade — o cliente usa isso para reconstruir o UFO com exatamente a posição que o servidor mandou.

Adicionar parâmetro a um construtor que dois consumidores legítimos chamam de jeito diferente não é abstração prematura; é refletir o fato concreto de que existem dois modos. A regra costuma proibir abstração na primeira repetição; aqui já temos a segunda.

## 3. Walkthrough do código entregue

### `server/protocol.py`

[`server/protocol.py`](../../server/protocol.py) concentra as constantes de tipo, o envelope, o parse defensivo, e o serializador do mundo.

```python
HELLO = "hello"
INPUT = "input"
WELCOME = "welcome"
REJECT = "reject"
SNAPSHOT = "snapshot"
EVENT = "event"
```

As constantes são strings simples. Comparações ficam `if msg["type"] == HELLO:` em vez de `if msg["type"] == "hello":`. O tipo "se eu errei a string, IDE me avisa" sai de graça.

```python
def envelope(msg_type, tick, seq, data):
    return json.dumps({"type": msg_type, "tick": tick, "seq": seq, "data": data})


def parse(raw):
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(msg, dict): return None
    if not isinstance(msg.get("type"), str): return None
    if not isinstance(msg.get("tick"), int) or isinstance(msg.get("tick"), bool): return None
    if not isinstance(msg.get("seq"), int) or isinstance(msg.get("seq"), bool): return None
    if not isinstance(msg.get("data"), dict): return None
    return msg
```

O `parse` é defensivo de propósito. Cliente mal-intencionado ou bugado pode mandar qualquer coisa pelo socket; o servidor não deve crashar por isso. Retornar `None` em qualquer suspeita é mais barato que reagir com exception em cada handler.

O detalhe sutil é o teste extra para `bool`. Em Python, `True` é `int`, `isinstance(True, int) == True`. Sem o teste, `{"tick": true}` passaria silenciosamente — sintaticamente válido, semanticamente uma confusão entre "tick é o número 1" e "tick é true". O `or isinstance(..., bool)` rejeita.

`world_to_snapshot(world)` serializa o estado do mundo num dict que o `json.dumps` consegue mandar:

```python
def world_to_snapshot(world):
    return {
        "ships": [{"player_id": s.player_id, "x": s.pos.x, "y": s.pos.y,
                   "angle": s.angle, "vx": s.vel.x, "vy": s.vel.y,
                   "shield_active": s.shield.active,
                   "invuln_active": s.invuln.active,
                   "shield_cd_remaining": s.shield_cd.remaining}
                  for s in world.ships.values()],
        "bullets":   [...],
        "asteroids": [...],
        "ufos":      [...],
        "scores": {str(pid): s for pid, s in world.scores.items()},
        "lives":  {str(pid): l for pid, l in world.lives.items()},
        "wave": world.wave,
        "game_over": world.game_over,
    }
```

Particles fora. Polígono dos asteroides fora (o cliente regenera). Timers do ship resumidos a flags booleanas mais o cooldown do shield, porque o renderer só precisa saber se o shield está ativo, não há quanto tempo está ativo.

As chaves de `scores` e `lives` são string. Em JSON, chaves de objeto são sempre string; converter na origem deixa o formato claro e evita conversão silenciosa do `json.dumps`.

### `server/main.py`

Em [`server/main.py`](../../server/main.py), a classe `Server` orquestra três tarefas async em paralelo: aceitar conexões, avançar o tick, e fazer broadcast do snapshot.

```python
async def run(self):
    async with websockets.serve(self._handle_connection, self.host, self.port):
        print(f"asteroids server listening on ws://{self.host}:{self.port}")
        await asyncio.gather(self._tick_loop(), self._snapshot_loop())
```

O `websockets.serve` é um context manager async que mantém o listener aberto enquanto estiver dentro do `async with`. O `asyncio.gather` espera as duas tarefas para sempre. Só sai quando o programa recebe Ctrl+C.

Os dois loops são propositalmente flat:

```python
async def _tick_loop(self):
    dt = 1.0 / C.FPS
    period = 1.0 / C.FPS
    while True:
        await asyncio.sleep(period)
        self.world.update(dt, self._inputs_by_player_id)
        self.tick += 1
```

`asyncio.sleep(period)` cede o controle. Outras tarefas (snapshot, conexões novas, recv de input) rodam nesse intervalo. Quando a sleep termina, este loop atualiza o mundo e bumpa o tick.

O `_snapshot_loop` é idêntico no formato, com `period` diferente. Compensação de drift (próximo tick em tempo absoluto, não relativo ao anterior) seria mais preciso; ficou de fora para manter o corpo do loop legível. O drift acumulado em LAN não atrapalha.

O handler de conexão integra handshake + recebimento de input + cleanup:

```python
async def _handle_connection(self, ws):
    player_id = await self._handshake(ws)
    if player_id is None: return

    self.connections[player_id] = ws
    self.world.spawn_player(player_id)
    try:
        async for raw in ws:
            msg = parse(raw)
            if msg is None: continue
            if msg["type"] == INPUT:
                self._inputs_by_player_id[player_id] = dict_to_command(msg["data"])
    finally:
        self.connections.pop(player_id, None)
        self._seq_by_player_id.pop(player_id, None)
        self._inputs_by_player_id.pop(player_id, None)
        self.world.ships.pop(player_id, None)
        self.world.scores.pop(player_id, None)
        self.world.lives.pop(player_id, None)
        self.world.extra_lives_awarded.pop(player_id, None)
```

O `try/finally` garante que mesmo se o cliente fechar a conexão de repente, todos os slots do servidor ficam limpos. O `world.ships.pop` é o que faz a nave do jogador sumir para os outros (que ainda não existem na F2, mas vão existir na F3).

### `multiplayer/snapshot.py`

A função em [`multiplayer/snapshot.py`](../../multiplayer/snapshot.py) faz o cliente sair do estado anterior e entrar no estado que o servidor acabou de mandar:

```python
def snapshot_to_world(snap, world):
    _apply_ships(snap["ships"], world)
    world.bullets = [Bullet(b["owner_id"], Vec(b["x"], b["y"]),
                            Vec(b["vx"], b["vy"]))
                     for b in snap["bullets"]]
    world.asteroids = [Asteroid(Vec(a["x"], a["y"]), Vec(a["vx"], a["vy"]),
                                a["size"])
                       for a in snap["asteroids"]]
    world.ufos = [_build_ufo(u) for u in snap["ufos"]]
    world.scores = {int(pid): score for pid, score in snap["scores"].items()}
    world.lives  = {int(pid): lives for pid, lives in snap["lives"].items()}
    world.wave = snap["wave"]
    world.game_over = snap["game_over"]
```

Listas planas são recriadas inteiras. Reaproveitamento de Ship importa: a câmera segue `world.get_ship(self.player_id).pos`; se o ship fosse substituído por outro objeto a cada snapshot, a câmera teria que reapontar e o player não notaria nada errado, mas o padrão "objeto identificado por id sobrevive" é mais limpo e suporta futuras otimizações.

`_apply_ships` reusa o objeto se já existia:

```python
def _apply_ships(ships_snap, world):
    new_ships = {}
    for s in ships_snap:
        pid = s["player_id"]
        ship = world.ships.get(pid) or Ship(pid, Vec(0.0, 0.0))
        ship.pos.xy = (s["x"], s["y"])
        ship.vel.xy = (s["vx"], s["vy"])
        ship.angle = s["angle"]
        ship.shield.reset(_ACTIVE_PULSE if s["shield_active"] else 0.0)
        ship.invuln.reset(_ACTIVE_PULSE if s["invuln_active"] else 0.0)
        ship.shield_cd.reset(s["shield_cd_remaining"])
        new_ships[pid] = ship
    world.ships = new_ships
```

`_ACTIVE_PULSE = 0.1` é o truque que faz `Countdown.active` retornar `True` por um período curto após o reset, suficiente para o renderer pintar o glow do shield nos frames até o próximo snapshot. Se o servidor manda `shield_active=False`, o reset é com `0.0` e a flag fica desativada na mesma hora.

### `multiplayer/player.py`

O cliente em [`multiplayer/player.py`](../../multiplayer/player.py) roda tudo num único event loop async. Sem threads.

```python
async def run(self):
    uri = f"ws://{self.host}:{self.port}"
    async with websockets.connect(uri) as ws:
        if not await self._handshake(ws): return
        recv_task = asyncio.create_task(self._receive_loop(ws))
        try:
            await self._game_loop(ws)
        finally:
            recv_task.cancel()
```

Duas corotinas concorrentes. `_receive_loop` itera por `async for raw in ws:`, parseia, e quando vê um snapshot chama `snapshot_to_world(msg["data"], self.world)`. `_game_loop` faz o pygame e o envio de input.

O `_game_loop` substitui o `clock.tick` clássico por uma sleep baseada no tempo decorrido:

```python
async def _game_loop(self, ws):
    period = 1.0 / C.FPS
    loop = asyncio.get_running_loop()
    while self.running:
        frame_start = loop.time()
        # ... pygame events, build command, send INPUT, draw ...
        elapsed = loop.time() - frame_start
        await asyncio.sleep(max(0.0, period - elapsed))
```

O `await asyncio.sleep` é o que dá oportunidade do `_receive_loop` rodar entre frames. Sem o `await`, o `while True` monopolizaria o event loop e os snapshots nunca chegariam.

## 4. Exercícios e referências

### Exercícios

1. **Adicione um endpoint `ping`/`pong`.** No `server/protocol.py`, defina constantes `PING` e `PONG`. No handler de conexão, quando vier uma mensagem do tipo `ping`, responda imediatamente com um `pong` que carrega `{"server_tick": self.tick}` no `data`. Não esqueça do teste em `tests/test_protocol.py`. É o exercício que ensina o caminho completo: nova constante, novo handler, nova mensagem do servidor para o cliente.

2. **Meça o bandwidth do snapshot.** Instrumente o `_broadcast_snapshot` no servidor para somar `len(envelope_string)` por segundo. Imprima a cada 5 segundos. Conecte um cliente, deixe rodar 30 segundos, e veja o número. Estime quanto seriam 8 jogadores (ainda full-state, sem delta). Esse é o número que justifica ou não otimizar para binário.

3. **Argumente sobre `seq` vs `tick`.** Por que o `seq` é por conexão e o `tick` é global do servidor? Pense num cenário onde dois clientes recebem o mesmo snapshot. Como o `seq` dos dois pode ser diferente, e por que isso é desejável? E se eles recebessem o mesmo `seq`, o que mudaria? A resposta escrita cabe num parágrafo, mas pensar nela ensina mais do que escrever.

### Referências

- **RFC 6455 — The WebSocket Protocol.** A especificação. Não é leve, mas as seções 1, 4 e 5 dão o vocabulário (handshake, frame, opcode, masking) que você reencontra em qualquer biblioteca do mundo.
- **Glenn Fiedler, *Networking for Game Programmers*** ([gafferongames.com](https://gafferongames.com/categories/networked-physics/)). Série clássica que cobre desde "por que UDP em jogos" até client-side prediction. Para esta fase, o artigo "Snapshot Compression" mostra o caminho de otimização que evitamos por design.
- **Documentação da biblioteca `websockets`** ([websockets.readthedocs.io](https://websockets.readthedocs.io/)). Capítulos sobre `asyncio.server` e o ciclo de vida de uma conexão são os que importam aqui. O resto da biblioteca tem extensões (HTTP/2, compressão, proxies) que não usamos por enquanto.

## 5. Para a próxima fase

A F3 introduz o segundo jogador. As peças que vão precisar mexer:

- O servidor já aceita mais de um jogador (`MAX_PLAYERS = 8`), mas falta lógica de deathmatch: bullet do player A atinge player B → frag de A, morte de B, respawn de B 3 segundos depois numa posição segura. O `_find_safe_hyperspace_pos` que já existe vai ser reaproveitado.
- O snapshot vai ficar maior (mais ships, mais bullets), e a pergunta sobre delta encoding vai voltar. Vai voltar com número (que o exercício 2 ajuda a estimar) e não com opinião.
- O HUD do cliente vai precisar mostrar score de todos os jogadores, não só o local. Isso já está implícito no snapshot: `scores` é dict.

Nenhuma decisão da F2 trava a F3. As escolhas feitas aqui (envelope simples, full-state, sticky input, particles locais) seguem sendo as decisões certas para um deathmatch de 8 jogadores. A F4 e a F5 trazem mudanças de fluxo (timer de partida, salas paralelas) que não derrubam o desenho de comunicação que esta fase fechou.
