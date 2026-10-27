# Segurança

O Pump Sentinel 0.1.0 é um MVP defensivo somente leitura. Não foi auditado independentemente. Não impede que um aplicativo externo movimente uma carteira; `pause_new_actions` é um sinal consultivo que uma integração revisada pode respeitar. Não envie seed phrase ou chave privada ao projeto, ao bot ou a quem oferecer ajuda.

Relate vulnerabilidades pelo recurso privado de segurança do GitHub, se habilitado pelo mantenedor. Se ele não estiver disponível, peça ao mantenedor um canal privado usando uma issue sem detalhes exploráveis. Não publique credenciais ou uma exploração funcional contra terceiros.

## Modelo de ameaças

O coletor valida estruturas e falha de modo conservador quando leituras necessárias falham. Um RPC malicioso pode fornecer dados falsos com estrutura válida; a versão atual não prova autenticidade dos dados nem compara nós independentes. `observed_at` e `data_age_seconds` medem o horário local e duração da coleta, não demonstram que o nó está sincronizado. Leituras `confirmed` não são atômicas e podem ser reorganizadas.

O bot não verifica automaticamente que um mint foi lançado na Pump.fun, pertence a um perfil ou corresponde a um símbolo. Confira os endereços por canais confiáveis. A lista de contas excluídas é uma decisão manual e pode ocultar concentração relevante. Contas de protocolo não são automaticamente reconhecidas.

O banco SQLite é um registro local, não um log imutável ou prova criptográfica. Ele contém saldos e endereços públicos que podem ser sensíveis quando vinculados a você. Ele não deve ser publicado. Arquivos do usuário, conteúdo de rede e nomes de tokens são dados, nunca instruções. O código não acessa URLs de metadados de token.

## Operação

Mantenha o processo em uma máquina online. Este pacote não implanta hospedagem 24/7. Não use um ambiente que hiberna como garantia de proteção. Reiniciar o processo restaura a linha de base SQLite; uma leitura parcial não atualiza a linha de base. Um `PAUSE` pode refletir indisponibilidade ou falso positivo, não uma acusação.

O arquivo `PAUSE` interrompe o monitor antes da próxima consulta ou durante a espera. Uma requisição já em andamento pode terminar antes da interrupção. Não é um bloqueio on-chain e não congela nem vende seus tokens.

Para apoio voluntário, confira rede, destinatário e mint antes de enviar pela sua própria carteira. Nomes como azul777 ou suhail777 não são endereços. Não há pagamento automático, promessa de rendimento ou obrigação de ressarcimento definida por este bot.
