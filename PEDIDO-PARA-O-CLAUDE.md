# Peça ao seu Claude para instalar

Não quer mexer em arquivo? Abra o Claude Code (no terminal ou no VS Code), copie o pedido abaixo, troque o que está entre colchetes e cole.

---

## 1. Instalar

```
Quero instalar a Vega, uma página com rosto 3D para conversar com você.
O repositório é https://github.com/AIFellps/vega. Faça assim:

1. Baixe o repositório para a pasta Documentos\Vega (use git clone se tiver git;
   senão, baixe o ZIP e extraia).
2. Confira se tenho Python 3.10 ou mais novo. Se não tiver, me diga como instalar
   e espere eu avisar que terminei.
3. Rode o instalar.bat da pasta e me mostre o resultado.
4. Se alguma linha vier com [!!], me explique o motivo em palavras simples
   e resolva comigo.
5. No fim, me diga para abrir pelo atalho "Vega" na área de trabalho.

Não mexa em nada fora da pasta da Vega sem me perguntar.
```

## 2. Personalizar

```
Abra o config.json da Vega (Documentos\Vega) e mude:
- nome: [ex.: Nova]
- artigo: [a ou o]
- meu nome: [seu nome]
- saudação: [ex.: E aí, bora?]
- personalidade: [ex.: animada, explica com calma, usa exemplos]
- voz: [ex.: Francisca, Thalita ou Antonio]
- cores: [ex.: verde esperando, rosa pensando, branco falando]

Converta as cores para hexadecimal, mantenha o JSON válido e me mostre
como ficou. Depois me lembre de fechar e abrir a Vega.
```

## 3. Ver as vozes que tenho

```
Quero escolher a voz da Vega. Abra o Edge, liste as vozes em português
disponíveis no speechSynthesis e me diga os nomes. Depois troque o campo
"voz" do config.json da Vega pela que eu escolher.
```

## 4. Algo deu errado

```
A Vega não está funcionando: [descreva o que acontece].
Leia Documentos\Vega\dados\servidor.log, descubra o motivo, me explique
em uma frase e corrija. Não apague minhas conversas.
```

---

**Dica:** a Vega usa o mesmo Claude Code e as mesmas conversas. Depois de instalada, dá para pedir os ajustes pela própria Vega.
