# Radar de preços

Site gratuito que coleta preços sozinho a cada 3 horas, guarda o histórico e mostra tudo num gráfico.

## Colocar no ar (uma vez só)
1. Crie uma conta grátis em github.com e um repositório **público** novo (ex.: `radar-precos`).
2. Em **Add file > Upload files**, envie TODO o conteúdo desta pasta (incluindo a pasta `.github`, `docs`, `collect.py` e `wishlist.json`) e confirme com **Commit**.
3. Em **Settings > Pages**: Source = *Deploy from a branch*, Branch = `main`, pasta `/docs`, **Save**.
4. Aba **Actions**: ative os workflows se pedir e rode **Coletar preços > Run workflow** uma vez.

Seu site fica em `https://SEU-USUARIO.github.io/radar-precos/`. Depois disso é tudo automático.

## Como funciona
- `wishlist.json`: produtos, filtros, preço-alvo. Para acompanhar outro produto, copie uma linha e mude `id`, `nome`, `busca`, `deve_conter`, `excluir`, `preco_min`, `alvo`.
- `collect.py`: busca em Mercado Livre e KaBuM, filtra anúncios que não são o produto, marca preços muito abaixo da mediana como suspeitos.
- `docs/data/`: dados e histórico (o gráfico começa a partir do primeiro dia de coleta).
- Se uma loja mudar o site, o painel mostra ✗ naquela fonte e as outras seguem funcionando.
