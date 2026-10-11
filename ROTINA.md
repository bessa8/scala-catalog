# Rotina do catálogo

Este é o manual da rotina do Claude que mantém o catálogo. Corre quando abre uma *issue* com a etiqueta `novidade` (a vigia abre-a às segundas) ou `rever` (o Carlos reabre uma «Precisa de ti» com a decisão nos comentários). Segue-o à letra; em caso de dúvida, não publiques: escreve um «Precisa de ti».

## Limites

- Trata **só** as pistas da *issue* (o bloco JSON no fim do texto) e, numa `rever`, a decisão do Carlos nos comentários. Não faças pesquisas gerais na web.
- Só lês páginas destes domínios: `diariodarepublica.pt`, `files.diariodarepublica.pt`, `joram.madeira.gov.pt`, `jo.azores.gov.pt`, `info.portaldasfinancas.gov.pt`, `at.madeira.gov.pt`, `dgaep.gov.pt`, `dgert.gov.pt`, `seg-social.pt`, `cga.pt`, `adse.pt`, `acss.min-saude.pt`. Uma pista noutro domínio vai para `semAlteracoes` com o motivo «fonte fora da lista».
- Nunca fazes push para `main`, nunca mexes em *issues*, nunca editas `tools/` (incluindo `tools/aceites.json`, que só o Carlos altera), `.github/`, `ROTINA.md` nem `README.md`. Só fazes push de um ramo `claude/atualizacao-AAAA-MM-DD` (se já existir, ou se esta for a segunda corrida do dia, `-2`, `-3`…).
- Nunca crias estrutura: carreiras, regimes, posições, perguntas, regras, profissões, instituições, ou tabelas com um `id` que ainda não existe em `tables/` ou `tax/`. Nunca apagas ficheiros.
- O ramo só pode acrescentar ou alterar ficheiros `.json` em `tables/` e `tax/`, mais `manifest.json`, `VERIFICAR.md`, `por-confirmar.md` e o relatório novo. Os caminhos só usam letras, algarismos, `.`, `_`, `-` e `/`. Qualquer outra coisa faz o portão da Action recusar o ramo inteiro.

## O que conta como oficial

- **Valores e data de início** só de um diploma publicado em jornal oficial, com número e data (Diário da República, JORAM, Jornal Oficial dos Açores), ou de um documento da entidade competente que o reproduz (AT, DGAEP, DGERT, Segurança Social, CGA, ADSE, ACSS).
- **Nunca** de propostas de lei (incluindo o Orçamento do Estado antes de publicado), acordos, comunicados, notícias, consultoras ou bancos.
- A data de início (`effective`) é a que o diploma diz, mesmo que já tenha passado (efeitos retroativos). `published` é a data de hoje.

## Para cada pista

1. Abre o link e lê o título e o sumário. Liga-a a uma tabela pelo tema (`tools/vigia.json`: cada tema diz que tabelas cobre).
2. Não toca o catálogo (outro assunto, ou nada de novo face ao que já está publicado) → `semAlteracoes` com uma frase de motivo.
3. Pede estrutura nova (uma carreira muda as posições ou os níveis de forma que o mapa abaixo não cobre, um suplemento novo, uma regra de cálculo nova, uma região nova) → `precisaDeTi` com o que encontraste e as fontes.
4. É uma versão nova ou uma retificação de uma tabela que já existe → segue «Preparar uma versão».
5. O PDF é só imagem e não há outra fonte em texto → `precisaDeTi`.

## Preparar uma versão

1. Antes de começares, `git fetch origin` e cria o ramo a partir do `origin/main` atual: o portão recusa um ramo que não parta dele.
2. Copia a versão anterior da mesma tabela como modelo: as mesmas chaves, a mesma ordem, o mesmo formato. O nome é `<pasta>/<id>.<effective>.json`. Uma retificação altera o ficheiro da vigência retificada (não cria outro) e acrescenta a declaração de retificação a `sources`.
3. Preenche `effective`, `published` (hoje), os valores e `sources` (o diploma e, se houver, a segunda fonte; `consulted` = hoje).
4. **Verificação dupla:**
   - Se há duas fontes oficiais (despacho no DR + circular da AT; decreto-lei + SRAP da DGAEP), extrai os valores de cada uma para `/tmp/a.json` e `/tmp/b.json` (no formato do ficheiro) e corre `python3 tools/comparar.py /tmp/a.json /tmp/b.json` (sai com 1 se houver qualquer diferença ou chave repetida).
   - Se só há uma, pede a um subagente do modelo Haiku que extraia os mesmos valores da mesma fonte sem ver a tua extração, e compara com `comparar.py`.
   - Qualquer diferença: não publiques essa tabela; `precisaDeTi` com as diferenças.
5. Corre, por esta ordem, e tudo tem de passar:
   ```bash
   python3 tools/catalog.py validate
   python3 tools/plausivel.py --desde origin/main
   python3 -m unittest discover -s tools -p 'test_*.py'
   python3 tools/catalog.py build
   python3 tools/catalog.py report
   ```
   O `plausivel.py` falha se um valor mudar mais de 15 %, se desaparecer ou aparecer uma chave, se mudar a unidade, se a TRU deixar de crescer de nível para nível, se o salário mínimo ou o IAS descerem, se a percentagem do IRS Jovem mudar, se o conjunto de tabelas ou extras do IRS mudar, ou se houver um `id` de imposto desconhecido. Também aceita ficheiros à mão: `python3 tools/plausivel.py <ficheiros novos ou alterados>`.
   Se o `plausivel.py` se queixar e o diploma confirmar o valor (um aumento grande mas legal), não publiques essa tabela (apaga a tua versão do ramo, não a deixes lá): `precisaDeTi` a pedir ao Carlos que acrescente a `tools/aceites.json` a entrada `{"caminho": "<caminho do ficheiro>", "sha256": "<sha256 do ficheiro>"}`. Dá os dois valores no `texto` (o sha256 calcula-se com `shasum -a 256 <ficheiro>` ao ficheiro tal como o prepararias). A entrada só vale enquanto o ficheiro tiver exatamente esse sha256: o Carlos reabre a *issue* com a etiqueta `rever`, e na rodada seguinte tens de gerar o ficheiro byte a byte igual (mesmas chaves, mesma ordem, mesmo formato, `published` e `consulted` com a data da primeira corrida, que o `texto` do «Precisa de ti» também deve indicar). Se o sha256 não coincidir, o `plausivel.py` volta a falhar: pede de novo com o sha256 novo.
6. Os mapas já conhecidos (abaixo) dizem como calcular as tabelas por posição a partir da TRU.

## Mapas conhecidos

Quando sair a TRU de 2027 (`tables/tru.2027-01-01.json`), publica no mesmo ramo as versões de 2027 de `medica`, `enfermagem` e `farmaceutico`: o valor de cada chave é o valor do nível indicado na TRU de 2027.

- `enfermagem` (Decreto-Lei n.º 111/2024, anexo IV, a partir de 2027-01-01; https://files.diariodarepublica.pt/1s/2024/12/24600/0001200016.pdf): `enfermeiro-1` a `enfermeiro-11` → níveis 21, 25, 29, 33, 36, 39, 42, 45, 48, 51, 54; `especialista-1` a `especialista-10` → 26, 30, 33, 36, 39, 42, 45, 48, 51, 54; `gestor-1` a `gestor-7` → 40, 44, 48, 52, 55, 58, 60.
- `farmaceutico` (Decreto-Lei n.º 45/2025, anexo III, a partir de 2027-01-01; https://files.diariodarepublica.pt/1s/2025/03/06100/0001900025.pdf): `assistente-1` a `assistente-7` → 29, 31, 33, 35, 37, 39, 41; `assessor-1` a `assessor-6` → 40, 43, 45, 47, 49, 51; `assessor-senior-1` a `assessor-senior-5` → 50, 52, 57, 62, 67.
- `medica` (Decreto-Lei n.º 46/2025, anexos IX e X; https://diariodarepublica.pt/dr/detalhe/decreto-lei/46-2025-912653923): as mesmas chaves de `tables/medica.2026-01-01.json`; o nível de cada chave em 2027 lê-se nos anexos IX e X. Se alguma chave não tiver nível claro, publica a TRU e as outras duas e põe a `medica` em `precisaDeTi`.

Fontes destas versões: o diploma da carreira, o decreto-lei da TRU de 2027 e, quando sair, o SRAP de 2027.

## Acabar

1. Escreve o relatório `relatorios/AAAA-MM-DD.json` (hoje). Se esta for a segunda corrida do dia (ou mais), `relatorios/AAAA-MM-DD-2.json`, `-3`…, com o mesmo sufixo do ramo (`claude/atualizacao-AAAA-MM-DD-2`). O ramo acrescenta **um único** relatório novo, e não mexe em relatórios antigos.
   ```json
   {
     "issue": 12,
     "publicado": [{"caminho": "tables/tru.2027-01-01.json", "titulo": "Tabela Remuneratória Única de 2027", "vigencia": "2027-01-01", "fontes": ["Decreto-Lei n.º X/2027 — https://diariodarepublica.pt/…"]}],
     "precisaDeTi": [{"titulo": "…", "texto": "…", "fontes": ["…"]}],
     "semAlteracoes": [{"pista": "Despacho n.º 2/2027", "motivo": "subdelegação de competências"}]
   }
   ```
   - `issue` é o número da *issue* que desencadeou esta corrida (a `novidade` ou `rever` aberta); se não estiver aberta e com uma dessas etiquetas, a Action recusa-se a fechá-la.
   - Cada pista da *issue* aparece numa das três listas.
   - Cada `caminho` de `publicado` é um `.json` de `tables/` ou `tax/` que o ramo acrescenta ou altera; `vigencia` é `AAAA-MM-DD`; `fontes` é uma lista de textos.
   - Os títulos com mais de 250 caracteres são cortados: mantém-nos curtos.
2. Cria o ramo `claude/atualizacao-AAAA-MM-DD` (ver acima), faz commit de tudo (dados, `manifest.json`, `VERIFICAR.md`, relatório) e push. Mesmo sem nada para publicar, o ramo leva o relatório: é a Action «Publicar» que fecha a *issue* e abre as «Publicado» e «Precisa de ti».
3. Termina. Não esperes pela Action.
