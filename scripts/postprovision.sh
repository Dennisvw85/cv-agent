#!/bin/sh
# Draait na `azd provision`. Doet wat buiten rg-cv-agent valt, bewust niet via azd:
# azd down gooit elke resource group weg waarin zijn deployment iets heeft uitgerold.
set -eu

echo "1/3 Foundry: modeldeployment ${AZURE_AI_MODEL_DEPLOYMENT_NAME} en rechten voor de Function App"
az deployment group create \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --resource-group "$FOUNDRY_RESOURCE_GROUP" \
  --name cv-agent-foundry-access \
  --template-file infra/foundry-access.bicep \
  --parameters foundryAccountName="$FOUNDRY_ACCOUNT_NAME" \
               functionPrincipalId="$AZURE_FUNCTION_PRINCIPAL_ID" \
               modelDeploymentName="$AZURE_AI_MODEL_DEPLOYMENT_NAME" \
  --output none

echo "2/3 Kennisbank en agent"
uv run --quiet scripts/deploy_agent.py

echo "3/3 Website: Standard-plan, wachtwoord en /api-koppeling"
if [ -z "${SITE_PASSWORD:-}" ]; then
  # Nog geen wachtwoord: genereer er een die aan de eisen voldoet en bewaar hem alleen lokaal.
  # Het streepje is het verplichte symbool; geen ! of $, die breken .env-parsers.
  SITE_PASSWORD="Cv-$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)-7"
  azd env set SITE_PASSWORD "$SITE_PASSWORD"
  echo "   Nieuw wachtwoord gegenereerd. Bekijk het met: azd env get-value SITE_PASSWORD"
fi
az deployment group create \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --resource-group "$STATIC_SITE_RESOURCE_GROUP" \
  --name cv-agent-website \
  --template-file infra/website.bicep \
  --parameters staticSiteName="$STATIC_SITE_NAME" \
               repositoryUrl="$STATIC_SITE_REPOSITORY" \
               functionAppId="$AZURE_FUNCTION_APP_ID" \
               functionAppLocation="$AZURE_FUNCTION_LOCATION" \
               sitePassword="$SITE_PASSWORD" \
  --output none
echo "Klaar."
