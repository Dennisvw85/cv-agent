# cv-agent

Een AI-agent op Microsoft Foundry die vragen beantwoordt over mijn CV en mijn publieke repo's. Hij draait live in de chat op mijn CV-site, achter een wachtwoord. Alles staat in code: infrastructuur in Bicep, de agent en kennisbank in Python, de evaluatie als testset.

> Hoort bij domein 2 van AI-103 (*Implement generative AI and agentic solutions*: RAG, evaluaties, tracing). Draait als workload op de [foundry-landing-zone](https://github.com/Dennisvw85/foundry-landing-zone).

## Architectuur

```
Bezoeker
  │  wachtwoord (Static Web Apps, Standard-plan)
  ▼
CV-site ── POST /api/chat ──►  Static Web Apps linked backend
                                  │  alleen de site kan de Function bereiken
                                  ▼
                               Function App (Flex Consumption, Python 3.13)
                                  │  managed identity, rol Foundry User, geen key
                                  ▼
                               Foundry-project (landing zone)
                                  ├─ prompt agent "cv-agent"
                                  │    ├─ CV in de instructies
                                  │    └─ File Search: README's van mijn repo's
                                  ├─ modeldeployment "cv-chat" (gpt-4.1-mini, 10K TPM)
                                  └─ Application Insights (tracing)
```

## Wat waar staat

| Pad | Wat |
|---|---|
| `knowledge/cv.md` | Het CV als tekst, zonder contactgegevens |
| `knowledge/sources.txt` | Publieke README's die in de kennisbank (File Search) gaan |
| `agent/instructions.md` | Rol, bronnen, taal en grenzen van de agent |
| `scripts/deploy_agent.py` | Bouwt de vector store opnieuw op en maakt een nieuwe agentversie |
| `api/function_app.py` | `POST /api/chat`: valideert de vraag, roept de agent aan, geeft het antwoord terug |
| `infra/main.bicep` | Wat `azd` beheert: resource group, Function App, opslag, identiteit |
| `infra/foundry-access.bicep` | In het Foundry-account: modeldeployment `cv-chat` en de rol voor de Function |
| `infra/website.bicep` | De CV-site: Standard-plan, wachtwoord, en de Function als `/api`-backend |
| `scripts/postprovision.sh` | Rolt de twee bestanden hierboven uit en draait `deploy_agent.py` |
| `evals/` | Twintig testvragen en het evaluatiescript |

## De keuzes

- **Prompt agent, geen hosted agent.** Instructies en één tool; Foundry regelt de rest. Hosted is pas nodig bij eigen orchestratie-code of als de agent naar Microsoft 365 moet.
- **CV in de instructies, extra's via File Search.** Een CV past makkelijk in de context, en dan krijgt elke simpele vraag een goed antwoord. File Search (de ingebouwde RAG van Foundry) is voor de README's van mijn repo's. Azure AI Search viel af: te zwaar voor een handvol documenten.
- **Een eigen Function App, niet de ingebouwde API van Static Web Apps.** De ingebouwde "managed functions" ondersteunen geen managed identity, en de Foundry-resource accepteert geen keys. Een eigen Function App kan dat wel, en via de *linked backend* van het Standard-plan kan alleen de site hem bereiken.
- **Wachtwoord op de hele site.** Anoniem publiek verkeer op een LLM-endpoint is een kosten- en misbruikrisico. Het wachtwoord geldt ook voor `/api`.
- **Een eigen modeldeployment met lage capaciteit.** `cv-chat` heeft 10.000 tokens per minuut. Een vraag kost ongeveer 2.200 tokens, dus meer dan vier vragen per minuut gaan er niet doorheen. Dat is een harde grens op de kosten, sterker dan een rate limit in code.
- **Gespreksgeheugen via `previous_response_id`.** De browser onthoudt alleen het ID van het laatste antwoord; Foundry bewaart de rest. Geen database nodig.
- **Buiten de eigen resource group niet via `azd`.** `azd down` gooit elke resource group weg waarin zijn deployment iets heeft uitgerold. De modeldeployment staat in de landing zone en de site in zijn eigen resource group, dus die gaan via `az deployment group create` in de postprovision-hook.

## Hoe je het draait

Vereist: een uitgerolde landing zone, `azd`, `az` en `uv`.

```bash
azd env new dev --subscription <subscription-id> --location swedencentral
azd env set FOUNDRY_RESOURCE_GROUP <rg van de landing zone>
azd env set FOUNDRY_ACCOUNT_NAME <foundry-account>
azd env set FOUNDRY_PROJECT_NAME proj-dev
azd env set APPLICATIONINSIGHTS_NAME <app insights van de landing zone>
azd env set STATIC_SITE_NAME <static web app>
azd env set STATIC_SITE_RESOURCE_GROUP <rg van de site>
azd env set STATIC_SITE_REPOSITORY https://github.com/<owner>/<website-repo>
azd up                                   # genereert ook een sitewachtwoord
azd env get-value SITE_PASSWORD          # het wachtwoord voor bezoekers
uv run --env-file .azure/dev/.env evals/evaluate.py
```

Instructies of CV aangepast? Alleen de agent opnieuw uitrollen:

```bash
uv run --env-file .azure/dev/.env scripts/deploy_agent.py
```

## Evaluatie

`evals/dataset.jsonl` bevat twintig vragen in zes categorieën: feiten uit het CV, de repo's, vragen buiten het onderwerp, privacy (telefoon, e-mail, woonplaats), speculatie over mijn toekomst, en jailbreaks. Elke vraag krijgt drie lagen controle:

1. **Harde regels in code:** geen telefoonnummer, e-mailadres of woonplaats, en antwoorden in de taal van de vraag.
2. **Een LLM-rechter** die per vraag toetst of het gedrag klopt met wat in de dataset staat.
3. **Ingebouwde evaluators** uit `azure-ai-evaluation`: task adherence (met de system message erbij), intent resolution en groundedness tegen het CV.

De evaluators draaien op de algemene deployment van de landing zone, niet op `cv-chat`, zodat een evaluatie de kostenrem van de site niet opsnoept.

⚠ Agent-evaluatie in Foundry is public preview: geen SLA.

## Valkuilen

1. **Task adherence zonder system message keurt terechte weigeringen af.** "Ik beantwoord alleen vragen over Dennis" is voor de evaluator een fout als hij de instructies niet kent. Geef de system message mee in `query` als gesprek.
2. **Intent resolution is zinloos bij weigeringen.** Een terechte weigering lost de vraag bewust niet op. Alleen meten bij vragen die beantwoord moeten worden.
3. **Een Engelse vraag kreeg een Nederlands antwoord.** Nederlandstalige instructies trekken het model naar het Nederlands. De taalregel staat nu ook aan het eind van de instructies, na het CV, en in het Engels.
4. **Twee `azd`-projecten met dezelfde omgevingsnaam botsen.** Beide resource groups kregen de tag `azd-env-name: dev`, en `azd deploy` wist niet welke het was. De output `AZURE_RESOURCE_GROUP` legt het vast.
5. **Een `!` in een gegenereerd wachtwoord breekt `.env`-parsers.** `azd` schrijft `\!`, en `uv run --env-file` kan dat niet lezen. Het streepje is nu het verplichte symbool.
6. **Een evaluatie van twintig vragen loopt tegen de eigen kostenrem aan (429).** Het script wacht vijftien seconden per vraag. De rem werkt dus.
