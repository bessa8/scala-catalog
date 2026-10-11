# Catálogo da Scala (formato 2)

Este repositório é a fonte do catálogo da app Scala e é também o que o GitHub Pages publica em `https://bessa8.github.io/scala-catalog/`. Os dados estão na raiz (`careers/`, `tables/`, `tax/`, `rules/`, `templates/`, `professions.json`, `institutions.json`); `python3 tools/catalog.py build` valida e escreve o `manifest.json`. A app leva uma cópia: `python3 ../scala-catalog/tools/catalog.py build --src ../scala-catalog --out assets/catalog`. O formato completo está, no repositório da app, em `docs/superpowers/specs/2026-10-09-catalogo-servicos-design.md`, secção 3.

    python3 tools/catalog.py validate   # confere tudo
    python3 tools/catalog.py build      # valida e escreve o manifest.json
    python3 tools/catalog.py list       # ficheiros e datas
    python3 tools/catalog.py report     # escreve VERIFICAR.md (valores, fontes, "Por confirmar" de por-confirmar.md) para ler antes de publicar
    python3 -m unittest discover -s tools -p 'test_*.py'

Pastas: `careers/` (profissões: setores → categorias → regimes → posições), `tables/<id>.<vigência>.json` (valores em cêntimos/mês ou micros/hora), `rules/` (regras de rendimento), `templates/` (modelos de turno, limites e predefinições do rendimento), e na raiz `professions.json` (lista do ecrã "Novo serviço") e `institutions.json`.

`sources` (opcional, em tabelas e carreiras): lista de `{"title", "url" (https://), "consulted" (AAAA-MM-DD)}`. `por-confirmar.md` (opcional, não vai para o manifest nem para a app) guarda o que não se confirmou numa fonte oficial.

Textos visíveis: `{"pt": "…", "en": "…"}`, ou uma string para as duas línguas.

Publicar uma tabela nova: criar `tables/<id>.<AAAA-MM-DD>.json` (a data é a vigência), mudar `published`, correr `build`.

O `migrate_v1.py` converteu uma única vez o catálogo antigo; fica no histórico do git da app.

## Tabelas fiscais (`tax/`)

Rendimento líquido (descontos em Portugal). Ficheiros `tax/<id>.<AAAA-MM-DD>.json` (a data é a vigência), com `id` numa destas: `irs-continente`, `irs-acores`, `irs-madeira`, `contributions`, `youth`. Cada um precisa de `title` e de `sources` com pelo menos uma fonte oficial (Diário da República, Portal das Finanças, Segurança Social, CGA, ADSE, governos regionais). Taxas em pontos-base (11 % = 1100, 12,50 % = 1250); dinheiro em cêntimos.

- **`irs-*`**: `tables` com as sete tabelas `I` a `VII`, cada uma uma lista de linhas por ordem crescente de `upTo` (cêntimos de remuneração mensal; a última linha tem `upTo: null`). Cada linha tem `rate` (pontos-base), a parcela a abater como `deduction` (cêntimos) **ou** `deductionFormula {factor, limit}` (a parcela é `taxa × factor × (limit − R)`), `perDependent` (parcela por dependente, cêntimos) e `effectiveAtLimit` (taxa efetiva no limite da linha, em décimas de ponto: 5,3 % = 53). O validador recalcula `effectiveAtLimit` (sem dependentes) e rejeita diferenças acima de 0,05 pontos percentuais. `extras`: `disabledDependent {single, married1, married2}`, `spouseDisabled`, `threePlusCut` e `overtimeShare` (percentagem).
- **`contributions`**: `ss`, `cga` e `health` (subsistema de saúde), em pontos-base.
- **`youth`** (IRS Jovem): `percent`, a percentagem isenta em cada um dos 10 anos, e `ias` (valor do IAS em cêntimos).

Descontos por setor: cada setor de uma carreira pode ter `deductions: {"social": "ss" | "cga" | "none", "health": true | false}`, a sugestão inicial para quem liga o rendimento líquido. Por omissão, o setor `public` desconta Segurança Social e saúde; os outros setores só a Segurança Social. A pessoa pode mudar tudo em Definições → Descontos, e o `.escala` partilhado nunca leva estes dados.

## Rever antes de publicar (`VERIFICAR.md`)

Nada se publica sem esta revisão. `python3 tools/catalog.py report` escreve `VERIFICAR.md` (é gerado: não se edita à mão; está no git para se ver o que mudou). Tem:

1. **Tabelas**: cada tabela e vigência com todas as chaves e valores em euros, e as fontes (título, endereço, data de consulta).
2. **Carreiras**: por setor, categoria e regime, cada posição com o nível, a tabela, a chave e o valor resultante, as perguntas de suplementos, as rotações e as fontes da carreira. «Fontes da carreira: nenhuma» só é normal nas profissões sem valores (horário fixo, trabalho livre, prestação de serviços).
3. **Instituições**: concelho e feriado municipal de cada uma, com a fonte.
4. **Sem tabela**: serviços em que a pessoa escreve o salário.
5. **Por confirmar** (vem de `por-confirmar.md`): o que ficou de fora ou assenta numa leitura não confirmada (tabelas de 2027 à espera da TRU, vínculos por contrato individual, suplementos não modelados, horários habituais, etc.).

Como rever: abrir `VERIFICAR.md`, conferir cada valor com a fonte indicada (os níveis da TRU com o anexo do DL 29-A/2026 e o SRAP da DGAEP), ler a secção «Por confirmar» e decidir se algum ponto bloqueia a publicação. Se uma fonte não confirma um valor, tirá-lo do JSON e acrescentá-lo a `por-confirmar.md`. Depois de qualquer correção: `validate`, `build`, `report`, `python3 -m unittest discover -s tools -p 'test_*.py'`; os testes `flutter test` correm na app (`../Scala`), depois de copiar o catálogo (o teste «Varrimento do catálogo inteiro» abre todas as profissões, constrói um serviço por regime e preenche cada rotação).

## Como se publica

Automático: a vigia (`tools/vigia.py`, todos os dias) procura novidades nas fontes oficiais; às segundas abre uma *issue* `novidade` que dispara a rotina do Claude (`ROTINA.md`). A rotina trabalha em `bessa8/scala-catalog-propostas`, uma cópia só para ela: a app Claude do GitHub só está instalada nesse repositório (que tem as Actions desligadas), por isso a rotina nunca tem escrita no `scala-catalog`. A rotina faz push de um ramo `claude/…` para lá. A Action «Publicar» corre de hora a hora a partir do `main`, copia o `main` para o repositório das propostas, traz no máximo um ramo `claude/…` (de nome `claude/atualizacao-AAAA-MM-DD[-N]`; os outros `claude/…` apaga-os, só com um aviso no registo) por corrida, confere-o com o portão, junta-o ao `main`, publica o Pages e abre as *issues* «Publicado» e «Precisa de ti». Precisa do ambiente `propostas` com o *secret* `PROPOSTAS_CHAVE`, a chave privada de uma *deploy key* com escrita no repositório das propostas; sem a chave só avisa e não publica nada. Cria o ambiente **antes da primeira corrida** (Settings → Environments → New environment → `propostas`): em *Deployment branches and tags* escolhe *Selected branches and tags* e acrescenta só a regra de ramo `main` (sem regras de etiquetas) e não ponhas *required reviewers*, para a publicação continuar automática. Se a Action correr antes de o ambiente existir, o GitHub cria-o sem proteções. À mão: editar no `main`, correr `validate`, `build`, `report` e os testes, e fazer push; a Action «Pages» publica.

A rotina é disparada pelo endpoint `/fire` do gatilho de API da rotina (os gatilhos de GitHub da rotina só aceitam `pull_request` e `release`, e as *issues* criadas com o `GITHUB_TOKEN` não disparam outros workflows). Para isso o repositório precisa de dois *secrets*, criados no claude.ai quando a rotina ganha um gatilho de API: `ROTINA_URL` (o endereço `https://api.anthropic.com/…/fire`) e `ROTINA_TOKEN`. Sem eles a vigia só abre *issues* (sem IA) e o disparo diz «Rotina não configurada». O ambiente na nuvem da rotina tem de permitir acesso à rede aos domínios oficiais do `ROTINA.md` e a `api.github.com` (o tráfego git do GitHub passa pelo *proxy*). Para repetir uma corrida: pôr a etiqueta `rever` na *issue* (só conta se for o `bessa8`) ou correr à mão a Action «Rotina» com o número da *issue* (`gh workflow run rotina.yml -f numero=N`).

Mudar de endereço: no `manifest.json` publicado, `"movedTo": "https://novo-endereco/"` (só `https://`); na próxima consulta, as apps passam a usar o endereço novo.

### Se a publicação falhar

A Action «Publicar» abre uma *issue* `precisa-de-ti` com a ligação para a execução e diz se o ramo ficou por juntar ou se já estava juntado ao `main` (e falhou um passo seguinte: Pages, *issues* ou apagar o ramo). Para voltar a tentar, comentar na *issue* tratada («tenta outra vez») e pôr-lhe a etiqueta `rever` (se já a tiver, tirá-la e voltar a pô-la): a rotina corre outra vez e prepara um ramo novo. A *issue* diz o que aconteceu ao ramo: foi movido para `recusados/claude/…` no repositório das propostas (o normal), foi apagado (nome inválido) ou ficou onde estava (se o push falhou; nesse caso pode apagar-se ou mover-se à mão). Se falhar o espelho do `main` para o repositório das propostas (chave sem escrita, revogada ou errada), a Action abre uma só *issue* «Precisa de ti: a Action Publicar falhou», sem repetir enquanto estiver aberta. Se o `main` já tem os dados mas o Pages não saiu, basta correr à mão a Action «Pages» (`gh workflow run pages.yml`).
