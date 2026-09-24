#!/bin/sh
# Noodrem voor het avatar-token. De browser krijgt een token dat 24 uur geldig is (vaste levensduur
# van managed-identity-tokens). Rollen worden per verzoek gecontroleerd, dus zonder rollen werkt een
# uitgelekt token niet meer. Gemeten op 24-9-2026: na ongeveer 5 minuten.
#
#   ./scripts/revoke-browser-access.sh           rollen intrekken
#   azd hooks run postprovision                  rollen herstellen
set -eu
PRINCIPAL=$(azd env get-value AZURE_BROWSER_PRINCIPAL_ID)
SUB=$(azd env get-value AZURE_SUBSCRIPTION_ID)
IDS=$(az role assignment list --all --subscription "$SUB" --assignee "$PRINCIPAL" --query "[].id" -o tsv)
if [ -z "$IDS" ]; then
  echo "Browser-identiteit heeft al geen rollen."
  exit 0
fi
# shellcheck disable=SC2086
az role assignment delete --subscription "$SUB" --ids $IDS
echo "Rollen van de browser-identiteit ingetrokken. De avatar werkt pas weer na: azd hooks run postprovision"
