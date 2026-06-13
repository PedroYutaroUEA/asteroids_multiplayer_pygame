# Mecânica 1 — Raio Laser

## Descrição

A mecânica de raio laser foi implementada como um power-up temporário. Ao coletar o item, a nave passa a disparar um feixe laser por tempo limitado, substituindo temporariamente o tiro comum.

O objetivo da mecânica é adicionar uma nova possibilidade ofensiva ao jogador, aumentando a variedade do combate sem remover a mecânica original de disparos.

## Base no GDD

A implementação foi baseada na proposta definida no GDD do projeto, que previa a adição de novas mecânicas ao jogo original.

O raio laser foi desenvolvido como uma extensão do sistema de combate já existente, mantendo a dinâmica principal do jogo e adicionando uma vantagem temporária ao jogador que coleta o power-up.

## Adaptação à arquitetura original

A arquitetura original do jogo foi preservada. Em vez de centralizar toda a lógica da nova mecânica em um único ponto, a implementação foi distribuída entre os módulos já existentes, respeitando suas responsabilidades.

| Módulo | Responsabilidade na mecânica |
|---|---|
| `core/` | Entidades, regras, colisões e estado do laser |
| `world/` | Spawn do power-up, ativação, duração e ciclo de vida |
| `server/` | Envio do estado autoritativo por meio dos snapshots |
| `multiplayer/` | Reconstrução do estado recebido do servidor |
| `client/` | Renderização do raio laser, power-up e indicadores visuais |
| `assets/` | Sons associados à coleta e ao disparo do laser |

## Justificativa do projeto

A mecânica foi implementada como uma extensão da arquitetura existente, sem alterar o fluxo principal do jogo. As regras da mecânica, como colisões, duração do efeito e ativação do laser, permanecem no núcleo da simulação.

No modo multiplayer, o servidor continua sendo a fonte autoritativa da partida. Por isso, as informações do power-up e do laser são enviadas aos clientes por meio dos snapshots, garantindo que todos os jogadores recebam o mesmo estado do jogo.

O cliente permanece responsável apenas pela representação visual da mecânica, como a exibição do power-up, do raio laser e dos indicadores associados. Dessa forma, a separação entre lógica do jogo, sincronização multiplayer e renderização foi mantida.


## Validação

A serialização do power-up foi validada por teste automatizado de snapshot. O teste verifica se o power-up é incluído corretamente no snapshot gerado pelo servidor e se pode ser reconstruído no mundo do cliente.

Também foi realizada validação manual em modo multiplayer local, com um servidor e dois clientes conectados na mesma sala. Durante o teste, o servidor registrou a existência do power-up no mundo e sua inclusão no snapshot enviado aos clientes.

## Evidências de preservação da arquitetura

A implementação preserva a arquitetura original do projeto porque:

- mantém a lógica da mecânica no núcleo do jogo;
- mantém o servidor como fonte autoritativa do estado da partida;
- utiliza o mecanismo de snapshots já existente para sincronização multiplayer;
- mantém o cliente limitado à renderização do estado recebido;
- adiciona a mecânica como extensão dos módulos existentes, sem reestruturar o fluxo principal da aplicação.

Assim, o raio laser foi integrado ao projeto original de forma compatível com a arquitetura definida previamente.