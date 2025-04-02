Versão em Português | [English Version](READ_ME.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./static/browser-use-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="./static/browser-use.png">
  <img alt="Shows a black Browser Use Logo in light color mode and a white one in dark color mode." src="./static/browser-use.png"  width="full">
</picture>

<h1 align="center">Habilite a IA para controlar seu navegador 🤖</h1>

[![GitHub stars](https://img.shields.io/github/stars/gregpr07/browser-use?style=social)](https://github.com/gregpr07/browser-use/stargazers)
[![Discord](https://img.shields.io/discord/1303749220842340412?color=7289DA&label=Discord&logo=discord&logoColor=white)](https://link.browser-use.com/discord)
[![Cloud](https://img.shields.io/badge/Cloud-☁️-blue)](https://cloud.browser-use.com)
[![Documentation](https://img.shields.io/badge/Documentation-📕-blue)](https://docs.browser-use.com)
[![Twitter Follow](https://img.shields.io/twitter/follow/Gregor?style=social)](https://x.com/gregpr07)
[![Twitter Follow](https://img.shields.io/twitter/follow/Magnus?style=social)](https://x.com/mamagnus00)
[![Weave Badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fapp.workweave.ai%2Fapi%2Frepository%2Fbadge%2Forg_T5Pvn3UBswTHIsN1dWS3voPg%2F881458615&labelColor=#EC6341)](https://app.workweave.ai/reports/repository/org_T5Pvn3UBswTHIsN1dWS3voPg/881458615)

🌐 Browser-use é a forma mais fácil de conectar seus agentes de IA com o navegador.

💡 Veja o que os outros estão construindo e compartilhe seus projetos em nosso [Discord](https://link.browser-use.com/discord)! Quer estilo? Confira o nosso [Merch store](https://browsermerch.com).

🌤️ Pule a configuração - tente nossa <b>versão hospedada</b> para automação instantânea do navegador! <b>[Try the cloud ☁︎](https://cloud.browser-use.com)</b>.

# Início Rápido

Com pip (Python>=3.11):

```bash
pip install browser-use
```

Install Playwright:
```bash
playwright install chromium
```

Inicie seu agente:

```python
from langchain_openai import ChatOpenAI
from browser_use import Agent
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def main():
    agent = Agent(
        task="Compare the price of gpt-4o and DeepSeek-V3",
        llm=ChatOpenAI(model="gpt-4o"),
    )
    await agent.run()

asyncio.run(main())
```

Adicione suas chaves de API para o provedor que você deseja usar ao seu arquivo `.env`.

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
AZURE_ENDPOINT=
AZURE_OPENAI_API_KEY=
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
```

Para outras configurações, modelos e mais, verifique a [documentation 📕](https://docs.browser-use.com).

### Teste com uma interface do usuário

Você pode testar em [browser-use with a UI repository](https://github.com/browser-use/web-ui)

Ou simplesmente executar o exemplo do gradio:

```
uv pip install gradio
```

```bash
python examples/ui/gradio_demo.py
```

# Demonstrações

<br/><br/>

[Task](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/shopping.py): Adicione itens de supermercado ao carrinho e finalize a compra.

[![AI Did My Groceries](https://github.com/user-attachments/assets/d9359085-bde6-41d4-aa4e-6520d0221872)](https://www.youtube.com/watch?v=L2Ya9PYNns8)

<br/><br/>

Prompt: Adicione meu último seguidor do LinkedIn aos meus leads no Salesforce.

![LinkedIn to Salesforce](https://github.com/user-attachments/assets/1440affc-a552-442e-b702-d0d3b277b0ae)

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/find_and_apply_to_jobs.py): Leia meu currículo, encontre vagas de ML, salve-as em um arquivo e, em seguida, comece a se candidatar a elas em novas abas.'

https://github.com/user-attachments/assets/171fb4d6-0355-46f2-863e-edb04a828d04

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/browser/real_browser.py): Escreva uma carta no Google Docs para o papai, agradecendo a ele por tudo, e salve o documento como um PDF.

![Letter to Papa](https://github.com/user-attachments/assets/242ade3e-15bc-41c2-988f-cbc5415a66aa)

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/custom-functions/save_to_file_hugging_face.py): Procure modelos com uma licença de cc-by-sa-4.0 e organize por número de curtidas no Hugging Face, salve os 5 principais em um arquivo.

https://github.com/user-attachments/assets/de73ee39-432c-4b97-b4e8-939fd7f323b3

<br/><br/>

## Mais exemplos

Para mais exemplos, veja a pasta [examples](examples) ou junte-se ao [Discord](https://link.browser-use.com/discord) e mostre seu projeto.

# Visão

Diga ao seu computador o que fazer, e ele fará.

## Roadmap

### Agente

- [ ] Melhore a memória do agente (resumir, comprimir, RAG, etc.).
- [ ] Aprimore as capacidades de planejamento (carregar contexto específico do site)
- [ ] Reduza o consumo de tokens (prompt do sistema, estado do DOM)

### Extração DOM

- [ ] Melhore extração para seletores de datas, menus suspensos, elementos especiais
- [ ] Melhore a representação do estado para elementos de interface do usuário

### Reexecutando tarefas

- [ ] LLM como fallback
- [ ] Torne fácil definir modelos de fluxo de trabalho onde o LLM preenche os detalhes
- [ ] Retorne o script playwright a partir do agente

### Datasets

- [ ] Crie conjuntos de dados para tarefas complexas
- [ ] Compare vários modelos
- [ ] Ajuste fino de modelos para tarefas específicas.

### Experiência do Usuário

- [ ] Execução com intervenção humana
- [ ] Melhore a qualidade do GIF gerado
- [ ] Crie várias demonstrações para execução de tutoriais, inscrição em vagas de emprego, teste de QA, mídias sociais, etc.

## Contribuição

Nós amamos contribuições. Sinta-se à vontade para cogitar problemas de bugs ou solicitações. Para contribuir com a documentação, verifique a pasta `/docs`.

## Configuração Local

Para saber mais sobre a biblioteca, confira o [local setup 📕](https://docs.browser-use.com/development/local-setup).


`main` é o ramo de desenvolvimento principal com alterações frequentes. Para uso em produção, instale uma versão estável: [versioned release](https://github.com/browser-use/browser-use/releases).

---

## Cooperação

Estamos formando uma comissão para definir as melhores práticas para design de UI/UX para agentes de navegador.
Juntos, estamos explorando como o redesign de software melhora o desempenho de agentes de IA e dá a essas empresas uma vantagem competitiva ao projetar seus softwares existentes para estarem à frente da era dos agentes.

Mande um e-mail para [Toby](mailto:tbiddle@loop11.com?subject=I%20want%20to%20join%20the%20UI/UX%20commission%20for%20AI%20agents&body=Hi%20Toby%2C%0A%0AI%20found%20you%20in%20the%20browser-use%20GitHub%20README.%0A%0A) para candidatar-se a uma vaga no comitê.

## Estilo

Quer exibir seu estilo Browser-use? Confira o nossa loja: [Merch store](https://browsermerch.com). Contribuintes bons receberão um brinde de graça 👀.

## Citação

Caso você use Browser Use em sua pesquisa ou projeto, por favor cite:

```bibtex
@software{browser_use2024,
  author = {Müller, Magnus and Žunič, Gregor},
  title = {Browser Use: Enable AI to control your browser},
  year = {2024},
  publisher = {GitHub},
  url = {https://github.com/browser-use/browser-use}
}
```

 <div align="center"> <img src="https://github.com/user-attachments/assets/06fa3078-8461-4560-b434-445510c1766f" width="400"/> 
 
[![Twitter Follow](https://img.shields.io/twitter/follow/Gregor?style=social)](https://x.com/gregpr07)
[![Twitter Follow](https://img.shields.io/twitter/follow/Magnus?style=social)](https://x.com/mamagnus00)
 
 </div>

<div align="center">
Feito com ❤️ em Zurique e São Francisco
 </div>
